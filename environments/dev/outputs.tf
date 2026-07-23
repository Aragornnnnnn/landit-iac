# 개발 환경의 주요 application platform 출력값을 정의한다.
output "alb_dns_name" {
  description = "Development ALB DNS name."
  value       = module.app_platform.alb_dns_name
}

output "alb_zone_id" {
  description = "Development ALB hosted zone ID."
  value       = module.app_platform.alb_zone_id
}

output "api_domain_name" {
  description = "Development backend API host name."
  value       = module.app_platform.api_domain_name
}

output "ai_domain_name" {
  description = "Development AI host name."
  value       = module.app_platform.ai_domain_name
}

output "api_ecr_repository_url" {
  description = "Development API ECR repository URL."
  value       = module.app_platform.api_ecr_repository_url
}

output "worker_ecr_repository_url" {
  description = "Development worker ECR repository URL."
  value       = module.app_platform.worker_ecr_repository_url
}

output "jobs_queue_url" {
  description = "Development SQS jobs queue URL."
  value       = module.app_platform.jobs_queue_url
}

output "push_notifications_queue_url" {
  description = "Development Push notifications SQS queue URL."
  value       = module.app_platform.push_notifications_queue_url
}

output "push_notifications_dlq_url" {
  description = "Development Push notifications dead-letter queue URL."
  value       = module.app_platform.push_notifications_dlq_url
}

output "review_reminder_scheduler_arn" {
  description = "Development review reminder EventBridge Scheduler ARN."
  value       = module.app_platform.review_reminder_scheduler_arn
}

output "app_bucket_name" {
  description = "Development private application S3 bucket name."
  value       = module.app_platform.app_bucket_name
}
