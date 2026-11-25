#!/bin/bash
# 실행 중인 운영 이미지로 Flyway와 EC2의 BE·AI·Caddy 연결을 검증한다.
set -euo pipefail
umask 077

root=/run/landit-rehearsal
registry=944011958218.dkr.ecr.ap-northeast-2.amazonaws.com
api_image=${1:?Provide the deployed BE digest}
ai_image=${2:?Provide the deployed AI digest}
[[ "$api_image" == "$registry/prod-landit-api@"* && "$api_image" =~ @sha256:[0-9a-f]{64}$ ]]
[[ "$ai_image" == "$registry/prod-landit-worker@"* && "$ai_image" =~ @sha256:[0-9a-f]{64}$ ]]
[[ -s "$root/api.env" && -s "$root/rds-ca.pem" ]]

export DOCKER_CONFIG
DOCKER_CONFIG="$(mktemp -d "$root/docker-auth.XXXXXX")"
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
aws ecr get-login-password --region ap-northeast-2 |
  docker login --username AWS --password-stdin "$registry" >/dev/null 2>&1
docker pull --quiet "$api_image" >/dev/null
docker pull --quiet "$ai_image" >/dev/null

if ! cmp -s "$root/flyway-image" <(printf '%s\n' "$api_image"); then
  [[ -s "$root/flyway.env" ]]
  docker run --rm --env-file "$root/flyway.env" \
    --mount "type=bind,source=$root/rds-ca.pem,target=$root/rds-ca.pem,readonly" \
    --entrypoint java "$api_image" \
    -cp '/app/app.jar:/app/lib/*' com.landit.landitbe.FlywayMigrationRunner \
    >"$root/flyway.log" 2>&1 || { echo 'Flyway failed; check the root-only flyway.log.' >&2; exit 1; }
  printf '%s\n' "$api_image" > "$root/flyway-image"
  rm -f "$root/flyway.env"
fi
grep -E -o 'Successfully validated [0-9]+ migrations|Current version of schema "public": [0-9]+|Schema "public" is up to date|Successfully applied [0-9]+ migration[s]?' "$root/flyway.log" || true

cat > "$root/Caddyfile" <<'CADDY'
{
  auto_https off
  admin off
}
http://api-ec2-prod.localhost {
  handle /actuator/health {
    reverse_proxy api:8080
  }
  handle {
    respond 404
  }
}
http://ai-ec2-prod.localhost {
  handle /health {
    reverse_proxy ai:8000
  }
  handle {
    respond 404
  }
}
CADDY
cat > "$root/compose.yml" <<'COMPOSE'
services:
  api:
    image: ${API_IMAGE}
    env_file: api.env
    environment:
      AWS_REGION: ap-northeast-2
      AWS_EC2_METADATA_DISABLED: "true"
    volumes:
      - ./rds-ca.pem:/run/landit-rehearsal/rds-ca.pem:ro
    mem_limit: 1g
    stop_grace_period: 120s
  ai:
    image: ${AI_IMAGE}
    environment:
      AWS_EC2_METADATA_DISABLED: "true"
      ROLEPLAY_THUMBNAIL_CONSUMER_ENABLED: "false"
    mem_limit: 2g
    stop_grace_period: 120s
  caddy:
    image: caddy:2.8.4-alpine
    ports:
      - "127.0.0.1:18080:80"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
COMPOSE
export API_IMAGE="$api_image" AI_IMAGE="$ai_image"
docker compose -p landit-rehearsal -f "$root/compose.yml" up -d --quiet-pull

for check in 'api-ec2-prod.localhost /actuator/health' 'ai-ec2-prod.localhost /health'; do
  read -r host path <<< "$check"
  ready=false
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 -o /dev/null -H "Host: $host" "http://127.0.0.1:18080$path" 2>/dev/null; then
      ready=true
      break
    fi
    sleep 2
  done
  if [[ "$ready" != true ]]; then
    docker compose -p landit-rehearsal -f "$root/compose.yml" logs --tail=80 > "$root/runtime.log" 2>&1
    echo "$host did not pass the health check; check the root-only runtime.log." >&2
    exit 1
  fi
  echo "$host$path passed through Caddy"
done
