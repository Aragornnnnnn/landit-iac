# Landit SSM Parameters

Landit runtime parameter 이름과 운영 규칙을 기록합니다. 실제 secret 값은 문서, Terraform 코드, git history에 남기지 않습니다.

## 기준

- AWS account는 `982529430654`입니다.
- AWS region은 `ap-northeast-2`입니다.
- 로컬 AWS profile은 `landit`입니다.
- development path는 `/landit/develop`입니다.
- production path는 `/landit/prod`입니다.
- secret 값은 Terraform state에 남기지 않기 위해 Terraform 밖에서 SSM Parameter Store에 작성합니다.
- DB 연결 URL에는 `sslmode=require`와 `prepareThreshold=0` query parameter를 포함합니다.
- 현재 받은 Supabase pooler URL은 session pooler 형태로 취급합니다.

## Parameter Registry

| Path pattern | Type | 용도 |
| --- | --- | --- |
| `/landit/{environment}/DB_URL` | `SecureString` | backend database connection URL |
| `/landit/{environment}/DB_USERNAME` | `SecureString` | backend database username |
| `/landit/{environment}/DB_PASSWORD` | `SecureString` | backend database password |
| `/landit/{environment}/OPENROUTER_API_KEY` | `SecureString` | AI API provider key |
| `/landit/{environment}/LLM_PROVIDER` | `String` | LLM provider identifier |
| `/landit/{environment}/OPENROUTER_BASE_URL` | `String` | OpenRouter API base URL |
| `/landit/{environment}/OPENROUTER_MODEL` | `String` | 기본 OpenRouter model |

`{environment}`는 `develop` 또는 `prod`만 사용합니다.

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

## 운영 규칙

- SSM 값은 shell history, CI log, git diff에 남지 않는 방식으로 갱신합니다.
- `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `OPENROUTER_API_KEY`는 `SecureString`으로만 관리합니다.
- `LLM_PROVIDER`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`은 secret이 아니므로 `String`으로 관리합니다.
- Terraform에서 secret 값을 직접 생성하거나 import하지 않습니다.
- 값 변경 후에는 값 자체가 아니라 parameter name, type, version만 검증 기록에 남깁니다.
