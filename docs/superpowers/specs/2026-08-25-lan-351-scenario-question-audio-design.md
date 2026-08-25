# LAN-351 시나리오 고정 질문 TTS 게시 설계

## 목표

production의 활성 시나리오 40개에 속한 영어 고정 질문 120개를 지정된 Deepgram Aura-2 voice로 MP3 변환하고, 재생성과 검증이 가능한 manifest와 함께 기존 shared private content S3 bucket에 게시한다.

후속 런타임은 이 자산을 사용자 발화에 대한 맞장구 TTS와 결합해 FE에 전달한다. 이번 작업은 해당 후속 구현이 정확한 객체를 조회할 수 있는 저장 계약까지만 제공한다.

## 범위

이번 작업은 다음을 포함한다.

- production DB의 활성 영어 질문과 시나리오 캐릭터 매핑을 읽기 전용으로 export한다.
- export snapshot의 구조, 개수, 순서와 digest를 검증한다.
- 캐릭터별 샘플 MP3를 생성하고 사람 검수 승인을 받는다.
- 승인 후 전체 120개 MP3를 재개 가능한 방식으로 생성한다.
- 생성 입력과 결과를 연결하는 manifest를 만든다.
- 로컬 전체 검증과 S3 변경 목록 검토 뒤 사용자 별도 승인으로 shared S3에 업로드한다.
- 업로드된 객체의 개수, metadata, byte size와 SHA-256을 manifest와 대조한다.
- 생성·검증·업로드 절차와 후속 런타임 조회 계약을 문서화한다.

다음은 범위에서 제외한다.

- landit-be와 landit-ai 코드 변경.
- BE·AI runtime IAM의 shared content `GetObject` 권한.
- 질문 오디오 S3 key 또는 URL을 저장하는 DB 컬럼과 migration.
- 맞장구 TTS 생성, 오디오 결합, 재인코딩과 FE 응답 계약.
- Terraform apply 또는 기존 AWS 리소스 구성 변경.

## 확인된 production 기준

2026-08-25 읽기 전용 집계 결과는 다음과 같다.

| 항목 | 결과 |
| --- | ---: |
| 활성 시나리오 | 40 |
| 활성 `EN`/`KR` 고정 질문 | 120 |
| 빈 질문 | 0 |
| 질문 수나 순서가 잘못된 시나리오 | 0 |
| Chloe 시나리오 / 질문 | 3 / 9 |
| Marco 시나리오 / 질문 | 8 / 24 |
| Teddy 시나리오 / 질문 | 29 / 87 |

질문 원문, 질문 ID, 순서와 캐릭터를 정렬해 계산한 초기 MD5는 `9c79b5aec3333eb7022dca5b9da10f39`다. 실제 생성 직전에는 전체 export JSON을 기준으로 SHA-256을 새로 계산하고, 위 집계와 달라지면 생성하지 않고 변경 내용을 보고한다.

production의 Chloe는 현재 `microsoft/mai-voice-2`에 연결돼 있지만, LAN-351에서는 사용자의 명시적 요청에 따라 아래 Aura-2 voice를 사용한다. 이 override는 manifest에 기록한다.

## TTS 계약

| 캐릭터 | OpenRouter model | `provider_voice_id` | 출력 | 생성 수 |
| --- | --- | --- | --- | ---: |
| Chloe | `deepgram/aura-2` | `aura-2-luna-en` | MP3 | 9 |
| Marco | `deepgram/aura-2` | `aura-2-hyperion-en` | MP3 | 24 |
| Teddy | `deepgram/aura-2` | `aura-2-draco-en` | MP3 | 87 |

OpenRouter에는 다음 요청을 보낸다.

```json
{
  "model": "deepgram/aura-2",
  "input": "<questionText>",
  "voice": "<providerVoiceId>",
  "response_format": "mp3"
}
```

응답은 raw MP3 byte stream으로 취급한다. `OPENROUTER_API_KEY`는 환경변수에서만 읽고 요청 body, manifest, 로그와 저장소에 남기지 않는다. OpenRouter의 `X-Generation-Id`는 비밀값이 아니며 생성 추적을 위해 manifest에 저장한다.

## source snapshot

생성 입력은 production DB에서 다음 조건으로 읽는다.

- `scenario.status = ACTIVE`.
- `scenario_question.status = ACTIVE`.
- `scenario_question_language_variant.status = ACTIVE`.
- `target_locale = EN`, `base_locale = KR`.
- 시나리오의 `character_id`와 질문의 `id`, `display_order`, `question_text`를 포함한다.

snapshot은 `scenarioId`, `displayOrder`, `scenarioQuestionId` 순서로 정렬하고 `/tmp/landit-lan-351-audio/source.json`에 둔다. 이 임시 파일은 최종 manifest에 필요한 source 필드가 모두 옮겨진 뒤 삭제하며 저장소에는 커밋하지 않는다. 다음 조건을 모두 만족해야 유효하다.

- 시나리오 40개와 질문 120개다.
- 각 시나리오에 질문이 정확히 3개 있다.
- 각 시나리오의 `displayOrder`는 1, 2, 3이다.
- 모든 질문 원문과 캐릭터 ID가 비어 있지 않다.
- 캐릭터는 `chloe`, `marco`, `teddy` 중 하나다.
- 질문 ID가 중복되지 않는다.

snapshot에는 DB 접속 정보, 사용자 정보와 번역문을 넣지 않는다. 질문 원문은 생성 입력과 사람 검수에 필요하므로 포함한다.

## S3 객체 계약

기존 shared private content bucket의 다음 prefix를 사용한다.

```text
content/scenario-question-audio/{scenarioQuestionId}/{generationFingerprint}.mp3
```

`generationFingerprint`는 아래 정규화 JSON의 UTF-8 bytes에 대한 SHA-256 hex다.

```json
{
  "model": "deepgram/aura-2",
  "providerVoiceId": "<providerVoiceId>",
  "questionText": "<production question text>",
  "responseFormat": "mp3"
}
```

키에 `scenarioId`나 `displayOrder`를 넣지 않는다. 두 값은 표시·관계 정보이고 질문 자체의 안정 식별자는 `scenarioQuestionId`다. 질문 원문, model, voice 또는 포맷이 바뀌면 fingerprint가 달라져 새 객체가 생성된다.

업로드 metadata는 다음과 같다.

- `Content-Type: audio/mpeg`.
- `Cache-Control: public, max-age=31536000, immutable`.
- 사용자 정의 metadata `source-sha256`, `audio-sha256`, `model`, `voice`.

객체 업로드에는 `If-None-Match: *`를 사용한다. 이미 같은 key가 있으면 덮어쓰지 않고 원격 metadata와 checksum을 검증한다. 기존 객체를 교체하거나 삭제하지 않는다.

## manifest 계약

manifest는 schema version과 batch 공통 정보, 120개 asset 항목을 갖는다.

```json
{
  "schemaVersion": 1,
  "issue": "LAN-351",
  "source": {
    "environment": "production",
    "targetLocale": "EN",
    "baseLocale": "KR",
    "snapshotSha256": "<sha256>",
    "scenarioCount": 40,
    "questionCount": 120
  },
  "assets": [
    {
      "scenarioId": 1,
      "scenarioQuestionId": 1,
      "displayOrder": 1,
      "characterId": "chloe",
      "questionText": "<text>",
      "model": "deepgram/aura-2",
      "providerVoiceId": "aura-2-luna-en",
      "responseFormat": "mp3",
      "generationFingerprint": "<sha256>",
      "s3Key": "content/scenario-question-audio/1/<sha256>.mp3",
      "audioByteSize": 12345,
      "audioSha256": "<sha256>",
      "openRouterGenerationId": "<id>"
    }
  ]
}
```

로컬 manifest는 `manifests/scenario-question-audio/lan-351.json`에 커밋해 후속 BE·AI 작업의 입력 계약으로 사용한다. MP3 바이너리는 `/tmp/landit-lan-351-audio/mp3/`에만 두고 저장소에 커밋하지 않는다. 최종 manifest도 내용 기반 SHA-256 key로 S3에 업로드해 덮어쓰지 않는다.

```text
content/scenario-question-audio/manifests/{manifestSha256}.json
```

런타임은 이슈 번호로 key를 조합하지 않는다. 후속 작업은 커밋된 manifest의 `s3Key`를 DB나 애플리케이션 계약으로 옮긴다.

## 생성 흐름

1. production snapshot을 만들고 구조와 source SHA-256을 검증한다.
2. Chloe, Marco, Teddy별 질문을 UTF-8 원문 길이와 질문 ID로 정렬하고 중앙 항목 한 개를 대표 샘플로 선택한다.
3. 샘플 세 개를 MP3로 생성하고 HTTP 상태, content type, 파일 크기와 디코딩 가능 여부를 확인한다.
4. 사용자가 세 샘플을 듣고 voice와 발화 품질을 승인한다.
5. 승인 후 나머지 항목을 동시 작업 네 개로 생성한다.
6. 성공한 파일과 generation metadata를 작업 디렉터리에 남겨 재실행 시 재사용한다.
7. 전체 120개가 성공하면 manifest를 완성하고 전수 검증한다.
8. 사용자에게 총 파일 수, 캐릭터별 수, 총 bytes, source·audio digest와 S3 변경 목록을 보고한다.
9. 별도 업로드 승인 뒤 S3에 신규 객체만 올린다.
10. S3 조회 결과와 manifest를 다시 대조한다.

동시 작업 수는 네 개로 고정한다. `429`가 발생하면 새 작업 제출을 멈추고 해당 항목을 재시도한 뒤 계속한다. 실행 중 병렬도를 자동으로 올리거나 무제한 동시 호출을 사용하지 않는다.

## 재시도와 실패 처리

- `429`, `500`, `502`, `503`과 일시적 연결 실패만 최초 요청을 포함해 최대 네 번 시도한다. 재시도 간격은 1초, 2초, 4초에 0초 이상 1초 미만의 jitter를 더한다.
- 요청별 연결 timeout은 10초, 전체 timeout은 120초로 둔다.
- `400`, `401`, `402`, `404`는 입력, 인증, 잔액 또는 model·voice 계약 오류이므로 즉시 전체 배치를 중단한다.
- 응답이 성공이어도 `Content-Type`이 MP3가 아니거나 파일이 비어 있거나 디코딩되지 않으면 실패로 처리한다.
- 실패 응답 body를 MP3로 저장하지 않는다.
- 로그에는 질문 ID, 시도 횟수, HTTP 상태, OpenRouter generation ID와 오류 종류만 기록한다. API key와 전체 질문 원문은 로그에 반복하지 않는다.
- 하나라도 실패하면 manifest를 완료 상태로 만들지 않고 S3 업로드를 시작하지 않는다.
- 재실행 시 generation fingerprint와 검증된 로컬 파일이 일치하는 항목은 건너뛴다.

## 검증

### snapshot 검증

- 시나리오 40개, 질문 120개와 캐릭터별 9·24·87개를 확인한다.
- 질문 ID 중복, 빈 원문, 잘못된 순서와 미지원 캐릭터가 0개인지 확인한다.
- 생성 직전 production 재조회에서 snapshot SHA-256이 바뀌면 중단한다.

### MP3 검증

- 모든 HTTP 응답이 2xx인지 확인한다.
- 응답 `Content-Type`이 `audio/mpeg`인지 확인한다.
- 모든 파일이 0 bytes보다 크고 `file` 또는 동등한 검사에서 MP3로 식별되는지 확인한다.
- 현재 macOS 환경에서는 `afinfo`로 각 MP3가 열리고 유효한 duration을 갖는지 확인한다. 다른 환경에서는 동등한 decoder probe를 사용한다.
- manifest의 byte size와 SHA-256이 실제 파일과 일치하는지 확인한다.
- 캐릭터별 샘플은 자동 검증과 별도로 사람이 억양, 음색, 질문 누락·잘림과 비정상 침묵을 듣고 승인한다.

### S3 검증

- 업로드 전 모든 대상 key가 신규인지 확인하고 기존 객체가 있으면 덮어쓰지 않는다.
- 업로드 후 신규 MP3 120개와 manifest 한 개가 존재하는지 확인한다.
- 각 객체의 content type, cache control, custom metadata, content length를 manifest와 비교한다.
- 객체를 다시 내려받아 SHA-256을 대조하거나 S3 checksum을 사용할 수 있으면 해당 checksum을 대조한다.
- 기존 `content/*` 객체와 Terraform state에는 변경이 없어야 한다.

## 보안과 비용 경계

- OpenRouter key와 production DB credentials는 기존 환경변수 또는 SSM SecureString에서 프로세스 메모리로만 읽는다.
- secret 원문을 파일, manifest, git diff, 명령 출력과 로그에 남기지 않는다.
- DB 조회는 `SELECT`만 사용한다.
- TTS 생성은 과금되므로 샘플 3개 뒤 사람 승인을 거친다.
- 2026-08-25 OpenRouter 계정 잔액은 조회 시점 약 `$578.64`였으나, 생성 직전에 다시 확인한다.
- S3 업로드는 외부 상태 변경이므로 전체 로컬 검증 결과와 대상 목록을 보고한 뒤 별도 승인받는다.
- Terraform apply, S3 객체 삭제와 기존 key overwrite는 수행하지 않는다.

## 후속 런타임 계약

후속 BE·AI 작업은 manifest의 정확한 `s3Key`를 사용한다. `scenarioId`와 `displayOrder`로 key를 추측하지 않는다. 서버 측 오디오 결합은 고정 MP3와 맞장구 음성을 디코딩한 뒤 결합하고 최종 형식으로 한 번 인코딩해야 한다. MP3 byte stream을 단순 연결하는 방식은 계약으로 삼지 않는다.

shared bucket을 직접 읽는 컴포넌트에는 후속 IaC 변경으로 해당 prefix에 한정된 `s3:GetObject`만 부여한다. 이번 작업에서는 런타임 권한을 미리 추가하지 않는다.

## 배포와 롤백

이번 게시 작업은 신규 immutable 객체만 추가하므로 기존 런타임에 즉시 영향을 주지 않는다. 후속 BE·AI가 manifest의 key를 참조하기 전까지 게시 객체는 사용되지 않는다.

문제가 발견되면 후속 애플리케이션 참조를 이전 상태로 되돌린다. LAN-351 객체는 기존 key를 덮어쓰지 않으므로 데이터 롤백이 필요하지 않다. 객체 삭제는 참조 여부와 보존 정책을 확인한 별도 승인 작업으로만 수행한다.
