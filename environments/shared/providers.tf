# 공유 콘텐츠 Terraform root의 AWS provider를 설정한다.
provider "aws" {
  region              = var.aws_region
  allowed_account_ids = ["944011958218"]

  default_tags {
    tags = local.common_tags
  }
}
