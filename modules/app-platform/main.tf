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

resource "aws_s3_bucket" "alb_access_logs" {
  count = var.alb_access_logs_enabled ? 1 : 0

  bucket = "${local.name_prefix}-alb-access-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "alb_access_logs" {
  count = var.alb_access_logs_enabled ? 1 : 0

  bucket = aws_s3_bucket.alb_access_logs[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "alb_access_logs" {
  count = var.alb_access_logs_enabled ? 1 : 0

  bucket = aws_s3_bucket.alb_access_logs[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_access_logs" {
  count = var.alb_access_logs_enabled ? 1 : 0

  bucket = aws_s3_bucket.alb_access_logs[0].id

  rule {
    id     = "expire-alb-access-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = var.alb_access_log_retention_days
    }
  }
}

resource "aws_s3_bucket_policy" "alb_access_logs" {
  count = var.alb_access_logs_enabled ? 1 : 0

  bucket = aws_s3_bucket.alb_access_logs[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowAlbAccessLogDelivery"
        Effect = "Allow"
        Principal = {
          Service = "logdelivery.elasticloadbalancing.amazonaws.com"
        }
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.alb_access_logs[0].arn}/alb/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          ArnLike = {
            "aws:SourceArn" = "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:loadbalancer/*"
          }
        }
      }
    ]
  })
}

resource "aws_glue_catalog_database" "alb_access_logs" {
  count = var.alb_access_logs_enabled ? 1 : 0

  name = "${replace(local.name_prefix, "-", "_")}_alb_access_logs"
}

resource "aws_glue_catalog_table" "alb_access_logs" {
  count = var.alb_access_logs_enabled ? 1 : 0

  name          = "alb_access_logs"
  database_name = aws_glue_catalog_database.alb_access_logs[0].name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL                       = "TRUE"
    "projection.enabled"           = "true"
    "projection.day.type"          = "date"
    "projection.day.range"         = "2026/07/01,NOW"
    "projection.day.format"        = "yyyy/MM/dd"
    "projection.day.interval"      = "1"
    "projection.day.interval.unit" = "DAYS"
    "storage.location.template"    = "s3://${aws_s3_bucket.alb_access_logs[0].bucket}/alb/AWSLogs/${data.aws_caller_identity.current.account_id}/elasticloadbalancing/${var.aws_region}/$${day}"
  }

  partition_keys {
    name = "day"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.alb_access_logs[0].bucket}/alb/AWSLogs/${data.aws_caller_identity.current.account_id}/elasticloadbalancing/${var.aws_region}/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    columns {
      name = "type"
      type = "string"
    }

    columns {
      name = "time"
      type = "string"
    }

    columns {
      name = "elb"
      type = "string"
    }

    columns {
      name = "client_ip"
      type = "string"
    }

    columns {
      name = "client_port"
      type = "int"
    }

    columns {
      name = "target_ip"
      type = "string"
    }

    columns {
      name = "target_port"
      type = "int"
    }

    columns {
      name = "request_processing_time"
      type = "double"
    }

    columns {
      name = "target_processing_time"
      type = "double"
    }

    columns {
      name = "response_processing_time"
      type = "double"
    }

    columns {
      name = "elb_status_code"
      type = "int"
    }

    columns {
      name = "target_status_code"
      type = "string"
    }

    columns {
      name = "received_bytes"
      type = "bigint"
    }

    columns {
      name = "sent_bytes"
      type = "bigint"
    }

    columns {
      name = "request_verb"
      type = "string"
    }

    columns {
      name = "request_url"
      type = "string"
    }

    columns {
      name = "request_proto"
      type = "string"
    }

    columns {
      name = "user_agent"
      type = "string"
    }

    columns {
      name = "ssl_cipher"
      type = "string"
    }

    columns {
      name = "ssl_protocol"
      type = "string"
    }

    columns {
      name = "target_group_arn"
      type = "string"
    }

    columns {
      name = "trace_id"
      type = "string"
    }

    columns {
      name = "domain_name"
      type = "string"
    }

    columns {
      name = "chosen_cert_arn"
      type = "string"
    }

    columns {
      name = "matched_rule_priority"
      type = "string"
    }

    columns {
      name = "request_creation_time"
      type = "string"
    }

    columns {
      name = "actions_executed"
      type = "string"
    }

    columns {
      name = "redirect_url"
      type = "string"
    }

    columns {
      name = "lambda_error_reason"
      type = "string"
    }

    columns {
      name = "target_port_list"
      type = "string"
    }

    columns {
      name = "target_status_code_list"
      type = "string"
    }

    columns {
      name = "classification"
      type = "string"
    }

    columns {
      name = "classification_reason"
      type = "string"
    }

    columns {
      name = "conn_trace_id"
      type = "string"
    }

    ser_de_info {
      name                  = "alb-access-logs-regex"
      serialization_library = "org.apache.hadoop.hive.serde2.RegexSerDe"

      parameters = {
        "serialization.format" = "1"
        "input.regex"          = <<-REGEX
          ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*):([0-9]*) ([^ ]*)[:-]([0-9]*) ([-.0-9]*) ([-.0-9]*) ([-.0-9]*) (|[-0-9]*) (-|[-0-9]*) ([-0-9]*) ([-0-9]*) "([^ ]*) (.*) (- |[^ ]*)" "([^"]*)" ([A-Z0-9-_]+) ([A-Za-z0-9.-]*) ([^ ]*) "([^"]*)" "([^"]*)" "([^"]*)" ([-.0-9]*) ([^ ]*) "([^"]*)" "([^"]*)" "([^ ]*)" "([^\s]+?)" "([^\s]+)" "([^ ]*)" "([^ ]*)" ?([^ ]*)? ?( .*)?
        REGEX
      }
    }
  }
}

resource "aws_athena_workgroup" "alb_access_logs" {
  count = var.alb_access_logs_enabled ? 1 : 0

  name = "${local.name_prefix}-alb-access-logs"

  configuration {
    enforce_workgroup_configuration = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.alb_access_logs[0].bucket}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

resource "aws_athena_named_query" "alb_4xx_analysis" {
  count = var.alb_access_logs_enabled ? 1 : 0

  name        = "${local.name_prefix}-alb-4xx-analysis"
  description = "최근 3일 ALB 4xx 요청의 호출 원본과 응답 상태를 확인합니다."
  database    = aws_glue_catalog_database.alb_access_logs[0].name
  workgroup   = aws_athena_workgroup.alb_access_logs[0].id
  query       = <<-SQL
    SELECT
      from_iso8601_timestamp(time) AT TIME ZONE 'Asia/Seoul' AS time_kst,
      client_ip,
      request_verb,
      request_url,
      elb_status_code,
      target_status_code,
      user_agent
    FROM alb_access_logs
    WHERE day BETWEEN date_format(current_date - INTERVAL '2' DAY, '%Y/%m/%d')
                  AND date_format(current_date, '%Y/%m/%d')
      AND elb_status_code BETWEEN 400 AND 499
    ORDER BY time_kst DESC
    LIMIT 1000
  SQL
}

resource "aws_lb" "api" {
  name               = "${local.name_prefix}-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = values(aws_subnet.public)[*].id

  dynamic "access_logs" {
    for_each = var.alb_access_logs_enabled ? [1] : []

    content {
      bucket  = aws_s3_bucket.alb_access_logs[0].bucket
      prefix  = "alb"
      enabled = true
    }
  }

  depends_on = [aws_s3_bucket_policy.alb_access_logs]
}

resource "aws_wafv2_web_acl" "alb" {
  count = var.waf_count_enabled ? 1 : 0

  name  = "${local.name_prefix}-alb-count"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "aws-managed-common"
    priority = 10

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-managed-ip-reputation"
    priority = 20

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAmazonIpReputationList"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "ip-rate-limit"
    priority = 30

    action {
      count {}
    }

    statement {
      rate_based_statement {
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300
        limit                 = var.waf_rate_limit
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-ip-rate"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name_prefix}-waf"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  count = var.waf_count_enabled ? 1 : 0

  resource_arn = aws_lb.api.arn
  web_acl_arn  = aws_wafv2_web_acl.alb[0].arn
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
