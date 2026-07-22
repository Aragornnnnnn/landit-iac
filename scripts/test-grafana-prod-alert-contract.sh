#!/usr/bin/env bash
# Grafana prod 장애 알림 규칙과 Discord 라우팅 계약을 검증한다.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <alert-rules.json> <notification-policy.json>" >&2
  exit 64
fi

RULES_JSON="$1"
POLICY_JSON="$2"

jq -e '
  (.rules // .) as $rules
  | [$rules[]
   | select((.folderUID // "landit-observability") == "landit-observability" and (.ruleGroup // "prod-incidents-1m") == "prod-incidents-1m")
   | {title, labels, for, keepFiringFor: (.keepFiringFor // .keep_firing_for), noDataState, execErrState, data}]
  | length == 6
  and any(.[]; .title == "prod-be-http-5xx-critical"
      and .labels.environment == "prod"
      and .labels.service == "be"
      and .labels.severity == "critical"
      and .labels.alert_scope == "landit_incident"
      and .for == "1m"
      and .keepFiringFor == "5m"
      and .noDataState == "OK"
      and .execErrState == "KeepLast")
  and any(.[]; .title == "prod-ai-http-5xx-critical"
      and .labels.environment == "prod"
      and .labels.service == "ai"
      and .labels.severity == "critical"
      and .for == "1m"
      and .keepFiringFor == "5m"
      and .noDataState == "OK"
      and .execErrState == "KeepLast")
  and any(.[]; .title == "prod-be-http-5xx-warning"
      and .labels.severity == "warning"
      and .for == "3m"
      and .keepFiringFor == "5m"
      and .noDataState == "OK"
      and .execErrState == "KeepLast")
  and any(.[]; .title == "prod-ai-http-5xx-warning"
      and .labels.severity == "warning"
      and .for == "3m"
      and .keepFiringFor == "5m"
      and .noDataState == "OK"
      and .execErrState == "KeepLast")
  and any(.[]; .title == "prod-be-runtime-metrics-missing"
      and .labels.severity == "monitoring"
      and .for == "5m"
      and .keepFiringFor == "5m"
      and .noDataState == "OK"
      and .execErrState == "Alerting")
  and any(.[]; .title == "prod-ai-runtime-metrics-missing"
      and .labels.severity == "monitoring"
      and .for == "5m"
      and .keepFiringFor == "5m"
      and .noDataState == "OK"
      and .execErrState == "Alerting")
' "$RULES_JSON" >/dev/null

jq -e '
  recurse(.routes[]?)
  | select(.object_matchers == [["alert_scope", "=", "landit_incident"]])
  | .group_by == ["service", "severity"]
    and .group_wait == "30s"
    and .group_interval == "5m"
    and .repeat_interval == "1h"
' "$POLICY_JSON" >/dev/null

for service in be ai; do
  jq -e --arg service "$service" '
    (.rules // .) as $rules
    | any($rules[];
      .labels.service == $service
      and (.title | endswith("-critical"))
      and ([.data[].model.expr?] | join(" ") | (contains("status=~") or contains("http_response_status_code=~")))
      and ([.data[].model.expr?] | join(" ") | test("actuator|/health"))
    )
  ' "$RULES_JSON" >/dev/null
done
