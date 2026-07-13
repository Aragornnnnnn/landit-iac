# 운영 Terraform root의 공통 입력값 후보를 정의한다.
variable "aws_region" {
  description = "AWS region for the Landit production infrastructure."
  type        = string
  default     = "ap-northeast-2"
}

variable "project_name" {
  description = "Short project name used in AWS resource names and tags."
  type        = string
  default     = "landit"
}

variable "environment" {
  description = "Deployment environment name used in tags."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["develop", "prod"], var.environment)
    error_message = "environment must be either 'develop' or 'prod'."
  }
}

variable "parameter_store_path" {
  description = "SSM Parameter Store path for production runtime configuration."
  type        = string
  default     = "/landit/prod"

  validation {
    condition     = startswith(var.parameter_store_path, "/") && !endswith(var.parameter_store_path, "/")
    error_message = "parameter_store_path must start with '/' and must not end with '/'."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the production VPC."
  type        = string
  default     = "10.10.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for production public subnets."
  type        = list(string)
  default     = ["10.10.0.0/24", "10.10.1.0/24"]
}

variable "container_port" {
  description = "API container port."
  type        = number
  default     = 8080
}

variable "api_domain_name" {
  description = "Production backend API host name."
  type        = string
  default     = "api.landit.im"
}

variable "ai_domain_name" {
  description = "Production AI host name."
  type        = string
  default     = "ai.landit.im"
}

variable "ai_container_port" {
  description = "Production AI container port."
  type        = number
  default     = 8000
}

variable "health_check_path" {
  description = "ALB health check path."
  type        = string
  default     = "/actuator/health"
}

variable "ai_health_check_path" {
  description = "Production AI health check path."
  type        = string
  default     = "/health"
}

variable "api_health_check_grace_period_seconds" {
  description = "Production API ECS health check grace period seconds."
  type        = number
  default     = 180
}

variable "ai_health_check_grace_period_seconds" {
  description = "Production AI ECS health check grace period seconds."
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
  description = "Desired production API task count."
  type        = number
  default     = 1
}

variable "worker_desired_count" {
  description = "Desired production worker task count."
  type        = number
  default     = 1
}

variable "alb_certificate_arn" {
  description = "Optional ACM certificate ARN for HTTPS."
  type        = string
  default     = "arn:aws:acm:ap-northeast-2:982529430654:certificate/c27457fe-4469-4944-a5d4-322569ddd549"
}

variable "grafana_cloud_external_id" {
  description = "External ID required when Grafana Cloud assumes the shared CloudWatch read role."
  type        = string
  default     = "3366938"

  validation {
    condition     = length(trimspace(var.grafana_cloud_external_id)) > 0
    error_message = "grafana_cloud_external_id must not be empty."
  }
}

variable "grafana_otlp_enabled" {
  description = "Whether to send production application metrics to Grafana Cloud OTLP."
  type        = bool
  default     = false
}

variable "grafana_otlp_endpoint" {
  description = "Production Grafana Cloud OTLP base endpoint."
  type        = string
  default     = ""
}

variable "grafana_logs_enabled" {
  description = "Whether to forward production CloudWatch Logs to Grafana Cloud."
  type        = bool
  default     = false
}

variable "grafana_logs_endpoint" {
  description = "Production Grafana Cloud AWS Logs ingest endpoint."
  type        = string
  default     = ""
}

variable "grafana_logs_secret_arn" {
  description = "Secrets Manager ARN containing production Grafana Logs authentication."
  type        = string
  default     = ""
}
