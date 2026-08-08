#!/usr/bin/env bash
# 개발 EC2 병행 인프라의 보안과 기존 리소스 보존 계약을 검증한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_OUTPUTS="${ROOT_DIR}/modules/app-platform/outputs.tf"
for output_name in vpc_id public_subnet_ids api_ecr_repository_arn worker_ecr_repository_arn app_bucket_arn jobs_queue_arn api_log_group_name worker_log_group_name; do
  rg -q "output \"${output_name}\"" "${MODULE_OUTPUTS}"
done

DEV_EC2="${ROOT_DIR}/environments/dev/ec2.tf"
test -f "${DEV_EC2}"
rg -q 'instance_type[[:space:]]*=[[:space:]]*var.dev_ec2_instance_type' "${DEV_EC2}"
rg -q 'default[[:space:]]*=[[:space:]]*"t3.small"' "${ROOT_DIR}/environments/dev/variables.tf"
rg -q 'http_tokens[[:space:]]*=[[:space:]]*"required"' "${DEV_EC2}"
rg -q 'http_put_response_hop_limit[[:space:]]*=[[:space:]]*2' "${DEV_EC2}"
rg -q 'cpu_credits[[:space:]]*=[[:space:]]*"standard"' "${DEV_EC2}"
rg -q 'encrypted[[:space:]]*=[[:space:]]*true' "${DEV_EC2}"
rg -q 'volume_size[[:space:]]*=[[:space:]]*20' "${DEV_EC2}"
if rg -q 'from_port[[:space:]]*=[[:space:]]*22' "${DEV_EC2}"; then
  echo '계약 위반. SSH 22번 포트를 열면 안 된다.' >&2
  exit 1
fi
