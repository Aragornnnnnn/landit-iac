#!/usr/bin/env bash
# Sentry relay API의 발신 IP 제한과 throttling 계약을 검사한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELAY_TF="${ROOT_DIR}/environments/prod/sentry-discord-relay.tf"

rg -q 'resource "aws_api_gateway_method_settings" "sentry_discord_relay"' "${RELAY_TF}"
rg -q 'throttling_rate_limit[[:space:]]*=[[:space:]]*1' "${RELAY_TF}"
rg -q 'throttling_burst_limit[[:space:]]*=[[:space:]]*5' "${RELAY_TF}"
rg -q 'resource "aws_api_gateway_rest_api_policy" "sentry_discord_relay"' "${RELAY_TF}"
rg -q 'aws_api_gateway_rest_api\.sentry_discord_relay\.execution_arn' "${RELAY_TF}"
rg -q 'variable[[:space:]]*=[[:space:]]*"aws:SourceIp"' "${RELAY_TF}"

for cidr in \
  35.184.238.160/32 \
  104.155.159.182/32 \
  104.155.149.19/32 \
  130.211.230.102/32 \
  34.125.65.3/32 \
  34.125.58.72/32 \
  8.228.7.8/32 \
  34.141.31.19/32 \
  34.141.4.162/32 \
  35.234.78.236/32; do
  rg -Fq "\"${cidr}\"" "${RELAY_TF}"
done
