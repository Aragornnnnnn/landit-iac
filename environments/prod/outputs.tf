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

output "push_notifications_queue_url" {
  description = "Production Push notifications SQS queue URL."
  value       = module.app_platform.push_notifications_queue_url
}

output "push_notifications_dlq_url" {
  description = "Production Push notifications dead-letter queue URL."
  value       = module.app_platform.push_notifications_dlq_url
}

output "review_reminder_scheduler_arn" {
  description = "Production review reminder EventBridge Scheduler ARN."
  value       = module.app_platform.review_reminder_scheduler_arn
}

output "alb_access_logs_athena_workgroup" {
  description = "Production Athena workgroup for ALB access log analysis."
  value       = module.app_platform.alb_access_logs_athena_workgroup
}

output "alb_access_logs_athena_named_query_id" {
  description = "Production Athena named query ID for recent ALB 4xx analysis."
  value       = module.app_platform.alb_access_logs_athena_named_query_id
}

output "app_bucket_name" {
  description = "Production private application S3 bucket name."
  value       = module.app_platform.app_bucket_name
}

output "sentry_discord_relay_webhook_url" {
  description = "Sentry webhook endpoint backed by asynchronous API Gateway integration."
  value       = "${aws_api_gateway_stage.sentry_discord_relay.invoke_url}/"
  sensitive   = true
}
