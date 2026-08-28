# LAN-373 발음 학습 오디오 게시·BE 임포트 장부 (2026-08-27 확정)

LAN-373/LAN-377 발음 학습 오디오 배치의 게시 결과 기록. 게시에 쓴 소스가 리포에 없어
사후 감사가 불가능했던 문제를 이 문서로 보완한다. 검증 방법과 숫자는 전부 로컬 산출물
(`/tmp/lan377_full`)·업로드 로그·S3 실측(head/list)으로 재확인한 값이다 (2026-08-27).

## BE 임포트 키 최종본 (이것만 사용)

사람이 BE Swagger의 `manifestKey` 파라미터에 그대로 복사해 넣는다.

```text
reference EN_US: content/expression-pronunciation-audio/reference/EN_US-8ead1be2c8e9b3b9155ce81c4ba2f0a53c894805a16c5347efeecddf3f9d83e8.json
reference EN_GB: content/expression-pronunciation-audio/reference/EN_GB-d776b0a1216ad49a76e390e2c65055bdd4f01cd7d8f07513c92bd4b72c3eab6e.json
reference EN_AU: content/expression-pronunciation-audio/reference/EN_AU-e2eb9521a3c7bd710d78d71595d035485c0b071a68ca2ccb0bbe372c84a5da2e.json
be manifest    : content/expression-pronunciation-audio/manifests/be-d2abf4aa4d5651fd5a8097a218f66696a5aa4e5e98af6aaf3cb0f3544a7da759.json
```

5개 키 모두 S3 실물 존재 확인 완료. be manifest는 로컬 산출물 SHA-256과 키 해시 일치 확인.

### 폐기 키 (임포트에 사용 금지 — immutable이라 객체는 남아 있음)

| 키 | 폐기 사유 |
| --- | --- |
| `reference/EN_AU-be18ae8f…` | EN_AU 억양 대조 비활성화 **전** 데이터. 이 키로 임포트하면 오탐 유발 대조 힌트가 DB에 들어간다 |
| `manifests/09f79f1d…` (2026-08-26) | 초기 샘플(표현 1 EN_GB 10객체) 검증용 작업 매니페스트 |

## 게시 식별자·자산 구성

| 항목 | 값 |
| --- | --- |
| source_sha256 | `111b5f8c35d3374af3f4b3f9d86e2e6ae05f82bba446c67147c9f76b46f2a625` |
| 작업 매니페스트 키 | `content/expression-pronunciation-audio/manifests/143a6e39272bf2a2c68fd1c182b9c9c5d85f6c88773d3a56127ef36328799612.json` |
| 표현 수 | 981 (expressionId 1~981) × 3 locale (EN_US/EN_GB/EN_AU) |
| **오디오 자산 정본** | **29,157** = sentence 2,943 + expression 2,535 + word 23,679 (locale당 9,719) |
| S3 실측 (2026-08-27) | mp3 정확히 29,157개 · manifests 3개 · reference 4개 |
| 표현 음성 생략 | 136 표현 × 3 locale = 408행 — be manifest에서 `expressionAudioUrl: null` (BE 컬럼 nullable, 정상) |

소스 자기일관성: `981(문장) + 845(표현) + 7,893(단어) = 9,719/locale`, ×3 = 29,157.
state.json·작업 매니페스트·로컬 mp3 파일 수·S3 업로드 검증(`verified=29158` = mp3 29,157 +
매니페스트 1) 전부 일치.

### 게시 개수 세 숫자 정산 (확인 B 결론)

| 숫자 | 정체 | 근거 |
| --- | --- | --- |
| **29,157** | 자산 정본 | 위 자기일관성 + S3 실측 1:1 |
| 29,147 | dry-run 시점 신규 업로드 예정 mp3 | dry-run 로그 `new=29148`(매니페스트 포함) − 1 |
| 29,169 | 업로드 중 모니터링 원라이너의 잘못된 분모 | `29,148(신규) + 21(기존 객체 오산)` — 기존 mp3는 10개였고, 21은 reference·manifest 등 비-mp3 객체까지 섞어 센 값. 자산 수로 쓰인 적 없음 |

- **29,157 − 29,147 = 10**: 사전 스모크 게시로 이미 S3에 있던 **표현 1 EN_GB 전체 세트**
  (expression 1 + sentence 1 + word 1~8 = 10객체)가 dry-run에서 재사용으로 분류된 것.
  항목 단위로 dry-run 신규 키 목록과 매니페스트 대조로 확인 완료.
- 소스 결손 검사: `accentLocales` 비었거나 없는 표현 **0**, `words` 비었거나 없는 표현 **0**.
- 표현 음성 생략 136개 검증: BE 시드 SQL(V44·V52)에서 원문(target_expression_text)을 확보한
  **122개 전부 패턴 문자(`~`·`+`·괄호·한글) 포함 확인** — 조용히 잘못 생략된 표현 없음.
  역방향으로 expressionText가 있는 845개 중 패턴 문자 포함 **0**, 소스 vs SQL 원문 불일치 **0**.
  나머지 14개(id 15, 18, 22, 23, 32, 34, 40, 45, 56, 61, 76, 77, 78, 79)는 리포 시드 SQL에
  없어(DB 직접 삽입분) 로컬 검증 불가 — BE DB에서
  `SELECT id, target_expression_text FROM writing_expression WHERE id IN (…)`로 확인 필요.

## EN_AU +1.5dB 게인 (확인 A 결론)

**적용됐다 — 단, 파이프라인 스크립트 밖에서.** 사실관계:

- 2026-08-27 14:24 KST 실측: EN_US 평균 -22.2dB / EN_GB -22.7 / EN_AU **-23.3dB**.
- 14:25 KST, 업로드 **전에** `/tmp/lan377_full/mp3`의 EN_AU 9,719개 전체에
  `ffmpeg -af volume=1.5dB -codec:a libmp3lame -q:a 2`로 **재인코딩 게인**을 제자리 적용
  (실패 0). 보정 후 EN_AU 평균 **-21.9dB** (EN_US와 동급).
- 이어서 state.json의 AU 항목(audioSha256·byteSize)을 보정본 기준으로 갱신하고 작업
  매니페스트를 재빌드한 뒤 업로드했다. 따라서 **S3 게시본 = 보정본**이며 state·매니페스트·
  S3 metadata(audio-sha256)·바이트 크기가 전부 보정본과 일치한다 (AU 3개 무작위 스팟 체크 +
  ffmpeg 재측정으로 확인).
- `scripts/expression_pronunciation_audio.py`에 게인 로직이 없는 것도 사실이다 — 일회성
  후처리였고 코드에 반영되지 않았다. 보고(-23.3→-21.9)는 정확했으나 "스크립트 밖 수동
  처리"라는 사실이 기록에 빠져 있었다. 이 문서로 정정한다.

**알려진 지뢰**: generation fingerprint(model·voice·text·format)에 게인이 반영되지 않는다.
EN_AU를 재합성하면 **게인 없는 버전이 같은 키로 계산**되고, 기존 immutable 객체와 바이트가
달라 업로드 계획에서 **conflict로 중단**된다(fail-closed — 조용한 덮어쓰기는 없음). 단
`--reuse-s3-bucket` 경로는 S3의 보정본을 내려받아 재사용하므로 정상 동작한다. EN_AU 재생성이
필요해지면 generation contract에 revision(후처리) 필드를 넣는 후속 작업이 선행돼야 한다.

## EN_AU 억양 대조 전면 비활성화

게이트 A 실측(landit-ai `docs/tasks/LAN-373/gates.md`)에서 정당한 호주 발음이 4/4 오탐됐다.
espeak의 호주 발음이 영국과 사실상 동일해 AU 대조는 독자적 근거가 약했고, 오탐으로 벌하는
것보다 힌트를 빼는 것이 낫다(오탐 제로 원칙)는 판단으로 기획 추인을 받아 비활성화했다.
호주 튜터 유저는 억양 대조 힌트 없이 본 판정(발음·강세)만 받는다. 이 정책 반영 전의
reference EN_AU 옛 키(be18ae8f…)를 폐기하고 신규 키(e2eb9521…)를 게시했다.

## 후속 작업 목록 (별도 승인 후 진행)

- 게시 소스(tts_source.json)를 리포에 커밋해 감사 가능성 확보 — 현재 `/tmp`에만 있음
  (`/tmp/tts_source_check.json`, sha 일치 확인됨)
- 소스 검증 강화: 빈 `words`/`accentLocales` 거부, `order` 타입 검증
- generation_contract에 revision 필드 (게인 등 후처리 반영 · 정정 오디오 게시 경로)
- `--reuse-s3-bucket` 경로 sha 검증 fail-closed + 원자적 다운로드
- build-be-manifest의 s3Key 실재(head) 확인
- verify-accent 재시도 + 체크포인트
- state.json flush 배치화 (현재 자산 1개마다 전체 rewrite)
- 미검증 14개 표현의 원문 패턴 문자 확인 (BE DB 조회)
