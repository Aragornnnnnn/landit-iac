# LAN-601 시나리오 41~70 질문·표현 음원 인수인계 (LAN-391용)

시나리오 41~70의 질문 음원 270개와 표현 발음 자산(표현 328개 × 3억양)을 S3에 게시했다(2026-09-30). LAN-391은 아래 id와 URL을 V135(질문)와 V136(표현) migration에 반영하고, 발음 자산 migration도 같은 PR에 넣는다.

## LAN-391이 반영할 것

1. **id 명시**: `scenario_question`과 `scenario_question_language_variant`에 365~634를, `writing_expression`에 4001~4328을 **파일 행 순서대로** 적는다. 파일 끝에서 각 테이블 시퀀스를 `setval`로 맞춘다.
2. **`audio_url` 채우기**: [questions.csv](lan-601/questions.csv)의 `audio_url`을 V135의 NULL 270곳에 넣는다.
3. **원문 수정 2건**: 아래 두 질문은 TTS가 감탄사를 끝내 읽지 못해, 수정 문안으로 음원을 만들었다(사용자 승인).

   | 질문 id | 새 question_text | 새 question_translation (제안) |
   | --- | --- | --- |
   | 400 (Day 50 · LEVEL_4_TO_5 · 3번) | Oh man, I need to clear my head. What should we do to cheer me up? | 아 진짜, 기분 전환이 필요해. 우리 뭐 하면서 기분 풀까? |
   | 419 (Day 58 · LEVEL_1 · 1번) | Wait, did I borrow a book from you? | 잠깐, 내가 너한테 책을 빌렸었나? |

4. **발음 자산 migration 포함**: [V137__insert_scenario_41_70_expression_pronunciation_assets.sql](lan-601/V137__insert_scenario_41_70_expression_pronunciation_assets.sql)을 V136 바로 다음 번호로 PR에 넣는다.
   - `expression_pronunciation_asset` 984행(328표현 × 3억양)을 넣는다.
   - 적재 전에 id 4001~4328의 표현과 대표 문장을 음성 원문과 대조하고, 다르면 멈춘다.
   - 로컬 PostgreSQL 14(V60·V62·V63 스키마)에서 검증했다: 984행 적재, 표현 음성 NULL 186행(패턴 표현 62×3), 단어 audioUrl 누락 0, 억양 대조 102개, 재적용 가능(ON CONFLICT), 원문이 다르면 중단.
5. **행 순서 고정**: 두 파일의 INSERT 행 순서를 바꾸지 않는다. id는 행 순서로 채번했으며, 아래 해시 시점에서 행 순서와 원문을 다시 대조했다.

## id 채번 근거

| 테이블 | 범위 | 근거 |
| --- | --- | --- |
| `scenario_question` | 365~634 | develop `06f4775` migration 기준. V78이 121~360을 고정했고, V90이 진단 질문 4개(361~364)를 시퀀스로 추가했다. develop 대상 열린 PR 10개(#219~#232)에는 `scenario_question` INSERT가 없다(2026-09-29 diff 확인). |
| `writing_expression` | 4001~4328 | 표현 1000개 PR #230(V127)이 id 3001~4000을 SQL에 고정했다. #230의 범위가 바뀌면 다시 채번해야 한다. |

- dev DB의 `max(id)`는 직접 조회하지 못했다. 머지 직전에 dev와 prod에서 두 테이블의 `max(id)`가 각각 364와 4000인지 확인한다.
- scenario id는 LAN-391 최신본대로 id = display_order(Day) = 41~70이다.

## 입력 파일 (대조 시점 해시)

| 파일 | SHA-256 |
| --- | --- |
| `V135__insert_scenario_41_70.sql` | `3fabec5c79906c40b4c32b85b6b9e9f29f013c9f6f5219d11c7a1e9b8f7fc41e` |
| `V136__insert_scenario_41_70_writing_expressions.sql` | `cf43c7af151f6c5f3809f5700bf6ca85d5ee63f2f52c4aec63d623aa6e497e12` |

처음 추출할 때 V135 해시는 `66d01783…`, V136 해시는 `d74d8c48…`였다. 그 뒤 시나리오 id 고정, 썸네일 URL 등이 바뀌었지만 질문 270행과 표현 328행의 순서와 원문은 그대로임을 확인했다.

## 매핑 파일

- [questions.csv](lan-601/questions.csv) (270행): `scenario_question_id, scenario_id, day, question_level_group, display_order, character_id, question_text, audio_url`. 400과 419는 수정 문안이 들어 있다.
- [expressions.csv](lan-601/expressions.csv) (984행 = 328 × 3억양): `writing_expression_id, scenario_id, day, display_order, target_expression_text, accent_locale, expression_audio_url, sentence_audio_url, word_audio_count`
  - 패턴 표현(`~`, 괄호 포함) 62개는 `expression_audio_url`이 비어 있다. 정상이며, BE 컬럼은 nullable이다.
  - 단어별 URL은 아래 BE manifest의 `words[]`에 있다.

## 게시 키

```text
질문 manifest   : content/scenario-question-audio/manifests/baf2cb938c96af0f71a0a15057e3553ca5483843595d1edc2fa7dc1fe2f02a06.json
표현 manifest   : content/expression-pronunciation-audio/manifests/fa01d5c9c9b3c1a0dd21199a922e69cf8175f99d22767da9c6d768869e95dcfc.json
BE manifest     : content/expression-pronunciation-audio/manifests/be-6ecf475f43ede5d46f4fbfbc00fe78fe27cf1c266ee3bde5031b7cfcf58520c6.json
reference EN_US : content/expression-pronunciation-audio/reference/EN_US-3acb0d4b883eba9a4afdc5e107a58f5ebf38b3ee265160474295632c26358b66.json
reference EN_GB : content/expression-pronunciation-audio/reference/EN_GB-5008e4b2ca944c1fd8618f10742468f59725ab9ef815846f7b74b9b97059d722.json
reference EN_AU : content/expression-pronunciation-audio/reference/EN_AU-0e14706cc72afd7cff1df5de4abecb3c3245bd77fac68d67deb1b1dd2f13eaf5.json
```

URL은 `https://d19azau1un4t7r.cloudfront.net/{s3Key}`로 만든다.

**주의: 질문 manifest의 `scenarioId`는 쓰지 않는다.** 이 값은 LAN-391이 scenario id를 고정하기 전 기준(행 순서 41부터)이라 270개 중 261개가 틀렸다. 음원 URL(`s3Key`)과 질문 id는 정확하다. manifest를 다시 게시하려면 MP3 270개의 객체 메타데이터(`source-sha256`)를 덮어써야 해서 하지 않았다. 올바른 scenario id와 Day는 questions.csv를 따른다.

## 게시·검증 결과

| 항목 | 값 |
| --- | --- |
| 질문 MP3 | 270개 (chloe 63 · marco 63 · teddy 144), 8,494,272 bytes |
| 표현 단위 | 4,308개 = 새로 합성 2,193 (표현 798 · 문장 984 · 단어 411) + 공용 풀 단어 재사용 2,115 |
| 업로드 | 질문 uploaded=271(manifest 포함), 표현 uploaded=2,194(manifest 포함), conflicts=0 |
| CDN 재다운로드 | 4,578 키 전수 SHA-256·크기 일치, 불일치 0 |
| 응답 | `audio/mpeg`, `public, max-age=31536000, immutable`, 캐릭터별 Range 요청 206 |

## 품질 검수 요약

- **질문**: 무음 검사, Whisper 전사 대조, 불합격분 Gemini 재판정을 거쳤다. 불량 26개는 재합성했고, 400과 419는 원문을 수정했다. 캐릭터별 샘플과 재합성분은 사람이 청취했다.
- **표현**: 새로 합성한 2,193개만 같은 절차로 검수했다(공용 풀 단어는 LAN-475에서 검수 완료).
  - 남은 불량 24개와 무작위 45개는 사람이 청취해 판정했다.
- **읽기 표기 치환**: 화면 표기와 S3 키는 원문 그대로 두고, TTS에 보내는 입력만 바꿨다.
  - `JIYU KIM` → `Jiyu Kim`
  - `sikhye` → `shik-hyeh`
  - `bulgogi` → 문장 속과 AU 단어는 `bul go ki`, US·GB 단어는 `bulgokee`
- **억양 대조 힌트**: 160 → 102. verify-accent 1차 실패분과, 3회 판정 중 2회 이상 실패한 7건을 reference에서 제거했다.
- **사람이 고른 클립**: `openRouterGenerationId`가 `lan601-human-approved-sample`로 표시된다.
