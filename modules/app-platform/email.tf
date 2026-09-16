# ECS API의 체험 알림 이메일 설정과 최소 발송·예약 권한을 정의한다.
resource "aws_sesv2_configuration_set" "transactional" {
  count = var.ecs_platform_enabled ? 1 : 0

  configuration_set_name = "${local.name_prefix}-transactional"
  reputation_options {
    reputation_metrics_enabled = true
  }
  suppression_options {
    suppressed_reasons = ["BOUNCE", "COMPLAINT"]
  }
}

resource "aws_sesv2_configuration_set_event_destination" "email_metrics" {
  count = var.ecs_platform_enabled ? 1 : 0

  configuration_set_name = aws_sesv2_configuration_set.transactional[0].configuration_set_name
  event_destination_name = "delivery-metrics"
  event_destination {
    enabled              = true
    matching_event_types = ["SEND", "DELIVERY", "BOUNCE", "COMPLAINT", "REJECT", "DELIVERY_DELAY"]
    cloud_watch_destination {
      dimension_configuration {
        default_dimension_value = var.environment
        dimension_name          = "Environment"
        dimension_value_source  = "MESSAGE_TAG"
      }
    }
  }
}

resource "aws_iam_role_policy" "api_email" {
  count = var.ecs_platform_enabled ? 1 : 0

  name = "${local.name_prefix}-email"
  role = aws_iam_role.api_task[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["ses:SendEmail"]
        Resource = [
          "arn:aws:ses:${var.aws_region}:${data.aws_caller_identity.current.account_id}:identity/landit.im",
          aws_sesv2_configuration_set.transactional[0].arn
        ]
        Condition = { StringEquals = { "ses:FromAddress" = "no-reply@landit.im" } }
      },
      {
        Effect = "Allow"
        Action = ["scheduler:CreateSchedule", "scheduler:GetSchedule"]
        Resource = [
          "arn:aws:scheduler:${var.aws_region}:${data.aws_caller_identity.current.account_id}:schedule/${aws_scheduler_schedule_group.admin_push.name}/notification-job-*"
        ]
      }
    ]
  })
  # landit.im identity는 개발 root가 소유한다. 기존 관리자 예약 정책의 PassRole을 재사용한다.
}
