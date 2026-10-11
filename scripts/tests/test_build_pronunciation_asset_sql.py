# 발음 자산 SQL 생성기가 음성 출처와 어긋난 입력을 SQL 생성 전에 거부하는지 검증한다.

import copy
import unittest

from scripts.build_pronunciation_asset_sql import build_sql, verify_provenance

CDN = "https://cdn.test/"
LOCALES = ("EN_US", "EN_GB", "EN_AU")


def sentence_key(locale):
    return f"content/expression-pronunciation-audio/7/{locale}/sentence/s.mp3"


def expression_key(locale):
    return f"content/expression-pronunciation-audio/7/{locale}/expression/e.mp3"


def word_key(locale, order):
    return f"content/expression-pronunciation-audio/word/{locale}/w{order}.mp3"


def fixture():
    expressions = [{"expressionId": 7, "expressionText": "turn left", "sentenceText": "Turn left here."}]
    tts = {"assets": []}
    be = {"assets": []}
    references = {}
    for locale in LOCALES:
        tts["assets"] += [
            {"expressionId": 7, "accentLocale": locale, "kind": "sentence", "wordOrder": None,
             "text": "Turn left here.", "s3Key": sentence_key(locale)},
            {"expressionId": 7, "accentLocale": locale, "kind": "expression", "wordOrder": None,
             "text": "turn left", "s3Key": expression_key(locale)},
        ] + [
            {"expressionId": 7, "accentLocale": locale, "kind": "word", "wordOrder": order,
             "text": word, "s3Key": word_key(locale, order)}
            for order, word in ((1, "Turn"), (2, "left"), (3, "here"))
        ]
        be["assets"].append({
            "expressionId": 7, "accentLocale": locale,
            "expressionAudioUrl": CDN + expression_key(locale),
            "sentenceAudioUrl": CDN + sentence_key(locale),
            "words": [{"order": order, "audioUrl": CDN + word_key(locale, order)} for order in (1, 2, 3)],
        })
        references[(7, locale)] = {
            "expressionId": 7, "accentLocale": locale, "sentenceText": "Turn left here.",
            "words": [{"order": order, "word": word} for order, word in ((1, "Turn"), (2, "left"), (3, "here"))],
        }
    return expressions, tts, be, references


class ProvenanceTests(unittest.TestCase):
    def test_matching_inputs_build_one_row_per_accent(self):
        expressions, tts, be, references = fixture()

        sql = build_sql("LAN-TEST", "-- header", tts, be, references, expressions)

        self.assertEqual(3, sql.count("::jsonb,now(),now())"))
        self.assertIn("(7, 'turn left', 'Turn left here.')", sql)

    def test_edited_sentence_text_is_rejected(self):
        # 원문을 고친 뒤 --expressions만 다시 만들면 옛 음성이 새 원문 행에 붙는다.
        expressions, tts, be, references = fixture()
        expressions[0]["sentenceText"] = "Turn right here."

        with self.assertRaisesRegex(ValueError, "sentence text differs"):
            verify_provenance(expressions, tts, be, references)

    def test_edited_expression_text_is_rejected(self):
        expressions, tts, be, references = fixture()
        expressions[0]["expressionText"] = "turn right"

        with self.assertRaisesRegex(ValueError, "expression text differs"):
            verify_provenance(expressions, tts, be, references)

    def test_be_url_that_is_not_the_published_audio_is_rejected(self):
        expressions, tts, be, references = fixture()
        be["assets"][0]["words"][1]["audioUrl"] = CDN + "content/other.mp3"

        with self.assertRaisesRegex(ValueError, "word-2: BE URL"):
            verify_provenance(expressions, tts, be, references)

    def test_reference_from_another_source_is_rejected(self):
        expressions, tts, be, references = fixture()
        references[(7, "EN_GB")]["sentenceText"] = "Turn left there."

        with self.assertRaisesRegex(ValueError, "sentence text differs"):
            verify_provenance(expressions, tts, be, references)

    def test_templated_expression_may_have_no_expression_audio(self):
        expressions, tts, be, references = fixture()
        expressions[0]["expressionText"] = "turn ~"
        tts["assets"] = [a for a in tts["assets"] if a["kind"] != "expression"]
        for asset in be["assets"]:
            asset["expressionAudioUrl"] = None

        verify_provenance(expressions, tts, be, references)

    def test_missing_expression_audio_for_speakable_text_is_rejected(self):
        expressions, tts, be, references = fixture()
        tts["assets"] = [a for a in tts["assets"] if a["kind"] != "expression"]
        for asset in be["assets"]:
            asset["expressionAudioUrl"] = None

        with self.assertRaisesRegex(ValueError, "expression audio is missing"):
            verify_provenance(copy.deepcopy(expressions), tts, be, references)


if __name__ == "__main__":
    unittest.main()
