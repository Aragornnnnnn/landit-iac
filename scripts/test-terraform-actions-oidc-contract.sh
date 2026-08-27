#!/usr/bin/env bash
# Terraform Actions OIDC bootstrap의 최소 권한과 저장 경계를 검증한다.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAP_DIR="${ROOT_DIR}/bootstrap/terraform-actions"
APP_MODULE="${ROOT_DIR}/modules/app-platform/main.tf"

assert_file() {
  local path="$1"

  if [ ! -f "${path}" ]; then
    echo "계약 위반. 파일이 필요하다: ${path}" >&2
    exit 1
  fi
}

assert_contains() {
  local content="$1"
  local pattern="$2"
  local message="$3"

  if ! grep -Fq "${pattern}" <<<"${content}"; then
    echo "계약 위반. ${message}" >&2
    exit 1
  fi
}

assert_not_contains() {
  local content="$1"
  local pattern="$2"
  local message="$3"

  if grep -Fq "${pattern}" <<<"${content}"; then
    echo "계약 위반. ${message}" >&2
    exit 1
  fi
}

for file in backend.tf versions.tf providers.tf variables.tf locals.tf main.tf outputs.tf; do
  assert_file "${BOOTSTRAP_DIR}/${file}"
done
assert_file "${APP_MODULE}"

bootstrap="$(find "${BOOTSTRAP_DIR}" -maxdepth 1 -name '*.tf' -type f -exec sed -n '1,$p' {} +)"

assert_contains "${bootstrap}" 'key          = "bootstrap/terraform-actions/terraform.tfstate"' "bootstrap state key가 분리되어야 한다."
assert_contains "${bootstrap}" 'data "aws_iam_openid_connect_provider" "github" {' "기존 GitHub OIDC provider를 조회해야 한다."
assert_not_contains "${bootstrap}" 'resource "aws_iam_openid_connect_provider"' "기존 OIDC provider를 중복 생성하면 안 된다."
assert_contains "${bootstrap}" 'values   = ["sts.amazonaws.com"]' "OIDC audience를 고정해야 한다."
assert_contains "${bootstrap}" 'repo:${var.github_owner}/${var.github_repository}:environment:terraform-${each.value.phase}-${each.value.target}' "role별 GitHub environment subject를 정확히 만들어야 한다."
assert_contains "${bootstrap}" 'for_each = local.role_bindings' "target과 phase 조합으로 역할 6개를 만들어야 한다."
assert_contains "${bootstrap}" 'block_public_acls       = true' "plan bucket public ACL을 차단해야 한다."
assert_contains "${bootstrap}" 'block_public_policy     = true' "plan bucket public policy를 차단해야 한다."
assert_contains "${bootstrap}" 'ignore_public_acls      = true' "plan bucket public ACL을 무시해야 한다."
assert_contains "${bootstrap}" 'restrict_public_buckets = true' "plan bucket public 접근을 제한해야 한다."
assert_contains "${bootstrap}" 'sse_algorithm = "AES256"' "plan bucket 기본 암호화를 사용해야 한다."
assert_contains "${bootstrap}" 'days = 1' "plan 객체를 1일 후 만료해야 한다."
assert_contains "${bootstrap}" '"s3:PutObject"' "state 또는 plan 업로드 권한이 필요하다."
assert_contains "${bootstrap}" '"s3:GetObject"' "state 또는 plan 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"s3:DeleteObject"' "lockfile 삭제 권한이 필요하다."
assert_contains "${bootstrap}" 'actions = ["iam:PassRole"]' "PassRole 권한을 별도 statement로 제한해야 한다."
assert_contains "${bootstrap}" 'variable = "iam:PassedToService"' "PassRole 대상 AWS service를 제한해야 한다."
assert_contains "${bootstrap}" 'arn:aws:ssm:${var.aws_region}::parameter/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64' "develop의 SSM 값 조회를 공용 AMI parameter로 제한해야 한다."
assert_contains "${bootstrap}" '"s3:GetLifecycleConfiguration"' "S3 lifecycle 조회 IAM action이 정확해야 한다."
assert_contains "${bootstrap}" '"s3:GetBucketOwnershipControls"' "shared bucket ownership 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"ec2:DescribeInstanceAttribute"' "develop aws_instance attribute 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"ec2:DescribeIamInstanceProfileAssociations"' "develop instance profile 연결 상태 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"ec2:DescribeVolumes"' "develop root volume 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"ec2:DescribeVolumesModifications"' "develop volume 변경 상태 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"ec2:DescribeVpcAttribute"' "VPC DNS attribute 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"ec2:DescribeAddressesAttribute"' "develop EIP domain attribute 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"ssm:DescribeDocumentPermission"' "develop SSM document permission 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"lambda:ListVersionsByFunction"' "production Lambda version 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"ec2:DescribeInstanceTypes"' "EC2 instance type 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"lambda:GetFunctionCodeSigningConfig"' "production Lambda code signing config 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"elasticloadbalancing:DescribeLoadBalancerAttributes"' "ALB attribute 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"elasticloadbalancing:DescribeTargetGroupAttributes"' "target group attribute 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"ec2:DescribeInstanceCreditSpecifications"' "EC2 credit specification 조회 권한이 필요하다."
assert_contains "${bootstrap}" '"elasticloadbalancing:DescribeListenerAttributes"' "listener attribute 조회 권한이 필요하다."
assert_contains "${bootstrap}" 'sid       = "ReadTargetBuckets"' "관리 대상 버킷의 존재 확인 권한을 별도 statement로 제한해야 한다."
assert_contains "${bootstrap}" 'resources = local.managed_bucket_arns_by_target[each.value.target]' "버킷 존재 확인 대상을 target별 ARN으로 제한해야 한다."
assert_contains "${bootstrap}" 'shared = []' "shared apply role은 AWS resource mutation을 허용하면 안 된다."
assert_contains "${bootstrap}" 'document/develop-${var.project_name}-ec2-deploy' "develop SSM document 변경 대상을 정확히 제한해야 한다."
assert_contains "${bootstrap}" 'service/prod-${var.project_name}-cluster/prod-${var.project_name}-api' "production ECS service 변경 대상을 정확히 제한해야 한다."
assert_contains "${bootstrap}" 'variable = "aws:RequestTag/Project"' "production task definition 등록을 project request tag로 제한해야 한다."
assert_contains "${bootstrap}" 'variable = "aws:RequestTag/Environment"' "production task definition 등록을 environment request tag로 제한해야 한다."
assert_contains "${bootstrap}" 'values   = ["prod"]' "production provider의 실제 Environment tag 값을 사용해야 한다."
assert_contains "${bootstrap}" 'values   = ["ecs-tasks.amazonaws.com"]' "PassRole을 ECS task service로만 제한해야 한다."
api_task_definition="$(sed -n '/resource "aws_ecs_task_definition" "api" {/,/^}/p' "${APP_MODULE}")"
assert_contains "${api_task_definition}" 'skip_destroy             = true' "API task definition은 wildcard Deregister 권한 없이 이전 revision을 유지해야 한다."
assert_not_contains "${bootstrap}" 'GetBucketLifecycleConfiguration' "S3 API 이름을 IAM action으로 사용하면 안 된다."
assert_not_contains "${bootstrap}" 'PutBucketLifecycleConfiguration' "S3 API 이름을 IAM action으로 사용하면 안 된다."
assert_not_contains "${bootstrap}" 'DeleteBucketCORS' "S3 CORS 삭제 API 이름을 IAM action으로 사용하면 안 된다."
assert_not_contains "${bootstrap}" 'DeleteBucketPublicAccessBlock' "S3 public access block 삭제 API 이름을 IAM action으로 사용하면 안 된다."
assert_not_contains "${bootstrap}" 'AdministratorAccess' "AdministratorAccess를 사용하면 안 된다."
assert_not_contains "${bootstrap}" 'PowerUserAccess' "PowerUserAccess를 사용하면 안 된다."
assert_not_contains "${bootstrap}" 'ReadOnlyAccess' "AWS 관리형 ReadOnlyAccess를 사용하면 안 된다."
assert_not_contains "${bootstrap}" '"iam:*"' "iam wildcard action을 사용하면 안 된다."
assert_not_contains "${bootstrap}" '"iam:PutRolePolicy"' "Actions apply role이 runtime role policy를 변경하면 안 된다."
assert_not_contains "${bootstrap}" '"ecs:DeregisterTaskDefinition"' "task definition 해제를 위한 account-wide mutation을 허용하면 안 된다."
assert_not_contains "${bootstrap}" '"s3:DeleteBucket"' "현재 saved plan에 필요하지 않은 bucket 삭제를 허용하면 안 된다."
assert_not_contains "${bootstrap}" '"iam:DeleteRole"' "현재 saved plan에 필요하지 않은 role 삭제를 허용하면 안 된다."
assert_not_contains "${bootstrap}" '"ec2:TerminateInstances"' "현재 saved plan에 필요하지 않은 instance 삭제를 허용하면 안 된다."

ssm_get_parameter_count="$(grep -F '"ssm:GetParameter"' "${BOOTSTRAP_DIR}"/*.tf | wc -l | tr -d ' ')"
if [ "${ssm_get_parameter_count}" != "1" ]; then
  echo "계약 위반. ssm:GetParameter는 공용 AMI 전용 statement에만 있어야 한다." >&2
  exit 1
fi

role_block="$(sed -n '/resource "aws_iam_role" "terraform" {/,/resource "aws_s3_bucket" "plans" {/p' "${BOOTSTRAP_DIR}/main.tf")"
assert_contains "${role_block}" 'for_each = local.role_bindings' "역할을 target과 phase 조합으로 생성해야 한다."
assert_contains "${role_block}" '"${var.project_name}-iac-terraform-${each.value.phase}-${each.value.target}"' "역할 이름에 phase와 target을 포함해야 한다."

manage_block="$(sed -n '/sid       = "ManageTargetResources"/,/^[[:space:]]*}/p' "${BOOTSTRAP_DIR}/main.tf")"
assert_contains "${manage_block}" 'resources = local.apply_resources_by_target[each.value.target]' "apply mutation은 target별 ARN으로 제한해야 한다."
assert_not_contains "${manage_block}" 'resources = ["*"]' "일반 apply mutation에 wildcard resource를 사용하면 안 된다."

echo "Terraform Actions OIDC bootstrap 계약이 통과했다."
