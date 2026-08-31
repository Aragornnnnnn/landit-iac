#!/usr/bin/env bash
# 개발 EC2 Docker 정리가 오래된 미사용 이미지만 안전하게 제거하는지 검증한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${TEST_DIR}"
}
trap cleanup EXIT

printf 'templatefile("%s", {})\n' \
  "${ROOT_DIR}/environments/dev/templates/ec2-docker-cleanup.sh.tftpl" |
  terraform -chdir="${TEST_DIR}" console > "${TEST_DIR}/docker-cleanup.rendered"
sed '1d;$d' "${TEST_DIR}/docker-cleanup.rendered" > "${TEST_DIR}/docker-cleanup"
chmod 0755 "${TEST_DIR}/docker-cleanup"
bash -n "${TEST_DIR}/docker-cleanup"

mkdir -p "${TEST_DIR}/bin"
cat > "${TEST_DIR}/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf 'docker %s\n' "$*" >> "${TEST_LOG}"
EOF
cat > "${TEST_DIR}/bin/journalctl" <<'EOF'
#!/usr/bin/env bash
printf 'journalctl %s\n' "$*" >> "${TEST_LOG}"
EOF
cat > "${TEST_DIR}/bin/flock" <<'EOF'
#!/usr/bin/env bash
printf 'flock %s\n' "$*" >> "${TEST_LOG}"
EOF
chmod 0755 "${TEST_DIR}/bin/"*

PATH="${TEST_DIR}/bin:${PATH}" \
  LANDIT_LOCK_FILE="${TEST_DIR}/deploy.lock" \
  TEST_LOG="${TEST_DIR}/commands.log" \
  "${TEST_DIR}/docker-cleanup"

if ! rg -Fxq 'docker image prune --all --force --filter until=24h' "${TEST_DIR}/commands.log"; then
  echo '자동 정리는 1일 이상 사용하지 않은 Docker image만 제거해야 한다.' >&2
  exit 1
fi
if ! rg -Fxq 'journalctl --vacuum-time=14d' "${TEST_DIR}/commands.log"; then
  echo '자동 정리는 14일이 지난 system journal을 정리해야 한다.' >&2
  exit 1
fi
if rg -q 'volume prune|system prune' "${TEST_DIR}/commands.log"; then
  echo '자동 정리는 Docker volume이나 전체 system을 prune하면 안 된다.' >&2
  exit 1
fi
