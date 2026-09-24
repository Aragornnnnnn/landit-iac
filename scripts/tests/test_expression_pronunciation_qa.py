# LAN-453 발음 자산 TTS 품질 검사 도구의 판정 규칙을 검증한다.

import array
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.expression_pronunciation_audio import (
    asset_id,
    audio_path_for,
    generate_assets,
    load_generation_state,
)
# QA 스크립트는 자기 디렉터리를 sys.path에 넣고 expression_pronunciation_audio를 최상위
# 모듈로 임포트한다. 같은 파일이라도 scripts.* 경로로 임포트하면 다른 모듈 객체가 되어
# 예외 클래스가 일치하지 않으므로, 예외는 QA 모듈이 들고 있는 참조에서 가져온다.
from scripts.expression_pronunciation_qa import epa as qa_epa
from scripts.expression_pronunciation_qa import (
    SILENCE_RMS_DBFS,
    format_pool_failures,
    pool_snapshot,
    run_check_pool,
    Adjudication,
    adjudicate_audio,
    run_adjudication,
    check_audio,
    normalize_tokens,
    pick_samples,
    resynthesize,
    rms_dbfs,
    run_check,
    summarize,
    systematic_failures,
    transcript_matches,
    variant_text,
)
from scripts.tests.test_expression_pronunciation_audio import (
    FakeS3,
    fake_probe_runner,
    load_snapshot,
    make_source_payload,
)


class NormalizeTests(unittest.TestCase):
    def test_strips_punctuation_case_and_curly_quotes(self):
        self.assertEqual(
            normalize_tokens("Don’t worry — I’ll help out!"),
            ["don't", "worry", "i'll", "help", "out"],
        )

    def test_numbers_become_words(self):
        self.assertEqual(normalize_tokens("at 20 past"), ["at", "twenty", "past"])
        self.assertTrue(transcript_matches("at 20 past", "at twenty past"))
        self.assertTrue(transcript_matches("at twenty past", "at 20 past"))

    def test_currency_matches_spelled_out_dollars(self):
        # Whisper가 "$10"으로 적어 불합격되던 LAN-471 실측 사례
        self.assertTrue(transcript_matches("It was only ten dollars.", "It was only $10."))
        self.assertTrue(transcript_matches("They were one dollar each.", "They were $1 each."))
        self.assertTrue(transcript_matches("I shelled out $120 for it.", "I shelled out $120 for it."))
        self.assertTrue(transcript_matches("It costs five dollars fifty cents", "It costs $5.50"))
        # 단수·복수가 틀리면 여전히 불합격
        self.assertFalse(transcript_matches("one dollars", "$1"))

    def test_percent_matches_spelled_out(self):
        self.assertTrue(
            transcript_matches("It was on sale for thirty percent off.", "It was on sale for 30% off.")
        )

    def test_compound_spacing_is_ignored(self):
        self.assertTrue(transcript_matches("log in", "login"))
        self.assertTrue(transcript_matches("meet up", "Meetup"))
        self.assertTrue(transcript_matches("I bought it secondhand online.", "I bought it second hand online."))
        # 공백만 다른 게 아니라 글자가 다르면 여전히 불합격
        self.assertFalse(transcript_matches("close friend", "close friends"))

    def test_ordinals_match_spelled_out(self):
        self.assertTrue(
            transcript_matches("It canceled at the eleventh hour.", "It canceled at the 11th hour.")
        )
        self.assertTrue(transcript_matches("the twenty first", "the 21st"))

    def test_hyphen_splits_like_whisper(self):
        self.assertTrue(transcript_matches("a well-known place", "a well known place"))


class MatchTests(unittest.TestCase):
    def test_exact_after_normalization(self):
        self.assertTrue(transcript_matches("Take care of it.", " take care of it"))

    def test_homophones_absorbed_by_cmu_phonemes(self):
        self.assertTrue(transcript_matches("the way to go", "the weigh two go"))
        self.assertTrue(transcript_matches("you're right", "your right"))

    def test_contractions_expand_both_ways(self):
        self.assertTrue(transcript_matches("I'll help out", "I will help out"))
        self.assertTrue(transcript_matches("I will help out", "I'll help out"))

    def test_missing_word_fails(self):
        self.assertFalse(transcript_matches("take care of", "Take care."))

    def test_wrong_word_fails(self):
        self.assertFalse(transcript_matches("took", "Tuck."))

    def test_extra_trailing_fragment_fails(self):
        self.assertFalse(transcript_matches("the", "the da-"))

    def test_empty_transcript_fails(self):
        self.assertFalse(transcript_matches("it", ""))


class SingleWordLenientTests(unittest.TestCase):
    def test_one_phoneme_apart_passes_only_for_single_word_clips(self):
        for expected, heard in (("an", "and"), ("call", "cool"), ("a", "I"), ("we're", "with")):
            self.assertTrue(
                transcript_matches(expected, heard, single_word_lenient=True), (expected, heard)
            )
            self.assertFalse(transcript_matches(expected, heard), (expected, heard))

    def test_two_phonemes_apart_still_fails(self):
        self.assertFalse(transcript_matches("move", "news", single_word_lenient=True))
        self.assertFalse(transcript_matches("took", "sit", single_word_lenient=True))

    def test_listened_ok_pairs_are_accent_specific(self):
        self.assertTrue(
            transcript_matches("I'll", "Oh.", single_word_lenient=True, accent_locale="EN_AU")
        )
        self.assertFalse(
            transcript_matches("I'll", "Oh.", single_word_lenient=True, accent_locale="EN_US")
        )
        self.assertTrue(
            transcript_matches("year", "Yeah.", single_word_lenient=True, accent_locale="EN_AU")
        )
        # 억양 특성은 "yeah"로 들린 경우만이다 — 무음·다른 단어는 여전히 불합격
        self.assertFalse(
            transcript_matches("year", "", single_word_lenient=True, accent_locale="EN_AU")
        )

    def test_leniency_never_applies_to_multi_word_text(self):
        self.assertFalse(
            transcript_matches("take care of", "take care off", single_word_lenient=True)
        )


class SilenceTests(unittest.TestCase):
    def test_rms_of_silence_is_minus_infinity(self):
        self.assertEqual(rms_dbfs(array.array("h", [0] * 1600)), -math.inf)

    def test_rms_of_full_scale_square_is_zero_dbfs(self):
        samples = array.array("h", [32767, -32767] * 800)
        self.assertAlmostEqual(rms_dbfs(samples), 0.0, places=2)

    def test_silent_file_fails_even_if_whisper_hallucinates(self):
        transcribe = Mock(return_value="Thanks for watching!")
        result = check_audio(
            Path("x.mp3"),
            "Thanks for watching!",
            transcribe,
            decoder=lambda path: array.array("h", [3] * 16000),
        )
        self.assertFalse(result.passed)
        self.assertLess(result.rms_dbfs, SILENCE_RMS_DBFS)
        transcribe.assert_not_called()

    def test_audible_and_matching_passes(self):
        result = check_audio(
            Path("x.mp3"),
            "help out",
            Mock(return_value=" Help out."),
            decoder=lambda path: array.array("h", [8000, -8000] * 8000),
        )
        self.assertTrue(result.passed)


class SilenceOnlyTests(unittest.TestCase):
    def test_no_transcriber_means_silence_check_only(self):
        loud = lambda path: array.array("h", [8000, -8000] * 8000)
        self.assertTrue(check_audio(Path("x.mp3"), "took", None, decoder=loud).passed)
        quiet = lambda path: array.array("h", [3] * 16000)
        self.assertFalse(check_audio(Path("x.mp3"), "took", None, decoder=quiet).passed)

    def test_silence_only_kinds_skip_whisper_for_words(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            make_generated_work_dir(snapshot, work_dir)
            transcribe = Mock(return_value="wrong")
            outcomes = run_check(
                snapshot,
                work_dir,
                work_dir / "qa.json",
                transcribe=transcribe,
                client=None,
                max_resynth=0,
                workers=2,
                kinds={"word", "sentence"},
                silence_only_kinds={"word"},
                decoder=lambda path: array.array("h", [8000, -8000] * 8000),
                progress=lambda message: None,
            )
            kinds = {o.kind for o in outcomes.values()}
            self.assertEqual(kinds, {"word", "sentence"})
            self.assertTrue(all(o.passed for o in outcomes.values() if o.kind == "word"))
            self.assertTrue(all(not o.passed for o in outcomes.values() if o.kind == "sentence"))
            self.assertEqual(transcribe.call_count, 2)  # 문장 2개(locale 2개)만 전사


class VariantTests(unittest.TestCase):
    def test_cycles_original_period_comma(self):
        self.assertEqual(variant_text("help out", 0), "help out")
        self.assertEqual(variant_text("help out", 1), "help out.")
        self.assertEqual(variant_text("help out", 2), "help out,")
        self.assertEqual(variant_text("help out", 3), "help out")

    def test_suffix_override_wins_over_cycle(self):
        self.assertEqual(variant_text("her", 1, suffix=","), "her,")
        self.assertEqual(variant_text("her.", 0, suffix=","), "her,")

    def test_replaces_existing_trailing_punctuation(self):
        self.assertEqual(variant_text("Take care of it.", 2), "Take care of it,")


def make_generated_work_dir(snapshot, work_dir: Path):
    client = Mock()
    client.synthesize = Mock(
        side_effect=lambda asset: Mock(
            body=f"mp3:{asset_id(asset)}".encode(), generation_id="gen-x"
        )
    )
    generate_assets(
        snapshot,
        work_dir,
        client=client,
        probe_runner=fake_probe_runner,
        probe_name="ffprobe",
    )


class ResynthTests(unittest.TestCase):
    def test_keeps_path_and_fingerprint_but_updates_audio(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            make_generated_work_dir(snapshot, work_dir)
            asset = snapshot.assets[0]
            before = load_generation_state(work_dir / "state.json")[asset_id(asset)]

            client = Mock()
            client.synthesize = Mock(
                return_value=Mock(body=b"mp3:new", generation_id="gen-new")
            )
            regenerated = resynthesize(
                asset,
                1,
                work_dir,
                client,
                probe_runner=fake_probe_runner,
                probe_name="ffprobe",
            )

            self.assertEqual(client.synthesize.call_args.args[0].text, asset.text + ".")
            self.assertEqual(regenerated.path, before.path)
            self.assertEqual(
                regenerated.generation_fingerprint, before.generation_fingerprint
            )
            self.assertNotEqual(regenerated.audio_sha256, before.audio_sha256)
            self.assertEqual(audio_path_for(work_dir, asset).read_bytes(), b"mp3:new")


class RunCheckTests(unittest.TestCase):
    def loud(self, path):
        return array.array("h", [8000, -8000] * 8000)

    def test_resynth_until_pass_and_state_sha_follows_new_audio(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            make_generated_work_dir(snapshot, work_dir)
            report = work_dir / "qa.json"
            bad = asset_id(snapshot.assets[0])
            calls = {"n": 0}

            def transcribe(path):
                # 첫 자산만 첫 두 번 틀리고 세 번째부터 맞는다.
                if path == audio_path_for(work_dir, snapshot.assets[0]):
                    calls["n"] += 1
                    if calls["n"] <= 2:
                        return "wrong words"
                text = next(
                    a.text for a in snapshot.assets if audio_path_for(work_dir, a) == path
                )
                return text

            client = Mock()
            client.synthesize = Mock(
                side_effect=lambda asset: Mock(
                    body=f"resynth:{asset.text}".encode(), generation_id="gen-r"
                )
            )
            outcomes = run_check(
                snapshot,
                work_dir,
                report,
                transcribe=transcribe,
                client=client,
                max_resynth=6,
                workers=2,
                decoder=self.loud,
                probe_runner=fake_probe_runner,
                probe_name="ffprobe",
                progress=lambda message: None,
            )

            self.assertTrue(outcomes[bad].passed)
            self.assertEqual(outcomes[bad].attempts, 3)
            self.assertEqual(client.synthesize.call_count, 2)
            state = load_generation_state(work_dir / "state.json")
            self.assertEqual(
                state[bad].audio_sha256, outcomes[bad].audio_sha256
            )
            summary = summarize(outcomes)
            self.assertEqual(summary["passedAfterResynth"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(
                json.loads(report.read_text())["summary"]["passedFirstTry"],
                len(snapshot.assets) - 1,
            )

    def test_exhausted_retries_land_in_failure_list_and_are_rechecked_next_run(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            make_generated_work_dir(snapshot, work_dir)
            report = work_dir / "qa.json"
            bad_path = audio_path_for(work_dir, snapshot.assets[0])

            def transcribe(path):
                if path == bad_path:
                    return "Hey"
                return next(
                    a.text for a in snapshot.assets if audio_path_for(work_dir, a) == path
                )

            client = Mock()
            client.synthesize = Mock(
                side_effect=lambda asset: Mock(
                    body=f"resynth:{asset.text}".encode(), generation_id="gen-r"
                )
            )
            kwargs = dict(
                transcribe=transcribe,
                client=client,
                max_resynth=2,
                workers=2,
                decoder=self.loud,
                probe_runner=fake_probe_runner,
                probe_name="ffprobe",
                progress=lambda message: None,
            )
            outcomes = run_check(snapshot, work_dir, report, **kwargs)
            bad = asset_id(snapshot.assets[0])
            self.assertFalse(outcomes[bad].passed)
            self.assertEqual(outcomes[bad].attempts, 3)
            self.assertEqual(client.synthesize.call_count, 2)

            # 두 번째 실행: 합격한 파일은 캐시로 건너뛰고 실패만 다시 본다.
            transcribe_again = Mock(side_effect=transcribe)
            kwargs["transcribe"] = transcribe_again
            run_check(snapshot, work_dir, report, **kwargs)
            checked_paths = {call.args[0] for call in transcribe_again.call_args_list}
            self.assertEqual(checked_paths, {bad_path})

    def test_systematic_failures_group_repeated_misreads(self):
        # 같은 억양이 같은 단어("it")를 세 번 모두 "Hey"로 읽으면 계통적 실패로 묶인다.
        payload = make_source_payload()
        payload["expressions"][0]["sentenceText"] = "it it it"
        payload["expressions"][0]["words"] = [
            {"order": order, "word": "it"} for order in (1, 2, 3)
        ]
        snapshot = load_snapshot(payload)
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            make_generated_work_dir(snapshot, work_dir)
            outcomes = run_check(
                snapshot,
                work_dir,
                work_dir / "qa.json",
                transcribe=lambda path: "Hey",
                client=None,
                max_resynth=0,
                workers=2,
                decoder=self.loud,
                progress=lambda message: None,
            )
            patterns = systematic_failures(outcomes)
            self.assertEqual(
                {(p["accentLocale"], p["text"], p["count"]) for p in patterns},
                {("EN_US", "it", 3), ("EN_GB", "it", 3)},
            )
            self.assertTrue(all(p["heard"] == "hey" for p in patterns))


class SilenceRetryTests(unittest.TestCase):
    def test_silent_clip_is_resynthesized_with_comma_variant(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            make_generated_work_dir(snapshot, work_dir)
            target = snapshot.assets[0]
            target_path = audio_path_for(work_dir, target)
            calls = {"n": 0}

            def decoder(path):
                if path == target_path and calls["n"] == 0:
                    calls["n"] += 1
                    return array.array("h", [0] * 16000)  # 첫 파일만 무음
                return array.array("h", [8000, -8000] * 8000)

            client = Mock()
            client.synthesize = Mock(
                side_effect=lambda asset: Mock(
                    body=f"resynth:{asset.text}".encode(), generation_id="gen-r"
                )
            )
            outcomes = run_check(
                snapshot,
                work_dir,
                work_dir / "qa.json",
                transcribe=lambda path: next(
                    a.text for a in snapshot.assets if audio_path_for(work_dir, a) == path
                ),
                client=client,
                max_resynth=3,
                workers=1,
                asset_ids={asset_id(target)},
                decoder=decoder,
                probe_runner=fake_probe_runner,
                probe_name="ffprobe",
                progress=lambda message: None,
            )
            self.assertTrue(outcomes[asset_id(target)].passed)
            self.assertEqual(client.synthesize.call_args.args[0].text, target.text + ",")
            self.assertEqual(client.synthesize.call_count, 1)


def make_judgment_response(status, body):
    return Mock(status=status, headers={}, body=json.dumps(body).encode())


class AdjudicationTests(unittest.TestCase):
    def reply(self, content):
        return make_judgment_response(200, {"choices": [{"message": {"content": content}}]})

    def clip(self):
        handle = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        handle.write(b"mp3")
        handle.close()
        return Path(handle.name)

    def test_expected_text_is_never_sent_to_the_model(self):
        """기대 텍스트를 프롬프트에 넣으면 모델이 그대로 따라 적는다 (2026-09-10 실측)."""
        path = self.clip()
        sent = {}

        def capture(payload, headers, *rest):
            sent["payload"] = payload
            return self.reply('{"heard": "Good question", "defect": "none"}')

        try:
            verdict = adjudicate_audio("key", path, "purple elephant sandwich", requester=capture)
        finally:
            path.unlink(missing_ok=True)
        prompt = sent["payload"]["messages"][0]["content"][0]["text"]
        self.assertNotIn("purple elephant sandwich", prompt)
        # 대조는 코드가 한다 — 들린 말이 기대와 다르면 불합격
        self.assertFalse(verdict.clean)
        self.assertEqual(verdict.heard, "Good question")
        self.assertEqual(verdict.problem, "wrong_words")

    def test_matching_transcript_with_no_defect_is_clean(self):
        path = self.clip()
        try:
            verdict = adjudicate_audio(
                "key", path, "help out",
                requester=lambda *a, **k: self.reply(
                    '```json\n{"heard": "Help out.", "defect": "none"}\n```'
                ),
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(verdict, Adjudication(True, "Help out.", "none"))

    def test_reported_defect_fails_even_when_words_match(self):
        """잡음 꼬리·잘림은 전사가 맞아도 불량이다 — RMS·Whisper가 못 잡는 유형."""
        path = self.clip()
        try:
            for defect in ("noise", "truncated", "silent"):
                verdict = adjudicate_audio(
                    "key", path, "help out",
                    requester=lambda *a, **k: self.reply(
                        '{"heard": "help out", "defect": "%s"}' % defect
                    ),
                )
                self.assertFalse(verdict.clean, defect)
                self.assertEqual(verdict.problem, defect)
        finally:
            path.unlink(missing_ok=True)

    def test_word_leniency_applies_like_whisper_rules(self):
        path = self.clip()
        try:
            lenient = adjudicate_audio(
                "key", path, "an", single_word_lenient=True,
                requester=lambda *a, **k: self.reply('{"heard": "and", "defect": "none"}'),
            )
            strict = adjudicate_audio(
                "key", path, "an",
                requester=lambda *a, **k: self.reply('{"heard": "and", "defect": "none"}'),
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertTrue(lenient.clean)
        self.assertFalse(strict.clean)

    def test_unintelligible_and_malformed_are_unresolved_not_clean(self):
        path = self.clip()
        try:
            for content in (
                '{"heard": "mmm", "defect": "unintelligible"}',
                '{"heard": "x"}',
                "not json",
            ):
                verdict = adjudicate_audio(
                    "key", path, "it", requester=lambda *a, **k: self.reply(content)
                )
                self.assertIsNone(verdict.clean, content)
            with self.assertRaises(qa_epa.AccentVerificationError):
                adjudicate_audio(
                    "key", path, "it",
                    requester=lambda *a, **k: make_judgment_response(500, {}),
                )
            with self.assertRaises(qa_epa.AccentVerificationError):
                adjudicate_audio(
                    "key", path, "it",
                    requester=lambda *a, **k: make_judgment_response(200, {"choices": []}),
                )
        finally:
            path.unlink(missing_ok=True)

    def build_report(self, work_dir, snapshot):
        make_generated_work_dir(snapshot, work_dir)
        report = work_dir / "qa.json"
        assets = []
        for index, asset in enumerate(snapshot.assets):
            assets.append(
                {
                    "assetId": asset_id(asset),
                    "text": asset.text,
                    "kind": asset.kind,
                    "accentLocale": asset.accent_locale,
                    "passed": index % 2 == 1,
                    "attempts": 1,
                    "firstReason": "" if index % 2 else "transcript mismatch",
                    "lastReason": "" if index % 2 else "transcript mismatch",
                    "lastTranscript": "x",
                    "lastRmsDbfs": -20.0,
                    "audioSha256": "sha",
                }
            )
        report.write_text(json.dumps({"schemaVersion": 1, "summary": {}, "assets": assets}))
        return report

    def test_non_object_json_is_unresolved(self):
        path = self.clip()
        try:
            for content in ("[]", "null", "42"):
                with self.subTest(content=content):
                    verdict = adjudicate_audio(
                        "key", path, "it", requester=lambda *a: self.reply(content)
                    )
                    self.assertIsNone(verdict.clean)
        finally:
            path.unlink(missing_ok=True)

    def test_network_failure_preserves_other_verdicts(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            report = self.build_report(work_dir, snapshot)
            failed_path = audio_path_for(work_dir, snapshot.assets[2])

            def judge(api_key, path, *args, **kwargs):
                if path == failed_path:
                    raise TimeoutError("request timed out")
                return Adjudication(True, "ok", "none")

            summary = run_adjudication(
                report, work_dir, snapshot, "key", workers=2, apply_verdicts=True,
                adjudicator=judge, progress=lambda m: None,
            )
            self.assertEqual(summary["unresolved"], 1)
            self.assertEqual(summary["geminiSaysClean"], summary["failedJudged"] - 1)
            rows = json.loads(report.read_text())["assets"]
            self.assertEqual(sum(not row["passed"] for row in rows), 1)

    def test_apply_refreshes_report_summary(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            report = self.build_report(work_dir, snapshot)
            payload = json.loads(report.read_text())
            payload["summary"] = {"failed": 6, "transcribeTimeouts": 2}
            report.write_text(json.dumps(payload))
            run_adjudication(
                report, work_dir, snapshot, "key", workers=2, apply_verdicts=True,
                adjudicator=lambda *a, **k: Adjudication(True, "ok", "none"),
                progress=lambda m: None,
            )
            payload = json.loads(report.read_text())
            self.assertTrue(all(row["passed"] for row in payload["assets"]))
            self.assertEqual(payload["summary"]["failed"], 0)
            self.assertEqual(payload["summary"]["failedByLocale"], {})
            self.assertEqual(payload["summary"]["passedFirstTry"], len(snapshot.assets))
            self.assertEqual(payload["summary"]["transcribeTimeouts"], 2)

    def test_records_verdicts_without_flipping_unless_applied(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            report = self.build_report(work_dir, snapshot)
            summary = run_adjudication(
                report, work_dir, snapshot, "key", workers=2,
                adjudicator=lambda *a, **k: Adjudication(True, "ok", "none"),
                progress=lambda m: None,
            )
            rows = {r["assetId"]: r for r in json.loads(report.read_text())["assets"]}
            self.assertEqual(summary["geminiSaysClean"], summary["failedJudged"])
            self.assertFalse(summary["applied"])
            self.assertTrue(all(r.get("geminiClean") for r in rows.values() if not r["passed"]))
            self.assertTrue(any(not r["passed"] for r in rows.values()))

            run_adjudication(
                report, work_dir, snapshot, "key", workers=2, apply_verdicts=True,
                adjudicator=lambda *a, **k: Adjudication(True, "ok", "none"),
                progress=lambda m: None,
            )
            rows = json.loads(report.read_text())["assets"]
            self.assertTrue(all(r["passed"] for r in rows))
            self.assertTrue(any(r["lastReason"].startswith("gemini-clean:") for r in rows))

    def test_confirmed_defects_and_passed_sample_are_counted(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            report = self.build_report(work_dir, snapshot)
            summary = run_adjudication(
                report, work_dir, snapshot, "key", workers=2, sample_passed=2,
                adjudicator=lambda *a, **k: Adjudication(False, "hey", "noise"),
                progress=lambda m: None,
            )
            self.assertEqual(summary["geminiSaysClean"], 0)
            self.assertEqual(summary["geminiConfirmsDefect"], summary["failedJudged"])
            self.assertEqual(summary["problemCounts"], {"noise": summary["failedJudged"]})
            self.assertEqual(summary["passedSampleJudged"], 2)
            self.assertEqual(summary["passedSampleDefects"], 2)

    def test_request_failure_is_unresolved_not_clean(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            report = self.build_report(work_dir, snapshot)

            def boom(*a, **k):
                raise qa_epa.AccentVerificationError("openrouter down")

            summary = run_adjudication(
                report, work_dir, snapshot, "key", workers=2, apply_verdicts=True,
                adjudicator=boom, progress=lambda m: None,
            )
            self.assertEqual(summary["unresolved"], summary["failedJudged"])
            self.assertEqual(summary["geminiSaysClean"], 0)
            rows = json.loads(report.read_text())["assets"]
            self.assertTrue(any(not r["passed"] for r in rows))


class InterruptedRunTests(unittest.TestCase):
    def test_interrupted_filtered_run_never_drops_assets_from_report(self):
        """재검사를 도중에 멈춰도 아직 검사 안 한 자산이 보고서에서 사라지면 안 된다 (LAN-471)."""
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            make_generated_work_dir(snapshot, work_dir)
            report = work_dir / "qa.json"
            loud = lambda path: array.array("h", [8000, -8000] * 8000)
            text_of = {audio_path_for(work_dir, a): a.text for a in snapshot.assets}
            # 1차: 전체를 정상 검사해 완전한 보고서를 만든다
            run_check(
                snapshot, work_dir, report, transcribe=lambda p: text_of[p], client=None,
                max_resynth=0, workers=1, decoder=loud, progress=lambda m: None,
            )
            everyone = {asset_id(a) for a in snapshot.assets}
            self.assertEqual({r["assetId"] for r in json.loads(report.read_text())["assets"]}, everyone)

            # 2차: 불합격으로 남은 일부만 재검사하다가 두 번째 자산에서 강제로 멈춘다
            # (실제로도 불합격분만 재검사한다 — 합격+sha 일치는 건너뛰므로 불합격으로 만들어 둔다)
            targets = [a for a in snapshot.assets if a.kind == "word"][:3]
            target_ids = {asset_id(a) for a in targets}
            payload = json.loads(report.read_text())
            for row in payload["assets"]:
                if row["assetId"] in target_ids:
                    row["passed"] = False
            report.write_text(json.dumps(payload))
            seen = {"n": 0}

            def interrupt_on_second(path):
                seen["n"] += 1
                if seen["n"] == 2:
                    raise KeyboardInterrupt
                return text_of[path]

            with self.assertRaises(KeyboardInterrupt):
                run_check(
                    snapshot, work_dir, report, transcribe=interrupt_on_second, client=None,
                    max_resynth=0, workers=1, asset_ids=target_ids,
                    decoder=loud, progress=lambda m: None,
                )
            kept = {r["assetId"] for r in json.loads(report.read_text())["assets"]}
            self.assertEqual(kept, everyone)


class WordRetryTests(unittest.TestCase):
    def run_one_mismatch(self, word_text):
        """해당 단어 클립만 첫 전사를 틀리게 만들고, 재합성 요청에 쓰인 입력을 돌려준다."""
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            make_generated_work_dir(snapshot, work_dir)
            word = next(a for a in snapshot.assets if a.kind == "word" and a.text == word_text)
            word_path = audio_path_for(work_dir, word)
            calls = {"n": 0}

            def transcribe(path):
                if path == word_path and calls["n"] == 0:
                    calls["n"] += 1
                    return "completely different"  # 무음은 아니고 오인식
                return next(a.text for a in snapshot.assets if audio_path_for(work_dir, a) == path)

            client = Mock()
            client.synthesize = Mock(
                side_effect=lambda asset: Mock(body=f"r:{asset.text}".encode(), generation_id="g")
            )
            run_check(
                snapshot, work_dir, work_dir / "qa.json",
                transcribe=transcribe, client=client, max_resynth=3, workers=1,
                asset_ids={asset_id(word)},
                decoder=lambda path: array.array("h", [8000, -8000] * 8000),
                probe_runner=fake_probe_runner, probe_name="ffprobe",
                progress=lambda m: None,
            )
            return client.synthesize.call_args.args[0].text

    def test_function_word_mismatch_is_resynthesized_with_comma(self):
        self.assertEqual(self.run_one_mismatch("it"), "it,")

    def test_content_word_keeps_the_original_variant_cycle(self):
        # 일반 단어는 쉼표 효과를 재지 않았으므로 기존 순환을 그대로 쓴다 — 첫 재합성은 원문
        self.assertEqual(self.run_one_mismatch("nothing"), "nothing")


class SampleTests(unittest.TestCase):
    def test_samples_are_balanced_by_locale_and_deterministic(self):
        snapshot = load_snapshot(make_source_payload())
        first = pick_samples(snapshot, 6, seed=1)
        second = pick_samples(snapshot, 6, seed=1)
        self.assertEqual(first, second)
        locales = [asset.accent_locale for asset in first]
        self.assertEqual(locales.count("EN_US"), 3)
        self.assertEqual(locales.count("EN_GB"), 3)
        self.assertEqual(len({asset_id(a) for a in first}), 6)




def pool_index_payload(entries: list[dict]) -> dict:
    return {
        "schemaVersion": 2,
        "issue": "LAN-475",
        "keyPrefix": "content/expression-pronunciation-audio",
        "bucket": "bucket",
        "preferredExpressionRanges": [],
        "summary": {},
        "entries": entries,
    }


def pool_entry(locale: str, word: str, expression_id: int, order: int, *, qa: bool,
               duplicates: int = 1) -> dict:
    fingerprint = qa_epa.word_fingerprint(locale, word)
    return {
        "accentLocale": locale,
        "fingerprint": fingerprint,
        "targetKey": qa_epa.shared_word_key(locale, fingerprint),
        "sourceKey": (
            f"content/expression-pronunciation-audio/{expression_id}/{locale}"
            f"/word/{order}/{fingerprint}.mp3"
        ),
        "sourceExpressionId": expression_id,
        "sourceWordOrder": order,
        "qaVerified": qa,
        "duplicateCount": duplicates,
        "published": True,
        "word": word,
    }


class WordPoolAssetTests(unittest.TestCase):
    def test_asset_keeps_the_legacy_asset_id_shape(self):
        entry = qa_epa.load_word_pool_index(
            write_json(pool_index_payload([pool_entry("EN_AU", "ago", 2386, 6, qa=True)]))
        )[0]

        asset = qa_epa.word_pool_asset(entry)

        self.assertEqual(qa_epa.asset_id(asset), "2386/EN_AU/word-6")
        self.assertEqual(qa_epa.generation_fingerprint(asset), entry.fingerprint)

    def test_entry_without_a_word_is_rejected(self):
        payload = pool_index_payload([pool_entry("EN_US", "the", 5, 1, qa=False)])
        payload["entries"][0].pop("word")
        entry = qa_epa.load_word_pool_index(write_json(payload))[0]

        with self.assertRaises(ValueError) as caught:
            qa_epa.word_pool_asset(entry)
        self.assertIn("no word text", str(caught.exception))
        # 무엇을 해야 하는지까지 말해 준다 — 색인을 다시 만들라는 것
        self.assertIn("--words", str(caught.exception))
        self.assertIn("--unmatched drop", str(caught.exception))

    def test_entry_whose_word_does_not_hash_to_its_fingerprint_is_rejected(self):
        payload = pool_index_payload([pool_entry("EN_US", "the", 5, 1, qa=False)])
        payload["entries"][0]["word"] = "take"
        entry = qa_epa.load_word_pool_index(write_json(payload))[0]

        with self.assertRaises(ValueError) as caught:
            qa_epa.word_pool_asset(entry)
        self.assertIn("does not match its word text", str(caught.exception))

    def test_index_of_another_schema_is_rejected(self):
        payload = pool_index_payload([])
        payload["issue"] = "LAN-373"

        with self.assertRaises(ValueError):
            qa_epa.load_word_pool_index(write_json(payload))

    def test_colliding_asset_ids_stop_the_run(self):
        # 예문이 수정된 표현은 같은 단어 순서에 키가 둘이다 (표현 1942·1945·1946).
        entries = qa_epa.load_word_pool_index(
            write_json(
                pool_index_payload(
                    [
                        pool_entry("EN_US", "the", 1942, 6, qa=False),
                        pool_entry("EN_US", "take", 1942, 6, qa=False),
                    ]
                )
            )
        )

        with self.assertRaises(ValueError) as caught:
            pool_snapshot(entries)
        self.assertIn("collide on asset id", str(caught.exception))

    def test_identical_duplicate_entries_stop_the_run(self):
        # 해시까지 같은 완전 중복은 판정이 서로 덮어써 한쪽이 보고서에서 사라진다.
        # 개수만 보면 눈치채지 못하므로 여기서 막는다.
        row = pool_entry("EN_US", "the", 982, 7, qa=True)
        entries = qa_epa.load_word_pool_index(
            write_json(pool_index_payload([row, dict(row)]))
        )

        with self.assertRaises(ValueError) as caught:
            pool_snapshot(entries)
        self.assertIn("collide on asset id", str(caught.exception))


def write_json(payload: dict) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(payload, handle, ensure_ascii=False)
    handle.close()
    return Path(handle.name)


class SilenceOnlyAssetIdTests(unittest.TestCase):
    def loud(self, path):
        return array.array("h", [8000, -8000] * 8000)

    def test_only_the_named_assets_skip_transcription(self):
        snapshot = load_snapshot(make_source_payload())
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            make_generated_work_dir(snapshot, work_dir)
            skipped = asset_id(snapshot.assets[0])
            transcribed: list[Path] = []

            def transcribe(path):
                transcribed.append(path)
                return next(
                    a.text for a in snapshot.assets
                    if audio_path_for(work_dir, a) == path
                )

            outcomes = run_check(
                snapshot,
                work_dir,
                work_dir / "qa.json",
                transcribe=transcribe,
                client=None,
                max_resynth=0,
                workers=2,
                silence_only_asset_ids=frozenset({skipped}),
                decoder=self.loud,
                probe_runner=fake_probe_runner,
                probe_name="ffprobe",
                progress=lambda message: None,
            )

            self.assertNotIn(
                audio_path_for(work_dir, snapshot.assets[0]), transcribed
            )
            self.assertEqual(len(transcribed), len(snapshot.assets) - 1)
            self.assertTrue(outcomes[skipped].passed)
            self.assertEqual(outcomes[skipped].last_transcript, "")


class CheckPoolTests(unittest.TestCase):
    def loud(self, path):
        return array.array("h", [8000, -8000] * 8000)

    def build(self, entries: list[dict]):
        s3 = FakeS3()
        for item in entries:
            s3.add_audio(item["targetKey"], f"mp3:{item['word']}:{item['accentLocale']}".encode())
        return s3, write_json(pool_index_payload(entries))

    def run_pool(self, s3, index, work_dir, **kwargs):
        transcribed: list[str] = []
        words = {}

        def transcribe(path):
            body = path.read_bytes().decode()
            transcribed.append(body)
            return words.get(body, body.split(":")[1])

        kwargs.setdefault("client", None)
        kwargs.setdefault("max_resynth", 0)
        result = run_check_pool(
            index,
            work_dir,
            work_dir / "qa.json",
            "bucket",
            transcribe=kwargs.pop("transcribe", transcribe),
            workers=2,
            aws_runner=kwargs.pop("aws_override", s3),
            probe_runner=fake_probe_runner,
            probe_name="ffprobe",
            decoder=self.loud,
            progress=lambda message: None,
            **kwargs,
        )
        return result, transcribed

    def test_qa_verified_units_are_only_checked_for_silence(self):
        entries = [
            pool_entry("EN_US", "the", 982, 7, qa=True, duplicates=852),
            pool_entry("EN_US", "warning", 5, 1, qa=False),
        ]
        s3, index = self.build(entries)
        with tempfile.TemporaryDirectory() as tmp:
            (summary, outcomes, _), transcribed = self.run_pool(s3, index, Path(tmp))

        self.assertEqual(summary["poolEntries"], 2)
        self.assertEqual(summary["silenceOnly"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(transcribed, ["mp3:warning:EN_US"])

    def test_recheck_transcribes_every_unit(self):
        entries = [pool_entry("EN_US", "the", 982, 7, qa=True)]
        s3, index = self.build(entries)
        with tempfile.TemporaryDirectory() as tmp:
            (summary, _, _), transcribed = self.run_pool(
                s3, index, Path(tmp), recheck_qa_verified=True
            )

        self.assertEqual(summary["silenceOnly"], 0)
        self.assertEqual(transcribed, ["mp3:the:EN_US"])

    def test_each_word_is_fetched_and_checked_once_however_many_expressions_use_it(self):
        entries = [pool_entry("EN_US", "the", 982, 7, qa=False, duplicates=852)]
        s3, index = self.build(entries)
        with tempfile.TemporaryDirectory() as tmp:
            (summary, outcomes, _), transcribed = self.run_pool(s3, index, Path(tmp))

        self.assertEqual(summary["total"], 1)
        self.assertEqual(len(transcribed), 1)
        self.assertEqual(len(outcomes), 1)

    def test_source_key_is_used_when_the_pool_copy_is_not_there_yet(self):
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3 = FakeS3()
        s3.add_audio(entry["sourceKey"], b"mp3:warning:EN_US")
        index = write_json(pool_index_payload([entry]))
        with tempfile.TemporaryDirectory() as tmp:
            (summary, _, _), transcribed = self.run_pool(s3, index, Path(tmp))

        self.assertEqual(summary["failed"], 0)
        self.assertEqual(transcribed, ["mp3:warning:EN_US"])

    def test_missing_object_stops_the_run(self):
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3 = FakeS3()
        index = write_json(pool_index_payload([entry]))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                self.run_pool(s3, index, Path(tmp))
        self.assertIn("word pool object is missing", str(caught.exception))

    def test_download_that_does_not_match_its_metadata_sha_stops_the_run(self):
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3 = FakeS3()
        s3.add_audio(entry["targetKey"], b"mp3:warning:EN_US")
        s3.bodies[entry["targetKey"]] = b"tampered"
        index = write_json(pool_index_payload([entry]))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                self.run_pool(s3, index, Path(tmp))
        self.assertIn("sha256 mismatch", str(caught.exception))

    def test_resynthesized_unit_is_published_back_to_its_pool_key(self):
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False, duplicates=40)
        s3, index = self.build([entry])
        client = Mock()
        # 재합성 바이트가 원본과 달라야 교체 대상이 된다 (같으면 올릴 이유가 없다).
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(
                body=b"mp3:warning:EN_US:fixed", generation_id="gen-fix"
            )
        )
        attempts = {"n": 0}

        def transcribe(path):
            attempts["n"] += 1
            return "warning" if attempts["n"] > 1 else "wrong"

        with tempfile.TemporaryDirectory() as tmp:
            (summary, _, _), _ = self.run_pool(
                s3,
                index,
                Path(tmp),
                transcribe=transcribe,
                client=client,
                max_resynth=3,
                publish_fixes=True,
                execute=True,
            )

        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["pendingPublish"], 1)
        self.assertEqual(summary["replaced"], 1)
        self.assertEqual(s3.bodies[entry["targetKey"]], b"mp3:warning:EN_US:fixed")
        self.assertEqual(
            s3.objects[entry["targetKey"]]["Metadata"]["generation-id"], "gen-fix"
        )

    def test_publish_dry_run_leaves_the_pool_object_untouched(self):
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3, index = self.build([entry])
        client = Mock()
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(body=b"fixed", generation_id="gen-fix")
        )
        attempts = {"n": 0}

        def transcribe(path):
            attempts["n"] += 1
            return "warning" if attempts["n"] > 1 else "wrong"

        with tempfile.TemporaryDirectory() as tmp:
            (summary, _, _), _ = self.run_pool(
                s3, index, Path(tmp), transcribe=transcribe, client=client,
                max_resynth=3, publish_fixes=True, execute=False,
            )

        self.assertEqual(summary["pendingPublish"], 1)
        self.assertEqual(summary["replaced"], 0)
        self.assertEqual(s3.bodies[entry["targetKey"]], b"mp3:warning:EN_US")

    def test_unpublished_local_fix_survives_the_next_run_and_gets_published(self):
        # 앞선 실행이 --resynth만 하고 게시하지 않았으면 로컬 mp3가 S3와 다르다.
        # 다시 받아 덮어쓰면 그 작업이 조용히 사라진다.
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3, index = self.build([entry])
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            client = Mock()
            client.synthesize = Mock(
                side_effect=lambda asset: Mock(
                    body=b"mp3:warning:EN_US:fixed", generation_id="gen-fix"
                )
            )
            attempts = {"n": 0}

            def failing_then_fixed(path):
                attempts["n"] += 1
                return "warning" if attempts["n"] > 1 else "wrong"

            (first, _, _), _ = self.run_pool(
                s3, index, work_dir, transcribe=failing_then_fixed,
                client=client, max_resynth=3,
            )
            self.assertEqual(first["pendingPublish"], 1)
            self.assertEqual(first["replaced"], 0)
            self.assertEqual(s3.bodies[entry["targetKey"]], b"mp3:warning:EN_US")

            # 같은 작업 폴더로 다시 돌린다 — 이번에는 게시까지.
            (second, _, _), _ = self.run_pool(
                s3, index, work_dir, transcribe=lambda path: "warning",
                client=None, max_resynth=0, publish_fixes=True, execute=True,
            )

        self.assertEqual(second["carriedOverFixes"], 1)
        self.assertEqual(second["pendingPublish"], 1)
        self.assertEqual(second["replaced"], 1)
        self.assertEqual(s3.bodies[entry["targetKey"]], b"mp3:warning:EN_US:fixed")

    def test_replaced_pool_object_carries_the_qa_marker(self):
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3, index = self.build([entry])
        client = Mock()
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(body=b"fixed-bytes", generation_id="gen-fix")
        )
        attempts = {"n": 0}

        def failing_then_fixed(path):
            attempts["n"] += 1
            return "warning" if attempts["n"] > 1 else "wrong"

        with tempfile.TemporaryDirectory() as tmp:
            self.run_pool(
                s3, index, Path(tmp), transcribe=failing_then_fixed, client=client,
                max_resynth=3, publish_fixes=True, execute=True,
            )

        self.assertEqual(
            s3.objects[entry["targetKey"]]["Metadata"][qa_epa.WORD_POOL_REPLACED_MARKER],
            qa_epa.WORD_POOL_REPLACED_VALUE,
        )

    def test_failed_resynth_is_not_published(self):
        # 재합성을 다 써도 불합격이면 공용 키는 건드리지 않는다. 그 키는 수백 개 표현이
        # 함께 쓰고, 버킷에 버저닝이 없어 되돌릴 수 없다.
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False, duplicates=852)
        s3, index = self.build([entry])
        client = Mock()
        bad = {"n": 0}

        def always_bad(asset):
            bad["n"] += 1
            return Mock(body=f"BAD-{bad['n']}".encode(), generation_id="gen-bad")

        client.synthesize = Mock(side_effect=always_bad)
        with tempfile.TemporaryDirectory() as tmp:
            (summary, _, _), _ = self.run_pool(
                s3, index, Path(tmp), transcribe=lambda path: "zero zero",
                client=client, max_resynth=3, publish_fixes=True, execute=True,
            )

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["withheldFailures"], 1)
        self.assertEqual(summary["pendingPublish"], 0)
        self.assertEqual(summary["replaced"], 0)
        self.assertEqual(s3.bodies[entry["targetKey"]], b"mp3:warning:EN_US")

    def test_stale_local_clip_is_not_adopted_as_a_fix(self):
        # 작업 폴더의 mp3 경로는 generate·check 명령과 형식이 같다. 옛 배치 폴더를
        # 재사용하면 남의 음성이 "미게시 수정본"으로 둔갑해 공용 키에 올라간다.
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3, index = self.build([entry])
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            asset = qa_epa.word_pool_asset(qa_epa.load_word_pool_index(index)[0])
            stale = qa_epa.audio_path_for(work_dir, asset)
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_bytes(b"STALE-FROM-AN-OLD-BATCH")

            with self.assertRaises(ValueError) as caught:
                self.run_pool(s3, index, work_dir, publish_fixes=True, execute=True)

        self.assertIn("this tool has no record of it", str(caught.exception))
        self.assertEqual(s3.bodies[entry["targetKey"]], b"mp3:warning:EN_US")

    def test_object_without_audio_sha_metadata_is_not_treated_as_changed(self):
        # 원격 sha를 모르면 "로컬이 다르다"를 판정할 수 없다. 빈 문자열로 뭉개면
        # 매 실행마다 게시 대상이 되어 pendingPublish가 0이 되는 날이 오지 않는다.
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3 = FakeS3()
        s3.add_audio(entry["targetKey"], b"mp3:warning:EN_US")
        s3.objects[entry["targetKey"]]["Metadata"].pop("audio-sha256")
        index = write_json(pool_index_payload([entry]))
        with tempfile.TemporaryDirectory() as tmp:
            (summary, _, _), _ = self.run_pool(
                s3, index, Path(tmp), publish_fixes=True, execute=True
            )

        self.assertEqual(summary["missingRemoteSha"], 1)
        self.assertEqual(summary["pendingPublish"], 0)
        self.assertEqual(summary["replaced"], 0)

    def test_partial_publish_failure_reports_what_was_replaced(self):
        entries = [
            pool_entry("EN_US", "alpha", 5, 1, qa=False),
            pool_entry("EN_US", "bravo", 5, 2, qa=False),
            pool_entry("EN_US", "delta", 5, 3, qa=False),
        ]
        s3, index = self.build(entries)
        client = Mock()
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(
                body=f"mp3:{asset.text}:EN_US:fixed".encode(), generation_id="gen-fix"
            )
        )
        seen: dict[str, int] = {}

        def failing_then_fixed(path):
            word = path.read_bytes().decode().split(":")[1]
            seen[word] = seen.get(word, 0) + 1
            return word if seen[word] > 1 else "wrong"

        original = s3.__call__
        # 가운데 항목의 put만 실패시킨다.
        bravo_key = entries[1]["targetKey"]

        def break_bravo(command, **kwargs):
            if command[2] == "put-object" and command[command.index("--key") + 1] == bravo_key:
                raise RuntimeError("S3 put-object failed for key " + bravo_key)
            return original(command, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            (summary, _, _), _ = self.run_pool(
                s3, index, Path(tmp), transcribe=failing_then_fixed, client=client,
                max_resynth=3, publish_fixes=True, execute=True, aws_override=break_bravo,
            )

        self.assertIn("publishError", summary)
        self.assertEqual(summary["replaced"], 1)
        self.assertEqual(summary["replacedKeys"], [entries[0]["targetKey"]])
        # 실패 뒤의 항목은 올리지 않는다
        self.assertEqual(s3.bodies[entries[2]["targetKey"]], b"mp3:delta:EN_US")

    def test_second_run_after_a_successful_publish_is_a_noop(self):
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3, index = self.build([entry])
        client = Mock()
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(
                body=b"mp3:warning:EN_US:fixed", generation_id="gen-fix"
            )
        )
        attempts = {"n": 0}

        def failing_then_fixed(path):
            attempts["n"] += 1
            return "warning" if attempts["n"] > 1 else "wrong"

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (first, _, _), _ = self.run_pool(
                s3, index, work_dir, transcribe=failing_then_fixed, client=client,
                max_resynth=3, publish_fixes=True, execute=True,
            )
            self.assertEqual(first["replaced"], 1)

            client.synthesize.reset_mock()
            (second, _, _), _ = self.run_pool(
                s3, index, work_dir, transcribe=lambda path: "warning",
                client=client, max_resynth=3, publish_fixes=True, execute=True,
            )

        self.assertEqual(second["pendingPublish"], 0)
        self.assertEqual(second["carriedOverFixes"], 0)
        self.assertEqual(second["replaced"], 0)
        self.assertEqual(client.synthesize.call_count, 0)

    def test_pool_state_does_not_clobber_the_expression_level_state(self):
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3, index = self.build([entry])
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (work_dir / "state.json").write_text(
                '{"schemaVersion":1,"assets":[]}', encoding="utf-8"
            )
            self.run_pool(s3, index, work_dir)

            self.assertEqual(
                (work_dir / "state.json").read_text(encoding="utf-8"),
                '{"schemaVersion":1,"assets":[]}',
            )
            self.assertTrue((work_dir / "pool-state.json").is_file())

    def test_missing_audio_sha_survives_a_second_run_in_the_same_work_dir(self):
        # 문서는 "먼저 검사, 그다음 게시"를 같은 work-dir에서 두 번 돌리라고 한다.
        # 원격 sha를 모르는 항목을 "다르다"로 몰면 2회차가 통째로 막힌다.
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3 = FakeS3()
        s3.add_audio(entry["targetKey"], b"mp3:warning:EN_US")
        s3.objects[entry["targetKey"]]["Metadata"].pop("audio-sha256")
        index = write_json(pool_index_payload([entry]))
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            (first, _, _), _ = self.run_pool(s3, index, work_dir)
            (second, _, _), _ = self.run_pool(
                s3, index, work_dir, publish_fixes=True, execute=True
            )

        self.assertEqual(first["missingRemoteSha"], 1)
        self.assertEqual(second["missingRemoteSha"], 1)
        self.assertEqual(second["failed"], 0)
        self.assertEqual(second["pendingPublish"], 0)
        self.assertEqual(second["carriedOverFixes"], 0)

    def test_stale_clip_is_rejected_even_when_the_object_has_no_audio_sha(self):
        # "같은 내용인가"(판정 불가)와 "어디서 왔나"(판정 가능)는 별개의 질문이다.
        # 앞엣것을 모른다고 뒤엣것까지 묻지 않으면 남의 파일이 합격으로 보고된다.
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3 = FakeS3()
        s3.add_audio(entry["targetKey"], b"mp3:warning:EN_US:REAL")
        s3.objects[entry["targetKey"]]["Metadata"].pop("audio-sha256")
        index = write_json(pool_index_payload([entry]))
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            asset = qa_epa.word_pool_asset(qa_epa.load_word_pool_index(index)[0])
            stale = qa_epa.audio_path_for(work_dir, asset)
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_bytes(b"STALE-FROM-SOMEONE-ELSES-BATCH")

            with self.assertRaises(ValueError) as caught:
                self.run_pool(s3, index, work_dir)

        self.assertIn("origin is unknown", str(caught.exception))

    def test_downloaded_clip_is_not_mistaken_for_a_local_fix_when_s3_moves_on(self):
        # 공용 풀 객체는 --metadata-directive COPY로 복사돼 원래 배치의 진짜
        # generation-id를 달고 있다. 내려받은 클립에 그 값을 그대로 쓰면 "s3-recovered"
        # 관문이 무력화돼, 다른 사람이 올린 최신 음성 위에 내 옛 사본을 덮어쓰게 된다.
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3, index = self.build([entry])
        s3.objects[entry["targetKey"]]["Metadata"]["generation-id"] = "gen-from-batch-4"
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            self.run_pool(s3, index, work_dir)

            # 다른 사람이 같은 키에 고친 음성을 올렸다고 하자.
            s3.add_audio(entry["targetKey"], b"mp3:warning:EN_US:SOMEONE-ELSES-FIX")
            s3.objects[entry["targetKey"]]["Metadata"]["generation-id"] = "gen-theirs"

            with self.assertRaises(ValueError) as caught:
                self.run_pool(
                    s3, index, work_dir, publish_fixes=True, execute=True
                )

        self.assertIn("downloaded from S3 but no longer matches", str(caught.exception))
        self.assertEqual(
            s3.bodies[entry["targetKey"]], b"mp3:warning:EN_US:SOMEONE-ELSES-FIX"
        )

    def test_publish_that_writes_then_fails_verification_lists_the_key(self):
        # put은 성공하고 게시 결과 검증만 어긋난 경우, 객체는 이미 바뀌어 있다.
        # 교체 목록에서 빠지면 CloudFront 무효화 대상에서도 빠져 옛 소리가 계속 나간다.
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3, index = self.build([entry])
        client = Mock()
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(
                body=b"mp3:warning:EN_US:fixed", generation_id="gen-fix"
            )
        )
        attempts = {"n": 0}

        def failing_then_fixed(path):
            attempts["n"] += 1
            return "warning" if attempts["n"] > 1 else "wrong"

        original = s3.__call__

        def corrupt_after_put(command, **kwargs):
            result = original(command, **kwargs)
            if command[2] == "put-object":
                key = command[command.index("--key") + 1]
                s3.objects[key]["Metadata"]["audio-sha256"] = "drifted"
            return result

        with tempfile.TemporaryDirectory() as tmp:
            (summary, _, _), _ = self.run_pool(
                s3, index, Path(tmp), transcribe=failing_then_fixed, client=client,
                max_resynth=3, publish_fixes=True, execute=True,
                aws_override=corrupt_after_put,
            )

        self.assertIn("publishError", summary)
        self.assertEqual(summary["unverifiedKey"], entry["targetKey"])
        # 실제로 바뀌었으므로 무효화 목록에 들어 있어야 한다
        self.assertIn(entry["targetKey"], summary["replacedKeys"])
        self.assertEqual(s3.bodies[entry["targetKey"]], b"mp3:warning:EN_US:fixed")

    def test_alternating_indexes_in_one_work_dir_names_the_real_cause(self):
        # 같은 (표현id, 순서)에 해시가 둘인 경우가 실제로 있다(표현 1942·1945·1946).
        # 한 폴더에서 두 색인을 번갈아 돌리면 기록이 서로의 것이 된다.
        first_entry = pool_entry("EN_US", "alpha", 5, 1, qa=False)
        second_entry = pool_entry("EN_US", "bravo", 5, 1, qa=False)
        s3, first_index = self.build([first_entry])
        s3.add_audio(second_entry["targetKey"], b"mp3:bravo:EN_US")
        second_index = write_json(pool_index_payload([second_entry]))
        client = Mock()
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(body=b"fixed-alpha", generation_id="gen-fix")
        )
        attempts = {"n": 0}

        def failing_then_fixed(path):
            attempts["n"] += 1
            return "alpha" if attempts["n"] > 1 else "wrong"

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            self.run_pool(
                s3, first_index, work_dir, transcribe=failing_then_fixed,
                client=client, max_resynth=3,
            )
            # alpha의 수정본이 남은 폴더에서 bravo 색인을 돌린다. 경로에 해시가 들어가
            # 파일은 갈리지만, 기록은 같은 자산 id를 공유한다.
            alpha_path = qa_epa.audio_path_for(
                work_dir, qa_epa.word_pool_asset(qa_epa.load_word_pool_index(second_index)[0])
            )
            alpha_path.write_bytes(b"not-bravo")

            with self.assertRaises(ValueError) as caught:
                self.run_pool(s3, second_index, work_dir)

        self.assertIn("different pool entry", str(caught.exception))

    def test_mp3_newer_than_the_record_says_it_may_be_an_interrupted_resynth(self):
        # 재합성 파일이 디스크에 쓰인 뒤 state 반영 전에 죽으면 생기는 창.
        # "남의 배치"로 몰면 운영자가 할 일을 잘못 고른다 — 이건 지워도 안전하다.
        entry = pool_entry("EN_US", "warning", 5, 1, qa=False)
        s3, index = self.build([entry])
        client = Mock()
        client.synthesize = Mock(
            side_effect=lambda asset: Mock(body=b"first-fix", generation_id="gen-fix")
        )
        attempts = {"n": 0}

        def failing_then_fixed(path):
            attempts["n"] += 1
            return "warning" if attempts["n"] > 1 else "wrong"

        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            self.run_pool(
                s3, index, work_dir, transcribe=failing_then_fixed,
                client=client, max_resynth=3,
            )
            asset = qa_epa.word_pool_asset(qa_epa.load_word_pool_index(index)[0])
            qa_epa.audio_path_for(work_dir, asset).write_bytes(b"even-newer")

            with self.assertRaises(ValueError) as caught:
                self.run_pool(s3, index, work_dir)

        message = str(caught.exception)
        self.assertIn("newer than this tool's record", message)
        self.assertIn("지워도 안전하다", message)

    def test_failure_lines_say_how_many_expressions_use_the_word(self):
        entry = pool_entry("EN_US", "the", 982, 7, qa=False, duplicates=852)
        s3, index = self.build([entry])
        with tempfile.TemporaryDirectory() as tmp:
            (summary, outcomes, by_id), _ = self.run_pool(
                s3, index, Path(tmp), transcribe=lambda path: "zero zero"
            )
            lines = format_pool_failures(outcomes, by_id)

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(len(lines), 1)
        self.assertIn("used_by=852", lines[0])
        self.assertIn(qa_epa.shared_word_key("EN_US", entry["fingerprint"]), lines[0])


if __name__ == "__main__":
    unittest.main()
