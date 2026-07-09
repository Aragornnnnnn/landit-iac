# ECS 기반 Landit application platform module의 입력값을 정의한다.
variable "project_name" {
  description = "Short project name used in AWS resource names and tags."
  type        = string
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
}

variable "aws_region" {
  description = "AWS region for the platform."
  type        = string
}

variable "parameter_store_path" {
  description = "SSM Parameter Store path for runtime configuration."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the new VPC."
  type        = string
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_cidrs) >= 2
    error_message = "At least two public subnets are required for ALB."
  }
}

variable "container_port" {
  description = "API container port."
  type        = number
  default     = 8080
}

variable "api_domain_name" {
  description = "Host name routed to the backend API target group."
  type        = string
  default     = ""
}

variable "ai_domain_name" {
  description = "Host name routed to the AI target group."
  type        = string
  default     = ""
}

variable "ai_container_port" {
  description = "AI container port."
  type        = number
  default     = 8000
}

variable "health_check_path" {
  description = "ALB target group health check path."
  type        = string
  default     = "/actuator/health"
}

variable "ai_health_check_path" {
  description = "AI target group health check path."
  type        = string
  default     = "/health"
}

variable "api_health_check_grace_period_seconds" {
  description = "Health check grace period seconds for the API ECS service."
  type        = number
  default     = 180
}

variable "ai_health_check_grace_period_seconds" {
  description = "Health check grace period seconds for the AI ECS service."
  type        = number
  default     = 60
}

variable "api_cpu" {
  description = "Fargate CPU units for the API task."
  type        = number
  default     = 256
}

variable "api_memory" {
  description = "Fargate memory MiB for the API task."
  type        = number
  default     = 512
}

variable "worker_cpu" {
  description = "Fargate CPU units for the worker task."
  type        = number
  default     = 256
}

variable "worker_memory" {
  description = "Fargate memory MiB for the worker task."
  type        = number
  default     = 512
}

variable "api_desired_count" {
  description = "Desired API task count."
  type        = number
  default     = 1
}

variable "worker_desired_count" {
  description = "Desired worker task count."
  type        = number
  default     = 1
}

variable "alb_certificate_arn" {
  description = "Optional ACM certificate ARN. When set, ALB enables HTTPS and redirects HTTP to HTTPS."
  type        = string
  default     = null
}
