<!-- LAN-405 보정 이미지와 질문 음성의 캐시 우회 URL 전환 계약을 전달한다. -->
# LAN-405 보정 자산 URL 전환

## 범위

- 연습 예문 이미지 35개는 기존 parent path 아래 새 UUID WebP key를 사용합니다.
- 시나리오 질문 음성 14개는 `revisions/{audioSha256}.mp3` key를 사용합니다.
- 전체 old/new URL은 [보정 자산 manifest](../../manifests/content-replacements/lan-405-asset-url-refresh.json)를 기준으로 합니다.
- 기존 S3 객체와 `backups/2026-09-06/practice-image-replacements/pre-overwrite/` 백업은 삭제하지 않습니다.

## 게시 검증

- 이미지 35개는 `Content-Type: image/webp`, `Cache-Control: public, max-age=31536000, immutable`, AES256과 `image-sha256` metadata를 확인했습니다.
- 이미지 35개를 S3와 CloudFront에서 재다운로드해 SHA-256을 전수 대조했습니다.
- 음원 14개는 `Content-Type: audio/mpeg`, 같은 immutable cache 정책과 기존 character·voice metadata를 유지합니다.
- LAN-351·LAN-405 음원 manifest 전체 360개와 새 revision key를 검증했습니다.

## BE 적용

BE forward migration은 manifest의 old URL이 현재 DB 값과 정확히 일치하는지 먼저 확인한 뒤 아래 값을 한 트랜잭션에서 갱신합니다.

- `writing_expression.practice_examples_payload[].imageUrl`: 35개.
- `scenario_question_language_variant.audio_url`: 14개.

새 URL은 기존 URL과 다른 immutable key이므로 CloudFront invalidation이나 WebView cache 삭제가 필요하지 않습니다.
