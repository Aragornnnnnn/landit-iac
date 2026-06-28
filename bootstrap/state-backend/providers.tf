# Terraform state bucket bootstrap root의 AWS provider 설정을 정의한다.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}
