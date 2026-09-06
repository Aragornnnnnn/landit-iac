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
from scripts.expression_pronunciation_qa import (
    SILENCE_RMS_DBFS,
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
