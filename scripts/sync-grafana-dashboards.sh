#!/usr/bin/env bash
# Grafana folder와 dashboard JSON을 HTTP API로 동기화하는 스크립트
set -euo pipefail

: "${GRAFANA_URL:?GRAFANA_URL is required}"
: "${GRAFANA_SERVICE_ACCOUNT_TOKEN:?GRAFANA_SERVICE_ACCOUNT_TOKEN is required}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DASHBOARD_DIR="${ROOT_DIR}/grafana/dashboards"
FOLDER_UID="landit-observability"
FOLDER_TITLE="Landit"
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "${RESPONSE_FILE}"' EXIT

request() {
  local method="$1"
  local path="$2"
  local data_file="${3:-}"
  local args=(
    --silent
    --show-error
    --output "${RESPONSE_FILE}"
    --write-out '%{http_code}'
    --request "${method}"
    --header "Authorization: Bearer ${GRAFANA_SERVICE_ACCOUNT_TOKEN}"
    --header 'Content-Type: application/json'
  )

  if [[ -n "${data_file}" ]]; then
    args+=(--data-binary "@${data_file}")
  fi

  curl "${args[@]}" "${GRAFANA_URL%/}${path}"
}

folder_payload="$(mktemp)"
jq -n --arg uid "${FOLDER_UID}" --arg title "${FOLDER_TITLE}" \
  '{uid: $uid, title: $title}' >"${folder_payload}"
folder_status="$(request POST '/api/folders' "${folder_payload}")"
rm -f "${folder_payload}"

if [[ "${folder_status}" == "409" || "${folder_status}" == "412" ]]; then
  folder_status="$(request GET "/api/folders/${FOLDER_UID}")"
fi

if [[ "${folder_status}" != "200" && "${folder_status}" != "201" ]]; then
  jq -r '.message // "Grafana folder request failed"' "${RESPONSE_FILE}" >&2
  exit 1
fi

for dashboard_file in "${DASHBOARD_DIR}"/*.json; do
  payload_file="$(mktemp)"
  jq -n --slurpfile dashboard "${dashboard_file}" --arg folder_uid "${FOLDER_UID}" \
    '{dashboard: $dashboard[0], folderUid: $folder_uid, overwrite: true}' >"${payload_file}"
  status="$(request POST '/api/dashboards/db' "${payload_file}")"
  rm -f "${payload_file}"

  if [[ "${status}" != "200" ]]; then
    jq -r '.message // "Grafana dashboard request failed"' "${RESPONSE_FILE}" >&2
    exit 1
  fi

  jq -r '"\(.uid) \(.url)"' "${RESPONSE_FILE}"
done
