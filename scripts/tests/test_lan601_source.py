# LAN-601 시나리오 41~70 질문·표현 추출과 질문 오디오 배치 계약을 검증한다.

import unittest
from dataclasses import replace

from scripts.lan601_extract_source import (
    extract_expressions,
    extract_questions,
    insert_values,
)
from scripts.scenario_question_audio import (
    SourceAsset,
    SourceSnapshot,
    build_manifest,
    validate_source,
)
from scripts.tests.test_scenario_question_audio import make_generated_assets


LEVEL_GROUPS = ("LEVEL_1", "LEVEL_2_TO_3", "LEVEL_4_TO_5")

QUESTION_SQL = """
-- scenario : 시나리오 (2행). 주석 안의 (괄호)는 무시한다.
INSERT INTO scenario
  (category_id, ai_role, character_id, difficulty, first_speaker, thumbnail_url,
   display_order, status, created_at, updated_at, total_question_count)
VALUES
  -- 기획서 시나리오 41 (Day 44)
  (3, '테니스 동아리 부원 (활발함)', 'chloe', 'EASY', 'AI', NULL, 44, 'ACTIVE', now(), now(), 3),
  (2, 'friend''s roommate', 'teddy', 'EASY', 'USER', NULL, 41, 'ACTIVE', now(), now(), 3);

INSERT INTO scenario_language_variant (scenario_id, title) VALUES
  ((SELECT id FROM scenario WHERE display_order = 44), 'ignored');

INSERT INTO scenario_question
  (scenario_id, display_order, question_level_group, response_demand, status, created_at, updated_at)
VALUES
  ((SELECT id FROM scenario WHERE display_order = 44), 2, 'LEVEL_1', 'LOW', 'ACTIVE', now(), now()),
  ((SELECT id FROM scenario WHERE display_order = 41), 1, 'LEVEL_4_TO_5', 'HIGH', 'ACTIVE', now(), now()),
  ((SELECT id FROM scenario WHERE display_order = 44), 1, 'LEVEL_1', 'LOW', 'ACTIVE', now(), now());

INSERT INTO scenario_question_language_variant
  (scenario_question_id, target_locale, base_locale, question_text, question_translation,
   required_response_element, audio_url, status, created_at, updated_at, inner_thought, inner_thought_type)
VALUES
  ((SELECT sq.id FROM scenario_question sq JOIN scenario s ON s.id = sq.scenario_id
    WHERE s.display_order = 44 AND sq.question_level_group = 'LEVEL_1' AND sq.display_order = 1),
   'EN', 'KR', 'Hi! What''s up; any (plans)?', '안녕', 'Say hi.', NULL, 'ACTIVE', now(), now(), NULL, NULL),
  ((SELECT sq.id FROM scenario_question sq JOIN scenario s ON s.id = sq.scenario_id
    WHERE s.display_order = 41 AND sq.question_level_group = 'LEVEL_4_TO_5' AND sq.display_order = 1),
   'EN', 'KR', 'Which route -- lake or hill?', '어느 길?', 'Pick one.', NULL, 'ACTIVE', now(), now(), NULL, NULL),
  ((SELECT sq.id FROM scenario_question sq JOIN scenario s ON s.id = sq.scenario_id
    WHERE s.display_order = 44 AND sq.question_level_group = 'LEVEL_1' AND sq.display_order = 2),
   'EN', 'KR', 'Do you want to come?', '올래?', 'Answer.', NULL, 'ACTIVE', now(), now(), NULL, NULL);
"""

EXPRESSION_SQL = """
INSERT INTO writing_expression
  (scenario_id, expression_type, usage_frequency_level, target_locale, base_locale,
   display_order, target_expression_text, base_expression_meaning_text,
   usage_summary, usage_description, representative_question_text, representative_question_translation,
   representative_sentence_text, representative_sentence_translation,
   representative_sentence_words, representative_sentence_word_choices, representative_image_url,
   practice_examples_payload, expression_source, status, difficulty_level, created_at, updated_at)
VALUES
  ((SELECT id FROM scenario WHERE display_order = 44), 'DAILY_ROUTINE', 'BASIC', 'EN', 'KR',
   1, 'I play ~', '나는 ~을 해', 'summary', '''I play ~''는 (운동) 표현', 'Q?', '질문',
   'I play tennis after school.', '번역',
   ARRAY['I', 'play']::varchar[], ARRAY['play', 'I']::varchar[], NULL,
   '[{"sentenceText": "We''ll play.", "imageUrl": null}]'::jsonb,
   'SCENARIO', 'ACTIVE', 1, now(), now()),
  ((SELECT id FROM scenario WHERE display_order = 41), 'CONVERSATION_SKILL', 'BASIC', 'EN', 'KR',
   2, 'make it to the top', '정상까지 가다', 'summary', 'desc', 'Q?', '질문',
   'I''ll make it to the top.', '번역',
   ARRAY['I''ll']::varchar[], ARRAY['I''ll']::varchar[], NULL,
   '[]'::jsonb, 'SCENARIO', 'ACTIVE', 4, now(), now());
"""


def make_lan601_snapshot() -> SourceSnapshot:
    assets = []
    question_id = 361
    scenario_id = 41
    for character_id, scenario_count in (("chloe", 7), ("marco", 7), ("teddy", 16)):
        for _ in range(scenario_count):
            for question_level_group in LEVEL_GROUPS:
                for order in (1, 2, 3):
                    assets.append(
                        SourceAsset(
                            scenario_id=scenario_id,
                            scenario_question_id=question_id,
                            display_order=order,
                            character_id=character_id,
                            question_text=f"Question {question_id}?",
                            question_level_group=question_level_group,
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
        issue="LAN-601",
    )


class Lan601ContractTests(unittest.TestCase):
    def test_validate_source_accepts_three_level_groups(self) -> None:
        snapshot = make_lan601_snapshot()

        validate_source(snapshot)

        self.assertEqual(270, len(snapshot.assets))

    def test_validate_source_rejects_missing_level_4_to_5(self) -> None:
        snapshot = make_lan601_snapshot()
        changed = replace(snapshot.assets[-1], question_level_group="LEVEL_2_TO_3")
        invalid = replace(snapshot, assets=snapshot.assets[:-1] + (changed,))

        with self.assertRaises(ValueError):
            validate_source(invalid)

    def test_manifest_keeps_all_three_level_groups(self) -> None:
        snapshot = make_lan601_snapshot()

        manifest = build_manifest(snapshot, make_generated_assets(snapshot))

        self.assertEqual("LAN-601", manifest["issue"])
        self.assertEqual(270, manifest["source"]["questionCount"])
        self.assertEqual(
            set(LEVEL_GROUPS),
            {asset["questionLevelGroup"] for asset in manifest["assets"]},
        )


class Lan601ExtractTests(unittest.TestCase):
    def test_insert_values_ignores_comments_and_quoted_delimiters(self) -> None:
        rows = insert_values(QUESTION_SQL, "scenario_question_language_variant")

        self.assertEqual(3, len(rows))
        self.assertEqual("'Hi! What''s up; any (plans)?'", rows[0][3])
        self.assertEqual("'Which route -- lake or hill?'", rows[1][3])

    def test_questions_are_numbered_in_scenario_question_row_order(self) -> None:
        questions = extract_questions(QUESTION_SQL, start_id=361)

        self.assertEqual([361, 362, 363], [q.scenario_question_id for q in questions])
        self.assertEqual(
            [(44, "LEVEL_1", 2), (41, "LEVEL_4_TO_5", 1), (44, "LEVEL_1", 1)],
            [(q.day, q.question_level_group, q.display_order) for q in questions],
        )
        self.assertEqual("Do you want to come?", questions[0].question_text)
        self.assertEqual("Hi! What's up; any (plans)?", questions[2].question_text)

    def test_question_character_and_scenario_id_follow_scenario_rows(self) -> None:
        questions = extract_questions(QUESTION_SQL, start_id=1)

        self.assertEqual(("teddy", 42), (questions[1].character_id, questions[1].scenario_id))
        self.assertEqual(("chloe", 41), (questions[0].character_id, questions[0].scenario_id))

    def test_missing_question_variant_is_rejected(self) -> None:
        broken = QUESTION_SQL.replace("sq.display_order = 2", "sq.display_order = 3")

        with self.assertRaisesRegex(ValueError, "do not match"):
            extract_questions(broken, start_id=1)

    def test_expressions_are_numbered_in_row_order_with_unescaped_text(self) -> None:
        expressions = extract_expressions(EXPRESSION_SQL, start_id=4001)

        self.assertEqual(
            [(4001, 44, 1, "I play ~", "I play tennis after school."),
             (4002, 41, 2, "make it to the top", "I'll make it to the top.")],
            [
                (e.expression_id, e.day, e.display_order, e.expression_text, e.sentence_text)
                for e in expressions
            ],
        )


if __name__ == "__main__":
    unittest.main()
