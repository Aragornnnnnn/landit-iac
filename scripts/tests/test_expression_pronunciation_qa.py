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


if __name__ == "__main__":
    unittest.main()
