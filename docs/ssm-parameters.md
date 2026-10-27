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
| `/landit/{environment}/LANDIT_AI_CONTENT_GENERATION_REQUEST_TIMEOUT` | `String` | backend가 콘텐츠 제작(LAN-690) AI 호출 한 번을 기다리는 시간. Duration 형식(`300s`). 코드 기본값 300초, landit-ai `CONTENT_GENERATION_TIMEOUT_SECONDS`보다 길어야 한다 |
| `/landit/{environment}/LANDIT_REVENUECAT_PROJECT_ID` | `String` | backend RevenueCat 프로젝트 ID |
| `/landit/{environment}/LANDIT_REVENUECAT_API_SECRET_KEY` | `SecureString` | backend RevenueCat v2 조회 키. |
| `/landit/{environment}/LANDIT_REVENUECAT_ENTITLEMENT_SECRET_KEY` | `SecureString` | LAN-659의 premium 부여·회수용 v1 Secret 키. 개발 EC2·운영 ECS API에만 주입하며 AI에는 전달하지 않는다. |
| `/landit/{environment}/LANDIT_AI_INTERNAL_TOKEN` | `SecureString` | BE 전용 AI 호출 토큰. 개발 optional 주입, 운영 BE→AI 순차 주입은 [배포 절차](deployment-safety.md)를 따른다. |
| `/landit/{environment}/LANDIT_MEMORY_WRITE_ENABLED` | `String` | backend 장기기억 저장 기능 사용 여부, 기본값 `false` |
| `/landit/{environment}/LANDIT_MEMORY_USE_ENABLED` | `String` | backend 프리톡 장기기억 검색 기능 사용 여부, 기본값 `false` |
| `/landit/{environment}/LANDIT_REVENUECAT_WEBHOOK_AUTHORIZATION` | `SecureString` | API의 RevenueCat 웹훅 Authorization 검증값, develop EC2 env와 prod ECS secrets로 주입 |
| `/landit/{environment}/LANDIT_SUBSCRIPTION_LAUNCHED_AT` | `String` | API의 유료 기능 제한 도입 시각, 오프셋을 포함한 ISO 8601 형식. develop EC2 env와 prod ECS secrets로 주입 |
| `/landit/{environment}/LANDIT_SUBSCRIPTION_FREE_EXPRESSION_TRIAL_SINCE` | `String` | 무료 사용자 표현 학습 1개 개방(LAN-704)의 기준 시각, 오프셋을 포함한 ISO 8601 형식(예 `2026-10-21T00:00:00+09:00`). 이 시각 이후 처음 완료한 오늘의 시나리오의 1번 표현이 체험 대상. 비어 있으면 체험이 꺼진 채 기존 잠금만 적용. develop EC2 env와 prod ECS secrets로 주입 |
| `/landit/{environment}/LANDIT_REWARD_ENABLED` | `String` | 환급 챌린지 적립 계산·조회 사용 여부, 기본값 `false`. develop EC2 env와 prod ECS API secrets로 주입한다. |
| `/landit/{environment}/LANDIT_REWARD_CAPTURE_ENABLED` | `String` | 환급 활성화 전 결제·학습 근거 사전 수집 여부, 기본값 `false`. develop EC2 env와 prod ECS API secrets로 주입한다. |
| `/landit/develop/LANDIT_REWARD_PRODUCTS_JSON` | `String` | 환급 대상 3·6개월 상품 JSON 배열(`appId`, `store`, `productId`, `months`). develop EC2 env에만 주입. 이름을 `LANDIT_REWARD_PRODUCTS`로 쓰면 Spring이 `landit.reward.products`(List)에도 바인딩해 API 기동이 실패한다. |
| `/landit/prod/LANDIT_REWARD_PRODUCTS` | `String` | 기존 운영 상품 JSON 경로를 유지하며 ECS에는 `LANDIT_REWARD_PRODUCTS_JSON`으로 매핑한다. bare 이름으로 주입하지 않는다. |
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
| `/landit/{environment}/FREE_TALK_CORRECTION_MODEL` | `String` | 스몰톡 턴 교정(고친 문장·이유) 전용 OpenRouter model. 2026-10-24 결정값 `openai/gpt-5.4`(LAN-759, 5개 모델 비교 결과). 기본 모델로 되돌리려면 파라미터를 지우거나 비우지 말고 `OPENROUTER_MODEL`과 같은 값으로 바꾼 뒤 재배포한다(task definition이 참조하므로 없으면 task가 시작하지 못함) |
| `/landit/{environment}/CONTENT_GENERATION_MODEL` | `String` | 콘텐츠 제작(LAN-690) 생성 OpenRouter model. 2026-10-18 결정값 `anthropic/claude-opus-5.5`(코드 기본값과 같음) |
| `/landit/{environment}/CONTENT_REVIEW_MODEL` | `String` | 콘텐츠 제작 독립 검수 model. 생성과 다른 계열이어야 한다. 결정값 `openai/gpt-5.6-terra` |
| `/landit/{environment}/CONTENT_GENERATION_TIMEOUT_SECONDS` | `String` | 콘텐츠 생성 호출 1회의 SDK 한도(초). 코드 기본값 `290`. BE `LANDIT_AI_CONTENT_GENERATION_REQUEST_TIMEOUT`보다 짧아야 한다 |
| `/landit/{environment}/OPENAI_API_KEY` | `SecureString` | 콘텐츠 에셋 생성(LAN-754) 이미지 전용 OpenAI API 키. OpenRouter에는 이미지 생성이 없어 따로 둔다. landit-ai에만 주입한다 |
| `/landit/{environment}/MESSAGE_FEEDBACK_REVIEW_ENABLED` | `String` | 메시지 피드백 문구 검수 사용 여부, `true` 또는 `false` |
| `/landit/{environment}/JEV_ENABLED` | `String` | Jev 사용 여부. develop·prod 모두 `false`. |
| `/landit/{environment}/JEV_ENABLED_WORKFLOWS` | `String` | JSON 배열 문자열. 양쪽 `["E1","E2","E3","E4","E7","E10","E13"]`. |
| `/landit/{environment}/JEV_MODEL` | `String` | `typesafe/jev-1.13`. |
| `/landit/{environment}/JEV_DECISIONS_URL` | `String` | `https://openrouter.ai/api/alpha/decisions`. |
| `/landit/{environment}/JEV_TIMEOUT_SECONDS` | `String` | `5`. |
| `/landit/{environment}/JEV_REQUEST_BUDGET_SECONDS` | `String` | `30`. |
| `/landit/{environment}/JEV_FALLBACK_MODEL` | `String` | 판단 보완 모델 `openai/gpt-5.4-mini`. |
| `/landit/{environment}/JEV_ADJUDICATOR_MODEL` | `String` | E2 보완 모델 `openai/gpt-5.4`. |
| `/landit/{environment}/CODE_SESSION_SUMMARY_ENABLED` | `String` | 양쪽 `false`. E14 세션 요약은 기존 LLM을 유지. |
| `/landit/prod/LANDIT_SENTRY_RELAY_AUTH_TOKEN` | `SecureString` | legacy 이름을 유지한 Sentry App webhook HMAC signing secret |
| `/landit/prod/LANDIT_SENTRY_DISCORD_WEBHOOK_URL` | `SecureString` | `#alerts-sentry-prod` 전용 Discord webhook URL |

`{environment}`는 `develop` 또는 `prod`만 사용합니다.

`LANDIT_SUBSCRIPTION_LAUNCHED_AT`은 SSM에 먼저 등록한 뒤 API에 연결합니다. 운영은 ECS task definition 반영 후 해당 리비전으로 API를 배포해야 하며, 이후 SSM 값만 변경해도 새 API task가 시작되어야 반영됩니다.

`LANDIT_SUBSCRIPTION_FREE_EXPRESSION_TRIAL_SINCE`(LAN-707)도 같은 순서를 따릅니다. ECS task definition `secrets`가 참조하는 parameter가 없으면 새 task가 시작하지 못하므로, **이 변경을 apply하기 전에 develop·prod 두 환경에 값을 먼저 `put-parameter`합니다.** 값은 BE(LAN-704)와 FE 게이트 수정이 모두 올라간 날의 0시(`+09:00`)로 정하며, 그 전에는 빈 문자열이 아니라 아직 오지 않은 미래 시각을 넣어 체험을 닫아 둘 수 있습니다. API는 서버 시작 때 한 번 읽고 기동 로그에 활성 여부를 남깁니다.

## 운영 환급 설정.

운영 API는 `reward_configuration_enabled=true`로 활성화·사전 수집 플래그와 상품 목록을 SSM에서 주입한다. SSM 값은 Terraform 밖에서 관리하며 AI Worker에는 전달하지 않는다. 상품 목록의 기존 SSM 이름은 `LANDIT_REWARD_PRODUCTS`지만 컨테이너 이름은 반드시 `LANDIT_REWARD_PRODUCTS_JSON`이어야 한다. bare 이름은 Spring의 `landit.reward.products` 목록 바인딩과 충돌한다.

운영 선반영 값은 `LANDIT_REWARD_ENABLED=true`, `LANDIT_REWARD_CAPTURE_ENABLED=false`다. BE는 enabled가 true이면 결제·학습 근거 수집도 수행하므로 capture를 함께 켤 필요가 없다. 세 파라미터를 먼저 준비하고 현재 이미지 digest를 보존한 Terraform plan·apply로 API를 재기동한다. 이후 BE 환급 버전의 정상 배포와 해당 DB 마이그레이션이 완료되면 별도 환경 설정 없이 활성화된다. 기존 구버전은 환급 설정을 사용하지 않는다.

BE 배포는 현재 서비스의 task definition 설정을 보존한다. 기능을 중지하려면 SSM `LANDIT_REWARD_ENABLED=false`로 변경하고 API를 새로 배포한다. 사전 수집도 중지하려면 `LANDIT_REWARD_CAPTURE_ENABLED=false`를 유지한다. SSM 변경은 실행 중 task에 자동 반영되지 않는다. 상품 4개 매핑, 실제 실행 revision·digest, ALB target health와 `/actuator/health`를 확인하며 실결제·학습 적립 검증은 BE 환급 버전 배포 후 별도로 수행한다.

## 프리톡 한도

| Path pattern | Type | 계정별 한도 |
| --- | --- | --- |
| `/landit/{environment}/LANDIT_FREE_TALK_SPEAKING_TIME_LIMIT_MS` | `String` | KST 하루 발화 시간 `7200000`ms, 120분 |
| `/landit/{environment}/LANDIT_FREE_TALK_DAILY_REQUEST_LIMIT` | `String` | KST 하루 생성 요청 `1000`회 |
| `/landit/{environment}/LANDIT_FREE_TALK_REQUESTS_PER_MINUTE_LIMIT` | `String` | 고정 1분 구간 생성 요청 `20`회 |

두 환경에 세 parameter를 먼저 등록한 뒤 개발 EC2 runtime env와 운영 ECS API `secrets`에 연결합니다. 값은 Terraform 밖에서 관리하며, AI 컨테이너에는 주입하지 않습니다. 개발은 `aws_ssm_document.ec2_deploy` 반영 후 API 배포가 필요하고, 운영은 task definition과 service 반영으로 새 API task가 시작되어야 합니다. 기존 값만 변경해도 API 재배포가 필요합니다.

운영 발화 시간 SSM 경로는 유지하되 컨테이너에는 `LANDIT_FREE_TALK_DAILY_SPEAKING_TIME_LIMIT_MS`라는 새 이름으로 주입합니다. 기존 운영 코드가 읽는 `LANDIT_FREE_TALK_SPEAKING_TIME_LIMIT_MS`는 운영 ECS에 주입하지 않습니다. 따라서 설정을 먼저 연결해도 구버전은 기본 1분을 유지하고, 새 이름을 읽는 BE LAN-478 배포 후 120분으로 전환됩니다. LAN-478은 개발 호환을 위해 기존 이름도 fallback으로 읽습니다. 일일·분당 요청 수 제한 역시 LAN-478 코드 배포 후 적용됩니다.

## 프리톡 컨텍스트 요약

| Path pattern | Type | 값 |
| --- | --- | --- |
| `/landit/{environment}/LANDIT_FREE_TALK_CONTEXT_ENABLED` | `String` | `true`이면 새 세션에 요약 정책 적용, `false`이면 전체 원문 경로 유지. |

`{environment}`는 `develop` 또는 `prod`입니다. 사용자 허용 목록 없이 BE의 단일 활성화 설정으로 제어합니다. 값은 Terraform 밖에서 사용자가 등록·변경하며 이 연결 변경은 기존 ON/OFF 값을 변경하지 않습니다.

SSM 파라미터는 IaC 반영과 다음 배포 전에 등록해야 합니다. 개발은 EC2 배포 SSM 문서 반영 후 컨테이너 재배포, 운영은 ECS task definition 반영 후 새 task 기동이 필요합니다. SSM 값 변경만으로 실행 중인 서버 설정은 바뀌지 않습니다. 연결 후에는 파라미터가 없으면 개발 env 갱신 또는 운영 task 시작이 실패합니다.

활성화 전 AI 요약 계약과 사용자 허용 목록을 제거한 BE 코드가 배포되어 있어야 합니다. 이미 시작된 세션에 요약 정책을 소급 생성하지 않습니다.

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

## 배포 보호 설정.

AI 토큰은 기본 공존 단계에서는 생략한다. BE가 먼저 헤더를 보내는지 확인한 뒤 AI 검증을 활성화한다. 운영 토큰 주입과 샌드박스 반영 입력, 구 캐시 전환, 고정 이미지 plan·롤백 절차는 [배포 중 학습 보존](deployment-safety.md)을 따른다. 샌드박스 반영은 비밀 값이 아니므로 SSM을 새로 만들지 않고 Terraform environment로 전달한다.

## 새 parameter 추가 절차

개발 API의 RevenueCat 인증값과 결제 도입 시각은 `environments/dev/templates/ec2-runtime-env.sh.tftpl`에서 SSM을 읽어 `/run/landit/api.env`에 주입합니다. 두 parameter를 먼저 준비하고 `aws_ssm_document.ec2_deploy` 변경을 plan·apply한 뒤 API를 재배포해야 기존 EC2 컨테이너에 반영됩니다. SSM 값만 저장하거나 컨테이너를 단순 재시작하면 새 환경변수가 주입되지 않습니다.

운영 API는 ECS task definition의 `secrets`로 `/landit/prod/LANDIT_REVENUECAT_WEBHOOK_AUTHORIZATION`만 연결합니다. 운영 반영 전에 RevenueCat 운영 웹훅의 Authorization과 같은 값을 해당 `SecureString`에 등록해야 합니다. parameter가 없으면 새 ECS task가 시작하지 못합니다. 운영 `LANDIT_SUBSCRIPTION_LAUNCHED_AT`은 연결하지 않으며, 결제 도입 시각은 추후 별도로 결정합니다.

운영 연결 코드를 병합해도 현재 task에는 적용되지 않습니다. 운영 반영 시 SSM 등록 후 Terraform plan·apply가 필요하며, ECS service가 새 task definition을 사용하면서 배포가 시작됩니다. 이 apply는 운영 배포 일정에 맞춰 실행합니다.

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

재배포를 사용자가 별도로 수행할 때는 SSM 참조를 추가한 ECS revision만 먼저 등록할 수 있습니다. 이 경우 배포 시 해당 revision을 명시해야 합니다. 현재 서비스 revision을 복사하는 배포 스크립트나 force deployment는 미적용 revision의 새 참조를 자동으로 가져오지 않습니다. develop EC2는 `/opt/landit/bin/runtime-env`의 API 목록에 이름을 추가하고 다음 배포 시 환경 파일을 다시 생성합니다.

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
- `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `LANDIT_AUTH_TOKEN_SECRET`, `LANDIT_BE_SENTRY_DSN`, `LANDIT_AI_SENTRY_DSN`, `LANDIT_GRAFANA_CLOUD_OTLP_HEADERS`, `LANDIT_REVENUECAT_WEBHOOK_AUTHORIZATION`, `LANDIT_AI_INTERNAL_TOKEN`, `LANDIT_SENTRY_RELAY_AUTH_TOKEN`, `LANDIT_SENTRY_DISCORD_WEBHOOK_URL`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`는 `SecureString`으로만 관리합니다.
- `LANDIT_CORS_ALLOWED_ORIGINS`, `LANDIT_AI_CLIENT_MODE`, `LANDIT_AI_BASE_URL`, `LANDIT_AI_CONTENT_GENERATION_REQUEST_TIMEOUT`, `CONTENT_GENERATION_MODEL`, `CONTENT_REVIEW_MODEL`, `CONTENT_GENERATION_TIMEOUT_SECONDS`, `LANDIT_SUBSCRIPTION_LAUNCHED_AT`, `LANDIT_SUBSCRIPTION_FREE_EXPRESSION_TRIAL_SINCE`, `LANDIT_MEMORY_WRITE_ENABLED`, `LANDIT_MEMORY_USE_ENABLED`, `LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES`, `LANDIT_AUTH_OIDC_KAKAO_AUDIENCES`, `LANDIT_AUTH_OIDC_APPLE_AUDIENCES`, `LLM_PROVIDER`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`, `MESSAGE_FEEDBACK_MODEL`, `FREE_TALK_CORRECTION_MODEL`, `MESSAGE_FEEDBACK_REVIEW_ENABLED`은 secret이 아니므로 `String`으로 관리합니다.
- Terraform에서 secret 값을 직접 생성하거나 import하지 않습니다.
- 값 변경 후에는 값 자체가 아니라 parameter name, type, version만 검증 기록에 남깁니다.
- ECS task definition에 연결된 SSM 값은 task 재시작 또는 새 deployment 후에만 container environment에 반영됩니다.

## 콘텐츠 제작 모델·한도 주입 (LAN-702)

- `CONTENT_GENERATION_MODEL`, `CONTENT_REVIEW_MODEL`, `CONTENT_GENERATION_TIMEOUT_SECONDS`(landit-ai)와 `LANDIT_AI_CONTENT_GENERATION_REQUEST_TIMEOUT`(API)은 ECS task definition의 `secrets`로 주입한다. task definition이 참조하는 SSM 값이 없으면 task가 시작하지 못하므로, **이 변경을 apply하기 전에 develop·prod 두 환경에 네 값을 먼저 `put-parameter`한다.** 네 값 모두 코드 기본값(`anthropic/claude-opus-5.5`, `openai/gpt-5.6-terra`, `290`, `300s`)과 같게 넣는다.
- 모델을 바꿀 때는 SSM 값만 바꾸고 task를 재시작한다. 두 timeout은 landit-ai 쪽이 API 쪽보다 항상 짧아야 한다.

LAN-462 예약 실패 보관용 `LANDIT_PUSH_SCHEDULER_DLQ_ARN`은 Terraform이 기존 환경별 Push DLQ ARN으로 직접 주입한다. 추가 SSM 비밀 값은 필요 없다.

## 콘텐츠 에셋 생성 주입 (LAN-754)

- landit-ai(ECS `worker` 태스크, develop EC2 `ai.env`)에 `OPENAI_API_KEY`를 SSM `SecureString`으로 주입한다. task definition·EC2 runtime env가 이 값을 요구하므로 **apply·배포 전에 develop·prod 두 환경에 먼저 `put-parameter`한다.** develop EC2는 값이 없으면 runtime env 작성 단계에서 멈춘다.
- 콘텐츠 버킷 이름과 CloudFront URL(`CONTENT_BUCKET_NAME`, `CONTENT_CLOUDFRONT_URL`)은 API와 같은 Terraform 값으로 landit-ai에도 환경 변수로 주입한다. 추가 SSM 값은 없다.
- 이미지 모델·등급, TTS 모델, 청취 판정 모델(`CONTENT_IMAGE_MODEL`, `CONTENT_IMAGE_*_QUALITY`, `CONTENT_TTS_MODEL`, `CONTENT_AUDIO_QA_MODEL`)은 landit-ai 코드 기본값(`gpt-image-1-mini`, 썸네일·대표 medium·예문 low, `deepgram/aura-2`, `google/gemini-3.5-flash`)을 쓰고 Terraform으로 주입하지 않는다. Day 1개 실측 뒤 바꿔야 하면 그때 SSM `String`과 task definition `secrets`를 함께 추가한다.
- IAM: landit-ai 태스크 롤(prod)과 EC2 인스턴스 롤(develop)에 콘텐츠 버킷의 `content/scenarios/*`, `content/writing-expressions/*`, `content/scenario-question-audio/*`, `content/expression-pronunciation-audio/*` 쓰기와, 단어 음성 공용 풀 HEAD가 404로 보이도록 `content/expression-pronunciation-audio/*` 접두어 `ListBucket`을 준다. API 태스크 롤에는 교체 업로드 복사용으로 `content/scenarios/*`, `content/writing-expressions/*` 쓰기와, 없는 원본이 404로 보이도록 `content/inbox/*` 접두어 `ListBucket`을 준다. 담당자 업로드 `content/inbox/*` 쓰기는 그대로 API만 갖는다.

## Jev 설정 주입 (LAN-530)

위 9개 String parameter를 Terraform 밖에서 먼저 등록한 뒤 AI에만 주입합니다. API 키는 기존 `OPENROUTER_API_KEY`를 재사용합니다. 두 보완 모델은 AI가 별도로 읽으므로 둘 다 등록합니다. E14는 양쪽 모두 끄고 기존 LLM 세션 요약을 유지합니다.

- develop: 사용자 결정에 따라 E1을 포함한 7개 작업 목록을 저장하되 `JEV_ENABLED=false`로 둡니다. 이후 켜기 전에 BE가 `NO_MATCH`와 빈 추천 목록을 정상 완료로 처리하는 배포와 LAN-530 AI 이미지 배포를 확인합니다.
- prod: 7개 작업 목록을 저장하되 `JEV_ENABLED=false`로 유지합니다.
- 개발 EC2는 user-data 변경을 무시하므로 템플릿 수정만으로 기존 인스턴스가 갱신되지 않습니다. `aws_ssm_document.ec2_deploy`를 apply하고 해당 버전으로 현재 AI 이미지를 재배포하면 `/opt/landit/bin/runtime-env`와 `/run/landit/ai.env`가 갱신됩니다.
- 운영 ECS는 AI task definition `secrets`와 service를 apply해 현재 이미지 digest로 새 task를 시작합니다. 기존 BE task와 다른 설정은 보존합니다.
- 개발 instance role의 `ssm:GetParametersByPath`와 운영 execution role의 `ssm:GetParameters`는 이미 각 환경의 `/landit/{environment}/*`를 허용합니다. 새 API 키나 IAM 권한 확대는 필요하지 않습니다.
- SSM 값, 배포 매핑, 실행 중 환경변수의 JSON 배열, 서비스 health를 각각 확인합니다. LAN-530 이미지 포함 여부와 실제 `decision_call` 실행 증거는 설정 주입 검증과 별개입니다.

환경별 적용 기록은 [LAN-530 계획과 검증 결과](tasks/LAN-530/plan.md)에 남깁니다.
