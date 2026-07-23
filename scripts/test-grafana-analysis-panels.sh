#!/usr/bin/env bash
# 병목·평소 대비·배포 마커 대시보드 계약을 검증한다.

set -euo pipefail

BE_DASHBOARD="grafana/dashboards/landit-be.json"
AI_DASHBOARD="grafana/dashboards/landit-ai.json"
OVERVIEW_DASHBOARD="grafana/dashboards/landit-overview.json"

jq -e '
  any(.panels[]; .title == "HikariCP 연결 풀" and
    any(.targets[]; .expr | contains("hikaricp_connections_pending"))) and
  any(.panels[]; .title == "Tomcat 요청 스레드" and
    any(.targets[]; .expr | contains("tomcat_threads_busy_threads"))) and
  any(.annotations.list[]; .name == "BE 배포" and
    (.target.expr | contains("workflow=deployment_started")))
' "${BE_DASHBOARD}" >/dev/null

jq -e '
  any(.annotations.list[]; .name == "AI 배포" and
    (.target.expr | contains("workflow=deployment_started")))
' "${AI_DASHBOARD}" >/dev/null

jq -e '
  any(.panels[]; .title == "서비스별 TPS" and
    any(.targets[]; (.expr | contains("offset 7d")) and
      (.legendFormat | contains("7일 전")))) and
  any(.panels[]; .title == "P99 응답시간 현재·7일 전" and
    any(.targets[]; .expr | contains("offset 7d"))) and
  any(.annotations.list[]; .name == "BE·AI 배포" and
    (.target.expr | contains("workflow=deployment_started")))
' "${OVERVIEW_DASHBOARD}" >/dev/null
