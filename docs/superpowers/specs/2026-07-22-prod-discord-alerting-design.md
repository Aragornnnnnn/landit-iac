# LAN-192 prod Discord 장애 알림 설계

## 목표

prod에서 즉시 확인이 필요한 애플리케이션 장애를 Sentry와 Grafana에서 각각 전용 Discord 채널로 전달한다. 신규·회귀 예외는 빠르게 발견하고, 반복 event와 일시적인 지표 변동으로 인한 알림 피로는 줄인다.

## 범위

### 포함

- prod BE·AI Sentry issue 알림.
- prod BE·AI HTTP 5xx Grafana alert.
- Sentry와 Grafana의 기본 Discord integration.
- 실제 Discord 수신과 Grafana 복구 알림 검증.

### 제외

- develop 알림.
- P95 응답시간, 트래픽 없음, 지표 없음, 에러 로그 발생량 alert.
- ECS CPU·memory와 ALB 지표 alert.
- 별도 webhook 중계 서비스.
- Grafana provider, alert 자동 배포 workflow, Terraform state 추가.
- Discord webhook URL과 integration credential의 저장소 관리.

현재 Grafana Cloud에는 prod BE·AI 애플리케이션 지표와 Loki 로그가 있다. 조직 SCP 제약 때문에 ECS와 ALB CloudWatch 지표는 수집하지 않으므로 이번 alert 범위에 포함하지 않는다.

## 알림 흐름

```text
Sentry prod BE·AI
  -> Sentry Discord integration
  -> #alerts-sentry-prod

Grafana Cloud prod BE·AI 5xx alert rules
  -> Grafana Discord contact point
  -> #alerts-grafana-prod
```

Sentry와 Grafana가 Discord에 직접 전송한다. 메시지 변환용 Lambda, Worker, bot은 만들지 않는다.

## Sentry 설계

### 대상

- BE Sentry project의 `prod` environment.
- AI Sentry project의 `prod` environment.

두 project는 같은 `#alerts-sentry-prod` 채널을 사용하되 메시지에서 project와 environment를 식별할 수 있어야 한다.

### 발송 조건

BE와 AI project에 아래 두 rule을 각각 만든다. 총 네 개의 rule이 같은 Discord 채널로 전송한다.

1. 신규·회귀 rule은 prod에서 처음 확인된 issue 또는 해결 뒤 회귀한 issue를 즉시 알린다.
2. 반복 급증 rule은 동일 issue가 5분 동안 10회 이상 발생하면 알린다.

개별 반복 event와 issue resolved 상태는 알리지 않는다. 같은 issue에서 같은 rule이 계속 충족되더라도 30분 안에는 다시 발송하지 않는다.

### 메시지 필수 정보

- `[PROD]`와 BE 또는 AI project 이름.
- issue 제목과 exception 유형.
- 최초 발생, 회귀, 반복 급증 중 어떤 조건인지.
- 최근 발생 횟수와 영향 사용자 수를 Sentry가 제공하는 범위에서 표시.
- Sentry issue 상세 링크.

## Grafana 설계

### 대상 alert rule

BE와 AI를 별도 rule로 만든다.

| Rule | 서비스 | 기준 지표 |
| --- | --- | --- |
| `prod-be-http-5xx-critical` | BE | `http_server_requests_milliseconds_count` |
| `prod-ai-http-5xx-critical` | AI | `http_server_request_duration_seconds_count` |

두 rule 모두 `deployment_environment_name="prod"`를 쿼리에 고정한다. Dashboard 변수에 의존하지 않는다.

### 장애 조건

최근 5분 동안 아래 두 조건을 모두 만족하면 장애 후보로 판단한다.

- 5xx 응답 5건 이상.
- 전체 요청 중 5xx 비율 20% 이상.

BE는 `status=~"5.."`, AI는 `http_response_status_code=~"5.."` label로 5xx를 계산한다. 누적 counter의 5분 증가량은 PromQL `increase()`로 계산한다. 오류 건수와 오류율을 함께 사용해 요청 한두 건의 실패가 바로 장애 알림으로 이어지지 않게 한다.

### 평가와 상태 전이

- Evaluation interval은 1분이다.
- Pending period는 2분이다.
- Keep firing for는 5분이다.
- No Data 상태는 Normal로 처리한다.
- Error 상태는 Keep Last State로 처리한다.
- Firing과 Resolved 전환을 Discord로 보낸다.

현재 트래픽이 없거나 OTLP 시계열이 잠시 비는 상황을 서비스 장애로 단정할 수 없으므로 No Data는 알리지 않는다. alert query 자체의 평가 실패도 초기 장애 채널에는 보내지 않는다. 이 선택은 alert pipeline 장애를 Discord에서 놓칠 수 있는 위험이 있으므로 운영 안정화 뒤 별도 관측성 상태 알림으로 재검토한다.

### 메시지 필수 정보

- `[FIRING][PROD][BE]` 또는 `[FIRING][PROD][AI]` 제목.
- 최근 5분 5xx 건수와 오류율.
- 임계치와 firing 시작 시각.
- 해당 서비스 Grafana dashboard 링크.
- Resolved 메시지에는 복구 시각과 firing 지속 시간을 표시.

## 설정 관리

LAN-192의 초기 구현은 Sentry와 Grafana Cloud UI에서 기본 integration과 alert rule을 설정한다. 저장소에는 승인된 조건과 검증 결과만 기록한다.

Grafana dashboard JSON의 기존 동기화 방식은 유지한다. alert rule provisioning, Grafana provider, 장기 service account token은 추가하지 않는다. alert rule 수가 늘어나 수동 설정 drift가 실제 문제가 될 때 별도 자동화를 검토한다.

## 보안

- Discord webhook URL은 secret으로 취급한다.
- webhook URL을 저장소, Terraform variable, Terraform state, 문서, 명령 출력에 넣지 않는다.
- Grafana contact point의 보호된 필드에만 webhook URL을 저장한다.
- Sentry는 공식 Discord integration authorization을 사용한다.
- Discord webhook은 지정된 알림 채널에만 연결하고 채널 접근 권한을 운영 인원으로 제한한다.
- webhook 노출이 의심되면 Discord에서 즉시 재생성하고 기존 webhook을 폐기한다.

## 검증

실제 장애를 만들지 않고 아래 순서로 검증한다.

1. Sentry Discord integration의 test notification이 `#alerts-sentry-prod`에 도착하는지 확인한다.
2. Sentry test event 또는 전용 검증 event가 prod 조건의 신규 issue 알림을 한 번 발생시키는지 확인한다.
3. Grafana Discord contact point의 test notification이 `#alerts-grafana-prod`에 도착하는지 확인한다.
4. 운영 rule을 복제한 단기 test rule로 firing 메시지를 확인한다.
5. test rule 조건을 정상화해 Resolved 메시지를 확인한다.
6. 두 채널에 develop 알림이 전달되지 않는지 설정을 다시 확인한다.
7. 검증용 test rule과 test issue를 정리하고 운영 rule이 Normal 상태인지 확인한다.

test event와 test rule은 제목에 `[TEST]`를 포함해 실제 장애와 구분한다.

## 성공 기준

- prod Sentry 신규·회귀·반복 급증 알림만 `#alerts-sentry-prod`에 전달된다.
- prod BE·AI 5xx 장애와 복구 알림만 `#alerts-grafana-prod`에 전달된다.
- develop event와 지표는 두 Discord 채널의 조건에서 제외된다.
- Discord webhook URL과 credential이 저장소와 Terraform state에 남지 않는다.
- test notification, firing, resolved 경로의 실제 Discord 수신 증거가 기록된다.

## 참고 문서

- [Sentry Discord integration](https://docs.sentry.io/api/integrations/get-integration-provider-information/)
- [Grafana Discord contact point](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/configure-discord/)
- [Grafana alert rule evaluation](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/)
- [Grafana No Data and Error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/nodata-and-error-states/)
