#!/usr/bin/env bash
# 운영 AI ECS 태스크의 CPU와 메모리 용량 계약을 검증한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROD_VARIABLES="${ROOT_DIR}/environments/prod/variables.tf"

worker_cpu_block="$(sed -n '/variable "worker_cpu" {/,/^}/p' "${PROD_VARIABLES}")"
worker_memory_block="$(sed -n '/variable "worker_memory" {/,/^}/p' "${PROD_VARIABLES}")"
worker_count_block="$(sed -n '/variable "worker_desired_count" {/,/^}/p' "${PROD_VARIABLES}")"

rg -q 'default[[:space:]]*=[[:space:]]*1024' <<<"${worker_cpu_block}"
rg -q 'default[[:space:]]*=[[:space:]]*2048' <<<"${worker_memory_block}"
rg -q 'default[[:space:]]*=[[:space:]]*1' <<<"${worker_count_block}"
