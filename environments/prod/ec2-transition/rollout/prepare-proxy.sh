#!/usr/bin/env bash
# 운영 Caddy와 슬롯 제어용 파일을 처음 한 번 준비한다.
set -euo pipefail
umask 077

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
runtime_dir="${LANDIT_RUNTIME_DIR:-/opt/landit}"
install -d -m 0755 "$runtime_dir" "$runtime_dir/caddy" "$runtime_dir/caddy/routes" "$runtime_dir/rollout-state"
exec 9>"$runtime_dir/deploy-api.lock"
flock -n 9 || { echo '다른 BE 배포가 실행 중입니다.' >&2; exit 1; }

install -m 0644 "$source_dir/Caddyfile" "$runtime_dir/caddy/Caddyfile"
install -m 0644 "$source_dir/compose.yml" "$runtime_dir/caddy-compose.yml"
if [[ ! -f "$runtime_dir/rollout-state/active-slot" ]]; then
  printf 'none\n' > "$runtime_dir/rollout-state/active-slot"
fi
if [[ ! -f "$runtime_dir/caddy/routes/api.caddy" ]]; then
  printf 'respond 503\n' > "$runtime_dir/caddy/routes/api.caddy"
fi
touch "$runtime_dir/scheduler.lock"
chmod 0644 "$runtime_dir/rollout-state/active-slot" "$runtime_dir/caddy/routes/api.caddy" "$runtime_dir/scheduler.lock"

if ! docker network inspect landit-prod >/dev/null 2>&1; then
  docker network create landit-prod
fi
docker compose --project-directory "$runtime_dir" -f "$runtime_dir/caddy-compose.yml" up -d caddy
