# LAN-373 발음 학습 오디오 배치 도구의 계약을 검증한다.

import hashlib
import json
import unittest
import unittest.mock
from pathlib import Path
import tempfile
from unittest.mock import Mock

from scripts.expression_pronunciation_audio import (
    AccentContrast,
    Boto3AwsRunner,
    _CompletedCall,
    _copied_head_matches,
    InvalidAudioResponse,
    OpenRouterSpeechClient,
    PermanentTtsError,
    SourceAsset,
    SourceSnapshot,
    SpeechHttpResult,
    asset_id,
    audio_path_for,
    build_be_manifest,
    build_manifest,
    canonical_manifest_bytes,
    check_accent_pronunciation,
    generate_assets,
    generation_fingerprint,
    load_source,
    manifest_sha256,
    plan_s3_upload,
    execute_s3_upload,
    publish_be_manifest,
    publish_reference,
    build_word_pool_index,
    execute_word_pool_backfill,
    load_word_texts,
    main,
    parse_expression_ranges,
    parse_legacy_word_keys,
    plan_word_pool,
    publish_word_pool_index,
    s3_key,
    shared_word_key,
    validate_source,
    verify_word_pool,
    word_fingerprint,
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

        # locale 2개 x (표현 1 + 문장 1 + 단어 4) = 12
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
                if "list-objects-v2" in command:
                    # 모든 매니페스트 키가 이미 존재한다고 응답한다
                    result.stdout = json.dumps(
                        [asset["s3Key"] for asset in manifest["assets"]]
                    )
                    return result
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

    def test_replace_overwrites_changed_keys_without_precondition(self):
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
            changed_key = manifest["assets"][0]["s3Key"]
            puts = []
            remote = {}

            def option(command, name):
                return command[command.index(name) + 1]

            def aws_runner(command, **kwargs):
                result = Mock()
                result.returncode = 0
                if "list-objects-v2" in command:
                    result.stdout = json.dumps([changed_key])
                    return result
                key = option(command, "--key")
                if "put-object" in command:
                    puts.append(command)
                    remote[key] = {
                        "ContentLength": Path(option(command, "--body")).stat().st_size,
                        "ContentType": option(command, "--content-type"),
                        "CacheControl": option(command, "--cache-control"),
                        "Metadata": dict(
                            item.split("=", 1)
                            for item in option(command, "--metadata").split(",")
                        ),
                    }
                    return result
                # head-object: 게시 전의 changed_key는 낡은 내용, 게시 후에는 put 그대로
                if key in remote:
                    result.stdout = json.dumps(remote[key])
                    return result
                if key == changed_key:
                    result.stdout = json.dumps(
                        {
                            "ContentLength": 1,
                            "ContentType": "audio/mpeg",
                            "CacheControl": "public, max-age=31536000, immutable",
                            "Metadata": {"audio-sha256": "stale"},
                        }
                    )
                    return result
                result.returncode = 1
                result.stderr = "404 Not Found"
                return result

            with self.assertRaises(ValueError):
                plan_s3_upload(
                    manifest, "bucket", work_dir=work_dir, aws_runner=aws_runner
                )
            plan = plan_s3_upload(
                manifest,
                "bucket",
                work_dir=work_dir,
                aws_runner=aws_runner,
                allow_replace=True,
            )
            self.assertEqual(plan.replace_keys, (changed_key,))
            self.assertNotIn(changed_key, plan.new_keys)

            result = execute_s3_upload(plan, execute=True, aws_runner=aws_runner)
            self.assertEqual(result.conflicts, 0)
            replace_put = next(c for c in puts if c[c.index("--key") + 1] == changed_key)
            self.assertNotIn("--if-none-match", replace_put)
            other_put = next(c for c in puts if c[c.index("--key") + 1] != changed_key)
            self.assertIn("--if-none-match", other_put)


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


def make_upload_stub():
    """head/put-object를 이해하고 put된 객체를 기록하는 aws CLI 대역."""
    stored: dict[str, tuple[bytes, dict, str, str]] = {}

    def aws_runner(command, **kwargs):
        result = Mock()
        result.returncode = 0
        key = command[command.index("--key") + 1]
        if "head-object" in command:
            if key not in stored:
                result.returncode = 1
                result.stderr = "404 Not Found"
                return result
            body, metadata, content_type, cache_control = stored[key]
            result.stdout = json.dumps(
                {
                    "ContentLength": len(body),
                    "ContentType": content_type,
                    "CacheControl": cache_control,
                    "Metadata": metadata,
                }
            )
            return result
        if "put-object" in command:
            body = Path(command[command.index("--body") + 1]).read_bytes()
            metadata = dict(
                part.split("=", 1)
                for part in command[command.index("--metadata") + 1].split(",")
            )
            stored[key] = (
                body,
                metadata,
                command[command.index("--content-type") + 1],
                command[command.index("--cache-control") + 1],
            )
            return result
        raise AssertionError(f"unexpected aws command: {command}")

    return aws_runner, stored


def make_reference_entries() -> list[dict]:
    return [
        {
            "expressionId": 164,
            "accentLocale": "EN_US",
            "sentenceText": "I'm super tired today.",
            "words": [
                {
                    "order": 1,
                    "word": "I'm",
                    "syllables": ["I'm"],
                    "stressIndex": -1,
                    "pronunciationDisplay": "aim",
                },
                {
                    "order": 2,
                    "word": "super",
                    "syllables": ["su", "per"],
                    "stressIndex": 0,
                    "pronunciationDisplay": "soo·per",
                    "accentContrast": {
                        "expected": "sounds like 「SOO-per」",
                        "other": "sounds like 「SYOO-per」",
                        "errorType": "vowel",
                    },
                },
            ],
        }
    ]


class ReferencePublishTests(unittest.TestCase):
    def publish(self, entries, *, execute=True):
        aws_runner, stored = make_upload_stub()
        with tempfile.TemporaryDirectory() as tmp:
            reference_path = Path(tmp) / "reference_EN_US.json"
            reference_path.write_text(
                json.dumps(entries, ensure_ascii=False), encoding="utf-8"
            )
            published = publish_reference(
                Path(tmp),
                "content/expression-pronunciation-audio/manifests/be-abc.json",
                "bucket",
                execute=execute,
                aws_runner=aws_runner,
            )
        return published, stored

    def test_published_body_is_the_top_level_array(self):
        entries = make_reference_entries()
        published, stored = self.publish(entries)

        self.assertEqual(len(published), 1)
        body, metadata, content_type, cache_control = stored[published[0]]
        parsed = json.loads(body)
        # BE parseReference()는 최상위 JSON 배열(List<Entry>)을 기대한다
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["expressionId"], 164)
        self.assertEqual(parsed[0]["sentenceText"], "I'm super tired today.")
        self.assertEqual(
            [word["order"] for word in parsed[0]["words"]], [1, 2]
        )
        digest = hashlib.sha256(body).hexdigest()
        self.assertEqual(
            published[0],
            "content/expression-pronunciation-audio/reference/"
            f"EN_US-{digest}.json",
        )
        # ttsManifestKey는 바디가 아니라 metadata로만 전달한다
        self.assertEqual(
            metadata["tts-manifest-key"],
            "content/expression-pronunciation-audio/manifests/be-abc.json",
        )
        self.assertEqual(content_type, "application/json")
        self.assertIn("immutable", cache_control)

    def test_dry_run_does_not_upload(self):
        published, stored = self.publish(make_reference_entries(), execute=False)

        self.assertEqual(len(published), 1)
        self.assertEqual(stored, {})

    def test_duplicate_word_order_blocks_publish(self):
        entries = make_reference_entries()
        entries[0]["words"][1]["order"] = 1

        with self.assertRaises(ValueError):
            self.publish(entries)

    def test_whitespace_in_word_blocks_publish(self):
        entries = make_reference_entries()
        entries[0]["words"][0]["word"] = "I am"

        with self.assertRaises(ValueError):
            self.publish(entries)

    def test_missing_sentence_text_blocks_publish(self):
        entries = make_reference_entries()
        del entries[0]["sentenceText"]

        with self.assertRaises(ValueError):
            self.publish(entries)


def make_be_source_payload() -> dict:
    payload = make_source_payload()
    payload["expressions"].append(
        {
            "expressionId": 8,
            # 패턴형 표현: expressionText가 없어 표현 음성을 생성하지 않는다
            "sentenceText": "She is busy working today.",
            "accentLocales": ["EN_US"],
            "words": [
                {"order": 1, "word": "She"},
                {"order": 2, "word": "is"},
                {"order": 3, "word": "busy"},
            ],
        }
    )
    return payload


class BeManifestTests(unittest.TestCase):
    def build_fixture(self):
        snapshot = load_snapshot(make_be_source_payload())
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
        return snapshot, manifest

    def manifest_key_of(self, manifest, expression_id, locale, kind, word_order=None):
        return next(
            row["s3Key"]
            for row in manifest["assets"]
            if row["expressionId"] == expression_id
            and row["accentLocale"] == locale
            and row["kind"] == kind
            and row["wordOrder"] == word_order
        )

    def test_rows_are_grouped_per_expression_and_locale(self):
        snapshot, manifest = self.build_fixture()

        be_manifest = build_be_manifest(
            manifest, snapshot, cdn_base_url="https://cdn.example.com/"
        )

        # BE importTts 계약: 최상위는 assets 하나, 필드명은 철자까지 동일
        self.assertEqual(set(be_manifest), {"assets"})
        by_group = {
            (asset["expressionId"], asset["accentLocale"]): asset
            for asset in be_manifest["assets"]
        }
        self.assertEqual(
            set(by_group), {(7, "EN_US"), (7, "EN_GB"), (8, "EN_US")}
        )

        full = by_group[(7, "EN_US")]
        self.assertEqual(
            set(full),
            {
                "expressionId",
                "accentLocale",
                "expressionAudioUrl",
                "sentenceAudioUrl",
                "words",
            },
        )
        # URL = base(끝 / 제거) + "/" + s3Key
        self.assertEqual(
            full["expressionAudioUrl"],
            "https://cdn.example.com/"
            + self.manifest_key_of(manifest, 7, "EN_US", "expression"),
        )
        self.assertEqual(
            full["sentenceAudioUrl"],
            "https://cdn.example.com/"
            + self.manifest_key_of(manifest, 7, "EN_US", "sentence"),
        )
        self.assertEqual([word["order"] for word in full["words"]], [1, 2, 3, 4])
        for word in full["words"]:
            self.assertEqual(set(word), {"order", "audioUrl"})
        self.assertEqual(
            full["words"][3]["audioUrl"],
            "https://cdn.example.com/"
            + self.manifest_key_of(manifest, 7, "EN_US", "word", 4),
        )

    def test_templated_expression_has_null_expression_url(self):
        snapshot, manifest = self.build_fixture()

        be_manifest = build_be_manifest(manifest, snapshot)

        by_group = {
            (asset["expressionId"], asset["accentLocale"]): asset
            for asset in be_manifest["assets"]
        }
        self.assertIsNone(by_group[(8, "EN_US")]["expressionAudioUrl"])
        self.assertEqual(
            [word["order"] for word in by_group[(8, "EN_US")]["words"]], [1, 2, 3]
        )

    def test_missing_sentence_row_fails(self):
        snapshot, manifest = self.build_fixture()
        manifest["assets"] = [
            row
            for row in manifest["assets"]
            if not (
                row["expressionId"] == 8 and row["kind"] == "sentence"
            )
        ]

        with self.assertRaises(ValueError):
            build_be_manifest(manifest, snapshot)

    def test_word_order_mismatch_with_source_fails(self):
        snapshot, manifest = self.build_fixture()
        manifest["assets"] = [
            row
            for row in manifest["assets"]
            if not (
                row["expressionId"] == 7
                and row["accentLocale"] == "EN_GB"
                and row["kind"] == "word"
                and row["wordOrder"] == 3
            )
        ]

        with self.assertRaises(ValueError):
            build_be_manifest(manifest, snapshot)

    def test_duplicate_word_row_fails(self):
        snapshot, manifest = self.build_fixture()
        duplicated = next(
            row
            for row in manifest["assets"]
            if row["expressionId"] == 7
            and row["accentLocale"] == "EN_US"
            and row["kind"] == "word"
            and row["wordOrder"] == 1
        )
        manifest["assets"].append(dict(duplicated))

        with self.assertRaises(ValueError):
            build_be_manifest(manifest, snapshot)

    def test_manifest_from_different_source_fails(self):
        _snapshot, manifest = self.build_fixture()
        other_snapshot = load_snapshot(make_source_payload())

        with self.assertRaises(ValueError):
            build_be_manifest(manifest, other_snapshot)

    def test_publish_uses_content_hash_key(self):
        snapshot, manifest = self.build_fixture()
        be_manifest = build_be_manifest(manifest, snapshot)
        aws_runner, stored = make_upload_stub()

        key = publish_be_manifest(
            be_manifest,
            manifest["source"]["snapshotSha256"],
            "bucket",
            execute=True,
            aws_runner=aws_runner,
        )

        body = canonical_manifest_bytes(be_manifest)
        digest = hashlib.sha256(body).hexdigest()
        self.assertEqual(
            key,
            f"content/expression-pronunciation-audio/manifests/be-{digest}.json",
        )
        self.assertEqual(stored[key][0], body)
        self.assertEqual(
            stored[key][1]["source-sha256"],
            manifest["source"]["snapshotSha256"],
        )

    def test_publish_dry_run_does_not_upload(self):
        snapshot, manifest = self.build_fixture()
        be_manifest = build_be_manifest(manifest, snapshot)
        aws_runner, stored = make_upload_stub()

        key = publish_be_manifest(
            be_manifest,
            manifest["source"]["snapshotSha256"],
            "bucket",
            execute=False,
            aws_runner=aws_runner,
        )

        self.assertTrue(
            key.startswith("content/expression-pronunciation-audio/manifests/be-")
        )
        self.assertEqual(stored, {})


if __name__ == "__main__":
    unittest.main()


class Boto3RunnerTests(unittest.TestCase):
    def make_runner(self, client):
        runner = Boto3AwsRunner.__new__(Boto3AwsRunner)
        runner._client = client
        return runner

    def test_list_head_put_follow_cli_contract(self):
        client = Mock()
        paginator = Mock()
        paginator.paginate = Mock(
            return_value=[{"Contents": [{"Key": "a"}]}, {"Contents": [{"Key": "b"}]}]
        )
        client.get_paginator = Mock(return_value=paginator)
        client.head_object = Mock(
            return_value={
                "ContentLength": 3,
                "ContentType": "audio/mpeg",
                "CacheControl": "cc",
                "Metadata": {"audio-sha256": "x"},
            }
        )
        runner = self.make_runner(client)

        listed = runner(
            ["aws", "s3api", "list-objects-v2", "--bucket", "b", "--prefix", "p",
             "--query", "Contents[].Key", "--output", "json"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(json.loads(listed.stdout), ["a", "b"])

        head = runner(
            ["aws", "s3api", "head-object", "--bucket", "b", "--key", "k",
             "--output", "json"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(json.loads(head.stdout)["Metadata"], {"audio-sha256": "x"})

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"mp3")
            body = Path(handle.name)
        try:
            put = runner(
                ["aws", "s3api", "put-object", "--bucket", "b", "--key", "k",
                 "--body", str(body), "--if-none-match", "*", "--content-type",
                 "audio/mpeg", "--cache-control", "cc", "--metadata",
                 "audio-sha256=x,source-sha256=y"],
                capture_output=True, text=True, check=False,
            )
        finally:
            body.unlink(missing_ok=True)
        self.assertEqual(put.returncode, 0)
        client.put_object.assert_called_once_with(
            Bucket="b", Key="k", Body=b"mp3", ContentType="audio/mpeg",
            CacheControl="cc", Metadata={"audio-sha256": "x", "source-sha256": "y"},
            IfNoneMatch="*",
        )

    def test_missing_object_reports_404_like_cli(self):
        from botocore.exceptions import ClientError

        client = Mock()
        client.head_object = Mock(
            side_effect=ClientError(
                {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )
        )
        runner = self.make_runner(client)
        result = runner(
            ["aws", "s3api", "head-object", "--bucket", "b", "--key", "k",
             "--output", "json"],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("404", result.stderr)


class WordPoolKeyTests(unittest.TestCase):
    def test_shared_word_key_drops_expression_and_order(self):
        fingerprint = "a" * 64
        self.assertEqual(
            shared_word_key("EN_AU", fingerprint),
            f"content/expression-pronunciation-audio/word/EN_AU/{fingerprint}.mp3",
        )

    def test_shared_word_key_matches_word_fingerprint_of_the_same_text(self):
        # 표현 id·단어 순서가 달라도 같은 (억양, 단어)면 같은 자리를 가리켜야 한다.
        left = SourceAsset(
            expression_id=7, accent_locale="EN_GB", kind="word", word_order=4, text="it"
        )
        right = SourceAsset(
            expression_id=99, accent_locale="EN_GB", kind="word", word_order=1, text="it"
        )
        self.assertEqual(
            generation_fingerprint(left), word_fingerprint("EN_GB", "it")
        )
        self.assertEqual(generation_fingerprint(left), generation_fingerprint(right))

    def test_word_fingerprint_reproduces_published_production_hashes(self):
        # 프로덕션 S3·V95에 실제로 올라가 있는 해시. 이 값이 달라지면 공용 풀이
        # 기존 객체를 못 알아보고 전부 새로 합성하게 된다.
        self.assertEqual(
            word_fingerprint("EN_US", "the"),
            "7bd05e2e00bec192601e48e14585277a5d4dd406ef2d7d82e0f5e5b15ee9f511",
        )
        self.assertEqual(
            word_fingerprint("EN_US", "I"),
            "27fff8268fc788326a47e4349bf855e8aba3cc137be9919a98f201015371af08",
        )

    def test_parse_keeps_only_legacy_word_keys(self):
        fingerprint = "b" * 64
        keys = [
            f"content/expression-pronunciation-audio/12/EN_US/word/3/{fingerprint}.mp3",
            f"content/expression-pronunciation-audio/12/EN_US/sentence/{fingerprint}.mp3",
            f"content/expression-pronunciation-audio/12/EN_US/expression/{fingerprint}.mp3",
            f"content/expression-pronunciation-audio/word/EN_US/{fingerprint}.mp3",
            "content/expression-pronunciation-audio/manifests/be-abc.json",
            "content/expression-pronunciation-audio/reference/EN_US-abc.json",
        ]

        parsed = parse_legacy_word_keys(keys)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].expression_id, 12)
        self.assertEqual(parsed[0].accent_locale, "EN_US")
        self.assertEqual(parsed[0].word_order, 3)
        self.assertEqual(parsed[0].fingerprint, fingerprint)

    def test_expression_ranges_are_inclusive_and_validated(self):
        self.assertEqual(
            parse_expression_ranges("982-1938,2259-3000"),
            ((982, 1938), (2259, 3000)),
        )
        self.assertEqual(parse_expression_ranges(""), ())
        with self.assertRaises(ValueError):
            parse_expression_ranges("982")
        with self.assertRaises(ValueError):
            parse_expression_ranges("3000-2259")


def legacy_word_key(expression_id: int, locale: str, order: int, fingerprint: str) -> str:
    return (
        f"content/expression-pronunciation-audio/{expression_id}/{locale}"
        f"/word/{order}/{fingerprint}.mp3"
    )


class WordPoolPlanTests(unittest.TestCase):
    def setUp(self):
        self.the = word_fingerprint("EN_US", "the")
        self.take = word_fingerprint("EN_US", "take")

    def test_duplicates_collapse_to_one_entry_per_locale_and_fingerprint(self):
        keys = [
            legacy_word_key(5, "EN_US", 1, self.the),
            legacy_word_key(900, "EN_US", 4, self.the),
            legacy_word_key(1200, "EN_US", 2, self.the),
            legacy_word_key(5, "EN_US", 2, self.take),
        ]

        plan = plan_word_pool(keys, "bucket")

        self.assertEqual(len(plan.entries), 2)
        by_fingerprint = {entry.fingerprint: entry for entry in plan.entries}
        self.assertEqual(by_fingerprint[self.the].duplicate_count, 3)
        self.assertEqual(by_fingerprint[self.take].duplicate_count, 1)
        self.assertEqual(plan.legacy_key_count, 4)

    def test_same_word_repeated_inside_one_expression_collapses(self):
        # 실데이터에 한 표현 안에서 같은 단어가 반복되는 경우가 있다 (LAN-471 기준 53건).
        keys = [
            legacy_word_key(5, "EN_US", 2, self.the),
            legacy_word_key(5, "EN_US", 7, self.the),
        ]

        plan = plan_word_pool(keys, "bucket")

        self.assertEqual(len(plan.entries), 1)
        self.assertEqual(plan.entries[0].duplicate_count, 2)
        self.assertEqual(plan.entries[0].source_word_order, 2)

    def test_representative_prefers_qa_verified_batches(self):
        keys = [
            legacy_word_key(5, "EN_US", 1, self.the),
            legacy_word_key(1200, "EN_US", 9, self.the),
        ]

        plan = plan_word_pool(
            keys, "bucket", preferred_expression_ranges=((982, 1938),)
        )

        self.assertEqual(plan.entries[0].source_expression_id, 1200)
        self.assertTrue(plan.entries[0].qa_verified)

    def test_representative_is_deterministic_without_a_preferred_batch(self):
        keys = [
            legacy_word_key(1200, "EN_US", 9, self.the),
            legacy_word_key(5, "EN_US", 3, self.the),
            legacy_word_key(5, "EN_US", 1, self.the),
        ]

        plan = plan_word_pool(keys, "bucket", preferred_expression_ranges=((9000, 9999),))

        self.assertEqual(plan.entries[0].source_expression_id, 5)
        self.assertEqual(plan.entries[0].source_word_order, 1)
        self.assertFalse(plan.entries[0].qa_verified)

    def test_each_locale_keeps_its_own_entry(self):
        keys = [
            legacy_word_key(5, locale, 1, word_fingerprint(locale, "take"))
            for locale in ("EN_US", "EN_GB", "EN_AU")
        ]

        plan = plan_word_pool(keys, "bucket")

        self.assertEqual(len(plan.entries), 3)
        self.assertEqual(
            sorted(entry.accent_locale for entry in plan.entries),
            ["EN_AU", "EN_GB", "EN_US"],
        )
        self.assertEqual(len({entry.fingerprint for entry in plan.entries}), 3)

    def test_already_shared_keys_are_reused_not_copied(self):
        keys = [
            legacy_word_key(5, "EN_US", 1, self.the),
            legacy_word_key(5, "EN_US", 2, self.take),
            shared_word_key("EN_US", self.the),
        ]

        plan = plan_word_pool(keys, "bucket")

        self.assertEqual(
            [entry.fingerprint for entry in plan.copy_entries], [self.take]
        )
        self.assertEqual(
            [entry.fingerprint for entry in plan.reused_entries], [self.the]
        )

    def test_word_texts_join_back_onto_fingerprints(self):
        keys = [legacy_word_key(5, "EN_US", 1, self.the)]

        plan = plan_word_pool(keys, "bucket", word_texts=[("EN_US", "the")])

        self.assertEqual(plan.entries[0].word, "the")
        self.assertEqual(plan.unmatched, ())

    def test_fingerprints_without_a_known_word_are_reported(self):
        keys = [legacy_word_key(5, "EN_US", 1, self.the)]

        plan = plan_word_pool(keys, "bucket", word_texts=[("EN_US", "take")])

        self.assertIsNone(plan.entries[0].word)
        self.assertEqual(plan.unmatched, (("EN_US", self.the),))

    def test_dropping_unmatched_keeps_them_out_of_the_pool_but_still_reports(self):
        # 예문이 수정되면서 버려진 옛 단어 음성이 실제로 있다(표현 1942·1945·1946,
        # 같은 단어 순서에 키가 둘). 풀에 넣으면 아무도 안 쓰는 항목이 생긴다.
        keys = [
            legacy_word_key(5, "EN_US", 1, self.the),
            legacy_word_key(5, "EN_US", 1, self.take),
        ]

        plan = plan_word_pool(
            keys, "bucket", word_texts=[("EN_US", "take")], drop_unmatched=True
        )

        self.assertEqual([entry.fingerprint for entry in plan.entries], [self.take])
        self.assertEqual(plan.unmatched, (("EN_US", self.the),))
        self.assertEqual(plan.copy_entries, plan.entries)

    def test_index_records_every_entry_with_its_source(self):
        keys = [
            legacy_word_key(1200, "EN_US", 9, self.the),
            legacy_word_key(5, "EN_US", 1, self.the),
        ]
        plan = plan_word_pool(
            keys,
            "bucket",
            preferred_expression_ranges=((982, 1938),),
            word_texts=[("EN_US", "the")],
        )

        index = build_word_pool_index(plan, ((982, 1938),))

        self.assertEqual(index["schemaVersion"], 1)
        self.assertEqual(index["issue"], "LAN-475")
        self.assertEqual(index["bucket"], "bucket")
        self.assertEqual(index["preferredExpressionRanges"], [[982, 1938]])
        self.assertEqual(index["summary"]["legacyWordKeys"], 2)
        self.assertEqual(index["summary"]["entries"], 1)
        self.assertEqual(index["summary"]["qaVerified"], 1)
        self.assertEqual(index["summary"]["byAccentLocale"], {"EN_US": 1})
        self.assertEqual(
            index["entries"][0],
            {
                "accentLocale": "EN_US",
                "fingerprint": self.the,
                "targetKey": shared_word_key("EN_US", self.the),
                "sourceKey": legacy_word_key(1200, "EN_US", 9, self.the),
                "sourceExpressionId": 1200,
                "sourceWordOrder": 9,
                "qaVerified": True,
                "duplicateCount": 2,
                "word": "the",
            },
        )


class WordTextFileTests(unittest.TestCase):
    def write(self, body: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".tsv", delete=False, encoding="utf-8"
        )
        handle.write(body)
        handle.close()
        self.addCleanup(Path(handle.name).unlink, True)
        return Path(handle.name)

    def test_pairs_are_read_in_order_without_duplicates(self):
        path = self.write("EN_US\tthe\nEN_GB\tthe\nEN_US\tthe\n\n")

        self.assertEqual(
            load_word_texts(path), (("EN_US", "the"), ("EN_GB", "the"))
        )

    def test_case_and_punctuation_stay_distinct(self):
        path = self.write("EN_US\tGood\nEN_US\tgood\n")

        pairs = load_word_texts(path)

        self.assertEqual(len(pairs), 2)
        self.assertNotEqual(
            word_fingerprint("EN_US", "Good"), word_fingerprint("EN_US", "good")
        )

    def test_missing_tab_and_unknown_locale_are_rejected(self):
        with self.assertRaises(ValueError):
            load_word_texts(self.write("EN_US the\n"))
        with self.assertRaises(ValueError):
            load_word_texts(self.write("EN_ZZ\tthe\n"))


class FakeS3:
    """copy-object까지 다루는 최소 S3 흉내. 저장은 키 → head 응답 dict."""

    def __init__(self, objects: dict[str, dict] | None = None):
        self.objects: dict[str, dict] = dict(objects or {})
        self.copies: list[tuple[str, str]] = []

    @staticmethod
    def _option(command, name):
        return command[command.index(name) + 1] if name in command else None

    def __call__(self, command, **kwargs):
        operation = command[2]
        key = self._option(command, "--key")
        if operation == "list-objects-v2":
            prefix = self._option(command, "--prefix")
            keys = [item for item in self.objects if item.startswith(prefix)]
            return _CompletedCall(0, json.dumps(keys or None))
        if operation == "head-object":
            if key not in self.objects:
                return _CompletedCall(1, "", "404 Not Found")
            return _CompletedCall(0, json.dumps(self.objects[key]))
        if operation == "copy-object":
            source = self._option(command, "--copy-source").split("/", 1)[1]
            self.copies.append((source, key))
            self.objects[key] = dict(self.objects[source])
            return _CompletedCall(0, "{}")
        if operation == "put-object":
            body = Path(self._option(command, "--body")).read_bytes()
            self.objects[key] = {
                "ContentLength": len(body),
                "ContentType": self._option(command, "--content-type"),
                "CacheControl": self._option(command, "--cache-control"),
                "Metadata": dict(
                    item.split("=", 1)
                    for item in self._option(command, "--metadata").split(",")
                ),
            }
            return _CompletedCall(0)
        raise AssertionError(f"unexpected aws command: {command[:3]}")


def audio_head(size: int, audio_sha: str) -> dict:
    return {
        "ContentLength": size,
        "ContentType": "audio/mpeg",
        "CacheControl": "public, max-age=31536000, immutable",
        "Metadata": {"audio-sha256": audio_sha, "model": "deepgram/aura-2"},
    }


class WordPoolBackfillTests(unittest.TestCase):
    def setUp(self):
        self.the = word_fingerprint("EN_US", "the")
        self.take = word_fingerprint("EN_US", "take")
        self.source_key = legacy_word_key(1200, "EN_US", 9, self.the)
        self.other_key = legacy_word_key(1201, "EN_US", 2, self.take)

    def build(self, objects=None):
        s3 = FakeS3(
            objects
            if objects is not None
            else {
                self.source_key: audio_head(100, "sha-the"),
                legacy_word_key(5, "EN_US", 1, self.the): audio_head(100, "sha-the"),
                self.other_key: audio_head(120, "sha-take"),
            }
        )
        plan = plan_word_pool(
            list(s3.objects), "bucket", preferred_expression_ranges=((982, 1938),)
        )
        return s3, plan

    def test_dry_run_writes_nothing(self):
        s3, plan = self.build()

        copied = execute_word_pool_backfill(plan, execute=False, aws_runner=s3)

        self.assertEqual(copied, 0)
        self.assertEqual(s3.copies, [])

    def test_execute_copies_each_unit_once_and_verifies(self):
        s3, plan = self.build()

        copied = execute_word_pool_backfill(plan, execute=True, aws_runner=s3)

        self.assertEqual(copied, 2)
        self.assertEqual(
            sorted(target for _, target in s3.copies),
            sorted([shared_word_key("EN_US", self.the), shared_word_key("EN_US", self.take)]),
        )
        # 중복 3개짜리 "the"도 딱 한 번만 복사된다
        self.assertEqual(
            [source for source, _ in s3.copies].count(self.source_key), 1
        )

    def test_second_run_copies_nothing(self):
        s3, plan = self.build()
        execute_word_pool_backfill(plan, execute=True, aws_runner=s3)

        replan = plan_word_pool(list(s3.objects), "bucket")
        copied = execute_word_pool_backfill(replan, execute=True, aws_runner=s3)

        self.assertEqual(copied, 0)
        self.assertEqual(len(replan.reused_entries), 2)

    def test_copy_that_lands_with_a_different_audio_sha_fails(self):
        s3, plan = self.build()
        original_copy = s3.__call__

        def corrupt(command, **kwargs):
            result = original_copy(command, **kwargs)
            if command[2] == "copy-object":
                key = command[command.index("--key") + 1]
                s3.objects[key]["Metadata"]["audio-sha256"] = "tampered"
            return result

        with self.assertRaises(ValueError) as caught:
            execute_word_pool_backfill(plan, execute=True, aws_runner=corrupt)
        self.assertIn("verification conflict", str(caught.exception))

    def test_missing_source_object_fails(self):
        s3, plan = self.build()
        del s3.objects[self.source_key]

        with self.assertRaises(ValueError) as caught:
            execute_word_pool_backfill(plan, execute=True, aws_runner=s3)
        self.assertIn("source object is missing", str(caught.exception))

    def test_verify_reports_drifted_and_missing_targets(self):
        s3, plan = self.build()
        execute_word_pool_backfill(plan, execute=True, aws_runner=s3)
        s3.objects[shared_word_key("EN_US", self.the)]["ContentLength"] = 999
        del s3.objects[shared_word_key("EN_US", self.take)]

        problems = verify_word_pool(plan, aws_runner=s3)

        self.assertEqual(len(problems), 2)
        self.assertTrue(any("differs from" in problem for problem in problems))
        self.assertTrue(any("missing" in problem for problem in problems))

    def test_object_without_audio_sha_is_not_accepted_as_verified(self):
        head = audio_head(100, "sha")
        head["Metadata"].pop("audio-sha256")
        self.assertFalse(_copied_head_matches(head, head))


class WordPoolIndexPublishTests(unittest.TestCase):
    def test_index_is_published_under_a_content_hash_key(self):
        s3 = FakeS3()
        index = {"schemaVersion": 1, "issue": "LAN-475", "entries": []}

        key = publish_word_pool_index(index, "bucket", execute=True, aws_runner=s3)

        digest = hashlib.sha256(canonical_manifest_bytes(index)).hexdigest()
        self.assertEqual(
            key, f"content/expression-pronunciation-audio/word-pool/{digest}.json"
        )
        self.assertIn(key, s3.objects)

    def test_dry_run_publish_writes_nothing(self):
        s3 = FakeS3()

        publish_word_pool_index({"entries": []}, "bucket", execute=False, aws_runner=s3)

        self.assertEqual(s3.objects, {})


class WordPoolCliTests(unittest.TestCase):
    def setUp(self):
        self.the = word_fingerprint("EN_US", "the")
        self.output = Path(tempfile.mkdtemp()) / "word-pool-index.json"

    def run_cli(self, s3, *extra):
        with unittest.mock.patch(
            "scripts.expression_pronunciation_audio.subprocess.run", s3
        ):
            return main(
                [
                    "backfill-word-pool",
                    "--bucket",
                    "bucket",
                    "--output",
                    str(self.output),
                    *extra,
                ]
            )

    def test_unmatched_fingerprints_stop_the_run(self):
        words = Path(tempfile.mkdtemp()) / "words.tsv"
        words.write_text("EN_US\ttake\n", encoding="utf-8")
        s3 = FakeS3({legacy_word_key(5, "EN_US", 1, self.the): audio_head(10, "sha")})

        code = self.run_cli(s3, "--words", str(words), "--execute")

        self.assertEqual(code, 1)
        self.assertEqual(s3.copies, [])
        self.assertFalse(self.output.exists())

    def test_keep_puts_unmatched_into_the_pool_without_a_word(self):
        words = Path(tempfile.mkdtemp()) / "words.tsv"
        words.write_text("EN_US\ttake\n", encoding="utf-8")
        s3 = FakeS3({legacy_word_key(5, "EN_US", 1, self.the): audio_head(10, "sha")})

        code = self.run_cli(
            s3, "--words", str(words), "--unmatched", "keep", "--execute"
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(s3.copies), 1)
        index = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(index["summary"]["entries"], 1)
        self.assertNotIn("word", index["entries"][0])

    def test_drop_leaves_unmatched_out_of_the_pool_entirely(self):
        words = Path(tempfile.mkdtemp()) / "words.tsv"
        words.write_text("EN_US\ttake\n", encoding="utf-8")
        s3 = FakeS3({legacy_word_key(5, "EN_US", 1, self.the): audio_head(10, "sha")})

        code = self.run_cli(
            s3, "--words", str(words), "--unmatched", "drop", "--execute"
        )

        self.assertEqual(code, 0)
        self.assertEqual(s3.copies, [])
        index = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(index["summary"]["entries"], 0)

    def test_dry_run_still_writes_the_index_but_copies_nothing(self):
        s3 = FakeS3({legacy_word_key(5, "EN_US", 1, self.the): audio_head(10, "sha")})

        code = self.run_cli(s3)

        self.assertEqual(code, 0)
        self.assertEqual(s3.copies, [])
        self.assertTrue(self.output.exists())


class Boto3CopyObjectTests(unittest.TestCase):
    def test_copy_object_follows_the_cli_contract(self):
        client = Mock()
        runner = Boto3AwsRunner.__new__(Boto3AwsRunner)
        runner._client = client

        result = runner(
            ["aws", "s3api", "copy-object", "--bucket", "b", "--key", "target",
             "--copy-source", "b/source", "--metadata-directive", "COPY",
             "--output", "json"],
            capture_output=True, text=True, check=False,
        )

        self.assertEqual(result.returncode, 0)
        client.copy_object.assert_called_once_with(
            Bucket="b", Key="target", CopySource="b/source", MetadataDirective="COPY"
        )
