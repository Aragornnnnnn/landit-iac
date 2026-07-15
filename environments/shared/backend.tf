# 공유 콘텐츠 Terraform state S3 backend를 정의한다.
terraform {
  backend "s3" {
    bucket       = "landit-terraform-state-982529430654"
    key          = "shared/landit-iac/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
