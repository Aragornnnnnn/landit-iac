# Grafana Cloud 대시보드 설계

## 목표

Landit 운영자가 Grafana Cloud에서 환경별 BE·AI 상태를 빠르게 확인하고, 이상 징후가 있으면 서비스별 메트릭과 로그로 바로 이동할 수 있도록 대시보드를 구성한다.

대시보드는 `prod`와 `develop`을 복제하지 않는다. 모든 대시보드에 환경 변수를 두고 기본값을 `prod`로 설정한다.

## 현재 데이터

### 메트릭

- 데이터 소스 UID는 `grafanacloud-prom`이다.
- 공통 라벨은 `service_name`과 `deployment_environment_name`이다.
- 서비스 이름은 `landit-be`, `landit-ai`이다.
- 환경 이름은 `develop`, `prod`이다.
- BE는 HTTP, JVM memory, JVM GC, JVM thread 메트릭을 전송한다.
- AI는 HTTP, process CPU·memory·thread, CPython GC 메트릭을 전송한다.

### 로그

- 데이터 소스 UID는 `grafanacloud-logs`이다.
- 공통 라벨은 `project`, `environment`, `aws_log_group`이다.
- `project` 값은 `landit`이다.
- BE 로그 그룹은 `/landit/{environment}/api`이다.
- AI 로그 그룹은 `/landit/{environment}/worker`이다.
- 로그에는 별도 `level` 라벨이 없으므로 에러 로그는 본문 정규식으로 구분한다.

## 선택한 접근법

대시보드 JSON을 `landit-iac`에서 관리하고 Grafana HTTP API로 배포한다.

UI에서 직접 수정하는 방식은 변경 이력을 남기기 어렵다. Grafana Terraform provider는 단일 Grafana stack을 위해 별도 state와 workflow를 추가해야 하므로 현재 범위에서는 사용하지 않는다.

공개 JVM·FastAPI 대시보드는 화면 구성만 참고한다. 실제 쿼리는 Landit이 전송하는 메트릭 이름과 라벨에 맞춰 작성한다.

## 파일 구조

```text
grafana/
  dashboards/
    landit-overview.json
    landit-be.json
    landit-ai.json
scripts/
  sync-grafana-dashboards.sh
```

dashboard UID는 각각 `landit-overview`, `landit-be`, `landit-ai`로 고정한다. Grafana folder 제목은 `Landit`, UID는 `landit-observability`로 고정한다.

## 공통 설정

- 기본 시간 범위는 최근 1시간이다.
- 자동 새로고침 주기는 30초이다.
- 기본 환경은 `prod`이다.
- 모든 메트릭 패널은 `deployment_environment_name="$environment"`를 사용한다.
- 모든 로그 패널은 `project="landit"`, `environment="$environment"`를 사용한다.
- 환경 변수는 `prod`, `develop` 두 값만 제공한다.
- dashboard link는 현재 시간 범위와 환경 값을 유지한다.
- 데이터가 없을 때는 0으로 보이지 않도록 `No data` 상태를 유지한다.

## Landit Overview

운영자가 처음 여는 대시보드다. BE와 AI의 요청 상태와 로그를 한 화면에 배치한다.

### 상단 상태 요약

- 전체 TPS.
- BE TPS.
- AI TPS.
- 전체 5xx 오류율.
- BE P95 응답시간.
- AI P95 응답시간.

BE와 AI의 HTTP 메트릭 이름이 다르므로 각 서비스 쿼리를 별도로 작성하고 패널에서 합산한다.

### 요청 추이

- 시간대별 BE·AI TPS.
- 시간대별 BE·AI 5xx 오류율.
- 서비스별 P50, P95, P99 응답시간.
- 요청량이 많은 endpoint 표.

### 로그 요약

- BE·AI 로그 발생량 추이.
- BE·AI 에러 로그 발생량 추이.
- 전체 로그 패널.
- 에러 로그 패널.

전체 로그 패널은 선택한 환경의 BE·AI 로그를 시간 역순으로 표시한다. `service` 변수로 전체, BE, AI를 선택하고 `log_search` 변수로 본문을 검색한다.

에러 로그 패널은 아래 정규식에 일치하는 로그만 표시한다.

```text
(?i)(error|exception|traceback|critical|fatal)
```

구조화된 `level` 라벨이 추가되면 정규식 대신 라벨 필터로 교체한다.

## Landit BE

### 변수

- `environment`은 `prod`, `develop` 중 하나를 선택한다.
- `endpoint`는 `uri` 라벨에서 조회한다.
- `log_search`는 로그 본문 검색어를 입력한다.

### HTTP

- 전체 TPS와 endpoint별 TPS.
- 전체 요청 수.
- 5xx 오류율.
- 상태 코드별 요청 추이.
- endpoint별 P50, P95, P99 응답시간.
- 느린 endpoint 표.

기준 메트릭은 `http_server_requests_milliseconds_count`, `http_server_requests_milliseconds_sum`, `http_server_requests_milliseconds_bucket`이다.

### JVM

- heap used와 max.
- non-heap used.
- heap 사용률.
- GC pause 횟수와 평균·최대 pause time.
- allocation rate와 promotion rate.
- live, daemon, peak thread.
- loaded class 수.

기준 메트릭은 `jvm_memory_*`, `jvm_gc_*`, `jvm_threads_*`, `jvm_classes_*`이다.

### 로그

- 로그 발생량 추이.
- 에러 로그 발생량 추이.
- 전체 로그 패널.
- 에러 로그 패널.

로그 그룹은 `/landit/$environment/api`로 제한한다.

## Landit AI

### 변수

- `environment`은 `prod`, `develop` 중 하나를 선택한다.
- `endpoint`는 `http_route` 라벨에서 조회한다.
- `log_search`는 로그 본문 검색어를 입력한다.

### HTTP

- 전체 TPS와 endpoint별 TPS.
- 전체 요청 수.
- 5xx 오류율.
- 상태 코드별 요청 추이.
- endpoint별 P50, P95, P99 응답시간.
- 느린 endpoint 표.

기준 메트릭은 `http_server_request_duration_seconds_count`, `http_server_request_duration_seconds_sum`, `http_server_request_duration_seconds_bucket`이다.

### Python runtime

- process CPU 사용률.
- process physical·virtual memory.
- process thread 수.
- CPython GC 세대별 실행 횟수.
- GC 수집 객체 수와 미수집 객체 수.

기준 메트릭은 `process_cpu_*`, `process_memory_*`, `process_thread_count`, `cpython_gc_*`이다.

### 로그

- 로그 발생량 추이.
- 에러 로그 발생량 추이.
- 전체 로그 패널.
- 에러 로그 패널.

로그 그룹은 `/landit/$environment/worker`로 제한한다.

## 배포와 인증

Grafana UI 작업 자동화에는 Cloud Access Policy가 아닌 Grafana service account를 사용한다.

- service account 이름은 `landit-dashboard-provisioner`로 한다.
- folder 생성과 dashboard upsert가 가능한 `Editor` role을 사용한다.
- `Editor`는 token 유효 기간에 다른 dashboard도 수정할 수 있으므로 token 만료 시간을 1일로 제한하고 작업 직후 폐기한다.
- token은 `GRAFANA_SERVICE_ACCOUNT_TOKEN` 환경변수로만 전달한다.
- token 값을 파일, Git, Terraform state, 명령 출력에 남기지 않는다.
- 배포와 검증이 끝나면 token을 즉시 폐기한다.

동기화 스크립트는 다음 순서로 동작한다.

1. `GRAFANA_URL=https://scarletmyrtle3008.grafana.net`과 `GRAFANA_SERVICE_ACCOUNT_TOKEN`을 확인한다.
2. `/api/folders/landit-observability`를 조회하고 없으면 `/api/folders`로 생성한다.
3. `/api/dashboards/db`로 dashboard JSON 3개를 folder에 upsert한다.
4. 생성된 dashboard URL과 UID만 출력한다.

스크립트는 같은 입력으로 반복 실행해도 dashboard를 중복 생성하지 않아야 한다.

## 오류 처리

- 인증 실패 시 HTTP 상태 코드와 API 메시지만 출력하고 token은 출력하지 않는다.
- dashboard JSON이 유효하지 않으면 배포 전에 로컬 검증에서 실패한다.
- 데이터 소스 UID가 없으면 dashboard 생성 후 검증 단계에서 실패로 처리한다.
- 일부 패널이 `No data`이면 dashboard 전체를 완료로 판단하지 않는다.
- 로그 정규식은 운영 중 발견한 오탐 사례를 문서화한 뒤 조정한다.

## 검증

### 로컬 검증

- dashboard JSON 3개가 JSON parser를 통과한다.
- 고정 UID와 데이터 소스 UID가 모두 포함됐는지 확인한다.
- token 또는 Authorization header가 저장소에 포함되지 않았는지 검색한다.
- 동기화 스크립트의 shell 문법을 확인한다.

### Grafana 검증

- `prod`, `develop` 전환 시 모든 메트릭 패널이 선택한 환경으로 바뀐다.
- Overview에서 BE·AI TPS, 오류율, P95가 조회된다.
- BE에서 endpoint HTTP 지표와 JVM memory·GC·thread 지표가 조회된다.
- AI에서 endpoint HTTP 지표와 process CPU·memory·thread·GC 지표가 조회된다.
- 세 대시보드의 전체 로그와 에러 로그 패널이 올바른 log group을 조회한다.
- dashboard link가 환경과 시간 범위를 유지한다.
- 배포에 사용한 service account token을 폐기한 뒤 dashboard 조회가 유지된다.

## 제외 범위

- 알림 규칙과 온콜 연동.
- Sentry 이벤트를 Grafana panel에 표시하는 작업.
- Grafana CloudWatch scrape.
- ALB RequestCount와 ECS CPU·memory 대시보드.
- dashboard 변경 자동 배포용 GitHub Actions workflow.

알림과 CloudWatch 인프라 지표는 필요한 권한과 운영 기준이 정해지면 별도 이슈로 진행한다.
