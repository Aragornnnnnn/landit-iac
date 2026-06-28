# Terraform state bucket bootstrap root의 입력값을 정의한다.
variable "aws_region" {
  description = "AWS region for the Landit Terraform state bucket."
  type        = string
  default     = "ap-northeast-2"
}

variable "project_name" {
  description = "Short project name used in AWS resource names and tags."
  type        = string
  default     = "landit"
}

variable "state_bucket_name" {
  description = "S3 bucket name for Landit Terraform state."
  type        = string
  default     = "landit-terraform-state-982529430654"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "state_bucket_name must be a valid lowercase S3 bucket name."
  }
}
