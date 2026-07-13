# Grafana Cloud Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grafana Cloud stack 표시 이름을 Landit에 맞게 변경하고, develop·prod의 BE·AI 필수 메트릭과 전체·에러 로그를 확인하는 대시보드 3개를 배포한다.

**Architecture:** stack 표시 이름을 `landitobservability`로 변경한 뒤 기존 Grafana URL에서 Prometheus·Loki 데이터가 유지되는지 먼저 확인한다. 대시보드 JSON은 `landit-iac`에 저장하고 단기 Grafana service account token으로 HTTP API에 upsert한다. token은 파일이나 명령 출력에 남기지 않고 배포 직후 폐기한다.

**Tech Stack:** Grafana Cloud HTTP API, Grafana dashboard JSON, PromQL, LogQL, Bash, curl, jq.

## Global Constraints

- issue number는 LAN-122이다.
- Grafana folder 제목은 `Landit`, UID는 `landit-observability`이다.
- dashboard UID는 `landit-overview`, `landit-be`, `landit-ai`이다.
- 환경 변수는 `prod`, `develop`이며 기본값은 `prod`이다.
- 기본 시간 범위는 최근 1시간, 자동 새로고침은 30초이다.
- Prometheus data source UID는 `grafanacloud-prom`이다.
- Loki data source UID는 `grafanacloud-logs`이다.
- token은 Git, Terraform state, 파일, CI 로그, shell 출력에 남기지 않는다.
- 사용자 ID, session ID, message ID, 요청 본문과 query string을 dashboard 변수나 label에 추가하지 않는다.
- ALB RequestCount, ECS CPU·memory, CloudWatch scrape, alert rule은 범위에서 제외한다.

## File Map

- Create: `grafana/dashboards/landit-overview.json` — BE·AI 통합 요청 상태와 전체·에러 로그를 표시한다.
- Create: `grafana/dashboards/landit-be.json` — BE HTTP와 JVM 및 BE 로그를 표시한다.
- Create: `grafana/dashboards/landit-ai.json` — AI HTTP와 Python runtime 및 AI 로그를 표시한다.
- Create: `scripts/sync-grafana-dashboards.sh` — folder를 생성하고 dashboard JSON을 idempotent하게 upsert한다.
- Modify: `docs/observability.md` — 새 stack URL과 dashboard 운영·재배포 절차를 기록한다.
- Modify: `checklist.md` — 실제 진행 상태를 반영한다.
- Modify: `context-notes.md` — rename, token, 배포, 검증 결과를 기록한다.

---

### Task 1: Grafana Cloud stack rename과 데이터 유지 확인

**Files:**
- Modify: `docs/observability.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**
- Consumes: 기존 stack `scarletmyrtle3008`과 로그인된 Grafana Cloud Portal session.
- Produces: 새 stack URL과 rename 후에도 유지되는 data source UID 및 수집 상태.

- [x] **Step 1: rename 전 상태를 기록한다.**

```text
Current stack: scarletmyrtle3008
Prometheus UID: grafanacloud-prom
Loki UID: grafanacloud-logs
Metric environments: develop, prod
Log groups: /landit/develop/api, /landit/develop/worker, /landit/prod/api, /landit/prod/worker
```

- [x] **Step 2: stack 이름을 변경한다.**

Grafana Cloud API로 stack 표시 이름을 `landitobservability`로 변경한다. 이 변경은 기존 Grafana URL slug를 바꾸지 않는다.

- [x] **Step 3: 새 URL과 data source를 확인한다.**

기존 Grafana URL에서 Data sources API를 조회해 `grafanacloud-prom`과 `grafanacloud-logs` UID를 확인한다.

- [x] **Step 4: rename 후 수집 상태를 확인한다.**

Prometheus Explore에서 아래 쿼리를 실행한다.

```promql
count by (deployment_environment_name, service_name) (
  {service_name=~"landit-be|landit-ai", deployment_environment_name=~"develop|prod"}
)
```

Expected: `develop`과 `prod`에서 `landit-be`, `landit-ai` 네 조합이 모두 조회된다.

Loki Explore에서 아래 쿼리를 실행한다.

```logql
sum by (environment, aws_log_group) (
  count_over_time({project="landit", environment=~"develop|prod"}[15m])
)
```

Expected: develop·prod의 api·worker 네 log group이 모두 조회된다.

- [x] **Step 5: rename 결과를 문서에 반영하고 커밋한다.**

Run:

```bash
git diff --check
git add docs/observability.md checklist.md context-notes.md
git commit -m "docs: Grafana Cloud stack 이름 변경 반영"
```

Expected: rename 관련 문서 변경만 커밋된다.

---

### Task 2: Overview·BE·AI dashboard JSON 작성

**Files:**
- Create: `grafana/dashboards/landit-overview.json`
- Create: `grafana/dashboards/landit-be.json`
- Create: `grafana/dashboards/landit-ai.json`

**Interfaces:**
- Consumes: Prometheus UID `grafanacloud-prom`, Loki UID `grafanacloud-logs`, metric labels와 log labels.
- Produces: Grafana `/api/dashboards/db` payload의 `dashboard` 필드로 사용할 JSON 객체 3개.

- [x] **Step 1: dashboard가 없을 때 검증이 실패하는지 확인한다.**

Run:

```bash
for file in grafana/dashboards/landit-overview.json grafana/dashboards/landit-be.json grafana/dashboards/landit-ai.json; do
  test -f "$file" && jq -e . "$file"
done
```

Expected: 첫 번째 없는 파일에서 non-zero exit code를 반환한다.

- [x] **Step 2: 세 dashboard의 공통 JSON 설정을 작성한다.**

세 파일은 아래 값을 공통으로 사용한다.

```json
{
  "editable": true,
  "graphTooltip": 1,
  "refresh": "30s",
  "schemaVersion": 41,
  "tags": ["landit", "observability"],
  "time": {"from": "now-1h", "to": "now"},
  "timezone": "browser"
}
```

`environment` 변수는 custom variable로 `prod,develop`을 제공하고 current value를 `prod`로 설정한다. `log_search`는 빈 문자열을 기본값으로 사용하는 textbox variable로 작성한다. 모든 dashboard는 `전체 로그`와 `에러 로그` 제목의 Loki panel을 포함한다.

- [x] **Step 3: Landit Overview panel을 작성한다.**

`landit-overview.json`은 UID `landit-overview`, title `Landit Overview`를 사용한다. `service` custom variable은 `All : api|worker,BE : api,AI : worker` 값을 사용한다.

필수 PromQL은 아래와 같다.

```promql
sum(rate(http_server_requests_milliseconds_count{service_name="landit-be",deployment_environment_name="$environment"}[$__rate_interval]))
```

```promql
sum(rate(http_server_request_duration_seconds_count{service_name="landit-ai",deployment_environment_name="$environment"}[$__rate_interval]))
```

```promql
100 * sum(rate(http_server_requests_milliseconds_count{service_name="landit-be",deployment_environment_name="$environment",status=~"5.."}[$__rate_interval]))
/ clamp_min(sum(rate(http_server_requests_milliseconds_count{service_name="landit-be",deployment_environment_name="$environment"}[$__rate_interval])), 0.000001)
```

```promql
100 * sum(rate(http_server_request_duration_seconds_count{service_name="landit-ai",deployment_environment_name="$environment",http_response_status_code=~"5.."}[$__rate_interval]))
/ clamp_min(sum(rate(http_server_request_duration_seconds_count{service_name="landit-ai",deployment_environment_name="$environment"}[$__rate_interval])), 0.000001)
```

```promql
histogram_quantile(0.95, sum by (le) (rate(http_server_requests_milliseconds_bucket{service_name="landit-be",deployment_environment_name="$environment"}[$__rate_interval])))
```

```promql
histogram_quantile(0.95, sum by (le) (rate(http_server_request_duration_seconds_bucket{service_name="landit-ai",deployment_environment_name="$environment"}[$__rate_interval])))
```

필수 LogQL은 아래와 같다.

```logql
{project="landit",environment="$environment",aws_log_group=~"/landit/$environment/(${service:raw})"} |~ "$log_search"
```

```logql
{project="landit",environment="$environment",aws_log_group=~"/landit/$environment/(${service:raw})"} |~ "(?i)(error|exception|traceback|critical|fatal)"
```

전체 로그와 에러 로그는 `logs` visualization을 사용하고 각각 12 grid width로 나란히 배치한다.

요청 추이에는 BE·AI TPS와 5xx 오류율을 서비스별 시계열로 표시한다. 응답시간에는 각 서비스의 P50·P95·P99를 표시하고, 요청량이 많은 endpoint 표는 BE의 `uri`와 AI의 `http_route`를 `service`, `endpoint`, `tps` 열로 합친다.

로그 발생량과 에러 로그 발생량 추이는 아래 LogQL을 사용한다.

```logql
sum by (aws_log_group) (count_over_time({project="landit",environment="$environment",aws_log_group=~"/landit/$environment/(${service:raw})"}[$__interval]))
```

```logql
sum by (aws_log_group) (count_over_time({project="landit",environment="$environment",aws_log_group=~"/landit/$environment/(${service:raw})"} |~ "(?i)(error|exception|traceback|critical|fatal)" [$__interval]))
```

BE·AI 상세 dashboard link는 `keepTime=true`, `includeVars=true`로 설정해 현재 시간 범위와 `environment` 값을 유지한다.

- [x] **Step 4: Landit BE panel을 작성한다.**

`landit-be.json`은 UID `landit-be`, title `Landit BE`를 사용한다. `endpoint` variable은 아래 query와 All value `.*`를 사용한다.

```promql
label_values(http_server_requests_milliseconds_count{service_name="landit-be",deployment_environment_name="$environment"}, uri)
```

필수 HTTP 쿼리는 아래와 같다.

```promql
sum by (uri) (rate(http_server_requests_milliseconds_count{service_name="landit-be",deployment_environment_name="$environment",uri=~"$endpoint"}[$__rate_interval]))
```

```promql
100 * sum(rate(http_server_requests_milliseconds_count{service_name="landit-be",deployment_environment_name="$environment",uri=~"$endpoint",status=~"5.."}[$__rate_interval]))
/ clamp_min(sum(rate(http_server_requests_milliseconds_count{service_name="landit-be",deployment_environment_name="$environment",uri=~"$endpoint"}[$__rate_interval])), 0.000001)
```

```promql
histogram_quantile(0.95, sum by (le, uri) (rate(http_server_requests_milliseconds_bucket{service_name="landit-be",deployment_environment_name="$environment",uri=~"$endpoint"}[$__rate_interval])))
```

같은 bucket 쿼리의 quantile 값을 `0.50`, `0.95`, `0.99`로 나눠 endpoint별 응답시간 시계열을 구성한다. 전체 요청 수는 `sum(increase(..._count[$__range]))`, 상태 코드별 요청 추이는 `sum by (status) (rate(..._count[$__rate_interval]))`, 느린 endpoint 표는 `sum by (uri) (rate(..._sum[$__rate_interval])) / clamp_min(sum by (uri) (rate(..._count[$__rate_interval])), 0.000001)`을 사용한다.

필수 JVM 쿼리는 아래와 같다.

```promql
sum(jvm_memory_used_bytes{service_name="landit-be",deployment_environment_name="$environment",area="heap"})
```

```promql
100 * sum(jvm_memory_used_bytes{service_name="landit-be",deployment_environment_name="$environment",area="heap"})
/ clamp_min(sum(jvm_memory_max_bytes{service_name="landit-be",deployment_environment_name="$environment",area="heap"}), 1)
```

```promql
sum(rate(jvm_gc_pause_milliseconds_sum{service_name="landit-be",deployment_environment_name="$environment"}[$__rate_interval]))
```

```promql
jvm_threads_live{service_name="landit-be",deployment_environment_name="$environment"}
```

JVM 보조 패널은 아래 메트릭을 실제 존재하는 label 기준으로 집계한다.

```promql
sum(jvm_memory_used_bytes{service_name="landit-be",deployment_environment_name="$environment",area="nonheap"})
```

```promql
sum(rate(jvm_gc_pause_milliseconds_count{service_name="landit-be",deployment_environment_name="$environment"}[$__rate_interval]))
```

```promql
sum(rate(jvm_gc_memory_allocated_bytes_total{service_name="landit-be",deployment_environment_name="$environment"}[$__rate_interval]))
```

```promql
sum(rate(jvm_gc_memory_promoted_bytes_total{service_name="landit-be",deployment_environment_name="$environment"}[$__rate_interval]))
```

```promql
jvm_threads_daemon{service_name="landit-be",deployment_environment_name="$environment"}
```

```promql
jvm_threads_peak{service_name="landit-be",deployment_environment_name="$environment"}
```

```promql
jvm_classes_loaded{service_name="landit-be",deployment_environment_name="$environment"}
```

GC 평균 pause는 pause sum rate를 count rate로 나누고, 최대 pause는 `jvm_gc_pause_milliseconds_max`를 사용한다. 전체·에러 로그와 로그 발생량 추이는 `/landit/$environment/api`만 조회한다.

- [x] **Step 5: Landit AI panel을 작성한다.**

`landit-ai.json`은 UID `landit-ai`, title `Landit AI`를 사용한다. `endpoint` variable은 아래 query와 All value `.*`를 사용한다.

```promql
label_values(http_server_request_duration_seconds_count{service_name="landit-ai",deployment_environment_name="$environment"}, http_route)
```

필수 HTTP 쿼리는 아래와 같다.

```promql
sum by (http_route) (rate(http_server_request_duration_seconds_count{service_name="landit-ai",deployment_environment_name="$environment",http_route=~"$endpoint"}[$__rate_interval]))
```

```promql
100 * sum(rate(http_server_request_duration_seconds_count{service_name="landit-ai",deployment_environment_name="$environment",http_route=~"$endpoint",http_response_status_code=~"5.."}[$__rate_interval]))
/ clamp_min(sum(rate(http_server_request_duration_seconds_count{service_name="landit-ai",deployment_environment_name="$environment",http_route=~"$endpoint"}[$__rate_interval])), 0.000001)
```

```promql
histogram_quantile(0.95, sum by (le, http_route) (rate(http_server_request_duration_seconds_bucket{service_name="landit-ai",deployment_environment_name="$environment",http_route=~"$endpoint"}[$__rate_interval])))
```

같은 bucket 쿼리의 quantile 값을 `0.50`, `0.95`, `0.99`로 나눠 endpoint별 응답시간 시계열을 구성한다. 전체 요청 수는 `sum(increase(..._count[$__range]))`, 상태 코드별 요청 추이는 `sum by (http_response_status_code) (rate(..._count[$__rate_interval]))`, 느린 endpoint 표는 `sum by (http_route) (rate(..._sum[$__rate_interval])) / clamp_min(sum by (http_route) (rate(..._count[$__rate_interval])), 0.000001)`을 사용한다.

필수 runtime 쿼리는 아래와 같다.

```promql
process_cpu_utilization_ratio{service_name="landit-ai",deployment_environment_name="$environment"}
```

```promql
process_memory_usage_bytes{service_name="landit-ai",deployment_environment_name="$environment"}
```

```promql
process_memory_virtual_bytes{service_name="landit-ai",deployment_environment_name="$environment"}
```

```promql
process_thread_count{service_name="landit-ai",deployment_environment_name="$environment"}
```

```promql
sum by (generation) (rate(cpython_gc_collections_total{service_name="landit-ai",deployment_environment_name="$environment"}[$__rate_interval]))
```

CPython GC 보조 패널은 아래 메트릭을 사용한다.

```promql
sum by (generation) (rate(cpython_gc_collected_objects_total{service_name="landit-ai",deployment_environment_name="$environment"}[$__rate_interval]))
```

```promql
sum by (generation) (rate(cpython_gc_uncollectable_objects_total{service_name="landit-ai",deployment_environment_name="$environment"}[$__rate_interval]))
```

전체·에러 로그와 로그 발생량 추이는 `/landit/$environment/worker`만 조회한다.

- [x] **Step 6: dashboard JSON을 정적 검증한다.**

Run:

```bash
for file in grafana/dashboards/*.json; do
  jq -e '
    (.uid | type == "string") and
    (.title | type == "string") and
    (.panels | length > 0) and
    ([.templating.list[].name] | index("environment") != null) and
    ([.panels[].title] | index("전체 로그") != null) and
    ([.panels[].title] | index("에러 로그") != null)
  ' "$file" >/dev/null
done
test "$(rg -l 'grafanacloud-prom' grafana/dashboards/*.json | wc -l | tr -d ' ')" = "3"
test "$(rg -l 'grafanacloud-logs' grafana/dashboards/*.json | wc -l | tr -d ' ')" = "3"
```

Expected: 모든 검증이 exit code `0`을 반환한다.

- [x] **Step 7: dashboard JSON을 커밋한다.**

```bash
git add grafana/dashboards/landit-overview.json grafana/dashboards/landit-be.json grafana/dashboards/landit-ai.json
git commit -m "feat: Grafana Cloud 운영 대시보드 추가"
```

---

### Task 3: Dashboard 동기화 스크립트 작성

**Files:**
- Create: `scripts/sync-grafana-dashboards.sh`

**Interfaces:**
- Consumes: `GRAFANA_URL`, `GRAFANA_SERVICE_ACCOUNT_TOKEN`, dashboard JSON 3개.
- Produces: `landit-observability` folder와 UID가 고정된 dashboard 3개.

- [x] **Step 1: 스크립트가 없을 때 검증이 실패하는지 확인한다.**

Run: `bash -n scripts/sync-grafana-dashboards.sh`.

Expected: 파일이 없어 non-zero exit code를 반환한다.

- [x] **Step 2: 최소 동기화 스크립트를 작성한다.**

```bash
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
  local url="$2"
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
  curl "${args[@]}" "${GRAFANA_URL%/}${url}"
}

folder_status="$(request GET "/api/folders/${FOLDER_UID}")"
if [[ "${folder_status}" == "404" ]]; then
  folder_payload="$(mktemp)"
  jq -n --arg uid "${FOLDER_UID}" --arg title "${FOLDER_TITLE}" \
    '{uid: $uid, title: $title}' >"${folder_payload}"
  folder_status="$(request POST '/api/folders' "${folder_payload}")"
  rm -f "${folder_payload}"
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
```

- [x] **Step 3: 환경변수 누락과 shell 문법을 검증한다.**

Run:

```bash
bash -n scripts/sync-grafana-dashboards.sh
env -u GRAFANA_URL -u GRAFANA_SERVICE_ACCOUNT_TOKEN ./scripts/sync-grafana-dashboards.sh
```

Expected: `bash -n`은 성공하고 실행은 `GRAFANA_URL is required`로 실패한다. token 값은 출력되지 않는다.

- [x] **Step 4: 실행 권한과 secret 노출을 확인한다.**

```bash
chmod +x scripts/sync-grafana-dashboards.sh
git diff --check
if rg -n 'glsa_[A-Za-z0-9_-]{20,}|glc_[A-Za-z0-9_-]{20,}' grafana scripts; then exit 1; fi
```

Expected: 모두 exit code `0`이다.

- [x] **Step 5: 동기화 스크립트를 커밋한다.**

```bash
git add scripts/sync-grafana-dashboards.sh
git commit -m "chore: Grafana dashboard 동기화 스크립트 추가"
```

---

### Task 4: Service account token 발급과 dashboard 배포

**Files:**
- Read: `grafana/dashboards/landit-overview.json`
- Read: `grafana/dashboards/landit-be.json`
- Read: `grafana/dashboards/landit-ai.json`

**Interfaces:**
- Consumes: 로그인된 Grafana session, `landit-dashboard-provisioner` service account, Editor token.
- Produces: `Landit` folder와 dashboard 3개. 작업 종료 시 active token은 남지 않는다.

- [x] **Step 1: service account를 생성한다.**

Grafana Administration에서 `landit-dashboard-provisioner`를 `Editor` role로 생성한다. 같은 이름이 있으면 기존 account를 사용한다.

- [x] **Step 2: 1일 만료 token을 생성한다.**

token은 브라우저 자동화 메모리에만 보관하고 응답, 파일, shell 명령에 출력하지 않는다.

- [x] **Step 3: dashboard JSON을 API로 upsert한다.**

`Landit` folder를 만든 뒤 JSON 3개를 `/api/dashboards/db`에 `overwrite=true`로 전송한다. 응답에는 아래 UID만 기록한다.

```text
landit-overview
landit-be
landit-ai
```

- [x] **Step 4: 같은 JSON을 다시 upsert해 멱등성을 확인한다.**

Expected: dashboard 수가 늘지 않고 같은 UID의 version만 증가한다.

---

### Task 5: Dashboard 데이터 검증과 token 폐기

**Files:**
- Modify: `docs/observability.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**
- Consumes: 배포된 dashboard 3개와 develop·prod telemetry.
- Produces: 실제 panel 검증 기록, 폐기된 token, 최신 운영 문서.

- [x] **Step 1: Overview를 두 환경에서 검증한다.**

`prod`, `develop` 각각에서 전체 TPS, BE·AI TPS, 오류율, P95, 전체 로그, 에러 로그 panel이 query error 없이 렌더링되는지 확인한다. 요청이나 에러가 없는 시계열은 `No data`가 허용되지만 query error는 허용하지 않는다.

- [x] **Step 2: BE dashboard를 두 환경에서 검증한다.**

endpoint variable, TPS, 오류율, P95, heap, GC pause, thread, 전체 로그, 에러 로그를 확인한다.

- [x] **Step 3: AI dashboard를 두 환경에서 검증한다.**

endpoint variable, TPS, 오류율, P95, process CPU·memory·thread, CPython GC, 전체 로그, 에러 로그를 확인한다.

- [x] **Step 4: dashboard link와 Grafana URL을 확인한다.**

Overview에서 BE·AI 상세 dashboard로 이동할 때 `var-environment`와 현재 시간 범위가 유지되는지 확인한다.

- [x] **Step 5: 배포 token을 폐기한다.**

`landit-dashboard-provisioner`에서 생성한 token을 삭제하고 active token이 남지 않았는지 확인한다. service account 자체는 다음 수동 배포를 위해 유지한다.

- [x] **Step 6: 운영 문서를 갱신한다.**

`docs/observability.md`에 dashboard URL, 환경 전환, 로그 검색, JSON 동기화 명령, token 발급·폐기 절차를 추가한다. `checklist.md`와 `context-notes.md`에는 실제 dashboard URL과 검증 결과만 기록하고 token은 기록하지 않는다.

- [x] **Step 7: 전체 로컬 검증을 실행한다.**

```bash
terraform fmt -recursive -check
AWS_PROFILE=landit terraform -chdir=environments/dev validate
AWS_PROFILE=landit terraform -chdir=environments/prod validate
bash -n scripts/sync-grafana-dashboards.sh
for file in grafana/dashboards/*.json; do jq -e . "$file" >/dev/null; done
if rg -n 'glsa_[A-Za-z0-9_-]{20,}|glc_[A-Za-z0-9_-]{20,}' grafana scripts docs checklist.md context-notes.md; then exit 1; fi
git diff --check
git status --short
```

Expected: 모든 명령이 exit code `0`이고 의도한 문서 파일만 수정 상태다.

- [x] **Step 8: 검증 문서를 커밋한다.**

```bash
git add docs/observability.md checklist.md context-notes.md
git commit -m "docs: Grafana dashboard 운영과 검증 결과 반영"
```

- [x] **Step 9: 최종 상태를 push한다.**

```bash
git status --short
git log --oneline -5
git push origin HEAD:main
```

Expected: 작업 트리가 clean이고 `origin/main`에 LAN-122 dashboard 관련 커밋이 반영된다.
