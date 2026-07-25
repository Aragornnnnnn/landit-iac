#!/usr/bin/env bash
# prod WAF rate limit 차단 전환의 Terraform 계약을 검증한다.

set -euo pipefail

MODULE_FILE="modules/app-platform/main.tf"
PROD_MAIN_FILE="environments/prod/main.tf"

rule_block() {
  local rule_name="$1"

  sed -n "/name     = \"${rule_name}\"/,/^  }/p" "${MODULE_FILE}"
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

rate_rule="$(rule_block "ip-rate-limit")"
common_rule="$(rule_block "aws-managed-common")"
ip_reputation_rule="$(rule_block "aws-managed-ip-reputation")"
prod_main="$(<"${PROD_MAIN_FILE}")"

assert_contains "$(sed -n '/resource "aws_wafv2_web_acl" "alb" {/,/^}/p' "${MODULE_FILE}")" 'name  = "${local.name_prefix}-alb-count"' "Web ACL 이름을 변경하면 안 된다."
assert_contains "${rate_rule}" 'block {}' "ip-rate-limit은 Block action이어야 한다."
assert_not_contains "${rate_rule}" 'count {}' "ip-rate-limit에는 Count action이 남으면 안 된다."
assert_contains "${rate_rule}" 'aggregate_key_type    = "IP"' "IP 집계 기준을 유지해야 한다."
assert_contains "${rate_rule}" 'evaluation_window_sec = 300' "5분 평가 구간을 유지해야 한다."
assert_contains "${rate_rule}" 'limit                 = var.waf_rate_limit' "기존 2,000회 limit 변수를 유지해야 한다."
assert_contains "${prod_main}" 'waf_rate_limit                = 2000' "prod rate limit은 2,000회여야 한다."
assert_contains "${common_rule}" 'count {}' "Common Rule Set은 Count를 유지해야 한다."
assert_contains "${ip_reputation_rule}" 'count {}' "IP Reputation List는 Count를 유지해야 한다."
