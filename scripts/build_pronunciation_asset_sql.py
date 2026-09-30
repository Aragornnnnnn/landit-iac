# 게시된 발음 기준 데이터와 BE 매니페스트로 expression_pronunciation_asset Flyway SQL을 만든다.
#
# 어드민 임포트 API(기준 데이터 upsert → TTS URL 조인)가 남기는 행과 같은 모양을 만든다:
# words = 기준 데이터 words에 BE 매니페스트의 단어별 audioUrl을 order로 붙인 배열.
# 적재 전에 writing_expression의 표현·대표 문장이 음성을 만든 원문과 같은지 대조하고, 다르면
# 마이그레이션을 멈춘다 (임포트 API의 "문장이 DB와 다릅니다" 검증을 옮긴 것, V95와 같은 방식).
# 그 기대 원문(--expressions)이 음성의 출처와 같은지도 SQL을 만들기 전에 확인한다: TTS 매니페스트
# (게시본)의 문장·표현 원문, BE 매니페스트의 URL, 기준 데이터의 문장이 모두 한 소스를 가리켜야 한다.
#
# 사용법:
#   python3 scripts/build_pronunciation_asset_sql.py --issue LAN-601 \
#       --tts-manifest work/manifest.json --be-manifest work/be-manifest.json \
#       --reference-dir work/reference-uploaded \
#       --expressions work/expressions.json --header work/header.sql --out V137__....sql
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ACCENT_LOCALES = ("EN_US", "EN_GB", "EN_AU")
# 표현 텍스트에 이 문자가 있으면 발화 불가능한 패턴형이라 표현 음성이 없다 (landit-ai build_tts_source.py와 같은 규칙).
TEMPLATED_EXPRESSION = re.compile(r"[~가-힣()+]")


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


def _url_matches_key(url: str | None, s3_key: str | None) -> bool:
    if url is None or s3_key is None:
        return url is None and s3_key is None
    return url.endswith("/" + s3_key)


def verify_provenance(
    expressions: list[dict], tts_manifest: dict, be_manifest: dict, references: dict
) -> None:
    """기대 원문·BE URL·기준 데이터가 모두 음성을 만든 TTS 매니페스트와 같은 소스인지 확인한다."""
    tts = {}
    for asset in tts_manifest["assets"]:
        tts[(asset["expressionId"], asset["accentLocale"], asset["kind"], asset.get("wordOrder"))] = asset
    be = {(a["expressionId"], a["accentLocale"]): a for a in be_manifest["assets"]}
    ids = {e["expressionId"] for e in expressions}
    if {key[0] for key in tts} != ids or {key[0] for key in be} != ids:
        raise ValueError("TTS/BE manifest expressions differ from the expression list")
    for expression in expressions:
        expression_id = expression["expressionId"]
        for locale in ACCENT_LOCALES:
            sentence = tts.get((expression_id, locale, "sentence", None))
            spoken = tts.get((expression_id, locale, "expression", None))
            be_asset = be.get((expression_id, locale))
            reference = references.get((expression_id, locale))
            if sentence is None or be_asset is None or reference is None:
                raise ValueError(f"{expression_id}/{locale}: missing sentence, BE or reference entry")
            if sentence["text"] != expression["sentenceText"] or reference["sentenceText"] != expression["sentenceText"]:
                raise ValueError(f"{expression_id}/{locale}: sentence text differs from the audio source")
            if spoken is None:
                if not TEMPLATED_EXPRESSION.search(expression["expressionText"]):
                    raise ValueError(f"{expression_id}/{locale}: expression audio is missing")
            elif spoken["text"] != expression["expressionText"]:
                raise ValueError(f"{expression_id}/{locale}: expression text differs from the audio source")
            if not _url_matches_key(be_asset["sentenceAudioUrl"], sentence["s3Key"]) or not _url_matches_key(
                be_asset["expressionAudioUrl"], spoken["s3Key"] if spoken else None
            ):
                raise ValueError(f"{expression_id}/{locale}: BE URL is not the published audio")
            for word in be_asset["words"]:
                tts_word = tts.get((expression_id, locale, "word", word["order"]))
                if tts_word is None or not _url_matches_key(word["audioUrl"], tts_word["s3Key"]):
                    raise ValueError(f"{expression_id}/{locale}/word-{word['order']}: BE URL is not the published audio")


def build_sql(
    issue: str,
    header: str,
    tts_manifest: dict,
    be_manifest: dict,
    references: dict,
    expressions: list[dict],
) -> str:
    verify_provenance(expressions, tts_manifest, be_manifest, references)
    ids = [e["expressionId"] for e in expressions]
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
    parser.add_argument("--tts-manifest", required=True, type=Path, help="음성을 게시한 작업 매니페스트")
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
        json.loads(args.tts_manifest.read_text(encoding="utf-8")),
        json.loads(args.be_manifest.read_text(encoding="utf-8")),
        load_reference(args.reference_dir),
        expressions,
    )
    args.out.write_text(sql, encoding="utf-8")
    print(f"expressions={len(expressions)} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
