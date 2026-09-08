# 관리자 일회성 예약을 기존 학습 알림과 분리하고 기존 Push SQS로 전달한다.
resource "aws_scheduler_schedule_group" "admin_push" {
  name = "${local.name_prefix}-admin-push"
}

data "aws_iam_policy_document" "admin_push_scheduler_assume_role" {
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
      values   = [aws_scheduler_schedule_group.admin_push.arn]
    }
  }
}

resource "aws_iam_role" "admin_push_scheduler" {
  name               = "${local.name_prefix}-admin-push-scheduler"
  assume_role_policy = data.aws_iam_policy_document.admin_push_scheduler_assume_role.json
}

resource "aws_iam_role_policy" "admin_push_scheduler" {
  name = "${local.name_prefix}-admin-push-send"
  role = aws_iam_role.admin_push_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = aws_sqs_queue.push_notifications.arn
    }]
  })
}

data "aws_iam_policy_document" "admin_push_manage" {
  statement {
    actions = ["scheduler:CreateSchedule", "scheduler:GetSchedule", "scheduler:DeleteSchedule"]
    resources = [
      "arn:aws:scheduler:${var.aws_region}:${data.aws_caller_identity.current.account_id}:schedule/${aws_scheduler_schedule_group.admin_push.name}/admin-push-*"
    ]
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.admin_push_scheduler.arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "api_admin_push_manage" {
  count = var.ecs_platform_enabled ? 1 : 0

  name   = "${local.name_prefix}-admin-push-manage"
  role   = aws_iam_role.api_task[0].id
  policy = data.aws_iam_policy_document.admin_push_manage.json
}

output "admin_push_scheduler_group" {
  description = "관리자 일회성 예약을 저장하는 환경별 그룹이다."
  value       = aws_scheduler_schedule_group.admin_push.name
}

output "admin_push_scheduler_role_arn" {
  description = "관리자 예약이 기존 Push SQS에 전달할 때 사용하는 실행 역할이다."
  value       = aws_iam_role.admin_push_scheduler.arn
}

output "admin_push_manage_policy_json" {
  description = "EC2 API에도 동일한 예약 관리 권한을 적용하는 정책이다."
  value       = data.aws_iam_policy_document.admin_push_manage.json
}
