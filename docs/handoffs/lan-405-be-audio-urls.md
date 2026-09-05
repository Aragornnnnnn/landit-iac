# LAN-405 BE 초보 질문 음성 URL 전달

## 사용 계약

BE는 [LAN-405 manifest](../../manifests/scenario-question-audio/lan-405.json)의 `assets[]`를 `scenarioQuestionId`로 조회하고, CloudFront base URL과 `s3Key`를 결합해 음원 URL을 구성합니다.

```text
audioUrl = https://d19azau1un4t7r.cloudfront.net/{asset.s3Key}
```

질문 ID나 시나리오 순서로 S3 key를 추측하지 않고 manifest의 `s3Key`를 그대로 사용합니다.

## 게시 결과

| 항목 | 값 |
| --- | --- |
| 질문 MP3 | 240개, 질문 ID 121~360 |
| 질문 그룹 | `LEVEL_1` 120개, `LEVEL_2_TO_3` 120개 |
| Chloe | 18개, `aura-2-luna-en` |
| Marco | 48개, `aura-2-hyperion-en` |
| Teddy | 174개, `aura-2-draco-en` |
| OpenRouter model | `deepgram/aura-2` |
| 총 재생 시간 | 1,037.376초 |
| 총 용량 | 6,224,256 bytes |
| Source SHA-256 | `4f1038e5fb6e30214040d71af9667b6869a2c3580e8b535e785c9a75918c7298` |
| Manifest SHA-256 | `1783b2faa66cd6711cdbaeb87cd82c80048f3ebb9e19c273c340aa45b0e0e7bb` |

게시된 manifest URL은 다음과 같습니다.

```text
https://d19azau1un4t7r.cloudfront.net/content/scenario-question-audio/manifests/1783b2faa66cd6711cdbaeb87cd82c80048f3ebb9e19c273c340aa45b0e0e7bb.json
```

## 검증 기록

- 최초 게시 검증일은 2026-09-02입니다.
- 품질 보정 검증일은 2026-09-06입니다.
- 질문 ID 124, 128, 142, 158, 245, 252, 298, 299를 기존 S3 key에 덮어쓰고 객체 metadata와 바이트 SHA-256을 보정 manifest와 대조했습니다.
- CloudFront invalidation `IBZOP5SXFZXKPRYWH6PNI3TVQE` 완료 후 같은 URL 8개의 바이트 SHA-256을 다시 대조했습니다.
- S3 재실행 결과는 `new=0`, `reused=241`, `conflicts=0`입니다.
- 원격 MP3 240개를 재다운로드해 크기와 SHA-256을 전수 대조했으며 불일치는 0개입니다.
- 원격 manifest와 로컬 canonical manifest의 바이트가 일치합니다.
- MP3는 `audio/mpeg`, manifest는 `application/json`으로 응답합니다.
- 세 음성의 대표 MP3가 Range 요청에 `206 Partial Content`로 응답합니다.
- 모든 객체의 캐시 정책은 `public, max-age=31536000, immutable`입니다.
- 이미 브라우저에 저장된 `immutable` 응답은 만료 전까지 이전 음성을 재생할 수 있습니다.
