# Landit SSM Parameters

Landit runtime parameter 이름과 운영 규칙을 기록합니다. 실제 secret 값은 문서, Terraform 코드, git history에 남기지 않습니다.

## 기준

- AWS account는 `982529430654`입니다.
- AWS region은 `ap-northeast-2`입니다.
- 로컬 AWS profile은 `landit`입니다.
- development path는 `/landit/develop`입니다.
- production path는 `/landit/prod`입니다.
- secret 값은 Terraform state에 남기지 않기 위해 Terraform 밖에서 SSM Parameter Store에 작성합니다.
- DB 연결 URL은 Java JDBC용 `jdbc:postgresql://` 형식으로 저장합니다.
- DB 연결 URL에는 username과 password를 넣지 않고 `DB_USERNAME`, `DB_PASSWORD`를 별도로 사용합니다.
- DB 연결 URL에는 `sslmode=require`와 `prepareThreshold=0` query parameter를 포함합니다.
- 현재 받은 Supabase pooler URL은 session pooler 형태로 취급합니다.

## Parameter Registry

| Path pattern | Type | 용도 |
| --- | --- | --- |
| `/landit/{environment}/DB_URL` | `SecureString` | backend JDBC database connection URL |
| `/landit/{environment}/DB_USERNAME` | `SecureString` | backend database username |
| `/landit/{environment}/DB_PASSWORD` | `SecureString` | backend database password |
| `/landit/{environment}/LANDIT_PUSH_AUDIENCE_DB_URL` | `SecureString` | 관리자 대상 SQL용 JDBC URL, 인증정보 없이 session pooler 5432와 `sslmode=require` 사용 |
| `/landit/{environment}/LANDIT_PUSH_AUDIENCE_DB_USERNAME` | `SecureString` | 읽기 역할 `landit_push_reader.<project-ref>` |
| `/landit/{environment}/LANDIT_PUSH_AUDIENCE_DB_PASSWORD` | `SecureString` | 해당 환경 읽기 역할의 비밀번호 |
| `/landit/{environment}/LANDIT_CORS_ALLOWED_ORIGINS` | `String` | backend CORS allowed origins, comma-separated |
| `/landit/{environment}/LANDIT_AUTH_TOKEN_SECRET` | `SecureString` | backend 자체 token signing secret |
| `/landit/{environment}/LANDIT_AI_CLIENT_MODE` | `String` | backend AI client mode |
| `/landit/{environment}/LANDIT_AI_BASE_URL` | `String` | backend에서 호출하는 AI service base URL |
| `/landit/{environment}/LANDIT_MEMORY_WRITE_ENABLED` | `String` | backend 장기기억 저장 기능 사용 여부, 기본값 `false` |
| `/landit/{environment}/LANDIT_MEMORY_USE_ENABLED` | `String` | backend 프리톡 장기기억 검색 기능 사용 여부, 기본값 `false` |
| `/landit/develop/LANDIT_REVENUECAT_WEBHOOK_AUTHORIZATION` | `SecureString` | 개발 API의 RevenueCat 웹훅 Authorization 검증값 |
| `/landit/develop/LANDIT_SUBSCRIPTION_LAUNCHED_AT` | `String` | 개발 API의 유료 기능 제한 도입 시각, 오프셋을 포함한 ISO 8601 형식 |
| `/landit/{environment}/LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS` | `String` | backend access token 만료시간, 초 단위 |
| `/landit/{environment}/LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS` | `String` | backend refresh token 만료시간, 초 단위 |
| `/landit/{environment}/LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES` | `String` | Google OIDC audience allowlist |
| `/landit/{environment}/LANDIT_AUTH_OIDC_KAKAO_AUDIENCES` | `String` | Kakao OIDC audience allowlist |
| `/landit/{environment}/LANDIT_AUTH_OIDC_APPLE_AUDIENCES` | `String` | Apple OIDC audience allowlist |
| `/landit/{environment}/LANDIT_BE_SENTRY_DSN` | `SecureString` | backend Sentry DSN, ECS에서 `SENTRY_DSN`으로 주입 |
| `/landit/{environment}/LANDIT_AI_SENTRY_DSN` | `SecureString` | AI service Sentry DSN, ECS에서 `SENTRY_DSN`으로 주입 |
| `/landit/{environment}/LANDIT_GRAFANA_CLOUD_OTLP_HEADERS` | `SecureString` | Grafana Cloud OTLP 인증 header, BE와 AI에서 `OTEL_EXPORTER_OTLP_HEADERS`로 주입 |
| `/landit/{environment}/OPENROUTER_API_KEY` | `SecureString` | AI API provider key |
| `/landit/{environment}/LLM_PROVIDER` | `String` | LLM provider identifier |
| `/landit/{environment}/OPENROUTER_BASE_URL` | `String` | OpenRouter API base URL |
| `/landit/{environment}/OPENROUTER_MODEL` | `String` | 기본 OpenRouter model |
| `/landit/{environment}/MESSAGE_FEEDBACK_MODEL` | `String` | 메시지 피드백 생성 전용 OpenRouter model |
| `/landit/{environment}/MESSAGE_FEEDBACK_REVIEW_ENABLED` | `String` | 메시지 피드백 문구 검수 사용 여부, `true` 또는 `false` |
| `/landit/prod/LANDIT_SENTRY_RELAY_AUTH_TOKEN` | `SecureString` | legacy 이름을 유지한 Sentry App webhook HMAC signing secret |
| `/landit/prod/LANDIT_SENTRY_DISCORD_WEBHOOK_URL` | `SecureString` | `#alerts-sentry-prod` 전용 Discord webhook URL |

`{environment}`는 `develop` 또는 `prod`만 사용합니다.

## DB URL 형식

`DB_URL`은 아래 형식을 사용합니다. username과 password는 포함하지 않습니다.

```text
jdbc:postgresql://{host}:5432/postgres?sslmode=require&prepareThreshold=0
```

## 검증 명령

값 없이 이름, 타입, 버전만 확인합니다.

```bash
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 \
  aws ssm get-parameters-by-path \
  --path /landit \
  --recursive \
  --query 'Parameters[].{Name:Name,Type:Type,Version:Version}' \
  --output table
```

## 새 parameter 추가 절차

개발 API의 RevenueCat 인증값과 결제 도입 시각은 `environments/dev/templates/ec2-runtime-env.sh.tftpl`에서 SSM을 읽어 `/run/landit/api.env`에 주입합니다. 두 parameter를 먼저 준비하고 `aws_ssm_document.ec2_deploy` 변경을 plan·apply한 뒤 API를 재배포해야 기존 EC2 컨테이너에 반영됩니다. SSM 값만 저장하거나 컨테이너를 단순 재시작하면 새 환경변수가 주입되지 않습니다.

결제 장애 복구 시에는 컨테이너의 인증값 존재 여부를 값 노출 없이 확인하고, RevenueCat의 Sandbox 웹훅 전달 주소·Authorization 설정을 대조합니다. 실패한 결제 이벤트를 재전송한 뒤 구독 조회의 `premium=true`와 실제 기능 접근을 확인합니다. 스토어 결제 성공이나 API health만으로 복구 완료를 판단하지 않습니다.

관리자 푸시의 세 DB 값은 기존 `DB_*`와 별개다. develop에서는 EC2 API env, production에서는 ECS API의 secrets로 주입하며, Java API가 Push 소비도 담당하므로 AI Worker에는 주입하지 않는다. Scheduler의 `LANDIT_PUSH_SCHEDULER_GROUP`, `LANDIT_PUSH_SCHEDULER_QUEUE_ARN`, `LANDIT_PUSH_SCHEDULER_ROLE_ARN`은 Terraform 리소스 참조로 주입하며 별도 SSM 값은 만들지 않는다.

SSM parameter를 생성해도 ECS container environment에 자동으로 들어가지 않습니다. 애플리케이션이 새 값을 환경변수로 읽는다면 아래 절차를 함께 진행합니다.

1. `/landit/develop`, `/landit/prod`에 parameter를 생성합니다.
2. 이 문서의 Parameter Registry에 이름, 타입, 용도를 추가합니다.
3. API나 worker가 환경변수로 읽는 값이면 Terraform task definition의 `secrets` 목록에 같은 이름을 추가합니다.
4. `terraform fmt -recursive`, `terraform validate`, `terraform plan`으로 task definition 변경 범위를 확인합니다.
5. `terraform apply`로 새 task definition revision을 만들고 ECS service에 반영합니다.
6. `aws ecs describe-task-definition`에서 container `secrets`에 새 이름이 포함됐는지 확인합니다.
7. 관련 endpoint, health check, preflight, smoke test 중 실제 사용 경로로 검증합니다.

장기기억 V1 parameter인 `LANDIT_MEMORY_WRITE_ENABLED`와 `LANDIT_MEMORY_USE_ENABLED`는 이 저장소가 SSM 리소스를 소유하지 않으므로 Terraform으로 생성하지 않습니다. ECS API task definition은 두 이름을 읽도록 연결되어 있으며, 출시 전 `/landit/develop`과 `/landit/prod`에 두 parameter를 `false`로 선행 생성하고 이름·타입·버전만 확인합니다. 기능을 켤 때만 운영 승인 후 SSM 값을 변경하고 API를 새로 배포합니다.

기존 parameter의 값만 바꾸는 경우도 running task에는 자동 반영되지 않습니다. ECS secret은 container 시작 시점에 주입되므로, 값 변경 후에는 ECS service 새 deployment가 필요합니다.

## 운영 장기기억 USE 활성화와 복구

기존 SSM 값만 변경하므로 Terraform 코드 변경이나 apply는 필요하지 않습니다. 운영 반영 승인을 받은 뒤 아래 절차를 실행합니다. WRITE는 유지하며 API만 재배포합니다.

1. 운영 WRITE가 활성화돼 있고, API task definition의 `secrets`에 두 기억 parameter가 연결돼 있는지 확인합니다. 변경 전 USE parameter의 이름·타입·버전과 API의 task definition·실행 image digest를 기록합니다.
2. task definition이 가리키는 ECR tag의 digest와 현재 실행 image digest가 같은지 확인합니다. 다르면 아래 재배포를 진행하지 않고 배포할 이미지를 먼저 확정합니다. `latest` 재배포에 다른 코드가 섞이는 것을 방지하기 위한 확인입니다.
3. 다음 명령으로 USE를 켜고 새 API task에 반영합니다. 비밀 값은 다루지 않습니다.

```bash
(
  set -euo pipefail
  aws --profile landit --region ap-northeast-2 ssm put-parameter \
    --name /landit/prod/LANDIT_MEMORY_USE_ENABLED \
    --type String --value true --overwrite
  aws --profile landit --region ap-northeast-2 ecs update-service \
    --cluster prod-landit-cluster --service prod-landit-api \
    --force-new-deployment \
    --query 'service.deployments[].{id:id,status:status,rolloutState:rolloutState}'
  aws --profile landit --region ap-northeast-2 ecs wait services-stable \
    --cluster prod-landit-cluster --services prod-landit-api
)
```

4. SSM 버전 증가와 기대값 일치 여부를 확인합니다. 새 deployment가 PRIMARY·COMPLETED인지, running 수가 desired 수와 일치하는지, 새 task의 image digest가 변경 전과 같은지 확인합니다. waiter 성공만으로 새 deployment 성공을 단정하지 않습니다.
5. API health와 새 task의 오류 로그를 확인하고, 저장된 기억이 있는 계정의 실제 프리톡에서 검색 기록과 응답을 함께 검수합니다. 다른 사람의 기억이나 원문에 없는 사실을 말하는지 확인합니다. health 성공은 기능 검증이 아니며, `used`는 모델 자기보고와 후처리 기록으로 인과적으로 검증된 사용률이나 응답 품질을 뜻하지 않습니다.

기억 사용으로 잘못된 응답이 발생하면 위 `put-parameter`의 `--value true`를 `--value false`로 바꾸고 API 재배포·검증을 반복합니다. 배포가 실패해도 SSM 값은 자동 복구되지 않으므로 기대값을 다시 확인합니다. USE를 꺼도 WRITE와 기존 기억은 유지되며, 데이터 삭제는 이 절차에 포함하지 않습니다.

## 운영 규칙

- SSM 값은 shell history, CI log, git diff에 남지 않는 방식으로 갱신합니다.
- `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `LANDIT_AUTH_TOKEN_SECRET`, `LANDIT_BE_SENTRY_DSN`, `LANDIT_AI_SENTRY_DSN`, `LANDIT_GRAFANA_CLOUD_OTLP_HEADERS`, `LANDIT_SENTRY_RELAY_AUTH_TOKEN`, `LANDIT_SENTRY_DISCORD_WEBHOOK_URL`, `OPENROUTER_API_KEY`는 `SecureString`으로만 관리합니다.
- `LANDIT_CORS_ALLOWED_ORIGINS`, `LANDIT_AI_CLIENT_MODE`, `LANDIT_AI_BASE_URL`, `LANDIT_MEMORY_WRITE_ENABLED`, `LANDIT_MEMORY_USE_ENABLED`, `LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES`, `LANDIT_AUTH_OIDC_KAKAO_AUDIENCES`, `LANDIT_AUTH_OIDC_APPLE_AUDIENCES`, `LLM_PROVIDER`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`, `MESSAGE_FEEDBACK_MODEL`, `MESSAGE_FEEDBACK_REVIEW_ENABLED`은 secret이 아니므로 `String`으로 관리합니다.
- Terraform에서 secret 값을 직접 생성하거나 import하지 않습니다.
- 값 변경 후에는 값 자체가 아니라 parameter name, type, version만 검증 기록에 남깁니다.
- ECS task definition에 연결된 SSM 값은 task 재시작 또는 새 deployment 후에만 container environment에 반영됩니다.

LAN-462 예약 실패 보관용 `LANDIT_PUSH_SCHEDULER_DLQ_ARN`은 Terraform이 기존 환경별 Push DLQ ARN으로 직접 주입한다. 추가 SSM 비밀 값은 필요 없다.
