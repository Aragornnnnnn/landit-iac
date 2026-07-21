#!/usr/bin/env bash
# Grafana 에러 패널이 서비스별 실제 로그 레벨만 사용하는지 검증한다.
set -euo pipefail

jq -e '[.panels[].targets[]?.expr] | any(contains("| logfmt | level=~\"ERROR|CRITICAL\""))' \
  grafana/dashboards/landit-ai.json >/dev/null

if rg -n '\(\?i\)\(error\|exception\|traceback\|critical\|fatal\)' \
  grafana/dashboards/landit-ai.json; then
  exit 1
fi

jq -e '
  [.panels[]
    | select(.title == "에러 로그 발생량" or .title == "에러 로그")
    | .targets
    | length]
  | length == 2 and all(. == 2)
' grafana/dashboards/landit-overview.json >/dev/null

jq -e '
  [.panels[]
    | select(.title == "에러 로그 발생량" or .title == "에러 로그")
    | .targets[]
    | .expr]
  | any(contains("/api") and contains("\\s(ERROR|FATAL)\\s"))
    and any(contains("/worker") and contains("| logfmt | level=~\"ERROR|CRITICAL\""))
' grafana/dashboards/landit-overview.json >/dev/null
