# LAN-184 푸시 알림 인프라 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EventBridge Scheduler가 Push 전용 SQS Standard Queue에 복습 리마인더 배치 메시지를 발행하고, 기존 API ECS Service 내부 Consumer가 메시지를 처리할 수 있는 최소 인프라와 운영 경보를 구성한다.

**Architecture:** 별도 Push Worker ECS Service나 Fargate Task는 만들지 않는다. 환경별 app-platform module이 Push 전용 main queue와 DLQ를 소유하고, Scheduler는 main queue에 배치 메시지를 발행하며 API Task Role만 main queue를 소비하고 Receipt 확인 메시지를 재발행한다. AI jobs 큐와 Push 큐의 리소스, 권한, 환경 변수를 분리한다.

**Tech Stack:** Terraform 1.6+, HashiCorp AWS Provider 5.x~6.x, Amazon SQS Standard Queue, Amazon EventBridge Scheduler, Amazon ECS Fargate, AWS IAM, Amazon CloudWatch.

## Global Constraints

- issue와 branch는 `LAN-184`, `feat/LAN-184`를 사용한다.
- Push 전용 ECS Service, Fargate Task, ECR repository, log group은 추가하지 않는다.
- 기존 `${local.name_prefix}-jobs` queue와 AI Worker Task Role은 변경하지 않는다.
- Push main queue와 DLQ는 환경별로 만들고 기존 jobs queue와 공유하지 않는다.
- API 컨테이너에 `SQS_PUSH_NOTIFICATIONS_QUEUE_URL`과 `LANDIT_NOTIFICATION_CONSUMER_ENABLED=true`를 일반 환경 변수로 주입한다.
- API Consumer 초기 동시성 `2`와 Receipt 확인 메시지의 `DelaySeconds=900`은 BE 애플리케이션 계약이며 Terraform이 별도 Consumer 설정으로 관리하지 않는다.
- Scheduler timezone은 `Asia/Seoul`, flexible time window는 `OFF`로 고정한다.
- 제품이 발송 시각을 확정하기 전에는 Scheduler expression을 설정하거나 Scheduler를 활성화하지 않는다.
- Terraform apply와 실제 AWS 리소스 변경은 plan 검토 후 별도 승인을 받아야 한다.

---

## File Map

- Create: `modules/app-platform/push-notifications.tf` — Push main queue, DLQ, Scheduler 실행 role, Scheduler, CloudWatch alarm을 정의한다.
- Modify: `modules/app-platform/main.tf` — API Task Role에 Push main queue 권한을 추가하고 API 컨테이너에 Queue URL과 Consumer enable 값을 주입한다.
- Modify: `modules/app-platform/variables.tf` — Queue visibility timeout, Scheduler expression·활성화, CloudWatch alarm action 입력을 정의한다.
- Modify: `modules/app-platform/outputs.tf` — Push main queue URL, DLQ URL, Scheduler ARN을 노출한다.
- Modify: `environments/dev/main.tf` — development의 Scheduler와 alarm 입력을 module에 전달한다.
- Modify: `environments/dev/variables.tf` — development는 Scheduler expression `null`, 활성화 `false`를 기본값으로 둔다.
- Modify: `environments/dev/outputs.tf` — development Push queue와 Scheduler 출력을 노출한다.
- Modify: `environments/prod/main.tf` — production의 Scheduler와 alarm 입력을 module에 전달한다.
- Modify: `environments/prod/variables.tf` — 제품 결정 전 Scheduler expression `null`, 활성화 `false`를 기본값으로 둔다.
- Modify: `environments/prod/outputs.tf` — production Push queue와 Scheduler 출력을 노출한다.
- Create: `scripts/test-push-notification-infra-contract.sh` — Queue 분리, 최소 IAM, API 환경 변수, Scheduler와 alarm 계약을 정적으로 검증한다.
- Create: `docs/push-notifications.md` — 메시지 계약, 운영 지표, 활성화와 DLQ 확인 절차를 기록한다.
- Modify: `checklist.md` — 구현, plan, apply, live 검증 상태를 추적한다.
- Modify: `context-notes.md` — 확정 결정, 미확정 값, BE 전달 계약과 검증 결과를 기록한다.

## BE 전달 계약

### Scheduler가 발행하는 메시지

EventBridge Scheduler target input은 다음 JSON을 사용한다.

```json
{
  "version": 1,
  "messageId": "<aws.scheduler.execution-id>",
  "messageType": "REVIEW_REMINDER_BATCH",
  "occurredAt": "<aws.scheduler.scheduled-time>",
  "payload": {}
}
```

- `messageId`는 UUID 형식을 보장하지 않으므로 BE는 비어 있지 않은 문자열로 처리한다.
- `occurredAt`은 Scheduler가 치환한 RFC 3339 예약 시각이다.
- Scheduler는 `payload.reviewDate`를 매일 `YYYY-MM-DD`로 포맷할 수 없다.
- BE는 `occurredAt`을 `Asia/Seoul`로 변환해 `reviewDate`를 계산한다.
- 실제 처리 시작 시각이 아니라 예약 시각을 사용해 지연 실행에서도 대상 날짜가 바뀌지 않게 한다.

### API가 같은 Queue에 발행하는 메시지

- `PUSH_RECEIPT_CHECK` 메시지의 payload와 `messageId` 생성은 BE가 소유한다.
- BE는 `SendMessage` 요청마다 `DelaySeconds=900`을 지정한다.
- SQS Standard Queue는 중복 전달과 순서 변경이 가능하므로 `REVIEW_REMINDER_BATCH`와 `PUSH_RECEIPT_CHECK` 모두 멱등해야 한다.
- 메시지 하나의 최대 크기는 256 KiB를 넘지 않게 Receipt 대상 ID를 분할한다.
- 처리 시간이 Queue visibility timeout을 넘을 수 있으면 BE가 `ChangeMessageVisibility`로 연장하거나 배치 크기를 줄인다.
- 지원하지 않는 version 또는 message type은 성공 삭제하지 않고 재시도 뒤 DLQ로 이동시킨다.

### 배포 순서

1. Queue와 DLQ, API IAM, API 환경 변수를 반영하되 Scheduler는 비활성 상태로 유지한다.
2. SQS Consumer가 포함된 BE를 배포하고 API task가 정상 기동하는지 확인한다.
3. development main queue에 수동 테스트 메시지를 보내 멱등 처리와 DLQ 이동을 검증한다.
4. 제품 발송 시각을 확정하고 production cron expression을 코드에 기록한다.
5. production Scheduler 활성화가 포함된 plan을 다시 검토하고 승인 뒤 apply한다.

---

### Task 1. Push Queue와 DLQ 구성

**Files:**
- Create: `scripts/test-push-notification-infra-contract.sh`
- Create: `modules/app-platform/push-notifications.tf`
- Modify: `modules/app-platform/variables.tf`

**Interfaces:**
- Consumes: `local.name_prefix`, `var.push_queue_visibility_timeout_seconds`.
- Produces: `aws_sqs_queue.push_notifications`, `aws_sqs_queue.push_notifications_dlq`.

- [ ] **Step 1: Queue 분리와 redrive 계약을 검사하는 실패 테스트를 작성한다.**

```bash
#!/usr/bin/env bash
# Push 알림 Terraform 리소스의 정적 계약을 검증한다.
set -euo pipefail

module_file="modules/app-platform/push-notifications.tf"
main_file="modules/app-platform/main.tf"

rg -q 'resource "aws_sqs_queue" "push_notifications"' "$module_file"
rg -q 'resource "aws_sqs_queue" "push_notifications_dlq"' "$module_file"
rg -q 'name[[:space:]]*=[[:space:]]*"\$\{local.name_prefix\}-push-notifications"' "$module_file"
rg -q 'deadLetterTargetArn[[:space:]]*=[[:space:]]*aws_sqs_queue.push_notifications_dlq.arn' "$module_file"
rg -q 'maxReceiveCount[[:space:]]*=[[:space:]]*3' "$module_file"

if rg -n 'push_notifications' "$module_file" "$main_file" | rg 'worker_task|aws_ecs_task_definition" "worker'; then
  echo "Push queue must not be wired to the AI worker." >&2
  exit 1
fi
```

- [ ] **Step 2: 계약 테스트가 리소스 부재로 실패하는지 확인한다.**

Run: `bash scripts/test-push-notification-infra-contract.sh`

Expected: `modules/app-platform/push-notifications.tf` 또는 Push queue resource가 없어 exit code가 `0`이 아니다.

- [ ] **Step 3: Standard main queue와 DLQ를 추가한다.**

```hcl
# Push 알림 전용 Queue, Scheduler, 운영 경보를 정의한다.
resource "aws_sqs_queue" "push_notifications_dlq" {
  name                      = "${local.name_prefix}-push-notifications-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "push_notifications" {
  name                       = "${local.name_prefix}-push-notifications"
  message_retention_seconds  = 345600
  visibility_timeout_seconds = var.push_queue_visibility_timeout_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.push_notifications_dlq.arn
    maxReceiveCount     = 3
  })
}
```

- [ ] **Step 4: visibility timeout 입력을 추가한다.**

```hcl
variable "push_queue_visibility_timeout_seconds" {
  description = "Initial visibility timeout for Push notification messages."
  type        = number
  default     = 300

  validation {
    condition = (
      var.push_queue_visibility_timeout_seconds >= 0 &&
      var.push_queue_visibility_timeout_seconds <= 43200
    )
    error_message = "push_queue_visibility_timeout_seconds must be between 0 and 43200."
  }
}
```

- [ ] **Step 5: Queue 계약 테스트를 다시 실행한다.**

Run: `bash scripts/test-push-notification-infra-contract.sh`

Expected: 이후 Task의 IAM과 환경 변수 검사가 아직 실패한다.

- [ ] **Step 6: Queue 변경을 커밋한다.**

```bash
git add modules/app-platform/push-notifications.tf \
  modules/app-platform/variables.tf \
  scripts/test-push-notification-infra-contract.sh
git commit -m "feat: Push 알림 전용 Queue와 DLQ를 분리한다"
```

### Task 2. 기존 API Task에 Queue 소비 권한과 환경 변수 연결

**Files:**
- Modify: `modules/app-platform/main.tf`
- Modify: `scripts/test-push-notification-infra-contract.sh`

**Interfaces:**
- Consumes: `aws_sqs_queue.push_notifications`.
- Produces: API Task Role의 Push queue 최소 권한, API container의 두 환경 변수.

- [ ] **Step 1: API 전용 권한과 환경 변수 검사를 계약 테스트에 추가한다.**

```bash
for action in \
  ChangeMessageVisibility \
  DeleteMessage \
  GetQueueAttributes \
  ReceiveMessage \
  SendMessage
do
  rg -q "\"sqs:${action}\"" "$main_file"
done

rg -q 'resources[[:space:]]*=[[:space:]]*\\[aws_sqs_queue.push_notifications.arn\\]' "$main_file"
rg -q '"SQS_PUSH_NOTIFICATIONS_QUEUE_URL"' "$main_file"
rg -q '"LANDIT_NOTIFICATION_CONSUMER_ENABLED".*"true"' "$main_file"
```

- [ ] **Step 2: 새 검사가 실패하는지 확인한다.**

Run: `bash scripts/test-push-notification-infra-contract.sh`

Expected: Push queue IAM statement와 API 환경 변수가 없어 exit code가 `0`이 아니다.

- [ ] **Step 3: API Task Role에 main queue 최소 권한을 별도 statement로 추가한다.**

```hcl
statement {
  actions = [
    "sqs:ChangeMessageVisibility",
    "sqs:DeleteMessage",
    "sqs:GetQueueAttributes",
    "sqs:ReceiveMessage",
    "sqs:SendMessage"
  ]
  resources = [aws_sqs_queue.push_notifications.arn]
}
```

- [ ] **Step 4: API container environment에 Queue URL과 Consumer enable 값을 추가한다.**

```hcl
{ name = "SQS_PUSH_NOTIFICATIONS_QUEUE_URL", value = aws_sqs_queue.push_notifications.url },
{ name = "LANDIT_NOTIFICATION_CONSUMER_ENABLED", value = "true" },
```

- [ ] **Step 5: API 연결 계약을 검증한다.**

Run: `bash scripts/test-push-notification-infra-contract.sh`

Expected: Queue, API IAM, API 환경 변수 검사는 통과하고 Scheduler 또는 alarm 검사는 아직 실패한다.

- [ ] **Step 6: API 연결 변경을 커밋한다.**

```bash
git add modules/app-platform/main.tf scripts/test-push-notification-infra-contract.sh
git commit -m "feat: API Task가 Push Queue를 소비하도록 연결한다"
```

### Task 3. EventBridge Scheduler 구성

**Files:**
- Modify: `modules/app-platform/push-notifications.tf`
- Modify: `modules/app-platform/variables.tf`
- Modify: `environments/dev/main.tf`
- Modify: `environments/dev/variables.tf`
- Modify: `environments/prod/main.tf`
- Modify: `environments/prod/variables.tf`
- Modify: `scripts/test-push-notification-infra-contract.sh`

**Interfaces:**
- Consumes: `aws_sqs_queue.push_notifications`, 제품이 확정한 Asia/Seoul 발송 시각.
- Produces: 최소 권한 Scheduler execution role, 선택적으로 생성되는 `aws_scheduler_schedule.review_reminder`.

- [ ] **Step 1: 제품이 Asia/Seoul 기준 `HH:mm` 발송 시각을 확정한다.**

Expected: 확정 시각을 `cron(mm HH * * ? *)` 형식으로 변환할 수 있다. 이 확인 전에는 다음 구현 단계를 시작하지 않는다.

- [ ] **Step 2: Scheduler timezone, 비활성 기본값, 메시지 context 검사를 계약 테스트에 추가한다.**

```bash
rg -q 'schedule_expression_timezone[[:space:]]*=[[:space:]]*"Asia/Seoul"' "$module_file"
rg -q 'mode[[:space:]]*=[[:space:]]*"OFF"' "$module_file"
rg -q '<aws.scheduler.execution-id>' "$module_file"
rg -q '<aws.scheduler.scheduled-time>' "$module_file"
rg -q 'messageType[[:space:]]*=[[:space:]]*"REVIEW_REMINDER_BATCH"' "$module_file"
rg -q 'Service"[[:space:]]*=[[:space:]]*"scheduler.amazonaws.com"' "$module_file"
```

- [ ] **Step 3: nullable expression과 활성화 입력을 추가한다.**

```hcl
variable "review_reminder_schedule_expression" {
  description = "Review reminder cron expression in Asia/Seoul. Null omits the schedule."
  type        = string
  default     = null

  validation {
    condition = (
      var.review_reminder_schedule_expression == null ||
      can(regex("^cron\\(.+\\)$", var.review_reminder_schedule_expression))
    )
    error_message = "review_reminder_schedule_expression must be null or an EventBridge cron expression."
  }
}

variable "review_reminder_schedule_enabled" {
  description = "Whether the review reminder schedule is enabled."
  type        = bool
  default     = false
}
```

- [ ] **Step 4: Scheduler assume role과 main queue 송신 권한을 추가한다.**

```hcl
data "aws_iam_policy_document" "review_reminder_scheduler_assume_role" {
  count = var.review_reminder_schedule_expression == null ? 0 : 1

  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values = [
        "arn:aws:scheduler:${var.aws_region}:${data.aws_caller_identity.current.account_id}:schedule/default/${local.name_prefix}-review-reminder"
      ]
    }
  }
}

resource "aws_iam_role" "review_reminder_scheduler" {
  count = var.review_reminder_schedule_expression == null ? 0 : 1

  name               = "${local.name_prefix}-review-reminder-scheduler"
  assume_role_policy = data.aws_iam_policy_document.review_reminder_scheduler_assume_role[0].json
}

data "aws_iam_policy_document" "review_reminder_scheduler" {
  count = var.review_reminder_schedule_expression == null ? 0 : 1

  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.push_notifications.arn]
  }
}

resource "aws_iam_role_policy" "review_reminder_scheduler" {
  count = var.review_reminder_schedule_expression == null ? 0 : 1

  name   = "${local.name_prefix}-review-reminder-scheduler"
  role   = aws_iam_role.review_reminder_scheduler[0].id
  policy = data.aws_iam_policy_document.review_reminder_scheduler[0].json
}
```

- [ ] **Step 5: 제품 시각이 있을 때만 생성되는 Scheduler를 추가한다.**

```hcl
resource "aws_scheduler_schedule" "review_reminder" {
  count = var.review_reminder_schedule_expression == null ? 0 : 1

  name                         = "${local.name_prefix}-review-reminder"
  schedule_expression          = var.review_reminder_schedule_expression
  schedule_expression_timezone = "Asia/Seoul"
  state                        = var.review_reminder_schedule_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sqs_queue.push_notifications.arn
    role_arn = aws_iam_role.review_reminder_scheduler[0].arn
    input = jsonencode({
      version     = 1
      messageId   = "<aws.scheduler.execution-id>"
      messageType = "REVIEW_REMINDER_BATCH"
      occurredAt  = "<aws.scheduler.scheduled-time>"
      payload     = {}
    })
  }
}
```

- [ ] **Step 6: dev와 prod root에서 값을 전달하되 기본 상태는 생성 안 함과 비활성으로 둔다.**

```hcl
review_reminder_schedule_expression = var.review_reminder_schedule_expression
review_reminder_schedule_enabled    = var.review_reminder_schedule_enabled
```

```hcl
variable "review_reminder_schedule_expression" {
  description = "Review reminder cron expression in Asia/Seoul."
  type        = string
  default     = null
}

variable "review_reminder_schedule_enabled" {
  description = "Whether the review reminder schedule is enabled."
  type        = bool
  default     = false
}
```

- [ ] **Step 7: 확정된 production cron을 기록하고 첫 plan에서는 비활성 상태를 유지한다.**

Expected: `environments/prod/variables.tf`의 expression은 제품이 확정한 `cron(mm HH * * ? *)`, enabled는 BE develop 통합 검증 전까지 `false`다. Development는 별도 제품 요구가 없으면 expression `null`, enabled `false`를 유지한다.

- [ ] **Step 8: Scheduler 계약을 검증하고 커밋한다.**

Run: `bash scripts/test-push-notification-infra-contract.sh`

Expected: Scheduler timezone, 메시지 context, execution role 최소 권한 검사가 통과한다.

```bash
git add modules/app-platform/push-notifications.tf \
  modules/app-platform/variables.tf \
  environments/dev/main.tf \
  environments/dev/variables.tf \
  environments/prod/main.tf \
  environments/prod/variables.tf \
  scripts/test-push-notification-infra-contract.sh
git commit -m "feat: 복습 리마인더 Scheduler를 Push Queue에 연결한다"
```

### Task 4. Queue 운영 경보와 출력값 구성

**Files:**
- Modify: `modules/app-platform/push-notifications.tf`
- Modify: `modules/app-platform/variables.tf`
- Modify: `modules/app-platform/outputs.tf`
- Modify: `environments/dev/main.tf`
- Modify: `environments/dev/variables.tf`
- Modify: `environments/dev/outputs.tf`
- Modify: `environments/prod/main.tf`
- Modify: `environments/prod/variables.tf`
- Modify: `environments/prod/outputs.tf`
- Modify: `scripts/test-push-notification-infra-contract.sh`

**Interfaces:**
- Consumes: main queue와 DLQ의 `QueueName`, 선택적인 alarm action ARN 목록.
- Produces: main queue oldest age alarm, DLQ visible messages alarm, 운영 확인용 Terraform outputs.

- [ ] **Step 1: 운영팀이 CloudWatch alarm의 외부 수신 대상을 확정한다.**

Expected: 연결할 SNS topic ARN 목록을 확정하거나, 첫 단계에서는 action 없이 CloudWatch Alarm 상태만 만들기로 명시적으로 결정한다. 현재 Grafana Discord contact point는 CloudWatch Alarm ARN을 직접 받지 않는다.

- [ ] **Step 2: 경보 metric과 임계값 검사를 계약 테스트에 추가한다.**

```bash
rg -q 'metric_name[[:space:]]*=[[:space:]]*"ApproximateAgeOfOldestMessage"' "$module_file"
rg -q 'metric_name[[:space:]]*=[[:space:]]*"ApproximateNumberOfMessagesVisible"' "$module_file"
rg -q 'treat_missing_data[[:space:]]*=[[:space:]]*"notBreaching"' "$module_file"
rg -q 'alarm_actions[[:space:]]*=[[:space:]]*var.push_alarm_action_arns' "$module_file"
```

- [ ] **Step 3: main queue 적체와 DLQ 메시지 경보를 추가한다.**

```hcl
resource "aws_cloudwatch_metric_alarm" "push_notifications_backlog" {
  alarm_name          = "${local.name_prefix}-push-notifications-backlog"
  alarm_description   = "Push notification message age is at least five minutes."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 300
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.push_alarm_action_arns

  dimensions = {
    QueueName = aws_sqs_queue.push_notifications.name
  }
}

resource "aws_cloudwatch_metric_alarm" "push_notifications_dlq_visible" {
  alarm_name          = "${local.name_prefix}-push-notifications-dlq-visible"
  alarm_description   = "At least one Push notification message is visible in the DLQ."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.push_alarm_action_arns

  dimensions = {
    QueueName = aws_sqs_queue.push_notifications_dlq.name
  }
}
```

- [ ] **Step 4: alarm action 입력과 환경별 전달을 추가한다.**

```hcl
variable "push_alarm_action_arns" {
  description = "SNS topic ARNs notified by Push queue CloudWatch alarms."
  type        = list(string)
  default     = []
}
```

각 환경 root에는 같은 이름의 variable을 추가하고 module call에 다음 값을 전달한다.

```hcl
push_alarm_action_arns = var.push_alarm_action_arns
```

- [ ] **Step 5: 운영 확인용 output을 module과 환경 root에 추가한다.**

```hcl
output "push_notifications_queue_url" {
  description = "Push notifications main queue URL."
  value       = aws_sqs_queue.push_notifications.url
}

output "push_notifications_dlq_url" {
  description = "Push notifications dead-letter queue URL."
  value       = aws_sqs_queue.push_notifications_dlq.url
}

output "review_reminder_schedule_arn" {
  description = "Review reminder EventBridge Scheduler ARN."
  value       = try(aws_scheduler_schedule.review_reminder[0].arn, null)
}
```

- [ ] **Step 6: 전체 정적 계약 테스트를 실행하고 커밋한다.**

Run: `bash scripts/test-push-notification-infra-contract.sh`

Expected: Queue, redrive, API IAM, API 환경 변수, Scheduler, CloudWatch alarm 검사가 모두 통과한다.

```bash
git add modules/app-platform/push-notifications.tf \
  modules/app-platform/variables.tf \
  modules/app-platform/outputs.tf \
  environments/dev/main.tf \
  environments/dev/variables.tf \
  environments/dev/outputs.tf \
  environments/prod/main.tf \
  environments/prod/variables.tf \
  environments/prod/outputs.tf \
  scripts/test-push-notification-infra-contract.sh
git commit -m "feat: Push Queue 적체와 DLQ 메시지를 경보한다"
```

### Task 5. 문서화와 Terraform plan 검증

**Files:**
- Create: `docs/push-notifications.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**
- Consumes: Tasks 1~4의 Terraform 계약과 BE 전달 계약.
- Produces: 운영 절차, 검증 근거, apply 승인용 dev·prod plan.

- [ ] **Step 1: Push 인프라 운영 문서를 작성한다.**

문서에는 다음 항목을 그대로 기록한다.

- Queue 이름과 기존 jobs queue 분리 원칙.
- Scheduler message JSON과 BE의 Asia/Seoul 날짜 변환 책임.
- API Task Role의 다섯 SQS action과 DLQ 접근 금지.
- Receipt message의 per-message `DelaySeconds=900`.
- Queue visibility timeout `300`, redrive `maxReceiveCount=3`, DLQ retention 14일.
- backlog와 DLQ alarm의 metric, period, threshold, notification action.
- Scheduler 비활성 상태에서 BE를 먼저 배포하는 순서.
- DLQ 메시지 본문을 외부에 노출하지 않고 message metadata와 원인만 확인하는 절차.

- [ ] **Step 2: Terraform format과 정적 검증을 실행한다.**

Run: `terraform fmt -recursive`

Run: `terraform fmt -recursive -check`

Run: `bash scripts/test-push-notification-infra-contract.sh`

Run: `git diff --check`

Expected: 모든 명령이 exit code `0`이다.

- [ ] **Step 3: development와 production validate를 실행한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/dev validate`

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod validate`

Expected: 두 명령 모두 `Success! The configuration is valid.`를 반환한다.

- [ ] **Step 4: Scheduler 비활성 상태의 dev·prod plan을 저장한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/dev plan -out=/tmp/lan184-dev-push.tfplan`

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod plan -out=/tmp/lan184-prod-push.tfplan`

Expected: Push main queue, DLQ, API Task Role policy, API task definition, 두 CloudWatch alarm이 추가된다. Scheduler expression이 확정된 환경에만 Scheduler role과 비활성 Scheduler가 추가된다. AI Worker Task Definition, AI jobs queue, ECS Service 교체나 삭제는 없다.

- [ ] **Step 5: 저장된 plan JSON으로 변경 범위를 검토한다.**

Run: `terraform -chdir=environments/dev show -json /tmp/lan184-dev-push.tfplan | jq -r '.resource_changes[] | [.address, .change.actions | join(",")] | @tsv'`

Run: `terraform -chdir=environments/prod show -json /tmp/lan184-prod-push.tfplan | jq -r '.resource_changes[] | [.address, .change.actions | join(",")] | @tsv'`

Expected: 삭제 action이 없고 `aws_sqs_queue.jobs`, `aws_ecs_task_definition.worker`, `aws_ecs_service.worker` 변경이 없다.

- [ ] **Step 6: 계획과 검증 기록을 커밋한다.**

```bash
git add docs/push-notifications.md checklist.md context-notes.md
git commit -m "docs: Push 알림 인프라 운영과 검증 절차를 정리한다"
```

- [ ] **Step 7: apply 전에 사용자에게 dev·prod plan 요약과 미확정 항목을 제시한다.**

Expected: 발송 시각, Scheduler 활성화 환경, CloudWatch alarm 수신 대상, plan의 add/change/destroy 수를 제시하고 명시적 승인을 받는다.

### Task 6. 승인 후 live 검증

이 Task는 현재 요청 범위에서 실행하지 않는다.

- [ ] **Step 1: 승인된 saved plan만 apply한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/dev apply /tmp/lan184-dev-push.tfplan`

Run: `AWS_PROFILE=landit terraform -chdir=environments/prod apply /tmp/lan184-prod-push.tfplan`

Expected: 승인된 plan과 같은 변경 수이며 삭제가 없다.

- [ ] **Step 2: Queue와 redrive live 설정을 확인한다.**

Run: `push_queue_url=$(AWS_PROFILE=landit terraform -chdir=environments/dev output -raw push_notifications_queue_url)`

Run: `AWS_PROFILE=landit aws sqs get-queue-attributes --queue-url "$push_queue_url" --attribute-names QueueArn VisibilityTimeout RedrivePolicy`

Expected: visibility timeout `300`, Push DLQ ARN, max receive count `3`이 확인된다.

- [ ] **Step 3: API Task Definition의 환경 변수와 Task Role policy를 확인한다.**

Expected: Queue URL과 Consumer enable 두 환경 변수가 API container에만 있고, API Task Role은 Push main queue에 다섯 action만 가지며 AI Worker Role에는 Push queue 권한이 없다.

- [ ] **Step 4: Scheduler와 CloudWatch alarm 상태를 확인한다.**

Expected: timezone `Asia/Seoul`, flexible window `OFF`, target main queue ARN, 확정 cron, 의도한 enabled 상태가 확인된다. 두 alarm은 처음에 `INSUFFICIENT_DATA` 또는 `OK`이며 action ARN이 결정과 일치한다.

- [ ] **Step 5: BE 배포 뒤 development 종단 검증을 수행한다.**

Expected: 수동 `REVIEW_REMINDER_BATCH`가 API Consumer에서 동시성 `2`로 처리되고, Receipt message가 같은 queue에서 900초 지연되며, 잘못된 message가 세 번 수신된 뒤 DLQ로 이동한다.

- [ ] **Step 6: production Scheduler를 활성화할 최종 plan을 별도 승인받아 적용한다.**

Expected: Scheduler state 변경 외의 예상하지 않은 변경이 없고, 첫 예약 실행의 message와 BE 발송 이력이 같은 scheduled time과 review date를 가리킨다.

## 구현 전 확인 사항

1. Asia/Seoul 기준 복습 리마인더 발송 시각을 `HH:mm`으로 확정해야 한다.
2. Scheduler를 production에만 만들지, development에도 비활성 상태로 만들지 확정해야 한다.
3. CloudWatch alarm이 상태만 관리할지, SNS topic을 통해 실제 운영 채널로 전달할지 확정해야 한다.
4. main queue visibility timeout `300`초 안에 한 배치가 끝나는지 BE 부하 기준을 확인해야 한다. 넘을 수 있으면 BE가 visibility를 연장해야 한다.
5. BE 문서의 `payload.reviewDate`를 Scheduler 입력에서 제거하고 `occurredAt`을 Asia/Seoul 날짜로 변환하는 계약으로 맞춰야 한다.
6. Scheduler 자체의 target 전송 실패를 Push DLQ에 섞지 않는다. 별도 Scheduler DLQ나 `TargetErrorCount` 경보가 필요한지는 초기 운영 범위 밖의 후속 결정으로 남긴다.
