# 운영 Terraform root의 Terraform 및 provider 버전 제약을 정의한다.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4, < 3.0"
    }

    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }
}
