# 운영 Terraform root의 공통 이름과 태그 후보를 계산한다.
locals {
  name_prefix = "${var.environment}-${var.project_name}"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Repository  = "landit-iac"
  }
}
