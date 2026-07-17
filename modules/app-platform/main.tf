# ECS Fargate 기반 Landit application platform 리소스를 정의한다.
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix     = "${var.environment}-${var.project_name}"
  ssm_path        = trimsuffix(var.parameter_store_path, "/")
  app_bucket_name = "${local.name_prefix}-app-${data.aws_caller_identity.current.account_id}"
  enable_https    = var.alb_certificate_arn != null
  enable_api_host_rule = (
    local.enable_https &&
    length(var.api_domain_name) > 0
  )
  enable_ai_host_rule = (
    local.enable_https &&
    length(var.ai_domain_name) > 0
  )
  availability_zones = slice(
    data.aws_availability_zones.available.names,
    0,
    length(var.public_subnet_cidrs)
  )
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_subnet" "public" {
  for_each = {
    for index, cidr in var.public_subnet_cidrs : tostring(index) => {
      cidr = cidr
      az   = local.availability_zones[index]
    }
  }

  vpc_id                  = aws_vpc.this.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-${each.key}"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "${local.name_prefix}-public"
  }
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb"
  description = "Allow public HTTP and HTTPS traffic to ALB."
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "ecs_tasks" {
  name        = "${local.name_prefix}-ecs-tasks"
  description = "Allow ALB traffic to ECS tasks."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "API from ALB"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description     = "AI from ALB"
    from_port       = var.ai_container_port
    to_port         = var.ai_container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "api" {
  name               = "${local.name_prefix}-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = values(aws_subnet.public)[*].id
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name_prefix}-api"
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.this.id

  health_check {
    enabled             = true
    path                = var.health_check_path
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_target_group" "ai" {
  name        = "${local.name_prefix}-ai"
  port        = var.ai_container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.this.id

  health_check {
    enabled             = true
    path                = var.ai_health_check_path
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = local.enable_https ? [] : [1]

    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.api.arn
    }
  }

  dynamic "default_action" {
    for_each = local.enable_https ? [1] : []

    content {
      type = "redirect"

      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count = local.enable_https ? 1 : 0

  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.alb_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener_rule" "api_host" {
  count = local.enable_api_host_rule ? 1 : 0

  listener_arn = aws_lb_listener.https[0].arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    host_header {
      values = [var.api_domain_name]
    }
  }
}

resource "aws_lb_listener_rule" "ai_host" {
  count = local.enable_ai_host_rule ? 1 : 0

  listener_arn = aws_lb_listener.https[0].arn
  priority     = 110

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ai.arn
  }

  condition {
    host_header {
      values = [var.ai_domain_name]
    }
  }
}

resource "aws_ecr_repository" "api" {
  name                 = "${local.name_prefix}-api"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "worker" {
  name                 = "${local.name_prefix}-worker"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_sqs_queue" "jobs_dlq" {
  name                      = "${local.name_prefix}-jobs-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "jobs" {
  name                       = "${local.name_prefix}-jobs"
  visibility_timeout_seconds = 300

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_s3_bucket" "app" {
  bucket = local.app_bucket_name
}

resource "aws_s3_bucket_public_access_block" "app" {
  bucket = aws_s3_bucket.app.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "app" {
  bucket = aws_s3_bucket.app.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/${var.project_name}/${var.environment}/api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/${var.project_name}/${var.environment}/worker"
  retention_in_days = 14
}

data "aws_iam_policy_document" "firehose_assume_role" {
  count = var.grafana_logs_enabled ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "firehose" {
  count = var.grafana_logs_enabled ? 1 : 0

  name               = "${local.name_prefix}-grafana-logs-firehose"
  assume_role_policy = data.aws_iam_policy_document.firehose_assume_role[0].json
}

data "aws_iam_policy_document" "firehose" {
  count = var.grafana_logs_enabled ? 1 : 0

  statement {
    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetBucketLocation",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:PutObject"
    ]
    resources = [
      aws_s3_bucket.app.arn,
      "${aws_s3_bucket.app.arn}/grafana-logs-failed/*"
    ]
  }

  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.grafana_logs_secret_arn]
  }
}

resource "aws_iam_role_policy" "firehose" {
  count = var.grafana_logs_enabled ? 1 : 0

  name   = "${local.name_prefix}-grafana-logs-firehose"
  role   = aws_iam_role.firehose[0].id
  policy = data.aws_iam_policy_document.firehose[0].json
}

resource "aws_kinesis_firehose_delivery_stream" "grafana_logs" {
  count = var.grafana_logs_enabled ? 1 : 0

  name        = "${local.name_prefix}-grafana-logs"
  destination = "http_endpoint"

  http_endpoint_configuration {
    url                = var.grafana_logs_endpoint
    name               = "Grafana Cloud AWS Logs"
    buffering_size     = 1
    buffering_interval = 60
    role_arn           = aws_iam_role.firehose[0].arn
    s3_backup_mode     = "FailedDataOnly"

    secrets_manager_configuration {
      enabled    = true
      role_arn   = aws_iam_role.firehose[0].arn
      secret_arn = var.grafana_logs_secret_arn
    }

    request_configuration {
      content_encoding = "GZIP"

      common_attributes {
        name  = "lbl_project"
        value = var.project_name
      }

      common_attributes {
        name  = "lbl_environment"
        value = var.environment
      }
    }

    s3_configuration {
      role_arn           = aws_iam_role.firehose[0].arn
      bucket_arn         = aws_s3_bucket.app.arn
      prefix             = "grafana-logs-failed/"
      buffering_size     = 5
      buffering_interval = 300
      compression_format = "GZIP"
    }
  }

  lifecycle {
    precondition {
      condition     = length(trimspace(var.grafana_logs_endpoint)) > 0
      error_message = "grafana_logs_endpoint is required when grafana_logs_enabled is true."
    }

    precondition {
      condition     = length(trimspace(var.grafana_logs_secret_arn)) > 0
      error_message = "grafana_logs_secret_arn is required when grafana_logs_enabled is true."
    }
  }
}

data "aws_iam_policy_document" "logs_subscription_assume_role" {
  count = var.grafana_logs_enabled ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["logs.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/${var.project_name}/${var.environment}/*"]
    }
  }
}

resource "aws_iam_role" "logs_subscription" {
  count = var.grafana_logs_enabled ? 1 : 0

  name               = "${local.name_prefix}-grafana-logs-subscription"
  assume_role_policy = data.aws_iam_policy_document.logs_subscription_assume_role[0].json
}

data "aws_iam_policy_document" "logs_subscription" {
  count = var.grafana_logs_enabled ? 1 : 0

  statement {
    actions   = ["firehose:PutRecord"]
    resources = [aws_kinesis_firehose_delivery_stream.grafana_logs[0].arn]
  }
}

resource "aws_iam_role_policy" "logs_subscription" {
  count = var.grafana_logs_enabled ? 1 : 0

  name   = "${local.name_prefix}-grafana-logs-subscription"
  role   = aws_iam_role.logs_subscription[0].id
  policy = data.aws_iam_policy_document.logs_subscription[0].json
}

resource "aws_cloudwatch_log_subscription_filter" "grafana_logs" {
  for_each = var.grafana_logs_enabled ? {
    api    = aws_cloudwatch_log_group.api.name
    worker = aws_cloudwatch_log_group.worker.name
  } : {}

  name            = "${local.name_prefix}-${each.key}-grafana-logs"
  role_arn        = aws_iam_role.logs_subscription[0].arn
  log_group_name  = each.value
  filter_pattern  = ""
  destination_arn = aws_kinesis_firehose_delivery_stream.grafana_logs[0].arn
  distribution    = "ByLogStream"
}

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_ssm" {
  statement {
    actions = ["ssm:GetParameters"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_path}/*"
    ]
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "execution_ssm" {
  name   = "${local.name_prefix}-ssm"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_ssm.json
}

resource "aws_iam_role" "api_task" {
  name               = "${local.name_prefix}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

resource "aws_iam_role" "worker_task" {
  name               = "${local.name_prefix}-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

data "aws_iam_policy_document" "api_task" {
  statement {
    actions = [
      "sqs:GetQueueAttributes",
      "sqs:SendMessage"
    ]
    resources = [aws_sqs_queue.jobs.arn]
  }

  statement {
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = ["${aws_s3_bucket.app.arn}/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.app.arn]
  }
}

resource "aws_iam_role_policy" "api_task" {
  name   = "${local.name_prefix}-api"
  role   = aws_iam_role.api_task.id
  policy = data.aws_iam_policy_document.api_task.json
}

data "aws_iam_policy_document" "worker_task" {
  statement {
    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ReceiveMessage"
    ]
    resources = [aws_sqs_queue.jobs.arn]
  }

  statement {
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = ["${aws_s3_bucket.app.arn}/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.app.arn]
  }
}

resource "aws_iam_role_policy" "worker_task" {
  name   = "${local.name_prefix}-worker"
  role   = aws_iam_role.worker_task.id
  policy = data.aws_iam_policy_document.worker_task.json
}

resource "aws_ecs_cluster" "this" {
  name = "${local.name_prefix}-cluster"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.api.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = concat([
        { name = "AWS_REGION", value = var.aws_region },
        { name = "ENVIRONMENT", value = var.environment },
        { name = "SENTRY_ENVIRONMENT", value = var.environment },
        { name = "SPRING_FLYWAY_BASELINE_ON_MIGRATE", value = "true" },
        { name = "SPRING_PROFILES_ACTIVE", value = var.environment },
        { name = "S3_BUCKET_NAME", value = aws_s3_bucket.app.bucket },
        { name = "SQS_JOBS_QUEUE_URL", value = aws_sqs_queue.jobs.url }
        ], var.grafana_otlp_enabled ? [
        { name = "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", value = "${trimsuffix(var.grafana_otlp_endpoint, "/")}/v1/metrics" },
        { name = "OTEL_TRACES_EXPORTER", value = "none" },
        { name = "OTEL_LOGS_EXPORTER", value = "none" },
        { name = "OTEL_SERVICE_NAME", value = "landit-be" },
        { name = "OTEL_RESOURCE_ATTRIBUTES", value = "service.namespace=landit,deployment.environment.name=${var.environment}" },
        { name = "MANAGEMENT_OTLP_METRICS_EXPORT_ENABLED", value = "true" },
        { name = "MANAGEMENT_OTLP_METRICS_EXPORT_STEP", value = "30s" }
      ] : [])

      secrets = concat([
        { name = "DB_URL", valueFrom = "${local.ssm_path}/DB_URL" },
        { name = "DB_USERNAME", valueFrom = "${local.ssm_path}/DB_USERNAME" },
        { name = "DB_PASSWORD", valueFrom = "${local.ssm_path}/DB_PASSWORD" },
        { name = "LANDIT_CORS_ALLOWED_ORIGINS", valueFrom = "${local.ssm_path}/LANDIT_CORS_ALLOWED_ORIGINS" },
        { name = "LANDIT_AUTH_TOKEN_SECRET", valueFrom = "${local.ssm_path}/LANDIT_AUTH_TOKEN_SECRET" },
        { name = "LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS", valueFrom = "${local.ssm_path}/LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS" },
        { name = "LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS", valueFrom = "${local.ssm_path}/LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS" },
        { name = "LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES", valueFrom = "${local.ssm_path}/LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES" },
        { name = "LANDIT_AUTH_OIDC_KAKAO_AUDIENCES", valueFrom = "${local.ssm_path}/LANDIT_AUTH_OIDC_KAKAO_AUDIENCES" },
        { name = "LANDIT_AUTH_OIDC_APPLE_AUDIENCES", valueFrom = "${local.ssm_path}/LANDIT_AUTH_OIDC_APPLE_AUDIENCES" },
        { name = "LANDIT_AI_CLIENT_MODE", valueFrom = "${local.ssm_path}/LANDIT_AI_CLIENT_MODE" },
        { name = "LANDIT_AI_BASE_URL", valueFrom = "${local.ssm_path}/LANDIT_AI_BASE_URL" },
        { name = "SENTRY_DSN", valueFrom = "${local.ssm_path}/LANDIT_BE_SENTRY_DSN" }
        ], var.grafana_otlp_enabled ? [
        { name = "OTEL_EXPORTER_OTLP_HEADERS", valueFrom = "${local.ssm_path}/LANDIT_GRAFANA_CLOUD_OTLP_HEADERS" }
      ] : [])

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  lifecycle {
    precondition {
      condition     = !var.grafana_otlp_enabled || length(trimspace(var.grafana_otlp_endpoint)) > 0
      error_message = "grafana_otlp_endpoint is required when grafana_otlp_enabled is true."
    }
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker_task.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = "${aws_ecr_repository.worker.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = var.ai_container_port
          protocol      = "tcp"
        }
      ]

      environment = concat([
        { name = "AWS_REGION", value = var.aws_region },
        { name = "ENVIRONMENT", value = var.environment },
        { name = "APP_ENV", value = var.environment },
        { name = "S3_BUCKET_NAME", value = aws_s3_bucket.app.bucket },
        { name = "SQS_JOBS_QUEUE_URL", value = aws_sqs_queue.jobs.url }
        ], var.grafana_otlp_enabled ? [
        { name = "OTEL_METRICS_ENABLED", value = "true" },
        { name = "OTEL_EXPORTER_OTLP_PROTOCOL", value = "http/protobuf" },
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = var.grafana_otlp_endpoint },
        { name = "OTEL_TRACES_EXPORTER", value = "none" },
        { name = "OTEL_LOGS_EXPORTER", value = "none" },
        { name = "OTEL_SERVICE_NAME", value = "landit-ai" },
        { name = "OTEL_RESOURCE_ATTRIBUTES", value = "service.namespace=landit,deployment.environment.name=${var.environment}" }
      ] : [])

      secrets = concat([
        { name = "DB_URL", valueFrom = "${local.ssm_path}/DB_URL" },
        { name = "DB_USERNAME", valueFrom = "${local.ssm_path}/DB_USERNAME" },
        { name = "DB_PASSWORD", valueFrom = "${local.ssm_path}/DB_PASSWORD" },
        { name = "LLM_PROVIDER", valueFrom = "${local.ssm_path}/LLM_PROVIDER" },
        { name = "OPENROUTER_BASE_URL", valueFrom = "${local.ssm_path}/OPENROUTER_BASE_URL" },
        { name = "OPENROUTER_MODEL", valueFrom = "${local.ssm_path}/OPENROUTER_MODEL" },
        { name = "MESSAGE_FEEDBACK_MODEL", valueFrom = "${local.ssm_path}/MESSAGE_FEEDBACK_MODEL" },
        { name = "MESSAGE_FEEDBACK_REVIEW_ENABLED", valueFrom = "${local.ssm_path}/MESSAGE_FEEDBACK_REVIEW_ENABLED" },
        { name = "OPENROUTER_API_KEY", valueFrom = "${local.ssm_path}/OPENROUTER_API_KEY" },
        { name = "SENTRY_DSN", valueFrom = "${local.ssm_path}/LANDIT_AI_SENTRY_DSN" }
        ], var.grafana_otlp_enabled ? [
        { name = "OTEL_EXPORTER_OTLP_HEADERS", valueFrom = "${local.ssm_path}/LANDIT_GRAFANA_CLOUD_OTLP_HEADERS" }
      ] : [])

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.worker.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  lifecycle {
    precondition {
      condition     = !var.grafana_otlp_enabled || length(trimspace(var.grafana_otlp_endpoint)) > 0
      error_message = "grafana_otlp_endpoint is required when grafana_otlp_enabled is true."
    }
  }
}

resource "aws_ecs_service" "api" {
  name                              = "${local.name_prefix}-api"
  cluster                           = aws_ecs_cluster.this.id
  task_definition                   = aws_ecs_task_definition.api.arn
  desired_count                     = var.api_desired_count
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = var.api_health_check_grace_period_seconds
  wait_for_steady_state             = false
  enable_execute_command            = false

  network_configuration {
    subnets          = values(aws_subnet.public)[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "worker" {
  name                              = "${local.name_prefix}-worker"
  cluster                           = aws_ecs_cluster.this.id
  task_definition                   = aws_ecs_task_definition.worker.arn
  desired_count                     = var.worker_desired_count
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = local.enable_ai_host_rule ? var.ai_health_check_grace_period_seconds : null
  wait_for_steady_state             = false
  enable_execute_command            = false

  network_configuration {
    subnets          = values(aws_subnet.public)[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  dynamic "load_balancer" {
    for_each = local.enable_ai_host_rule ? [1] : []

    content {
      target_group_arn = aws_lb_target_group.ai.arn
      container_name   = "worker"
      container_port   = var.ai_container_port
    }
  }

  depends_on = [aws_lb_listener_rule.ai_host]
}
