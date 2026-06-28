# 운영 Terraform root의 공통 입력값 후보를 정의한다.
variable "aws_region" {
  description = "AWS region for the Landit production infrastructure. 결정 필요."
  type        = string
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
  description = "Candidate SSM Parameter Store path for production runtime configuration."
  type        = string
  default     = "/landit/prod"

  validation {
    condition     = startswith(var.parameter_store_path, "/") && !endswith(var.parameter_store_path, "/")
    error_message = "parameter_store_path must start with '/' and must not end with '/'."
  }
}
