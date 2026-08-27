# Terraform Actions bootstrap root의 입력값을 정의한다.
variable "aws_region" {
  description = "AWS region for Landit Terraform Actions resources."
  type        = string
  default     = "ap-northeast-2"
}

variable "project_name" {
  description = "Short project name used in AWS resource names and tags."
  type        = string
  default     = "landit"
}

variable "github_owner" {
  description = "GitHub organization or account that owns the IaC repository."
  type        = string
  default     = "Aragornnnnnn"
}

variable "github_repository" {
  description = "GitHub repository that runs Terraform Actions."
  type        = string
  default     = "landit-iac"
}

variable "state_bucket_name" {
  description = "S3 bucket that stores Landit Terraform state."
  type        = string
  default     = "landit-terraform-state-982529430654"
}

variable "plan_bucket_name" {
  description = "Private S3 bucket that temporarily stores saved Terraform plans."
  type        = string
  default     = "landit-terraform-plan-artifacts-982529430654"
}
