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
| `/landit/{environment}/LANDIT_CORS_ALLOWED_ORIGINS` | `String` | backend CORS allowed origins, comma-separated |
| `/landit/{environment}/LANDIT_AUTH_TOKEN_SECRET` | `SecureString` | backend 자체 token signing secret |
| `/landit/{environment}/LANDIT_AI_CLIENT_MODE` | `String` | backend AI client mode |
| `/landit/{environment}/LANDIT_AI_BASE_URL` | `String` | backend에서 호출하는 AI service base URL |
| `/landit/{environment}/LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS` | `String` | backend access token 만료시간, 초 단위 |
| `/landit/{environment}/LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS` | `String` | backend refresh token 만료시간, 초 단위 |
| `/landit/{environment}/LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES` | `String` | Google OIDC audience allowlist |
| `/landit/{environment}/LANDIT_AUTH_OIDC_KAKAO_AUDIENCES` | `String` | Kakao OIDC audience allowlist |
| `/landit/{environment}/LANDIT_AUTH_OIDC_APPLE_AUDIENCES` | `String` | Apple OIDC audience allowlist |
| `/landit/{environment}/LANDIT_BE_SENTRY_DSN` | `SecureString` | backend Sentry DSN, ECS에서 `SENTRY_DSN`으로 주입 |
| `/landit/{environment}/LANDIT_AI_SENTRY_DSN` | `SecureString` | AI service Sentry DSN, ECS에서 `SENTRY_DSN`으로 주입 |
| `/landit/{environment}/OPENROUTER_API_KEY` | `SecureString` | AI API provider key |
| `/landit/{environment}/LLM_PROVIDER` | `String` | LLM provider identifier |
| `/landit/{environment}/OPENROUTER_BASE_URL` | `String` | OpenRouter API base URL |
| `/landit/{environment}/OPENROUTER_MODEL` | `String` | 기본 OpenRouter model |

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

SSM parameter를 생성해도 ECS container environment에 자동으로 들어가지 않습니다. 애플리케이션이 새 값을 환경변수로 읽는다면 아래 절차를 함께 진행합니다.

1. `/landit/develop`, `/landit/prod`에 parameter를 생성합니다.
2. 이 문서의 Parameter Registry에 이름, 타입, 용도를 추가합니다.
3. API나 worker가 환경변수로 읽는 값이면 Terraform task definition의 `secrets` 목록에 같은 이름을 추가합니다.
4. `terraform fmt -recursive`, `terraform validate`, `terraform plan`으로 task definition 변경 범위를 확인합니다.
5. `terraform apply`로 새 task definition revision을 만들고 ECS service에 반영합니다.
6. `aws ecs describe-task-definition`에서 container `secrets`에 새 이름이 포함됐는지 확인합니다.
7. 관련 endpoint, health check, preflight, smoke test 중 실제 사용 경로로 검증합니다.

기존 parameter의 값만 바꾸는 경우도 running task에는 자동 반영되지 않습니다. ECS secret은 container 시작 시점에 주입되므로, 값 변경 후에는 ECS service 새 deployment가 필요합니다.

## 운영 규칙

- SSM 값은 shell history, CI log, git diff에 남지 않는 방식으로 갱신합니다.
- `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `LANDIT_AUTH_TOKEN_SECRET`, `LANDIT_BE_SENTRY_DSN`, `LANDIT_AI_SENTRY_DSN`, `OPENROUTER_API_KEY`는 `SecureString`으로만 관리합니다.
- `LANDIT_CORS_ALLOWED_ORIGINS`, `LANDIT_AI_CLIENT_MODE`, `LANDIT_AI_BASE_URL`, `LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES`, `LANDIT_AUTH_OIDC_KAKAO_AUDIENCES`, `LANDIT_AUTH_OIDC_APPLE_AUDIENCES`, `LLM_PROVIDER`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`은 secret이 아니므로 `String`으로 관리합니다.
- Terraform에서 secret 값을 직접 생성하거나 import하지 않습니다.
- 값 변경 후에는 값 자체가 아니라 parameter name, type, version만 검증 기록에 남깁니다.
- ECS task definition에 연결된 SSM 값은 task 재시작 또는 새 deployment 후에만 container environment에 반영됩니다.
