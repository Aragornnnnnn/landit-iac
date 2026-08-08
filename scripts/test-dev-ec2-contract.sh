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

USER_DATA="${ROOT_DIR}/environments/dev/templates/ec2-user-data.sh.tftpl"
COMPOSE="${ROOT_DIR}/environments/dev/templates/docker-compose.yml.tftpl"
CADDY="${ROOT_DIR}/environments/dev/templates/Caddyfile.tftpl"
test -f "${USER_DATA}"
test -f "${COMPOSE}"
test -f "${CADDY}"
rg -q 'LANDIT_AI_BASE_URL=http://ai:8000' "${USER_DATA}"
rg -q 'chmod 0600' "${USER_DATA}"
rg -q 'flock' "${USER_DATA}"
rg -q 'mkswap' "${USER_DATA}"
rg -q 'amazon-cloudwatch-agent' "${USER_DATA}"
rg -q 'mem_limit: 768m' "${COMPOSE}"
rg -q 'mem_limit: 512m' "${COMPOSE}"
rg -q '127.0.0.1:8080:8080' "${COMPOSE}"
rg -q '127.0.0.1:8000:8000' "${COMPOSE}"
rg -q 'awslogs-group' "${COMPOSE}"
rg -q 'reverse_proxy api:8080' "${CADDY}"
rg -q 'reverse_proxy ai:8000' "${CADDY}"
