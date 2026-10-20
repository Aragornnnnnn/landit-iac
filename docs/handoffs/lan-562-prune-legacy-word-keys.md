# LAN-562 옛 단어 키 69,531개 삭제 실행서 (2026-10-20)

LAN-475 백필(1단계)이 (억양, 해시)별 대표를 공용 자리 `word/{억양}/{해시}.mp3`로 복사하고,
LAN-560(V126, be-v1.6.0)이 DB의 `words[*].audioUrl`을 공용 주소로 바꾸고, LAN-561(iac#50)로
새 배치가 공용 자리만 만들게 된 뒤, 옛 단어 키 `{표현id}/{억양}/word/{순서}/{해시}.mp3`는
아무도 참조하지 않는다. 이 문서는 그 옛 키를 지우는 `prune-legacy-word-keys`의 실행 순서다.

## 되돌릴 수 없다 (먼저 읽을 것)

버킷 `landit-content-982529430654`에는 **버저닝이 없다**. 지운 객체의 복구 수단은 재합성뿐이다
(`generate → upload`, 이후 CloudFront 무효화). 그래서 서브커맨드는 삭제 직전에 안전장치 다섯을
순서대로 통과해야 하고, 하나라도 실패하면 아무것도 지우지 않는다.

| # | 안전장치 | 실패 시 |
| --- | --- | --- |
| 1 | dev·prod DB의 모든 `words[*].audioUrl`과 삭제 대상의 교집합이 0 | 전체 중단 (그 환경에 LAN-560이 덜 적용된 것) |
| 2 | 대상의 (억양, 해시) 전부가 공용 자리에 실물로 있음 (head-object 전수) | 빠진 (억양, 해시)의 옛 키는 대상에서 빼고 보고 |
| 3 | 삭제 목록(키·크기·sha)을 로컬 파일과 S3 `manifests/prune-legacy-word-keys-{sha}.json`에 남김 | 게시 실패면 중단 |
| 4 | `--execute`일 때만 1,000개 배치 `delete-objects`, 응답 `Errors` 비어 있고 `Deleted` 수 일치 | 그 배치에서 중단, 지운 수 출력 |
| 5 | 다시 나열해 옛 단어 키 0개, 공용·문장·표현·참조·풀 색인 객체 수 불변 | 중단 (이미 지운 뒤라 목록으로 사후 확인) |

대상은 정규식 `LEGACY_WORD_KEY_PATTERN`에 맞는 키뿐이다. `sentence/`·`expression/`·`manifests/`·
`reference/`·`word-pool/`·새 `word/{억양}/`가 대상에 하나라도 섞이면 계획 단계에서 즉시 중단한다.

## 선행 조건 (하나라도 미달이면 실행 금지)

- [x] LAN-560이 dev·prod 양쪽에 적용 완료됐다 — be-v1.6.0부터 prod, 현재 v1.7.6.
- [x] prod에서 단어 URL 표본을 CloudFront로 받아 200과 sha 일치를 확인했다 — 2026-10-20 공용 URL 5건
      (억양별 1~2건) 전부 200, 본문 sha256 = S3 `audio-sha256` 메타데이터. dev·prod의 단어 URL 집합은
      완전히 같다(16,710개, 양방향 차집합 0).
- [x] 3단계(LAN-561, iac#50)가 머지돼 새 배치가 옛 경로를 더는 만들지 않는다 — 2026-10-20 S3 실측에서
      옛 단어 키가 9/24 측정값 69,531개 그대로다(한 개도 늘지 않았다).

## 1. DB에서 단어 URL 전체 뽑기 (`--word-urls` 입력, 환경마다 하나)

안전장치 1의 입력이다. **빈 파일은 거부한다** — 교집합 0을 빈 목록으로 통과하면 안 되기 때문이다.
접속 정보는 SSM `/landit/{develop|prod}/DB_URL`·`DB_USERNAME`·`DB_PASSWORD`이고 값은 출력하지 않는다.

```sql
\copy (SELECT DISTINCT w->>'audioUrl'
       FROM expression_pronunciation_asset a, jsonb_array_elements(a.words) w
       WHERE w->>'audioUrl' IS NOT NULL ORDER BY 1) TO 'dev_word_urls.txt'
```

같은 쿼리를 prod에서 `prod_word_urls.txt`로 뽑는다. URL의 호스트는 무엇이든 떼고 S3 키로 비교한다.

함께 확인해 둘 것: `public` 스키마의 모든 text/varchar/json/jsonb 컬럼에서 옛 단어 키 패턴
`expression-pronunciation-audio/[0-9]+/[A-Z_]+/word/`를 찾아 `expression_pronunciation_asset.words`
밖에는 참조가 없는지 본다(기록·피드백 스냅샷 테이블이 옛 URL을 품고 있으면 삭제 후 404가 난다).
2026-10-20 실측: dev 418개·prod 354개 컬럼 중 양쪽 모두 `expression_pronunciation_asset.words`만 걸렸고,
그 3건은 아래 "알게 된 것"의 7451 변형 키라 삭제 대상이 아니다. 행 22,680·단어 170,994·공용 URL 170,991로
두 환경이 같다.

## 2. dry-run

```bash
python3 -m scripts.expression_pronunciation_audio prune-legacy-word-keys \
  --bucket landit-content-982529430654 \
  --word-urls dev_word_urls.txt --word-urls prod_word_urls.txt \
  --expect-count 69531 \
  --output lan562-prune-list.json --boto3
```

- `--expect-count`가 나열 결과와 다르면 아무것도 하지 않고 멈춘다.
- head-object를 대상 69,531 + 공용 10,506번 돈다. `--boto3`가 아니면 수 시간이 걸린다.
- 출력 `targets=…, units=…, legacyWord=…, sharedWord=…, sentence=…, expression=…` 가 실행 전
  객체 수 스냅샷이고, 삭제 목록의 `keyCountsBefore`에도 같은 값이 남는다.
- dry-run은 S3에 아무것도 쓰지 않는다(삭제 목록 키는 계산만 한다). 로컬 `--output`만 생긴다.

## 3. 실행

같은 명령에 `--execute`를 붙인다. `--word-urls`가 두 개 미만이면 인자 단계에서 거부한다.
순서는 1 → 2 → 3(목록 게시) → 4(삭제) → 5(재나열 검증)이고, 마지막 줄 `after: legacyWord=6, …`이
나와야 끝난 것이다(6은 아래 "알게 된 것"의 제외 키다). 중간에 죽으면 `deleted N/M before failing`이 나오고, 그대로 다시 돌리면 된다 —
남은 키만 다시 대상이 되고 삭제 목록은 새 키로 하나 더 게시된다.

## 4. 사후 확인

- prod 앱에서 단어 음성 재생 표본이 정상인지 본다(공용 URL이라 영향이 없어야 한다).
- CloudFront는 지운 객체도 캐시 만료(1년)까지 옛 URL로 계속 내보낼 수 있다. 참조가 없으니
  문제는 아니지만, "지웠는데 아직 열린다"가 정상임을 알아 둔다.
- 완료 기준의 "공용 단어 객체 10,494개"는 이슈 작성 시점 값이다. 배치 4·5·LAN-672가 공용 풀에
  합류해 2026-10-20 실측은 **18,012개(억양당 6,004)** 이고, 삭제 전후 이 수가 같아야 한다.

## 알게 된 것

- **7451 "résumé" 변형 키 3개**: dev·prod DB 모두 표현 7451 단어 8번(`résumé`)이 세 억양에서
  `{표현id}/{억양}/word/{해시}.mp3`(순서 조각 없음)를 가리키고, S3에도 그 키 3개가 실제로 있으며
  공용 자리 사본은 없다. 옛 키 정규식에 맞지 않아 **삭제 대상이 아니고 `other`로 분류된다**(안전장치
  5의 전후 비교에서도 그대로 유지돼야 한다). 어느 마이그레이션에도 없는 URL이라 어드민 TTS 임포트
  경로로 들어온 것으로 보인다. 공용 풀로 옮기는 일은 LAN-562 범위 밖이다.
- **공용 사본이 없어 제외되는 옛 키 6개**: 표현 1942 단어 6번과 1945 단어 5번의 세 억양. 예문이 수정되며
  버려진 옛 음성이라 백필이 `--unmatched drop`으로 풀에서 뺀 것이고, dev·prod DB 어느 쪽도 참조하지
  않는다. 안전장치 2가 대상에서 빼므로 실행 후에도 옛 단어 키는 0이 아니라 **6개**가 남는다. 이 6개까지
  지우려면 별도 결정이 필요하다(스크립트는 공용 사본 없는 키를 지우지 않는다).
- 옛 배치의 work 매니페스트와 BE 매니페스트(`manifests/`, `reference/`)는 옛 단어 키를 가리킨다.
  삭제 후 그 키로 어드민 API 재임포트를 하면 words의 audioUrl이 죽은 주소가 된다. 적재는 Flyway로
  바뀌어 실사용 경로가 아니지만, `lan-373-be-import.md`·`lan-453-batch3-982-1938.md`에 표시해 뒀다.

## 실행 기록 (2026-10-20)

- `--execute --boto3`로 1회 실행, 안전장치 1~5 전부 통과. **69,525개 삭제**, 옛 단어 키 6개(위 1942·1945 제외분) 잔존.
- 삭제 목록: `manifests/prune-legacy-word-keys-f44d7e12cbdc9f7d92b34ae655dcab41bbde9e4fb9c006cc04d2d8992fdec9f7.json`
  (69,525건, 302,324,070B). 버저닝이 없어 이것이 유일한 기록이다.
- 스크립트와 별개로 전후 키 목록을 다시 나열해 대조: 사라진 키 69,525개 전부 옛 단어 키 형식, 새로 생긴 키는
  삭제 목록 1개뿐. 공용 18,012 · 문장 26,292 · 표현 23,271 · reference 34 · word-pool 1 · 7451 변형 3 모두 불변.
- 삭제 후 prod 단어 URL 표본 5건(억양별 1~2건) CloudFront 200·sha 일치, 지운 옛 키는 origin에서 404.
- 상세 로그는 PR Aragornnnnnn/landit-iac#59 코멘트.
