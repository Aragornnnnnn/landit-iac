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
# 시나리오 참조는 두 형식을 받는다: display_order 서브쿼리(초기본) 또는 고정 id 리터럴(최신본).
SCENARIO_REFERENCE = re.compile(r"(display_order|id)\s*=\s*(\d+)")
VARIANT_KEY = re.compile(
    r"s\.(display_order|id)\s*=\s*(\d+)\s+AND\s+sq\.question_level_group\s*=\s*'(\w+)'"
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


def insert_columns(sql: str, table: str) -> list[str]:
    """`INSERT INTO {table} (컬럼, ...)`의 컬럼 이름 목록을 돌려준다."""
    match = re.search(rf"INSERT INTO {table}\s*\(([^)]*)\)", sql)
    if match is None:
        raise ValueError(f"INSERT INTO {table} columns not found")
    return [name.strip() for name in match.group(1).split(",")]


def scenario_day(field: str, day_by_scenario_id: dict[int, int] | None = None) -> int:
    """시나리오 참조 필드에서 Day(display_order)를 얻는다. 고정 id면 id→Day로 바꾼다."""
    if field.isdigit():
        if day_by_scenario_id is None:
            raise ValueError(f"scenario id literal needs an id→day map: {field}")
        return day_by_scenario_id[int(field)]
    match = SCENARIO_REFERENCE.search(field)
    if match is None:
        raise ValueError(f"scenario reference not found: {field[:80]}")
    if match.group(1) == "id":
        if day_by_scenario_id is None:
            raise ValueError(f"scenario id reference needs an id→day map: {field[:80]}")
        return day_by_scenario_id[int(match.group(2))]
    return int(match.group(2))


def scenario_ids_and_days(sql: str) -> tuple[dict[int, int], dict[int, str], dict[int, int]]:
    """(Day→scenario id, Day→캐릭터, scenario id→Day). id 컬럼이 없으면 행 순서로 41부터 부여한다."""
    columns = insert_columns(sql, "scenario")
    rows = insert_values(sql, "scenario")
    day_index = columns.index("display_order")
    character_index = columns.index("character_id")
    scenario_id_by_day: dict[int, int] = {}
    character_by_day: dict[int, str] = {}
    for index, row in enumerate(rows):
        day = int(row[day_index])
        scenario_id_by_day[day] = (
            int(row[columns.index("id")]) if "id" in columns else FIRST_SCENARIO_ID + index
        )
        character_by_day[day] = sql_string(row[character_index])
    day_by_scenario_id = {scenario_id: day for day, scenario_id in scenario_id_by_day.items()}
    return scenario_id_by_day, character_by_day, day_by_scenario_id


def extract_questions(sql: str, start_id: int) -> list[QuestionRow]:
    scenario_id_by_day, character_by_day, day_by_scenario_id = scenario_ids_and_days(sql)

    columns = insert_columns(sql, "scenario_question")
    question_rows = insert_values(sql, "scenario_question")
    question_keys = [
        (
            scenario_day(row[columns.index("scenario_id")], day_by_scenario_id),
            sql_string(row[columns.index("question_level_group")]),
            int(row[columns.index("display_order")]),
        )
        for row in question_rows
    ]
    ensure_explicit_ids_follow_row_order(columns, question_rows, start_id, "scenario_question")
    variant_columns = insert_columns(sql, "scenario_question_language_variant")
    text_index = variant_columns.index("question_text")
    text_by_key: dict[tuple[int, str, int], str] = {}
    for row in insert_values(sql, "scenario_question_language_variant"):
        match = VARIANT_KEY.search(row[0])
        if match is None:
            raise ValueError(f"variant key not found: {row[0][:80]}")
        reference = int(match.group(2))
        day = day_by_scenario_id[reference] if match.group(1) == "id" else reference
        key = (day, match.group(3), int(match.group(4)))
        if key in text_by_key:
            raise ValueError(f"duplicate question variant: {key}")
        text_by_key[key] = sql_string(row[text_index])

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


def ensure_explicit_ids_follow_row_order(
    columns: list[str], rows: list[list[str]], start_id: int, table: str
) -> None:
    """id를 명시한 SQL이면 그 값이 채번 규칙(시작 번호 + 행 순서)과 같아야 한다."""
    if "id" not in columns:
        return
    explicit_ids = [int(row[columns.index("id")]) for row in rows]
    if explicit_ids != list(range(start_id, start_id + len(rows))):
        raise ValueError(f"{table} explicit ids do not follow row order from {start_id}")


def extract_expressions(
    sql: str, start_id: int, day_by_scenario_id: dict[int, int] | None = None
) -> list[ExpressionRow]:
    columns = insert_columns(sql, "writing_expression")
    rows = insert_values(sql, "writing_expression")
    ensure_explicit_ids_follow_row_order(columns, rows, start_id, "writing_expression")

    def field(row: list[str], name: str) -> str:
        return row[columns.index(name)]

    return [
        ExpressionRow(
            expression_id=start_id + index,
            day=scenario_day(field(row, "scenario_id"), day_by_scenario_id),
            display_order=int(field(row, "display_order")),
            expression_text=sql_string(field(row, "target_expression_text")),
            sentence_text=sql_string(field(row, "representative_sentence_text")),
        )
        for index, row in enumerate(rows)
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

    question_sql = args.question_sql.read_text(encoding="utf-8")
    questions = extract_questions(question_sql, args.question_start_id)
    _, _, day_by_scenario_id = scenario_ids_and_days(question_sql)
    expressions = extract_expressions(
        args.expression_sql.read_text(encoding="utf-8"),
        args.expression_start_id,
        day_by_scenario_id,
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
