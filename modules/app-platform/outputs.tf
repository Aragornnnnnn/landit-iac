# ECS 기반 Landit application platform module의 출력값을 정의한다.
output "alb_dns_name" {
  description = "ALB DNS name for public service routing."
  value       = aws_lb.api.dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID for alias records."
  value       = aws_lb.api.zone_id
}

output "api_domain_name" {
  description = "Backend API host name routed by ALB."
  value       = var.api_domain_name
}

output "ai_domain_name" {
  description = "AI host name routed by ALB."
  value       = var.ai_domain_name
}

output "api_ecr_repository_url" {
  description = "API ECR repository URL."
  value       = aws_ecr_repository.api.repository_url
}

output "worker_ecr_repository_url" {
  description = "Worker ECR repository URL."
  value       = aws_ecr_repository.worker.repository_url
}

output "jobs_queue_url" {
  description = "SQS jobs queue URL."
  value       = aws_sqs_queue.jobs.url
}

output "push_notifications_queue_url" {
  description = "Push notifications SQS queue URL."
  value       = aws_sqs_queue.push_notifications.url
}

output "push_notifications_dlq_url" {
  description = "Push notifications dead-letter queue URL."
  value       = aws_sqs_queue.push_notifications_dlq.url
}

output "review_reminder_scheduler_arn" {
  description = "Review reminder EventBridge Scheduler ARN."
  value       = aws_scheduler_schedule.review_reminder.arn
}

output "alb_access_logs_athena_workgroup" {
  description = "Athena workgroup for ALB access log analysis."
  value       = try(aws_athena_workgroup.alb_access_logs[0].name, null)
}

output "alb_access_logs_athena_named_query_id" {
  description = "Athena named query ID for recent ALB 4xx analysis."
  value       = try(aws_athena_named_query.alb_4xx_analysis[0].id, null)
}

output "app_bucket_name" {
  description = "Private application S3 bucket name."
  value       = aws_s3_bucket.app.bucket
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}
