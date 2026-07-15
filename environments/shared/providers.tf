# 공유 콘텐츠 Terraform root의 AWS provider를 설정한다.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}
