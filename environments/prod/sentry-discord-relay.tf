# Sentry prod issue alert를 Discord로 중계하는 Lambda 리소스를 정의한다.
data "aws_caller_identity" "current" {}

data "archive_file" "sentry_discord_relay" {
  type        = "zip"
  source_file = "${path.module}/lambda/sentry_discord_relay.py"
  output_path = "${path.root}/.terraform/sentry-discord-relay.zip"
}

locals {
  sentry_discord_relay_name = "${local.name_prefix}-sentry-discord-relay"
  sentry_relay_auth_parameter_name = (
    "${var.parameter_store_path}/LANDIT_SENTRY_RELAY_AUTH_TOKEN"
  )
  sentry_discord_webhook_parameter_name = (
    "${var.parameter_store_path}/LANDIT_SENTRY_DISCORD_WEBHOOK_URL"
  )
}

resource "aws_iam_role" "sentry_discord_relay" {
  name = local.sentry_discord_relay_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "sentry_discord_relay_logs" {
  role       = aws_iam_role.sentry_discord_relay.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "sentry_discord_relay_ssm" {
  name = "ssm-read"
  role = aws_iam_role.sentry_discord_relay.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameters"
        ]
        Resource = [
          "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.sentry_relay_auth_parameter_name}",
          "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.sentry_discord_webhook_parameter_name}",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.sentry_discord_relay_name}"
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "sentry_discord_relay" {
  name              = "/aws/lambda/${local.sentry_discord_relay_name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "sentry_discord_relay" {
  function_name = local.sentry_discord_relay_name
  role          = aws_iam_role.sentry_discord_relay.arn

  runtime       = "python3.13"
  architectures = ["arm64"]
  handler       = "sentry_discord_relay.lambda_handler"

  filename         = data.archive_file.sentry_discord_relay.output_path
  source_code_hash = data.archive_file.sentry_discord_relay.output_base64sha256

  memory_size                    = 512
  timeout                        = 10
  reserved_concurrent_executions = 2

  environment {
    variables = {
      AUTH_TOKEN_PARAMETER_NAME      = local.sentry_relay_auth_parameter_name
      DISCORD_WEBHOOK_PARAMETER_NAME = local.sentry_discord_webhook_parameter_name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.sentry_discord_relay,
    aws_iam_role_policy.sentry_discord_relay_ssm,
    aws_iam_role_policy_attachment.sentry_discord_relay_logs,
  ]
}

resource "aws_lambda_function_event_invoke_config" "sentry_discord_relay" {
  function_name                = aws_lambda_function.sentry_discord_relay.function_name
  maximum_event_age_in_seconds = 300
  maximum_retry_attempts       = 2
}

resource "aws_lambda_function_url" "sentry_discord_relay" {
  function_name      = aws_lambda_function.sentry_discord_relay.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "sentry_discord_relay_url" {
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.sentry_discord_relay.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "sentry_discord_relay_invoke" {
  statement_id             = "AllowPublicInvokeViaFunctionUrl"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.sentry_discord_relay.function_name
  principal                = "*"
  invoked_via_function_url = true
}
