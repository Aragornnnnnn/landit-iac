#!/usr/bin/env bash
# WAF logging과 Athena 분석 Terraform 계약을 검증한다.

set -euo pipefail

MODULE_FILE="modules/app-platform/main.tf"
OUTPUT_FILE="modules/app-platform/outputs.tf"

grep -q 'resource "aws_s3_bucket" "waf_logs"' "${MODULE_FILE}"
grep -q 'bucket = "aws-waf-logs-' "${MODULE_FILE}"
grep -q 'resource "aws_s3_bucket_policy" "waf_logs"' "${MODULE_FILE}"
grep -q 'Service = "delivery.logs.amazonaws.com"' "${MODULE_FILE}"
grep -q 'resource "aws_wafv2_web_acl_logging_configuration" "alb"' "${MODULE_FILE}"
grep -q 'default_behavior = "DROP"' "${MODULE_FILE}"
grep -q 'action_condition' "${MODULE_FILE}"
grep -q 'name = "authorization"' "${MODULE_FILE}"
grep -q 'name = "cookie"' "${MODULE_FILE}"
grep -q 'name = "x-api-key"' "${MODULE_FILE}"
grep -q 'query_string {}' "${MODULE_FILE}"
grep -q 'resource "aws_glue_catalog_table" "waf_logs"' "${MODULE_FILE}"
grep -q '"projection.log_time.format"        = "yyyy/MM/dd/HH/mm"' "${MODULE_FILE}"
grep -q '"projection.log_time.range"         = "2026/07/25/00/00,NOW"' "${MODULE_FILE}"
grep -q 'resource "aws_athena_named_query" "waf_recent_matches"' "${MODULE_FILE}"
grep -q 'output "waf_logs_athena_named_query_id"' "${OUTPUT_FILE}"
