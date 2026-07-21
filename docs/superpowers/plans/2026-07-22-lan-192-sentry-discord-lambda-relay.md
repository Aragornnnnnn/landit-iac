# LAN-192 prod 관측성과 Discord 장애 알림 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sentry prod 장애를 1초 안에 접수해 Discord로 비동기 전달하고, AI 로그 오분류를 제거하며, prod ALB 미매핑 요청을 access log와 WAF Count로 관찰한다.

**Architecture:** 기존 Sentry Lambda는 Function URL ingress와 자기 함수의 비동기 delivery 경로로 분리한다. Landit AI는 root·Uvicorn 로그에 logfmt `level` 필드를 기록하고 Grafana AI·Overview가 그 필드를 사용한다. prod app-platform module은 선택적인 ALB access log S3 bucket과 `Count` 전용 Web ACL을 제공한다.

**Tech Stack:** Terraform 1.6+, AWS provider, AWS Lambda Python 3.13, Python `unittest`, FastAPI·Uvicorn, Grafana Loki LogQL, S3, AWS WAFv2.

## Global Constraints

- issue와 branch는 `LAN-192`, `feat/LAN-192`를 사용한다.
- Sentry·Grafana·ALB·WAF의 변경 대상은 prod이며 develop 동작은 바꾸지 않는다.
- Discord webhook URL과 Sentry App signing secret은 Terraform variable, state, git, 문서와 명령 출력에 남기지 않는다.
- WAF rule은 모두 `Count`로 시작하고 이번 작업에서 `Block`으로 전환하지 않는다.
- AI의 기존 workflow message와 `WARNING` log level은 바꾸지 않는다.
- Terraform apply, Grafana dashboard 운영 반영, AI 배포는 검증 결과와 범위를 제시한 뒤 별도 승인받는다.
- IaC와 AI 변경은 같은 이슈를 사용하되 저장소별·논리 단위별 커밋으로 나눈다.

---

## File Map

### landit-iac

- Modify: `environments/prod/lambda/sentry_discord_relay.py` — Function URL ingress와 비동기 delivery를 분리한다.
- Modify: `environments/prod/lambda/tests/test_sentry_discord_relay.py` — dispatch, signature, environment, Discord 변환을 검증한다.
- Modify: `environments/prod/sentry-discord-relay.tf` — self invoke IAM, memory, timeout, async retry를 정의한다.
- Modify: `modules/app-platform/main.tf` — 선택적 ALB log bucket과 WAFv2 Web ACL을 정의한다.
- Modify: `modules/app-platform/variables.tf` — access log와 WAF enable, retention, rate limit 입력을 정의한다.
- Modify: `environments/prod/main.tf` — prod에서 access log와 WAF Count를 활성화한다.
- Modify: `grafana/dashboards/landit-ai.json` — AI error query를 `level` 필드 기반으로 변경한다.
- Modify: `grafana/dashboards/landit-overview.json` — BE와 AI error query를 분리한다.
- Create: `scripts/test-grafana-log-level-queries.sh` — dashboard LogQL 계약을 정적으로 검증한다.
- Modify: `docs/observability.md` — 비동기 relay, AI level, ALB log, WAF Count 운영 절차를 기록한다.
- Modify: `docs/ssm-parameters.md` — relay path가 signing secret을 저장한다는 의미를 명확히 한다.
- Modify: `checklist.md` — 실제 진행과 검증 결과를 반영한다.
- Modify: `context-notes.md` — 결정, plan, apply, 종단 검증 근거를 반영한다.

### landit-ai

- Create: `app/core/logging.py` — root·Uvicorn handler에 공통 logfmt formatter를 설정한다.
- Modify: `app/main.py` — 앱 초기화 전에 logging을 설정한다.
- Create: `tests/test_logging.py` — WARNING과 ERROR의 명시적 level 필드를 검증한다.
- Create: `docs/tasks/LAN-192/design.md` — 승인된 AI stdout level 계약을 기록한다.
- Create: `docs/tasks/LAN-192/plan.md` — 구현 순서와 검증 결과를 기록한다.

---

### Task 1: Sentry Lambda를 ingress와 비동기 delivery로 분리

**Files:**
- Modify: `environments/prod/lambda/tests/test_sentry_discord_relay.py`
- Modify: `environments/prod/lambda/sentry_discord_relay.py`
- Modify: `environments/prod/sentry-discord-relay.tf`

**Interfaces:**
- Consumes: Function URL v2 event, `Sentry-Hook-Signature`, Lambda context ARN, 두 SSM parameter name.
- Produces: `lambda_handler(event, context) -> dict`, internal event `{"relayMode":"delivery","bodyBase64":str,"signature":str}`.

- [x] **Step 1: ingress가 secret과 Discord를 읽지 않고 async dispatch하는 실패 테스트를 작성한다.**

```python
def test_ingress_dispatches_delivery_without_reading_secrets(self):
    event = self.valid_event()
    context = Mock(invoked_function_arn="arn:aws:lambda:region:account:function:relay")
    with (
        patch.object(relay, "dispatch_delivery") as dispatch_delivery,
        patch.object(relay, "get_secret") as get_secret,
        patch.object(relay, "send_discord") as send_discord,
    ):
        result = relay.lambda_handler(event, context)
    self.assertEqual(204, result["statusCode"])
    dispatch_delivery.assert_called_once()
    get_secret.assert_not_called()
    send_discord.assert_not_called()
```

- [x] **Step 2: internal delivery만 HMAC과 prod를 검증하는 실패 테스트를 작성한다.**

```python
def test_internal_delivery_verifies_signature_and_sends_prod(self):
    ingress = self.valid_event()
    event = {
        "relayMode": "delivery",
        "bodyBase64": base64.b64encode(ingress["body"].encode("utf-8")).decode("ascii"),
        "signature": ingress["headers"]["Sentry-Hook-Signature"],
    }
    with (
        patch.object(relay, "get_secret", side_effect=["expected-secret", "https://discord.example/webhook"]),
        patch.object(relay, "send_discord") as send_discord,
    ):
        result = relay.lambda_handler(event, None)
    self.assertEqual(204, result["statusCode"])
    send_discord.assert_called_once()
```

- [x] **Step 3: 기존 Lambda unit test를 실행해 새 계약이 실패하는지 확인한다.**

Run: `python3 -m unittest discover -s environments/prod/lambda/tests -v`

Expected: ingress가 동기 `get_secret`과 `send_discord`를 호출해 새 테스트가 실패한다.

- [x] **Step 4: ingress validation과 async dispatch를 최소 구현한다.**

```python
MAX_RAW_BODY_BYTES = 700_000
SIGNATURE_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")

def dispatch_delivery(body, signature, function_name):
    payload = json.dumps({
        "relayMode": "delivery",
        "bodyBase64": base64.b64encode(body.encode("utf-8")).decode("ascii"),
        "signature": signature,
    }).encode("utf-8")
    result = get_lambda_client().invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=payload,
    )
    if result["StatusCode"] != 202:
        raise RuntimeError("delivery dispatch was not accepted")

def handle_ingress(event, context):
    body = decode_body(event)
    signature = normalize_headers(event.get("headers") or {}).get(
        "sentry-hook-signature", ""
    )
    if len(body.encode("utf-8")) > MAX_RAW_BODY_BYTES:
        return response(413)
    if not SIGNATURE_PATTERN.fullmatch(signature):
        return response(401)
    dispatch_delivery(body, signature, context.invoked_function_arn)
    return response(204)
```

- [x] **Step 5: internal delivery handler를 구현하고 외부 Function URL event와 분리한다.**

```python
def is_delivery_event(event):
    return event.get("relayMode") == "delivery" and "requestContext" not in event

def lambda_handler(event, context):
    if is_delivery_event(event):
        return handle_delivery(event)
    return handle_ingress(event, context)
```

- [x] **Step 6: Terraform에 self invoke와 실행 한도를 반영한다.**

```hcl
statement {
  actions   = ["lambda:InvokeFunction"]
  resources = [aws_lambda_function.sentry_discord_relay.arn]
}

memory_size = 512
timeout     = 10

resource "aws_lambda_function_event_invoke_config" "sentry_discord_relay" {
  function_name                = aws_lambda_function.sentry_discord_relay.function_name
  maximum_event_age_in_seconds = 300
  maximum_retry_attempts       = 2
}
```

- [x] **Step 7: Lambda unit test와 Terraform 정적 검증을 실행한다.**

Run: `python3 -m unittest discover -s environments/prod/lambda/tests -v`

Run: `terraform fmt -recursive -check`

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod validate`

Expected: 모든 명령이 exit code `0`이다.

- [x] **Step 8: Lambda 변경을 커밋한다.**

```bash
git add environments/prod/lambda/sentry_discord_relay.py \
  environments/prod/lambda/tests/test_sentry_discord_relay.py \
  environments/prod/sentry-discord-relay.tf
git commit -m "fix: Sentry Discord 전달을 비동기로 분리한다"
```

### Task 2: AI stdout에 명시적인 level 필드를 추가

**Files:**
- Create: `app/core/logging.py`
- Modify: `app/main.py`
- Create: `tests/test_logging.py`
- Create: `docs/tasks/LAN-192/design.md`
- Create: `docs/tasks/LAN-192/plan.md`

**Interfaces:**
- Consumes: Python `logging` root logger와 Uvicorn handler.
- Produces: 첫 로그 줄 `level=<LEVEL> logger=<LOGGER> message=<MESSAGE>`.

- [x] **Step 1: WARNING과 ERROR 필드를 검증하는 실패 테스트를 작성한다.**

```python
def test_log_formatter_includes_explicit_level(self):
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_log_formatter())
    logger = logging.getLogger("landit.logging.test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.warning("reason=message_feedback_schema: Value error")
    self.assertIn("level=WARNING", stream.getvalue())
    self.assertNotIn("level=ERROR", stream.getvalue())
```

- [x] **Step 2: AI logging test를 실행해 formatter 부재로 실패하는지 확인한다.**

Run: `python -m unittest tests.test_logging -v`

Expected: `app.core.logging` 또는 `build_log_formatter`가 없어 실패한다.

- [x] **Step 3: 공통 formatter와 logging 설정을 구현한다.**

```python
# AI stdout 로그에 명시적인 level 필드를 설정한다.
import logging
import sys

LOG_FORMAT = "level=%(levelname)s logger=%(name)s message=%(message)s"

def build_log_formatter():
    return logging.Formatter(LOG_FORMAT)

def configure_logging():
    formatter = build_log_formatter()
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(logger_name).handlers:
            handler.setFormatter(formatter)
    root.setLevel(logging.INFO)
```

- [x] **Step 4: app 초기화 전에 logging을 설정한다.**

```python
from app.core.logging import configure_logging

def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    resolved_settings = settings or Settings()
```

- [x] **Step 5: 대상과 전체 AI 테스트를 실행한다.**

Run: `.venv/bin/python -m unittest tests.test_logging -v`

Run: `.venv/bin/python -m unittest discover -s tests -v`

Run: `.venv/bin/python -m compileall -q app tests`

Expected: 모든 테스트와 compileall이 exit code `0`이다.

- [x] **Step 6: AI 이슈 문서와 검증 기록을 작성하고 커밋한다.**

```bash
git add app/core/logging.py app/main.py tests/test_logging.py \
  docs/tasks/LAN-192/design.md docs/tasks/LAN-192/plan.md
git commit -m "fix: AI 로그에 명시적인 level 필드를 추가한다"
```

### Task 3: Grafana AI error query를 level 기반으로 변경

**Files:**
- Create: `scripts/test-grafana-log-level-queries.sh`
- Modify: `grafana/dashboards/landit-ai.json`
- Modify: `grafana/dashboards/landit-overview.json`

**Interfaces:**
- Consumes: AI logfmt `level` field와 기존 BE Spring log line.
- Produces: AI `ERROR|CRITICAL` 전용 LogQL과 서비스 선택을 유지하는 Overview query.

- [x] **Step 1: dashboard 계약을 검증하는 실패 스크립트를 작성한다.**

```bash
#!/usr/bin/env bash
# Grafana AI 에러 패널이 명시적인 level 필드만 사용하는지 검증한다.
set -euo pipefail

jq -e '[.panels[].targets[]?.expr] | any(contains("| logfmt | level=~\\\"ERROR|CRITICAL\\\""))' \
  grafana/dashboards/landit-ai.json >/dev/null
! rg -n '\(\?i\)\(error\|exception\|traceback\|critical\|fatal\)' \
  grafana/dashboards/landit-ai.json
jq -e '[.panels[] | select(.title == "에러 로그 발생량" or .title == "에러 로그") | .targets | length] | all(. == 2)' \
  grafana/dashboards/landit-overview.json >/dev/null
```

- [x] **Step 2: 계약 스크립트가 현재 broad regex 때문에 실패하는지 확인한다.**

Run: `bash scripts/test-grafana-log-level-queries.sh`

Expected: AI dashboard에 `logfmt` level query가 없어 exit code가 `0`이 아니다.

- [x] **Step 3: AI error count와 logs query를 변경한다.**

```logql
sum(count_over_time({project="landit",environment="$environment",aws_log_group="/landit/$environment/worker"} | logfmt | level=~"ERROR|CRITICAL" [$__interval])) or vector(0)
```

```logql
{project="landit",environment="$environment",aws_log_group="/landit/$environment/worker"} | logfmt | level=~"ERROR|CRITICAL"
```

- [x] **Step 4: Overview의 BE와 AI error target을 분리한다.**

```logql
{project="landit",environment="$environment",aws_log_group=~"/landit/$environment/(${service:raw})",aws_log_group="/landit/$environment/api"} |~ "\\s(ERROR|FATAL)\\s"
```

```logql
{project="landit",environment="$environment",aws_log_group=~"/landit/$environment/(${service:raw})",aws_log_group="/landit/$environment/worker"} | logfmt | level=~"ERROR|CRITICAL"
```

- [x] **Step 5: JSON과 dashboard 계약을 검증한다.**

Run: `jq empty grafana/dashboards/landit-ai.json grafana/dashboards/landit-overview.json`

Run: `bash scripts/test-grafana-log-level-queries.sh`

Expected: 두 명령이 exit code `0`이다.

- [x] **Step 6: dashboard 변경을 커밋한다.**

```bash
git add scripts/test-grafana-log-level-queries.sh \
  grafana/dashboards/landit-ai.json grafana/dashboards/landit-overview.json
git commit -m "fix: Grafana AI 에러 로그를 level로 분류한다"
```

### Task 4: prod ALB access log와 WAF Count를 추가

**Files:**
- Modify: `modules/app-platform/main.tf`
- Modify: `modules/app-platform/variables.tf`
- Modify: `environments/prod/main.tf`

**Interfaces:**
- Consumes: prod ALB ARN, AWS account ID, environment와 project name.
- Produces: 전용 S3 access log bucket, 30일 lifecycle, REGIONAL Web ACL, ALB association.

- [x] **Step 1: 현재 prod plan에 WAF와 ALB log 리소스가 없어 계약 검사가 실패하는지 확인한다.**

Run: `rg -n 'aws_wafv2_web_acl|access_logs|alb_access_log' modules/app-platform environments/prod`

Expected: access log와 WAF 리소스가 없어 필요한 계약을 충족하지 않는다.

- [x] **Step 2: module 입력값을 추가한다.**

```hcl
variable "alb_access_logs_enabled" {
  description = "Whether to store ALB access logs in a dedicated S3 bucket."
  type        = bool
  default     = false
}

variable "alb_access_log_retention_days" {
  description = "Days to retain ALB access log objects."
  type        = number
  default     = 30
}

variable "waf_count_enabled" {
  description = "Whether to associate a Count-only WAF Web ACL with the ALB."
  type        = bool
  default     = false
}

variable "waf_rate_limit" {
  description = "Requests per source IP per five minutes before WAF Count matches."
  type        = number
  default     = 2000
}
```

- [x] **Step 3: 전용 S3 bucket과 ALB access log를 추가한다.**

```hcl
resource "aws_s3_bucket" "alb_access_logs" {
  count  = var.alb_access_logs_enabled ? 1 : 0
  bucket = "${local.name_prefix}-alb-access-${data.aws_caller_identity.current.account_id}"
}

dynamic "access_logs" {
  for_each = var.alb_access_logs_enabled ? [1] : []

  content {
    bucket  = aws_s3_bucket.alb_access_logs[0].bucket
    prefix  = "alb"
    enabled = true
  }
}
```

Bucket public access block, SSE-S3, 30일 lifecycle, ALB log delivery service principal의 account prefix `PutObject` policy를 함께 정의한다. `aws_lb.api`는 bucket policy가 적용된 뒤 log delivery를 활성화하도록 dependency를 둔다.

- [x] **Step 4: Count-only Web ACL과 ALB association을 추가한다.**

```hcl
resource "aws_wafv2_web_acl" "alb" {
  count = var.waf_count_enabled ? 1 : 0
  name  = "${local.name_prefix}-alb-count"
  scope = "REGIONAL"

  default_action { allow {} }
}
```

Web ACL에는 `AWSManagedRulesCommonRuleSet`, `AWSManagedRulesAmazonIpReputationList`, `aggregate_key_type = "IP"`, `evaluation_window_sec = 300`, `limit = var.waf_rate_limit`인 rate rule을 추가한다. 두 managed rule은 `override_action { count {} }`, rate rule은 `action { count {} }`를 사용한다. 모든 rule과 Web ACL의 CloudWatch metric과 sampled request를 활성화한다.

- [x] **Step 5: prod만 기능을 활성화한다.**

```hcl
alb_access_logs_enabled        = true
alb_access_log_retention_days = 30
waf_count_enabled              = true
waf_rate_limit                 = 2000
```

- [x] **Step 6: Terraform format과 validate를 실행한다.**

Run: `terraform fmt -recursive`

Run: `terraform fmt -recursive -check`

Run: `AWS_PROFILE=landit terraform -chdir=environments/dev validate`

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod validate`

Expected: 모든 명령이 exit code `0`이다.

- [x] **Step 7: ALB·WAF 변경을 커밋한다.**

```bash
git add modules/app-platform/main.tf modules/app-platform/variables.tf \
  environments/prod/main.tf
git commit -m "feat: prod ALB 요청 관측과 WAF Count를 구성한다"
```

### Task 5: 문서·plan·운영 반영을 검증

**Files:**
- Modify: `docs/observability.md`
- Modify: `docs/ssm-parameters.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**
- Consumes: Tasks 1~4의 verified commit과 live configuration.
- Produces: saved prod Terraform plan, Grafana sync payload, 종단 검증 기록.

- [x] **Step 1: 운영 문서의 이전 가정을 교체한다.**

`docs/observability.md`에는 Sentry ingress·delivery 분리, `Sentry-Hook-Signature`, AI logfmt level, prod ALB S3 retention 30일, WAF Count 3개 rule, 7일 관찰 절차를 기록한다. `docs/ssm-parameters.md`에는 `/landit/prod/LANDIT_SENTRY_RELAY_AUTH_TOKEN`이 Sentry App signing secret을 저장하는 legacy-named path임을 기록한다.

- [x] **Step 2: 전체 정적 검증을 실행한다.**

Run: `python3 -m unittest discover -s environments/prod/lambda/tests -v`

Run: `jq empty grafana/dashboards/*.json`

Run: `bash scripts/test-grafana-log-level-queries.sh`

Run: `terraform fmt -recursive -check`

Run: `AWS_PROFILE=landit terraform -chdir=environments/dev validate`

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod validate`

Run: `git diff --check`

Expected: 모든 명령이 exit code `0`이다.

- [x] **Step 3: prod Terraform plan을 저장하고 exact scope를 검사한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod plan -out=/tmp/lan192-prod-observability.tfplan`

Run: `terraform -chdir=environments/prod show -json /tmp/lan192-prod-observability.tfplan | jq '.resource_changes[] | select(.change.actions != ["no-op"]) | {address, actions: .change.actions}'`

Expected: Sentry Lambda update, self invoke IAM, async config, ALB access log S3 resources, ALB attribute, WAF Web ACL과 association만 포함한다. 삭제는 없다.

- [ ] **Step 4: 문서와 검증 기록을 커밋한다.**

```bash
git add docs/observability.md docs/ssm-parameters.md checklist.md context-notes.md \
  docs/superpowers/plans/2026-07-22-lan-192-sentry-discord-lambda-relay.md
git commit -m "docs: LAN-192 관측성 운영 절차를 반영한다"
```

- [x] **Step 5: 사용자에게 apply와 운영 반영 승인을 요청한다.**

승인 요청에는 Terraform plan add/change/destroy 수, exact resource address, WAF action이 전부 `Count`인 근거, Grafana dashboard 2개 변경, AI 배포 필요성을 포함한다.

- [ ] **Step 6: 승인 뒤 같은 saved plan을 apply하고 live 상태를 검증한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod apply /tmp/lan192-prod-observability.tfplan`

검증은 Lambda cold ingress 1초 이내 2xx, 비동기 Discord 도착, invalid signature·develop 미전달, S3 access log object 생성, Web ACL association, 세 rule의 Count action, post-apply `No changes`를 포함한다.

- [ ] **Step 7: AI 배포 뒤 Grafana dashboard를 동기화하고 렌더링을 검증한다.**

AI prod log에서 `level=WARNING`과 `level=ERROR`를 확인한 뒤 단기 Grafana service account token으로 `scripts/sync-grafana-dashboards.sh`를 실행한다. Landit AI·Overview에서 WARNING `Value error` 제외, 실제 ERROR 포함, query error 없음, service variable BE·AI 분리를 확인하고 token을 폐기한다.

- [ ] **Step 8: 완료 전 독립 리뷰와 최종 검증을 실행한다.**

Reviewer는 코드·Terraform diff, unit test, saved plan, live AWS·Grafana·Discord 근거를 구현자와 독립적으로 확인한다. criterion-linked blocker가 있으면 수정 후 관련 검증을 다시 실행한다.
