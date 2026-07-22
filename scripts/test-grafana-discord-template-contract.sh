#!/usr/bin/env bash
# Grafana Discord contact point가 Landit 알림 템플릿을 사용하는지 검증한다.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <notification-template.json> <contact-point.json>" >&2
  exit 64
fi

TEMPLATE_JSON="$1"
CONTACT_POINT_JSON="$2"
TEMPLATE_FILE="grafana/templates/landit-discord.tmpl"

jq -e --rawfile expected "$TEMPLATE_FILE" '
  .template == $expected
' "$TEMPLATE_JSON" >/dev/null

jq -e '
  .name == "discord-prod-incidents"
  and .type == "discord"
  and .disableResolveMessage == false
  and .settings.title == "{{ template \"landit.discord.title\" . }}"
  and .settings.message == "{{ template \"landit.discord.message\" . }}"
' "$CONTACT_POINT_JSON" >/dev/null
