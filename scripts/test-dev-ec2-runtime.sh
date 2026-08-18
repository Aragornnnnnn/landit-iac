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
  user_data = templatefile("${ROOT_DIR}/environments/dev/templates/ec2-user-data.sh.tftpl", {
    api_image            = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-api"
    ai_image             = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/develop-landit-worker"
    api_log_group_name   = "/landit/develop/api"
    ai_log_group_name    = "/landit/develop/worker"
    aws_region           = "ap-northeast-2"
    parameter_store_path = "/landit/develop"
    ecr_registry         = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com"
    environment          = "develop"
    app_bucket_name      = "develop-landit-app-123456789012"
    jobs_queue_url       = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/develop-landit-jobs"
    grafana_otlp_enabled = "true"
    grafana_otlp_endpoint = "https://otlp.example.com/otlp"
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
awk '
  /<<.DEPLOY_SERVICE.$/ { capture = 1; next }
  /^DEPLOY_SERVICE$/ { exit }
  capture { print }
' "${TEST_DIR}/user-data.sh" > "${TEST_DIR}/deploy-service"
chmod 0755 "${TEST_DIR}/deploy-service"

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
  : > "${case_dir}/landit/compose.yml"
  printf '#!/usr/bin/env bash\nexit 0\n' > "${case_dir}/landit/bin/runtime-env"
  chmod 0755 "${case_dir}/landit/bin/runtime-env"

  cat > "${case_dir}/bin/aws" <<'EOF'
#!/usr/bin/env bash
printf 'token\n'
EOF
  cat > "${case_dir}/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${TEST_LOG}"
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
