#!/usr/bin/env bash
# Terraform workflow의 private S3 plan 전달과 실행 제한을 검증한다.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW_FILE="${ROOT_DIR}/.github/workflows/terraform.yml"
workflow="$(<"${WORKFLOW_FILE}")"

assert_contains() {
  local pattern="$1"
  local message="$2"

  if ! grep -Fq "${pattern}" <<<"${workflow}"; then
    echo "계약 위반. ${message}" >&2
    exit 1
  fi
}

assert_not_contains() {
  local pattern="$1"
  local message="$2"

  if grep -Fq "${pattern}" <<<"${workflow}"; then
    echo "계약 위반. ${message}" >&2
    exit 1
  fi
}

assert_not_contains "actions/upload-artifact" "saved plan을 GitHub artifact에 올리면 안 된다."
assert_not_contains "actions/download-artifact" "saved plan을 GitHub artifact에서 받으면 안 된다."
assert_contains 'PLAN_BUCKET: landit-terraform-plan-artifacts-982529430654' "private plan bucket을 고정해야 한다."
assert_contains "if: \${{ inputs.operation == 'plan-only' }}" "plan-only를 speculative plan으로 분리해야 한다."
assert_contains 'plan -input=false' "plan-only는 저장 파일 없이 실행해야 한다."
assert_contains 'plans/${TARGET}/${GITHUB_RUN_ID}/${GITHUB_RUN_ATTEMPT}/${PLAN_FILE}' "plan key에 target과 run 식별자를 포함해야 한다."
assert_contains 'aws s3 cp "${PLAN_PATH}" "s3://${PLAN_BUCKET}/${PLAN_KEY}"' "saved plan을 private S3에 올려야 한다."
assert_contains 'aws s3 cp "s3://${PLAN_BUCKET}/${PLAN_KEY}" "${PLAN_PATH}"' "apply가 정확한 S3 plan을 내려받아야 한다."
assert_contains 'sha256sum "${PLAN_PATH}"' "saved plan SHA-256을 계산해야 한다."
assert_contains 'sha256sum --check --strict' "apply 전에 saved plan SHA-256을 검증해야 한다."
assert_contains "github.ref != 'refs/heads/main'" "apply를 main branch로 제한해야 한다."
assert_contains "inputs.confirm_environment != 'production'" "production 확인 문자열을 유지해야 한다."
assert_contains 'actions/checkout@11d5960a326750d5838078e36cf38b85af677262' "checkout action을 검증한 SHA로 고정해야 한다."
assert_contains 'hashicorp/setup-terraform@b9cd54a3c349d3f38e8881555d616ced269862dd' "Terraform setup action을 검증한 SHA로 고정해야 한다."
assert_contains 'aws-actions/configure-aws-credentials@ff717079ee2060e4bcee96c4779b553acc87447c' "AWS credential action을 검증한 SHA로 고정해야 한다."

echo "Terraform workflow private plan 계약이 통과했다."
