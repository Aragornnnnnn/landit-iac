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

variable "content_upload_allowed_origins" {
  description = "Browser origins allowed to upload shared content images directly to S3."
  type        = list(string)
  default = [
    "https://landit.im",
    "https://develop.landit.im",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://10.0.2.2:3000",
    "http://172.16.103.142:3000",
    "http://192.168.219.107:3000"
  ]
}
