# LAN-601 시나리오 41~70 질문·표현 TTS

## 범위

- LAN-601은 시나리오 41~70의 질문 음원 270개와 표현 음원 328개를 만든다.
  - 표현 음원은 LAN-377과 같은 범위(3억양 × 표현·문장·단어)다.
  - 만든 음원은 S3에 올리고, id 매핑과 URL을 LAN-391에 넘긴다.
- landit-be의 시나리오·질문·표현 INSERT는 LAN-391이 반영한다.
  - 대상 파일은 `V135__insert_scenario_41_70.sql`과 `V136__insert_scenario_41_70_writing_expressions.sql`이다.
- LAN-601은 발음 자산(`expression_pronunciation_asset`) migration 하나만 작성한다.
  - 번호는 LAN-391 INSERT 뒤로 잡는다.
- migration 적용 순서는 다음과 같다.
  1. 표현 1000개(landit-be PR #230, V127)
  2. LAN-391 INSERT
  3. LAN-601 발음 자산

## 입력

입력은 landit-be 워킹 트리에 untracked로 있는 LAN-391 최신본이다. `Downloads/sql_41_70`은 `character_id`가 없어서 쓰지 않는다.

| 파일 | SHA-256 (2026-09-29 추출 시점) |
| --- | --- |
| `V135__insert_scenario_41_70.sql` | `66d0178335174cccfed00f958fb695220b63f5823381771079ddc17f2e1b4e16` |
| `V136__insert_scenario_41_70_writing_expressions.sql` | `d74d8c481621f9ac04183d20956d58794d571cc6b35203787dc1724b0d431da4` |

채번 이후 LAN-391은 두 파일의 행 순서를 바꾸지 않는다. 행 순서가 바뀌었는지는 위 해시로 확인한다.

## id 채번 규칙

- **시작 번호**: develop 머지 시점 기준 `max(id) + 1`
  - develop 브랜치의 migration에서 계산한 값과 dev DB 읽기 전용 조회 값을 교차 확인한다.
  - 근거로 커밋 해시, 조회 시각, 두 값을 남긴다.
- **질문**: V135의 `scenario_question` INSERT 행 순서대로 연속 부여한다.
- **표현**: V136의 `writing_expression` INSERT 행 순서대로 연속 부여한다.
- **scenarioId**: V135의 `scenario` INSERT 행 순서대로 41~70을 부여한다. 음원 key에는 쓰지 않고 manifest 메타데이터로만 남는다.
- **채번 전 확인**: develop 대상 열린 PR에 `scenario_question` INSERT가 없는지 확인한다.

## 현재 상태 (2026-09-29)

- **선행 조건 미충족**
  - 표현 1000개 PR #230이 아직 열려 있다.
  - 그래서 채번, 실제 TTS 생성, 업로드는 보류 중이다.
- **확인 결과**: develop 대상 열린 PR 10개(#219~#232)의 diff를 확인했다. `scenario_question` INSERT는 없고, `writing_expression` INSERT는 #230에만 있다.
- **완료된 준비 작업**
  - `scripts/lan601_extract_source.py`
    - V135와 V136에서 질문 270개와 표현 328개를 추출한다.
    - 시작 id는 인자로 받는다.
  - `scripts/scenario_question_audio.py`
    - `LAN-601` 계약을 추가했다.
    - 계약 내용: 30 시나리오, 270 질문, chloe 63, marco 63, teddy 144, `LEVEL_4_TO_5` 포함.
  - 임시 id(질문 361~, 표현 4001~)로 소스 검증을 모두 통과했다.
    - 질문: `validate-source` 통과
    - 표현: `validate-source` 통과. expressions 328, assets 10,053, contrasts 160
    - 표현 음성 생략(패턴 표현)은 62개다.
  - landit-ai `generate_pronunciation_reference.py`
    - 음절 수동 분리 7개를 추가했다: carrier, jiyu, layers, management, simpler, somewhere, usb.
    - 남은 검수 항목은 숫자 단어 `2` 하나다. 판정 제외 대상이고, 정렬은 `two`로 한다.

## 발견 사항

- **`JIYU KIM` (표현 행 V136 Day 70 display_order 9)**
  - 대문자 표기라서 TTS가 글자 단위로 읽을 수 있다.
  - 샘플을 청취해서 확인한다. 문제가 있으면 LAN-391에 표기 변경을 요청한다.
- **EN_AU 억양 대조 0개**
  - 기존 게이트 A 실측 결과에 따라 대조를 전면 비활성화한 것이다. 정상이다.

## 남은 순서

1. **PR #230 머지 후 채번**
   - 시작 번호를 확정한다.
   - 추출기를 다시 실행해 `sources/scenario-question-audio/lan-601.json`을 커밋한다.
2. **질문 음원**
   - 실행 순서: `generate --sample-only` → 청취 → `generate` → `verify` → `build-manifest` → `upload`
   - `upload`는 dry-run으로 먼저 돌리고, 승인 후 `--execute`로 실행한다.
3. **표현 음원**
   - landit-ai에서 reference와 TTS 소스를 만든다.
   - 이후 실행 순서: `generate` → `verify` → `verify-accent` → `build-manifest` → `upload-reference` → `build-be-manifest` → `upload`
4. **인수인계 문서 작성**: `docs/handoffs/lan-601-be-audio-urls.md`
   - 질문 매핑 270행: `id ↔ (Day, 레벨, 문항 순번) ↔ URL`
   - 표현 매핑 328행: `id ↔ (Day, display_order) ↔ URL`
   - manifest 키
   - 채번 근거
5. **LAN-391 반영본 회신 후 로컬 검증**
   - 반영본에는 명시 id, URL, setval이 들어간다.
   - 로컬 PostgreSQL에 표현 1000개 → LAN-391 → 발음 자산 순서로 적용해 검증한다.
6. **발음 자산 migration PR**: LAN-391 PR 머지 후 올린다.
