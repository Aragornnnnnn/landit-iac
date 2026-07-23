# Push 알림 Queue, Scheduler, 경보 리소스를 정의한다.
resource "aws_sqs_queue" "push_notifications_dlq" {
  name                      = "${local.name_prefix}-push-notifications-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "push_notifications" {
  name                       = "${local.name_prefix}-push-notifications"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 345600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.push_notifications_dlq.arn
    maxReceiveCount     = 3
  })
}

data "aws_iam_policy_document" "review_reminder_scheduler_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "review_reminder_scheduler" {
  name               = "${local.name_prefix}-review-reminder-scheduler"
  assume_role_policy = data.aws_iam_policy_document.review_reminder_scheduler_assume_role.json
}

data "aws_iam_policy_document" "review_reminder_scheduler" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.push_notifications.arn]
  }
}

resource "aws_iam_role_policy" "review_reminder_scheduler" {
  name   = "${local.name_prefix}-review-reminder-scheduler"
  role   = aws_iam_role.review_reminder_scheduler.id
  policy = data.aws_iam_policy_document.review_reminder_scheduler.json
}

resource "aws_scheduler_schedule" "review_reminder" {
  name                         = "${local.name_prefix}-review-reminder"
  schedule_expression          = var.review_reminder_schedule_expression
  schedule_expression_timezone = "Asia/Seoul"
  state                        = var.review_reminder_schedule_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sqs_queue.push_notifications.arn
    role_arn = aws_iam_role.review_reminder_scheduler.arn
    input = jsonencode({
      version     = 1
      messageId   = "<aws.scheduler.execution-id>"
      messageType = "REVIEW_REMINDER_BATCH"
      occurredAt  = "<aws.scheduler.scheduled-time>"
      payload     = {}
    })
  }
}

resource "aws_cloudwatch_metric_alarm" "push_notifications_backlog" {
  alarm_name          = "${local.name_prefix}-push-notifications-backlog"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 300
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.push_notifications.name
  }
}

resource "aws_cloudwatch_metric_alarm" "push_notifications_dlq" {
  alarm_name          = "${local.name_prefix}-push-notifications-dlq"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.push_notifications_dlq.name
  }
}
