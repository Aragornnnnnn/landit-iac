# 운영 Terraform root의 AWS provider 후보 설정을 정의한다.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}
