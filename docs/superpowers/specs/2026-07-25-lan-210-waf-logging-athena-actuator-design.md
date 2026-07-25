# LAN-210 WAF logging, Athena parser, Actuator 최소 노출 설계

## 목적

prod WAF의 `ip-rate-limit` Block 전환 이후 요청별 매칭 규칙과 차단 결과를 보존하고, 민감 요청 정보를 로그에서 제거한다. 기존 ALB access log를 Athena에서 정상 파싱하며, prod BE는 ALB health check에 필요한 Actuator endpoint만 외부에 남긴다.

## 현재 상태와 확인된 원인

- prod WAF는 Common Rule Set과 Amazon IP Reputation List를 `Count`로 유지하고, `ip-rate-limit`은 IP별 5분 2,000회 기준 `Block`으로 적용돼 있다.
- prod WAF의 logging configuration은 현재 0건이다.
- 2026-07-25 ALB access log에 대한 Athena 집계는 전체 1,015행을 찾았지만 `type`과 `client_ip`가 파싱된 행은 각각 0건이었다.
- 실제 최신 ALB 로그 10행은 34개 원본 필드를 포함한다.
- 현재 Glue table은 34개 컬럼을 정의하지만 RegexSerDe regex는 35개 capture group을 만든다. RegexSerDe는 capture group과 table column 수가 다르면 정상 역직렬화하지 못한다.
- 최신 ALB 로그에는 `transformed_host`, `transformed_uri`, `request_transform_status`가 포함된다. 현재 table은 이 필드를 별도 컬럼으로 정의하지 않고 나머지 전체를 추가 capture group 하나로 처리한다.
- prod BE는 `health,info`를 Actuator web endpoint로 노출하고 discovery endpoint도 활성화한다. Grafana는 이 HTTP endpoint를 scrape하지 않고 Micrometer OTLP exporter가 30초마다 Grafana Cloud로 metric을 직접 전송한다.

## 결정

### WAF 로그 저장

prod에서만 이름이 `aws-waf-logs-`로 시작하는 전용 S3 bucket을 생성한다. bucket은 현재 ALB access log와 같은 AWS account와 region에 두고 아래 정책을 적용한다.

- S3 public access block 네 항목을 모두 활성화한다.
- SSE-S3 server-side encryption을 사용한다.
- versioning은 사용하지 않는다.
- 모든 WAF log object와 Athena query result를 30일 뒤 만료한다.
- `delivery.logs.amazonaws.com`만 현재 account와 region 조건으로 log object를 작성할 수 있게 한다.
- WAF logging configuration은 S3 bucket policy 이후 생성한다.

WAF logging filter는 기본 동작을 `DROP`으로 두고 `BLOCK`과 `COUNT` action만 `KEEP`한다. pure `ALLOW` 요청은 저장하지 않는다. 이 범위면 rate 차단 결과와 두 managed rule의 Count 요청을 모두 분석하면서 저장 비용과 정상 요청 정보 수집을 줄일 수 있다.

### 민감 정보 제거

WAF logging configuration의 `redacted_fields`에서 다음 요청 정보를 제거한다.

- `Authorization` header.
- `Cookie` header.
- `X-Api-Key` header.
- 전체 query string.

client IP, URI path, HTTP method, User-Agent는 보안 분석에 필요하므로 유지한다. 로그 검증에서는 redacted field의 원문 값을 출력하지 않고 header name과 `REDACTED` 상태만 확인한다.

### WAF 로그 Athena 분석

기존 prod ALB Glue database와 Athena workgroup을 재사용하고 `waf_logs` table을 추가한다. S3의 WAF JSON log를 OpenX JSON SerDe와 시간 partition projection으로 조회한다.

table은 아래 분석에 필요한 필드만 명시한다.

- timestamp, web ACL ARN, terminating rule ID와 type, action.
- non-terminating matching rules와 rule group list.
- client IP, country, URI, method, headers, request ID.
- labels, rate-based rule list, JA3·JA4 fingerprint.

저장 query는 최근 Block·Count 요청을 KST 시각, action, terminating rule, client IP, method, URI, User-Agent 순서로 조회한다. 두 번째 query는 5분 구간과 client IP별 요청량을 집계한다.

### ALB Glue parser 수정

기존 34개 table column 뒤에 아래 세 컬럼을 추가한다.

- `transformed_host`.
- `transformed_uri`.
- `request_transform_status`.

regex는 이 세 필드를 각각 capture하고, AWS가 이후 추가하는 후행 필드는 non-capturing group `(?: .*)?`로 허용한다. 결과는 37개 table column과 37개 capture group이 정확히 일치한다.

parser 계약 검사는 synthetic ALB log 한 줄을 사용해 다음을 확인한다.

- regex capture group 수와 Glue column 수가 같다.
- 최신 transform field가 있는 행을 파싱한다.
- future trailing field가 있어도 기존 컬럼을 유지한다.
- named query에 client IP, URL, 상태 코드, User-Agent가 포함된다.
- IP별 5분 집계 query가 포함된다.

실제 apply 뒤에는 같은 2026-07-25 partition에서 `count(*)`, `count(type)`, `count(client_ip)`가 모두 같은 값인지 확인한다.

### prod Actuator 최소 노출

BE prod 프로필에서 Actuator web exposure를 `health`로 제한하고 discovery endpoint를 비활성화한다.

- `/actuator/health`는 ALB target health check를 위해 200을 유지한다.
- `/actuator`는 404를 반환한다.
- `/actuator/info`는 404를 반환한다.
- local과 develop의 기존 Actuator 설정은 바꾸지 않는다.
- Micrometer OTLP exporter와 Grafana dashboard query는 변경하지 않는다.

BE의 prod integration test에서 세 endpoint 응답을 고정한다. Swagger와 OpenAPI 차단 테스트는 기존 LAN-210 PR 범위 그대로 유지한다.

## 적용과 검증 순서

1. IaC 계약 검사를 먼저 실패시키고 WAF logging, redaction, parser, query 요구를 고정한다.
2. Terraform을 최소 변경해 계약 검사를 통과시킨다.
3. BE prod integration test에 Actuator 기대 응답을 먼저 추가하고 실패를 확인한다.
4. prod 설정을 최소 변경해 테스트를 통과시킨다.
5. IaC에서 `terraform fmt -recursive`, dev·prod `terraform validate`, 계약 검사, `git diff --check`를 실행한다.
6. BE에서 focused integration test와 `./gradlew check --no-daemon`을 실행한다.
7. prod Terraform saved plan에서 WAF log bucket·policy·logging configuration, Glue table·named query와 ALB Glue table in-place 수정 외 변경이나 삭제가 없는지 확인한다.
8. 사용자 승인 뒤에만 saved plan을 apply한다.
9. 실제 WAF log object, redaction, Athena WAF query, ALB parser query를 확인한다.
10. BE·AI PR이 병합된 뒤 별도 승인된 운영 배포로 문서와 Actuator 외부 응답을 확인한다.

## 실패와 롤백

- WAF logging 생성이 실패하면 managed rule과 rate rule action은 변경하지 않고 logging resource만 수정한다.
- WAF log에 민감 값이 확인되면 logging configuration을 제거해 수집을 중단하고 redaction을 수정한 새 plan을 검토한다.
- Athena parser 수정이 기존 query를 깨뜨리면 Glue table의 regex와 transform column 변경만 이전 형태로 되돌린다. ALB 원본 S3 object는 변경하지 않는다.
- Actuator 변경 뒤 ALB health check가 실패하면 prod exposure에서 `health` 설정을 확인하고 BE 변경만 되돌린다.
- `ip-rate-limit`으로 정상 사용자 영향이 확인되면 기존 운영 문서대로 action을 `Count`로 복귀한 saved plan을 승인 후 적용한다.

## 범위 밖

- Common Rule Set과 Amazon IP Reputation List의 Block 전환.
- WAF 로그의 Grafana 실시간 dashboard와 alert.
- 장기 보관을 위한 Glacier 전환.
- local·develop Actuator endpoint 정책 변경.
- 인증된 로그인·학습·대화 E2E용 테스트 계정 생성.

## 완료 조건

- Terraform plan에 의도한 WAF logging·S3·Glue·Athena 변경만 있고 삭제가 없다.
- WAF가 `BLOCK`과 `COUNT` 요청을 S3에 저장한다.
- Authorization, Cookie, X-Api-Key와 query string이 WAF 로그에서 redaction된다.
- Athena에서 WAF action과 매칭 규칙을 요청별로 조회한다.
- Athena에서 ALB client IP, 경로, 상태 코드, User-Agent와 IP별 5분 요청량을 조회한다.
- prod BE에서 `/actuator/health`만 유지하고 `/actuator`, `/actuator/info`는 404를 반환한다.
- 기존 BE·AI metric OTLP 전송과 ALB health check가 정상이다.

## 참고

- [AWS WAF S3 logging](https://docs.aws.amazon.com/waf/latest/developerguide/logging-s3.html).
- [AWS WAF Athena table](https://docs.aws.amazon.com/athena/latest/ug/create-waf-table-partition-projection.html).
- [AWS ALB access log fields](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-access-logs.html).
- [Athena RegexSerDe](https://docs.aws.amazon.com/athena/latest/ug/regex-serde.html).
