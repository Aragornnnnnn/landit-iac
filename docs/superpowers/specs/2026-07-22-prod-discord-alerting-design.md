# LAN-192 prod 관측성과 Discord 장애 알림 설계

## 목표

prod에서 즉시 확인이 필요한 애플리케이션 장애를 Sentry와 Grafana에서 각각 전용 Discord 채널로 전달한다. AI 로그의 실제 level을 Grafana가 의미적으로 분류하게 하고, 반복되는 미매핑 요청은 ALB access log와 WAF `Count` 데이터로 호출 주체와 정상 트래픽 기준선을 확인할 수 있게 한다.

## 범위

### 포함

- prod BE·AI Sentry issue 알림.
- prod BE·AI HTTP 5xx Grafana alert.
- Sentry Internal Integration과 prod 전용 Lambda Discord relay.
- Grafana 기본 Discord webhook integration.
- 실제 Discord 수신과 Grafana 복구 알림 검증.
- AI 애플리케이션과 Uvicorn 로그의 명시적 `level` 필드.
- Landit AI와 Overview dashboard의 level 기반 에러 로그 조회.
- prod ALB access log 전용 S3 저장소.
- prod ALB에 연결하는 AWS WAF 관리형 규칙과 IP rate rule의 `Count` 모드.

### 제외

- develop 알림.
- P95 응답시간, 트래픽 없음, 지표 없음, 에러 로그 발생량 alert.
- ECS CPU·memory와 ALB 지표 alert.
- Sentry Team 플랜 업그레이드와 공식 Discord integration.
- Grafana provider, alert 자동 배포 workflow, Terraform state 추가.
- Discord webhook URL과 integration credential의 저장소 관리.
- BE 로그 형식 변경.
- WAF `Block` 전환과 정상 운영 IP 예외 목록.
- WAF·ALB CloudWatch metric의 Grafana 수집과 차단 알림.

현재 Grafana Cloud에는 prod BE·AI 애플리케이션 지표와 Loki 로그가 있다. 조직 SCP 제약 때문에 ECS와 ALB CloudWatch 지표는 수집하지 않으므로 이번 alert 범위에 포함하지 않는다.

## 알림 흐름

```text
Sentry prod BE·AI
  -> Sentry Internal Integration alert action
  -> API Gateway async Lambda integration
  -> Sentry Discord relay Lambda ingress
  -> 같은 Lambda의 비동기 delivery invocation
  -> #alerts-sentry-prod

Grafana Cloud prod BE·AI 5xx alert rules
  -> Grafana Discord contact point
  -> #alerts-grafana-prod

AI stdout/stderr
  -> CloudWatch Logs
  -> Data Firehose
  -> Grafana Loki

prod ALB
  -> S3 access log
  -> 7일 정상 요청량·IP·경로·User-Agent 관찰

prod ALB
  -> AWS WAF managed rules와 IP rate rule
  -> Count metric과 sampled request 관찰
```

Grafana는 Discord에 직접 전송한다. Sentry 공식 Discord integration은 Saynow의 현재 플랜에서 `Requires Team Plan or above`로 차단되므로, prod 전용 Lambda가 Sentry alert payload를 Discord webhook payload로 변환한다.

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

## AI 로그 level 설계

### 원인과 범위

AI worker의 Python logger는 `WARNING`으로 기록해도 현재 stdout message에 level을 남기지 않는다. Grafana는 본문의 `error`, `exception`, `traceback`, `critical`, `fatal` 문자열을 검색하므로 `reason=message_feedback_schema: Value error` 같은 복구 로그도 에러로 오분류한다.

Landit AI의 root logger와 Uvicorn logger가 모든 첫 로그 줄에 아래 필드를 기록하게 한다.

```text
level=WARNING logger=app.conversation.application.next_message_service message=workflow=...
```

기존 workflow와 reason message는 유지한다. `message_feedback_candidate_repair`, `message_feedback_candidate_fallback`, `message_feedback_failed`의 애플리케이션 log level도 이번 작업에서 바꾸지 않는다.

### Grafana 조회

Landit AI dashboard의 에러 발생량과 에러 로그 패널은 Loki `logfmt` parser로 `level`을 추출하고 `ERROR`, `CRITICAL`만 조회한다. 메시지 본문의 단어는 분류 조건으로 사용하지 않는다.

Landit Overview는 서비스 선택 변수를 유지하면서 BE와 AI query를 분리한다.

- BE는 기존 Spring log level 위치에 한정한 `ERROR`, `FATAL` 조회를 유지한다.
- AI는 `| logfmt | level=~"ERROR|CRITICAL"` 조회를 사용한다.

전체 로그, 피드백 후보 fallback, 피드백 생성 실패 패널은 기존 workflow 검색을 유지한다. 과거 AI 로그에는 `level` 필드가 없으므로 배포 시점 이전 데이터가 새 에러 패널에서 제외되는 것은 허용한다.

## Grafana 설계

### 대상 alert rule

BE와 AI를 별도 rule로 만든다.

| Rule | 서비스 | 기준 지표 |
| --- | --- | --- |
| `prod-be-http-5xx-incident` | BE | `http_server_requests_milliseconds_count` |
| `prod-ai-http-5xx-incident` | AI | `http_server_request_duration_seconds_count` |

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

## Lambda relay 설계

### 실행 경로

- prod Terraform root의 API Gateway와 Python Lambda를 유지한다.
- Sentry App webhook의 기본 HTTP timeout은 1초이므로 API Gateway가 Lambda를 `Event` 방식으로 호출하고 즉시 `204`를 반환한다.
- Lambda ingress는 body와 `Sentry-Hook-Signature` 형식을 확인한 뒤 같은 Lambda의 delivery를 `Event` 방식으로 비동기 호출한다.
- API Gateway mapping이 만든 ingress event와 내부 delivery event는 최상위 event 구조로 구분한다. 외부 request body에 내부 mode를 넣어도 delivery 경로로 진입할 수 없다.
- delivery invocation이 Sentry App client secret으로 raw body의 `Sentry-Hook-Signature` HMAC-SHA256을 상수 시간 비교한다.
- 인증에 실패하거나 payload environment가 명시적인 `prod`가 아니면 Discord로 보내지 않는다.
- 인증을 통과한 payload만 Sentry issue 제목, project 또는 rule 이름, level, environment, issue URL을 Discord embed로 변환한다.
- 비동기 delivery 오류는 Lambda async invocation의 기본 재시도 범위 안에서 최대 두 번 재시도한다.
- Lambda memory는 512MB, timeout은 10초, reserved concurrency는 2로 제한한다. 외부 cold request가 1초 안에 응답하는지는 실제 API Gateway endpoint 검증으로 확인한다.

API Gateway는 HMAC secret을 읽기 전에 ingress invocation을 만들기 때문에 형식만 맞춘 위조 request도 Lambda invocation을 만들 수 있다. delivery에서 HMAC을 반드시 검증해 Discord 오발송을 막는다. 공개 ingress는 Sentry 공식 US·US2·EU outbound IP만 허용하고 초당 1건, burst 5건으로 제한한다. 필수 signature header·signature 형식 검사·body 크기 제한과 Lambda reserved concurrency는 이 경계 뒤에서 추가 방어로 사용한다. 실제 API Gateway 검증에서 cold 요청은 약 0.10초, warm 요청은 약 0.05초에 `204`를 반환했다.

### 비밀값

Terraform은 아래 parameter의 이름과 ARN만 사용한다. 실제 값은 Terraform 밖에서 `SecureString`으로 작성한다.

```text
/landit/prod/LANDIT_SENTRY_RELAY_AUTH_TOKEN
/landit/prod/LANDIT_SENTRY_DISCORD_WEBHOOK_URL
```

Lambda 실행 role은 두 parameter에 대한 `ssm:GetParameters`와 자기 함수에 대한 `lambda:InvokeFunction`만 추가로 허용한다. secret 값은 Lambda 환경변수, Terraform variable, state, 문서와 명령 출력에 기록하지 않는다. `LANDIT_SENTRY_RELAY_AUTH_TOKEN`이라는 기존 path에는 Sentry App이 생성한 webhook signing secret을 저장한다.

## ALB access log와 WAF Count 설계

### ALB access log

prod ALB 전용 S3 bucket을 새로 만들고 ALB access log를 활성화한다. 애플리케이션 파일 bucket과 섞지 않는다.

- bucket 이름은 environment, project, account ID를 포함한다.
- public access는 전부 차단한다.
- ALB log delivery service principal만 account 전용 prefix에 `s3:PutObject`할 수 있다.
- SSE-S3 기본 암호화를 사용한다.
- object는 30일 뒤 만료한다.
- Terraform이나 로그 분석 결과에 전체 client IP와 민감 query를 문서화하지 않는다.

Access log로 status 404 요청의 실제 path, source IP, User-Agent, 시간대 분포를 7일 동안 확인한다. 과거 404 약 3,161건의 호출 주체는 access log가 없던 기간이라 소급 식별하지 않는다.

### WAF Count

prod ALB에 `REGIONAL` Web ACL을 연결하고 default action은 `Allow`로 둔다. 아래 rule은 모두 `Count`로 시작한다.

1. AWS Managed Rules Common Rule Set.
2. Amazon IP Reputation List.
3. source IP 기준 5분 2,000회 rate rule.

CloudWatch metric과 sampled request를 활성화한다. `Count` 단계에서는 정상 request를 차단하지 않는다. 7일 관찰 뒤 정상 사용자의 최고 요청량, 공유 NAT 환경, 내부 연동 IP를 확인해 별도 승인된 plan에서만 rate rule을 `Block`으로 전환한다.

## 설정 관리

Grafana Cloud의 contact point와 alert rule은 UI에서 관리한다. Sentry alert rule은 Sentry Internal Integration의 alert action으로 API Gateway endpoint를 호출한다. API Gateway, Lambda, IAM, log retention은 prod Terraform state에서 관리한다.

Grafana dashboard JSON의 기존 동기화 방식은 유지한다. alert rule provisioning, Grafana provider, 장기 service account token은 추가하지 않는다. alert rule 수가 늘어나 수동 설정 drift가 실제 문제가 될 때 별도 자동화를 검토한다.

AI logging 설정은 `landit-ai`, dashboard JSON과 AWS 리소스는 `landit-iac`에서 관리한다. 두 저장소의 변경은 같은 LAN-192 이슈를 사용하되 저장소별 커밋으로 분리한다.

ALB access log와 WAF는 module에서 선택적으로 활성화할 수 있게 하고 이번에는 prod root만 켠다. develop ALB에는 적용하지 않는다.

## 보안

- Discord webhook URL은 secret으로 취급한다.
- webhook URL을 저장소, Terraform variable, Terraform state, 문서, 명령 출력에 넣지 않는다.
- Grafana contact point의 보호된 필드에만 webhook URL을 저장한다.
- Sentry App의 공식 `Sentry-Hook-Signature`를 사용하고 signing secret을 custom header로 전송하지 않는다.
- Lambda delivery는 signature를 상수 시간 비교하고 prod가 아닌 payload를 전달하지 않는다.
- API Gateway method는 signature header를 필수로 받고 Lambda는 body·signature 형식, timeout, memory, reserved concurrency를 제한해 오용 범위를 줄인다.
- Lambda는 Discord webhook URL과 signing secret을 SSM에서 한 번에 복호화해 읽고 로그에 출력하지 않는다.
- Discord webhook은 지정된 알림 채널에만 연결하고 채널 접근 권한을 운영 인원으로 제한한다.
- webhook 노출이 의심되면 Discord에서 즉시 재생성하고 기존 webhook을 폐기한다.
- ALB access log bucket은 public access를 차단하고 30일 retention으로 원본 client 정보를 제한한다.
- WAF는 관찰 기간에 `Count`만 사용하고 사용자 승인 없는 `Block` 전환을 금지한다.

## 검증

실제 장애를 만들지 않고 아래 순서로 검증한다.

1. Lambda unit test로 ingress 비동기 dispatch, delivery signature 검증, non-prod 제외, payload 변환을 확인한다.
2. 새 Lambda code 배포 직후 cold ingress가 1초 안에 `204`를 반환하고 비동기 delivery가 `#alerts-sentry-prod`에 도착하는지 확인한다.
3. 잘못된 signature와 non-prod request가 Discord로 전달되지 않는지 확인한다.
4. Sentry test event 또는 전용 검증 event가 prod 조건의 신규 issue 알림을 한 번 발생시키는지 확인한다.
5. Grafana Discord contact point의 test notification이 `#alerts-grafana-prod`에 도착하는지 확인한다.
6. 운영 rule을 복제한 단기 test rule로 firing과 Resolved 메시지를 확인한다.
7. AI logging test에서 `WARNING`, `ERROR` record가 각각 `level=WARNING`, `level=ERROR` 필드를 포함하는지 확인한다.
8. Grafana LogQL 검증에서 `Value error`가 포함된 `level=WARNING` 로그는 에러 패널에서 제외되고 실제 `level=ERROR` 로그는 포함되는지 확인한다.
9. Terraform plan에서 prod ALB log bucket, ALB attribute, Web ACL, association만 추가되고 WAF action이 모두 `Count`인지 확인한다.
10. apply 뒤 S3에 실제 ALB access log object가 생성되고 WAF sampled request·Count metric이 조회되는지 확인한다.
11. 두 Discord 채널과 Grafana 로그 조건에서 develop이 제외되고, develop ALB에 WAF와 access log가 추가되지 않았는지 확인한다.

test event와 test rule은 제목에 `[TEST]`를 포함해 실제 장애와 구분한다.

## 성공 기준

- prod Sentry 신규·회귀·반복 급증 알림만 `#alerts-sentry-prod`에 전달된다.
- prod BE·AI 5xx 장애와 복구 알림만 `#alerts-grafana-prod`에 전달된다.
- develop event와 지표는 두 Discord 채널의 조건에서 제외된다.
- Discord webhook URL과 credential이 저장소와 Terraform state에 남지 않는다.
- 인증되지 않은 request와 prod가 아닌 payload는 relay에서 차단된다.
- test notification, firing, resolved 경로의 실제 Discord 수신 증거가 기록된다.
- Sentry ingress는 cold 상태에서도 1초 안에 2xx를 반환하고 delivery 실패는 비동기로 재시도된다.
- AI `WARNING` 로그 본문의 `Value error`가 Grafana 에러 로그로 오분류되지 않는다.
- 실제 AI `ERROR`, `CRITICAL` 로그는 AI와 Overview 에러 패널에 표시된다.
- prod ALB access log가 전용 비공개 S3 bucket에 저장되고 30일 뒤 만료된다.
- prod WAF의 관리형 규칙과 rate rule은 모두 `Count`이며 정상 request를 차단하지 않는다.
- 7일 관찰 후 source IP·path·User-Agent·요청률을 근거로 `Block` 여부를 별도 결정할 수 있다.

## 참고 문서

- [Sentry Discord integration](https://docs.sentry.io/api/integrations/get-integration-provider-information/)
- [Sentry custom integration update API](https://docs.sentry.io/api/integration/update-an-existing-custom-integration/)
- [Sentry App webhook timeout defaults](https://github.com/getsentry/sentry/blob/master/src/sentry/options/defaults.py#L2501-L2515)
- [AWS API Gateway 비동기 Lambda 통합](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-integration-async.html)
- [Application Load Balancer access logs](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-access-logs.html)
- [AWS WAF rule action](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-action.html)
- [AWS WAF rate-based rule](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-statement-type-rate-based.html)
- [Grafana Discord contact point](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/configure-discord/)
- [Grafana alert rule evaluation](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/)
- [Grafana No Data and Error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/nodata-and-error-states/)
