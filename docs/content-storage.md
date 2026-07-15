# 콘텐츠 이미지 저장과 CloudFront 조회

시나리오 썸네일과 연습 예문 이미지는 환경과 무관한 공통 콘텐츠 S3 버킷에 저장하고 CloudFront로 조회합니다. 사용자 음성과 Grafana 실패 로그는 기존처럼 환경별 application bucket에 저장합니다.

## 저장 경로

콘텐츠 key에는 환경명과 사용자 원본 파일명을 넣지 않습니다. `assetId`는 UUID를 사용합니다.

```text
content/scenarios/{scenarioId}/thumbnail/{assetId}.{ext}
content/scenarios/{scenarioId}/expressions/{expressionId}/practice-examples/{assetId}.{ext}
```

사용자 음성은 환경별 application bucket의 아래 key를 사용합니다.

```text
user-content/{userId}/sessions/{sessionId}/messages/{messageId}/audio/{assetId}.{ext}
```

`grafana-logs-failed/`는 Firehose의 기존 실패 백업 prefix로 유지합니다.

## 조회와 DB 반영

콘텐츠 버킷은 public access를 차단합니다. CloudFront OAC만 `content/*`를 읽을 수 있고, 프론트는 API가 내려준 CloudFront URL을 직접 요청합니다. 백엔드는 콘텐츠 이미지를 S3에서 받아 프록시하지 않습니다.

공유 Terraform root의 `cloudfront_url` output을 base URL로 사용합니다. 예를 들어 아래 key의 URL은 다음과 같습니다.

```text
key: content/scenarios/101/thumbnail/{assetId}.webp
URL: https://{cloudFrontDomain}/content/scenarios/101/thumbnail/{assetId}.webp
```

운영자는 시나리오 썸네일 URL을 `scenario.thumbnail_url`에, 연습 예문 URL을 `practice_examples_payload[].imageUrl`에 저장합니다. develop과 prod가 별도 DB를 사용하면 각 환경에 같은 CloudFront URL을 반영합니다.

이번 구성은 CloudFront 기본 domain만 제공합니다. custom CDN domain, DNS record, ACM 인증서는 별도 작업으로 추가합니다.

## 업로드와 교체 절차

1. 새 UUID `assetId`와 지정된 콘텐츠 key를 만든다.
2. 운영자 전용 IAM 권한으로 공통 콘텐츠 버킷에 파일을 업로드한다. 업로드 권한은 이 Terraform root가 만들지 않는다.
3. 객체에 올바른 `Content-Type`과 `Cache-Control: public, max-age=31536000, immutable`을 설정한다.
4. CloudFront URL이 `200`으로 조회되는지 확인한다.
5. DB 참조 URL을 새 CloudFront URL로 갱신한다.
6. develop과 prod에서 새 URL 노출을 확인한다.
7. 이전 URL 참조가 모두 사라지고 최대 캐시 TTL이 지난 뒤 이전 객체를 삭제한다.

같은 key를 덮어쓰지 않으므로 파일 교체 시 CloudFront invalidation은 필요하지 않습니다.

## 범위

콘텐츠 이미지 업로드 API는 만들지 않습니다. 현재 backend는 DB에 저장된 `thumbnailUrl`과 `practice_examples_payload[].imageUrl`을 그대로 응답하므로 CloudFront URL을 저장하면 별도 조회 코드 변경 없이 사용할 수 있습니다.

사용자 음성 업로드·조회 구현은 이 Terraform 변경의 범위가 아닙니다. 해당 기능을 구현할 때 위 `user-content/` key 규칙을 사용합니다.
