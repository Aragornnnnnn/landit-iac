#!/usr/bin/env bash
# ALB access log를 Athena로 분석하는 Terraform 계약을 검증한다.

set -euo pipefail

MODULE_FILE="modules/app-platform/main.tf"
OUTPUT_FILE="modules/app-platform/outputs.tf"

grep -q 'resource "aws_glue_catalog_database" "alb_access_logs"' "${MODULE_FILE}"
grep -q 'resource "aws_glue_catalog_table" "alb_access_logs"' "${MODULE_FILE}"
grep -q '"projection.enabled"[[:space:]]*=[[:space:]]*"true"' "${MODULE_FILE}"
grep -q '"storage.location.template"' "${MODULE_FILE}"
grep -q 'resource "aws_athena_workgroup" "alb_access_logs"' "${MODULE_FILE}"
grep -q 'resource "aws_athena_named_query" "alb_4xx_analysis"' "${MODULE_FILE}"
grep -q 'resource "aws_athena_named_query" "alb_top_client_rate"' "${MODULE_FILE}"
grep -q 'elb_status_code BETWEEN 400 AND 499' "${MODULE_FILE}"
grep -q 'name = "transformed_host"' "${MODULE_FILE}"
grep -q 'name = "transformed_uri"' "${MODULE_FILE}"
grep -q 'name = "request_transform_status"' "${MODULE_FILE}"
grep -q 'INTERVAL '\''1'\'' MINUTE' "${MODULE_FILE}"
if rg -q '"input.regex"[[:space:]]*=[[:space:]]*<<-' "${MODULE_FILE}"; then
  exit 1
fi
grep -q 'output "alb_access_logs_athena_workgroup"' "${OUTPUT_FILE}"
grep -q 'output "alb_access_logs_athena_named_query_id"' "${OUTPUT_FILE}"
grep -q 'output "alb_access_logs_athena_rate_named_query_id"' "${OUTPUT_FILE}"
