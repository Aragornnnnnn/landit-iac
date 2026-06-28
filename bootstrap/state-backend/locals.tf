# Terraform state bucket bootstrap root의 공통 태그를 계산한다.
locals {
  common_tags = {
    Project    = var.project_name
    ManagedBy  = "terraform"
    Repository = "landit-iac"
    Purpose    = "terraform-state"
  }
}
