#!/usr/bin/env bash
# 운영 Caddy와 슬롯 제어용 파일을 처음 한 번 준비한다.
set -euo pipefail
umask 077

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
runtime_dir="${LANDIT_RUNTIME_DIR:-/opt/landit}"
install -d -m 0755 "$runtime_dir" "$runtime_dir/caddy" "$runtime_dir/caddy/routes" "$runtime_dir/rollout-state"
exec 9>"$runtime_dir/deploy-api.lock"
flock -n 9 || { echo '다른 BE 배포가 실행 중입니다.' >&2; exit 1; }

if [[ -n "$(docker ps -q --filter label=com.docker.compose.project=landit-rehearsal)" ]]; then
  echo '운영 프록시를 준비하기 전에 landit-rehearsal 컨테이너를 종료하세요.' >&2
  exit 1
fi

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
  docker network create --subnet 172.30.86.0/24 --ip-range 172.30.86.128/25 landit-prod
fi
network_layout=$(docker network inspect --format '{{range .IPAM.Config}}{{.Subnet}} {{.IPRange}}{{end}}' landit-prod)
if [[ "$network_layout" != "172.30.86.0/24 172.30.86.128/25" ]]; then
  echo 'landit-prod 네트워크가 Caddy의 고정 주소를 지원하도록 준비하세요.' >&2
  exit 1
fi
docker compose --project-directory "$runtime_dir" -f "$runtime_dir/caddy-compose.yml" up -d caddy
