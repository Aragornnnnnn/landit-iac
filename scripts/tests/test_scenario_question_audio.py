# LAN-351 고정 질문 오디오 배치 도구의 계약을 검증한다.

import unittest
from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import Mock, patch

from scripts.scenario_question_audio import (
    GeneratedAsset,
    InvalidAudioResponse,
    InvalidMp3Error,
    OpenRouterSpeechClient,
    PermanentTtsError,
    SpeechHttpResult,
    SourceAsset,
    SourceSnapshot,
    SpeechResponse,
    audio_path_for,
    build_manifest,
    canonical_manifest_bytes,
    execute_s3_upload,
    generate_assets,
    generation_fingerprint,
    load_source,
    load_generation_state,
    main,
    manifest_sha256,
    plan_s3_upload,
    request_speech,
    resolve_probe,
    select_sample_ids,
    validate_source,
    validate_mp3,
    verify_manifest,
    verify_generated_assets,
)


def make_valid_snapshot() -> SourceSnapshot:
    assets = []
    question_id = 1
    scenario_id = 1
    for character_id, scenario_count in (("chloe", 3), ("marco", 8), ("teddy", 29)):
        for _ in range(scenario_count):
            for order in (1, 2, 3):
                assets.append(
                    SourceAsset(
                        scenario_id=scenario_id,
                        scenario_question_id=question_id,
                        display_order=order,
                        character_id=character_id,
                        question_text=f"Question {question_id}?",
                    )
                )
                question_id += 1
            scenario_id += 1
    return SourceSnapshot(
        schema_version=1,
        environment="production",
        target_locale="EN",
        base_locale="KR",
        assets=tuple(assets),
    )


def snapshot_payload(snapshot: SourceSnapshot) -> dict:
    return {
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
            for asset in snapshot.assets
        ],
    }


def successful_probe(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        ["afinfo", "audio.mp3"],
        0,
        "estimated duration: 1.25 sec\n",
        "",
    )


def seed_verified_generation_state(
    work_dir: Path,
    asset: SourceAsset,
    body: bytes,
) -> GeneratedAsset:
    path = audio_path_for(work_dir, asset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    generated = GeneratedAsset(
        scenario_question_id=asset.scenario_question_id,
        generation_fingerprint=generation_fingerprint(asset),
        path=path,
        audio_byte_size=len(body),
        audio_sha256=hashlib.sha256(body).hexdigest(),
        generation_id="seed-generation",
        duration_seconds=1.25,
    )
    existing_assets = []
    state_path = work_dir / "state.json"
    if state_path.exists():
        existing_assets = json.loads(state_path.read_text(encoding="utf-8"))["assets"]
    existing_assets = [
        item
        for item in existing_assets
        if item["scenarioQuestionId"] != generated.scenario_question_id
    ]
    state_payload = {
        "schemaVersion": 1,
        "assets": existing_assets + [
            {
                "scenarioQuestionId": generated.scenario_question_id,
                "generationFingerprint": generated.generation_fingerprint,
                "path": str(generated.path),
                "audioByteSize": generated.audio_byte_size,
                "audioSha256": generated.audio_sha256,
                "generationId": generated.generation_id,
                "durationSeconds": generated.duration_seconds,
            }
        ],
    }
    state_path.write_text(
        json.dumps(state_payload),
        encoding="utf-8",
    )
    return generated


def make_generated_assets(
    snapshot: SourceSnapshot | None = None,
    work_dir: Path = Path("/tmp/lan-351-test"),
) -> list[GeneratedAsset]:
    source = snapshot or make_valid_snapshot()
    return [
        GeneratedAsset(
            scenario_question_id=asset.scenario_question_id,
            generation_fingerprint=generation_fingerprint(asset),
            path=audio_path_for(work_dir, asset),
            audio_byte_size=len(f"ID3audio-{asset.scenario_question_id}".encode()),
            audio_sha256=hashlib.sha256(
                f"ID3audio-{asset.scenario_question_id}".encode()
            ).hexdigest(),
            generation_id=f"generation-{asset.scenario_question_id}",
            duration_seconds=1.25,
        )
        for asset in source.assets
    ]


def seed_full_manifest(work_dir: Path) -> tuple[SourceSnapshot, list[GeneratedAsset], dict]:
    snapshot = make_valid_snapshot()
    generated_assets = make_generated_assets(snapshot, work_dir)
    for generated in generated_assets:
        generated.path.parent.mkdir(parents=True, exist_ok=True)
        generated.path.write_bytes(
            f"ID3audio-{generated.scenario_question_id}".encode()
        )
    manifest = build_manifest(snapshot, generated_assets)
    return snapshot, generated_assets, manifest


def valid_manifest() -> dict:
    return build_manifest(make_valid_snapshot(), make_generated_assets())


def matching_head_results(manifest: dict) -> dict[str, dict]:
    source_sha = manifest["source"]["snapshotSha256"]
    results = {
        asset["s3Key"]: {
            "ContentLength": asset["audioByteSize"],
            "ContentType": "audio/mpeg",
            "CacheControl": "public, max-age=31536000, immutable",
            "Metadata": {
                "source-sha256": source_sha,
                "audio-sha256": asset["audioSha256"],
                "model": asset["model"],
                "voice": asset["providerVoiceId"],
            },
        }
        for asset in manifest["assets"]
    }
    digest = manifest_sha256(manifest)
    results[f"content/scenario-question-audio/manifests/{digest}.json"] = {
        "ContentLength": len(canonical_manifest_bytes(manifest)),
        "ContentType": "application/json",
        "CacheControl": "public, max-age=31536000, immutable",
        "Metadata": {
            "source-sha256": source_sha,
            "manifest-sha256": digest,
        },
    }
    return results


class RecordingAwsRunner:
    def __init__(self, head_results: dict[str, dict]) -> None:
        self.head_results = head_results.copy()
        self.expected_results = matching_head_results(valid_manifest())
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(command)
        key = command[command.index("--key") + 1]
        if "head-object" in command:
            if key not in self.head_results:
                return subprocess.CompletedProcess(command, 254, "", "Not Found")
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(self.head_results[key]),
                "",
            )
        if "put-object" in command:
            self.head_results[key] = self.expected_results[key]
            return subprocess.CompletedProcess(command, 0, "{}", "")
        raise AssertionError(f"unexpected AWS command: {command}")


class SourceContractTests(unittest.TestCase):
    def test_validate_source_rejects_wrong_question_count(self) -> None:
        snapshot = make_valid_snapshot()
        invalid = replace(snapshot, assets=snapshot.assets[:-1])

        with self.assertRaisesRegex(ValueError, "120 questions"):
            validate_source(invalid)

    def test_validate_source_rejects_missing_display_order(self) -> None:
        snapshot = make_valid_snapshot()
        changed = replace(snapshot.assets[0], display_order=2)
        invalid = replace(snapshot, assets=(changed,) + snapshot.assets[1:])

        with self.assertRaisesRegex(ValueError, "display orders"):
            validate_source(invalid)

    def test_validate_source_rejects_duplicate_question_id(self) -> None:
        snapshot = make_valid_snapshot()
        duplicate = replace(snapshot.assets[1], scenario_question_id=1)
        invalid = replace(
            snapshot,
            assets=(snapshot.assets[0], duplicate) + snapshot.assets[2:],
        )

        with self.assertRaisesRegex(ValueError, "duplicate question id"):
            validate_source(invalid)

    def test_validate_source_rejects_unknown_character(self) -> None:
        snapshot = make_valid_snapshot()
        unknown = replace(snapshot.assets[0], character_id="unknown")
        invalid = replace(snapshot, assets=(unknown,) + snapshot.assets[1:])

        with self.assertRaisesRegex(ValueError, "unsupported character"):
            validate_source(invalid)

    def test_validate_source_rejects_wrong_character_distribution(self) -> None:
        snapshot = make_valid_snapshot()
        changed = replace(snapshot.assets[0], character_id="marco")
        invalid = replace(snapshot, assets=(changed,) + snapshot.assets[1:])

        with self.assertRaisesRegex(ValueError, "character question counts"):
            validate_source(invalid)

    def test_validate_source_rejects_mixed_characters_in_scenario(self) -> None:
        snapshot = make_valid_snapshot()
        chloe = replace(snapshot.assets[0], character_id="marco")
        marco = replace(snapshot.assets[9], character_id="chloe")
        assets = list(snapshot.assets)
        assets[0] = chloe
        assets[9] = marco

        with self.assertRaisesRegex(ValueError, "one character"):
            validate_source(replace(snapshot, assets=tuple(assets)))

    def test_validate_source_rejects_blank_question_text(self) -> None:
        snapshot = make_valid_snapshot()
        blank = replace(snapshot.assets[0], question_text="  ")

        with self.assertRaisesRegex(ValueError, "blank question text"):
            validate_source(replace(snapshot, assets=(blank,) + snapshot.assets[1:]))

    def test_validate_source_rejects_wrong_snapshot_metadata(self) -> None:
        snapshot = replace(make_valid_snapshot(), environment="develop")

        with self.assertRaisesRegex(ValueError, "production EN/KR"):
            validate_source(snapshot)

    def test_generation_fingerprint_changes_with_text_or_voice(self) -> None:
        asset = make_valid_snapshot().assets[0]
        changed_text = replace(asset, question_text="A different question?")
        changed_voice = replace(asset, character_id="marco")

        fingerprint = generation_fingerprint(asset)

        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(fingerprint, generation_fingerprint(asset))
        self.assertNotEqual(fingerprint, generation_fingerprint(changed_text))
        self.assertNotEqual(fingerprint, generation_fingerprint(changed_voice))

    def test_select_samples_uses_median_utf8_length_per_character(self) -> None:
        selected = select_sample_ids(make_valid_snapshot())

        self.assertEqual({5, 22, 77}, selected)

    def test_load_source_parses_camel_case_json(self) -> None:
        snapshot = make_valid_snapshot()
        payload = snapshot_payload(snapshot)
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.json"
            source_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = load_source(source_path)

        self.assertEqual(snapshot, loaded)

    def test_validate_source_cli_reports_counts_and_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.json"
            source_path.write_text(
                json.dumps(snapshot_payload(make_valid_snapshot())),
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(["validate-source", "--source", str(source_path)])

        self.assertEqual(0, exit_code)
        self.assertIn("40 scenarios, 120 questions", output.getvalue())
        self.assertIn("chloe=9, marco=24, teddy=87", output.getvalue())
        self.assertRegex(output.getvalue(), r"source_sha256=[0-9a-f]{64}")


class OpenRouterSpeechClientTests(unittest.TestCase):
    def test_default_requester_posts_json_with_separate_timeouts(self) -> None:
        calls = {}

        class FakeSocket:
            def settimeout(self, value):
                calls["socket_timeout"] = value

        class FakeResponse:
            status = 200

            @staticmethod
            def getheaders():
                return [("Content-Type", "audio/mpeg"), ("X-Generation-Id", "g-1")]

            @staticmethod
            def read():
                return b"ID3audio"

        class FakeConnection:
            def __init__(self, host, timeout):
                calls["host"] = host
                calls["connect_timeout"] = timeout
                self.sock = FakeSocket()

            def connect(self):
                calls["connected"] = True

            def request(self, method, path, body, headers):
                calls["request"] = (method, path, body, headers)

            @staticmethod
            def getresponse():
                return FakeResponse()

            def close(self):
                calls["closed"] = True

        result = request_speech(
            {"model": "deepgram/aura-2"},
            {"Authorization": "Bearer secret-key"},
            10,
            120,
            connection_factory=FakeConnection,
        )

        self.assertEqual("openrouter.ai", calls["host"])
        self.assertEqual(10, calls["connect_timeout"])
        self.assertEqual(120, calls["socket_timeout"])
        self.assertEqual("POST", calls["request"][0])
        self.assertEqual("/api/v1/audio/speech", calls["request"][1])
        self.assertEqual(b'{"model":"deepgram/aura-2"}', calls["request"][2])
        self.assertTrue(calls["closed"])
        self.assertEqual(200, result.status)
        self.assertEqual(b"ID3audio", result.body)

    def test_sends_exact_tts_contract_and_returns_binary_metadata(self) -> None:
        calls = []

        def requester(payload, headers, connect_timeout, total_timeout):
            calls.append((payload, headers, connect_timeout, total_timeout))
            return SpeechHttpResult(
                status=200,
                headers={
                    "Content-Type": "audio/mpeg",
                    "X-Generation-Id": "generation-1",
                },
                body=b"ID3audio",
            )

        response = OpenRouterSpeechClient(
            "secret-key",
            requester=requester,
        ).synthesize(make_valid_snapshot().assets[0])

        self.assertEqual("generation-1", response.generation_id)
        self.assertEqual(b"ID3audio", response.body)
        self.assertEqual(
            {
                "model": "deepgram/aura-2",
                "input": "Question 1?",
                "voice": "aura-2-luna-en",
                "response_format": "mp3",
            },
            calls[0][0],
        )
        self.assertEqual("Bearer secret-key", calls[0][1]["Authorization"])
        self.assertEqual(10, calls[0][2])
        self.assertEqual(120, calls[0][3])

    def test_retries_429_then_succeeds_on_fourth_attempt(self) -> None:
        results = iter(
            [
                SpeechHttpResult(429, {}, b"rate limited"),
                SpeechHttpResult(429, {}, b"rate limited"),
                SpeechHttpResult(429, {}, b"rate limited"),
                SpeechHttpResult(
                    200,
                    {
                        "Content-Type": "audio/mpeg",
                        "X-Generation-Id": "generation-4",
                    },
                    b"ID3audio",
                ),
            ]
        )
        sleeps = []
        client = OpenRouterSpeechClient(
            "secret-key",
            requester=lambda *args: next(results),
            sleep=sleeps.append,
            jitter=lambda: 0.5,
        )

        response = client.synthesize(make_valid_snapshot().assets[0])

        self.assertEqual("generation-4", response.generation_id)
        self.assertEqual([1.5, 2.5, 4.5], sleeps)

    def test_does_not_retry_permanent_errors_or_expose_key(self) -> None:
        for status in (400, 401, 402, 404):
            calls = []

            def requester(*args):
                calls.append(status)
                return SpeechHttpResult(status, {}, b"request failed")

            client = OpenRouterSpeechClient("secret-key", requester=requester)

            with self.assertRaises(PermanentTtsError) as caught:
                client.synthesize(make_valid_snapshot().assets[0])

            self.assertEqual([status], calls)
            self.assertNotIn("secret-key", str(caught.exception))

    def test_retries_connection_error_then_succeeds(self) -> None:
        calls = []

        def requester(*args):
            calls.append(None)
            if len(calls) == 1:
                raise TimeoutError("connection timed out")
            return SpeechHttpResult(
                200,
                {
                    "Content-Type": "audio/mpeg",
                    "X-Generation-Id": "generation-2",
                },
                b"ID3audio",
            )

        client = OpenRouterSpeechClient(
            "secret-key",
            requester=requester,
            sleep=lambda seconds: None,
            jitter=lambda: 0,
        )

        response = client.synthesize(make_valid_snapshot().assets[0])

        self.assertEqual("generation-2", response.generation_id)
        self.assertEqual(2, len(calls))

    def test_rejects_invalid_success_response(self) -> None:
        invalid_results = (
            SpeechHttpResult(
                200,
                {
                    "Content-Type": "application/json",
                    "X-Generation-Id": "bad-content-type",
                },
                b"{}",
            ),
            SpeechHttpResult(
                200,
                {
                    "Content-Type": "audio/mpeg",
                    "X-Generation-Id": "empty-body",
                },
                b"",
            ),
            SpeechHttpResult(200, {"Content-Type": "audio/mpeg"}, b"ID3audio"),
        )
        for result in invalid_results:
            with self.subTest(result=result):
                client = OpenRouterSpeechClient(
                    "secret-key",
                    requester=lambda *args: result,
                )
                with self.assertRaises(InvalidAudioResponse):
                    client.synthesize(make_valid_snapshot().assets[0])


class GenerationTests(unittest.TestCase):
    def test_resolve_probe_prefers_afinfo_then_ffprobe(self) -> None:
        self.assertEqual(
            "afinfo",
            resolve_probe(lambda name: "/usr/bin/afinfo" if name == "afinfo" else None),
        )
        self.assertEqual(
            "ffprobe",
            resolve_probe(lambda name: "/usr/bin/ffprobe" if name == "ffprobe" else None),
        )
        with self.assertRaisesRegex(InvalidMp3Error, "afinfo or ffprobe"):
            resolve_probe(lambda name: None)

    def test_validate_mp3_accepts_positive_afinfo_duration(self) -> None:
        completed = subprocess.CompletedProcess(
            ["afinfo", "audio.mp3"],
            0,
            "estimated duration: 1.25 sec\n",
            "",
        )
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "audio.mp3"
            audio_path.write_bytes(b"ID3audio")

            probe = validate_mp3(
                audio_path,
                probe_runner=lambda *args, **kwargs: completed,
                probe_name="afinfo",
            )

        self.assertEqual(1.25, probe.duration_seconds)

    def test_validate_mp3_accepts_ffprobe_duration(self) -> None:
        calls = []
        completed = subprocess.CompletedProcess(
            ["ffprobe", "audio.mp3"],
            0,
            "1.75\n",
            "",
        )
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "audio.mp3"
            audio_path.write_bytes(b"ID3audio")

            probe = validate_mp3(
                audio_path,
                probe_runner=lambda *args, **kwargs: calls.append(args[0]) or completed,
                probe_name="ffprobe",
            )

        self.assertEqual(1.75, probe.duration_seconds)
        self.assertEqual(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            calls[0],
        )

    def test_validate_mp3_rejects_probe_failure_and_zero_duration(self) -> None:
        invalid_results = (
            subprocess.CompletedProcess(
                ["afinfo", "audio.mp3"],
                1,
                "",
                "invalid audio",
            ),
            subprocess.CompletedProcess(
                ["afinfo", "audio.mp3"],
                0,
                "estimated duration: 0.0 sec\n",
                "",
            ),
        )
        for completed in invalid_results:
            with self.subTest(completed=completed):
                with tempfile.TemporaryDirectory() as directory:
                    audio_path = Path(directory) / "audio.mp3"
                    audio_path.write_bytes(b"ID3audio")
                    with self.assertRaises(InvalidMp3Error):
                        validate_mp3(
                            audio_path,
                            probe_runner=lambda *args, **kwargs: completed,
                            probe_name="afinfo",
                        )

    def test_validate_mp3_rejects_missing_or_empty_file(self) -> None:
        completed = subprocess.CompletedProcess(
            ["afinfo", "audio.mp3"],
            0,
            "estimated duration: 1.0 sec\n",
            "",
        )
        with tempfile.TemporaryDirectory() as directory:
            missing_path = Path(directory) / "missing.mp3"
            empty_path = Path(directory) / "empty.mp3"
            empty_path.touch()

            for audio_path in (missing_path, empty_path):
                with self.subTest(audio_path=audio_path):
                    with self.assertRaises(InvalidMp3Error):
                        validate_mp3(
                            audio_path,
                            probe_runner=lambda *args, **kwargs: completed,
                            probe_name="afinfo",
                        )

    def test_generate_assets_reuses_matching_verified_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            snapshot = make_valid_snapshot()
            sample_ids = select_sample_ids(snapshot)
            for asset in snapshot.assets:
                if asset.scenario_question_id in sample_ids:
                    seed_verified_generation_state(
                        work_dir,
                        asset,
                        f"ID3audio-{asset.scenario_question_id}".encode(),
                    )
            client = Mock()

            results = generate_assets(
                snapshot,
                work_dir,
                sample_only=True,
                client=client,
                probe_runner=successful_probe,
                probe_name="afinfo",
            )

        self.assertEqual(
            sample_ids,
            {item.scenario_question_id for item in results},
        )
        client.synthesize.assert_not_called()

    def test_generate_assets_regenerates_tampered_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            snapshot = make_valid_snapshot()
            sample_ids = select_sample_ids(snapshot)
            assets = [
                asset
                for asset in snapshot.assets
                if asset.scenario_question_id in sample_ids
            ]
            for asset in assets:
                seed_verified_generation_state(work_dir, asset, b"ID3audio")
            tampered_asset = assets[0]
            audio_path_for(work_dir, tampered_asset).write_bytes(b"tampered")
            client = Mock()
            client.synthesize.return_value = SpeechResponse(
                b"ID3replacement",
                "replacement",
            )

            generate_assets(
                snapshot,
                work_dir,
                sample_only=True,
                client=client,
                probe_runner=successful_probe,
                probe_name="afinfo",
            )

        client.synthesize.assert_called_once_with(tampered_asset)

    def test_sample_only_generates_exactly_three_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            client.synthesize.return_value = SpeechResponse(
                b"ID3audio",
                "generation",
            )

            results = generate_assets(
                make_valid_snapshot(),
                Path(directory),
                sample_only=True,
                client=client,
                probe_runner=successful_probe,
                probe_name="afinfo",
            )

        self.assertEqual(3, len(results))
        self.assertEqual(3, client.synthesize.call_count)

    def test_verify_generated_assets_requires_every_selected_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            snapshot = make_valid_snapshot()

            with self.assertRaisesRegex(InvalidMp3Error, "3 generated assets"):
                verify_generated_assets(
                    snapshot,
                    work_dir,
                    sample_only=True,
                    probe_runner=successful_probe,
                    probe_name="afinfo",
                )

    def test_verify_generated_assets_returns_verified_sample_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            snapshot = make_valid_snapshot()
            for asset in snapshot.assets:
                if asset.scenario_question_id in select_sample_ids(snapshot):
                    seed_verified_generation_state(work_dir, asset, b"ID3audio")

            verified = verify_generated_assets(
                snapshot,
                work_dir,
                sample_only=True,
                probe_runner=successful_probe,
                probe_name="afinfo",
            )

        self.assertEqual(3, len(verified))


class ManifestTests(unittest.TestCase):
    def test_manifest_requires_all_120_generated_assets(self) -> None:
        with self.assertRaisesRegex(ValueError, "120 generated assets"):
            build_manifest(make_valid_snapshot(), make_generated_assets()[:-1])

    def test_manifest_contains_source_and_audio_digests_and_exact_s3_keys(
        self,
    ) -> None:
        manifest = build_manifest(make_valid_snapshot(), make_generated_assets())
        first = manifest["assets"][0]

        self.assertRegex(manifest["source"]["snapshotSha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(first["audioSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            f"content/scenario-question-audio/1/{first['generationFingerprint']}.mp3",
            first["s3Key"],
        )

    def test_manifest_is_canonical_and_has_stable_sha256(self) -> None:
        manifest = build_manifest(make_valid_snapshot(), make_generated_assets())

        first = canonical_manifest_bytes(manifest)
        second = canonical_manifest_bytes(json.loads(first))

        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertEqual(
            hashlib.sha256(first).hexdigest(),
            manifest_sha256(manifest),
        )

    def test_verify_manifest_detects_changed_audio_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, generated, manifest = seed_full_manifest(Path(directory))
            generated[0].path.write_bytes(b"changed")

            with self.assertRaisesRegex(ValueError, "audio sha256 mismatch"):
                verify_manifest(manifest, Path(directory))

    def test_verify_cli_checks_source_assets_and_manifest_together(self) -> None:
        snapshot = make_valid_snapshot()
        generated = make_generated_assets(snapshot)
        manifest = build_manifest(snapshot, generated)
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_bytes(canonical_manifest_bytes(manifest))
            with (
                patch(
                    "scripts.scenario_question_audio.load_source",
                    return_value=snapshot,
                ),
                patch(
                    "scripts.scenario_question_audio.verify_generated_assets",
                    return_value=generated,
                ) as verify_generated,
                patch(
                    "scripts.scenario_question_audio.verify_manifest"
                ) as verify_saved_manifest,
                redirect_stdout(io.StringIO()),
            ):
                result = main(
                    [
                        "verify",
                        "--source",
                        "source.json",
                        "--manifest",
                        str(manifest_path),
                        "--work-dir",
                        directory,
                    ]
                )

        self.assertEqual(0, result)
        verify_generated.assert_called_once()
        verify_saved_manifest.assert_called_once()


class S3UploadTests(unittest.TestCase):
    def test_upload_defaults_to_dry_run_without_aws_put(self) -> None:
        runner = RecordingAwsRunner(head_results={})
        plan = plan_s3_upload(valid_manifest(), "bucket", aws_runner=runner)

        result = execute_s3_upload(plan, execute=False, aws_runner=runner)

        self.assertEqual(0, result.uploaded)
        self.assertFalse(any("put-object" in call for call in runner.calls))

    def test_upload_uses_if_none_match_and_required_metadata(self) -> None:
        manifest = valid_manifest()
        runner = RecordingAwsRunner(head_results={})
        plan = plan_s3_upload(manifest, "bucket", aws_runner=runner)

        execute_s3_upload(plan, execute=True, aws_runner=runner)

        put_call = next(
            call
            for call in runner.calls
            if "put-object" in call
            and call[call.index("--key") + 1].endswith(".mp3")
        )
        self.assertEqual("*", put_call[put_call.index("--if-none-match") + 1])
        self.assertEqual(
            "audio/mpeg",
            put_call[put_call.index("--content-type") + 1],
        )
        self.assertIn("--metadata", put_call)

    def test_existing_matching_objects_are_reused(self) -> None:
        manifest = valid_manifest()
        runner = RecordingAwsRunner(matching_head_results(manifest))

        plan = plan_s3_upload(manifest, "bucket", aws_runner=runner)

        self.assertEqual(121, plan.reused_count)
        self.assertEqual(0, plan.conflict_count)

    def test_existing_mismatched_object_fails_without_overwrite(self) -> None:
        manifest = valid_manifest()
        head_results = matching_head_results(manifest)
        first_key = manifest["assets"][0]["s3Key"]
        head_results[first_key]["Metadata"]["audio-sha256"] = "0" * 64
        runner = RecordingAwsRunner(head_results)

        with self.assertRaisesRegex(ValueError, "existing object conflict"):
            plan_s3_upload(manifest, "bucket", aws_runner=runner)

        self.assertFalse(any("put-object" in call for call in runner.calls))

    def test_manifest_upload_runs_after_all_mp3_objects(self) -> None:
        runner = RecordingAwsRunner(head_results={})
        plan = plan_s3_upload(valid_manifest(), "bucket", aws_runner=runner)

        execute_s3_upload(plan, execute=True, aws_runner=runner)

        put_keys = [
            call[call.index("--key") + 1]
            for call in runner.calls
            if "put-object" in call
        ]
        self.assertTrue(
            put_keys[-1].startswith("content/scenario-question-audio/manifests/")
        )

    def test_post_upload_head_matches_manifest_metadata(self) -> None:
        runner = RecordingAwsRunner(head_results={})
        plan = plan_s3_upload(valid_manifest(), "bucket", aws_runner=runner)

        result = execute_s3_upload(plan, execute=True, aws_runner=runner)

        self.assertEqual(121, result.uploaded)
        self.assertEqual(121, result.verified)
        self.assertEqual(0, result.conflicts)


if __name__ == "__main__":
    unittest.main()
