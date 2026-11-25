#!/usr/bin/env bash
# 운영 EC2의 AI 이미지와 헬스체크를 검증하고 실패하면 직전 컨테이너로 복구한다.
set -euo pipefail
umask 077

runtime_dir=${LANDIT_RUNTIME_DIR:-/opt/landit}
registry=944011958218.dkr.ecr.ap-northeast-2.amazonaws.com
repository="$registry/prod-landit-worker"
digest=${SSM_ImageDigest:-}
[[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'AI 이미지 다이제스트가 필요합니다.' >&2; exit 2; }

active=landit-ai
previous=landit-ai-previous
created=false
stopping=false
moved=false
previous_digest=
health_url=http://127.0.0.1:18080/health

# BE의 두 슬롯이 겹치는 동안 AI 컨테이너를 교체하지 않는다.
exec 9>"$runtime_dir/deploy-api.lock"
flock -n 9 || { echo '다른 운영 배포가 실행 중입니다.' >&2; exit 1; }
test -s "$runtime_dir/ai.env"
docker network inspect landit-prod >/dev/null

container_image() {
  docker inspect --format '{{.Config.Image}}' "$1" 2>/dev/null
}

wait_until_healthy() {
  local attempt
  for ((attempt = 0; attempt < 20; attempt++)); do
    if curl -fsS --connect-timeout 2 --max-time 3 "$health_url" 2>/dev/null |
      jq -e '.status == "ok"' >/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

rollback_on_failure() {
  local result=$?
  trap - EXIT
  if ((result == 0)); then
    return
  fi
  if [[ "$created" == true ]]; then
    docker rm -f "$active" >/dev/null || exit 1
  fi
  if [[ "$moved" == true ]]; then
    docker rename "$previous" "$active" || exit 1
  fi
  if [[ "$stopping" == true ]]; then
    docker start "$active" >/dev/null && wait_until_healthy &&
      echo '직전 AI 컨테이너 헬스체크를 확인했습니다.' >&2
  fi
  exit "$result"
}

active_image=$(container_image "$active" || true)
previous_image=$(container_image "$previous" || true)
for reference in "$active_image" "$previous_image"; do
  if [[ -n "$reference" && ( "${reference%@*}" != "$repository" || ! "${reference##*@}" =~ ^sha256:[a-f0-9]{64}$ ) ]]; then
    echo '기존 AI 컨테이너의 이미지 참조를 확인하세요.' >&2
    exit 1
  fi
done

# 중단된 교체에서 이름만 옮겨진 컨테이너가 있으면 재배포 전에 복구한다.
if [[ -z "$active_image" && -n "$previous_image" ]]; then
  docker rename "$previous" "$active"
  active_image=$previous_image
  previous_image=
fi
if [[ -n "$active_image" ]]; then
  if [[ "$(docker inspect --format '{{.State.Running}}' "$active")" != true ]]; then
    docker start "$active" >/dev/null
  fi
  wait_until_healthy || { echo '현재 AI 헬스체크를 먼저 복구하세요.' >&2; exit 1; }
  previous_digest=${active_image##*@}
fi

aws ecr get-login-password --region ap-northeast-2 | docker login --username AWS --password-stdin "$registry" >/dev/null
docker pull "$repository@$digest" >/dev/null

trap rollback_on_failure EXIT
trap 'exit 1' HUP INT TERM
env_override=()
if [[ -n "$active_image" ]]; then
  if [[ -n "$previous_image" ]]; then
    docker rm "$previous" >/dev/null
  fi
  stopping=true
  # 새 컨테이너가 썸네일 큐를 구독하기 전에 이전 프로세스를 종료한다.
  docker stop --time 120 "$active" >/dev/null
  docker rename "$active" "$previous"
  moved=true
else
  # 최초 기동에서 기존 ECS 소비자와 겹치지 않도록 큐 구독을 끈다.
  env_override=(--env ROLEPLAY_THUMBNAIL_CONSUMER_ENABLED=false)
fi

docker create --name "$active" --network landit-prod --restart unless-stopped \
  --env-file "$runtime_dir/ai.env" ${env_override[@]+"${env_override[@]}"} \
  --log-opt max-size=10m --log-opt max-file=3 "$repository@$digest" >/dev/null
created=true
docker start "$active" >/dev/null
if ! wait_until_healthy || [[ "$(container_image "$active")" != "$repository@$digest" ]]; then
  echo '새 AI 헬스체크 또는 이미지 확인에 실패했습니다.' >&2
  exit 1
fi

printf 'image_digest=%s\nprevious_image_digest=%s\n' "$digest" "$previous_digest"
