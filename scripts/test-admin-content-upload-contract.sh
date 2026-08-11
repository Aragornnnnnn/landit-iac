#!/usr/bin/env bash
# 관리자 콘텐츠 이미지 업로드 IaC 계약을 검증한다.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHARED_MAIN_FILE="${ROOT_DIR}/environments/shared/main.tf"
SHARED_VARIABLES_FILE="${ROOT_DIR}/environments/shared/variables.tf"
DEV_MAIN_FILE="${ROOT_DIR}/environments/dev/main.tf"
PROD_MAIN_FILE="${ROOT_DIR}/environments/prod/main.tf"
MODULE_FILE="${ROOT_DIR}/modules/app-platform/main.tf"
MODULE_VARIABLES_FILE="${ROOT_DIR}/modules/app-platform/variables.tf"

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

shared_main="$(<"${SHARED_MAIN_FILE}")"
shared_variables="$(<"${SHARED_VARIABLES_FILE}")"
dev_main="$(<"${DEV_MAIN_FILE}")"
prod_main="$(<"${PROD_MAIN_FILE}")"
module="$(<"${MODULE_FILE}")"
module_variables="$(<"${MODULE_VARIABLES_FILE}")"
api_policy="$(sed -n '/data "aws_iam_policy_document" "api_task" {/,/^}/p' "${MODULE_FILE}")"
worker_policy="$(sed -n '/data "aws_iam_policy_document" "worker_task" {/,/^}/p' "${MODULE_FILE}")"
api_task="$(sed -n '/resource "aws_ecs_task_definition" "api" {/,/^}/p' "${MODULE_FILE}")"
worker_task="$(sed -n '/resource "aws_ecs_task_definition" "worker" {/,/^}/p' "${MODULE_FILE}")"

assert_contains "${shared_main}" 'resource "aws_s3_bucket_cors_configuration" "content" {' "shared 콘텐츠 버킷 CORS 리소스가 필요하다."
assert_contains "${shared_main}" 'allowed_methods = ["PUT"]' "콘텐츠 업로드는 PUT만 허용해야 한다."
assert_contains "${shared_main}" 'allowed_origins = var.content_upload_allowed_origins' "CORS origin은 변수로 관리해야 한다."
assert_contains "${shared_main}" 'allowed_headers = ["Content-Type", "Cache-Control", "If-None-Match", "x-amz-*"]' "presigned PUT header 계약을 유지해야 한다."
assert_contains "${shared_main}" 'expose_headers  = ["ETag"]' "업로드 응답에서 ETag를 노출해야 한다."
assert_contains "${shared_main}" 'max_age_seconds = 3600' "preflight cache 시간을 3,600초로 유지해야 한다."

for origin in \
  "https://landit.im" \
  "https://develop.landit.im" \
  "http://localhost:3000" \
  "http://127.0.0.1:3000" \
  "http://10.0.2.2:3000" \
  "http://172.16.103.142:3000" \
  "http://192.168.219.107:3000"; do
  assert_contains "${shared_variables}" "\"${origin}\"" "허용 origin ${origin}을 유지해야 한다."
done

assert_contains "${shared_variables}" 'variable "content_upload_allowed_origins" {' "shared CORS origin 변수가 필요하다."
assert_contains "${dev_main}" 'data "terraform_remote_state" "shared" {' "develop은 shared state를 참조해야 한다."
assert_contains "${prod_main}" 'data "terraform_remote_state" "shared" {' "production은 shared state를 참조해야 한다."
assert_contains "${dev_main}" 'key    = "shared/landit-iac/terraform.tfstate"' "develop shared state key가 정확해야 한다."
assert_contains "${prod_main}" 'key    = "shared/landit-iac/terraform.tfstate"' "production shared state key가 정확해야 한다."
assert_contains "${dev_main}" 'content_bucket_name    = data.terraform_remote_state.shared.outputs.content_bucket_name' "develop이 shared bucket output을 module에 전달해야 한다."
assert_contains "${prod_main}" 'content_bucket_name    = data.terraform_remote_state.shared.outputs.content_bucket_name' "production이 shared bucket output을 module에 전달해야 한다."
assert_contains "${dev_main}" 'content_cloudfront_url = data.terraform_remote_state.shared.outputs.cloudfront_url' "develop이 CloudFront output을 module에 전달해야 한다."
assert_contains "${prod_main}" 'content_cloudfront_url = data.terraform_remote_state.shared.outputs.cloudfront_url' "production이 CloudFront output을 module에 전달해야 한다."

assert_contains "${module_variables}" 'variable "content_bucket_name" {' "콘텐츠 bucket module 변수가 필요하다."
assert_contains "${module_variables}" 'variable "content_cloudfront_url" {' "CloudFront URL module 변수가 필요하다."
assert_contains "${module}" 'actions   = ["s3:PutObject"]' "API Task Role은 PutObject 권한을 가져야 한다."
assert_contains "${module}" 'resources = ["arn:aws:s3:::${var.content_bucket_name}/content/inbox/*"]' "API 업로드 권한은 inbox prefix로 제한해야 한다."
assert_contains "${api_task}" '{ name = "CONTENT_BUCKET_NAME", value = var.content_bucket_name }' "API에 콘텐츠 bucket 이름을 주입해야 한다."
assert_contains "${api_task}" '{ name = "CONTENT_CLOUDFRONT_URL", value = var.content_cloudfront_url }' "API에 CloudFront URL을 주입해야 한다."
assert_not_contains "${worker_policy}" 'content_bucket_name' "worker IAM에는 shared 콘텐츠 bucket 권한을 추가하면 안 된다."
assert_not_contains "${worker_task}" 'CONTENT_BUCKET_NAME' "worker에는 콘텐츠 bucket 환경 변수를 주입하면 안 된다."

echo "관리자 콘텐츠 이미지 업로드 IaC 계약이 통과했다."
