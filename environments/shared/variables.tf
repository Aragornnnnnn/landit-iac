# 공유 콘텐츠 Terraform root의 입력값을 정의한다.
variable "aws_region" {
  description = "AWS region for shared Landit content infrastructure."
  type        = string
  default     = "ap-northeast-2"
}

variable "project_name" {
  description = "Short project name used in shared resource names and tags."
  type        = string
  default     = "landit"
}
