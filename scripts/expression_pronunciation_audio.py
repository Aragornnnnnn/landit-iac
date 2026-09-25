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
import threading
import time
from typing import Callable, Iterable, Mapping, Sequence


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
DEFAULT_GENERATE_WORKERS = 4
STATE_FLUSH_INTERVAL_SECONDS = 5.0
KIND_EXPRESSION = "expression"
KIND_SENTENCE = "sentence"
KIND_WORD = "word"
KINDS = (KIND_EXPRESSION, KIND_SENTENCE, KIND_WORD)

KEY_PREFIX = "content/expression-pronunciation-audio"
CACHE_CONTROL = "public, max-age=31536000, immutable"
# LAN-351 계약과 동일한 콘텐츠 CDN. URL = base(끝 / 제거) + "/" + s3Key
# (docs/handoffs/lan-351-be-audio-urls.md)
DEFAULT_CDN_BASE_URL = "https://d19azau1un4t7r.cloudfront.net"


class PermanentTtsError(RuntimeError):
    pass


class InvalidAudioResponse(RuntimeError):
    pass


class InvalidMp3Error(RuntimeError):
    pass


class AccentVerificationError(RuntimeError):
    pass


class WordPoolReplacementUnverified(RuntimeError):
    """put은 성공했지만 게시 결과 검증이 어긋났다.

    이 경우 S3 객체는 **이미 바뀌어 있다.** 일반 실패(아무것도 쓰지 않음)와 뭉뚱그리면
    교체 키 목록에서 빠져 CloudFront 무효화 대상에서도 빠지고, 옛 소리가 계속 나간다.
    """


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
    # QA 재합성 등으로 내용이 바뀐 기존 키. --replace일 때만 채워지고 덮어쓴다.
    replace_keys: tuple[str, ...] = ()

    @property
    def reused_count(self) -> int:
        return len(self.reused_keys)

    @property
    def replace_count(self) -> int:
        return len(self.replace_keys)

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


# 표현 음성은 "hang out with"처럼 문법적으로 끝나지 않은 조각인 경우가 많다. 그대로 읽히면
# TTS가 문장을 이어가려다 다음 단어의 첫 소리를 흘려서 잡음 꼬리가 붙는다 (배치 1·2 실측:
# 조각형 표현의 19%, 그 밖의 1.3%). 같은 텍스트도 억양에 따라 붙기도 안 붙기도 해 확률적이므로,
# 어떤 텍스트가 걸릴지 고르는 대신 **끝을 알리는 부호를 항상 붙여 유발 조건을 없앤다.**
#
# 이미 문장부호로 끝나면 건드리지 않는다. 물음표로 끝나는 표현이 103개 있는데(`Have you got a
# minute?`) 마침표로 바꾸면 의문문 억양이 평서문이 된다. 재합성이 붙이는 쉼표 변형도 그대로 둬야
# 그 실험이 유지된다. 그래서 판단 기준은 "종결부호"가 아니라 "부호로 끝나는가"이고, 이 함수는
# 몇 번 적용해도 같은 결과를 낸다.
#
# 근거: 이미 꼬리가 난 51개에서 마침표 45/51 통과 vs 원문 재생성 29/51. 멀쩡한 표현 60개로는
# 마침표 46/60 vs 원문 재생성 44/60으로 차이가 없어 해롭지 않음을 확인했다 (2026-09-25).
# 이 부호로 끝나면 부르는 쪽이 이미 끝맺음을 정한 것으로 보고 손대지 않는다.
EXPLICIT_ENDINGS = (".", "?", "!", ",", ";", ":")


def speech_text(asset: SourceAsset) -> str:
    """TTS에 실제로 보낼 문자열. 생성 계약(S3 키)은 asset.text 그대로를 쓴다.

    말하는 입력과 내용 식별자를 분리한다. 같은 (억양, 원문)은 항상 같은 입력을 만들므로
    키와 소리의 대응은 그대로 유지된다.

    :param asset: 합성할 자산
    :return: 표현 음성이면서 부호로 끝나지 않으면 마침표를 붙인 텍스트, 그 밖에는 원문 그대로
    """
    if asset.kind != KIND_EXPRESSION:
        return asset.text
    stripped = asset.text.rstrip()
    if not stripped or stripped.endswith(EXPLICIT_ENDINGS):
        return asset.text
    return stripped + "."


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


WORD_POOL_SCHEMA_VERSION = 2
WORD_POOL_ISSUE = "LAN-475"
WORD_POOL_SEGMENT = "word"
# 풀 QA가 재합성으로 교체한 객체에 남기는 표시. 교체본은 원본 옛 키와 내용이 달라지는 것이
# 정상이므로, 백필의 원본 대조가 이걸 보고 불일치를 오탐으로 올리지 않는다.
WORD_POOL_REPLACED_MARKER = "replaced-by"
WORD_POOL_REPLACED_VALUE = "lan-475-pool-qa"

LEGACY_WORD_KEY_PATTERN = re.compile(
    rf"^{re.escape(KEY_PREFIX)}/(?P<expression_id>\d+)/(?P<accent_locale>[A-Z]{{2}}_[A-Z]{{2}})"
    r"/word/(?P<word_order>\d+)/(?P<fingerprint>[0-9a-f]{64})\.mp3$"
)
SHARED_WORD_KEY_PATTERN = re.compile(
    rf"^{re.escape(KEY_PREFIX)}/{WORD_POOL_SEGMENT}"
    r"/(?P<accent_locale>[A-Z]{2}_[A-Z]{2})/(?P<fingerprint>[0-9a-f]{64})\.mp3$"
)


def shared_word_key(accent_locale: str, fingerprint: str) -> str:
    """(억양, 해시) 하나가 차지하는 공용 단어 키를 돌려준다.

    표현 id 자리에 숫자가 아닌 `word`가 들어가므로 옛 키와 섞이지 않는다.

    :param accent_locale: 억양 로케일 (EN_US·EN_GB·EN_AU)
    :param fingerprint: 생성 계약 sha256
    :return: `content/expression-pronunciation-audio/word/{억양}/{해시}.mp3`
    """
    return f"{KEY_PREFIX}/{WORD_POOL_SEGMENT}/{accent_locale}/{fingerprint}.mp3"


def synthesis_unit_id(asset: SourceAsset) -> str:
    """한 번만 합성하면 되는 단위의 id.

    단어는 (억양, 해시)마다 하나다 — 같은 억양의 같은 단어는 표현이 달라도 같은 소리이고,
    LAN-475에서 공용 자리 하나로 모았다. 문장·표현은 텍스트가 표현마다 달라 중복이 없으므로
    지금처럼 자산 하나가 곧 단위다.

    단어 단위 id는 `word/`로 시작하고 자산 id는 표현 번호(숫자)로 시작하므로 섞이지 않는다.

    :param asset: 소스 자산
    :return: 같은 소리를 내는 자산들이 공유하는 id
    """
    if asset.kind != KIND_WORD:
        return asset_id(asset)
    return f"{KIND_WORD}/{asset.accent_locale}/{generation_fingerprint(asset)}"


def dedupe_synthesis_units(assets: Iterable[SourceAsset]) -> list[SourceAsset]:
    """자산 목록에서 중복을 합쳐 단위마다 대표 하나씩 돌려준다.

    LAN-471 배치는 단어 16,167개를 합성했지만 서로 다른 것은 3,843개뿐이었다. 대표는
    자산 id가 가장 앞선 것으로 고정해 같은 입력이면 항상 같은 결과가 나오게 한다.

    :param assets: 소스 자산 (필터를 먼저 적용한 부분집합이어도 된다)
    :return: 단위 id 순으로 정렬된 대표 자산
    """
    representatives: dict[str, SourceAsset] = {}
    for asset in sorted(assets, key=asset_id):
        representatives.setdefault(synthesis_unit_id(asset), asset)
    return [representatives[key] for key in sorted(representatives)]


def synthesis_unit_members(
    assets: Iterable[SourceAsset],
) -> dict[str, list[SourceAsset]]:
    """단위 id → 그 소리를 쓰는 자산 목록. 불합격이 어느 표현에 걸리는지 되짚을 때 쓴다."""
    members: dict[str, list[SourceAsset]] = defaultdict(list)
    for asset in sorted(assets, key=asset_id):
        members[synthesis_unit_id(asset)].append(asset)
    return dict(members)


def synthesis_units(snapshot: SourceSnapshot) -> list[SourceAsset]:
    """스냅샷 전체의 합성 단위 대표."""
    return dedupe_synthesis_units(snapshot.assets)


def s3_key(asset: SourceAsset, fingerprint: str) -> str:
    """자산이 차지하는 S3 키. 단어는 표현과 무관한 공용 자리를 가리킨다."""
    if asset.kind == KIND_WORD:
        return shared_word_key(asset.accent_locale, fingerprint)
    return (
        f"{KEY_PREFIX}/{asset.expression_id}/{asset.accent_locale}/"
        f"{asset.kind}/{fingerprint}.mp3"
    )


def audio_path_for(work_dir: Path, asset: SourceAsset) -> Path:
    """작업 폴더에서 이 자산의 소리를 담는 파일. 같은 단위는 같은 파일을 쓴다.

    파일 이름을 단위 id에서 만들어 S3 키와 1:1로 맞춘다. 단어 하나를 여러 표현이 쓰면
    파일도 하나다 — 예전처럼 표현마다 따로 두면 같은 소리를 여러 번 만들고 검사하게 된다.
    """
    return work_dir / "mp3" / (synthesis_unit_id(asset).replace("/", "-") + ".mp3")


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
            # 생성 계약(키)은 원문 기준이고, 말하는 입력만 speech_text가 다듬는다.
            "input": speech_text(asset),
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
    # OpenRouter는 일시 장애 때 200이면서 choices가 없거나 null인 몸통을 줄 수 있다.
    # HTTP 실패와 동일하게 fail-closed로 처리해 검증이 조용히 오판하지 않게 한다.
    try:
        body = json.loads(result.body.decode("utf-8"))
        raw = (body["choices"][0]["message"]["content"] or "").strip()
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise AccentVerificationError(
            f"judgment response body is malformed: {type(error).__name__}"
        ) from error
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
    # 2: 항목의 키가 자산 id에서 합성 단위 id로 바뀌었다 (LAN-561). 옛 파일은 받지 않는다 —
    # 자산별로 읽으면 같은 단어의 형제 행이 낡은 sha를 들고 있어 재합성 판정이 어긋난다.
    if payload.get("schemaVersion") != 2:
        raise ValueError("generation state must use schema version 2")
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
        "schemaVersion": 2,
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
    existing = state.get(synthesis_unit_id(asset))
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
    """이미 S3에 게시된 소리면 내려받아 재사용한다. 없으면 None.

    단어는 (억양, 단어) 공용 자리를 본다. 그래서 새 배치라도 이미 만들어 둔 단어는
    합성하지 않는다 — LAN-471 배치 기준 단어 16,167개 중 새로 필요한 것은 984개뿐이었다.
    재합성하면 바이트가 달라져 기존 immutable 객체와 충돌하므로 내려받는 쪽이 맞기도 하다.

    :return: 내려받아 검증한 자산, 또는 S3에 없으면 None
    :raises ValueError: 내려받은 파일의 sha256이 S3 메타데이터와 다를 때
    """
    fingerprint = generation_fingerprint(asset)
    key = s3_key(asset, fingerprint)
    head = _head_key(bucket, key, aws_runner)
    if head is None:
        return None
    metadata = {
        name.lower(): str(value) for name, value in head.get("Metadata", {}).items()
    }

    # 여러 자산이 같은 단위를 공유하므로 최종 경로에 직접 쓰면 서로의 반쪽 파일을 읽을 수
    # 있다. 임시 파일에 받아 제자리 교체한다.
    final_path = audio_path_for(work_dir, asset)
    _get_object(bucket, key, final_path, aws_runner)

    audio_bytes = final_path.read_bytes()
    audio_sha256 = hashlib.sha256(audio_bytes).hexdigest()
    remote_sha256 = metadata.get("audio-sha256")
    if remote_sha256 and remote_sha256 != audio_sha256:
        raise ValueError(f"downloaded audio sha256 mismatch for key {key}")
    probe = validate_mp3(final_path, probe_runner=probe_runner, probe_name=probe_name)
    return GeneratedAsset(
        asset_id=synthesis_unit_id(asset),
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
    max_workers: int = DEFAULT_GENERATE_WORKERS,
    state_flush_interval_seconds: float = STATE_FLUSH_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    progress: Callable[[str], None] = lambda message: None,
) -> list[GeneratedAsset]:
    resolved_probe = probe_name or resolve_probe()
    speech_client = client or OpenRouterSpeechClient(os.environ["OPENROUTER_API_KEY"])
    state_path = work_dir / "state.json"
    state = load_generation_state(state_path)
    completed: dict[str, GeneratedAsset] = {}
    pending = []
    # 같은 소리를 여러 번 만들지 않도록 단위마다 한 번만 돈다.
    for asset in synthesis_units(snapshot):
        existing = _verified_existing_asset(
            asset, work_dir, state, probe_runner, resolved_probe
        )
        if existing is None:
            pending.append(asset)
        else:
            completed[synthesis_unit_id(asset)] = existing

    counts = {"reused": 0, "synthesized": 0}
    counts_lock = threading.Lock()

    def generate_one(asset: SourceAsset) -> GeneratedAsset:
        if reuse_bucket is not None:
            fetched = _fetch_existing_s3_asset(
                reuse_bucket, asset, work_dir, probe_runner, resolved_probe, aws_runner
            )
            if fetched is not None:
                with counts_lock:
                    counts["reused"] += 1
                return fetched
        response = speech_client.synthesize(asset)
        with counts_lock:
            counts["synthesized"] += 1
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
            # 단어는 여러 표현이 공유하므로 expression_id·word_order는 대표의 출처 기록일 뿐이다.
            asset_id=synthesis_unit_id(asset),
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

    # state.json은 자산마다 전체를 다시 쓰므로(수만 건이면 한 번에 수 MB) 매 완료마다
    # 쓰면 메인 스레드가 병목이 된다. 일정 간격으로만 내려쓰고, 실패로 빠져나갈 때도
    # 그때까지 완료된 자산은 남긴다 — 재실행 시 이어서 생성한다.
    executor = ThreadPoolExecutor(max_workers=max_workers)
    last_flush = clock()
    try:
        futures = {executor.submit(generate_one, asset): asset for asset in pending}
        for future in as_completed(futures):
            generated = future.result()
            completed[generated.asset_id] = generated
            state[generated.asset_id] = generated
            if clock() - last_flush >= state_flush_interval_seconds:
                write_generation_state(state_path, state)
                last_flush = clock()
    except BaseException:
        # 아직 시작하지 않은 작업은 취소해 실패 뒤 몇 시간씩 대기하지 않게 한다.
        executor.shutdown(wait=True, cancel_futures=True)
        if pending:
            write_generation_state(state_path, state)
        raise
    executor.shutdown(wait=True)

    if pending:
        state.update(completed)
        write_generation_state(state_path, state)
    # 재사용이 몇 건인지 보여야 --reuse-s3-bucket을 쓸 이유가 드러난다.
    progress(
        f"units={len(completed)}, synthesized={counts['synthesized']}, "
        f"reused_from_s3={counts['reused']}, already_local={len(completed) - len(pending)}"
    )
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

    units = synthesis_units(snapshot)

    def verify_one(asset: SourceAsset) -> GeneratedAsset | None:
        return _verified_existing_asset(
            asset, work_dir, state, probe_runner, resolved_probe
        )

    # 자산마다 ffprobe 프로세스를 띄우므로 직렬이면 수만 개에 십수 분이 걸린다.
    with ThreadPoolExecutor(max_workers=8) as executor:
        verified = [
            generated
            for generated in executor.map(verify_one, units)
            if generated is not None
        ]
    # 개수만 맞추지 않는다 — 모든 자산이 자기 단위를 갖는지 집합으로 확인한다.
    missing = {synthesis_unit_id(asset) for asset in snapshot.assets} - {
        generated.asset_id for generated in verified
    }
    if missing:
        raise InvalidMp3Error(
            f"expected {len(units)} synthesis units, verified {len(verified)} "
            f"(missing {sorted(missing)[:3]})"
        )
    return sorted(verified, key=lambda item: item.asset_id)


def build_manifest(
    snapshot: SourceSnapshot, generated_assets: list[GeneratedAsset]
) -> dict:
    validate_source(snapshot)
    # 매니페스트 행은 자산마다 하나다 (BE가 표현·억양·단어순서마다 한 행을 요구한다).
    # 오디오 데이터는 그 자산이 속한 합성 단위에서 가져온다 — 단어는 여러 자산이 공유한다.
    generated_by_unit = {asset.asset_id: asset for asset in generated_assets}
    missing = {synthesis_unit_id(asset) for asset in snapshot.assets} - set(generated_by_unit)
    if missing:
        raise ValueError(
            f"manifest requires a generated asset for every synthesis unit "
            f"(missing {sorted(missing)[:3]})"
        )

    manifest_assets = []
    for source_asset in sorted(snapshot.assets, key=asset_id):
        generated = generated_by_unit[synthesis_unit_id(source_asset)]
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
    candidates = [
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
    # 매니페스트 행은 자산마다 하나지만 공유 단어는 여러 행이 같은 키를 가리킨다. 키를
    # 그대로 두면 같은 객체를 N번 올리려다 --if-none-match가 412로 막는다. 합치되,
    # 합쳐지는 행들이 정말 같은 소리인지 확인하고 다르면 멈춘다 — 조용히 덮으면 어느
    # 표현의 소리가 올라갔는지 알 수 없게 된다.
    objects: list[UploadObject] = []
    by_key: dict[str, UploadObject] = {}
    for candidate in candidates:
        seen = by_key.get(candidate.key)
        if seen is None:
            by_key[candidate.key] = candidate
            objects.append(candidate)
            continue
        if (
            seen.content_length != candidate.content_length
            or seen.metadata.get("audio-sha256") != candidate.metadata.get("audio-sha256")
        ):
            raise ValueError(
                f"manifest rows disagree on the audio behind {candidate.key}: "
                f"{seen.metadata.get('audio-sha256')} vs "
                f"{candidate.metadata.get('audio-sha256')}"
            )
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


class _CompletedCall:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Boto3AwsRunner:
    """aws CLI 호출(list-objects-v2·head-object·get-object·copy-object·put-object)을 boto3로 대신한다.

    CLI는 호출마다 파이썬 프로세스를 새로 띄워 객체당 1초 이상 걸리므로 수만 개 게시에
    한 시간이 넘는다. 같은 인자 계약을 받아 프로세스 안에서 처리하면 스레드 32개로
    초당 수백 개까지 올라간다. 게시 결과(키·메타데이터·If-None-Match)는 CLI와 같다.
    """

    def __init__(self) -> None:
        import boto3

        self._client = boto3.client("s3")

    @staticmethod
    def _option(command: list[str], name: str) -> str | None:
        return command[command.index(name) + 1] if name in command else None

    def __call__(self, command: list[str], **kwargs) -> _CompletedCall:
        from botocore.exceptions import ClientError

        operation = command[2]
        bucket = self._option(command, "--bucket")
        try:
            if operation == "list-objects-v2":
                keys: list[str] = []
                paginator = self._client.get_paginator("list_objects_v2")
                for page in paginator.paginate(
                    Bucket=bucket, Prefix=self._option(command, "--prefix")
                ):
                    keys.extend(item["Key"] for item in page.get("Contents", []))
                return _CompletedCall(0, json.dumps(keys or None))
            if operation == "head-object":
                head = self._client.head_object(
                    Bucket=bucket, Key=self._option(command, "--key")
                )
                payload = {
                    "ContentLength": head.get("ContentLength"),
                    "ContentType": head.get("ContentType"),
                    "CacheControl": head.get("CacheControl"),
                    "Metadata": head.get("Metadata", {}),
                }
                return _CompletedCall(0, json.dumps(payload))
            if operation == "head-bucket":
                self._client.head_bucket(Bucket=bucket)
                return _CompletedCall(0, "{}")
            if operation == "get-object":
                # CLI는 마지막 위치 인자를 내려받을 파일 경로로 받는다.
                self._client.download_file(bucket, self._option(command, "--key"),
                                           command[-1])
                return _CompletedCall(0, "{}")
            if operation == "copy-object":
                self._client.copy_object(
                    Bucket=bucket,
                    Key=self._option(command, "--key"),
                    CopySource=self._option(command, "--copy-source"),
                    MetadataDirective=self._option(command, "--metadata-directive"),
                )
                return _CompletedCall(0, "{}")
            if operation == "put-object":
                metadata = dict(
                    item.split("=", 1)
                    for item in self._option(command, "--metadata").split(",")
                )
                body = Path(self._option(command, "--body")).read_bytes()
                request = {
                    "Bucket": bucket,
                    "Key": self._option(command, "--key"),
                    "Body": body,
                    "ContentType": self._option(command, "--content-type"),
                    "CacheControl": self._option(command, "--cache-control"),
                    "Metadata": metadata,
                }
                if "--if-none-match" in command:
                    request["IfNoneMatch"] = self._option(command, "--if-none-match")
                self._client.put_object(**request)
                return _CompletedCall(0)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            return _CompletedCall(1, "", f"{code} {status} {error}")
        raise ValueError(f"unsupported aws command: {command[:3]}")


def require_bucket(bucket: str, aws_runner: Callable = subprocess.run) -> None:
    """버킷이 있는지 작업 시작 전에 한 번 확인한다.

    head-object는 버킷이 없을 때도 키가 없을 때와 같은 404를 주므로, 개별 키 조회로는
    `--bucket` 오타를 알아낼 수 없다. 그대로 두면 전 항목이 "object is missing"으로
    나와 원인을 키에서 찾게 된다.

    :raises RuntimeError: 버킷이 없거나 접근할 수 없을 때
    """
    completed = aws_runner(
        ["aws", "s3api", "head-bucket", "--bucket", bucket],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"S3 bucket is missing or not accessible: {bucket} ({completed.stderr.strip()})"
        )


def _head_key(bucket: str, key: str, aws_runner: Callable) -> dict | None:
    """키 하나의 head 응답을 돌려준다. 객체가 없으면 None, 그 밖의 실패는 예외."""
    completed = aws_runner(
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
    if completed.returncode == 0:
        return json.loads(completed.stdout)
    # head-object는 버킷이 없을 때도 키가 없을 때와 똑같이 맨 404를 준다(실측). 그래서
    # 여기서는 구분할 수 없고, 버킷은 작업 시작 전에 require_bucket으로 한 번 확인한다.
    # aws CLI 경로는 NoSuchBucket을 실어 주므로 그건 여기서 걸러 준다.
    if "NoSuchBucket" in completed.stderr:
        raise RuntimeError(f"S3 bucket does not exist: {bucket}")
    if any(
        marker in completed.stderr for marker in ("404", "Not Found", "NoSuchKey")
    ):
        return None
    raise RuntimeError(f"S3 head-object failed for key {key}")


def _head_object(
    bucket: str, upload_object: UploadObject, aws_runner: Callable
) -> dict | None:
    return _head_key(bucket, upload_object.key, aws_runner)


def _head_matches(upload_object: UploadObject, head: dict) -> bool:
    remote_metadata = {
        key.lower(): str(value) for key, value in head.get("Metadata", {}).items()
    }
    expected_metadata = dict(upload_object.metadata)
    # generation-id 메타데이터 도입 전에 게시된 객체는 그 키가 없다 — 하위 호환
    if "generation-id" not in remote_metadata:
        expected_metadata.pop("generation-id", None)
    # source-sha256은 처음 게시한 배치의 스냅샷 기록일 뿐 객체 정체성이 아니다.
    # 증분 게시에서는 배치가 달라지므로 비교에서 제외한다.
    expected_metadata.pop("source-sha256", None)
    remote_metadata.pop("source-sha256", None)
    # 풀 QA 교체 표시도 내력일 뿐이다. 남겨 두면 교체본을 다른 경로에서 검증할 때
    # 기대 메타데이터에 이 키가 없어 불일치로 잡힌다.
    expected_metadata.pop(WORD_POOL_REPLACED_MARKER, None)
    remote_metadata.pop(WORD_POOL_REPLACED_MARKER, None)
    return (
        head.get("ContentLength") == upload_object.content_length
        and head.get("ContentType") == upload_object.content_type
        and head.get("CacheControl") == upload_object.cache_control
        and remote_metadata == expected_metadata
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
    allow_replace: bool = False,
) -> UploadPlan:
    """게시 계획을 세운다.

    allow_replace=False(기본)면 내용이 다른 기존 키는 충돌로 막는다 (immutable 게시 원칙).
    allow_replace=True면 그 키들을 replace_keys로 분류해 덮어쓴다 — QA 재합성으로 같은
    텍스트의 음성을 교체할 때 쓴다. 키가 같으므로 DB URL은 그대로지만 CloudFront 캐시가
    immutable이라 게시 후 무효화가 필요하다 (upload 출력의 invalidation 안내 참고).
    """
    objects = _upload_objects(manifest, work_dir)
    existing = _list_existing_keys(bucket, KEY_PREFIX, aws_runner)
    new_keys = []
    reused_keys = []
    conflict_keys = []
    replace_keys = []
    # 기존 키의 head-object 대조는 서로 독립이라 병렬로 한다 (29k 직렬 실측 15분 → 1분대).
    existing_objects = [o for o in objects if o.key in existing]
    with ThreadPoolExecutor(max_workers=16) as executor:
        heads = dict(
            zip(
                (o.key for o in existing_objects),
                executor.map(lambda o: _head_object(bucket, o, aws_runner), existing_objects),
            )
        )
    for upload_object in objects:
        if upload_object.key not in existing:
            new_keys.append(upload_object.key)
            continue
        head = heads[upload_object.key]
        if head is None:
            new_keys.append(upload_object.key)
        elif _head_matches(upload_object, head):
            reused_keys.append(upload_object.key)
        elif allow_replace and not upload_object.manifest_object:
            replace_keys.append(upload_object.key)
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
        replace_keys=tuple(replace_keys),
    )


def _put_object(
    plan: UploadPlan,
    upload_object: UploadObject,
    body_path: Path,
    aws_runner: Callable,
    *,
    overwrite: bool = False,
) -> None:
    metadata = ",".join(
        f"{key}={value}" for key, value in upload_object.metadata.items()
    )
    # 신규 키는 If-None-Match: * 로 우연한 덮어쓰기를 막고, 교체 키만 조건 없이 올린다.
    precondition = [] if overwrite else ["--if-none-match", "*"]
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
            *precondition,
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
    max_workers: int = 12,
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
    replace_key_set = set(plan.replace_keys)

    def upload_one(upload_object: UploadObject) -> None:
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
            _put_object(
                plan,
                upload_object,
                body_path,
                aws_runner,
                overwrite=upload_object.key in replace_key_set,
            )
        finally:
            if temporary_manifest_path is not None:
                temporary_manifest_path.unlink(missing_ok=True)
        head = _head_object(plan.bucket, upload_object, aws_runner)
        if head is None or not _head_matches(upload_object, head):
            raise ValueError(
                f"uploaded object verification conflict: {upload_object.key}"
            )

    # 객체별 put+head를 직렬로 하면 수만 개 게시에 수 시간이 걸린다(실측 0.7개/초).
    # 객체들은 서로 독립이므로 병렬로 올리되, 게시 완료의 표식인 매니페스트는
    # 데이터 객체가 전부 성공한 뒤 마지막에 단독으로 올린다.
    data_objects = [o for o in ordered_new_objects if not o.manifest_object]
    data_objects += [objects_by_key[key] for key in plan.replace_keys]
    marker_objects = [o for o in ordered_new_objects if o.manifest_object]
    uploaded = 0
    verified = plan.reused_count
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for _ in executor.map(upload_one, data_objects):
            uploaded += 1
            verified += 1
    for upload_object in marker_objects:
        upload_one(upload_object)
        uploaded += 1
        verified += 1
    return UploadResult(uploaded=uploaded, verified=verified, conflicts=0)


def validate_reference_entries(entries: object) -> str:
    """기준 데이터가 BE parseReference() 계약대로 게시 가능한지 검증하고 locale을 반환한다.

    BE는 아래 규칙을 어긴 표현을 임포트 실패 목록에 올리므로 게시 전에 같은 규칙으로
    막는다. 단 sentenceText가 BE DB의 현재 대표 예문과 문자열까지 일치하는지는 여기서
    확인할 수 없다 — 임포트 응답의 실패 목록으로 확인한다.
    """
    if not isinstance(entries, list) or not entries:
        raise ValueError("reference must be a non-empty top-level JSON array")
    locales = set()
    for entry in entries:
        expression_id = entry.get("expressionId")
        if not isinstance(expression_id, int) or isinstance(expression_id, bool):
            raise ValueError("reference entry expressionId must be an integer")
        label = f"reference entry {expression_id}"
        locale = entry.get("accentLocale")
        if locale not in SUPPORTED_LOCALES:
            raise ValueError(f"{label} has an unsupported accentLocale")
        locales.add(locale)
        sentence = entry.get("sentenceText")
        if not isinstance(sentence, str) or not sentence.strip():
            raise ValueError(f"{label} is missing sentenceText")
        words = entry.get("words")
        if not isinstance(words, list) or not words:
            raise ValueError(f"{label} must have at least one word")
        orders = []
        for word in words:
            order = word.get("order")
            if not isinstance(order, int) or isinstance(order, bool) or order < 1:
                raise ValueError(f"{label} word order must be an integer >= 1")
            orders.append(order)
            word_text = word.get("word")
            if (
                not isinstance(word_text, str)
                or not word_text
                or re.search(r"\s", word_text)
            ):
                raise ValueError(f"{label} word must not contain whitespace")
        if len(set(orders)) != len(orders):
            raise ValueError(f"{label} has a duplicate word order")
    if len(locales) != 1:
        raise ValueError("reference file must contain a single accentLocale")
    return locales.pop()


def publish_reference(
    reference_dir: Path,
    tts_manifest_key: str,
    bucket: str,
    *,
    execute: bool = False,
    aws_runner: Callable = subprocess.run,
) -> list[str]:
    """기준 데이터 JSON 3개를 최상위 배열 그대로 S3에 게시하고 키 목록을 반환한다.

    BE parseReference()가 최상위 JSON 배열(List<Entry>)을 기대하므로 겉포장을 씌우지
    않는다. TTS 매니페스트 키는 S3 객체 metadata(tts-manifest-key)로만 전달한다.
    """
    published = []
    for reference_path in sorted(reference_dir.glob("reference_EN_*.json")):
        if "review" in reference_path.name:
            continue
        entries = json.loads(reference_path.read_text(encoding="utf-8"))
        locale = validate_reference_entries(entries)
        body = (
            json.dumps(entries, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        key = f"{KEY_PREFIX}/reference/{locale}-{digest}.json"
        upload_object = UploadObject(
            key=key,
            body_path=None,
            body_bytes=body,
            content_length=len(body),
            content_type="application/json",
            cache_control=CACHE_CONTROL,
            metadata={"tts-manifest-key": tts_manifest_key},
            manifest_object=True,
        )
        head = _head_object(bucket, upload_object, aws_runner)
        if head is not None:
            print(f"reused {key}")
            published.append(key)
            continue
        if execute:
            with tempfile.NamedTemporaryFile(
                prefix="lan-373-reference-", suffix=".json", delete=False
            ) as handle:
                handle.write(body)
                temporary = Path(handle.name)
            try:
                _put_object(
                    UploadPlan(bucket=bucket, new_keys=(key,), reused_keys=(),
                               conflict_keys=(), objects=(upload_object,)),
                    upload_object,
                    temporary,
                    aws_runner,
                )
            finally:
                temporary.unlink(missing_ok=True)
            print(f"uploaded {key}")
        else:
            print(f"would upload {key} ({len(body)}B)")
        published.append(key)
    return published


def build_be_manifest(
    manifest: dict,
    snapshot: SourceSnapshot,
    *,
    cdn_base_url: str = DEFAULT_CDN_BASE_URL,
) -> dict:
    """작업 매니페스트를 BE importTts가 기대하는 모양으로 변환한다.

    BE 계약(확정 DTO): 표현x억양당 1행, CDN URL. 필드명은 assets/expressionId/
    accentLocale/expressionAudioUrl/sentenceAudioUrl/words/order/audioUrl 철자 그대로.
    BE는 기준 데이터 words의 order로 조인하므로 소스와 order 집합이 어긋난 표현은
    임포트 실패 처리된다 — 게시 전에 소스와 교차 검증해 중단한다.
    """
    if manifest["source"]["snapshotSha256"] != source_sha256(snapshot):
        raise ValueError("manifest was not built from the given --source")
    base_url = cdn_base_url.rstrip("/")

    rows_by_group: dict[tuple[int, str], dict[str, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in manifest["assets"]:
        rows_by_group[(row["expressionId"], row["accentLocale"])][
            row["kind"]
        ].append(row)

    expected_by_group: dict[tuple[int, str], dict] = {}
    for asset in snapshot.assets:
        expected = expected_by_group.setdefault(
            (asset.expression_id, asset.accent_locale),
            {"has_expression": False, "word_orders": set()},
        )
        if asset.kind == KIND_EXPRESSION:
            expected["has_expression"] = True
        elif asset.kind == KIND_WORD:
            expected["word_orders"].add(asset.word_order)

    if set(rows_by_group) != set(expected_by_group):
        raise ValueError("manifest expressions do not match the source")

    be_assets = []
    for expression_id, locale in sorted(expected_by_group):
        rows = rows_by_group[(expression_id, locale)]
        expected = expected_by_group[(expression_id, locale)]
        label = f"expression {expression_id} ({locale})"
        sentence_rows = rows.get(KIND_SENTENCE, [])
        if len(sentence_rows) != 1:
            raise ValueError(f"{label} must have exactly one sentence row")
        expression_rows = rows.get(KIND_EXPRESSION, [])
        if len(expression_rows) > 1:
            raise ValueError(f"{label} must have at most one expression row")
        # 패턴형 표현은 표현 행이 없는 게 정상이지만, 소스가 기대하는데 없거나
        # 소스에 없는데 있으면 데이터 결손·혼입이다
        if bool(expression_rows) != expected["has_expression"]:
            raise ValueError(f"{label} expression row does not match the source")
        word_rows = sorted(rows.get(KIND_WORD, []), key=lambda row: row["wordOrder"])
        word_orders = [row["wordOrder"] for row in word_rows]
        if len(set(word_orders)) != len(word_orders):
            raise ValueError(f"{label} has a duplicate word order")
        if set(word_orders) != expected["word_orders"]:
            raise ValueError(f"{label} word orders do not match the source")
        be_assets.append(
            {
                "expressionId": expression_id,
                "accentLocale": locale,
                # 패턴형 표현은 표현 음성이 없다 — BE 컬럼이 nullable이라 null이 정상
                "expressionAudioUrl": (
                    f"{base_url}/{expression_rows[0]['s3Key']}"
                    if expression_rows
                    else None
                ),
                "sentenceAudioUrl": f"{base_url}/{sentence_rows[0]['s3Key']}",
                "words": [
                    {"order": row["wordOrder"], "audioUrl": f"{base_url}/{row['s3Key']}"}
                    for row in word_rows
                ],
            }
        )
    return {"assets": be_assets}


def publish_be_manifest(
    be_manifest: dict,
    source_sha: str,
    bucket: str,
    *,
    execute: bool = False,
    aws_runner: Callable = subprocess.run,
) -> str:
    """BE 매니페스트를 콘텐츠 해시 키로 게시하고 키를 반환한다.

    반환된 키를 사람이 BE Swagger의 manifestKey 파라미터에 그대로 복사해 넣는다.
    """
    body = canonical_manifest_bytes(be_manifest)
    digest = hashlib.sha256(body).hexdigest()
    key = f"{KEY_PREFIX}/manifests/be-{digest}.json"
    upload_object = UploadObject(
        key=key,
        body_path=None,
        body_bytes=body,
        content_length=len(body),
        content_type="application/json",
        cache_control=CACHE_CONTROL,
        metadata={"source-sha256": source_sha, "manifest-sha256": digest},
        manifest_object=True,
    )
    head = _head_object(bucket, upload_object, aws_runner)
    if head is not None:
        if not _head_matches(upload_object, head):
            raise ValueError(f"existing object conflict: {key}")
        print(f"reused {key}")
        return key
    if not execute:
        print(f"would upload {key} ({len(body)}B)")
        return key
    with tempfile.NamedTemporaryFile(
        prefix="lan-373-be-manifest-", suffix=".json", delete=False
    ) as handle:
        handle.write(body)
        temporary = Path(handle.name)
    try:
        _put_object(
            UploadPlan(bucket=bucket, new_keys=(key,), reused_keys=(),
                       conflict_keys=(), objects=(upload_object,)),
            upload_object,
            temporary,
            aws_runner,
        )
    finally:
        temporary.unlink(missing_ok=True)
    verified = _head_object(bucket, upload_object, aws_runner)
    if verified is None or not _head_matches(upload_object, verified):
        raise ValueError(f"uploaded object verification conflict: {key}")
    print(f"uploaded {key}")
    return key


# ---------------------------------------------------------------------------
# LAN-475 공용 단어 풀
#
# 단어 음성의 옛 키는 `{표현id}/{억양}/word/{순서}/{해시}.mp3`라 경로에 표현 id가
# 들어가 같은 단어가 표현마다 따로 저장됐다(실측 69,531개 중 서로 다른 것은 10,506개).
# 해시는 이미 (모델·보이스·텍스트·포맷)으로만 계산되므로, 같은 해시는 같은 소리다.
# 여기서는 (억양, 해시)마다 대표를 하나 골라 공용 자리로 서버 사이드 복사만 한다.
# 새 합성은 없고, 옛 키도 건드리지 않는다(삭제는 V126 prod 검증 뒤 별도 단계).
# ---------------------------------------------------------------------------

# 2: entry에 published(공용 자리 실물 확인 결과)가 생겼다. V126 허용 목록이 이 값을
# 믿고 만들어지므로, 그 필드가 없는 옛 색인은 받지 않는다.
def word_fingerprint(accent_locale: str, text: str) -> str:
    """단어 텍스트로부터 해시를 계산한다 (표현 id·순서와 무관함을 드러낸다)."""
    return generation_fingerprint(
        SourceAsset(
            expression_id=0,
            accent_locale=accent_locale,
            kind=KIND_WORD,
            word_order=1,
            text=text,
        )
    )


@dataclass(frozen=True)
class LegacyWordKey:
    key: str
    expression_id: int
    accent_locale: str
    word_order: int
    fingerprint: str


@dataclass(frozen=True)
class WordPoolEntry:
    accent_locale: str
    fingerprint: str
    source_key: str
    source_expression_id: int
    source_word_order: int
    qa_verified: bool
    duplicate_count: int
    word: str | None = None

    @property
    def target_key(self) -> str:
        return shared_word_key(self.accent_locale, self.fingerprint)


@dataclass(frozen=True)
class WordPoolPlan:
    bucket: str
    entries: tuple[WordPoolEntry, ...]
    existing_target_keys: frozenset[str]
    legacy_key_count: int
    # 단어 텍스트를 함께 넘겼을 때, 어떤 텍스트와도 이어지지 않은 (억양, 해시)
    unmatched: tuple[tuple[str, str], ...] = ()

    @property
    def copy_entries(self) -> tuple[WordPoolEntry, ...]:
        return tuple(
            entry
            for entry in self.entries
            if entry.target_key not in self.existing_target_keys
        )

    @property
    def reused_entries(self) -> tuple[WordPoolEntry, ...]:
        return tuple(
            entry
            for entry in self.entries
            if entry.target_key in self.existing_target_keys
        )


def parse_expression_ranges(raw: str) -> tuple[tuple[int, int], ...]:
    """`982-1938,2259-3000` 형식을 (시작, 끝) 쌍으로 바꾼다. 양끝 포함."""
    ranges: list[tuple[int, int]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            raise ValueError(f"expression range must look like 982-1938: {part}")
        start_text, _, end_text = part.partition("-")
        start, end = int(start_text), int(end_text)
        if start > end:
            raise ValueError(f"expression range start exceeds end: {part}")
        ranges.append((start, end))
    return tuple(ranges)


def parse_legacy_word_keys(keys: Iterable[str]) -> tuple[LegacyWordKey, ...]:
    """키 목록에서 옛 단어 키만 골라 구성 요소로 쪼갠다. 문장·표현 키는 버린다."""
    parsed: list[LegacyWordKey] = []
    for key in keys:
        match = LEGACY_WORD_KEY_PATTERN.match(key)
        if match is None:
            continue
        parsed.append(
            LegacyWordKey(
                key=key,
                expression_id=int(match.group("expression_id")),
                accent_locale=match.group("accent_locale"),
                word_order=int(match.group("word_order")),
                fingerprint=match.group("fingerprint"),
            )
        )
    return tuple(parsed)


def _representative(
    candidates: list[LegacyWordKey], preferred_ranges: tuple[tuple[int, int], ...]
) -> tuple[LegacyWordKey, bool]:
    """중복 후보 중 대표 하나와 그 대표가 QA를 받은 배치 출신인지를 돌려준다.

    QA 이력이 있는 배치를 먼저 쓰고, 그 안에서는 표현 id·단어 순서가 작은 쪽을
    쓴다. 같은 입력이면 항상 같은 대표가 나와야 재실행이 안전하다.
    """

    def in_preferred(item: LegacyWordKey) -> bool:
        return any(start <= item.expression_id <= end for start, end in preferred_ranges)

    chosen = min(
        candidates,
        key=lambda item: (
            0 if in_preferred(item) else 1,
            item.expression_id,
            item.word_order,
        ),
    )
    return chosen, in_preferred(chosen)


def plan_word_pool(
    keys: Iterable[str],
    bucket: str,
    *,
    preferred_expression_ranges: tuple[tuple[int, int], ...] = (),
    word_texts: Iterable[tuple[str, str]] | None = None,
    drop_unmatched: bool = False,
) -> WordPoolPlan:
    """버킷 키 목록에서 (억양, 해시)별 대표를 골라 복사 계획을 세운다.

    :param keys: `content/expression-pronunciation-audio/` 아래 키 전체
    :param bucket: 대상 버킷 (복사는 같은 버킷 안에서 일어난다)
    :param preferred_expression_ranges: QA를 받은 배치의 표현 id 구간. 대표 선정에 우선한다
    :param word_texts: (억양, 단어) 쌍. 주면 해시를 다시 계산해 단어를 이어 붙인다
    :param drop_unmatched: True면 어떤 단어와도 이어지지 않은 해시를 풀에서 뺀다
    :return: 복사 대상과 이미 있는 것이 나뉜 계획
    """
    key_list = list(keys)
    legacy = parse_legacy_word_keys(key_list)
    existing_targets = frozenset(
        key for key in key_list if SHARED_WORD_KEY_PATTERN.match(key)
    )

    grouped: dict[tuple[str, str], list[LegacyWordKey]] = defaultdict(list)
    for item in legacy:
        grouped[(item.accent_locale, item.fingerprint)].append(item)

    text_by_fingerprint: dict[tuple[str, str], str] = {}
    if word_texts is not None:
        for accent_locale, word in word_texts:
            text_by_fingerprint[
                (accent_locale, word_fingerprint(accent_locale, word))
            ] = word

    entries: list[WordPoolEntry] = []
    unmatched: list[tuple[str, str]] = []
    for (accent_locale, fingerprint), candidates in sorted(grouped.items()):
        chosen, qa_verified = _representative(candidates, preferred_expression_ranges)
        text = text_by_fingerprint.get((accent_locale, fingerprint))
        if word_texts is not None and text is None:
            unmatched.append((accent_locale, fingerprint))
            if drop_unmatched:
                continue
        entries.append(
            WordPoolEntry(
                accent_locale=accent_locale,
                fingerprint=fingerprint,
                source_key=chosen.key,
                source_expression_id=chosen.expression_id,
                source_word_order=chosen.word_order,
                qa_verified=qa_verified,
                duplicate_count=len(candidates),
                word=text,
            )
        )
    return WordPoolPlan(
        bucket=bucket,
        entries=tuple(entries),
        existing_target_keys=existing_targets,
        legacy_key_count=len(legacy),
        unmatched=tuple(unmatched),
    )


def load_word_texts(path: Path) -> tuple[tuple[str, str], ...]:
    """`{억양}<탭>{단어}` 줄로 된 파일을 읽어 (억양, 단어) 쌍으로 돌려준다.

    단어의 앞뒤 공백도 해시에 들어가므로 strip 하지 않는다. 빈 줄만 건너뛴다.

    :param path: 탭으로 구분된 (억양, 단어) 파일
    :return: 파일에 나온 순서대로, 중복을 뺀 (억양, 단어) 쌍
    :raises ValueError: 탭이 없거나 억양이 지원 목록에 없는 줄이 있을 때
    """
    pairs: dict[tuple[str, str], None] = {}
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        accent_locale, tab, word = line.partition("\t")
        if not tab:
            raise ValueError(f"{path}:{number} must be tab separated locale and word")
        if accent_locale not in SUPPORTED_LOCALES:
            raise ValueError(f"{path}:{number} has unsupported locale {accent_locale}")
        pairs[(accent_locale, word)] = None
    return tuple(pairs)


def build_word_pool_index(
    plan: WordPoolPlan,
    preferred_expression_ranges: tuple[tuple[int, int], ...],
    *,
    published_target_keys: frozenset[str] = frozenset(),
) -> dict:
    """공용 풀의 내용을 2·3단계가 읽을 문서로 만든다.

    V126 마이그레이션의 허용 목록과, 다음 배치의 "이미 있으니 합성하지 않는다"
    판정이 이 문서를 입력으로 쓴다.

    :param published_target_keys: 공용 자리에 실물이 있다고 확인된 키. 항목마다
        `published`로 남긴다. dry-run으로 만든 색인을 허용 목록으로 잘못 쓰면
        파일 없는 URL을 허용하게 되므로, 실물 확인 결과를 색인이 직접 들고 있게 한다
    """
    entries = [
        {
            "accentLocale": entry.accent_locale,
            "fingerprint": entry.fingerprint,
            "targetKey": entry.target_key,
            "sourceKey": entry.source_key,
            "sourceExpressionId": entry.source_expression_id,
            "sourceWordOrder": entry.source_word_order,
            "qaVerified": entry.qa_verified,
            "duplicateCount": entry.duplicate_count,
            "published": entry.target_key in published_target_keys,
            **({"word": entry.word} if entry.word is not None else {}),
        }
        for entry in plan.entries
    ]
    return {
        "schemaVersion": WORD_POOL_SCHEMA_VERSION,
        "issue": WORD_POOL_ISSUE,
        "keyPrefix": KEY_PREFIX,
        "bucket": plan.bucket,
        "preferredExpressionRanges": [
            [start, end] for start, end in preferred_expression_ranges
        ],
        "summary": {
            "legacyWordKeys": plan.legacy_key_count,
            "entries": len(plan.entries),
            "published": sum(
                1 for entry in plan.entries if entry.target_key in published_target_keys
            ),
            "qaVerified": sum(1 for entry in plan.entries if entry.qa_verified),
            "byAccentLocale": {
                locale: sum(
                    1 for entry in plan.entries if entry.accent_locale == locale
                )
                for locale in sorted({entry.accent_locale for entry in plan.entries})
            },
        },
        "entries": entries,
    }


def _copy_object(
    bucket: str, source_key: str, target_key: str, aws_runner: Callable
) -> None:
    """같은 버킷 안에서 서버 사이드 복사한다. 메타데이터·Cache-Control은 그대로 옮긴다."""
    completed = aws_runner(
        [
            "aws",
            "s3api",
            "copy-object",
            "--bucket",
            bucket,
            "--key",
            target_key,
            "--copy-source",
            f"{bucket}/{source_key}",
            "--metadata-directive",
            "COPY",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"S3 copy-object failed for key {target_key}")


def _copied_head_matches(source_head: dict, target_head: dict) -> bool:
    """복사본이 원본과 같은 바이트·타입·캐시 정책·audio-sha256을 갖는지 본다."""

    def audio_sha(head: dict) -> str | None:
        metadata = {
            key.lower(): str(value) for key, value in head.get("Metadata", {}).items()
        }
        return metadata.get("audio-sha256")

    return (
        source_head.get("ContentLength") == target_head.get("ContentLength")
        and source_head.get("ContentType") == target_head.get("ContentType")
        and source_head.get("CacheControl") == target_head.get("CacheControl")
        and audio_sha(source_head) == audio_sha(target_head)
        and audio_sha(source_head) is not None
    )


def execute_word_pool_backfill(
    plan: WordPoolPlan,
    *,
    execute: bool = False,
    aws_runner: Callable = subprocess.run,
    max_workers: int = 16,
    progress: Callable[[str], None] = lambda message: None,
) -> int:
    """계획의 복사 대상을 공용 자리에 복사하고 원본과 대조해 검증한다.

    이미 공용 자리에 있는 키는 건드리지 않되, 원본과 같은 내용인지 대조한다.
    하나라도 어긋나면 예외를 던져 멈춘다 — 조용히 넘기면 잘못된 소리가 모든
    표현에 한꺼번에 퍼진다.

    :param plan: plan_word_pool이 만든 계획
    :param execute: False면 아무것도 쓰지 않고 0을 돌려준다 (대조도 하지 않는다)
    :param aws_runner: aws CLI 호출 대행 (Boto3AwsRunner 사용 가능)
    :param max_workers: 동시 복사 스레드 수
    :param progress: 진행 상황 출력 콜백
    :return: 실제로 복사한 객체 수
    :raises ValueError: 복사본이 원본과 다르거나 원본 head를 못 읽을 때
    """
    if not execute:
        return 0

    copied = 0
    total = len(plan.copy_entries)
    counter_lock = threading.Lock()

    def copy_one(entry: WordPoolEntry) -> None:
        nonlocal copied
        source_head = _head_key(plan.bucket, entry.source_key, aws_runner)
        if source_head is None:
            raise ValueError(f"source object is missing: {entry.source_key}")
        _copy_object(plan.bucket, entry.source_key, entry.target_key, aws_runner)
        # 취소 시점에 이미 S3에 도달한 작업도 세야 한다. 결과를 꺼낸 것만 세면
        # "1건 복사됨"이라고 알리면서 실제로는 5개가 생겨 있을 수 있다.
        with counter_lock:
            copied += 1
        target_head = _head_key(plan.bucket, entry.target_key, aws_runner)
        if target_head is None or not _copied_head_matches(source_head, target_head):
            raise ValueError(f"copied object verification conflict: {entry.target_key}")

    # executor.map은 첫 예외 뒤에도 제출된 나머지를 끝까지 돌린다. 원본 하나가 빠진 걸로
    # 멈춰야 할 실행이 수천 건을 더 복사하고 나서야 터지므로, run_check와 같이 명시적으로
    # 취소한다. 진행분은 예외와 함께 사라지지 않도록 먼저 알린다.
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = [executor.submit(copy_one, entry) for entry in plan.copy_entries]
        done = 0
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 500 == 0:
                progress(f"copied {done}/{total}")
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        progress(f"copied {copied}/{total} before failing")
        raise
    executor.shutdown(wait=True)
    if copied:
        progress(f"copied {copied}/{total}")

    # 이미 공용 자리에 있던 항목은 복사하지 않지만, 내용이 원본과 같은지는 확인한다.
    # 여기서 넘기면 잘못된 소리가 모든 표현에 한꺼번에 퍼진 채로 아무도 다시 안 본다.
    # 복사 진행분은 위에서 이미 알렸으므로 여기서 터져도 사라지지 않는다.
    reused_problems, reused_replaced = verify_word_pool(
        plan,
        aws_runner=aws_runner,
        max_workers=max_workers,
        entries=plan.reused_entries,
    )
    if plan.reused_entries:
        # 건너뛴 건수를 조용히 버리지 않는다 — "몇 개를 왜 대조하지 않았는지"가 보여야 한다.
        progress(
            f"reused {len(plan.reused_entries)} verified against source, "
            f"{reused_replaced} skipped (QA replaced)"
        )
    if reused_problems:
        raise ValueError(
            "existing shared objects differ from their source: "
            + ", ".join(reused_problems[:5])
        )
    return copied


def verify_word_pool(
    plan: WordPoolPlan,
    *,
    aws_runner: Callable = subprocess.run,
    max_workers: int = 16,
    entries: Sequence[WordPoolEntry] | None = None,
) -> tuple[tuple[str, ...], int]:
    """공용 자리의 모든 항목이 자기 원본과 같은 내용인지 전수 대조한다.

    풀 QA가 재합성으로 교체한 객체는 원본과 달라지는 것이 정상이므로 대조에서 빼고
    따로 센다. 표시가 없는데 내용이 다르면 복사 사고이므로 문제로 올린다.

    :param entries: 대조할 항목. 생략하면 계획 전체
    :return: (어긋난 대상 키 목록, 교체 표시가 붙어 건너뛴 수)
    """
    problems: list[str] = []
    replaced = 0

    def check_one(entry: WordPoolEntry) -> str | None:
        source_head = _head_key(plan.bucket, entry.source_key, aws_runner)
        target_head = _head_key(plan.bucket, entry.target_key, aws_runner)
        if target_head is None:
            return f"{entry.target_key} missing"
        metadata = {
            name.lower(): str(value)
            for name, value in target_head.get("Metadata", {}).items()
        }
        if metadata.get(WORD_POOL_REPLACED_MARKER) == WORD_POOL_REPLACED_VALUE:
            return "replaced"
        if source_head is None:
            return f"{entry.target_key} source missing {entry.source_key}"
        if not _copied_head_matches(source_head, target_head):
            return f"{entry.target_key} differs from {entry.source_key}"
        return None

    targets = plan.entries if entries is None else tuple(entries)
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        for problem in executor.map(check_one, targets):
            if problem == "replaced":
                replaced += 1
            elif problem is not None:
                problems.append(problem)
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    executor.shutdown(wait=True)
    return tuple(problems), replaced


def publish_word_pool_index(
    index: dict,
    bucket: str,
    *,
    execute: bool = False,
    aws_runner: Callable = subprocess.run,
) -> str:
    """풀 색인을 콘텐츠 해시 키로 게시하고 키를 반환한다.

    2단계 V126의 허용 목록을 이 키에서 받아 만든다.

    :raises ValueError: 공용 자리에 실물이 없는 항목이 하나라도 있을 때. 이 색인을
        허용 목록으로 쓰면 파일 없는 URL을 허용하게 된다
    """
    summary = index.get("summary", {})
    if summary.get("published") != summary.get("entries"):
        raise ValueError(
            f"word pool index is not fully published "
            f"({summary.get('published')}/{summary.get('entries')}) — "
            "--execute로 백필을 끝낸 뒤 게시할 것"
        )
    body = canonical_manifest_bytes(index)
    digest = hashlib.sha256(body).hexdigest()
    key = f"{KEY_PREFIX}/word-pool/{digest}.json"
    upload_object = UploadObject(
        key=key,
        body_path=None,
        body_bytes=body,
        content_length=len(body),
        content_type="application/json",
        cache_control=CACHE_CONTROL,
        metadata={"manifest-sha256": digest},
        manifest_object=True,
    )
    head = _head_object(bucket, upload_object, aws_runner)
    if head is not None:
        if not _head_matches(upload_object, head):
            raise ValueError(f"existing object conflict: {key}")
        print(f"reused {key}")
        return key
    if not execute:
        print(f"would upload {key} ({len(body)}B)")
        return key
    with tempfile.NamedTemporaryFile(
        prefix="lan-475-word-pool-", suffix=".json", delete=False
    ) as handle:
        handle.write(body)
        temporary = Path(handle.name)
    try:
        _put_object(
            UploadPlan(
                bucket=bucket,
                new_keys=(key,),
                reused_keys=(),
                conflict_keys=(),
                objects=(upload_object,),
            ),
            upload_object,
            temporary,
            aws_runner,
        )
    finally:
        temporary.unlink(missing_ok=True)
    verified = _head_object(bucket, upload_object, aws_runner)
    if verified is None or not _head_matches(upload_object, verified):
        raise ValueError(f"uploaded object verification conflict: {key}")
    print(f"uploaded {key}")
    return key


def load_word_pool_index(path: Path) -> tuple[WordPoolEntry, ...]:
    """백필이 남긴 풀 색인을 다시 항목으로 읽는다.

    :param path: `backfill-word-pool --output`이 남긴 JSON
    :return: 색인에 적힌 순서 그대로의 풀 항목
    :raises ValueError: 스키마 버전이나 이슈 표시가 다를 때
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schemaVersion") != WORD_POOL_SCHEMA_VERSION
        or payload.get("issue") != WORD_POOL_ISSUE
    ):
        raise ValueError(
            f"word pool index must be a {WORD_POOL_ISSUE} schema version "
            f"{WORD_POOL_SCHEMA_VERSION} document"
        )
    missing = [
        item.get("fingerprint")
        for item in payload["entries"]
        if "published" not in item
    ]
    if missing:
        raise ValueError(
            f"word pool index entries are missing 'published' ({len(missing)}) — "
            "backfill-word-pool로 색인을 다시 만들 것"
        )
    return tuple(
        WordPoolEntry(
            accent_locale=item["accentLocale"],
            fingerprint=item["fingerprint"],
            source_key=item["sourceKey"],
            source_expression_id=item["sourceExpressionId"],
            source_word_order=item["sourceWordOrder"],
            qa_verified=item["qaVerified"],
            duplicate_count=item["duplicateCount"],
            word=item.get("word"),
        )
        for item in payload["entries"]
    )


def word_pool_asset(entry: WordPoolEntry) -> SourceAsset:
    """풀 항목을 기존 자산 계약에 맞춘 SourceAsset으로 바꾼다.

    표현 id·단어 순서는 대표를 뽑아온 원본 키의 값을 그대로 쓴다. 그래야 자산 id가
    `{표현id}/{억양}/word-{순서}` 형식을 유지해 QA 도구와 landit-ai의 대조 정리
    도구가 쓰는 문제 문자열 계약이 그대로 통한다.

    :param entry: 단어 텍스트가 채워진 풀 항목
    :return: 같은 해시를 내는 단어 자산
    :raises ValueError: 단어 텍스트가 없거나, 텍스트로 계산한 해시가 색인과 다를 때
    """
    if entry.word is None:
        raise ValueError(
            f"word pool entry has no word text: {entry.accent_locale} {entry.fingerprint}"
            " — backfill-word-pool을 --words와 --unmatched drop으로 다시 돌려 색인을"
            " 새로 만들 것"
        )
    asset = SourceAsset(
        expression_id=entry.source_expression_id,
        accent_locale=entry.accent_locale,
        kind=KIND_WORD,
        word_order=entry.source_word_order,
        text=entry.word,
    )
    recomputed = generation_fingerprint(asset)
    if recomputed != entry.fingerprint:
        raise ValueError(
            f"word pool entry fingerprint does not match its word text: "
            f"{entry.accent_locale} {entry.fingerprint} != {recomputed}"
        )
    return asset


def _get_object(bucket: str, key: str, path: Path, aws_runner: Callable) -> None:
    """S3 객체를 임시 파일로 받아 제자리 교체한다. 중간에 죽어도 반쪽 파일이 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = Path(f"{path}.part")
    completed = aws_runner(
        ["aws", "s3api", "get-object", "--bucket", bucket, "--key", key,
         str(temporary_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(f"S3 get-object failed for key {key}")
    os.replace(temporary_path, path)


@dataclass(frozen=True)
class FetchedPoolObject:
    """풀 항목 하나를 작업 폴더에 확보한 결과."""

    generated: GeneratedAsset
    # S3 객체의 audio-sha256 메타데이터. 없으면 None — 빈 문자열과 구분해야 한다
    # (""로 뭉개면 "로컬이 원격과 다르다"가 영원히 참이 된다).
    remote_sha256: str | None
    # 로컬 파일이 S3와 다르고, 이 도구가 앞서 만든 것임이 state로 증명된 경우
    local_fix: bool


def fetch_word_pool_audio(
    entries: Iterable[WordPoolEntry],
    work_dir: Path,
    bucket: str,
    *,
    prior_state: Mapping[str, GeneratedAsset] = {},
    aws_runner: Callable = subprocess.run,
    probe_runner: Callable = subprocess.run,
    probe_name: str | None = None,
    max_workers: int = 16,
    progress: Callable[[str], None] = lambda message: None,
) -> dict[str, FetchedPoolObject]:
    """풀 항목의 음성을 작업 폴더로 확보해 QA가 읽을 기록을 만든다.

    공용 자리에 이미 있으면 그쪽을, 아직 복사 전이면 원본 키를 받는다.

    로컬 파일 처리 규칙은 네 갈래다. 파일이 있다는 것만으로는 그게 무엇인지 알 수 없고,
    작업 폴더의 mp3 경로는 `generate`·`check` 명령과 형식이 같아 다른 배치의 파일이
    놓여 있을 수 있기 때문이다. **어느 갈래든 로컬 파일을 쓰기로 할 때는 근거가 있어야 한다.**

    | 상황 | 내용이 같은가 | 출처를 아는가 | 결정 |
    | --- | --- | --- | --- |
    | 1. 파일 없음 | - | - | 내려받고 sha 대조 |
    | 2. S3에 sha 없음 | 알 수 없음 | prior_state로 확인 | 확인되면 쓰고, 아니면 거부 |
    | 3. sha 일치 | 같다 | 물을 필요 없음 | 그대로 쓴다 |
    | 4. sha 불일치 | 다르다 | prior_state로 확인 | 앞선 실행의 미게시 수정본이면 쓰고(`local_fix`), 아니면 원인별로 거부 |

    출처 확인은 `prior_state`의 기록이 **같은 sha**를 들고 있고 `generationId`가
    `s3-recovered`가 아닌 것으로 한다(4번). 2번은 내용 대조가 불가능하므로 sha 일치만 본다.
    fingerprint는 따로 보지 않는다 — 기록을 찾는 키(합성 단위 id)에 이미 들어 있어서
    다른 색인의 기록이 여기로 딸려올 수 없다.

    :param entries: 단어 텍스트가 채워진 풀 항목
    :param work_dir: mp3를 둘 작업 폴더
    :param bucket: 콘텐츠 버킷
    :param prior_state: 같은 작업 폴더의 이전 state. 2번 규칙의 증거로만 쓴다
    :return: 자산 id → 확보 결과
    :raises ValueError: 객체가 없거나, 내려받은 sha가 메타데이터와 다르거나,
        정체를 증명할 수 없는 로컬 파일이 있을 때
    """
    probe = probe_name or resolve_probe()
    entry_list = list(entries)
    fetched: dict[str, FetchedPoolObject] = {}

    def fetch_one(entry: WordPoolEntry) -> FetchedPoolObject:
        asset = word_pool_asset(entry)
        key_id = synthesis_unit_id(asset)
        path = audio_path_for(work_dir, asset)
        head = _head_key(bucket, entry.target_key, aws_runner)
        key = entry.target_key
        if head is None:
            head = _head_key(bucket, entry.source_key, aws_runner)
            key = entry.source_key
        if head is None:
            raise ValueError(f"word pool object is missing: {entry.target_key}")
        metadata = {
            name.lower(): str(value)
            for name, value in head.get("Metadata", {}).items()
        }
        remote_sha = metadata.get("audio-sha256")

        # 파일은 한 번만 읽는다. sha·크기·검사를 각각 따로 읽으면 그 사이에 바뀐 내용이
        # 서로 다른 값으로 기록될 수 있다.
        body = path.read_bytes() if path.is_file() else None
        local_sha = hashlib.sha256(body).hexdigest() if body is not None else None
        local_fix = False
        if local_sha is None:
            _get_object(bucket, key, path, aws_runner)
            body = path.read_bytes()
            local_sha = hashlib.sha256(body).hexdigest()
            if remote_sha is not None and remote_sha != local_sha:
                raise ValueError(f"downloaded audio sha256 mismatch for key {key}")
        elif remote_sha is None:
            # S3에 audio-sha256이 없으면 로컬과 "같은지"는 알 수 없다. 그렇다고 출처까지
            # 묻지 않으면, 기록 없는 남의 파일이 그대로 검사를 통과해 합격으로 보고된다.
            # 같은지(판정 불가)와 어디서 왔는지(판정 가능)는 별개의 질문이다.
            # 1회차에는 파일이 없어 내려받고 기록을 남기므로 2회차부터 여기를 통과한다.
            previous = prior_state.get(key_id)
            if (
                previous is None
                or previous.generation_fingerprint != entry.fingerprint
                or previous.audio_sha256 != local_sha
            ):
                raise ValueError(
                    f"S3 object has no audio-sha256 and this local clip's origin is "
                    f"unknown: {path} — 내용을 대조할 수 없으니 출처라도 확실해야 한다. "
                    f"이 파일을 지우고 다시 받을 것"
                )
        elif local_sha == remote_sha:
            pass
        else:
            previous = prior_state.get(key_id)
            # 거부 사유를 뭉뚱그리면 운영자가 할 일을 못 고른다. 원인별로 나눈다.
            if previous is None:
                raise ValueError(
                    f"local clip differs from S3 and this tool has no record of it: "
                    f"{path} — 다른 배치의 작업 폴더를 재사용했을 수 있다. "
                    f"새 --work-dir을 쓰거나 이 파일을 지울 것"
                )
            if previous.audio_sha256 != local_sha:
                raise ValueError(
                    f"local clip is newer than this tool's record: {path} "
                    f"— 재합성 도중 중단됐을 수 있다. 이 파일은 지워도 안전하다"
                    f"(다시 받아 검사부터 새로 한다)"
                )
            if previous.generation_id == "s3-recovered":
                raise ValueError(
                    f"local clip was downloaded from S3 but no longer matches it: {path} "
                    f"— 파일이 바깥에서 바뀌었다. 지우고 다시 돌릴 것"
                )
            local_fix = True

        duration = validate_mp3(
            path, probe_runner=probe_runner, probe_name=probe
        ).duration_seconds
        return FetchedPoolObject(
            generated=GeneratedAsset(
                asset_id=key_id,
                expression_id=asset.expression_id,
                accent_locale=asset.accent_locale,
                kind=asset.kind,
                word_order=asset.word_order,
                generation_fingerprint=entry.fingerprint,
                path=path,
                audio_byte_size=len(body),
                audio_sha256=local_sha,
                # 내려받은 클립은 S3 객체의 generation-id를 물려받지 않고 "s3-recovered"로
                # 표시한다. 공용 풀 객체는 --metadata-directive COPY로 복사돼 원래 배치의
                # 진짜 generation-id를 달고 있어서, 그대로 쓰면 위 정체 검사의 마지막
                # 관문이 무력화된다. 그러면 다른 사람이 같은 키에 올린 최신 음성 위에
                # 내 옛 사본이 "미게시 수정본"으로 덮어써진다.
                generation_id=(
                    prior_state[key_id].generation_id if local_fix else "s3-recovered"
                ),
                duration_seconds=duration,
            ),
            remote_sha256=remote_sha,
            local_fix=local_fix,
        )

    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = [executor.submit(fetch_one, entry) for entry in entry_list]
        for future in as_completed(futures):
            item = future.result()
            fetched[item.generated.asset_id] = item
            if len(fetched) % 500 == 0:
                progress(f"fetched {len(fetched)}/{len(entry_list)}")
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    executor.shutdown(wait=True)
    return fetched


def publish_word_pool_replacement(
    bucket: str,
    entry: WordPoolEntry,
    generated: GeneratedAsset,
    *,
    execute: bool = False,
    aws_runner: Callable = subprocess.run,
) -> None:
    """재합성으로 고친 단어 음성을 공용 키에 덮어쓴다.

    키는 텍스트 해시라 내용이 바뀌어도 그대로다. 그래서 DB URL은 손대지 않아도 되지만
    CloudFront 캐시(immutable)에는 옛 소리가 남으므로 게시 뒤 무효화해야 한다.

    :raises WordPoolReplacementUnverified: put은 됐는데 게시 결과가 올린 내용과 다를 때
        (객체는 이미 바뀌어 있으므로 호출자는 이 키를 교체 목록에 넣어야 한다)
    :raises RuntimeError: put 자체가 실패했을 때 (객체는 그대로다)
    """
    upload_object = UploadObject(
        key=entry.target_key,
        body_path=generated.path,
        body_bytes=None,
        content_length=generated.audio_byte_size,
        content_type="audio/mpeg",
        cache_control=CACHE_CONTROL,
        metadata={
            "audio-sha256": generated.audio_sha256,
            "model": MODEL,
            "voice": VOICE_BY_LOCALE[entry.accent_locale],
            "generation-id": generated.generation_id,
            WORD_POOL_REPLACED_MARKER: WORD_POOL_REPLACED_VALUE,
        },
        manifest_object=False,
    )
    if not execute:
        print(f"would replace {entry.target_key}")
        return
    _put_object(
        UploadPlan(
            bucket=bucket,
            new_keys=(),
            reused_keys=(),
            conflict_keys=(),
            objects=(upload_object,),
            replace_keys=(entry.target_key,),
        ),
        upload_object,
        generated.path,
        aws_runner,
        overwrite=True,
    )
    head = _head_key(bucket, entry.target_key, aws_runner)
    if head is None or not _head_matches(upload_object, head):
        raise WordPoolReplacementUnverified(
            f"replaced object verification conflict: {entry.target_key}"
        )
    print(f"replaced {entry.target_key}")


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
        help=(
            "이미 이 버킷에 게시된 키는 합성하지 않고 내려받아 재사용한다. "
            "단어는 (억양, 단어) 공용 자리를 보므로 새 배치에서도 대부분 적중한다 — 권장"
        ),
    )
    generate_parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_GENERATE_WORKERS,
        help="동시 합성 스레드 수 (OpenRouter 429가 잦으면 줄인다)",
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
    reference_parser = subparsers.add_parser("upload-reference")
    reference_parser.add_argument("--reference-dir", required=True, type=Path)
    reference_parser.add_argument("--tts-manifest-key", required=True)
    reference_parser.add_argument("--bucket", required=True)
    reference_parser.add_argument("--execute", action="store_true")
    be_parser = subparsers.add_parser("build-be-manifest")
    be_parser.add_argument("--manifest", required=True, type=Path)
    be_parser.add_argument(
        "--source", required=True, type=Path, help="소스와 교차 검증한다"
    )
    be_parser.add_argument("--bucket", required=True)
    be_parser.add_argument("--cdn-base-url", default=DEFAULT_CDN_BASE_URL)
    be_parser.add_argument(
        "--output", type=Path, help="변환 결과를 로컬 파일로도 남긴다"
    )
    be_parser.add_argument("--execute", action="store_true")
    pool_parser = subparsers.add_parser("backfill-word-pool")
    pool_parser.add_argument("--bucket", required=True)
    pool_parser.add_argument(
        "--prefer-expression-ranges",
        default="",
        help="QA를 받은 배치의 표현 id 구간 (예: 982-1938,2259-3000). 대표 선정에 우선한다",
    )
    pool_parser.add_argument(
        "--words",
        type=Path,
        help="'<억양><탭><단어>' 줄로 된 파일. 주면 색인에 단어 텍스트를 함께 담는다",
    )
    pool_parser.add_argument(
        "--unmatched",
        choices=("stop", "drop", "keep"),
        default="stop",
        help=(
            "--words의 어떤 단어로도 만들어지지 않는 (억양, 해시)를 어떻게 할지. "
            "stop=중단(기본), drop=풀에서 빼고 계속, keep=단어 없이 풀에 넣는다"
        ),
    )
    pool_parser.add_argument(
        "--output", required=True, type=Path, help="풀 색인을 남길 로컬 경로"
    )
    pool_parser.add_argument(
        "--publish-index",
        action="store_true",
        help="풀 색인을 S3에도 게시한다 (2·3단계가 이 키를 읽는다)",
    )
    pool_parser.add_argument(
        "--verify-existing",
        action="store_true",
        help="이미 공용 자리에 있는 항목까지 원본과 전수 대조한다",
    )
    pool_parser.add_argument("--execute", action="store_true")
    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--manifest", required=True, type=Path)
    upload_parser.add_argument("--work-dir", required=True, type=Path)
    upload_parser.add_argument("--bucket", required=True)
    upload_parser.add_argument("--execute", action="store_true")
    upload_parser.add_argument(
        "--replace",
        action="store_true",
        help="내용이 바뀐 기존 키를 충돌 대신 덮어쓴다 (QA 교체용, 게시 후 CloudFront 무효화 필요)",
    )
    for s3_parser in (upload_parser, be_parser, reference_parser, pool_parser, generate_parser):
        s3_parser.add_argument(
            "--boto3",
            action="store_true",
            help="aws CLI 대신 boto3로 S3를 호출한다 (수만 개 게시 시 수십 배 빠름)",
        )
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
        if args.workers < 1:
            parser.error("--workers must be at least 1")
        generated = generate_assets(
            snapshot,
            args.work_dir,
            reuse_bucket=args.reuse_s3_bucket,
            max_workers=args.workers,
            aws_runner=Boto3AwsRunner() if args.boto3 else subprocess.run,
            progress=print,
        )
        print(f"completed={len(generated)}, failed=0")
        if args.reuse_s3_bucket is None:
            print(
                "NOTE: --reuse-s3-bucket을 주면 공용 자리에 이미 있는 단어는 합성하지 "
                "않는다. LAN-471 배치 기준 단어 16,167개 중 새로 필요한 것은 984개였다"
            )
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
    elif args.command == "upload-reference":
        published = publish_reference(
            args.reference_dir,
            args.tts_manifest_key,
            args.bucket,
            execute=args.execute,
            aws_runner=Boto3AwsRunner() if args.boto3 else subprocess.run,
        )
        print(f"reference_keys={len(published)}")
        # 사람이 BE Swagger의 manifestKey 파라미터에 복사해 넣는 키
        for key in published:
            print(f"reference_key={key}")
    elif args.command == "build-be-manifest":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        snapshot = load_source(args.source)
        be_manifest = build_be_manifest(
            manifest, snapshot, cdn_base_url=args.cdn_base_url
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = Path(f"{args.output}.part")
            temporary_path.write_bytes(canonical_manifest_bytes(be_manifest))
            os.replace(temporary_path, args.output)
        key = publish_be_manifest(
            be_manifest,
            manifest["source"]["snapshotSha256"],
            args.bucket,
            execute=args.execute,
            aws_runner=Boto3AwsRunner() if args.boto3 else subprocess.run,
        )
        print(f"expressions={len(be_manifest['assets'])}")
        # 사람이 BE Swagger의 manifestKey 파라미터에 복사해 넣는 키
        print(f"be_manifest_key={key}")
    elif args.command == "backfill-word-pool":
        aws_runner = Boto3AwsRunner() if args.boto3 else subprocess.run
        require_bucket(args.bucket, aws_runner)
        preferred = parse_expression_ranges(args.prefer_expression_ranges)
        word_texts = load_word_texts(args.words) if args.words else None
        keys = _list_existing_keys(args.bucket, f"{KEY_PREFIX}/", aws_runner)
        plan = plan_word_pool(
            keys,
            args.bucket,
            preferred_expression_ranges=preferred,
            word_texts=word_texts,
            drop_unmatched=args.unmatched == "drop",
        )
        print(
            f"legacy_word_keys={plan.legacy_key_count}, entries={len(plan.entries)}, "
            f"copy={len(plan.copy_entries)}, reused={len(plan.reused_entries)}, "
            f"qa_verified={sum(1 for e in plan.entries if e.qa_verified)}"
        )
        if plan.unmatched:
            print(f"unmatched_keys={len(plan.unmatched)} ({args.unmatched})")
            for accent_locale, fingerprint in plan.unmatched[:20]:
                print(f"unmatched {accent_locale} {fingerprint}")
            if args.unmatched == "stop":
                print(
                    "STOP: 위 (억양, 해시)는 --words의 어떤 단어로도 만들어지지 않는다. "
                    "단어 목록이 모자라거나, 예문이 수정되면서 버려진 옛 음성이다. "
                    "확인 후 --unmatched drop(풀에서 뺀다) 또는 keep(넣는다)으로 다시 돌릴 것"
                )
                return 1
        copied = execute_word_pool_backfill(
            plan,
            execute=args.execute,
            aws_runner=aws_runner,
            max_workers=32 if args.boto3 else 8,
            progress=print,
        )
        print(f"copied={copied}")
        if args.verify_existing:
            problems, replaced = verify_word_pool(
                plan, aws_runner=aws_runner, max_workers=32 if args.boto3 else 8
            )
            print(f"verify_problems={len(problems)}, qa_replaced={replaced}")
            for problem in problems:
                print(problem)
            if problems:
                return 1
        # 색인의 published는 추측이 아니라 S3 실물 목록에서 받는다. dry-run으로 만든
        # 색인을 V126 허용 목록으로 잘못 쓰면 파일 없는 URL을 허용하게 된다.
        published = frozenset(
            _list_existing_keys(
                args.bucket, f"{KEY_PREFIX}/{WORD_POOL_SEGMENT}/", aws_runner
            )
        )
        index = build_word_pool_index(
            plan, preferred, published_target_keys=published
        )
        if any("word" not in entry for entry in index["entries"]):
            print(
                "NOTE: 단어 텍스트가 없는 항목이 색인에 있다. 이 색인으로는 check-pool을 "
                "돌릴 수 없다 — 풀 QA를 하려면 --words와 --unmatched drop으로 다시 만들 것"
            )
        print(
            f"published={index['summary']['published']}/{index['summary']['entries']}"
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(f"{args.output}.part")
        temporary_path.write_bytes(canonical_manifest_bytes(index))
        os.replace(temporary_path, args.output)
        print(f"index={args.output}, index_sha256={manifest_sha256(index)}")
        if args.publish_index:
            key = publish_word_pool_index(
                index, args.bucket, execute=args.execute, aws_runner=aws_runner
            )
            print(f"word_pool_index_key={key}")
    elif args.command == "upload":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        verify_manifest(manifest, args.work_dir)
        aws_runner = Boto3AwsRunner() if args.boto3 else subprocess.run
        plan = plan_s3_upload(
            manifest,
            args.bucket,
            work_dir=args.work_dir,
            aws_runner=aws_runner,
            allow_replace=args.replace,
        )
        print(
            f"new={len(plan.new_keys)}, reused={plan.reused_count}, "
            f"replace={plan.replace_count}, conflicts={plan.conflict_count}"
        )
        for key in plan.new_keys:
            print(key)
        for key in plan.replace_keys:
            print(f"replace {key}")
        if plan.replace_keys:
            print(
                "NOTE: 교체 키는 CloudFront 캐시(immutable)에 남는다. 게시 후 "
                "무효화할 것: aws cloudfront create-invalidation --distribution-id <id> "
                "--paths <교체 키들 앞에 / 붙인 경로>"
            )
        result = execute_s3_upload(
            plan,
            execute=args.execute,
            aws_runner=aws_runner,
            max_workers=32 if args.boto3 else 12,
        )
        print(
            f"uploaded={result.uploaded}, verified={result.verified}, "
            f"conflicts={result.conflicts}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
