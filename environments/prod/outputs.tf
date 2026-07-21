# 운영 환경의 주요 application platform 출력값을 정의한다.
output "alb_dns_name" {
  description = "Production ALB DNS name."
  value       = module.app_platform.alb_dns_name
}

output "alb_zone_id" {
  description = "Production ALB hosted zone ID."
  value       = module.app_platform.alb_zone_id
}

output "api_domain_name" {
  description = "Production backend API host name."
  value       = module.app_platform.api_domain_name
}

output "ai_domain_name" {
  description = "Production AI host name."
  value       = module.app_platform.ai_domain_name
}

output "api_ecr_repository_url" {
  description = "Production API ECR repository URL."
  value       = module.app_platform.api_ecr_repository_url
}

output "worker_ecr_repository_url" {
  description = "Production worker ECR repository URL."
  value       = module.app_platform.worker_ecr_repository_url
}

output "jobs_queue_url" {
  description = "Production SQS jobs queue URL."
  value       = module.app_platform.jobs_queue_url
}

output "app_bucket_name" {
  description = "Production private application S3 bucket name."
  value       = module.app_platform.app_bucket_name
}

output "sentry_discord_relay_function_url" {
  description = "Production Sentry Internal Integration webhook endpoint."
  value       = aws_lambda_function_url.sentry_discord_relay.function_url
  sensitive   = true
}

output "sentry_discord_relay_webhook_url" {
  description = "Sentry webhook endpoint backed by asynchronous API Gateway integration."
  value       = "${aws_api_gateway_stage.sentry_discord_relay.invoke_url}/"
  sensitive   = true
}
