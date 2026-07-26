#!/usr/bin/env bash
# Scheduler plan의 context token이 Unicode escape 없이 전달되는지 검증한다.

set -euo pipefail

plan_file="${1:?usage: $0 <terraform-plan-file>}"
scheduler_input="$({
  terraform show -json "$plan_file" |
    jq -er '.resource_changes[] | select(.address == "module.app_platform.aws_scheduler_schedule.review_reminder") | .change.after.target[0].input'
})"

if [[ "$scheduler_input" == *'\u003c'* || "$scheduler_input" == *'\u003e'* ]]; then
  echo "Scheduler context token must not be Unicode escaped in target input" >&2
  exit 1
fi

jq -e \
  '.version == 1 and
   .messageId == "<aws.scheduler.execution-id>" and
   .messageType == "SCHEDULED_NOTIFICATION_BATCH" and
   .occurredAt == "<aws.scheduler.scheduled-time>" and
   .payload == {}' \
  <<<"$scheduler_input" >/dev/null
