# LAN-373 발음 학습 오디오 배치 도구의 계약을 검증한다.

import hashlib
import json
import unittest
from pathlib import Path
import tempfile
from unittest.mock import Mock

from scripts.expression_pronunciation_audio import (
    AccentContrast,
    InvalidAudioResponse,
    OpenRouterSpeechClient,
    PermanentTtsError,
    SourceAsset,
    SourceSnapshot,
    SpeechHttpResult,
    asset_id,
    audio_path_for,
    build_manifest,
    check_accent_pronunciation,
    generate_assets,
    generation_fingerprint,
    load_source,
    manifest_sha256,
    plan_s3_upload,
    s3_key,
    validate_source,
    verify_accent_pronunciations,
    verify_manifest,
)


def make_source_payload() -> dict:
    return {
        "schemaVersion": 1,
        "environment": "production",
        "expressions": [
            {
                "expressionId": 7,
                "expressionText": "There is nothing like",
                "sentenceText": "There's nothing like it.",
                "accentLocales": ["EN_US", "EN_GB"],
                "words": [
                    {"order": 1, "word": "There's"},
                    {"order": 2, "word": "nothing"},
                    {"order": 3, "word": "like"},
                    {
                        "order": 4,
                        "word": "it",
                        "accentContrast": {
                            "EN_GB": {
                                "expected": "a clear t",
                                "other": "a d-like flap",
                            }
                        },
                    },
                ],
            }
        ],
    }


def load_snapshot(payload: dict) -> SourceSnapshot:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as handle:
        json.dump(payload, handle)
        path = Path(handle.name)
    try:
        return load_source(path)
    finally:
        path.unlink(missing_ok=True)


class SourceTests(unittest.TestCase):
    def test_expressions_expand_to_assets_per_locale(self):
        snapshot = load_snapshot(make_source_payload())

        # locale 2개 × (표현 1 + 문장 1 + 단어 4) = 12
        self.assertEqual(len(snapshot.assets), 12)
        kinds = {asset.kind for asset in snapshot.assets}
        self.assertEqual(kinds, {"expression", "sentence", "word"})

    def test_contrast_is_kept_only_for_declared_locale(self):
        snapshot = load_snapshot(make_source_payload())

        self.assertIn((7, "EN_GB", 4), snapshot.contrasts)
        self.assertNotIn((7, "EN_US", 4), snapshot.contrasts)

    def test_unsupported_locale_is_rejected(self):
        payload = make_source_payload()
        payload["expressions"][0]["accentLocales"] = ["EN_XX"]

        with self.assertRaises(ValueError):
            load_snapshot(payload)

    def test_blank_text_is_rejected(self):
        payload = make_source_payload()
        payload["expressions"][0]["words"][0]["word"] = "   "

        with self.assertRaises(ValueError):
            load_snapshot(payload)

    def test_duplicate_word_order_is_rejected(self):
        payload = make_source_payload()
        payload["expressions"][0]["words"][1]["order"] = 1

        with self.assertRaises(ValueError):
            load_snapshot(payload)


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.asset = SourceAsset(
            expression_id=7,
            accent_locale="EN_GB",
            kind="sentence",
            word_order=None,
            text="There's nothing like it.",
        )

    def test_fingerprint_covers_generation_contract(self):
        baseline = generation_fingerprint(self.asset)
        changed_text = generation_fingerprint(
            SourceAsset(
                expression_id=7,
                accent_locale="EN_GB",
                kind="sentence",
                word_order=None,
                text="There's nothing like them.",
            )
        )
        changed_voice = generation_fingerprint(
            SourceAsset(
                expression_id=7,
                accent_locale="EN_US",
                kind="sentence",
                word_order=None,
                text="There's nothing like it.",
            )
        )

        self.assertNotEqual(baseline, changed_text)
        self.assertNotEqual(baseline, changed_voice)

    def test_s3_key_layout(self):
        fingerprint = generation_fingerprint(self.asset)
        self.assertEqual(
            s3_key(self.asset, fingerprint),
            "content/expression-pronunciation-audio/7/EN_GB/sentence/"
            f"{fingerprint}.mp3",
        )

    def test_word_s3_key_includes_order(self):
        word_asset = SourceAsset(
            expression_id=7,
            accent_locale="EN_GB",
            kind="word",
            word_order=4,
            text="it",
        )
        fingerprint = generation_fingerprint(word_asset)
        self.assertEqual(
            s3_key(word_asset, fingerprint),
            "content/expression-pronunciation-audio/7/EN_GB/word/4/"
            f"{fingerprint}.mp3",
        )


class SpeechClientTests(unittest.TestCase):
    def setUp(self):
        self.asset = SourceAsset(
            expression_id=7,
            accent_locale="EN_US",
            kind="word",
            word_order=1,
            text="There's",
        )

    def test_valid_response_is_returned(self):
        requester = Mock(
            return_value=SpeechHttpResult(
                status=200,
                headers={
                    "Content-Type": "audio/mpeg",
                    "x-generation-id": "gen-1",
                },
                body=b"mp3-bytes",
            )
        )
        client = OpenRouterSpeechClient("key", requester=requester, sleep=Mock())

        response = client.synthesize(self.asset)

        self.assertEqual(response.body, b"mp3-bytes")
        payload = requester.call_args.args[0]
        self.assertEqual(payload["voice"], "aura-2-thalia-en")
        self.assertEqual(payload["model"], "deepgram/aura-2")

    def test_missing_generation_id_is_invalid(self):
        requester = Mock(
            return_value=SpeechHttpResult(
                status=200,
                headers={"Content-Type": "audio/mpeg"},
                body=b"mp3-bytes",
            )
        )
        client = OpenRouterSpeechClient("key", requester=requester, sleep=Mock())

        with self.assertRaises(InvalidAudioResponse):
            client.synthesize(self.asset)

    def test_client_error_is_permanent(self):
        requester = Mock(
            return_value=SpeechHttpResult(status=400, headers={}, body=b"")
        )
        client = OpenRouterSpeechClient("key", requester=requester, sleep=Mock())

        with self.assertRaises(PermanentTtsError):
            client.synthesize(self.asset)
        self.assertEqual(requester.call_count, 1)

    def test_server_error_is_retried(self):
        requester = Mock(
            side_effect=[
                SpeechHttpResult(status=503, headers={}, body=b""),
                SpeechHttpResult(
                    status=200,
                    headers={
                        "Content-Type": "audio/mpeg",
                        "x-generation-id": "gen-2",
                    },
                    body=b"mp3-bytes",
                ),
            ]
        )
        client = OpenRouterSpeechClient(
            "key", requester=requester, sleep=Mock(), jitter=lambda: 0.0
        )

        response = client.synthesize(self.asset)

        self.assertEqual(response.generation_id, "gen-2")
        self.assertEqual(requester.call_count, 2)


def fake_probe_runner(command, **kwargs):
    result = Mock()
    result.returncode = 0
    result.stdout = "1.5\n"
    return result


class GenerateAndManifestTests(unittest.TestCase):
    def make_generated(self, snapshot, work_dir: Path):
        client = Mock()
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(
                body=f"mp3:{asset_id(asset)}".encode(), generation_id="gen-x"
            )
        )
        return generate_assets(
            snapshot,
            work_dir,
            client=client,
            probe_runner=fake_probe_runner,
            probe_name="ffprobe",
        )

    def test_generate_then_manifest_round_trip(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            generated = self.make_generated(snapshot, work_dir)

            self.assertEqual(len(generated), len(snapshot.assets))
            manifest = build_manifest(snapshot, generated)
            verify_manifest(manifest, work_dir)
            self.assertEqual(manifest["issue"], "LAN-373")
            self.assertEqual(manifest["source"]["assetCount"], 12)
            self.assertTrue(manifest_sha256(manifest))

    def test_generate_resumes_from_existing_state(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            self.make_generated(snapshot, work_dir)

            client = Mock()
            client.synthesize = Mock()
            resumed = generate_assets(
                snapshot,
                work_dir,
                client=client,
                probe_runner=fake_probe_runner,
                probe_name="ffprobe",
            )

            self.assertEqual(len(resumed), len(snapshot.assets))
            client.synthesize.assert_not_called()

    def test_manifest_rejects_tampered_audio(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            generated = self.make_generated(snapshot, work_dir)
            manifest = build_manifest(snapshot, generated)

            tampered = audio_path_for(work_dir, snapshot.assets[0])
            tampered.write_bytes(b"tampered")

            with self.assertRaises(ValueError):
                verify_manifest(manifest, work_dir)


class AccentVerificationTests(unittest.TestCase):
    def test_mismatch_is_reported_for_word_and_sentence(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            for asset in snapshot.assets:
                path = audio_path_for(work_dir, asset)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"mp3")

            checker = Mock(return_value=(False, "wrong-sound"))
            problems = verify_accent_pronunciations(
                snapshot, work_dir, "key", checker=checker
            )

            # EN_GB의 word-4와 sentence 두 개가 검사돼 둘 다 문제로 보고된다
            self.assertEqual(len(problems), 2)
            self.assertEqual(checker.call_count, 2)

    def test_matching_pronunciation_reports_no_problem(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            for asset in snapshot.assets:
                path = audio_path_for(work_dir, asset)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"mp3")

            problems = verify_accent_pronunciations(
                snapshot, work_dir, "key", checker=Mock(return_value=(True, "ok"))
            )

            self.assertEqual(problems, [])

    def test_missing_audio_is_a_problem(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            problems = verify_accent_pronunciations(
                snapshot, Path(tmp), "key", checker=Mock()
            )

            self.assertEqual(len(problems), 2)
            self.assertIn("missing", problems[0])

    def test_check_parses_forced_choice_answer(self):
        contrast = AccentContrast(word="it", expected="a clear t", other="a flap")
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            handle.write(b"mp3")
            path = Path(handle.name)
        try:
            body = json.dumps(
                {
                    "choices": [
                        {"message": {"content": '{"answer": "B", "heard": "id"}'}}
                    ]
                }
            ).encode()
            requester = Mock(
                return_value=SpeechHttpResult(status=200, headers={}, body=body)
            )

            matches, heard = check_accent_pronunciation(
                "key", path, contrast, requester=requester
            )

            self.assertFalse(matches)
            self.assertEqual(heard, "id")
        finally:
            path.unlink(missing_ok=True)


def make_s3_stub(objects: dict[str, bytes]):
    """head-object/get-object만 이해하는 aws CLI 대역. objects는 key→mp3 bytes."""

    def aws_runner(command, **kwargs):
        result = Mock()
        key = command[command.index("--key") + 1]
        if "head-object" in command:
            if key not in objects:
                result.returncode = 1
                result.stderr = "404 Not Found"
                return result
            body = objects[key]
            result.returncode = 0
            result.stdout = json.dumps(
                {
                    "ContentLength": len(body),
                    "Metadata": {
                        "audio-sha256": hashlib.sha256(body).hexdigest(),
                        "generation-id": "gen-remote",
                    },
                }
            )
            return result
        if "get-object" in command:
            Path(command[-1]).write_bytes(objects[key])
            result.returncode = 0
            return result
        raise AssertionError(f"unexpected aws command: {command}")

    return aws_runner


class ReuseFromS3Tests(unittest.TestCase):
    def test_existing_s3_asset_is_downloaded_instead_of_synthesized(self):
        from scripts.expression_pronunciation_audio import (
            generation_fingerprint as fingerprint_of,
        )

        snapshot = load_snapshot(make_source_payload())
        remote = {
            s3_key(asset, fingerprint_of(asset)): f"mp3:{asset_id(asset)}".encode()
            for asset in snapshot.assets
        }
        client = Mock()
        client.synthesize = Mock()

        with tempfile.TemporaryDirectory() as tmp:
            generated = generate_assets(
                snapshot,
                Path(tmp),
                client=client,
                probe_runner=fake_probe_runner,
                probe_name="ffprobe",
                reuse_bucket="bucket",
                aws_runner=make_s3_stub(remote),
            )

            self.assertEqual(len(generated), len(snapshot.assets))
            client.synthesize.assert_not_called()
            self.assertEqual(
                {asset.generation_id for asset in generated}, {"gen-remote"}
            )

    def test_missing_s3_key_falls_back_to_synthesis(self):
        snapshot = load_snapshot(make_source_payload())
        client = Mock()
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(
                body=f"mp3:{asset_id(asset)}".encode(), generation_id="gen-new"
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            generated = generate_assets(
                snapshot,
                Path(tmp),
                client=client,
                probe_runner=fake_probe_runner,
                probe_name="ffprobe",
                reuse_bucket="bucket",
                aws_runner=make_s3_stub({}),
            )

            self.assertEqual(len(generated), len(snapshot.assets))
            self.assertEqual(client.synthesize.call_count, len(snapshot.assets))

    def test_downloaded_audio_sha_mismatch_fails(self):
        from scripts.expression_pronunciation_audio import (
            generation_fingerprint as fingerprint_of,
        )

        snapshot = load_snapshot(make_source_payload())
        remote = {
            s3_key(asset, fingerprint_of(asset)): b"mp3-bytes"
            for asset in snapshot.assets
        }
        stub = make_s3_stub(remote)

        def tampering_runner(command, **kwargs):
            if "get-object" in command:
                Path(command[-1]).write_bytes(b"tampered")
                result = Mock()
                result.returncode = 0
                return result
            return stub(command, **kwargs)

        client = Mock()
        client.synthesize = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                generate_assets(
                    snapshot,
                    Path(tmp),
                    client=client,
                    probe_runner=fake_probe_runner,
                    probe_name="ffprobe",
                    reuse_bucket="bucket",
                    aws_runner=tampering_runner,
                )


class UploadPlanTests(unittest.TestCase):
    def test_conflicting_remote_object_stops_the_plan(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            client = Mock()
            client.synthesize = Mock(
                side_effect=lambda asset: Mock(
                    body=f"mp3:{asset_id(asset)}".encode(), generation_id="gen-x"
                )
            )
            generated = generate_assets(
                snapshot,
                work_dir,
                client=client,
                probe_runner=fake_probe_runner,
                probe_name="ffprobe",
            )
            manifest = build_manifest(snapshot, generated)

            def head_conflict(command, **kwargs):
                result = Mock()
                result.returncode = 0
                result.stdout = json.dumps(
                    {
                        "ContentLength": 1,
                        "ContentType": "text/plain",
                        "CacheControl": "no-cache",
                        "Metadata": {},
                    }
                )
                return result

            with self.assertRaises(ValueError):
                plan_s3_upload(
                    manifest,
                    "bucket",
                    work_dir=work_dir,
                    aws_runner=head_conflict,
                )


class ValidateSourceTests(unittest.TestCase):
    def test_missing_sentence_kind_is_rejected(self):
        asset = SourceAsset(
            expression_id=1,
            accent_locale="EN_US",
            kind="expression",
            word_order=None,
            text="hello",
        )
        snapshot = SourceSnapshot(
            schema_version=1,
            environment="production",
            assets=(asset,),
            contrasts={},
        )
        validate_source(snapshot)  # expression 하나만 있어도 개수 규칙은 통과한다

        duplicated = SourceSnapshot(
            schema_version=1,
            environment="production",
            assets=(asset, asset),
            contrasts={},
        )
        with self.assertRaises(ValueError):
            validate_source(duplicated)


if __name__ == "__main__":
    unittest.main()
