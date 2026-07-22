# LAN-192 Grafana Alert Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** prod BE·AI의 급성 5xx 장애, 지속 5xx 장애, 장기 관측 공백을 구분해 Discord에 낮은 노이즈로 전달한다.

**Architecture:** Grafana Cloud의 기존 Discord contact point는 유지하고, 단기 Editor service account로 Alerting Provisioning HTTP API를 호출한다. 새 여섯 rule과 prod 전용 notification route를 먼저 생성·검증한 뒤 기존 단일 5xx rule을 제거하며, 저장소에는 live export의 구조를 검사하는 계약 스크립트와 운영 문서만 남긴다.

**Tech Stack:** Grafana Cloud Alerting Provisioning HTTP API, Prometheus, PromQL, Bash, curl, jq, Discord webhook contact point.

## Global Constraints

- 대상은 `deployment_environment_name="prod"`인 BE와 AI뿐이며 develop은 제외한다.
- CRITICAL은 최근 2분 5xx 3건 이상과 오류율 50% 이상을 1분간 유지한다.
- WARNING은 최근 10분 5xx 10건 이상과 오류율 20% 이상을 3분간 유지한다.
- MONITORING은 runtime metric이 10분간 없고 그 상태가 5분간 유지될 때 알린다.
- 모든 rule의 evaluation interval은 1분, keep firing for는 5분이다.
- 알림은 `service`, `severity`로 묶고 group wait 30초, group interval 5분, repeat interval 1시간을 사용한다.
- Firing과 Resolved는 모두 `#alerts-grafana-prod`로 보낸다.
- service account token, Discord webhook URL, contact point secure setting은 저장소·문서·명령 출력에 남기지 않는다.
- 운영 rule 변경 전 현재 alert rule, contact point, notification policy JSON을 `/private/tmp`에 백업한다.

---

### Task 1: Live Grafana alert 기준선과 PromQL 검증

**Files:**
- Modify: `checklist.md` — live 기준선과 PromQL 검증 상태를 반영한다.
- Modify: `context-notes.md` — 익명화한 live rule·datasource·query 검증 결과를 기록한다.
- Runtime only: `/private/tmp/lan192-grafana-token` — 종료 시 삭제할 임시 token.
- Runtime only: `/private/tmp/lan192-grafana-*-before.json` — 기존 alert rule, contact point, notification policy 백업.

**Interfaces:**
- Consumes: 로그인된 Grafana Cloud session과 기존 `#alerts-grafana-prod` Discord contact point.
- Produces: 기존 rule UID·folder UID·rule group, 유일한 Discord receiver 이름, Prometheus datasource UID, BE·AI PromQL 검증 결과.

- [ ] **Step 1: 임시 Editor service account와 token을 만든다.**

Grafana UI에서 `lan192-alert-improvement-20260722` service account를 Editor 역할로 만들고 token을 생성한다. token은 권한 `0600`의 `/private/tmp/lan192-grafana-token`에만 저장한다.

- [ ] **Step 2: API 인증과 현재 alert 상태를 백업한다.**

```bash
export GRAFANA_URL='https://scarletmyrtle3008.grafana.net'
export GRAFANA_SERVICE_ACCOUNT_TOKEN="$(< /private/tmp/lan192-grafana-token)"
curl --fail --silent --show-error --header "Authorization: Bearer ${GRAFANA_SERVICE_ACCOUNT_TOKEN}" \
  "${GRAFANA_URL}/api/v1/provisioning/alert-rules" \
  --output /private/tmp/lan192-grafana-alert-rules-before.json
curl --fail --silent --show-error --header "Authorization: Bearer ${GRAFANA_SERVICE_ACCOUNT_TOKEN}" \
  "${GRAFANA_URL}/api/v1/provisioning/contact-points" \
  --output /private/tmp/lan192-grafana-contact-points-before.json
curl --fail --silent --show-error --header "Authorization: Bearer ${GRAFANA_SERVICE_ACCOUNT_TOKEN}" \
  "${GRAFANA_URL}/api/v1/provisioning/policies" \
  --output /private/tmp/lan192-grafana-policy-before.json
jq -e 'type == "array"' /private/tmp/lan192-grafana-alert-rules-before.json >/dev/null
jq -e '[.[] | select(.type == "discord") | .name] | unique | length == 1' \
  /private/tmp/lan192-grafana-contact-points-before.json >/dev/null
```

Expected: 모든 HTTP 요청이 성공하고 Discord contact point 이름은 정확히 하나다. webhook URL과 secure setting 값은 출력하지 않는다.

- [ ] **Step 3: 헬스체크를 제외한 PromQL을 datasource query API로 검증한다.**

BE 5xx count·ratio는 `uri!~"/actuator.*"`, AI 5xx count·ratio는 `http_route!="/health"`를 분자와 분모에 모두 사용한다. MONITORING은 아래 query를 사용한다.

```promql
absent_over_time(jvm_threads_live{service_name="landit-be",deployment_environment_name="prod"}[10m])
absent_over_time(process_thread_count{service_name="landit-ai",deployment_environment_name="prod"}[10m])
```

Grafana `/api/ds/query`에 여섯 query를 요청해 HTTP 200, frame error 없음, 5xx query의 숫자 결과, runtime metric 존재 시 `absent_over_time`의 빈 결과를 확인한다.

- [ ] **Step 4: 기준선 기록을 커밋한다.**

```bash
git add checklist.md context-notes.md
git commit -m "docs: Grafana 알림 기준선을 기록한다"
```

Expected: secret 없이 live rule 이름, datasource UID 검증, query 성공 여부만 커밋된다.

---

### Task 2: Live alert configuration 계약 검사

**Files:**
- Create: `scripts/test-grafana-alert-config.sh` — Grafana API export가 승인된 여섯 rule과 prod Discord route 계약을 만족하는지 검사한다.

**Interfaces:**
- Consumes: `GRAFANA_ALERT_RULES_JSON`, `GRAFANA_CONTACT_POINTS_JSON`, `GRAFANA_NOTIFICATION_POLICY_JSON`이 가리키는 JSON 파일.
- Produces: 계약 충족 시 exit 0, rule·route 누락 또는 조건 불일치 시 non-zero.

- [ ] **Step 1: 현재 live export를 대상으로 실패하는 계약 검사를 작성한다.**

```bash
#!/usr/bin/env bash
# Grafana prod 장애 알림 규칙과 Discord 라우팅 계약을 검증한다.
set -euo pipefail

: "${GRAFANA_ALERT_RULES_JSON:?GRAFANA_ALERT_RULES_JSON is required}"
: "${GRAFANA_CONTACT_POINTS_JSON:?GRAFANA_CONTACT_POINTS_JSON is required}"
: "${GRAFANA_NOTIFICATION_POLICY_JSON:?GRAFANA_NOTIFICATION_POLICY_JSON is required}"

discord_receiver="$(jq -er '[.[] | select(.type == "discord") | .name] | unique |
  if length == 1 then .[0] else error("expected one Discord receiver") end' \
  "${GRAFANA_CONTACT_POINTS_JSON}")"

jq -e '
  def duration_is($actual; $short; $long): $actual == $short or $actual == $long;
  def one($title): [.[] | select(.title == $title)] | length == 1;
  def matches($title; $severity; $pending; $pendingLong; $errorState; $needles):
    [.[] | select(.title == $title)][0] as $rule
    | $rule.labels.environment == "prod"
      and $rule.labels.severity == $severity
      and duration_is($rule.for; $pending; $pendingLong)
      and duration_is($rule.keepFiringFor; "5m"; "5m0s")
      and $rule.noDataState == "OK"
      and $rule.execErrState == $errorState
      and all($needles[]; . as $needle |
        any($rule.data[]; ((.model.expr // .model.expression // "") | contains($needle))));
  one("prod-be-http-5xx-critical")
  and one("prod-ai-http-5xx-critical")
  and one("prod-be-http-5xx-warning")
  and one("prod-ai-http-5xx-warning")
  and one("prod-be-telemetry-missing")
  and one("prod-ai-telemetry-missing")
  and matches("prod-be-http-5xx-critical"; "critical"; "1m"; "1m0s"; "KeepLast";
    ["http_server_requests_milliseconds_count", "uri!~\"/actuator.*\"", "[2m]", "$A >= 3", "$B >= 0.5"])
  and matches("prod-ai-http-5xx-critical"; "critical"; "1m"; "1m0s"; "KeepLast";
    ["http_server_request_duration_seconds_count", "http_route!=\"/health\"", "[2m]", "$A >= 3", "$B >= 0.5"])
  and matches("prod-be-http-5xx-warning"; "warning"; "3m"; "3m0s"; "KeepLast";
    ["http_server_requests_milliseconds_count", "uri!~\"/actuator.*\"", "[10m]", "$A >= 10", "$B >= 0.2"])
  and matches("prod-ai-http-5xx-warning"; "warning"; "3m"; "3m0s"; "KeepLast";
    ["http_server_request_duration_seconds_count", "http_route!=\"/health\"", "[10m]", "$A >= 10", "$B >= 0.2"])
  and matches("prod-be-telemetry-missing"; "monitoring"; "5m"; "5m0s"; "Error";
    ["absent_over_time(jvm_threads_live", "[10m]"])
  and matches("prod-ai-telemetry-missing"; "monitoring"; "5m"; "5m0s"; "Error";
    ["absent_over_time(process_thread_count", "[10m]"])
' "${GRAFANA_ALERT_RULES_JSON}" >/dev/null

jq -e --arg receiver "${discord_receiver}" '
  [.. | objects
    | select(.receiver? == $receiver)
    | select(.group_by? == ["service", "severity"])
    | select(.group_wait? == "30s")
    | select(.group_interval? == "5m")
    | select(.repeat_interval? == "1h")
    | select(any(.object_matchers[]?; . == ["environment", "=", "prod"]))]
  | length == 1
' "${GRAFANA_NOTIFICATION_POLICY_JSON}" >/dev/null
```

- [ ] **Step 2: 기존 설정에서 RED를 확인한다.**

```bash
chmod +x scripts/test-grafana-alert-config.sh
GRAFANA_ALERT_RULES_JSON=/private/tmp/lan192-grafana-alert-rules-before.json \
GRAFANA_CONTACT_POINTS_JSON=/private/tmp/lan192-grafana-contact-points-before.json \
GRAFANA_NOTIFICATION_POLICY_JSON=/private/tmp/lan192-grafana-policy-before.json \
  bash scripts/test-grafana-alert-config.sh
```

Expected: 기존 단일 rule만 있으므로 non-zero로 실패한다.

- [ ] **Step 3: 셸 문법과 diff를 검사하고 커밋한다.**

```bash
bash -n scripts/test-grafana-alert-config.sh
git diff --check
git add scripts/test-grafana-alert-config.sh
git commit -m "test: Grafana 장애 알림 계약을 검증한다"
```

Expected: 문법·diff 검사는 exit 0이고 계약 스크립트만 커밋된다.

---

### Task 3: 여섯 alert rule과 prod Discord route 적용

**Files:**
- Runtime only: `/private/tmp/lan192-grafana-rule-payloads/` — API 요청 payload와 응답. secret을 포함하지 않는다.
- Runtime only: `/private/tmp/lan192-grafana-policy-after.json` — 기존 route를 보존하고 prod Discord child route만 추가한 policy.
- Modify: `checklist.md` — live 적용과 계약 검증 상태를 반영한다.
- Modify: `context-notes.md` — 생성 UID, 상태, 삭제한 기존 UID, notification route 검증을 기록한다.

**Interfaces:**
- Consumes: Task 1의 folder UID·rule group·datasource UID·Discord receiver와 Task 2의 계약 검사.
- Produces: Normal 상태의 여섯 prod rule, `service`·`severity` 그룹화 route, 제거된 기존 단일 rule 두 개.

- [ ] **Step 1: 기존 rule을 API 요청 형식으로 정규화한다.**

기존 BE·AI rule에서 `folderUID`, `ruleGroup`, Prometheus `datasourceUid`, query model 공통 필드를 추출한다. 새 rule payload는 `X-Disable-Provenance: true`로 생성해 UI 편집 가능 상태를 유지한다. 모든 payload는 `orgId`, 빈 `uid`, `condition`, `annotations`, `labels`, `data`, `for`, `keepFiringFor`, `noDataState`, `execErrState`, `isPaused=false`를 명시한다.

- [ ] **Step 2: CRITICAL과 WARNING payload를 생성한다.**

각 rule의 data는 A 오류 건수, B 오류율, C Math condition 세 query로 구성한다. C expression은 CRITICAL에서 `($A >= 3) && ($B >= 0.5)`, WARNING에서 `($A >= 10) && ($B >= 0.2)`로 고정한다. annotations에는 summary, 평가 기간, 건수·비율 임계치, 서비스 dashboard URL을 넣는다.

- [ ] **Step 3: MONITORING payload를 생성한다.**

각 rule은 A `absent_over_time()` query, B Reduce `last`, C Threshold `B > 0`으로 구성한다. BE는 `jvm_threads_live`, AI는 `process_thread_count`를 사용하고 `execErrState="Error"`, `noDataState="OK"`, `for="5m"`, `keepFiringFor="5m"`를 적용한다.

- [ ] **Step 4: 새 여섯 rule을 생성하고 Normal 상태를 확인한다.**

```bash
for payload in /private/tmp/lan192-grafana-rule-payloads/*.json; do
  curl --fail --silent --show-error \
    --request POST \
    --header "Authorization: Bearer ${GRAFANA_SERVICE_ACCOUNT_TOKEN}" \
    --header 'Content-Type: application/json' \
    --header 'X-Disable-Provenance: true' \
    --data-binary "@${payload}" \
    "${GRAFANA_URL}/api/v1/provisioning/alert-rules" >/dev/null
done
```

Expected: 여섯 POST가 모두 성공하고 Alerting UI/API에서 여섯 rule이 Error 없이 Normal이다. 하나라도 Error이면 새 rule을 삭제하고 기존 rule을 유지한다.

- [ ] **Step 5: 기존 policy의 다른 route를 보존하며 prod Discord child route를 추가한다.**

Discord receiver는 Task 1에서 확인한 유일한 Discord contact point 이름을 사용한다. root receiver와 기존 route는 변경하지 않고 아래 속성의 child route만 추가한다.

```json
{
  "object_matchers": [["environment", "=", "prod"]],
  "group_by": ["service", "severity"],
  "group_wait": "30s",
  "group_interval": "5m",
  "repeat_interval": "1h",
  "continue": false
}
```

`jq --arg receiver "${discord_receiver}"`로 live receiver 이름을 주입한다. PUT 전후 JSON에서 새 child route 외의 root·route 구조가 동일한지 `jq` 정규화 diff로 확인한다.

- [ ] **Step 6: live export가 계약을 만족하는지 GREEN을 확인한다.**

```bash
curl --fail --silent --show-error --header "Authorization: Bearer ${GRAFANA_SERVICE_ACCOUNT_TOKEN}" \
  "${GRAFANA_URL}/api/v1/provisioning/alert-rules" \
  --output /private/tmp/lan192-grafana-alert-rules-after.json
curl --fail --silent --show-error --header "Authorization: Bearer ${GRAFANA_SERVICE_ACCOUNT_TOKEN}" \
  "${GRAFANA_URL}/api/v1/provisioning/policies" \
  --output /private/tmp/lan192-grafana-policy-after.json
GRAFANA_ALERT_RULES_JSON=/private/tmp/lan192-grafana-alert-rules-after.json \
GRAFANA_CONTACT_POINTS_JSON=/private/tmp/lan192-grafana-contact-points-before.json \
GRAFANA_NOTIFICATION_POLICY_JSON=/private/tmp/lan192-grafana-policy-after.json \
  bash scripts/test-grafana-alert-config.sh
```

Expected: exit 0.

- [ ] **Step 7: 새 rule과 route 검증 뒤 기존 단일 rule 두 개를 삭제한다.**

삭제 대상은 title이 정확히 `prod-be-http-5xx-incident`, `prod-ai-http-5xx-incident`인 UID 두 개로 제한한다. 삭제 직전 before export에서 UID와 title을 다시 매칭하고, 새 여섯 rule이 모두 존재하는 경우에만 DELETE한다. 삭제 후 재조회에서 기존 title 0개, 새 title 각 1개를 확인한다.

- [ ] **Step 8: 운영 반영 기록을 커밋한다.**

```bash
git add checklist.md context-notes.md
git commit -m "docs: Grafana 다단계 알림 적용을 기록한다"
```

---

### Task 4: Discord Firing·Resolved 검증과 운영 문서 마감

**Files:**
- Modify: `docs/observability.md` — 조건, 상태 전이, 알림 그룹화, 운영 확인 절차를 기록한다.
- Modify: `checklist.md` — Firing·Resolved·관측 공백 검증을 완료 처리한다.
- Modify: `context-notes.md` — test rule과 Discord 수신, 최종 live 상태, 임시 credential 폐기를 기록한다.

**Interfaces:**
- Consumes: Task 3의 여섯 rule, prod Discord route, 기존 Discord contact point.
- Produces: 실제 Discord 수신 증거, 문서와 live 상태 일치, 폐기된 임시 service account와 token.

- [ ] **Step 1: `[TEST]` CRITICAL rule로 Firing을 검증한다.**

운영 CRITICAL rule의 datasource와 route label을 복제하되 title은 `[TEST] prod-be-http-5xx-critical`, expression은 `vector(1)`, pending은 `0s`, keep firing은 `0s`로 만든다. Discord에서 `[TEST][FIRING][CRITICAL][PROD][BE]`와 dashboard 링크를 확인한다. 운영 rule의 query와 상태는 변경하지 않는다.

- [ ] **Step 2: test rule을 Normal로 바꿔 Resolved를 검증한다.**

동일 UID의 expression을 `vector(0)`으로 PUT하고 다음 evaluation 뒤 `[TEST][RESOLVED][CRITICAL][PROD][BE]`가 도착하는지 확인한다. 확인 직후 test rule을 DELETE하고 title·UID가 더 이상 조회되지 않는지 검증한다.

- [ ] **Step 3: `[TEST]` MONITORING rule로 관측 공백 메시지를 검증한다.**

title `[TEST] prod-ai-telemetry-missing`, query `absent_over_time(landit_nonexistent_metric{service_name="landit-ai",deployment_environment_name="prod"}[1m])`, pending `0s`, keep firing `0s`인 test rule을 만든다. `[TEST][FIRING][MONITORING][PROD][AI]`가 도착하고 metric 이름과 관측 공백 설명이 포함됐는지 확인한 뒤 rule을 삭제한다.

- [ ] **Step 4: 최종 live 상태와 계약을 재검증한다.**

여섯 운영 rule이 모두 unpaused이고 Error가 아니며 test rule과 기존 단일 rule이 없음을 확인한다. alert rules·contact points·policy를 다시 export해 `scripts/test-grafana-alert-config.sh`를 실행하고 exit 0을 확인한다.

- [ ] **Step 5: 운영 문서와 체크리스트를 갱신한다.**

`docs/observability.md`에 여섯 rule 표, exact threshold, No Data·Error 처리, route timer, 7일 보정 절차를 기록한다. webhook URL, token, contact point secure setting, API response의 민감값은 기록하지 않는다.

- [ ] **Step 6: 전체 검증을 실행한다.**

```bash
bash -n scripts/test-grafana-alert-config.sh
GRAFANA_ALERT_RULES_JSON=/private/tmp/lan192-grafana-alert-rules-after.json \
GRAFANA_CONTACT_POINTS_JSON=/private/tmp/lan192-grafana-contact-points-before.json \
GRAFANA_NOTIFICATION_POLICY_JSON=/private/tmp/lan192-grafana-policy-after.json \
  bash scripts/test-grafana-alert-config.sh
terraform fmt -recursive -check
git diff --check
git status --short
```

Expected: 스크립트와 fmt·diff check가 모두 통과하고 status에는 의도한 문서 변경만 표시된다.

- [ ] **Step 7: 문서 마감 커밋을 만든다.**

```bash
git add docs/observability.md checklist.md context-notes.md
git commit -m "docs: Grafana 장애 알림 운영 절차를 반영한다"
```

- [ ] **Step 8: 임시 credential과 runtime 파일을 폐기한다.**

Grafana UI에서 `lan192-alert-improvement-20260722` service account를 삭제하고 token이 인증에 실패하는지 확인한다. `/private/tmp/lan192-grafana-token`과 live export·payload 파일은 secret 포함 여부를 확인한 뒤 삭제하며, 저장소와 git diff에서 token·webhook URL 패턴이 없는지 검사한다.
