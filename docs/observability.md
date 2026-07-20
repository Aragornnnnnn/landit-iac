# Landit Observability

Landit은 Sentry로 애플리케이션 오류를 확인하고, Grafana Cloud에서 애플리케이션 지표와 CloudWatch Logs를 함께 조회합니다.

## 데이터 흐름

```text
BE, AI application metrics
  -> Grafana Cloud OTLP endpoint

BE, AI stdout
  -> CloudWatch Logs
  -> Amazon Data Firehose
  -> Grafana Cloud Logs
```

BE와 AI는 Grafana Cloud OTLP endpoint로 직접 지표를 전송합니다. Alloy는 로컬 버퍼링, 신호 가공, 다중 backend 전송이 필요해질 때 도입합니다.

Grafana Cloud CloudWatch scrape는 조직 SCP의 `tag:GetResources` 명시적 거부를 변경할 수 없어 사용하지 않습니다. 따라서 ALB TPS와 ECS CPU·memory는 현재 Grafana Cloud 조회 범위에서 제외합니다.

## Grafana 대시보드

Grafana Cloud stack의 표시 이름은 `landitobservability`입니다. 기존 stack slug는 유지되므로 접속 주소는 계속 `https://scarletmyrtle3008.grafana.net`입니다.

`Landit` folder에는 다음 dashboard를 둡니다.

- [Landit Overview](https://scarletmyrtle3008.grafana.net/d/landit-overview/landit-overview). BE·AI의 TPS, 5xx 오류율, 응답시간, 통합 전체 로그와 에러 로그를 확인합니다.
- [Landit BE](https://scarletmyrtle3008.grafana.net/d/landit-be/landit-be). BE endpoint 지표와 JVM heap, GC, thread, API 로그를 확인합니다.
- [Landit AI](https://scarletmyrtle3008.grafana.net/d/landit-ai/landit-ai). AI endpoint 지표와 process CPU·memory·thread, CPython GC, worker 로그를 확인합니다.

세 dashboard는 `환경` 변수에서 `prod`와 `develop`을 전환합니다. 기본값은 `prod`이며, 시간대는 브라우저 설정과 관계없이 한국 표준시 `Asia/Seoul`로 고정합니다. `로그 본문 검색`을 비워 두면 전체 로그를 표시합니다. BE 에러 로그와 에러 발생량은 `ERROR`, `FATAL` 레벨 줄만 표시합니다. 5xx 오류율과 에러 로그 발생량은 오류가 없을 때 `0`으로 표시하며, 원문 로그 패널은 조회 결과가 없으면 비어 있습니다. Java stack trace의 이어지는 줄은 레벨이 없어 `UNK`로 표시될 수 있으므로 전체 로그 패널에서 확인합니다.

Dashboard JSON은 `grafana/dashboards/`에서 관리합니다. 수정 후에는 유효 기간을 제한한 Grafana service account token을 환경변수로만 전달해 동기화합니다.

```bash
GRAFANA_URL=https://scarletmyrtle3008.grafana.net \
GRAFANA_SERVICE_ACCOUNT_TOKEN=<temporary-token> \
./scripts/sync-grafana-dashboards.sh
```

동기화가 끝나면 해당 token을 즉시 폐기합니다. Grafana dashboard 관리에는 Cloud Access Policy가 아닌 Grafana service account token이 필요합니다.

## 애플리케이션 OTLP 지표

dev/prod는 아래 OTLP endpoint로 지표 전송을 활성화합니다.

```hcl
grafana_otlp_enabled  = true
grafana_otlp_endpoint = "https://otlp-gateway-prod-ap-northeast-0.grafana.net/otlp"
```

인증 header는 Terraform 밖에서 아래 SSM `SecureString`에 작성합니다.

```text
/landit/develop/LANDIT_GRAFANA_CLOUD_OTLP_HEADERS
/landit/prod/LANDIT_GRAFANA_CLOUD_OTLP_HEADERS
```

BE와 AI task는 이 값을 `OTEL_EXPORTER_OTLP_HEADERS`로 주입합니다. Terraform 코드와 state에는 header 값이 저장되지 않습니다.

Basic 인증 username에는 OTLP stack instance ID `1721357`을 사용합니다. Prometheus service instance ID `3366938`은 OTLP gateway 인증 username으로 사용하지 않습니다.

BE는 30초 간격으로 OTLP metric export를 활성화하고 base endpoint에 `/v1/metrics`를 붙인 signal-specific endpoint를 사용합니다. AI는 base endpoint를 사용합니다. 두 서비스 모두 trace와 log exporter를 `none`으로 제한해 metrics만 OTLP로 전송합니다. 공통 resource attribute는 `service.namespace=landit`, `deployment.environment.name=develop|prod`이고, service name은 각각 `landit-be`, `landit-ai`입니다.

## CloudWatch Logs 전달

dev/prod는 아래 Grafana Cloud AWS Logs endpoint와 Secrets Manager ARN으로 로그 전송을 활성화합니다.

```hcl
grafana_logs_enabled    = true
grafana_logs_endpoint   = "https://aws-logs-prod-030.grafana.net/aws-logs/api/v1/push"
grafana_logs_secret_arn = "arn:aws:secretsmanager:ap-northeast-2:982529430654:secret:landit/grafana-cloud/logs-R3yL8N"
```

Secrets Manager secret 값은 Terraform 밖에서 아래 JSON 형식으로 작성합니다.

```json
{"api_key":"<Loki instance ID>:<logs write token>"}
```

Terraform은 secret ARN만 관리하고 Firehose가 실행 시점에 `secretsmanager:GetSecretValue`로 인증값을 읽습니다. `sensitive=true` 변수나 Terraform data source로 secret 값을 읽지 않습니다.

환경별 Firehose delivery stream 하나가 API와 AI CloudWatch log group을 함께 전달합니다. 전달 실패 데이터는 같은 환경의 application S3 bucket `grafana-logs-failed/` prefix에 GZIP 형식으로 저장합니다.

## 인증 정책과 rotation

Grafana Cloud access policy는 OTLP용 `metrics:write`와 Logs용 `logs:write`를 분리해 최소 권한으로 관리합니다. 현재 token에는 자동 만료가 없으므로 정기적으로 사용 여부를 확인하고 수동 rotation 및 폐기해야 합니다. 교체할 때는 SSM OTLP header와 Secrets Manager Logs secret을 각각 갱신하고, 새 ECS deployment와 Firehose 전송 성공을 확인한 뒤 이전 token을 폐기합니다.

## 검증

코드 변경 후 아래 정적 검증을 실행합니다.

```bash
terraform fmt -recursive -check
AWS_PROFILE=landit terraform -chdir=environments/dev validate
AWS_PROFILE=landit terraform -chdir=environments/prod validate
```

endpoint와 secret을 준비한 뒤 plan을 저장하고 예상 리소스만 변경되는지 확인합니다.

```bash
AWS_PROFILE=landit terraform -chdir=environments/dev plan -out=/tmp/lan122-dev.tfplan
terraform -chdir=environments/dev show -no-color /tmp/lan122-dev.tfplan

AWS_PROFILE=landit terraform -chdir=environments/prod plan -out=/tmp/lan122-prod.tfplan
terraform -chdir=environments/prod show -no-color /tmp/lan122-prod.tfplan
```

apply 후 Grafana Cloud에서 환경별 API·AI 로그를 확인합니다. BE·AI 변경 image를 배포한 뒤 JVM·GC·HTTP와 process·GC·HTTP 지표를 확인합니다. Firehose 실패 백업 prefix와 delivery 오류도 함께 확인합니다.

2026-07-13 기준 develop과 prod에서 BE HTTP·JVM GC·JVM memory, AI HTTP·CPython GC·process 지표를 모두 확인했습니다.
