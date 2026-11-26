#!/usr/bin/env bash
# 운영 EC2의 대기 슬롯을 검증하고 Caddy의 API 라우트를 전환한다.
set -euo pipefail
umask 077

runtime_dir="${LANDIT_RUNTIME_DIR:-/opt/landit}"
registry=944011958218.dkr.ecr.ap-northeast-2.amazonaws.com
image_repository="$registry/prod-landit-api"
digest="${1:-${SSM_ImageDigest:-}}"
mode="${2:-rollout}"
if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo '배포할 ECR 이미지 다이제스트가 필요합니다.' >&2
  exit 2
fi

routes="$runtime_dir/caddy/routes"
state="$runtime_dir/rollout-state"
active_file="$state/active-slot"
route_file="$routes/api.caddy"
lock_file="$runtime_dir/scheduler.lock"
api_image="$image_repository@$digest"
caddy_health="http://127.0.0.1:18080/actuator/health/readiness"
public_health=https://api.landit.im/actuator/health/readiness

exec 9>"$runtime_dir/deploy-api.lock"
flock -n 9 || { echo '다른 BE 배포가 실행 중입니다.' >&2; exit 1; }
test -f "$active_file"
test -f "$route_file"
test -f "$lock_file"
test -s "$runtime_dir/api.env"
test -s "$runtime_dir/migration.env"
test -s "$runtime_dir/rds-ca.pem"
test -s "$runtime_dir/rds-cacerts"
credentials="$runtime_dir/aws/api"
test -s "$credentials/config"
jq -e '.Expiration | sub("\\+00:00$";"Z") | sub("[.][0-9]+Z$";"Z") |
  fromdateiso8601 > (now + 300)' "$credentials/credentials.json" >/dev/null

api_url=$(sed -n 's/^DB_URL=//p' "$runtime_dir/api.env")
migration_url=$(sed -n 's/^DB_URL=//p' "$runtime_dir/migration.env")
if [[ "$api_url" != "$migration_url" ||
  ! "${api_url%%\?*}" =~ ^jdbc:postgresql://[a-z0-9.-]+\.rds\.amazonaws\.com(:5432)?/landit$ ||
  "$api_url" != *'sslmode=verify-full'* ]]; then
  echo 'BE와 Flyway가 같은 운영 RDS에 TLS로 연결하도록 설정해야 합니다.' >&2
  exit 1
fi

slot_name() {
  printf 'landit-be-%s' "$1"
}

slot_port() {
  if [[ "$1" == blue ]]; then printf '18081'; else printf '18082'; fi
}

replace_file() {
  local file="$1" value="$2" next
  next=$(mktemp "$file.XXXXXX") || return 1
  printf '%s\n' "$value" > "$next" || return 1
  chmod 0644 "$next" || return 1
  mv -f "$next" "$file"
}

slot_digest() {
  local reference
  reference=$(docker inspect --format '{{.Config.Image}}' "$(slot_name "$1")") || return 1
  [[ "$reference" == "$image_repository@"* ]] || return 1
  printf '%s\n' "${reference##*@}"
}

route_for() {
  local slot="$1" image_digest="$2"
  if [[ "$slot" == none ]]; then
    printf 'respond 503\n'
  else
    printf 'reverse_proxy %s:8080 {\n  header_up X-Forwarded-For {client_ip}\n  header_down X-Landit-Image-Digest %s\n  stream_close_delay 2m\n}\n' \
      "$(slot_name "$slot")" "$image_digest"
  fi
}

reload_proxy() {
  docker exec landit-caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
}

wait_until_ready() {
  local url="$1" expected="$2" attempts="$3" attempt
  for ((attempt = 0; attempt < attempts; attempt++)); do
    if curl -fsS --connect-timeout 2 --max-time 4 -D "$scratch/headers" \
        -o "$scratch/health" "$url" 2>/dev/null &&
      jq -e '.status == "UP"' "$scratch/health" >/dev/null &&
      { [[ -z "$expected" ]] || awk -v expected="$expected" \
        'tolower($1) == "x-landit-image-digest:" { sub(/\r$/, "", $2); if ($2 == expected) yes = 1 } END { exit !yes }' \
        "$scratch/headers"; }; then
      return 0
    fi
    sleep 2
  done
  echo "헬스체크 또는 이미지 확인에 실패했습니다. url=$url" >&2
  return 1
}

stop_slot() {
  local name
  name=$(slot_name "$1")
  if [[ "$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)" == true ]]; then
    docker stop --time 120 "$name"
  fi
}

active=$(cat "$active_file")
case "$active" in
  blue) candidate=green ;;
  green | none) candidate=blue ;;
  *) echo '활성 슬롯 기록이 올바르지 않습니다.' >&2; exit 1 ;;
esac
case "$mode:$active" in
  --bootstrap:none | rollout:blue | rollout:green) ;;
  rollout:none)
    echo '최초 전환은 운영 EC2에서 --bootstrap으로 준비한 뒤 공개 주소를 전환해야 합니다.' >&2
    exit 1
    ;;
  *) echo '초기 슬롯에서만 --bootstrap을 사용할 수 있습니다.' >&2; exit 2 ;;
esac
previous_digest=''
if [[ "$active" != none ]]; then
  if ! previous_digest=$(slot_digest "$active"); then
    # 컨테이너가 사라져도 활성 라우트가 가리키는 다이제스트로 복구 대상을 찾는다.
    previous_digest=$(awk -v upstream="$(slot_name "$active"):8080" '
      $1 == "reverse_proxy" && $2 == upstream { matched = 1 }
      matched && $1 == "header_down" && $2 == "X-Landit-Image-Digest" { print $3 }
    ' "$route_file")
  fi
  [[ "$previous_digest" =~ ^sha256:[0-9a-f]{64}$ ]]
fi
previous_route=$(route_for "$active" "$previous_digest")
scratch=$(mktemp -d)
candidate_started=false
route_changed=false
restart_previous=false
committed=false

finish() {
  local result=$?
  trap - EXIT
  if [[ "$route_changed" == true && "$(cat "$active_file")" == "$candidate" ]]; then
    committed=true
  fi
  if [[ "$committed" == false ]]; then
    if [[ "$route_changed" == true ]]; then
      if { [[ "$restart_previous" == true ]] &&
          ! { docker start "$(slot_name "$active")" >/dev/null &&
            wait_until_ready "http://127.0.0.1:$(slot_port "$active")/actuator/health/readiness" '' 60; }; } ||
        ! replace_file "$route_file" "$previous_route" || ! reload_proxy ||
        { [[ "$active" != none ]] && ! wait_until_ready "$caddy_health" "$previous_digest" 10; }; then
        echo '이전 라우트의 복귀를 확인하지 못했습니다. 두 슬롯을 유지합니다.' >&2
        candidate_started=false
        result=1
      fi
    fi
    if [[ "$candidate_started" == true ]]; then
      stop_slot "$candidate" || result=1
    fi
  fi
  rm -rf -- "$scratch"
  exit "$result"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 구 슬롯을 종료한 직후 호스트가 중단되면 활성 기록을 기준으로 재시작한다.
if [[ "$active" != none && "$(docker inspect --format '{{.State.Running}}' "$(slot_name "$active")" 2>/dev/null || true)" == false ]]; then
  docker start "$(slot_name "$active")" >/dev/null
fi

# 중단된 이전 배포가 남긴 라우트를 확인하고 후보 슬롯을 건드리기 전에 복원한다.
if [[ "$(cat "$route_file")" != "$previous_route" ]]; then
  replace_file "$route_file" "$previous_route"
  reload_proxy
fi
previous_healthy=false
if [[ "$active" != none ]]; then
  if wait_until_ready "$caddy_health" "$previous_digest" 2 ||
    { reload_proxy && wait_until_ready "$caddy_health" "$previous_digest" 2; }; then
    previous_healthy=true
  else
    echo '현재 슬롯이 응답하지 않아 복구 이미지를 준비합니다.' >&2
  fi
fi

if [[ "$previous_healthy" == true && "$previous_digest" == "$digest" ]]; then
  wait_until_ready "$public_health" "$digest" 15
  committed=true
  stop_slot "$candidate"
  printf 'active_slot=%s\nimage_digest=%s\nprevious_image_digest=%s\n' "$active" "$digest" "$previous_digest"
  exit 0
fi

export DOCKER_CONFIG="$scratch/docker"
mkdir "$DOCKER_CONFIG"
aws ecr get-login-password --region ap-northeast-2 |
  docker login --username AWS --password-stdin "$registry" >/dev/null
docker pull "$api_image" >/dev/null
rollout_contract=$(docker image inspect --format '{{index .Config.Labels "im.landit.ec2-rollout"}}' "$api_image")
if [[ "$rollout_contract" != slot-scheduling-v1 ]]; then
  echo '새 BE 이미지가 슬롯별 예약 작업을 지원하지 않습니다.' >&2
  exit 1
fi

# 기존 BE가 읽고 쓸 수 있는 마이그레이션만 같은 배포에 포함한다.
install -m 0600 /dev/null "$runtime_dir/migration.log"
docker run --rm --memory 1g --env-file "$runtime_dir/migration.env" \
  --mount "type=bind,src=$runtime_dir/rds-ca.pem,dst=/run/landit/rds-ca.pem,readonly" \
  --entrypoint java "$api_image" \
  -cp '/app/app.jar:/app/lib/*' com.landit.landitbe.FlywayMigrationRunner \
  > "$runtime_dir/migration.log" 2>&1 || {
  echo 'Flyway 실행에 실패했습니다. 호스트의 migration.log를 확인하세요.' >&2
  exit 1
}

candidate_name=$(slot_name "$candidate")
caddy_ip=$(docker inspect --format '{{(index .NetworkSettings.Networks "landit-prod").IPAddress}}' landit-caddy)
[[ "$caddy_ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]
stop_slot "$candidate"
if docker inspect "$candidate_name" >/dev/null 2>&1; then
  docker rm "$candidate_name" >/dev/null
fi
candidate_started=true
docker run -d --name "$candidate_name" --network landit-prod --restart unless-stopped \
  --memory 1g --stop-timeout 120 \
  --log-driver json-file --log-opt max-size=20m --log-opt max-file=3 \
  --publish "127.0.0.1:$(slot_port "$candidate"):8080" \
  --env-file "$runtime_dir/api.env" \
  --env AWS_CONFIG_FILE=/run/landit-aws/config --env AWS_SHARED_CREDENTIALS_FILE=/dev/null \
  --env AWS_PROFILE=default --env AWS_EC2_METADATA_DISABLED=true \
  --env SPRING_FLYWAY_ENABLED=false --env SPRING_DATASOURCE_HIKARI_READONLY=false \
  --mount "type=bind,src=$credentials,dst=/run/landit-aws,readonly" \
  --mount "type=bind,src=$runtime_dir/rds-cacerts,dst=/run/landit/rds-cacerts,readonly" \
  --env SPRING_PROFILES_ACTIVE=prod --env "LANDIT_DEPLOYMENT_SLOT=$candidate" \
  --env "LANDIT_REFERRAL_TRUSTED_PROXY_CIDRS=$caddy_ip/32" \
  --env SPRING_DATASOURCE_HIKARI_MAXIMUMPOOLSIZE=10 --env SPRING_DATASOURCE_HIKARI_MINIMUMIDLE=1 \
  --env MANAGEMENT_ENDPOINT_HEALTH_PROBES_ENABLED=true \
  --env MANAGEMENT_ENDPOINT_HEALTH_GROUP_READINESS_INCLUDE=readinessState,db \
  --mount "type=bind,src=$runtime_dir/rds-ca.pem,dst=/run/landit/rds-ca.pem,readonly" \
  --mount "type=bind,src=$state,dst=/run/landit-rollout,readonly" \
  --mount "type=bind,src=$lock_file,dst=/run/landit-scheduler.lock" \
  "$api_image" >/dev/null
test "$(slot_digest "$candidate")" = "$digest"
wait_until_ready "http://127.0.0.1:$(slot_port "$candidate")/actuator/health/readiness" '' 60

route_changed=true
replace_file "$route_file" "$(route_for "$candidate" "$digest")"
reload_proxy
wait_until_ready "$caddy_health" "$digest" 10
if [[ "$mode" == rollout ]]; then
  wait_until_ready "$public_health" "$digest" 15
fi

# v1.10.5는 슬롯 파일을 읽지 않는다. HTTP 검증 후 구 프로세스가 끝나야 새 스케줄러를 연다.
if [[ "$active" != none ]]; then
  previous_name=$(slot_name "$active")
  # 조회 실패와 컨테이너 부재를 구분해야 구버전이 살아 있는 채 인계되지 않는다.
  listed=$(docker ps --all --filter "name=^/${previous_name}$" --format '{{.Names}}')
  if [[ -n "$listed" ]]; then
    [[ "$listed" == "$previous_name" ]]
    restart_previous=true
    docker stop --time 120 "$previous_name" >/dev/null
    [[ "$(docker inspect --format '{{.State.Running}}' "$previous_name")" == false ]]
  fi
fi
replace_file "$active_file" "$candidate"
committed=true
if ! docker image prune --all --force --filter label=im.landit.ec2-rollout=slot-scheduling-v1 >/dev/null; then
  echo '사용하지 않는 BE 이미지 정리에 실패했습니다.' >&2
fi
printf 'active_slot=%s\nimage_digest=%s\nprevious_image_digest=%s\n' "$candidate" "$digest" "$previous_digest"
