# 롤플레이 썸네일 큐와 AI 서버의 백그라운드 소비 권한을 정의한다.
resource "aws_sqs_queue" "roleplay_thumbnails_dlq" {
  name                      = "${local.name_prefix}-roleplay-thumbnails-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "roleplay_thumbnails" {
  name                       = "${local.name_prefix}-roleplay-thumbnails"
  visibility_timeout_seconds = 900
  receive_wait_time_seconds  = 20
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.roleplay_thumbnails_dlq.arn
    maxReceiveCount     = 5
  })
}

variable "roleplay_thumbnail_enabled" {
  description = "배포한 BE에서 썸네일 작업 등록을 활성화한다."
  type        = bool
  default     = false
}

locals {
  thumbnail_environment = [
    { name = "ROLEPLAY_THUMBNAIL_ENABLED", value = tostring(var.roleplay_thumbnail_enabled) },
    { name = "ROLEPLAY_THUMBNAIL_CONSUMER_ENABLED", value = tostring(var.roleplay_thumbnail_enabled) },
    { name = "ROLEPLAY_THUMBNAIL_MODEL", value = "gpt-image-2.5-flare" },
    { name = "ROLEPLAY_THUMBNAIL_QUALITY", value = "low" },
    { name = "ROLEPLAY_THUMBNAIL_QUEUE_URL", value = aws_sqs_queue.roleplay_thumbnails.url },
    { name = "ROLEPLAY_THUMBNAIL_BACKEND_URL", value = "https://${var.api_domain_name}" }
  ]
}

data "aws_iam_policy_document" "thumbnail_consumer" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.roleplay_thumbnails.arn]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.content_bucket_name}/content/roleplay-thumbnails/*"]
  }
}

resource "aws_iam_role_policy" "worker_thumbnail_consumer" {
  count  = var.ecs_platform_enabled && var.roleplay_thumbnail_enabled ? 1 : 0
  name   = "${local.name_prefix}-thumbnail-consumer"
  role   = aws_iam_role.worker_task[0].id
  policy = data.aws_iam_policy_document.thumbnail_consumer.json
}

resource "aws_cloudwatch_metric_alarm" "thumbnail_dlq" {
  alarm_name          = "${local.name_prefix}-roleplay-thumbnail-dlq"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = aws_sqs_queue.roleplay_thumbnails_dlq.name }
}

output "roleplay_thumbnail_queue_url" { value = aws_sqs_queue.roleplay_thumbnails.url }
output "roleplay_thumbnail_queue_arn" { value = aws_sqs_queue.roleplay_thumbnails.arn }
output "roleplay_thumbnail_consumer_policy_json" { value = data.aws_iam_policy_document.thumbnail_consumer.json }
