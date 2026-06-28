# Terraform state bucket bootstrap root의 결과값을 정의한다.
output "state_bucket_name" {
  description = "S3 bucket name for Landit Terraform state."
  value       = aws_s3_bucket.terraform_state.bucket
}

output "development_state_key" {
  description = "Candidate S3 object key for development Terraform state."
  value       = "dev/landit-iac/terraform.tfstate"
}

output "production_state_key" {
  description = "Candidate S3 object key for production Terraform state."
  value       = "prod/landit-iac/terraform.tfstate"
}
