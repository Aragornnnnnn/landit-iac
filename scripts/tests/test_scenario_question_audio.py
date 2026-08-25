# LAN-351 고정 질문 오디오 배치 도구의 계약을 검증한다.

import unittest
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile

from scripts.scenario_question_audio import (
    SourceAsset,
    SourceSnapshot,
    generation_fingerprint,
    load_source,
    main,
    select_sample_ids,
    validate_source,
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


if __name__ == "__main__":
    unittest.main()
