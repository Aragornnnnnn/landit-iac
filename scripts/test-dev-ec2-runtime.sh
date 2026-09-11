#!/usr/bin/env bash
# 렌더된 EC2 배포 스크립트의 SHA 보존과 rollback 동작을 검증한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR="$(mktemp -d)"
OLD_SHA="1111111111111111111111111111111111111111"
NEW_SHA="2222222222222222222222222222222222222222"

cleanup() {
  rm -rf "${TEST_DIR}"
}
trap cleanup EXIT

cat > "${TEST_DIR}/main.tf" <<EOF
locals {
  deploy_service = templatefile("${ROOT_DIR}/environments/dev/templates/ec2-deploy-service.sh.tftpl", {
    api_image    = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-api"
    ai_image     = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-worker"
    aws_region   = "ap-northeast-2"
    ecr_registry = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com"
  })
  runtime_env = templatefile("${ROOT_DIR}/environments/dev/templates/ec2-runtime-env.sh.tftpl", {
    aws_region             = "ap-northeast-2"
    parameter_store_path   = "/landit/develop"
    environment            = "develop"
    app_bucket_name        = "develop-landit-app-123456789012"
    content_bucket_name    = "develop-landit-content-123456789012"
    content_cloudfront_url = "https://d1234567890.cloudfront.net"
    jobs_queue_url         = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/develop-landit-jobs"
    push_queue_url         = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/develop-landit-push-notifications"
    push_queue_arn         = "arn:aws:sqs:ap-northeast-2:123456789012:develop-landit-push-notifications"
    push_dlq_arn           = "arn:aws:sqs:ap-northeast-2:123456789012:develop-landit-push-notifications-dlq"
    push_scheduler_group   = "develop-landit-admin-push"
    push_scheduler_role    = "arn:aws:iam::123456789012:role/develop-landit-admin-push-scheduler"
    grafana_otlp_enabled   = "true"
    grafana_otlp_endpoint  = "https://otlp.example.com/otlp"
  })
  user_data = templatefile("${ROOT_DIR}/environments/dev/templates/ec2-user-data.sh.tftpl", {
    api_image            = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-api"
    ai_image             = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-worker"
    api_log_group_name   = "/landit/develop/api"
    ai_log_group_name    = "/landit/develop/worker"
    aws_region           = "ap-northeast-2"
    parameter_store_path = "/landit/develop"
    ecr_registry         = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com"
    docker_cleanup       = templatefile("${ROOT_DIR}/environments/dev/templates/ec2-docker-cleanup.sh.tftpl", {})
    docker_cleanup_service = "[Unit]\nDescription=Test cleanup\n[Service]\nType=oneshot\nExecStart=/opt/landit/bin/docker-cleanup"
    docker_cleanup_timer   = "[Unit]\nDescription=Test cleanup timer\n[Timer]\nOnCalendar=weekly\n[Install]\nWantedBy=timers.target"
    deploy_service_base64  = base64encode(local.deploy_service)
    runtime_env          = local.runtime_env
    docker_compose = templatefile("${ROOT_DIR}/environments/dev/templates/docker-compose.yml.tftpl", {
      api_log_group_name = "/landit/develop/api"
      ai_log_group_name  = "/landit/develop/worker"
      aws_region         = "ap-northeast-2"
    })
    caddyfile = templatefile("${ROOT_DIR}/environments/dev/templates/Caddyfile.tftpl", {
      api_domain_names = "api-ec2-develop.landit.im, api-develop.landit.im"
      ai_domain_names  = "ai-ec2-develop.landit.im, ai-develop.landit.im"
    })
  })
}
EOF

(
  cd "${TEST_DIR}"
  terraform console <<'EOF' > "${TEST_DIR}/user-data.sh"
local.user_data
EOF
)
sed '1d;$d' "${TEST_DIR}/user-data.sh" > "${TEST_DIR}/user-data.rendered.sh"
mv "${TEST_DIR}/user-data.rendered.sh" "${TEST_DIR}/user-data.sh"
bash -n "${TEST_DIR}/user-data.sh"
(
  cd "${TEST_DIR}"
  terraform console <<'EOF' > "${TEST_DIR}/user-data-gzip.json"
base64gzip(local.user_data)
EOF
)
python3 - "${TEST_DIR}" <<'PY'
import base64, gzip, json, pathlib, sys
directory = pathlib.Path(sys.argv[1])
compressed = base64.b64decode(json.loads((directory / "user-data-gzip.json").read_text()))
assert len(compressed) <= 16384, "EC2 user data exceeds the 16 KiB limit"
assert gzip.decompress(compressed).rstrip() == (directory / "user-data.sh").read_bytes().rstrip()
PY
if ! rg -q 'CONTENT_BUCKET_NAME="?develop-landit-content-123456789012' "${TEST_DIR}/user-data.sh"; then
  echo 'rendered runtime must provide CONTENT_BUCKET_NAME to the API.' >&2
  exit 1
fi
if ! rg -q 'CONTENT_CLOUDFRONT_URL="?https://d1234567890\.cloudfront\.net' "${TEST_DIR}/user-data.sh"; then
  echo 'rendered runtime must provide CONTENT_CLOUDFRONT_URL to the API.' >&2
  exit 1
fi
if ! rg -q 'SQS_PUSH_NOTIFICATIONS_QUEUE_URL="?https://sqs\.ap-northeast-2\.amazonaws\.com/123456789012/develop-landit-push-notifications' "${TEST_DIR}/user-data.sh"; then
  echo 'rendered runtime must provide SQS_PUSH_NOTIFICATIONS_QUEUE_URL to the API.' >&2
  exit 1
fi
for notification_flag in LANDIT_NOTIFICATION_CONSUMER_ENABLED LANDIT_NOTIFICATION_TEST_API_ENABLED; do
  if ! rg -q "${notification_flag}=true" "${TEST_DIR}/user-data.sh"; then
    echo "rendered runtime must enable ${notification_flag} for the develop API." >&2
    exit 1
  fi
done
for scheduler_setting in \
  'LANDIT_PUSH_SCHEDULER_GROUP=develop-landit-admin-push' \
  'LANDIT_PUSH_SCHEDULER_QUEUE_ARN=arn:aws:sqs:ap-northeast-2:123456789012:develop-landit-push-notifications' \
  'LANDIT_PUSH_SCHEDULER_DLQ_ARN=arn:aws:sqs:ap-northeast-2:123456789012:develop-landit-push-notifications-dlq' \
  'LANDIT_PUSH_SCHEDULER_ROLE_ARN=arn:aws:iam::123456789012:role/develop-landit-admin-push-scheduler'; do
  if ! grep -Fq "${scheduler_setting}" "${TEST_DIR}/user-data.sh"; then
    echo 'rendered API runtime must use the matching environment scheduler and queue.' >&2
    exit 1
  fi
done
if ! grep -Fq 'LANDIT_PUSH_AUDIENCE_DB_URL LANDIT_PUSH_AUDIENCE_DB_USERNAME LANDIT_PUSH_AUDIENCE_DB_PASSWORD' "${TEST_DIR}/user-data.sh"; then
  echo 'rendered API runtime must load audience credentials from SSM.' >&2
  exit 1
fi
if ! rg -q 'LANDIT_MEMORY_WRITE_ENABLED LANDIT_MEMORY_USE_ENABLED LANDIT_FREE_TALK_SPEAKING_TIME_LIMIT_MS' "${TEST_DIR}/user-data.sh"; then
  echo 'develop API must load the free-talk speaking limit from SSM.' >&2
  exit 1
fi
if rg -q 'LANDIT_FREE_TALK_SPEAKING_TIME_LIMIT_MS=9999999' "${TEST_DIR}/user-data.sh"; then
  echo 'develop API must not hardcode the free-talk speaking limit.' >&2
  exit 1
fi
awk '
  /<<.RUNTIME_ENV.$/ { capture = 1; next }
  /^RUNTIME_ENV$/ { exit }
  capture { print }
' "${TEST_DIR}/user-data.sh" > "${TEST_DIR}/runtime-env"
bash -n "${TEST_DIR}/runtime-env"
mkdir -p "${TEST_DIR}/runtime-bin"
cat > "${TEST_DIR}/runtime-bin/aws" <<'EOF'
#!/usr/bin/env bash
cat "${TEST_SSM_RESPONSE}"
EOF
chmod 0755 "${TEST_DIR}/runtime-bin/aws"
python3 - "${TEST_DIR}" <<'PY'
import json, pathlib, sys
directory = pathlib.Path(sys.argv[1])
names = """DB_URL DB_USERNAME DB_PASSWORD LANDIT_CORS_ALLOWED_ORIGINS LANDIT_AUTH_TOKEN_SECRET
LANDIT_PUSH_AUDIENCE_DB_URL LANDIT_PUSH_AUDIENCE_DB_USERNAME LANDIT_PUSH_AUDIENCE_DB_PASSWORD
LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS
LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES LANDIT_AUTH_OIDC_KAKAO_AUDIENCES LANDIT_AUTH_OIDC_APPLE_AUDIENCES
LANDIT_AI_CLIENT_MODE LANDIT_BE_SENTRY_DSN LANDIT_MEMORY_WRITE_ENABLED LANDIT_MEMORY_USE_ENABLED
LANDIT_FREE_TALK_SPEAKING_TIME_LIMIT_MS LANDIT_GRAFANA_CLOUD_OTLP_HEADERS LLM_PROVIDER
OPENROUTER_BASE_URL OPENROUTER_MODEL MESSAGE_FEEDBACK_MODEL MESSAGE_FEEDBACK_REVIEW_ENABLED
OPENROUTER_API_KEY LANDIT_AI_SENTRY_DSN""".split()
values = dict.fromkeys(names, "test-value")
values.update(LANDIT_FREE_TALK_SPEAKING_TIME_LIMIT_MS="7200000",
              LANDIT_FREE_TALK_DAILY_REQUEST_LIMIT="1000",
              LANDIT_FREE_TALK_REQUESTS_PER_MINUTE_LIMIT="20")
values.update(LANDIT_AI_INTERNAL_TOKEN="lan474-token$secret")
values.update(LANDIT_REVENUECAT_WEBHOOK_AUTHORIZATION="Bearer lan477-test$secret",
              LANDIT_SUBSCRIPTION_LAUNCHED_AT="2026-09-11T14:44:00+09:00")
(directory / "ssm.json").write_text(json.dumps({"Parameters": [
    {"Name": "/landit/develop/" + name, "Value": value} for name, value in values.items()
]}))
script = (directory / "runtime-env").read_text().replace('/run/landit', str(directory / 'runtime'))
if sys.platform == "darwin":
    # Linux 배포 스크립트의 in-place 옵션만 로컬 BSD sed 문법에 맞춘다.
    script = script.replace("sed -i '", "sed -i '' '")
(directory / "runtime-env").write_text(script)
PY
PATH="${TEST_DIR}/runtime-bin:${PATH}" TEST_SSM_RESPONSE="${TEST_DIR}/ssm.json" \
  bash "${TEST_DIR}/runtime-env"
python3 - "${TEST_DIR}" <<'PY'
import json, pathlib, stat, sys
directory = pathlib.Path(sys.argv[1])
api = directory / "runtime/api.env"
expected = {
    'LANDIT_FREE_TALK_SPEAKING_TIME_LIMIT_MS="7200000"',
    'LANDIT_FREE_TALK_DAILY_REQUEST_LIMIT="1000"',
    'LANDIT_FREE_TALK_REQUESTS_PER_MINUTE_LIMIT="20"',
    'LANDIT_REVENUECAT_WEBHOOK_AUTHORIZATION="Bearer lan477-test$$secret"',
    'LANDIT_SUBSCRIPTION_LAUNCHED_AT="2026-09-11T14:44:00+09:00"',
    'LANDIT_AI_INTERNAL_TOKEN="lan474-token$$secret"',
    'LANDIT_REVENUECAT_APPLY_SANDBOX_EVENTS=true',
    'SERVER_SHUTDOWN=graceful',
    'SPRING_LIFECYCLE_TIMEOUT_PER_SHUTDOWN_PHASE=50s',
}
assert expected <= set(api.read_text().splitlines()), "API must receive subscription and free-talk SSM values"
assert stat.S_IMODE(api.stat().st_mode) == 0o600, "API secrets must remain owner-only"
assert not any("LANDIT_REVENUECAT" in line or "LANDIT_SUBSCRIPTION" in line or "LANDIT_FREE_TALK" in line
               for line in (directory / "runtime/ai.env").read_text().splitlines())
assert 'LANDIT_AI_INTERNAL_TOKEN="lan474-token$$secret"' in (directory / "runtime/ai.env").read_text()
(directory / "api-before.env").write_bytes(api.read_bytes())
response = json.loads((directory / "ssm.json").read_text())
response["Parameters"] = [p for p in response["Parameters"]
                          if not p["Name"].endswith("/LANDIT_REVENUECAT_WEBHOOK_AUTHORIZATION")]
(directory / "ssm-missing.json").write_text(json.dumps(response))
PY
if PATH="${TEST_DIR}/runtime-bin:${PATH}" TEST_SSM_RESPONSE="${TEST_DIR}/ssm-missing.json" \
  bash "${TEST_DIR}/runtime-env" > "${TEST_DIR}/missing-output" 2>&1; then
  echo 'missing webhook authentication must stop runtime generation.' >&2
  exit 1
fi
cmp "${TEST_DIR}/api-before.env" "${TEST_DIR}/runtime/api.env"
(
  cd "${TEST_DIR}"
  terraform console <<'EOF' > "${TEST_DIR}/deploy-service.quoted"
local.deploy_service
EOF
)
sed '1d;$d' "${TEST_DIR}/deploy-service.quoted" > "${TEST_DIR}/deploy-service"
chmod 0755 "${TEST_DIR}/deploy-service"
if ! rg -q '^LOCK_FD="\$\{LANDIT_DEPLOY_LOCK_FD:-\}"$' "${TEST_DIR}/deploy-service" || \
  ! rg -q 'flock -n -x "\$\{LOCK_FD\}"' "${TEST_DIR}/deploy-service"; then
  echo 'deploy-service must reuse and validate an inherited deploy lock fd.' >&2
  exit 1
fi

assert_file_value() {
  local file="$1"
  local expected="$2"
  local actual

  actual="$(cat "${file}")"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "expected ${file} to contain ${expected}, got ${actual}" >&2
    exit 1
  fi
}

prepare_case() {
  local name="$1"
  local case_dir="${TEST_DIR}/${name}"

  mkdir -p "${case_dir}/bin" "${case_dir}/landit/bin"
  printf '%s\n' "${OLD_SHA}" > "${case_dir}/landit/api.tag"
  printf '%s\n' "${OLD_SHA}" > "${case_dir}/landit/ai.tag"
  if [[ "${name}" == same-sha ]]; then printf '%s\n' "${NEW_SHA}" > "${case_dir}/landit/api.tag"; fi
  : > "${case_dir}/landit/compose.yml"
  printf '#!/usr/bin/env bash\nexit 0\n' > "${case_dir}/landit/bin/runtime-env"
  chmod 0755 "${case_dir}/landit/bin/runtime-env"

  cat > "${case_dir}/bin/aws" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *get-login-password*) printf 'token\n' ;;
  *describe-images*) printf 'sha256:%064d\n' 2 ;;
  *) exit 1 ;;
esac
EOF
  cat > "${case_dir}/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${TEST_LOG}"
case "$*" in
  *' ps '*) exit 1 ;;
  'ps -aq'*service=api) printf 'aaaaaaaaaaaa\n'; exit 0 ;;
  'ps -aq'*service=ai) printf 'bbbbbbbbbbbb\n'; exit 0 ;;
  'inspect '*) printf 'sha256:%064d\n' 1; exit 0 ;;
  'image inspect '*)
    printf '["123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-api@sha256:%064d","123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-worker@sha256:%064d"]\n' 1 1
    exit 0 ;;
esac
if [[ "$*" == *' up -d '* || "$*" == *' pull '* ]]; then
  while [[ "$#" -gt 0 ]]; do
    if [[ "$1" == --env-file ]]; then cat "$2" >> "${TEST_LOG}.images"; break; fi
    shift
  done
fi
if [[ "${TEST_MODE}" == pull-fail && "$*" == *' pull api'* ]]; then
  exit 1
fi
exit 0
EOF
  cat > "${case_dir}/bin/curl" <<'EOF'
#!/usr/bin/env bash
count=0
if [[ -f "${TEST_CURL_COUNT}" ]]; then
  count="$(cat "${TEST_CURL_COUNT}")"
fi
count=$((count + 1))
printf '%s\n' "${count}" > "${TEST_CURL_COUNT}"
case "${TEST_MODE}" in
  success) exit 0 ;;
  health-fail) [[ "${count}" -gt 30 ]] && exit 0 || exit 1 ;;
  rollback-fail) exit 1 ;;
  *) exit 1 ;;
esac
EOF
  cat > "${case_dir}/bin/flock" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat > "${case_dir}/bin/sleep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod 0755 "${case_dir}/bin/"*
  printf '%s' "${case_dir}"
}

run_case() {
  local name="$1"
  local mode="$2"
  local expected_exit="$3"
  local case_dir

  case_dir="$(prepare_case "${name}")"
  if PATH="${case_dir}/bin:${PATH}" \
    LANDIT_DIR="${case_dir}/landit" \
    LANDIT_LOCK_FILE="${case_dir}/deploy.lock" \
    TEST_LOG="${case_dir}/docker.log" \
    TEST_CURL_COUNT="${case_dir}/curl-count" \
    TEST_MODE="${mode}" \
    "${TEST_DIR}/deploy-service" api "${NEW_SHA}"; then
    actual_exit=0
  else
    actual_exit=1
  fi
  if [[ "${actual_exit}" != "${expected_exit}" ]]; then
    echo "${name} expected exit ${expected_exit}, got ${actual_exit}" >&2
    exit 1
  fi

  printf '%s' "${case_dir}"
}

success_dir="$(run_case success success 0)"
assert_file_value "${success_dir}/landit/api.tag" "${NEW_SHA}"
assert_file_value "${success_dir}/landit/api.previous.tag" "${OLD_SHA}"
rg -q "api ${OLD_SHA} ${NEW_SHA} " "${success_dir}/landit/deployments.log"

pull_failure_dir="$(run_case pull-failure pull-fail 1)"
assert_file_value "${pull_failure_dir}/landit/api.tag" "${OLD_SHA}"
if rg -q ' up -d --no-deps api' "${pull_failure_dir}/docker.log"; then
  echo 'pull failure must not restart the API container.' >&2
  exit 1
fi

health_failure_dir="$(run_case health-failure health-fail 1)"
assert_file_value "${health_failure_dir}/landit/api.tag" "${OLD_SHA}"
if [[ "$(rg -c ' up -d --no-deps api' "${health_failure_dir}/docker.log")" -ne 2 ]]; then
  echo 'health failure must restart the previous API image once.' >&2
  exit 1
fi

rollback_failure_dir="$(run_case rollback-failure rollback-fail 1)"
assert_file_value "${rollback_failure_dir}/landit/api.tag" "${OLD_SHA}"

# 토큰이 아직 준비되지 않은 공존 단계에서도 기존 환경 생성은 성공한다.
python3 - "${TEST_DIR}" <<'PYTEST'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
response = json.loads((p / "ssm.json").read_text())
response["Parameters"] = [v for v in response["Parameters"] if not v["Name"].endswith("/LANDIT_AI_INTERNAL_TOKEN")]
(p / "ssm-no-token.json").write_text(json.dumps(response))
PYTEST
PATH="${TEST_DIR}/runtime-bin:${PATH}" TEST_SSM_RESPONSE="${TEST_DIR}/ssm-no-token.json" \
  bash "${TEST_DIR}/runtime-env"
if rg -q '^LANDIT_AI_INTERNAL_TOKEN=' "${TEST_DIR}/runtime/api.env" "${TEST_DIR}/runtime/ai.env"; then
  echo 'optional token must be absent while compatibility mode is active.' >&2
  exit 1
fi

# 같은 SHA의 태그가 새 이미지로 덮여도 이전 실행 digest로 돌아간다.
same_sha_dir="$(run_case same-sha health-fail 1)"
old_ref="123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-api@$(printf 'sha256:%064d' 1)"
new_ref="123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-api@$(printf 'sha256:%064d' 2)"
assert_file_value "${same_sha_dir}/landit/api.tag" "${NEW_SHA}"
assert_file_value "${same_sha_dir}/landit/api.previous.ref" "${old_ref}"
assert_file_value "${same_sha_dir}/landit/api.ref" "${old_ref}"
rg -Fxq "API_IMAGE_REF=${new_ref}" "${same_sha_dir}/docker.log.images"
rg -Fxq "API_IMAGE_REF=${old_ref}" "${same_sha_dir}/landit/images.env"
