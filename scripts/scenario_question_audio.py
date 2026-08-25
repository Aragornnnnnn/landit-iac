# production 시나리오 고정 질문을 MP3로 생성하고 immutable S3 객체로 게시한다.

from collections import Counter, defaultdict
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


VOICE_BY_CHARACTER = {
    "chloe": "aura-2-luna-en",
    "marco": "aura-2-hyperion-en",
    "teddy": "aura-2-draco-en",
}
EXPECTED_QUESTION_COUNTS = {"chloe": 9, "marco": 24, "teddy": 87}
MODEL = "deepgram/aura-2"
RESPONSE_FORMAT = "mp3"


@dataclass(frozen=True)
class SourceAsset:
    scenario_id: int
    scenario_question_id: int
    display_order: int
    character_id: str
    question_text: str


@dataclass(frozen=True)
class SourceSnapshot:
    schema_version: int
    environment: str
    target_locale: str
    base_locale: str
    assets: tuple[SourceAsset, ...]


def load_source(path: Path) -> SourceSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    snapshot = SourceSnapshot(
        schema_version=payload["schemaVersion"],
        environment=payload["environment"],
        target_locale=payload["targetLocale"],
        base_locale=payload["baseLocale"],
        assets=tuple(
            SourceAsset(
                scenario_id=asset["scenarioId"],
                scenario_question_id=asset["scenarioQuestionId"],
                display_order=asset["displayOrder"],
                character_id=asset["characterId"],
                question_text=asset["questionText"],
            )
            for asset in payload["assets"]
        ),
    )
    validate_source(snapshot)
    return snapshot


def generation_contract(asset: SourceAsset) -> dict[str, str]:
    return {
        "model": MODEL,
        "providerVoiceId": VOICE_BY_CHARACTER[asset.character_id],
        "questionText": asset.question_text,
        "responseFormat": RESPONSE_FORMAT,
    }


def generation_fingerprint(asset: SourceAsset) -> str:
    encoded = json.dumps(
        generation_contract(asset),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def select_sample_ids(snapshot: SourceSnapshot) -> set[int]:
    assets_by_character: dict[str, list[SourceAsset]] = defaultdict(list)
    for asset in snapshot.assets:
        assets_by_character[asset.character_id].append(asset)

    selected = set()
    for character_id in VOICE_BY_CHARACTER:
        assets = sorted(
            assets_by_character[character_id],
            key=lambda asset: (
                len(asset.question_text.encode("utf-8")),
                asset.scenario_question_id,
            ),
        )
        selected.add(assets[len(assets) // 2].scenario_question_id)
    return selected


def source_sha256(snapshot: SourceSnapshot) -> str:
    payload = {
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
            for asset in sorted(
                snapshot.assets,
                key=lambda item: (
                    item.scenario_id,
                    item.display_order,
                    item.scenario_question_id,
                ),
            )
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate-source")
    validate_parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "validate-source":
        snapshot = load_source(args.source)
        print(
            "40 scenarios, 120 questions, chloe=9, marco=24, teddy=87, "
            f"source_sha256={source_sha256(snapshot)}"
        )
    return 0


def validate_source(snapshot: SourceSnapshot) -> None:
    if (
        snapshot.schema_version != 1
        or snapshot.environment != "production"
        or snapshot.target_locale != "EN"
        or snapshot.base_locale != "KR"
    ):
        raise ValueError("source must use schema version 1 and production EN/KR metadata")
    if len(snapshot.assets) != 120:
        raise ValueError("source must contain exactly 120 questions")

    question_ids = [asset.scenario_question_id for asset in snapshot.assets]
    if len(set(question_ids)) != len(question_ids):
        raise ValueError("source contains a duplicate question id")
    if any(not asset.question_text.strip() for asset in snapshot.assets):
        raise ValueError("source contains a blank question text")

    unsupported_characters = {
        asset.character_id
        for asset in snapshot.assets
        if asset.character_id not in VOICE_BY_CHARACTER
    }
    if unsupported_characters:
        raise ValueError(
            f"source contains an unsupported character: {sorted(unsupported_characters)}"
        )

    character_question_counts = Counter(
        asset.character_id for asset in snapshot.assets
    )
    if dict(character_question_counts) != EXPECTED_QUESTION_COUNTS:
        raise ValueError(
            "source character question counts must be chloe=9, marco=24, teddy=87"
        )

    orders_by_scenario: dict[int, list[int]] = defaultdict(list)
    characters_by_scenario: dict[int, set[str]] = defaultdict(set)
    for asset in snapshot.assets:
        orders_by_scenario[asset.scenario_id].append(asset.display_order)
        characters_by_scenario[asset.scenario_id].add(asset.character_id)
    if any(sorted(orders) != [1, 2, 3] for orders in orders_by_scenario.values()):
        raise ValueError("each scenario must contain display orders 1, 2, and 3")
    if any(len(characters) != 1 for characters in characters_by_scenario.values()):
        raise ValueError("each scenario must use exactly one character")


if __name__ == "__main__":
    raise SystemExit(main())
