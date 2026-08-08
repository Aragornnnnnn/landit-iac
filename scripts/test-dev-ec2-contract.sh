#!/usr/bin/env bash
# 개발 EC2 병행 인프라의 보안과 기존 리소스 보존 계약을 검증한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_OUTPUTS="${ROOT_DIR}/modules/app-platform/outputs.tf"
for output_name in vpc_id public_subnet_ids api_ecr_repository_arn worker_ecr_repository_arn app_bucket_arn jobs_queue_arn api_log_group_name worker_log_group_name; do
  rg -q "output \"${output_name}\"" "${MODULE_OUTPUTS}"
done
