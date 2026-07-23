#!/usr/bin/env bash
# Push 알림 SQS와 Scheduler Terraform 계약을 정적으로 검증한다.
set -euo pipefail

MODULE_DIR="modules/app-platform"
PUSH_FILE="${MODULE_DIR}/push-notifications.tf"
MAIN_FILE="${MODULE_DIR}/main.tf"
VARIABLES_FILE="${MODULE_DIR}/variables.tf"
OUTPUTS_FILE="${MODULE_DIR}/outputs.tf"

require() {
  grep -Eq "$1" "$2" || {
    echo "missing contract: $1 in $2" >&2
    exit 1
  }
}

require_text() {
  grep -Eq "$1" <<<"$2" || {
    echo "missing contract: $1 in $3" >&2
    exit 1
  }
}

forbid_text() {
  ! grep -Eq "$1" <<<"$2" || {
    echo "unexpected contract: $1 in $3" >&2
    exit 1
  }
}

forbid_push_resource() {
  local resource_type="$1"
  local source_files
  source_files="$(find "$MODULE_DIR" -name '*.tf' -type f -print)"

  ! grep -Eq "resource \"${resource_type}\" \"[^\"]*(push|notification)[^\"]*\"" $source_files || {
    echo "unexpected Push ${resource_type} resource" >&2
    exit 1
  }
}

block() {
  awk -v start="$1" '
    $0 ~ start { found = 1 }
    found {
      line = $0
      opens = gsub(/{/, "{", line)
      closes = gsub(/}/, "}", line)
      depth += opens - closes
      print
      if (depth == 0) exit
    }
  ' "$2"
}

statement_with_resource() {
  awk -v resource="$2" '
    /^[[:space:]]*statement[[:space:]]*\{/ {
      in_statement = 1
      depth = 0
      matches_resource = 0
      statement = ""
    }
    in_statement {
      line = $0
      opens = gsub(/{/, "{", line)
      closes = gsub(/}/, "}", line)
      depth += opens - closes
      statement = statement $0 "\n"
      if ($0 ~ ("^[[:space:]]*resources[[:space:]]*=[[:space:]]*\\[" resource "\\][[:space:]]*$")) {
        matches_resource = 1
      }
      if (depth == 0) {
        if (matches_resource) print statement
        in_statement = 0
      }
    }
  ' <<<"$1"
}

single_statement() {
  local statements count
  statements="$(awk '
    /^[[:space:]]*statement[[:space:]]*\{/ {
      in_statement = 1
      depth = 0
      statement = ""
    }
    in_statement {
      line = $0
      opens = gsub(/{/, "{", line)
      closes = gsub(/}/, "}", line)
      depth += opens - closes
      statement = statement $0 "\n"
      if (depth == 0) {
        print statement
        in_statement = 0
      }
    }
  ' <<<"$1")"
  count="$(grep -Ec '^[[:space:]]*statement[[:space:]]*\{' <<<"$statements")"
  [[ "$count" -eq 1 ]] || {
    echo "expected exactly one statement in $2" >&2
    exit 1
  }
  printf '%s\n' "$statements"
}

require 'resource "aws_sqs_queue" "push_notifications_dlq"' "$PUSH_FILE"
require 'name[[:space:]]*=[[:space:]]*"\$\{local.name_prefix\}-push-notifications-dlq"' "$PUSH_FILE"
require 'message_retention_seconds[[:space:]]*=[[:space:]]*1209600' "$PUSH_FILE"
require 'resource "aws_sqs_queue" "push_notifications"' "$PUSH_FILE"
require 'name[[:space:]]*=[[:space:]]*"\$\{local.name_prefix\}-push-notifications"' "$PUSH_FILE"
require 'visibility_timeout_seconds[[:space:]]*=[[:space:]]*300' "$PUSH_FILE"
require 'message_retention_seconds[[:space:]]*=[[:space:]]*345600' "$PUSH_FILE"
require 'deadLetterTargetArn[[:space:]]*=[[:space:]]*aws_sqs_queue.push_notifications_dlq.arn' "$PUSH_FILE"
require 'maxReceiveCount[[:space:]]*=[[:space:]]*3' "$PUSH_FILE"

api_policy="$(block 'data "aws_iam_policy_document" "api_task"' "$MAIN_FILE")"
api_push_statement="$(statement_with_resource "$api_policy" 'aws_sqs_queue\.push_notifications\.arn')"
[[ "$(grep -Ec '^[[:space:]]*statement[[:space:]]*\{' <<<"$api_push_statement")" -eq 1 ]] || {
  echo "expected exactly one API Push queue policy statement" >&2
  exit 1
}
api_push_actions="$(grep -Eo '"sqs:[A-Za-z]+"' <<<"$api_push_statement" | tr -d '"' | sort -u)"
[[ "$api_push_actions" == $'sqs:ChangeMessageVisibility\nsqs:DeleteMessage\nsqs:GetQueueAttributes\nsqs:ReceiveMessage\nsqs:SendMessage' ]] || {
  echo "unexpected API Push queue actions: $api_push_actions" >&2
  exit 1
}
forbid_text 'sqs:GetQueueUrl|push_notifications_dlq' "$api_push_statement" "API Push queue policy statement"

api_task="$(block 'resource "aws_ecs_task_definition" "api"' "$MAIN_FILE")"
grep -q 'SQS_PUSH_NOTIFICATIONS_QUEUE_URL' <<<"$api_task"
grep -q 'LANDIT_NOTIFICATION_CONSUMER_ENABLED", value = "true"' <<<"$api_task"
worker_task="$(block 'resource "aws_ecs_task_definition" "worker"' "$MAIN_FILE")"
! grep -q 'PUSH_NOTIFICATIONS' <<<"$worker_task"
worker_policy="$(block 'data "aws_iam_policy_document" "worker_task"' "$MAIN_FILE")"
forbid_text 'aws_sqs_queue\.push_notifications' "$worker_policy" "Worker IAM policy"
for resource_type in aws_ecs_task_definition aws_ecs_service aws_ecr_repository aws_cloudwatch_log_group; do
  forbid_push_resource "$resource_type"
done

require 'variable "review_reminder_schedule_expression"' "$VARIABLES_FILE"
require 'variable "review_reminder_schedule_enabled"' "$VARIABLES_FILE"
schedule_expression_variable="$(block 'variable "review_reminder_schedule_expression"' "$VARIABLES_FILE")"
require_text 'default[[:space:]]*=[[:space:]]*"cron\(0 20 \* \* \? \*\)"' "$schedule_expression_variable" "review reminder schedule expression variable"
schedule_enabled_variable="$(block 'variable "review_reminder_schedule_enabled"' "$VARIABLES_FILE")"
require_text 'default[[:space:]]*=[[:space:]]*false' "$schedule_enabled_variable" "review reminder schedule enabled variable"
require 'resource "aws_iam_role" "review_reminder_scheduler"' "$PUSH_FILE"
scheduler_assume_policy="$(block 'data "aws_iam_policy_document" "review_reminder_scheduler_assume_role"' "$PUSH_FILE")"
scheduler_assume_statement="$(single_statement "$scheduler_assume_policy" "scheduler assume policy")"
require_text 'type[[:space:]]*=[[:space:]]*"Service"' "$scheduler_assume_statement" "scheduler assume policy"
require_text 'identifiers[[:space:]]*=[[:space:]]*\["scheduler.amazonaws.com"\]' "$scheduler_assume_statement" "scheduler assume policy"
[[ "$(grep -Ec '^[[:space:]]*principals[[:space:]]*\{' <<<"$scheduler_assume_statement")" -eq 1 ]] || {
  echo "expected scheduler assume policy to have one principal" >&2
  exit 1
}
scheduler_inline_policy="$(block 'data "aws_iam_policy_document" "review_reminder_scheduler"' "$PUSH_FILE")"
scheduler_inline_statement="$(single_statement "$scheduler_inline_policy" "scheduler inline policy")"
require_text 'actions[[:space:]]*=[[:space:]]*\["sqs:SendMessage"\]' "$scheduler_inline_statement" "scheduler inline policy"
require_text 'resources[[:space:]]*=[[:space:]]*\[aws_sqs_queue.push_notifications.arn\]' "$scheduler_inline_statement" "scheduler inline policy"
require 'resource "aws_scheduler_schedule" "review_reminder"' "$PUSH_FILE"
require 'schedule_expression[[:space:]]*=[[:space:]]*var.review_reminder_schedule_expression' "$PUSH_FILE"
require 'schedule_expression_timezone[[:space:]]*=[[:space:]]*"Asia/Seoul"' "$PUSH_FILE"
require 'state[[:space:]]*=[[:space:]]*var.review_reminder_schedule_enabled \? "ENABLED" : "DISABLED"' "$PUSH_FILE"
require 'mode[[:space:]]*=[[:space:]]*"OFF"' "$PUSH_FILE"
for value in 'version[[:space:]]*=[[:space:]]*1' '<aws.scheduler.execution-id>' 'REVIEW_REMINDER_BATCH' '<aws.scheduler.scheduled-time>' 'payload[[:space:]]*=[[:space:]]*\{\}'; do
  grep -Eq "$value" "$PUSH_FILE"
done

require 'resource "aws_cloudwatch_metric_alarm" "push_notifications_backlog"' "$PUSH_FILE"
require 'resource "aws_cloudwatch_metric_alarm" "push_notifications_dlq"' "$PUSH_FILE"
backlog_alarm="$(block 'resource "aws_cloudwatch_metric_alarm" "push_notifications_backlog"' "$PUSH_FILE")"
require_text 'metric_name[[:space:]]*=[[:space:]]*"ApproximateAgeOfOldestMessage"' "$backlog_alarm" "Push backlog alarm"
require_text 'statistic[[:space:]]*=[[:space:]]*"Maximum"' "$backlog_alarm" "Push backlog alarm"
require_text 'period[[:space:]]*=[[:space:]]*300' "$backlog_alarm" "Push backlog alarm"
require_text 'evaluation_periods[[:space:]]*=[[:space:]]*1' "$backlog_alarm" "Push backlog alarm"
require_text 'threshold[[:space:]]*=[[:space:]]*300' "$backlog_alarm" "Push backlog alarm"
require_text 'treat_missing_data[[:space:]]*=[[:space:]]*"notBreaching"' "$backlog_alarm" "Push backlog alarm"
forbid_text 'alarm_actions|ok_actions|insufficient_data_actions' "$backlog_alarm" "Push backlog alarm"
dlq_alarm="$(block 'resource "aws_cloudwatch_metric_alarm" "push_notifications_dlq"' "$PUSH_FILE")"
require_text 'metric_name[[:space:]]*=[[:space:]]*"ApproximateNumberOfMessagesVisible"' "$dlq_alarm" "Push DLQ alarm"
require_text 'statistic[[:space:]]*=[[:space:]]*"Maximum"' "$dlq_alarm" "Push DLQ alarm"
require_text 'period[[:space:]]*=[[:space:]]*300' "$dlq_alarm" "Push DLQ alarm"
require_text 'evaluation_periods[[:space:]]*=[[:space:]]*1' "$dlq_alarm" "Push DLQ alarm"
require_text 'threshold[[:space:]]*=[[:space:]]*1' "$dlq_alarm" "Push DLQ alarm"
require_text 'treat_missing_data[[:space:]]*=[[:space:]]*"notBreaching"' "$dlq_alarm" "Push DLQ alarm"
forbid_text 'alarm_actions|ok_actions|insufficient_data_actions' "$dlq_alarm" "Push DLQ alarm"

require 'output "push_notifications_queue_url"' "$OUTPUTS_FILE"
require 'output "push_notifications_dlq_url"' "$OUTPUTS_FILE"
require 'output "review_reminder_scheduler_arn"' "$OUTPUTS_FILE"
