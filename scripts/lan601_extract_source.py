# LAN-601 시나리오 41~70 SQL에서 질문·표현 id 매핑과 TTS 소스를 추출한다.
#
# 입력은 LAN-391이 조립한 landit-be migration 두 개다 (질문 SQL, 표현 SQL).
# id는 SQL이 시퀀스에 맡기므로, 여기서 파일 행 순서대로 시작 번호부터 연속 부여한다.
# 이후 LAN-391은 두 파일의 행 순서를 바꾸지 않는다 (inputs.sha256으로 확인).
#
# 사용법:
#   python3 scripts/lan601_extract_source.py \
#       --question-sql .../V135__insert_scenario_41_70.sql \
#       --expression-sql .../V136__insert_scenario_41_70_writing_expressions.sql \
#       --question-start-id 361 --expression-start-id 4001 --out-dir work/lan-601
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


QUESTION_COUNT = 270
EXPRESSION_COUNT = 328
SCENARIO_COUNT = 30
FIRST_SCENARIO_ID = 41
LEVEL_GROUPS = ("LEVEL_1", "LEVEL_2_TO_3", "LEVEL_4_TO_5")
SCENARIO_DAY = re.compile(r"display_order\s*=\s*(\d+)")
VARIANT_KEY = re.compile(
    r"s\.display_order\s*=\s*(\d+)\s+AND\s+sq\.question_level_group\s*=\s*'(\w+)'"
    r"\s+AND\s+sq\.display_order\s*=\s*(\d+)"
)


@dataclass(frozen=True)
class QuestionRow:
    scenario_question_id: int
    scenario_id: int
    day: int
    question_level_group: str
    display_order: int
    character_id: str
    question_text: str


@dataclass(frozen=True)
class ExpressionRow:
    expression_id: int
    day: int
    display_order: int
    expression_text: str
    sentence_text: str


def _skip_line_comment(sql: str, index: int) -> int:
    end = sql.find("\n", index)
    return len(sql) if end == -1 else end


def insert_values(sql: str, table: str) -> list[list[str]]:
    """`INSERT INTO {table} (...) VALUES` 뒤의 튜플을 필드 문자열 목록으로 나눈다."""
    header = re.search(rf"INSERT INTO {table}\s*\(", sql)
    if header is None:
        raise ValueError(f"INSERT INTO {table} not found")
    values_at = re.compile(r"\bVALUES\b").search(sql, header.end())
    if values_at is None:
        raise ValueError(f"VALUES for {table} not found")

    rows: list[list[str]] = []
    fields: list[str] = []
    current: list[str] = []
    depth = 0
    index = values_at.end()
    while index < len(sql):
        char = sql[index]
        if char == "'":
            end = index + 1
            while True:
                end = sql.index("'", end)
                if sql.startswith("''", end):
                    end += 2
                    continue
                break
            current.append(sql[index : end + 1])
            index = end + 1
            continue
        if char == "-" and sql.startswith("--", index):
            index = _skip_line_comment(sql, index)
            continue
        if char in "([":
            depth += 1
            if depth == 1:
                fields, current = [], []
                index += 1
                continue
        elif char in ")]":
            depth -= 1
            if depth == 0:
                fields.append("".join(current).strip())
                rows.append(fields)
                index += 1
                continue
        elif char == "," and depth == 1:
            fields.append("".join(current).strip())
            current = []
            index += 1
            continue
        elif char == ";" and depth == 0:
            return rows
        if depth >= 1:
            current.append(char)
        index += 1
    raise ValueError(f"INSERT INTO {table} is not terminated")


def sql_string(field: str) -> str:
    if not (field.startswith("'") and field.endswith("'")):
        raise ValueError(f"expected a SQL string literal: {field[:60]}")
    return field[1:-1].replace("''", "'")


def scenario_day(field: str) -> int:
    match = SCENARIO_DAY.search(field)
    if match is None:
        raise ValueError(f"scenario display_order not found: {field[:80]}")
    return int(match.group(1))


def extract_questions(sql: str, start_id: int) -> list[QuestionRow]:
    scenario_rows = insert_values(sql, "scenario")
    # scenario 컬럼: category_id, ai_role, character_id, ..., display_order(6)
    character_by_day = {int(row[6]): sql_string(row[2]) for row in scenario_rows}
    scenario_id_by_day = {
        int(row[6]): FIRST_SCENARIO_ID + index for index, row in enumerate(scenario_rows)
    }

    # scenario_question 컬럼: scenario_id, display_order, question_level_group, ...
    question_keys = [
        (scenario_day(row[0]), sql_string(row[2]), int(row[1]))
        for row in insert_values(sql, "scenario_question")
    ]
    # scenario_question_language_variant 컬럼: scenario_question_id, target, base, question_text, ...
    text_by_key: dict[tuple[int, str, int], str] = {}
    for row in insert_values(sql, "scenario_question_language_variant"):
        match = VARIANT_KEY.search(row[0])
        if match is None:
            raise ValueError(f"variant key not found: {row[0][:80]}")
        key = (int(match.group(1)), match.group(2), int(match.group(3)))
        if key in text_by_key:
            raise ValueError(f"duplicate question variant: {key}")
        text_by_key[key] = sql_string(row[3])

    if len(set(question_keys)) != len(question_keys):
        raise ValueError("scenario_question contains a duplicate (day, level, order)")
    if set(question_keys) != set(text_by_key):
        raise ValueError("scenario_question and its language variants do not match")

    return [
        QuestionRow(
            scenario_question_id=start_id + index,
            scenario_id=scenario_id_by_day[day],
            day=day,
            question_level_group=level,
            display_order=order,
            character_id=character_by_day[day],
            question_text=text_by_key[(day, level, order)],
        )
        for index, (day, level, order) in enumerate(question_keys)
    ]


def extract_expressions(sql: str, start_id: int) -> list[ExpressionRow]:
    # writing_expression 컬럼: scenario_id(0), ..., display_order(5), target_expression_text(6),
    # ..., representative_sentence_text(12)
    return [
        ExpressionRow(
            expression_id=start_id + index,
            day=scenario_day(row[0]),
            display_order=int(row[5]),
            expression_text=sql_string(row[6]),
            sentence_text=sql_string(row[12]),
        )
        for index, row in enumerate(insert_values(sql, "writing_expression"))
    ]


def validate(questions: list[QuestionRow], expressions: list[ExpressionRow]) -> None:
    if len(questions) != QUESTION_COUNT:
        raise ValueError(f"expected {QUESTION_COUNT} questions, got {len(questions)}")
    if len(expressions) != EXPRESSION_COUNT:
        raise ValueError(f"expected {EXPRESSION_COUNT} expressions, got {len(expressions)}")
    if len({q.scenario_id for q in questions}) != SCENARIO_COUNT:
        raise ValueError(f"expected {SCENARIO_COUNT} scenarios")
    if any(q.question_level_group not in LEVEL_GROUPS for q in questions):
        raise ValueError("unsupported question level group")
    if len({(e.day, e.display_order) for e in expressions}) != EXPRESSION_COUNT:
        raise ValueError("writing_expression contains a duplicate (day, display_order)")
    if any(not q.question_text.strip() for q in questions) or any(
        not e.sentence_text.strip() for e in expressions
    ):
        raise ValueError("blank speech text")


def question_source(questions: list[QuestionRow]) -> dict:
    return {
        "schemaVersion": 1,
        "environment": "production",
        "issue": "LAN-601",
        "targetLocale": "EN",
        "baseLocale": "KR",
        "assets": [
            {
                "scenarioId": q.scenario_id,
                "scenarioQuestionId": q.scenario_question_id,
                "displayOrder": q.display_order,
                "questionLevelGroup": q.question_level_group,
                "characterId": q.character_id,
                "questionText": q.question_text,
            }
            for q in questions
        ],
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="LAN-601 id 매핑·TTS 소스 추출")
    parser.add_argument("--question-sql", required=True, type=Path)
    parser.add_argument("--expression-sql", required=True, type=Path)
    parser.add_argument("--question-start-id", required=True, type=int)
    parser.add_argument("--expression-start-id", required=True, type=int)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    questions = extract_questions(
        args.question_sql.read_text(encoding="utf-8"), args.question_start_id
    )
    expressions = extract_expressions(
        args.expression_sql.read_text(encoding="utf-8"), args.expression_start_id
    )
    validate(questions, expressions)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "question-source.json", question_source(questions))
    write_json(
        args.out_dir / "expressions.json",
        [
            {
                "expressionId": e.expression_id,
                "day": e.day,
                "displayOrder": e.display_order,
                "expressionText": e.expression_text,
                "sentenceText": e.sentence_text,
            }
            for e in expressions
        ],
    )
    write_json(
        args.out_dir / "inputs.json",
        {
            "questionSql": {"name": args.question_sql.name, "sha256": file_sha256(args.question_sql)},
            "expressionSql": {
                "name": args.expression_sql.name,
                "sha256": file_sha256(args.expression_sql),
            },
            "questionIdRange": [questions[0].scenario_question_id, questions[-1].scenario_question_id],
            "expressionIdRange": [expressions[0].expression_id, expressions[-1].expression_id],
        },
    )
    characters = Counter(q.character_id for q in questions)
    print(
        f"questions={len(questions)} "
        f"ids={questions[0].scenario_question_id}..{questions[-1].scenario_question_id} "
        f"characters={dict(sorted(characters.items()))}"
    )
    print(
        f"expressions={len(expressions)} "
        f"ids={expressions[0].expression_id}..{expressions[-1].expression_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
