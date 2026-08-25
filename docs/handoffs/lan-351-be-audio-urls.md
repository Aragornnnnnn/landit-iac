# LAN-351 BE 고정 질문 음성 URL 전달

## 결론

BE는 [LAN-351 manifest](../../manifests/scenario-question-audio/lan-351.json)의 `assets[]`를 `scenarioQuestionId`로 조회하고, 아래 CloudFront base URL과 `s3Key`를 결합해 고정 질문 MP3 URL을 얻습니다.

```text
CloudFront base URL: https://d19azau1un4t7r.cloudfront.net
audioUrl:            {CloudFront base URL}/{asset.s3Key}
```

120개 질문 URL을 별도 목록으로 복제하지 않습니다. 커밋된 manifest를 단일 기준으로 사용해야 질문, voice 또는 파일이 바뀌었을 때 URL 목록과 실제 객체가 어긋나지 않습니다.

## 게시 결과

| 항목 | 값 |
| --- | --- |
| 질문 MP3 | 120개 |
| Chloe | 9개, `aura-2-luna-en` |
| Marco | 24개, `aura-2-hyperion-en` |
| Teddy | 87개, `aura-2-draco-en` |
| OpenRouter model | `deepgram/aura-2` |
| 응답 형식 | MP3, `audio/mpeg` |
| 총 용량 | 4,915,152 bytes |
| Source SHA-256 | `bf534681837848ebb45644d2c7add05b023d4fd18880f3139f769017c14c5fce` |
| Manifest SHA-256 | `2e084d63e194f984f0160341889d3df7e610b9de99f8dc528ee3f95211874509` |

게시된 manifest URL은 다음과 같습니다.

```text
https://d19azau1un4t7r.cloudfront.net/content/scenario-question-audio/manifests/2e084d63e194f984f0160341889d3df7e610b9de99f8dc528ee3f95211874509.json
```

## Manifest 필드

BE에서 필요한 핵심 필드는 다음과 같습니다.

| 필드 | 용도 |
| --- | --- |
| `scenarioId` | 시나리오 식별 및 검증 |
| `scenarioQuestionId` | 질문 음성 조회의 기본 식별자 |
| `displayOrder` | 시나리오 내 질문 순서 |
| `characterId` | Chloe, Marco, Teddy 구분 |
| `s3Key` | 정확한 immutable 객체 key |
| `audioByteSize` | 다운로드 크기 검증 |
| `audioSha256` | MP3 바이트 무결성 검증 |
| `generationFingerprint` | 질문 원문, model, voice, 형식의 생성 버전 |

`scenarioId`와 `displayOrder`로 S3 key를 추측하지 않습니다. 항상 해당 `scenarioQuestionId`의 manifest `s3Key`를 사용합니다.

## URL 생성 예시

질문 ID 1의 manifest 항목은 다음 key를 가집니다.

```text
content/scenario-question-audio/1/4d8422c99edfb8fe16c06981ec87eac5ec99b727fd807ed70e5f18317f52878c.mp3
```

따라서 실제 URL은 다음과 같습니다.

```text
https://d19azau1un4t7r.cloudfront.net/content/scenario-question-audio/1/4d8422c99edfb8fe16c06981ec87eac5ec99b727fd807ed70e5f18317f52878c.mp3
```

Kotlin에서는 다음처럼 구성할 수 있습니다.

```kotlin
private const val SCENARIO_AUDIO_BASE_URL =
    "https://d19azau1un4t7r.cloudfront.net"

fun ScenarioQuestionAudioAsset.audioUrl(): String =
    "$SCENARIO_AUDIO_BASE_URL/$s3Key"

val audioByQuestionId: Map<Long, ScenarioQuestionAudioAsset> =
    manifest.assets.associateBy { it.scenarioQuestionId }
```

환경 변수로 관리한다면 기존 `CONTENT_CLOUDFRONT_URL`을 base URL로 사용하고, 값 끝의 `/`를 제거한 뒤 `s3Key`와 결합합니다.

## 런타임 전달 시 주의 사항

- FE가 고정 질문 MP3를 직접 재생한다면 위 CloudFront URL을 전달할 수 있습니다.
- BE 또는 AI가 맞장구 음성과 결합한다면 MP3 두 개의 바이트를 단순 연결하지 않습니다. 각각 디코딩한 뒤 결합하고 최종 음성을 한 번 인코딩합니다.
- 객체는 `Cache-Control: public, max-age=31536000, immutable`이므로 같은 key의 내용은 바뀌지 않습니다.
- 질문 원문, model, voice 또는 출력 형식이 바뀌면 새 generation fingerprint와 새 key를 사용합니다.
- 이번 LAN-351 작업에는 BE, AI 코드와 runtime IAM 변경이 포함되지 않았습니다.

## BE 전달용 요약

```text
LAN-351 고정 질문 MP3 120개 게시 완료.
- Mapping source: LAN-351 manifest assets[]
- Lookup key: scenarioQuestionId
- URL: https://d19azau1un4t7r.cloudfront.net/{s3Key}
- Manifest: https://d19azau1un4t7r.cloudfront.net/content/scenario-question-audio/manifests/2e084d63e194f984f0160341889d3df7e610b9de99f8dc528ee3f95211874509.json
- Do not compose keys from scenarioId/displayOrder.
- MP3 결합 시 바이트 단순 연결 금지. 디코딩 후 결합하고 재인코딩 필요.
```

## 검증 기록

- 검증일: 2026-08-25.
- CloudFront distribution: 활성 상태.
- 대표 MP3 URL: HTTP 200, `Content-Type: audio/mpeg`, `Content-Length: 62928`.
- Manifest URL: HTTP 200, `Content-Type: application/json`, `Content-Length: 79606`.
- Cache-Control: `public, max-age=31536000, immutable`.
- 원격 MP3 120개 재다운로드 SHA-256 불일치: 0개.
- 원격 manifest와 로컬 canonical manifest 바이트 일치: 확인.
