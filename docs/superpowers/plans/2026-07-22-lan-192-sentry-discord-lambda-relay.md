# LAN-192 Sentry Discord Lambda Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sentry prod BE·AI issue alert를 인증된 Lambda relay를 거쳐 `#alerts-sentry-prod` Discord webhook으로 전달한다.

**Architecture:** Sentry Internal Integration의 alert rule action이 prod Lambda Function URL을 호출한다. Lambda는 SSM `SecureString`의 relay token과 request header를 상수 시간 비교하고, prod payload만 Discord embed로 변환해 별도 SSM `SecureString` webhook URL로 전송한다.

**Tech Stack:** Terraform 1.6+, AWS provider 5.x/6.x, Archive provider 2.x, AWS Lambda Python 3.13, Python `unittest`, SSM Parameter Store, Sentry Internal Integration, Discord webhook.

## Global Constraints

- 대상은 `saynow/be-prod`, `saynow/ai-prod`와 `#alerts-sentry-prod`만 포함한다.
- Terraform apply와 실제 AWS 리소스 변경은 사용자 승인 뒤 실행한다.
- Discord webhook URL과 relay token은 Terraform variable, state, git, 문서와 명령 출력에 남기지 않는다.
- secret은 `/landit/prod/LANDIT_SENTRY_DISCORD_WEBHOOK_URL`, `/landit/prod/LANDIT_SENTRY_RELAY_AUTH_TOKEN` Standard `SecureString`으로 Terraform 밖에서 작성한다.
- Lambda는 API Gateway 없이 Function URL을 사용하고 timeout 5초, reserved concurrency 2, log retention 14일로 제한한다.
- Sentry 신규·회귀는 즉시, 같은 issue 5분 10회 이상은 알리고 rule별 재발송은 30분으로 제한한다.

---

### Task 1: Lambda relay 동작을 테스트 우선으로 구현

**Files:**
- Create: `environments/prod/lambda/sentry_discord_relay.py`
- Create: `environments/prod/lambda/tests/test_sentry_discord_relay.py`

**Interfaces:**
- Consumes: Function URL v2 event, `X-Landit-Sentry-Token`, SSM parameter names in environment variables.
- Produces: `lambda_handler(event, context) -> dict`, Discord webhook POST payload.

- [ ] **Step 1: 인증 실패 테스트를 작성한다.**

```python
def test_lambda_handler_rejects_invalid_token(self):
    relay.get_secret = lambda name: "expected-token"
    event = self.valid_event(token="wrong-token")
    self.assertEqual(401, relay.lambda_handler(event, None)["statusCode"])
```

- [ ] **Step 2: non-prod 제외 테스트를 작성한다.**

```python
def test_lambda_handler_skips_non_prod_event(self):
    relay.get_secret = lambda name: "expected-token"
    relay.send_discord = Mock()
    event = self.valid_event(token="expected-token", environment="develop")
    self.assertEqual(204, relay.lambda_handler(event, None)["statusCode"])
    relay.send_discord.assert_not_called()
```

- [ ] **Step 3: Discord 변환 테스트를 작성한다.**

```python
def test_lambda_handler_sends_prod_alert(self):
    relay.get_secret = lambda name: {
        "auth-param": "expected-token",
        "discord-param": "https://discord.example/webhook",
    }[name]
    relay.send_discord = Mock()
    response = relay.lambda_handler(self.valid_event(token="expected-token"), None)
    self.assertEqual(204, response["statusCode"])
    payload = relay.send_discord.call_args.args[1]
    self.assertIn("[PROD]", payload["embeds"][0]["title"])
    self.assertEqual("https://sentry.example/issues/1", payload["embeds"][0]["url"])
```

- [ ] **Step 4: 테스트가 기능 부재로 실패하는지 확인한다.**

Run: `python3 -m unittest discover -s environments/prod/lambda/tests -v`

Expected: `ImportError` 또는 `ModuleNotFoundError`로 relay 구현이 없어서 실패한다.

- [ ] **Step 5: 최소 handler를 구현한다.**

```python
def lambda_handler(event, context):
    body = decode_body(event)
    headers = normalize_headers(event.get("headers") or {})
    expected = get_secret(os.environ["AUTH_TOKEN_PARAMETER_NAME"])
    if not hmac.compare_digest(headers.get("x-landit-sentry-token", ""), expected):
        return response(401)
    payload = json.loads(body)
    if extract_environment(payload) not in (None, "prod"):
        return response(204)
    webhook_url = get_secret(os.environ["DISCORD_WEBHOOK_PARAMETER_NAME"])
    send_discord(webhook_url, build_discord_payload(payload))
    return response(204)
```

- [ ] **Step 6: 전체 Lambda 테스트를 통과시킨다.**

Run: `python3 -m unittest discover -s environments/prod/lambda/tests -v`

Expected: 인증 실패, malformed JSON, non-prod 제외, prod 변환 테스트가 모두 `OK`다.

### Task 2: prod Terraform에 relay 리소스를 추가

**Files:**
- Create: `environments/prod/sentry-discord-relay.tf`
- Modify: `environments/prod/versions.tf`
- Modify: `environments/prod/outputs.tf`
- Modify: `environments/prod/.terraform.lock.hcl`

**Interfaces:**
- Consumes: Lambda source zip, 두 prod SSM parameter ARN.
- Produces: IAM role, Lambda, log group, Function URL, `sentry_discord_relay_function_url` output.

- [ ] **Step 1: Archive provider 제약을 추가한다.**

```hcl
archive = {
  source  = "hashicorp/archive"
  version = ">= 2.4, < 3.0"
}
```

- [ ] **Step 2: Lambda archive와 최소 IAM 리소스를 정의한다.**

```hcl
data "archive_file" "sentry_discord_relay" {
  type        = "zip"
  source_file = "${path.module}/lambda/sentry_discord_relay.py"
  output_path = "${path.root}/.terraform/sentry-discord-relay.zip"
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role_policy" "sentry_discord_relay_ssm" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.parameter_store_path}/LANDIT_SENTRY_RELAY_AUTH_TOKEN",
        "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.parameter_store_path}/LANDIT_SENTRY_DISCORD_WEBHOOK_URL",
      ]
    }]
  })
}
```

- [ ] **Step 3: Function URL과 제한값을 정의한다.**

```hcl
resource "aws_lambda_function" "sentry_discord_relay" {
  function_name                  = "${local.name_prefix}-sentry-discord-relay"
  runtime                        = "python3.13"
  handler                        = "sentry_discord_relay.lambda_handler"
  timeout                        = 5
  memory_size                    = 128
  reserved_concurrent_executions = 2
  filename                       = data.archive_file.sentry_discord_relay.output_path
  source_code_hash               = data.archive_file.sentry_discord_relay.output_base64sha256
}

resource "aws_lambda_function_url" "sentry_discord_relay" {
  function_name      = aws_lambda_function.sentry_discord_relay.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "sentry_discord_relay_url" {
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.sentry_discord_relay.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "sentry_discord_relay_invoke" {
  statement_id             = "AllowPublicInvokeViaFunctionUrl"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.sentry_discord_relay.function_name
  principal                = "*"
  invoked_via_function_url = true
}
```

- [ ] **Step 4: Terraform을 초기화하고 정적 검증한다.**

Run: `terraform -chdir=environments/prod init -backend=false`

Run: `terraform fmt -recursive -check`

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod validate`

Expected: 세 명령이 exit code `0`이다.

### Task 3: 운영 문서와 secret registry를 갱신

**Files:**
- Modify: `docs/ssm-parameters.md`
- Modify: `docs/observability.md`
- Modify: `docs/superpowers/specs/2026-07-22-prod-discord-alerting-design.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**
- Consumes: Terraform resource names과 Sentry rule 기준.
- Produces: secret-safe 운영 절차와 검증 기록.

- [ ] **Step 1: 두 prod 전용 SecureString을 registry에 추가한다.**

```markdown
| `/landit/prod/LANDIT_SENTRY_RELAY_AUTH_TOKEN` | `SecureString` | Sentry Internal Integration과 Lambda 사이의 고정 header 인증값 |
| `/landit/prod/LANDIT_SENTRY_DISCORD_WEBHOOK_URL` | `SecureString` | `#alerts-sentry-prod` 전용 Discord webhook URL |
```

- [ ] **Step 2: Lambda relay 흐름과 secret rotation 순서를 기록한다.**

```text
Sentry issue alert -> Internal Integration -> Lambda Function URL -> Discord webhook
```

Rotation은 새 Discord webhook 또는 relay token을 SSM과 Sentry에 반영하고 test alert를 확인한 뒤 기존 값을 폐기하는 순서로 고정한다.

- [ ] **Step 3: 문서의 직접 연동 가정을 Lambda relay 결정으로 교체한다.**

Expected: `rg -n "별도 중계 서비스를 만들지|Sentry와 Grafana가 Discord에 직접" docs checklist.md context-notes.md` 결과에 승인 전 가정이 남지 않는다.

### Task 4: plan 검증 후 적용 승인 요청

**Files:**
- Modify after verification: `checklist.md`
- Modify after verification: `context-notes.md`

**Interfaces:**
- Consumes: prod Terraform configuration and current AWS state.
- Produces: saved plan summary and exact apply scope.

- [ ] **Step 1: prod plan을 저장한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod plan -out=/tmp/lan192-prod.tfplan`

- [ ] **Step 2: plan에서 secret 값과 예상 밖 변경을 검사한다.**

Run: `terraform -chdir=environments/prod show -no-color /tmp/lan192-prod.tfplan`

Expected: Lambda relay, IAM, log group, Function URL, archive provider 관련 변경만 있고 secret 값은 없다.

- [ ] **Step 3: 사용자에게 exact plan summary와 예상 비용을 보고하고 apply 승인을 요청한다.**

Expected: 승인 전에는 `terraform apply`, SSM write, Sentry custom integration mutation을 실행하지 않는다.

### Task 5: 승인 후 AWS·Sentry·Discord를 연결하고 검증

**Files:**
- Modify after live verification: `checklist.md`
- Modify after live verification: `context-notes.md`

**Interfaces:**
- Consumes: approved Terraform plan, Discord webhook URL, generated relay token.
- Produces: live Function URL, Sentry Internal Integration, four prod alert rules, Discord receipt evidence.

- [ ] **Step 1: Discord에 `Sentry Prod` webhook을 `#alerts-sentry-prod`용으로 만든다.**

Expected: webhook URL은 화면 보호 필드나 `read -s` 입력으로만 취급하고 출력하지 않는다.

- [ ] **Step 2: secret 두 개를 prod SSM에 작성한다.**

```bash
read -rs 'lan192_discord_webhook?Discord webhook URL: '
read -rs 'lan192_relay_token?Relay token: '
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws ssm put-parameter --name /landit/prod/LANDIT_SENTRY_DISCORD_WEBHOOK_URL --type SecureString --value "$lan192_discord_webhook" --overwrite
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws ssm put-parameter --name /landit/prod/LANDIT_SENTRY_RELAY_AUTH_TOKEN --type SecureString --value "$lan192_relay_token" --overwrite
unset lan192_discord_webhook lan192_relay_token
```

- [ ] **Step 3: 승인된 plan을 적용하고 Lambda를 확인한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod apply /tmp/lan192-prod.tfplan`

Expected: apply 성공, Function URL 생성, Lambda state `Active`, log group retention 14일이다.

- [ ] **Step 4: Sentry Internal Integration을 alertable webhook으로 연결한다.**

Expected configuration: name `Landit Prod Discord Relay`, webhook URL은 Terraform output, custom header는 `X-Landit-Sentry-Token`, alert rule action enabled, 최소 `event:read` scope다.

- [ ] **Step 5: BE·AI alert rule을 구성한다.**

Expected: project별 신규·회귀 rule과 5분 10회 반복 rule 총 네 개, environment `prod`, frequency `30`, action은 `Landit Prod Discord Relay`다.

- [ ] **Step 6: 실제 수신과 차단 경로를 확인한다.**

Expected: prod test alert 한 건은 `#alerts-sentry-prod`에 도착하고, invalid token과 develop payload는 Lambda `401` 또는 `204`이며 Discord 메시지가 없다.

- [ ] **Step 7: 최종 상태를 기록하고 논리 단위로 커밋한다.**

Run: `git diff --check && git status --short`

Run: `git add <LAN-192 변경 파일>`

Run: `git commit -m "chore: Sentry 장애 알림 Lambda 중계를 구성한다"`

Expected: secret이 git diff에 없고 working tree가 clean이다.
