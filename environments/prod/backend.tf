# 운영 Terraform state S3 backend를 정의한다.
terraform {
  backend "s3" {
    bucket              = "landit-terraform-state-944011958218"
    key                 = "prod/landit-iac/terraform.tfstate"
    region              = "ap-northeast-2"
    encrypt             = true
    use_lockfile        = true
    allowed_account_ids = ["944011958218"]
  }
}
