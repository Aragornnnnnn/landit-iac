# LAN-373 원어민 표현 발음 학습용 오디오를 생성하고 immutable S3 객체로 게시한다.
#
# 표현마다 억양(locale)별로 3종을 만든다:
#   expression — 타겟 표현 음성
#   sentence   — 대표 예문 전체. 발음 판정의 대조 기준이자 "원어민 발음 듣기" 재생용
#   word       — 예문의 단어별 음성. 오류 단어 카드의 "원어민" 재생용
# 단어 음성은 문장에서 잘라내지 않고 단어 단위로 따로 생성한다 (자연스러운 단독 발음).
#
# scripts/scenario_question_audio.py(LAN-351)의 생성·업로드 방식을 따른다. 그 스크립트는
# 프로덕션에서 이미 완료된 일회성 작업이라 건드리지 않고, 필요한 부분을 가져와 발음용
# 검증으로 교체했다. 중복은 감수한다 — 두 스크립트의 생명주기가 다르다.

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile
import time
from typing import Callable, Mapping


MODEL = "deepgram/aura-2"
RESPONSE_FORMAT = "mp3"

# 발음 학습 전용 여성 음성. 시나리오 캐릭터 음성(luna/hyperion/draco)과 겹치지 않는다.
VOICE_BY_LOCALE = {
    "EN_US": "aura-2-thalia-en",
    "EN_GB": "aura-2-pandora-en",
    "EN_AU": "aura-2-theia-en",
}
SUPPORTED_LOCALES = frozenset(VOICE_BY_LOCALE)

# 생성 종류. S3 키의 한 단계로 쓰인다.
KIND_EXPRESSION = "expression"
KIND_SENTENCE = "sentence"
KIND_WORD = "word"
KINDS = (KIND_EXPRESSION, KIND_SENTENCE, KIND_WORD)

KEY_PREFIX = "content/expression-pronunciation-audio"
CACHE_CONTROL = "public, max-age=31536000, immutable"


class PermanentTtsError(RuntimeError):
    pass


class InvalidAudioResponse(RuntimeError):
    pass


class InvalidMp3Error(RuntimeError):
    pass


class AccentVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccentContrast:
    """억양이 갈리는 단어의 양자택일 선택지.

    생성된 참조 음성이 실제로 그 억양대로 발음하는지 확인하는 데 쓴다. TTS는 생성마다
    어휘 선택이 흔들려서(같은 음성이 tomato를 MAY로도 MAH로도 낸다) 재생 가능 여부만으로는
    콘텐츠 정확성을 보장할 수 없다.
    """

    word: str
    expected: str
    other: str


@dataclass(frozen=True)
class SourceAsset:
    expression_id: int
    accent_locale: str
    kind: str
    # word 종류에서만 쓰는 문장 내 순서. 나머지는 None.
    word_order: int | None
    text: str


@dataclass(frozen=True)
class SourceSnapshot:
    schema_version: int
    environment: str
    assets: tuple[SourceAsset, ...]
    contrasts: Mapping[tuple[int, str, int], AccentContrast]


@dataclass(frozen=True)
class SpeechHttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class SpeechResponse:
    body: bytes
    generation_id: str


@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float


@dataclass(frozen=True)
class GeneratedAsset:
    asset_id: str
    expression_id: int
    accent_locale: str
    kind: str
    word_order: int | None
    generation_fingerprint: str
    path: Path
    audio_byte_size: int
    audio_sha256: str
    generation_id: str
    duration_seconds: float


@dataclass(frozen=True)
class UploadObject:
    key: str
    body_path: Path | None
    body_bytes: bytes | None
    content_length: int
    content_type: str
    cache_control: str
    metadata: Mapping[str, str]
    manifest_object: bool


@dataclass(frozen=True)
class UploadPlan:
    bucket: str
    new_keys: tuple[str, ...]
    reused_keys: tuple[str, ...]
    conflict_keys: tuple[str, ...]
    objects: tuple[UploadObject, ...]

    @property
    def reused_count(self) -> int:
        return len(self.reused_keys)

    @property
    def conflict_count(self) -> int:
        return len(self.conflict_keys)


@dataclass(frozen=True)
class UploadResult:
    uploaded: int
    verified: int
    conflicts: int


def asset_id(asset: SourceAsset) -> str:
    suffix = "" if asset.word_order is None else f"-{asset.word_order}"
    return f"{asset.expression_id}/{asset.accent_locale}/{asset.kind}{suffix}"


def generation_contract(asset: SourceAsset) -> dict[str, str]:
    return {
        "model": MODEL,
        "providerVoiceId": VOICE_BY_LOCALE[asset.accent_locale],
        "text": asset.text,
        "responseFormat": RESPONSE_FORMAT,
    }


def generation_fingerprint(asset: SourceAsset) -> str:
    encoded = json.dumps(
        generation_contract(asset),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def s3_key(asset: SourceAsset, fingerprint: str) -> str:
    kind_path = asset.kind if asset.word_order is None else f"word/{asset.word_order}"
    return (
        f"{KEY_PREFIX}/{asset.expression_id}/{asset.accent_locale}/"
        f"{kind_path}/{fingerprint}.mp3"
    )


def audio_path_for(work_dir: Path, asset: SourceAsset) -> Path:
    fingerprint = generation_fingerprint(asset)
    suffix = "" if asset.word_order is None else f"-{asset.word_order}"
    return (
        work_dir
        / "mp3"
        / f"{asset.expression_id}-{asset.accent_locale}-{asset.kind}{suffix}"
        f"-{fingerprint}.mp3"
    )


def resolve_probe(which: Callable[[str], str | None] = shutil.which) -> str:
    if which("afinfo"):
        return "afinfo"
    if which("ffprobe"):
        return "ffprobe"
    raise InvalidMp3Error("MP3 validation requires afinfo or ffprobe")


def validate_mp3(
    path: Path,
    *,
    probe_runner: Callable = subprocess.run,
    probe_name: str | None = None,
) -> AudioProbe:
    if not path.is_file() or path.stat().st_size == 0:
        raise InvalidMp3Error("MP3 file is missing or empty")
    resolved_probe = probe_name or resolve_probe()
    command = [resolved_probe, str(path)]
    if resolved_probe == "ffprobe":
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    completed = probe_runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise InvalidMp3Error("MP3 decoder probe failed")
    try:
        if resolved_probe == "ffprobe":
            duration_seconds = float(completed.stdout.strip())
        else:
            match = re.search(
                r"estimated duration:\s*([0-9.]+)\s*sec", completed.stdout
            )
            if match is None:
                raise ValueError
            duration_seconds = float(match.group(1))
    except ValueError as error:
        raise InvalidMp3Error("MP3 duration must be positive") from error
    if duration_seconds <= 0:
        raise InvalidMp3Error("MP3 duration must be positive")
    return AudioProbe(duration_seconds=duration_seconds)


def request_speech(
    payload: dict,
    headers: dict,
    connect_timeout: int,
    total_timeout: int,
    *,
    connection_factory: Callable = http.client.HTTPSConnection,
) -> SpeechHttpResult:
    connection = connection_factory("openrouter.ai", timeout=connect_timeout)
    try:
        connection.connect()
        connection.sock.settimeout(total_timeout)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        connection.request(
            "POST", "/api/v1/audio/speech", body=body, headers=headers
        )
        response = connection.getresponse()
        return SpeechHttpResult(
            status=response.status,
            headers=dict(response.getheaders()),
            body=response.read(),
        )
    finally:
        connection.close()


class OpenRouterSpeechClient:
    def __init__(
        self,
        api_key: str,
        *,
        requester: Callable[[dict, dict, int, int], SpeechHttpResult] = request_speech,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._api_key = api_key
        self._requester = requester
        self._sleep = sleep
        self._jitter = jitter

    def synthesize(self, asset: SourceAsset) -> SpeechResponse:
        payload = {
            "model": MODEL,
            "input": asset.text,
            "voice": VOICE_BY_LOCALE[asset.accent_locale],
            "response_format": RESPONSE_FORMAT,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(4):
            try:
                result = self._requester(payload, headers, 10, 120)
            except OSError as error:
                if attempt == 3:
                    raise RuntimeError(
                        "OpenRouter TTS connection failed after 4 attempts"
                    ) from error
                self._sleep((2**attempt) + self._jitter())
                continue
            if result.status == 200:
                normalized = {
                    key.lower(): value for key, value in result.headers.items()
                }
                content_type = normalized.get("content-type", "").split(";", 1)[0]
                generation_id = normalized.get("x-generation-id", "").strip()
                if (
                    content_type != "audio/mpeg"
                    or not result.body
                    or not generation_id
                ):
                    raise InvalidAudioResponse(
                        "OpenRouter returned an invalid MP3 response"
                    )
                return SpeechResponse(body=result.body, generation_id=generation_id)
            # 520~524는 Cloudflare 일시 오류 — 전량 생성 실측에서 520 순단 확인
            if result.status not in {429, 500, 502, 503, 520, 521, 522, 523, 524}:
                raise PermanentTtsError(
                    f"OpenRouter TTS rejected the request with HTTP {result.status}"
                )
            if attempt == 3:
                raise RuntimeError(f"OpenRouter TTS failed with HTTP {result.status}")
            self._sleep((2**attempt) + self._jitter())
        raise RuntimeError("OpenRouter TTS retry loop ended unexpectedly")


ACCENT_CHECK_PROMPT = """Listen to the audio and focus ONLY on how the speaker
pronounces the word "{word}".

Which does it sound like?
A) {option_a}
B) {option_b}

Judge only from the audio, not from what is typical. If the word is not clearly
audible, answer "UNCLEAR".

Answer with JSON only, no markdown fences:
{"answer": "A", "heard": "<short respelling of just that word>"}"""

JUDGMENT_MODEL = "google/gemini-3.5-flash"


def request_judgment(
    payload: dict,
    headers: dict,
    connect_timeout: int,
    total_timeout: int,
    *,
    connection_factory: Callable = http.client.HTTPSConnection,
) -> SpeechHttpResult:
    connection = connection_factory("openrouter.ai", timeout=connect_timeout)
    try:
        connection.connect()
        connection.sock.settimeout(total_timeout)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        connection.request(
            "POST", "/api/v1/chat/completions", body=body, headers=headers
        )
        response = connection.getresponse()
        return SpeechHttpResult(
            status=response.status,
            headers=dict(response.getheaders()),
            body=response.read(),
        )
    finally:
        connection.close()


def check_accent_pronunciation(
    api_key: str,
    audio_path: Path,
    contrast: AccentContrast,
    *,
    requester: Callable = request_judgment,
) -> tuple[bool | None, str | None]:
    """생성된 오디오의 대조 단어가 기대 발음인지 확인한다.

    반환: (기대 발음과 일치하는지, 들린 respelling). 판별 불가면 (None, None).
    TTS는 생성마다 어휘 선택이 흔들리므로(tomato가 MAY로도 MAH로도 나온다) immutable
    게시 전에 반드시 확인한다. 열린 질문은 환각을 일으켜 양자택일만 쓴다 (LAN-373 스파이크).
    """
    import base64

    prompt = (
        ACCENT_CHECK_PROMPT.replace("{word}", contrast.word)
        .replace("{option_a}", contrast.expected)
        .replace("{option_b}", contrast.other)
    )
    audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
    payload = {
        "model": JUDGMENT_MODEL,
        "temperature": 0.0,
        "max_tokens": 1000,
        "reasoning": {"effort": "low"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_b64, "format": "mp3"},
                    },
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    result = requester(payload, headers, 10, 60)
    if result.status != 200:
        raise AccentVerificationError(
            f"judgment request failed with HTTP {result.status}"
        )
    body = json.loads(result.body.decode("utf-8"))
    raw = (body["choices"][0]["message"]["content"] or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    answer = parsed.get("answer")
    if answer not in ("A", "B"):
        return None, None
    heard = parsed.get("heard")
    return answer == "A", heard if isinstance(heard, str) else None


def _is_flap_class(contrast: AccentContrast) -> bool:
    """d/t(flap)·r 유무만 다른 대조인지 — 미국 단독 인용형은 flap을 안 하는 게 정상이다."""

    def normalize(option: str) -> str:
        inner = option
        if "「" in option:
            inner = option.split("「", 1)[1].rstrip("」")
        return inner.replace("d", "t").replace("er", "uh").replace("r", "")

    return normalize(contrast.expected) == normalize(contrast.other)


def verify_accent_pronunciations(
    snapshot: SourceSnapshot,
    work_dir: Path,
    api_key: str,
    *,
    checker: Callable = check_accent_pronunciation,
) -> list[str]:
    """억양 대조가 정의된 단어의 생성 오디오를 검사해 문제 목록을 반환한다.

    단어 단독 음성과 문장 음성을 둘 다 검사한다 — 단어 음성은 오류 카드 재생용이고
    문장 음성은 판정의 대조 기준이라 어느 쪽이 틀려도 콘텐츠 결함이다.
    """
    assets_by_id = {asset_id(asset): asset for asset in snapshot.assets}
    problems = []
    for (expression_id, locale, word_order), contrast in sorted(
        snapshot.contrasts.items()
    ):
        targets = [
            assets_by_id.get(f"{expression_id}/{locale}/{KIND_WORD}-{word_order}"),
            assets_by_id.get(f"{expression_id}/{locale}/{KIND_SENTENCE}"),
        ]
        for target in targets:
            if target is None:
                continue
            # 미국 단독 발음(인용형)은 flap을 안 하는 게 표준이라 flap류 대조를
            # 단어 음성에는 적용하지 않는다 (문장 음성은 검사 유지).
            # GB/AU는 인용형도 clear-t가 기대값이라 그대로 검사한다.
            if (
                target.kind == KIND_WORD
                and target.accent_locale == "EN_US"
                and _is_flap_class(contrast)
            ):
                continue
            audio_path = audio_path_for(work_dir, target)
            if not audio_path.is_file():
                problems.append(f"{asset_id(target)}: audio file is missing")
                continue
            matches, heard = checker(api_key, audio_path, contrast)
            if matches is None:
                problems.append(
                    f"{asset_id(target)}: '{contrast.word}' could not be judged"
                )
            elif not matches:
                problems.append(
                    f"{asset_id(target)}: '{contrast.word}' sounded like "
                    f"{heard!r}, expected {contrast.expected!r} — regenerate"
                )
    return problems


def load_source(path: Path) -> SourceSnapshot:
    """표현 JSON을 읽어 생성 대상 자산으로 펼친다.

    입력 형식:
      {"schemaVersion": 1, "environment": "production",
       "expressions": [{"expressionId": 1, "expressionText": "...",
                        "sentenceText": "...",
                        "words": [{"order": 1, "word": "There's",
                                   "accentContrast": {"EN_GB": {...}}}],
                        "accentLocales": ["EN_US", "EN_GB", "EN_AU"]}]}
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets: list[SourceAsset] = []
    contrasts: dict[tuple[int, str, int], AccentContrast] = {}

    for expression in payload["expressions"]:
        expression_id = expression["expressionId"]
        for locale in expression["accentLocales"]:
            # 패턴형 표현("be busy ~ing" 등)은 그대로 읽힐 수 없어 표현 음성을
            # 생략한다 (expressionText 미포함). 문장·단어 음성은 정상 생성한다.
            if expression.get("expressionText"):
                assets.append(
                    SourceAsset(
                        expression_id=expression_id,
                        accent_locale=locale,
                        kind=KIND_EXPRESSION,
                        word_order=None,
                        text=expression["expressionText"],
                    )
                )
            assets.append(
                SourceAsset(
                    expression_id=expression_id,
                    accent_locale=locale,
                    kind=KIND_SENTENCE,
                    word_order=None,
                    text=expression["sentenceText"],
                )
            )
            for word in expression["words"]:
                assets.append(
                    SourceAsset(
                        expression_id=expression_id,
                        accent_locale=locale,
                        kind=KIND_WORD,
                        word_order=word["order"],
                        text=word["word"],
                    )
                )
                contrast = (word.get("accentContrast") or {}).get(locale)
                if contrast:
                    contrasts[(expression_id, locale, word["order"])] = AccentContrast(
                        word=word["word"],
                        expected=contrast["expected"],
                        other=contrast["other"],
                    )

    snapshot = SourceSnapshot(
        schema_version=payload["schemaVersion"],
        environment=payload["environment"],
        assets=tuple(assets),
        contrasts=contrasts,
    )
    validate_source(snapshot)
    return snapshot


def validate_source(snapshot: SourceSnapshot) -> None:
    if snapshot.schema_version != 1:
        raise ValueError("source must use schema version 1")
    if not snapshot.assets:
        raise ValueError("source must contain at least one asset")

    unsupported = {
        asset.accent_locale
        for asset in snapshot.assets
        if asset.accent_locale not in SUPPORTED_LOCALES
    }
    if unsupported:
        raise ValueError(f"source contains an unsupported locale: {sorted(unsupported)}")

    if any(asset.kind not in KINDS for asset in snapshot.assets):
        raise ValueError("source contains an unsupported kind")
    if any(not asset.text.strip() for asset in snapshot.assets):
        raise ValueError("source contains a blank text")

    identifiers = [asset_id(asset) for asset in snapshot.assets]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("source contains a duplicate asset id")

    # 표현마다 locale별로 expression·sentence가 정확히 하나씩 있어야 한다
    counts: dict[tuple[int, str, str], int] = defaultdict(int)
    for asset in snapshot.assets:
        counts[(asset.expression_id, asset.accent_locale, asset.kind)] += 1
    for (expression_id, locale, kind), count in counts.items():
        if kind == KIND_SENTENCE and count != 1:
            raise ValueError(
                f"expression {expression_id} ({locale}) must have exactly one sentence"
            )
        if kind == KIND_EXPRESSION and count > 1:
            raise ValueError(
                f"expression {expression_id} ({locale}) must have at most one expression"
            )


def source_sha256(snapshot: SourceSnapshot) -> str:
    payload = {
        "schemaVersion": snapshot.schema_version,
        "environment": snapshot.environment,
        "assets": [
            {
                "expressionId": asset.expression_id,
                "accentLocale": asset.accent_locale,
                "kind": asset.kind,
                "wordOrder": asset.word_order,
                "text": asset.text,
            }
            for asset in sorted(snapshot.assets, key=asset_id)
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_generation_state(path: Path) -> dict[str, GeneratedAsset]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise ValueError("generation state must use schema version 1")
    return {
        item["assetId"]: GeneratedAsset(
            asset_id=item["assetId"],
            expression_id=item["expressionId"],
            accent_locale=item["accentLocale"],
            kind=item["kind"],
            word_order=item.get("wordOrder"),
            generation_fingerprint=item["generationFingerprint"],
            path=Path(item["path"]),
            audio_byte_size=item["audioByteSize"],
            audio_sha256=item["audioSha256"],
            generation_id=item["generationId"],
            duration_seconds=item.get("durationSeconds", 0.0),
        )
        for item in payload["assets"]
    }


def write_generation_state(path: Path, assets: Mapping[str, GeneratedAsset]) -> None:
    payload = {
        "schemaVersion": 1,
        "assets": [
            {
                "assetId": asset.asset_id,
                "expressionId": asset.expression_id,
                "accentLocale": asset.accent_locale,
                "kind": asset.kind,
                "wordOrder": asset.word_order,
                "generationFingerprint": asset.generation_fingerprint,
                "path": str(asset.path),
                "audioByteSize": asset.audio_byte_size,
                "audioSha256": asset.audio_sha256,
                "generationId": asset.generation_id,
                "durationSeconds": asset.duration_seconds,
            }
            for asset in sorted(assets.values(), key=lambda item: item.asset_id)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.part")
    temporary_path.write_text(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def _verified_existing_asset(
    asset: SourceAsset,
    work_dir: Path,
    state: Mapping[str, GeneratedAsset],
    probe_runner: Callable,
    probe_name: str,
) -> GeneratedAsset | None:
    existing = state.get(asset_id(asset))
    expected_path = audio_path_for(work_dir, asset)
    if (
        existing is None
        or existing.generation_fingerprint != generation_fingerprint(asset)
        or existing.path != expected_path
        or not expected_path.is_file()
        or expected_path.stat().st_size != existing.audio_byte_size
        or hashlib.sha256(expected_path.read_bytes()).hexdigest()
        != existing.audio_sha256
    ):
        return None
    try:
        probe = validate_mp3(
            expected_path, probe_runner=probe_runner, probe_name=probe_name
        )
    except InvalidMp3Error:
        return None
    return GeneratedAsset(
        asset_id=existing.asset_id,
        expression_id=existing.expression_id,
        accent_locale=existing.accent_locale,
        kind=existing.kind,
        word_order=existing.word_order,
        generation_fingerprint=existing.generation_fingerprint,
        path=existing.path,
        audio_byte_size=existing.audio_byte_size,
        audio_sha256=existing.audio_sha256,
        generation_id=existing.generation_id,
        duration_seconds=probe.duration_seconds,
    )


def _fetch_existing_s3_asset(
    bucket: str,
    asset: SourceAsset,
    work_dir: Path,
    probe_runner: Callable,
    probe_name: str,
    aws_runner: Callable,
) -> GeneratedAsset | None:
    """이미 S3에 게시된 자산이면 내려받아 재사용한다. 없으면 None.

    TTS는 재합성하면 바이트가 달라져 기존 immutable 객체와 충돌하므로, S3에 있는 키는
    합성하지 않고 원본을 내려받는다 (TTS 비용 절약 + 충돌 방지).
    """
    fingerprint = generation_fingerprint(asset)
    key = s3_key(asset, fingerprint)
    head = aws_runner(
        [
            "aws",
            "s3api",
            "head-object",
            "--bucket",
            bucket,
            "--key",
            key,
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if head.returncode != 0:
        if any(
            marker in head.stderr for marker in ("404", "Not Found", "NoSuchKey")
        ):
            return None
        raise RuntimeError(f"S3 head-object failed for key {key}")
    metadata = {
        name.lower(): str(value)
        for name, value in json.loads(head.stdout).get("Metadata", {}).items()
    }

    final_path = audio_path_for(work_dir, asset)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    fetched = aws_runner(
        [
            "aws",
            "s3api",
            "get-object",
            "--bucket",
            bucket,
            "--key",
            key,
            str(final_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if fetched.returncode != 0:
        raise RuntimeError(f"S3 get-object failed for key {key}")

    audio_bytes = final_path.read_bytes()
    audio_sha256 = hashlib.sha256(audio_bytes).hexdigest()
    remote_sha256 = metadata.get("audio-sha256")
    if remote_sha256 and remote_sha256 != audio_sha256:
        raise ValueError(f"downloaded audio sha256 mismatch for key {key}")
    probe = validate_mp3(final_path, probe_runner=probe_runner, probe_name=probe_name)
    return GeneratedAsset(
        asset_id=asset_id(asset),
        expression_id=asset.expression_id,
        accent_locale=asset.accent_locale,
        kind=asset.kind,
        word_order=asset.word_order,
        generation_fingerprint=fingerprint,
        path=final_path,
        audio_byte_size=len(audio_bytes),
        audio_sha256=audio_sha256,
        generation_id=metadata.get("generation-id") or "s3-recovered",
        duration_seconds=probe.duration_seconds,
    )


def generate_assets(
    snapshot: SourceSnapshot,
    work_dir: Path,
    *,
    client: OpenRouterSpeechClient | None = None,
    probe_runner: Callable = subprocess.run,
    probe_name: str | None = None,
    reuse_bucket: str | None = None,
    aws_runner: Callable = subprocess.run,
) -> list[GeneratedAsset]:
    resolved_probe = probe_name or resolve_probe()
    speech_client = client or OpenRouterSpeechClient(os.environ["OPENROUTER_API_KEY"])
    state_path = work_dir / "state.json"
    state = load_generation_state(state_path)
    completed: dict[str, GeneratedAsset] = {}
    pending = []
    for asset in snapshot.assets:
        existing = _verified_existing_asset(
            asset, work_dir, state, probe_runner, resolved_probe
        )
        if existing is None:
            pending.append(asset)
        else:
            completed[asset_id(asset)] = existing

    def generate_one(asset: SourceAsset) -> GeneratedAsset:
        if reuse_bucket is not None:
            fetched = _fetch_existing_s3_asset(
                reuse_bucket, asset, work_dir, probe_runner, resolved_probe, aws_runner
            )
            if fetched is not None:
                return fetched
        response = speech_client.synthesize(asset)
        final_path = audio_path_for(work_dir, asset)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(f"{final_path}.part")
        try:
            temporary_path.write_bytes(response.body)
            probe = validate_mp3(
                temporary_path, probe_runner=probe_runner, probe_name=resolved_probe
            )
            audio_sha256 = hashlib.sha256(response.body).hexdigest()
            os.replace(temporary_path, final_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        return GeneratedAsset(
            asset_id=asset_id(asset),
            expression_id=asset.expression_id,
            accent_locale=asset.accent_locale,
            kind=asset.kind,
            word_order=asset.word_order,
            generation_fingerprint=generation_fingerprint(asset),
            path=final_path,
            audio_byte_size=len(response.body),
            audio_sha256=audio_sha256,
            generation_id=response.generation_id,
            duration_seconds=probe.duration_seconds,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(generate_one, asset): asset for asset in pending}
        for future in as_completed(futures):
            generated = future.result()
            completed[generated.asset_id] = generated
            state[generated.asset_id] = generated
            write_generation_state(state_path, state)

    if pending:
        state.update(completed)
        write_generation_state(state_path, state)
    return sorted(completed.values(), key=lambda item: item.asset_id)


def verify_generated_assets(
    snapshot: SourceSnapshot,
    work_dir: Path,
    *,
    probe_runner: Callable = subprocess.run,
    probe_name: str | None = None,
) -> list[GeneratedAsset]:
    resolved_probe = probe_name or resolve_probe()
    state = load_generation_state(work_dir / "state.json")
    verified = [
        generated
        for asset in snapshot.assets
        if (
            generated := _verified_existing_asset(
                asset, work_dir, state, probe_runner, resolved_probe
            )
        )
        is not None
    ]
    if len(verified) != len(snapshot.assets):
        raise InvalidMp3Error(
            f"expected {len(snapshot.assets)} generated assets, "
            f"verified {len(verified)}"
        )
    return sorted(verified, key=lambda item: item.asset_id)


def build_manifest(
    snapshot: SourceSnapshot, generated_assets: list[GeneratedAsset]
) -> dict:
    validate_source(snapshot)
    generated_by_id = {asset.asset_id: asset for asset in generated_assets}
    if set(generated_by_id) != {asset_id(asset) for asset in snapshot.assets}:
        raise ValueError("manifest requires one generated asset per source asset")

    manifest_assets = []
    for source_asset in sorted(snapshot.assets, key=asset_id):
        generated = generated_by_id[asset_id(source_asset)]
        expected_fingerprint = generation_fingerprint(source_asset)
        if generated.generation_fingerprint != expected_fingerprint:
            raise ValueError("generated asset fingerprint mismatch")
        if (
            generated.audio_byte_size <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", generated.audio_sha256)
            or not generated.generation_id
            or generated.duration_seconds <= 0
        ):
            raise ValueError("generated asset metadata is invalid")
        manifest_assets.append(
            {
                "expressionId": source_asset.expression_id,
                "accentLocale": source_asset.accent_locale,
                "kind": source_asset.kind,
                "wordOrder": source_asset.word_order,
                "text": source_asset.text,
                "model": MODEL,
                "providerVoiceId": VOICE_BY_LOCALE[source_asset.accent_locale],
                "responseFormat": RESPONSE_FORMAT,
                "generationFingerprint": expected_fingerprint,
                "s3Key": s3_key(source_asset, expected_fingerprint),
                "audioByteSize": generated.audio_byte_size,
                "audioSha256": generated.audio_sha256,
                "durationSeconds": generated.duration_seconds,
                "openRouterGenerationId": generated.generation_id,
            }
        )

    expression_ids = {asset.expression_id for asset in snapshot.assets}
    locales = {asset.accent_locale for asset in snapshot.assets}
    return {
        "schemaVersion": 1,
        "issue": "LAN-373",
        "source": {
            "environment": snapshot.environment,
            "snapshotSha256": source_sha256(snapshot),
            "expressionCount": len(expression_ids),
            "accentLocales": sorted(locales),
            "assetCount": len(manifest_assets),
        },
        "assets": manifest_assets,
    }


def canonical_manifest_bytes(manifest: dict) -> bytes:
    return (
        json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def manifest_sha256(manifest: dict) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def verify_manifest(manifest: dict, work_dir: Path) -> None:
    if manifest.get("schemaVersion") != 1 or manifest.get("issue") != "LAN-373":
        raise ValueError("manifest must be a LAN-373 schema version 1 manifest")
    assets = manifest.get("assets", [])
    if not assets or len(assets) != manifest["source"]["assetCount"]:
        raise ValueError("manifest asset count mismatch")

    snapshot = SourceSnapshot(
        schema_version=1,
        environment=manifest["source"]["environment"],
        assets=tuple(
            SourceAsset(
                expression_id=asset["expressionId"],
                accent_locale=asset["accentLocale"],
                kind=asset["kind"],
                word_order=asset["wordOrder"],
                text=asset["text"],
            )
            for asset in assets
        ),
        contrasts={},
    )
    validate_source(snapshot)
    if source_sha256(snapshot) != manifest["source"]["snapshotSha256"]:
        raise ValueError("manifest source sha256 mismatch")

    source_by_id = {asset_id(asset): asset for asset in snapshot.assets}
    for asset in assets:
        source_asset = source_by_id[
            asset_id(
                SourceAsset(
                    expression_id=asset["expressionId"],
                    accent_locale=asset["accentLocale"],
                    kind=asset["kind"],
                    word_order=asset["wordOrder"],
                    text=asset["text"],
                )
            )
        ]
        fingerprint = asset["generationFingerprint"]
        if (
            asset["model"] != MODEL
            or asset["providerVoiceId"] != VOICE_BY_LOCALE[source_asset.accent_locale]
            or asset["responseFormat"] != RESPONSE_FORMAT
            or fingerprint != generation_fingerprint(source_asset)
        ):
            raise ValueError("manifest generation contract mismatch")
        if asset["s3Key"] != s3_key(source_asset, fingerprint):
            raise ValueError("manifest s3 key mismatch")
        audio_path = audio_path_for(work_dir, source_asset)
        if not audio_path.is_file():
            raise ValueError("manifest audio file is missing")
        audio_bytes = audio_path.read_bytes()
        if hashlib.sha256(audio_bytes).hexdigest() != asset["audioSha256"]:
            raise ValueError("audio sha256 mismatch")
        if len(audio_bytes) != asset["audioByteSize"]:
            raise ValueError("audio byte size mismatch")


def _upload_objects(manifest: dict, work_dir: Path) -> tuple[UploadObject, ...]:
    source_sha = manifest["source"]["snapshotSha256"]
    objects = [
        UploadObject(
            key=asset["s3Key"],
            body_path=audio_path_for(
                work_dir,
                SourceAsset(
                    expression_id=asset["expressionId"],
                    accent_locale=asset["accentLocale"],
                    kind=asset["kind"],
                    word_order=asset["wordOrder"],
                    text=asset["text"],
                ),
            ),
            body_bytes=None,
            content_length=asset["audioByteSize"],
            content_type="audio/mpeg",
            cache_control=CACHE_CONTROL,
            metadata={
                "source-sha256": source_sha,
                "audio-sha256": asset["audioSha256"],
                "model": asset["model"],
                "voice": asset["providerVoiceId"],
                # 재실행 시 S3에서 내려받아 재사용할 때 매니페스트 복원에 필요하다
                "generation-id": asset["openRouterGenerationId"],
            },
            manifest_object=False,
        )
        for asset in manifest["assets"]
    ]
    manifest_body = canonical_manifest_bytes(manifest)
    digest = manifest_sha256(manifest)
    objects.append(
        UploadObject(
            key=f"{KEY_PREFIX}/manifests/{digest}.json",
            body_path=None,
            body_bytes=manifest_body,
            content_length=len(manifest_body),
            content_type="application/json",
            cache_control=CACHE_CONTROL,
            metadata={"source-sha256": source_sha, "manifest-sha256": digest},
            manifest_object=True,
        )
    )
    return tuple(objects)


def _head_object(
    bucket: str, upload_object: UploadObject, aws_runner: Callable
) -> dict | None:
    completed = aws_runner(
        [
            "aws",
            "s3api",
            "head-object",
            "--bucket",
            bucket,
            "--key",
            upload_object.key,
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return json.loads(completed.stdout)
    if any(
        marker in completed.stderr for marker in ("404", "Not Found", "NoSuchKey")
    ):
        return None
    raise RuntimeError(f"S3 head-object failed for key {upload_object.key}")


def _head_matches(upload_object: UploadObject, head: dict) -> bool:
    remote_metadata = {
        key.lower(): str(value) for key, value in head.get("Metadata", {}).items()
    }
    return (
        head.get("ContentLength") == upload_object.content_length
        and head.get("ContentType") == upload_object.content_type
        and head.get("CacheControl") == upload_object.cache_control
        and remote_metadata == dict(upload_object.metadata)
    )


def _list_existing_keys(
    bucket: str, prefix: str, aws_runner: Callable
) -> set[str]:
    """prefix 아래 기존 키 전체를 한 번에 나열한다 (CLI가 페이지네이션 처리).

    수만 개 키를 개별 head-object로 확인하면 계획만 수 시간 걸리므로, 목록에 없는
    키는 head 없이 신규로 분류하고 목록에 있는 키만 head로 대조한다.
    """
    completed = aws_runner(
        [
            "aws",
            "s3api",
            "list-objects-v2",
            "--bucket",
            bucket,
            "--prefix",
            prefix,
            "--query",
            "Contents[].Key",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("S3 list-objects-v2 failed")
    keys = json.loads(completed.stdout or "null")
    return set(keys or [])


def plan_s3_upload(
    manifest: dict,
    bucket: str,
    *,
    work_dir: Path = Path("."),
    aws_runner: Callable = subprocess.run,
) -> UploadPlan:
    objects = _upload_objects(manifest, work_dir)
    existing = _list_existing_keys(bucket, KEY_PREFIX, aws_runner)
    new_keys = []
    reused_keys = []
    conflict_keys = []
    for upload_object in objects:
        if upload_object.key not in existing:
            new_keys.append(upload_object.key)
            continue
        head = _head_object(bucket, upload_object, aws_runner)
        if head is None:
            new_keys.append(upload_object.key)
        elif _head_matches(upload_object, head):
            reused_keys.append(upload_object.key)
        else:
            conflict_keys.append(upload_object.key)
    if conflict_keys:
        raise ValueError("existing object conflict: " + ", ".join(conflict_keys))
    return UploadPlan(
        bucket=bucket,
        new_keys=tuple(new_keys),
        reused_keys=tuple(reused_keys),
        conflict_keys=tuple(conflict_keys),
        objects=objects,
    )


def _put_object(
    plan: UploadPlan,
    upload_object: UploadObject,
    body_path: Path,
    aws_runner: Callable,
) -> None:
    metadata = ",".join(
        f"{key}={value}" for key, value in upload_object.metadata.items()
    )
    completed = aws_runner(
        [
            "aws",
            "s3api",
            "put-object",
            "--bucket",
            plan.bucket,
            "--key",
            upload_object.key,
            "--body",
            str(body_path),
            "--if-none-match",
            "*",
            "--content-type",
            upload_object.content_type,
            "--cache-control",
            upload_object.cache_control,
            "--metadata",
            metadata,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"S3 put-object failed for key {upload_object.key}")


def execute_s3_upload(
    plan: UploadPlan,
    *,
    execute: bool = False,
    aws_runner: Callable = subprocess.run,
) -> UploadResult:
    if not execute:
        return UploadResult(
            uploaded=0, verified=plan.reused_count, conflicts=plan.conflict_count
        )

    objects_by_key = {item.key: item for item in plan.objects}
    ordered_new_objects = sorted(
        (objects_by_key[key] for key in plan.new_keys),
        key=lambda item: item.manifest_object,
    )
    uploaded = 0
    verified = plan.reused_count
    for upload_object in ordered_new_objects:
        temporary_manifest_path = None
        body_path = upload_object.body_path
        if upload_object.body_bytes is not None:
            with tempfile.NamedTemporaryFile(
                prefix="lan-373-manifest-", suffix=".json", delete=False
            ) as temporary_file:
                temporary_file.write(upload_object.body_bytes)
                temporary_manifest_path = Path(temporary_file.name)
            body_path = temporary_manifest_path
        if body_path is None:
            raise ValueError("upload object body path is missing")
        try:
            _put_object(plan, upload_object, body_path, aws_runner)
        finally:
            if temporary_manifest_path is not None:
                temporary_manifest_path.unlink(missing_ok=True)
        head = _head_object(plan.bucket, upload_object, aws_runner)
        if head is None or not _head_matches(upload_object, head):
            raise ValueError(
                f"uploaded object verification conflict: {upload_object.key}"
            )
        uploaded += 1
        verified += 1
    return UploadResult(uploaded=uploaded, verified=verified, conflicts=0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate-source")
    validate_parser.add_argument("--source", required=True, type=Path)
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--source", required=True, type=Path)
    generate_parser.add_argument("--work-dir", required=True, type=Path)
    generate_parser.add_argument(
        "--reuse-s3-bucket",
        help="이미 이 버킷에 게시된 키는 합성하지 않고 내려받아 재사용한다",
    )
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--source", type=Path)
    verify_parser.add_argument("--manifest", type=Path)
    verify_parser.add_argument("--work-dir", required=True, type=Path)
    accent_parser = subparsers.add_parser("verify-accent")
    accent_parser.add_argument("--source", required=True, type=Path)
    accent_parser.add_argument("--work-dir", required=True, type=Path)
    build_parser = subparsers.add_parser("build-manifest")
    build_parser.add_argument("--source", required=True, type=Path)
    build_parser.add_argument("--work-dir", required=True, type=Path)
    build_parser.add_argument("--output", required=True, type=Path)
    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--manifest", required=True, type=Path)
    upload_parser.add_argument("--work-dir", required=True, type=Path)
    upload_parser.add_argument("--bucket", required=True)
    upload_parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "validate-source":
        snapshot = load_source(args.source)
        expressions = {asset.expression_id for asset in snapshot.assets}
        locales = sorted({asset.accent_locale for asset in snapshot.assets})
        print(
            f"expressions={len(expressions)}, assets={len(snapshot.assets)}, "
            f"locales={','.join(locales)}, contrasts={len(snapshot.contrasts)}, "
            f"source_sha256={source_sha256(snapshot)}"
        )
    elif args.command == "generate":
        snapshot = load_source(args.source)
        generated = generate_assets(
            snapshot, args.work_dir, reuse_bucket=args.reuse_s3_bucket
        )
        print(f"completed={len(generated)}, failed=0")
    elif args.command == "verify":
        if not args.source and not args.manifest:
            parser.error("verify requires --source, --manifest, or both")
        if args.source:
            snapshot = load_source(args.source)
            verified = verify_generated_assets(snapshot, args.work_dir)
            print(
                f"verified={len(verified)}, "
                f"total_bytes={sum(asset.audio_byte_size for asset in verified)}"
            )
        if args.manifest:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            verify_manifest(manifest, args.work_dir)
            print(
                f"manifest_assets={len(manifest['assets'])}, "
                f"manifest_sha256={manifest_sha256(manifest)}"
            )
    elif args.command == "verify-accent":
        snapshot = load_source(args.source)
        if not snapshot.contrasts:
            print("contrasts=0, problems=0 (no accent contrasts defined)")
        else:
            problems = verify_accent_pronunciations(
                snapshot, args.work_dir, os.environ["OPENROUTER_API_KEY"]
            )
            print(f"contrasts={len(snapshot.contrasts)}, problems={len(problems)}")
            for problem in problems:
                print(problem)
            if problems:
                return 1
    elif args.command == "build-manifest":
        snapshot = load_source(args.source)
        generated = verify_generated_assets(snapshot, args.work_dir)
        manifest = build_manifest(snapshot, generated)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(f"{args.output}.part")
        temporary_path.write_bytes(canonical_manifest_bytes(manifest))
        os.replace(temporary_path, args.output)
        print(
            f"assets={len(manifest['assets'])}, "
            f"manifest_sha256={manifest_sha256(manifest)}, output={args.output}"
        )
    elif args.command == "upload":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        verify_manifest(manifest, args.work_dir)
        plan = plan_s3_upload(manifest, args.bucket, work_dir=args.work_dir)
        print(
            f"new={len(plan.new_keys)}, reused={plan.reused_count}, "
            f"conflicts={plan.conflict_count}"
        )
        for key in plan.new_keys:
            print(key)
        result = execute_s3_upload(plan, execute=args.execute)
        print(
            f"uploaded={result.uploaded}, verified={result.verified}, "
            f"conflicts={result.conflicts}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
