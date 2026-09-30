# 게시된 발음 기준 데이터와 BE 매니페스트로 expression_pronunciation_asset Flyway SQL을 만든다.
#
# 어드민 임포트 API(기준 데이터 upsert → TTS URL 조인)가 남기는 행과 같은 모양을 만든다:
# words = 기준 데이터 words에 BE 매니페스트의 단어별 audioUrl을 order로 붙인 배열.
# 적재 전에 writing_expression의 표현·대표 문장이 음성을 만든 원문과 같은지 대조하고, 다르면
# 마이그레이션을 멈춘다 (임포트 API의 "문장이 DB와 다릅니다" 검증을 옮긴 것, V95와 같은 방식).
#
# 사용법:
#   python3 scripts/build_pronunciation_asset_sql.py --issue LAN-601 \
#       --be-manifest work/be-manifest.json --reference-dir work/reference-uploaded \
#       --expressions work/expressions.json --header work/header.sql --out V137__....sql
from __future__ import annotations

import argparse
import json
from pathlib import Path

ACCENT_LOCALES = ("EN_US", "EN_GB", "EN_AU")


def sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def load_reference(reference_dir: Path) -> dict[tuple[int, str], dict]:
    entries = {}
    for locale in ACCENT_LOCALES:
        for entry in json.loads((reference_dir / f"{locale}.json").read_text(encoding="utf-8")):
            entries[(entry["expressionId"], entry["accentLocale"])] = entry
    return entries


def joined_words(reference_words: list[dict], manifest_words: list[dict]) -> list[dict]:
    """기준 데이터 words에 단어별 audioUrl을 order로 붙인다. order 집합이 다르면 멈춘다."""
    audio_by_order = {word["order"]: word["audioUrl"] for word in manifest_words}
    if set(audio_by_order) != {word["order"] for word in reference_words}:
        raise ValueError("reference words and manifest words have different orders")
    return [{**word, "audioUrl": audio_by_order[word["order"]]} for word in reference_words]


def asset_rows(be_manifest: dict, references: dict[tuple[int, str], dict]) -> list[str]:
    rows = []
    for asset in sorted(
        be_manifest["assets"],
        key=lambda item: (item["expressionId"], ACCENT_LOCALES.index(item["accentLocale"])),
    ):
        key = (asset["expressionId"], asset["accentLocale"])
        words = joined_words(references[key]["words"], asset["words"])
        words_json = json.dumps(words, ensure_ascii=False, separators=(",", ":"))
        rows.append(
            f"({asset['expressionId']},{sql_literal(asset['accentLocale'])},"
            f"{sql_literal(asset['expressionAudioUrl'])},{sql_literal(asset['sentenceAudioUrl'])},"
            f"{sql_literal(words_json)}::jsonb,now(),now())"
        )
    return rows


def text_guard(issue: str, expressions: list[dict]) -> str:
    values = ",\n".join(
        f"        ({e['expressionId']}, {sql_literal(e['expressionText'])}, "
        f"{sql_literal(e['sentenceText'])})"
        for e in expressions
    )
    return f"""DO $$
DECLARE
    mismatched integer;
    first_mismatch bigint;
BEGIN
    SELECT count(*), min(expected.id)
    INTO mismatched, first_mismatch
    FROM (VALUES
{values}
    ) AS expected(id, expression_text, sentence_text)
    LEFT JOIN writing_expression we ON we.id = expected.id
    WHERE we.id IS NULL
       OR we.target_expression_text IS DISTINCT FROM expected.expression_text
       OR we.representative_sentence_text IS DISTINCT FROM expected.sentence_text;

    IF mismatched > 0 THEN
        RAISE EXCEPTION '{issue} pronunciation assets: % writing_expression rows are missing or differ from the texts the audio was generated from (first id %).',
            mismatched, first_mismatch;
    END IF;
END
$$;"""


def count_guard(issue: str, first_id: int, last_id: int, expression_count: int, templated: int) -> str:
    total = expression_count * len(ACCENT_LOCALES)
    return f"""DO $$
BEGIN
    IF (SELECT count(*) FROM expression_pronunciation_asset
        WHERE writing_expression_id BETWEEN {first_id} AND {last_id}) <> {total} THEN
        RAISE EXCEPTION '{issue} pronunciation assets: expected {total} rows for {first_id}~{last_id}';
    END IF;

    IF EXISTS (
        SELECT 1 FROM expression_pronunciation_asset
        WHERE writing_expression_id BETWEEN {first_id} AND {last_id}
        GROUP BY accent_locale
        HAVING count(*) <> {expression_count}
    ) OR (SELECT count(DISTINCT accent_locale) FROM expression_pronunciation_asset
          WHERE writing_expression_id BETWEEN {first_id} AND {last_id}) <> {len(ACCENT_LOCALES)} THEN
        RAISE EXCEPTION '{issue} pronunciation assets: every accent locale must have {expression_count} rows';
    END IF;

    IF EXISTS (
        SELECT 1 FROM expression_pronunciation_asset
        WHERE writing_expression_id BETWEEN {first_id} AND {last_id}
          AND sentence_audio_url IS NULL
    ) THEN
        RAISE EXCEPTION '{issue} pronunciation assets: sentence audio URL is missing';
    END IF;

    IF (SELECT count(*) FROM expression_pronunciation_asset
        WHERE writing_expression_id BETWEEN {first_id} AND {last_id}
          AND expression_audio_url IS NULL) <> {templated} THEN
        RAISE EXCEPTION '{issue} pronunciation assets: expected {templated} templated expressions without expression audio';
    END IF;
END
$$;"""


def build_sql(issue: str, header: str, be_manifest: dict, references: dict, expressions: list[dict]) -> str:
    ids = [e["expressionId"] for e in expressions]
    if {a["expressionId"] for a in be_manifest["assets"]} != set(ids):
        raise ValueError("BE manifest expressions differ from the expression list")
    templated = sum(1 for a in be_manifest["assets"] if a["expressionAudioUrl"] is None)
    rows = ",\n".join(asset_rows(be_manifest, references))
    return "\n\n".join(
        [
            header.rstrip(),
            text_guard(issue, expressions),
            "INSERT INTO expression_pronunciation_asset (writing_expression_id, accent_locale, "
            "expression_audio_url, sentence_audio_url, words, created_at, updated_at) VALUES\n"
            + rows
            + "\nON CONFLICT (writing_expression_id, accent_locale) DO UPDATE SET\n"
            "    expression_audio_url = EXCLUDED.expression_audio_url,\n"
            "    sentence_audio_url = EXCLUDED.sentence_audio_url,\n"
            "    words = EXCLUDED.words,\n"
            "    updated_at = now();",
            count_guard(issue, min(ids), max(ids), len(ids), templated),
        ]
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="발음 자산 Flyway SQL 생성")
    parser.add_argument("--issue", required=True)
    parser.add_argument("--be-manifest", required=True, type=Path)
    parser.add_argument("--reference-dir", required=True, type=Path, help="{EN_US,EN_GB,EN_AU}.json (게시본)")
    parser.add_argument("--expressions", required=True, type=Path, help="[{expressionId, expressionText, sentenceText}]")
    parser.add_argument("--header", required=True, type=Path, help="SQL 머리 주석 파일")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    expressions = json.loads(args.expressions.read_text(encoding="utf-8"))
    sql = build_sql(
        args.issue,
        args.header.read_text(encoding="utf-8"),
        json.loads(args.be_manifest.read_text(encoding="utf-8")),
        load_reference(args.reference_dir),
        expressions,
    )
    args.out.write_text(sql, encoding="utf-8")
    print(f"expressions={len(expressions)} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
