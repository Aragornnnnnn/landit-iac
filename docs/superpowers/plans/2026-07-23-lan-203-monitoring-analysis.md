# LAN-203 모니터링 분석 보강 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Landit 대시보드에서 사용자 증상과 BE 풀 병목을 함께 진단하고, ALB 4xx 원본과 배포 영향을 추적할 수 있게 한다.

**Architecture:** BE와 AI는 기존 Grafana Cloud OTLP 전송 경로를 유지하며 배포 버전을 metric attribute와 시작 로그에 추가한다. Grafana는 Tomcat·HikariCP 패널, 7일 전 비교선, Loki 배포 annotation을 사용한다. ALB access log는 S3 원본 위에 Athena partition projection table과 저장 쿼리를 구성한다.

**Tech Stack:** Spring Boot Actuator, Micrometer OTLP, OpenTelemetry Python, Grafana PromQL·LogQL, AWS Athena·Glue Data Catalog, Terraform.

## Global Constraints

- BE와 AI의 기존 OTLP·Loki 전송 경로를 변경하지 않는다.
- 사용자 ID, 세션 ID, 요청 본문, 원본 query string을 metric·log label에 추가하지 않는다.
- `service.version`은 Docker image에 주입한 Git commit SHA 또는 release tag만 사용한다.
- SQS CloudWatch 지표는 조직 SCP의 `tag:GetResources` 명시적 거부가 해소되기 전에는 Grafana에 수집하지 않는다.
- Terraform apply와 Grafana dashboard 실반영은 plan과 변경 내용을 확인한 뒤 별도 승인을 받는다.

---

### Task 1: BE 풀 지표와 배포 식별자

**Files:**
- Modify: `/private/tmp/landit-LAN-203/landit-be/src/test/java/com/landit/landitbe/ObservabilityIntegrationTests.java`
- Create: `/private/tmp/landit-LAN-203/landit-be/src/main/java/com/landit/landitbe/common/observability/DeploymentReadyLogger.java`
- Create: `/private/tmp/landit-LAN-203/landit-be/src/test/java/com/landit/landitbe/common/observability/DeploymentReadyLoggerTest.java`
- Modify: `/private/tmp/landit-LAN-203/landit-be/src/main/resources/application.yml`
- Modify: `/private/tmp/landit-LAN-203/landit-be/Dockerfile`
- Modify: `/private/tmp/landit-LAN-203/landit-be/.github/workflows/deploy-dev.yml`
- Modify: `/private/tmp/landit-LAN-203/landit-be/.github/workflows/deploy-prod.yml`

**Interfaces:**
- Consumes: `APP_VERSION`, `MeterRegistry`, Spring `ApplicationReadyEvent`.
- Produces: `service_version` metric label, `workflow=deployment_started serviceVersion=<version>` 시작 로그, Tomcat·HikariCP meters.

- [ ] **Step 1: 풀 지표와 시작 로그의 실패 테스트를 추가한다.**

```java
assertThat(meterRegistry.find("hikaricp.connections.pending").meters()).isNotEmpty();
assertThat(meterRegistry.find("tomcat.threads.busy").meters()).isNotEmpty();
```

- [ ] **Step 2: 관련 테스트가 새 요구사항 때문에 실패하는지 확인한다.**

Run: `./gradlew test --tests '*ObservabilityIntegrationTests' --tests '*DeploymentReadyLoggerTest'`

Expected: Tomcat meter 또는 새 logger 타입이 없어 실패한다.

- [ ] **Step 3: APP_VERSION tag와 배포 시작 로그를 구현한다.**

```yaml
management:
  metrics:
    tags:
      service.version: ${APP_VERSION:local}
```

```text
Landit BE 배포가 준비되었습니다. workflow=deployment_started serviceVersion=<version>
```

- [ ] **Step 4: Docker build argument로 배포 버전을 주입한다.**

```dockerfile
ARG APP_VERSION=local
ENV APP_VERSION=${APP_VERSION}
```

```bash
docker build --build-arg "APP_VERSION=${GITHUB_SHA}" ...
```

- [ ] **Step 5: BE 전체 검증을 실행한다.**

Run: `./gradlew check`

Expected: `BUILD SUCCESSFUL`.

### Task 2: AI 배포 식별자

**Files:**
- Modify: `/private/tmp/landit-LAN-203/landit-ai/app/core/config.py`
- Modify: `/private/tmp/landit-LAN-203/landit-ai/app/core/observability.py`
- Modify: `/private/tmp/landit-LAN-203/landit-ai/app/main.py`
- Modify: `/private/tmp/landit-LAN-203/landit-ai/tests/test_observability.py`
- Modify: `/private/tmp/landit-LAN-203/landit-ai/tests/test_app.py`
- Modify: `/private/tmp/landit-LAN-203/landit-ai/Dockerfile`
- Modify: `/private/tmp/landit-LAN-203/landit-ai/.github/workflows/deploy-dev-worker.yml`
- Modify: `/private/tmp/landit-LAN-203/landit-ai/.github/workflows/deploy-prod-worker.yml`

**Interfaces:**
- Consumes: `APP_VERSION`, FastAPI startup lifecycle, OpenTelemetry `Resource`.
- Produces: `service.version` resource attribute와 `workflow=deployment_started` 시작 로그.

- [ ] **Step 1: service.version과 시작 로그 실패 테스트를 추가한다.**

```python
self.assertEqual(resource_attributes["service.version"], "ai-v1.2.3")
```

- [ ] **Step 2: 새 테스트가 APP_VERSION 미지원으로 실패하는지 확인한다.**

Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest tests.test_observability tests.test_app`

Expected: `service.version` resource attribute가 없어 실패한다.

- [ ] **Step 3: Settings, Resource, startup logger를 구현한다.**

```python
"service.version": settings.app_version,
```

```text
Landit AI 배포가 준비되었습니다. workflow=deployment_started serviceVersion=<version>
```

- [ ] **Step 4: Docker build argument로 배포 버전을 주입한다.**

```dockerfile
ARG APP_VERSION=local
ENV APP_VERSION=${APP_VERSION}
```

- [ ] **Step 5: AI 전체 검증을 실행한다.**

Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`

Expected: 185개 이상의 테스트가 성공한다.

### Task 3: ALB access log Athena 분석 경로

**Files:**
- Modify: `/private/tmp/landit-LAN-203/landit-iac/modules/app-platform/main.tf`
- Modify: `/private/tmp/landit-LAN-203/landit-iac/modules/app-platform/outputs.tf`
- Modify: `/private/tmp/landit-LAN-203/landit-iac/docs/observability.md`
- Create: `/private/tmp/landit-LAN-203/landit-iac/scripts/test-athena-alb-contract.sh`

**Interfaces:**
- Consumes: prod ALB access log bucket의 `alb/AWSLogs/<account>/elasticloadbalancing/<region>/` 경로.
- Produces: Glue database·partition projection table, Athena workgroup·4xx named query, query result S3 prefix.

- [ ] **Step 1: Athena 계약 테스트를 작성하고 실패를 확인한다.**

Run: `bash scripts/test-athena-alb-contract.sh`

Expected: Athena·Glue 리소스가 없어 실패한다.

- [ ] **Step 2: AWS 공식 ALB RegexSerDe와 day partition projection table을 추가한다.**

```hcl
parameters = {
  "projection.enabled"          = "true"
  "projection.day.type"         = "date"
  "projection.day.range"        = "2026/07/01,NOW"
  "projection.day.format"       = "yyyy/MM/dd"
  "storage.location.template"   = "s3://.../${day}"
}
```

- [ ] **Step 3: 4xx 원인 분석 named query와 운영 문서를 추가한다.**

```sql
SELECT
  from_iso8601_timestamp(time) AT TIME ZONE 'Asia/Seoul' AS time_kst,
  client_ip,
  request_verb,
  request_url,
  elb_status_code,
  target_status_code,
  user_agent
FROM alb_access_logs
WHERE day BETWEEN date_format(current_date - INTERVAL '2' DAY, '%Y/%m/%d')
              AND date_format(current_date, '%Y/%m/%d')
  AND elb_status_code BETWEEN 400 AND 499
ORDER BY time_kst DESC
LIMIT 1000;
```

- [ ] **Step 4: Terraform과 계약 테스트를 검증한다.**

Run: `terraform fmt -recursive`

Run: `bash scripts/test-athena-alb-contract.sh`

Expected: 두 명령 모두 성공한다.

### Task 4: Grafana 진단 대시보드

**Files:**
- Modify: `/private/tmp/landit-LAN-203/landit-iac/grafana/dashboards/landit-overview.json`
- Modify: `/private/tmp/landit-LAN-203/landit-iac/grafana/dashboards/landit-be.json`
- Modify: `/private/tmp/landit-LAN-203/landit-iac/grafana/dashboards/landit-ai.json`
- Create: `/private/tmp/landit-LAN-203/landit-iac/scripts/test-grafana-analysis-panels.sh`
- Modify: `/private/tmp/landit-LAN-203/landit-iac/docs/observability.md`

**Interfaces:**
- Consumes: BE Tomcat·HikariCP metrics, BE·AI `service_version`, Loki `workflow=deployment_started`.
- Produces: 풀 포화도 패널, 현재와 7일 전 TPS·P99 비교선, 배포 annotation.

- [ ] **Step 1: 필수 panel·query·annotation 계약 테스트를 작성한다.**

Run: `bash scripts/test-grafana-analysis-panels.sh`

Expected: 신규 패널과 annotation이 없어 실패한다.

- [ ] **Step 2: BE Tomcat·HikariCP 패널을 추가한다.**

```promql
sum(hikaricp_connections_pending{service_name="landit-be",deployment_environment_name="$environment"})
```

```promql
sum(tomcat_threads_busy_threads{service_name="landit-be",deployment_environment_name="$environment"})
```

- [ ] **Step 3: Overview에 7일 전 TPS·P99 비교선을 추가한다.**

```promql
sum(rate(http_server_requests_milliseconds_count{service_name="landit-be",deployment_environment_name="$environment"}[$__rate_interval])) offset 7d
```

- [ ] **Step 4: Loki 배포 시작 로그를 dashboard annotation으로 추가한다.**

```logql
{project="landit",environment="$environment"} |= "workflow=deployment_started"
```

- [ ] **Step 5: 대시보드 JSON과 계약을 검증한다.**

Run: `jq empty grafana/dashboards/*.json`

Run: `bash scripts/test-grafana-analysis-panels.sh`

Expected: 두 명령 모두 성공한다.

### Task 5: 최종 검증과 적용 경계

**Files:**
- Review: 세 저장소의 `git diff`와 `git status --short`.

**Interfaces:**
- Consumes: Task 1부터 Task 4까지의 변경.
- Produces: 검증된 LAN-203 커밋과 사용자 승인용 Terraform plan.

- [ ] **Step 1: BE·AI 전체 테스트를 다시 실행한다.**

Run: `./gradlew check`

Run: `/Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`

- [ ] **Step 2: IaC 정적 검증과 환경별 plan을 실행한다.**

Run: `terraform fmt -check -recursive`

Run: `terraform validate`

Run: `terraform plan` for develop and production with the repository workflow.

- [ ] **Step 3: 시크릿 패턴과 의도하지 않은 변경을 확인한다.**

Run: `rg -n 'glc_[A-Za-z0-9_-]{20,}|glsa_[A-Za-z0-9_-]{20,}' grafana scripts docs modules`

Expected: 실제 token 값이 검색되지 않는다.

- [ ] **Step 4: 논리 단위로 커밋하고 apply·Grafana sync 전 승인을 요청한다.**

SQS Grafana 지표는 SCP가 해소되지 않았으므로 완료로 표시하지 않는다. Athena apply와 Grafana dashboard sync는 사용자 승인 전 실행하지 않는다.
