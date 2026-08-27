#!/usr/bin/env bash
# Terraform Actions OIDC bootstrap의 최소 권한과 저장 경계를 검증한다.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAP_DIR="${ROOT_DIR}/bootstrap/terraform-actions"

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
assert_contains "${bootstrap}" 'actions   = ["iam:PassRole"]' "PassRole 권한을 별도 statement로 제한해야 한다."
assert_contains "${bootstrap}" 'variable = "iam:PassedToService"' "PassRole 대상 AWS service를 제한해야 한다."
assert_contains "${bootstrap}" 'arn:aws:ssm:${var.aws_region}::parameter/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64' "develop의 SSM 값 조회를 공용 AMI parameter로 제한해야 한다."
assert_not_contains "${bootstrap}" 'AdministratorAccess' "AdministratorAccess를 사용하면 안 된다."
assert_not_contains "${bootstrap}" 'PowerUserAccess' "PowerUserAccess를 사용하면 안 된다."
assert_not_contains "${bootstrap}" 'ReadOnlyAccess' "AWS 관리형 ReadOnlyAccess를 사용하면 안 된다."
assert_not_contains "${bootstrap}" '"iam:*"' "iam wildcard action을 사용하면 안 된다."

ssm_get_parameter_count="$(grep -F '"ssm:GetParameter"' "${BOOTSTRAP_DIR}"/*.tf | wc -l | tr -d ' ')"
if [ "${ssm_get_parameter_count}" != "1" ]; then
  echo "계약 위반. ssm:GetParameter는 공용 AMI 전용 statement에만 있어야 한다." >&2
  exit 1
fi

role_block="$(sed -n '/resource "aws_iam_role" "terraform" {/,/resource "aws_s3_bucket" "plans" {/p' "${BOOTSTRAP_DIR}/main.tf")"
assert_contains "${role_block}" 'for_each = local.role_bindings' "역할을 target과 phase 조합으로 생성해야 한다."
assert_contains "${role_block}" '"${var.project_name}-iac-terraform-${each.value.phase}-${each.value.target}"' "역할 이름에 phase와 target을 포함해야 한다."

echo "Terraform Actions OIDC bootstrap 계약이 통과했다."
