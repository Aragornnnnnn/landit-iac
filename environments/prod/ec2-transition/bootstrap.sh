#!/bin/bash
# 운영 전환용 EC2에 Compose와 PostgreSQL 이관 도구를 설치한다.
set -euo pipefail
umask 027

dnf install -y docker jq postgresql17
install -d -m 0755 /usr/local/lib/docker/cli-plugins /opt/landit
curl -fsSL --retry 4 https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
printf '%s  %s\n' \
  383ce6698cd5d5bbf958d2c8489ed75094e34a77d340404d9f32c4ae9e12baf0 \
  /usr/local/lib/docker/cli-plugins/docker-compose | sha256sum --check --status
chmod 0755 /usr/local/lib/docker/cli-plugins/docker-compose
systemctl enable --now docker
