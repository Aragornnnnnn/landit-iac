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
import time
from typing import Callable, Mapping


VOICE_BY_CHARACTER = {
    "chloe": "aura-2-luna-en",
    "marco": "aura-2-hyperion-en",
    "teddy": "aura-2-draco-en",
}
EXPECTED_QUESTION_COUNTS = {"chloe": 9, "marco": 24, "teddy": 87}
MODEL = "deepgram/aura-2"
RESPONSE_FORMAT = "mp3"


@dataclass(frozen=True)
class SourceAsset:
    scenario_id: int
    scenario_question_id: int
    display_order: int
    character_id: str
    question_text: str


@dataclass(frozen=True)
class SourceSnapshot:
    schema_version: int
    environment: str
    target_locale: str
    base_locale: str
    assets: tuple[SourceAsset, ...]


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
            )
            for asset in payload["assets"]
        ),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate-source")
    validate_parser.add_argument("--source", required=True, type=Path)
    for command in ("generate", "verify"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--source", required=True, type=Path)
        command_parser.add_argument("--work-dir", required=True, type=Path)
        command_parser.add_argument("--sample-only", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "validate-source":
        snapshot = load_source(args.source)
        print(
            "40 scenarios, 120 questions, chloe=9, marco=24, teddy=87, "
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
        snapshot = load_source(args.source)
        verified = verify_generated_assets(
            snapshot,
            args.work_dir,
            args.sample_only,
        )
        character_by_question_id = {
            asset.scenario_question_id: asset.character_id for asset in snapshot.assets
        }
        character_counts = Counter(
            character_by_question_id[asset.scenario_question_id] for asset in verified
        )
        print(
            f"verified={len(verified)}, "
            f"chloe={character_counts['chloe']}, "
            f"marco={character_counts['marco']}, "
            f"teddy={character_counts['teddy']}, "
            f"total_bytes={sum(asset.audio_byte_size for asset in verified)}"
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
    if len(snapshot.assets) != 120:
        raise ValueError("source must contain exactly 120 questions")

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
    if dict(character_question_counts) != EXPECTED_QUESTION_COUNTS:
        raise ValueError(
            "source character question counts must be chloe=9, marco=24, teddy=87"
        )

    orders_by_scenario: dict[int, list[int]] = defaultdict(list)
    characters_by_scenario: dict[int, set[str]] = defaultdict(set)
    for asset in snapshot.assets:
        orders_by_scenario[asset.scenario_id].append(asset.display_order)
        characters_by_scenario[asset.scenario_id].add(asset.character_id)
    if any(sorted(orders) != [1, 2, 3] for orders in orders_by_scenario.values()):
        raise ValueError("each scenario must contain display orders 1, 2, and 3")
    if any(len(characters) != 1 for characters in characters_by_scenario.values()):
        raise ValueError("each scenario must use exactly one character")


if __name__ == "__main__":
    raise SystemExit(main())
