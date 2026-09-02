# production 시나리오 고정 질문을 MP3로 생성하고 immutable S3 객체로 게시한다.

from __future__ import annotations

from collections import Counter, defaultdict
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


VOICE_BY_CHARACTER = {
    "chloe": "aura-2-luna-en",
    "marco": "aura-2-hyperion-en",
    "teddy": "aura-2-draco-en",
}
EXPECTED_BATCH_CONTRACTS = {
    "LAN-351": {
        "scenario_count": 40,
        "question_count": 120,
        "character_question_counts": {"chloe": 9, "marco": 24, "teddy": 87},
        "question_level_groups": set(),
    },
    "LAN-405": {
        "scenario_count": 40,
        "question_count": 240,
        "character_question_counts": {"chloe": 18, "marco": 48, "teddy": 174},
        "question_level_groups": {"LEVEL_1", "LEVEL_2_TO_3"},
    },
}
MODEL = "deepgram/aura-2"
RESPONSE_FORMAT = "mp3"


@dataclass(frozen=True)
class SourceAsset:
    scenario_id: int
    scenario_question_id: int
    display_order: int
    character_id: str
    question_text: str
    question_level_group: str | None = None


@dataclass(frozen=True)
class SourceSnapshot:
    schema_version: int
    environment: str
    target_locale: str
    base_locale: str
    assets: tuple[SourceAsset, ...]
    issue: str = "LAN-351"


@dataclass(frozen=True)
class SpeechHttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class SpeechResponse:
    body: bytes
    generation_id: str


class PermanentTtsError(RuntimeError):
    pass


class InvalidAudioResponse(RuntimeError):
    pass


class InvalidMp3Error(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float


@dataclass(frozen=True)
class GeneratedAsset:
    scenario_question_id: int
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
    completed = probe_runner(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise InvalidMp3Error("MP3 decoder probe failed")
    try:
        if resolved_probe == "ffprobe":
            duration_seconds = float(completed.stdout.strip())
        else:
            match = re.search(
                r"estimated duration:\s*([0-9.]+)\s*sec",
                completed.stdout,
            )
            if match is None:
                raise ValueError
            duration_seconds = float(match.group(1))
    except ValueError as error:
        raise InvalidMp3Error("MP3 duration must be positive") from error
    if duration_seconds <= 0:
        raise InvalidMp3Error("MP3 duration must be positive")
    return AudioProbe(duration_seconds=duration_seconds)


def audio_path_for(work_dir: Path, asset: SourceAsset) -> Path:
    return (
        work_dir
        / "mp3"
        / f"{asset.scenario_question_id}-{generation_fingerprint(asset)}.mp3"
    )


def load_generation_state(path: Path) -> dict[str, GeneratedAsset]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise ValueError("generation state must use schema version 1")
    return {
        str(item["scenarioQuestionId"]): GeneratedAsset(
            scenario_question_id=item["scenarioQuestionId"],
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
                "scenarioQuestionId": asset.scenario_question_id,
                "generationFingerprint": asset.generation_fingerprint,
                "path": str(asset.path),
                "audioByteSize": asset.audio_byte_size,
                "audioSha256": asset.audio_sha256,
                "generationId": asset.generation_id,
                "durationSeconds": asset.duration_seconds,
            }
            for asset in sorted(
                assets.values(),
                key=lambda item: item.scenario_question_id,
            )
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.part")
    temporary_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
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
    existing = state.get(str(asset.scenario_question_id))
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
            expected_path,
            probe_runner=probe_runner,
            probe_name=probe_name,
        )
    except InvalidMp3Error:
        return None
    return GeneratedAsset(
        scenario_question_id=existing.scenario_question_id,
        generation_fingerprint=existing.generation_fingerprint,
        path=existing.path,
        audio_byte_size=existing.audio_byte_size,
        audio_sha256=existing.audio_sha256,
        generation_id=existing.generation_id,
        duration_seconds=probe.duration_seconds,
    )


def generate_assets(
    snapshot: SourceSnapshot,
    work_dir: Path,
    sample_only: bool,
    *,
    client: OpenRouterSpeechClient | None = None,
    probe_runner: Callable = subprocess.run,
    probe_name: str | None = None,
) -> list[GeneratedAsset]:
    resolved_probe = probe_name or resolve_probe()
    speech_client = client or OpenRouterSpeechClient(os.environ["OPENROUTER_API_KEY"])
    selected_ids = select_sample_ids(snapshot) if sample_only else None
    target_assets = [
        asset
        for asset in snapshot.assets
        if selected_ids is None or asset.scenario_question_id in selected_ids
    ]
    state_path = work_dir / "state.json"
    state = load_generation_state(state_path)
    completed: dict[str, GeneratedAsset] = {}
    pending = []
    for asset in target_assets:
        existing = _verified_existing_asset(
            asset,
            work_dir,
            state,
            probe_runner,
            resolved_probe,
        )
        if existing is None:
            pending.append(asset)
        else:
            completed[str(asset.scenario_question_id)] = existing

    def generate_one(asset: SourceAsset) -> GeneratedAsset:
        response = speech_client.synthesize(asset)
        final_path = audio_path_for(work_dir, asset)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(f"{final_path}.part")
        try:
            temporary_path.write_bytes(response.body)
            probe = validate_mp3(
                temporary_path,
                probe_runner=probe_runner,
                probe_name=resolved_probe,
            )
            audio_sha256 = hashlib.sha256(response.body).hexdigest()
            os.replace(temporary_path, final_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        return GeneratedAsset(
            scenario_question_id=asset.scenario_question_id,
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
            key = str(generated.scenario_question_id)
            completed[key] = generated
            state[key] = generated
            write_generation_state(state_path, state)

    if pending or any(
        state.get(key) != value for key, value in completed.items()
    ):
        state.update(completed)
        write_generation_state(state_path, state)
    return sorted(completed.values(), key=lambda item: item.scenario_question_id)


def verify_generated_assets(
    snapshot: SourceSnapshot,
    work_dir: Path,
    sample_only: bool,
    *,
    probe_runner: Callable = subprocess.run,
    probe_name: str | None = None,
) -> list[GeneratedAsset]:
    resolved_probe = probe_name or resolve_probe()
    selected_ids = select_sample_ids(snapshot) if sample_only else None
    target_assets = [
        asset
        for asset in snapshot.assets
        if selected_ids is None or asset.scenario_question_id in selected_ids
    ]
    state = load_generation_state(work_dir / "state.json")
    verified = [
        generated
        for asset in target_assets
        if (
            generated := _verified_existing_asset(
                asset,
                work_dir,
                state,
                probe_runner,
                resolved_probe,
            )
        )
        is not None
    ]
    if len(verified) != len(target_assets):
        raise InvalidMp3Error(
            f"expected {len(target_assets)} generated assets, verified {len(verified)}"
        )
    return sorted(verified, key=lambda item: item.scenario_question_id)


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
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        connection.request(
            "POST",
            "/api/v1/audio/speech",
            body=body,
            headers=headers,
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
            "input": asset.question_text,
            "voice": VOICE_BY_CHARACTER[asset.character_id],
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
                    raise RuntimeError("OpenRouter TTS connection failed after 4 attempts") from error
                self._sleep((2**attempt) + self._jitter())
                continue
            if result.status == 200:
                normalized_headers = {
                    key.lower(): value for key, value in result.headers.items()
                }
                content_type = normalized_headers.get("content-type", "").split(";", 1)[0]
                generation_id = normalized_headers.get("x-generation-id", "").strip()
                if content_type != "audio/mpeg" or not result.body or not generation_id:
                    raise InvalidAudioResponse("OpenRouter returned an invalid MP3 response")
                return SpeechResponse(
                    body=result.body,
                    generation_id=generation_id,
                )
            if result.status not in {429, 500, 502, 503}:
                raise PermanentTtsError(
                    f"OpenRouter TTS rejected the request with HTTP {result.status}"
                )
            if attempt == 3:
                raise RuntimeError(f"OpenRouter TTS failed with HTTP {result.status}")
            self._sleep((2**attempt) + self._jitter())
        raise RuntimeError("OpenRouter TTS retry loop ended unexpectedly")


def load_source(path: Path) -> SourceSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    snapshot = SourceSnapshot(
        schema_version=payload["schemaVersion"],
        environment=payload["environment"],
        target_locale=payload["targetLocale"],
        base_locale=payload["baseLocale"],
        assets=tuple(
            SourceAsset(
                scenario_id=asset["scenarioId"],
                scenario_question_id=asset["scenarioQuestionId"],
                display_order=asset["displayOrder"],
                character_id=asset["characterId"],
                question_text=asset["questionText"],
                question_level_group=asset.get("questionLevelGroup"),
            )
            for asset in payload["assets"]
        ),
        issue=payload.get("issue", "LAN-351"),
    )
    validate_source(snapshot)
    return snapshot


def generation_contract(asset: SourceAsset) -> dict[str, str]:
    return {
        "model": MODEL,
        "providerVoiceId": VOICE_BY_CHARACTER[asset.character_id],
        "questionText": asset.question_text,
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


def select_sample_ids(snapshot: SourceSnapshot) -> set[int]:
    assets_by_character: dict[str, list[SourceAsset]] = defaultdict(list)
    for asset in snapshot.assets:
        assets_by_character[asset.character_id].append(asset)

    selected = set()
    for character_id in VOICE_BY_CHARACTER:
        assets = sorted(
            assets_by_character[character_id],
            key=lambda asset: (
                len(asset.question_text.encode("utf-8")),
                asset.scenario_question_id,
            ),
        )
        selected.add(assets[len(assets) // 2].scenario_question_id)
    return selected


def source_sha256(snapshot: SourceSnapshot) -> str:
    payload = {
        "schemaVersion": snapshot.schema_version,
        "environment": snapshot.environment,
        "targetLocale": snapshot.target_locale,
        "baseLocale": snapshot.base_locale,
        "assets": [
            {
                "scenarioId": asset.scenario_id,
                "scenarioQuestionId": asset.scenario_question_id,
                "displayOrder": asset.display_order,
                "characterId": asset.character_id,
                "questionText": asset.question_text,
                **(
                    {"questionLevelGroup": asset.question_level_group}
                    if asset.question_level_group is not None
                    else {}
                ),
            }
            for asset in sorted(
                snapshot.assets,
                key=lambda item: (
                    item.scenario_id,
                    item.display_order,
                    item.scenario_question_id,
                ),
            )
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_manifest(
    snapshot: SourceSnapshot,
    generated_assets: list[GeneratedAsset],
) -> dict:
    validate_source(snapshot)
    contract = EXPECTED_BATCH_CONTRACTS[snapshot.issue]
    expected_question_count = contract["question_count"]
    if len(generated_assets) != expected_question_count:
        raise ValueError(
            f"manifest requires exactly {expected_question_count} generated assets"
        )
    generated_by_question_id = {
        asset.scenario_question_id: asset for asset in generated_assets
    }
    source_question_ids = {
        asset.scenario_question_id for asset in snapshot.assets
    }
    if (
        len(generated_by_question_id) != expected_question_count
        or set(generated_by_question_id) != source_question_ids
    ):
        raise ValueError(
            f"manifest requires exactly {expected_question_count} generated assets"
        )

    manifest_assets = []
    for source_asset in sorted(
        snapshot.assets,
        key=lambda item: (
            item.scenario_id,
            item.display_order,
            item.scenario_question_id,
        ),
    ):
        generated = generated_by_question_id[source_asset.scenario_question_id]
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
                "scenarioId": source_asset.scenario_id,
                "scenarioQuestionId": source_asset.scenario_question_id,
                "displayOrder": source_asset.display_order,
                "characterId": source_asset.character_id,
                "questionText": source_asset.question_text,
                **(
                    {"questionLevelGroup": source_asset.question_level_group}
                    if source_asset.question_level_group is not None
                    else {}
                ),
                "model": MODEL,
                "providerVoiceId": VOICE_BY_CHARACTER[source_asset.character_id],
                "responseFormat": RESPONSE_FORMAT,
                "generationFingerprint": expected_fingerprint,
                "s3Key": (
                    "content/scenario-question-audio/"
                    f"{source_asset.scenario_question_id}/{expected_fingerprint}.mp3"
                ),
                "audioByteSize": generated.audio_byte_size,
                "audioSha256": generated.audio_sha256,
                "openRouterGenerationId": generated.generation_id,
            }
        )
    return {
        "schemaVersion": 1,
        "issue": snapshot.issue,
        "source": {
            "environment": snapshot.environment,
            "targetLocale": snapshot.target_locale,
            "baseLocale": snapshot.base_locale,
            "snapshotSha256": source_sha256(snapshot),
            "scenarioCount": contract["scenario_count"],
            "questionCount": expected_question_count,
        },
        "assets": manifest_assets,
    }


def canonical_manifest_bytes(manifest: dict) -> bytes:
    return (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def manifest_sha256(manifest: dict) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def verify_manifest(manifest: dict, work_dir: Path) -> None:
    issue = manifest.get("issue")
    contract = EXPECTED_BATCH_CONTRACTS.get(issue)
    if contract is None:
        raise ValueError("manifest issue is unsupported")
    expected_question_count = contract["question_count"]
    if (
        manifest.get("schemaVersion") != 1
        or manifest.get("source", {}).get("scenarioCount")
        != contract["scenario_count"]
        or manifest.get("source", {}).get("questionCount")
        != expected_question_count
        or len(manifest.get("assets", [])) != expected_question_count
    ):
        raise ValueError(
            f"manifest must contain exactly {expected_question_count} generated assets"
        )
    question_ids = [asset["scenarioQuestionId"] for asset in manifest["assets"]]
    if len(set(question_ids)) != expected_question_count:
        raise ValueError("manifest contains duplicate question ids")
    snapshot = SourceSnapshot(
        schema_version=1,
        environment=manifest["source"]["environment"],
        target_locale=manifest["source"]["targetLocale"],
        base_locale=manifest["source"]["baseLocale"],
        assets=tuple(
            SourceAsset(
                scenario_id=asset["scenarioId"],
                scenario_question_id=asset["scenarioQuestionId"],
                display_order=asset["displayOrder"],
                character_id=asset["characterId"],
                question_text=asset["questionText"],
                question_level_group=asset.get("questionLevelGroup"),
            )
            for asset in manifest["assets"]
        ),
        issue=issue,
    )
    validate_source(snapshot)
    if source_sha256(snapshot) != manifest["source"]["snapshotSha256"]:
        raise ValueError("manifest source sha256 mismatch")
    source_assets_by_question_id = {
        asset.scenario_question_id: asset for asset in snapshot.assets
    }
    for asset in manifest["assets"]:
        source_asset = source_assets_by_question_id[asset["scenarioQuestionId"]]
        fingerprint = asset["generationFingerprint"]
        if (
            asset["model"] != MODEL
            or asset["providerVoiceId"]
            != VOICE_BY_CHARACTER[source_asset.character_id]
            or asset["responseFormat"] != RESPONSE_FORMAT
            or fingerprint != generation_fingerprint(source_asset)
        ):
            raise ValueError("manifest generation contract mismatch")
        expected_key = (
            "content/scenario-question-audio/"
            f"{asset['scenarioQuestionId']}/{fingerprint}.mp3"
        )
        if asset["s3Key"] != expected_key:
            raise ValueError("manifest s3 key mismatch")
        audio_path = (
            work_dir
            / "mp3"
            / f"{asset['scenarioQuestionId']}-{fingerprint}.mp3"
        )
        if not audio_path.is_file():
            raise ValueError("manifest audio file is missing")
        audio_bytes = audio_path.read_bytes()
        if hashlib.sha256(audio_bytes).hexdigest() != asset["audioSha256"]:
            raise ValueError("audio sha256 mismatch")
        if len(audio_bytes) != asset["audioByteSize"]:
            raise ValueError("audio byte size mismatch")


def _upload_objects(manifest: dict, work_dir: Path) -> tuple[UploadObject, ...]:
    cache_control = "public, max-age=31536000, immutable"
    source_sha = manifest["source"]["snapshotSha256"]
    objects = [
        UploadObject(
            key=asset["s3Key"],
            body_path=(
                work_dir
                / "mp3"
                / (
                    f"{asset['scenarioQuestionId']}-"
                    f"{asset['generationFingerprint']}.mp3"
                )
            ),
            body_bytes=None,
            content_length=asset["audioByteSize"],
            content_type="audio/mpeg",
            cache_control=cache_control,
            metadata={
                "source-sha256": source_sha,
                "audio-sha256": asset["audioSha256"],
                "model": asset["model"],
                "voice": asset["providerVoiceId"],
            },
            manifest_object=False,
        )
        for asset in manifest["assets"]
    ]
    manifest_body = canonical_manifest_bytes(manifest)
    digest = manifest_sha256(manifest)
    objects.append(
        UploadObject(
            key=f"content/scenario-question-audio/manifests/{digest}.json",
            body_path=None,
            body_bytes=manifest_body,
            content_length=len(manifest_body),
            content_type="application/json",
            cache_control=cache_control,
            metadata={
                "source-sha256": source_sha,
                "manifest-sha256": digest,
            },
            manifest_object=True,
        )
    )
    return tuple(objects)


def _head_object(
    bucket: str,
    upload_object: UploadObject,
    aws_runner: Callable,
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
    missing_markers = ("404", "Not Found", "NoSuchKey")
    if any(marker in completed.stderr for marker in missing_markers):
        return None
    raise RuntimeError(
        f"S3 head-object failed for key {upload_object.key}"
    )


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


def plan_s3_upload(
    manifest: dict,
    bucket: str,
    *,
    work_dir: Path = Path("."),
    aws_runner: Callable = subprocess.run,
) -> UploadPlan:
    objects = _upload_objects(manifest, work_dir)
    new_keys = []
    reused_keys = []
    conflict_keys = []
    for upload_object in objects:
        head = _head_object(bucket, upload_object, aws_runner)
        if head is None:
            new_keys.append(upload_object.key)
        elif _head_matches(upload_object, head):
            reused_keys.append(upload_object.key)
        else:
            conflict_keys.append(upload_object.key)
    if conflict_keys:
        raise ValueError(
            "existing object conflict: " + ", ".join(conflict_keys)
        )
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
        raise RuntimeError(
            f"S3 put-object failed for key {upload_object.key}"
        )


def execute_s3_upload(
    plan: UploadPlan,
    *,
    execute: bool = False,
    aws_runner: Callable = subprocess.run,
) -> UploadResult:
    if not execute:
        return UploadResult(
            uploaded=0,
            verified=plan.reused_count,
            conflicts=plan.conflict_count,
        )

    objects_by_key = {item.key: item for item in plan.objects}
    new_objects = [objects_by_key[key] for key in plan.new_keys]
    ordered_new_objects = sorted(
        new_objects,
        key=lambda item: item.manifest_object,
    )
    uploaded = 0
    verified = plan.reused_count
    for upload_object in ordered_new_objects:
        temporary_manifest_path = None
        body_path = upload_object.body_path
        if upload_object.body_bytes is not None:
            with tempfile.NamedTemporaryFile(
                prefix="lan-351-manifest-",
                suffix=".json",
                delete=False,
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
    return UploadResult(
        uploaded=uploaded,
        verified=verified,
        conflicts=0,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate-source")
    validate_parser.add_argument("--source", required=True, type=Path)
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--source", required=True, type=Path)
    generate_parser.add_argument("--work-dir", required=True, type=Path)
    generate_parser.add_argument("--sample-only", action="store_true")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--source", type=Path)
    verify_parser.add_argument("--manifest", type=Path)
    verify_parser.add_argument("--work-dir", required=True, type=Path)
    verify_parser.add_argument("--sample-only", action="store_true")
    build_manifest_parser = subparsers.add_parser("build-manifest")
    build_manifest_parser.add_argument("--source", required=True, type=Path)
    build_manifest_parser.add_argument("--work-dir", required=True, type=Path)
    build_manifest_parser.add_argument("--output", required=True, type=Path)
    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--manifest", required=True, type=Path)
    upload_parser.add_argument("--work-dir", required=True, type=Path)
    upload_parser.add_argument("--bucket", required=True)
    upload_parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "validate-source":
        snapshot = load_source(args.source)
        character_counts = Counter(asset.character_id for asset in snapshot.assets)
        print(
            f"{len({asset.scenario_id for asset in snapshot.assets})} scenarios, "
            f"{len(snapshot.assets)} questions, "
            f"chloe={character_counts['chloe']}, "
            f"marco={character_counts['marco']}, "
            f"teddy={character_counts['teddy']}, "
            f"source_sha256={source_sha256(snapshot)}"
        )
    elif args.command == "generate":
        snapshot = load_source(args.source)
        generated = generate_assets(
            snapshot,
            args.work_dir,
            args.sample_only,
        )
        print(f"completed={len(generated)}, failed=0")
    elif args.command == "verify":
        if not args.source and not args.manifest:
            parser.error("verify requires --source, --manifest, or both")
        if args.manifest and args.sample_only:
            parser.error("--sample-only cannot be used with --manifest")
        if args.source:
            snapshot = load_source(args.source)
            verified = verify_generated_assets(
                snapshot,
                args.work_dir,
                args.sample_only,
            )
            character_by_question_id = {
                asset.scenario_question_id: asset.character_id
                for asset in snapshot.assets
            }
            character_counts = Counter(
                character_by_question_id[asset.scenario_question_id]
                for asset in verified
            )
            print(
                f"verified={len(verified)}, "
                f"chloe={character_counts['chloe']}, "
                f"marco={character_counts['marco']}, "
                f"teddy={character_counts['teddy']}, "
                f"total_bytes={sum(asset.audio_byte_size for asset in verified)}"
            )
        if args.manifest:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            verify_manifest(manifest, args.work_dir)
            print(
                f"manifest_assets={len(manifest['assets'])}, "
                f"manifest_sha256={manifest_sha256(manifest)}"
            )
    elif args.command == "build-manifest":
        snapshot = load_source(args.source)
        generated = verify_generated_assets(snapshot, args.work_dir, False)
        manifest = build_manifest(snapshot, generated)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(f"{args.output}.part")
        temporary_path.write_bytes(canonical_manifest_bytes(manifest))
        os.replace(temporary_path, args.output)
        print(
            f"assets={len(manifest['assets'])}, "
            f"manifest_sha256={manifest_sha256(manifest)}, "
            f"output={args.output}"
        )
    elif args.command == "upload":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        verify_manifest(manifest, args.work_dir)
        plan = plan_s3_upload(
            manifest,
            args.bucket,
            work_dir=args.work_dir,
        )
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


def validate_source(snapshot: SourceSnapshot) -> None:
    if (
        snapshot.schema_version != 1
        or snapshot.environment != "production"
        or snapshot.target_locale != "EN"
        or snapshot.base_locale != "KR"
    ):
        raise ValueError("source must use schema version 1 and production EN/KR metadata")
    contract = EXPECTED_BATCH_CONTRACTS.get(snapshot.issue)
    if contract is None:
        raise ValueError("source issue is unsupported")
    expected_question_count = contract["question_count"]
    if len(snapshot.assets) != expected_question_count:
        raise ValueError(
            f"source must contain exactly {expected_question_count} questions"
        )

    question_ids = [asset.scenario_question_id for asset in snapshot.assets]
    if len(set(question_ids)) != len(question_ids):
        raise ValueError("source contains a duplicate question id")
    if any(not asset.question_text.strip() for asset in snapshot.assets):
        raise ValueError("source contains a blank question text")

    unsupported_characters = {
        asset.character_id
        for asset in snapshot.assets
        if asset.character_id not in VOICE_BY_CHARACTER
    }
    if unsupported_characters:
        raise ValueError(
            f"source contains an unsupported character: {sorted(unsupported_characters)}"
        )

    character_question_counts = Counter(
        asset.character_id for asset in snapshot.assets
    )
    if dict(character_question_counts) != contract["character_question_counts"]:
        raise ValueError(
            "source character question counts do not match the batch contract"
        )

    orders_by_scenario_and_group: dict[tuple[int, str | None], list[int]] = defaultdict(
        list
    )
    groups_by_scenario: dict[int, set[str | None]] = defaultdict(set)
    characters_by_scenario: dict[int, set[str]] = defaultdict(set)
    for asset in snapshot.assets:
        key = (asset.scenario_id, asset.question_level_group)
        orders_by_scenario_and_group[key].append(asset.display_order)
        groups_by_scenario[asset.scenario_id].add(asset.question_level_group)
        characters_by_scenario[asset.scenario_id].add(asset.character_id)
    if len(groups_by_scenario) != contract["scenario_count"]:
        raise ValueError("source scenario count does not match the batch contract")
    if any(
        sorted(orders) != [1, 2, 3]
        for orders in orders_by_scenario_and_group.values()
    ):
        raise ValueError(
            "each scenario and question level group must contain display orders 1, 2, and 3"
        )
    expected_groups = contract["question_level_groups"]
    if expected_groups:
        if any(groups != expected_groups for groups in groups_by_scenario.values()):
            raise ValueError("each scenario must contain every question level group")
    elif any(groups != {None} for groups in groups_by_scenario.values()):
        raise ValueError("this batch does not support question level groups")
    if any(len(characters) != 1 for characters in characters_by_scenario.values()):
        raise ValueError("each scenario must use exactly one character")


if __name__ == "__main__":
    raise SystemExit(main())
