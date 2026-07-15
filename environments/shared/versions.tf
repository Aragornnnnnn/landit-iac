# 공유 콘텐츠 root의 Terraform 및 provider 버전 제약을 정의한다.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }
}
