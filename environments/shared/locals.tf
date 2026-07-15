# 공유 콘텐츠 리소스 이름과 태그를 계산한다.
locals {
  name_prefix         = "${var.project_name}-shared"
  content_bucket_name = "${var.project_name}-content-${data.aws_caller_identity.current.account_id}"
  content_origin_id   = "content-s3"

  common_tags = {
    Project     = var.project_name
    Environment = "shared"
    ManagedBy   = "terraform"
    Repository  = "landit-iac"
  }
}
