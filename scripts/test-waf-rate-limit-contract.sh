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

assert_equals() {
  local actual="$1"
  local expected="$2"
  local message="$3"

  if [[ "${actual}" != "${expected}" ]]; then
    echo "계약 위반. ${message}" >&2
    exit 1
  fi
}

rate_rule="$(rule_block "ip-rate-limit")"
common_rule="$(rule_block "aws-managed-common")"
ip_reputation_rule="$(rule_block "aws-managed-ip-reputation")"
label_block_rule="$(sed -n '/name     = "common-label-block"/,/^  rule {/p' "${MODULE_FILE}")"
label_block_keys="$(sed -n 's/^[[:space:]]*key[[:space:]]*=[[:space:]]*"\([^"]*\)".*$/\1/p' <<<"${label_block_rule}" | sort)"
expected_label_block_keys="$(printf '%s\n' \
  'awswaf:managed:aws:core-rule-set:BadBots_Header' \
  'awswaf:managed:aws:core-rule-set:GenericLFI_URIPath' \
  'awswaf:managed:aws:core-rule-set:RestrictedExtensions_URIPath')"
prod_main="$(<"${PROD_MAIN_FILE}")"

assert_contains "$(sed -n '/resource "aws_wafv2_web_acl" "alb" {/,/^}/p' "${MODULE_FILE}")" 'name  = "${local.name_prefix}-alb-count"' "Web ACL 이름을 변경하면 안 된다."
assert_contains "${rate_rule}" 'block {}' "ip-rate-limit은 Block action이어야 한다."
assert_not_contains "${rate_rule}" 'count {}' "ip-rate-limit에는 Count action이 남으면 안 된다."
assert_contains "${rate_rule}" 'aggregate_key_type    = "IP"' "IP 집계 기준을 유지해야 한다."
assert_contains "${rate_rule}" 'evaluation_window_sec = 300' "5분 평가 구간을 유지해야 한다."
assert_contains "${rate_rule}" 'limit                 = var.waf_rate_limit' "기존 2,000회 limit 변수를 유지해야 한다."
assert_contains "${prod_main}" 'waf_rate_limit                = 2000' "prod rate limit은 2,000회여야 한다."
assert_contains "${common_rule}" 'count {}' "Common Rule Set은 Count를 유지해야 한다."
assert_contains "${ip_reputation_rule}" 'none {}' "IP Reputation List는 AWS 관리형 기본 action을 사용해야 한다."
assert_not_contains "${ip_reputation_rule}" 'count {}' "IP Reputation List에 Count override가 남으면 안 된다."
assert_contains "${label_block_rule}" 'name     = "common-label-block"' "Common Label Block 규칙을 유지해야 한다."
assert_contains "${label_block_rule}" 'priority = 25' "Common Label Block은 IP Reputation 이후에 평가해야 한다."
assert_contains "${label_block_rule}" 'block {}' "선택한 Common Rule Set 라벨은 Block이어야 한다."
assert_equals "${label_block_keys}" "${expected_label_block_keys}" "Common Label Block은 승인된 세 라벨만 포함해야 한다."
assert_contains "${label_block_rule}" 'scope = "LABEL"' "Label Match scope는 LABEL이어야 한다."
