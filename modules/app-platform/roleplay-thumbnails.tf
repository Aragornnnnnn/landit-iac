# 롤플레이 썸네일 전용 큐와 독립 소비 프로세스의 최소 실행 권한을 정의한다.
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
    { name = "AWS_REGION", value = var.aws_region },
    { name = "APP_ENV", value = var.environment },
    { name = "LLM_PROVIDER", value = "openai" },
    { name = "EMBEDDING_MODEL", value = "openai/text-embedding-3-small" },
    { name = "ROLEPLAY_THUMBNAIL_ENABLED", value = "true" },
    { name = "ROLEPLAY_THUMBNAIL_MODEL", value = "gpt-image-2.5-flare" },
    { name = "ROLEPLAY_THUMBNAIL_QUALITY", value = "low" },
    { name = "ROLEPLAY_THUMBNAIL_QUEUE_URL", value = aws_sqs_queue.roleplay_thumbnails.url },
    { name = "ROLEPLAY_THUMBNAIL_BACKEND_URL", value = "https://${var.api_domain_name}" },
    { name = "CONTENT_BUCKET_NAME", value = var.content_bucket_name },
    { name = "CONTENT_CLOUDFRONT_URL", value = var.content_cloudfront_url },
    { name = "CONTENT_ASSET_TIMEOUT_SECONDS", value = "600" }
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

resource "aws_iam_role" "thumbnail_task" {
  count              = var.ecs_platform_enabled && var.roleplay_thumbnail_enabled ? 1 : 0
  name               = "${local.name_prefix}-thumbnail-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

resource "aws_iam_role_policy" "thumbnail_task" {
  count  = var.ecs_platform_enabled && var.roleplay_thumbnail_enabled ? 1 : 0
  name   = "${local.name_prefix}-thumbnail-consumer"
  role   = aws_iam_role.thumbnail_task[0].id
  policy = data.aws_iam_policy_document.thumbnail_consumer.json
}

resource "aws_security_group" "thumbnail_tasks" {
  count       = var.ecs_platform_enabled && var.roleplay_thumbnail_enabled ? 1 : 0
  name        = "${local.name_prefix}-thumbnail-tasks"
  description = "Outbound-only thumbnail worker; no inbound listener."
  vpc_id      = aws_vpc.this.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_task_definition" "thumbnail" {
  count                    = var.ecs_platform_enabled && var.roleplay_thumbnail_enabled ? 1 : 0
  family                   = "${local.name_prefix}-thumbnail"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution[0].arn
  task_role_arn            = aws_iam_role.thumbnail_task[0].arn
  skip_destroy             = true
  container_definitions = jsonencode([{
    name        = "thumbnail"
    image       = var.worker_image_ref
    command     = ["python", "-m", "app.roleplay.thumbnail_worker"]
    essential   = true
    stopTimeout = 120
    healthCheck = {
      command     = ["CMD-SHELL", "test -f /tmp/landit-thumbnail-ready"]
      interval    = 10
      timeout     = 2
      retries     = 3
      startPeriod = 45
    }
    environment = local.thumbnail_environment
    secrets = [
      { name = "OPENAI_API_KEY", valueFrom = "${local.ssm_path}/OPENAI_API_KEY" },
      { name = "ROLEPLAY_THUMBNAIL_WORKER_TOKEN", valueFrom = "${local.ssm_path}/ROLEPLAY_THUMBNAIL_WORKER_TOKEN" }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.worker.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "thumbnail"
      }
    }
  }])
  lifecycle {
    precondition {
      condition     = try(split("@", var.worker_image_ref)[0] == aws_ecr_repository.worker.repository_url, false) && can(regex("@sha256:[0-9a-f]{64}$", var.worker_image_ref))
      error_message = "thumbnail uses the same digest-pinned AI repository."
    }
  }
}

resource "aws_ecs_service" "thumbnail" {
  count           = var.ecs_platform_enabled && var.roleplay_thumbnail_enabled ? 1 : 0
  name            = "${local.name_prefix}-thumbnail"
  cluster         = aws_ecs_cluster.this[0].id
  task_definition = aws_ecs_task_definition.thumbnail[0].arn
  # 새 코드 이미지를 AI 배포 workflow가 고정한 뒤 최초 1개로 시작한다.
  desired_count         = 0
  launch_type           = "FARGATE"
  wait_for_steady_state = false
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = values(aws_subnet.public)[*].id
    security_groups  = [aws_security_group.thumbnail_tasks[0].id]
    assign_public_ip = true
  }
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
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
output "roleplay_thumbnail_service_name" { value = try(aws_ecs_service.thumbnail[0].name, null) }
