# Terraform Actions bootstrap의 GitHub environment 연결값을 출력한다.
output "plan_role_arns" {
  description = "OIDC role ARN for each Terraform plan environment."
  value = {
    for target in keys(local.target_state_keys) :
    target => aws_iam_role.terraform["plan-${target}"].arn
  }
}

output "apply_role_arns" {
  description = "OIDC role ARN for each Terraform apply environment."
  value = {
    for target in keys(local.target_state_keys) :
    target => aws_iam_role.terraform["apply-${target}"].arn
  }
}

output "plan_bucket_name" {
  description = "Private bucket used to transfer saved Terraform plans."
  value       = aws_s3_bucket.plans.bucket
}
