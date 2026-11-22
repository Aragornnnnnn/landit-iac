# Terraform state bucket bootstrap root의 AWS provider 설정을 정의한다.
provider "aws" {
  region              = var.aws_region
  allowed_account_ids = ["944011958218"]

  default_tags {
    tags = local.common_tags
  }
}
