# LAN-210 WAF Logging, Athena Parser, Actuator Implementation Plan

> For agentic workers: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** prod WAF의 Count·Block 요청을 민감 정보 없이 저장하고 Athena ALB parser와 BE Actuator 공개 범위를 완료 기준에 맞게 수정한다.

**Architecture:** IaC module에 prod 전용 WAF S3 logging, WAF JSON Athena table, ALB parser 수정과 named query를 추가한다. BE prod는 Actuator health만 외부에 남기고 discovery와 info endpoint를 비활성화한다.

**Tech Stack:** Terraform AWS provider, WAFv2, S3, Glue, Athena, Spring Boot Actuator, MockMvc, Gradle.

## Global Constraints

- prod apply와 BE·AI 운영 배포는 saved plan 확인 뒤 사용자 승인을 받아야 한다.
- WAF logging은 BLOCK과 COUNT만 저장하며 Authorization, Cookie, X-Api-Key, query string을 redaction한다.
- Common Rule Set과 Amazon IP Reputation List는 Count를 유지한다.
- prod Actuator health는 ALB health check를 위해 200을 유지한다.

---

### Task 1: IaC 계약을 실패하는 검사로 먼저 고정한다.

**Files:**

- Create: scripts/test-waf-logging-athena-contract.sh.
- Modify: scripts/test-athena-alb-contract.sh.
- Modify: checklist.md.
- Modify: context-notes.md.

**Interfaces:**

- Consumes: modules/app-platform/main.tf의 WAF Web ACL과 ALB Glue table.
- Produces: WAF logging·redaction·filter, WAF Glue table, ALB transform parser와 5분 집계 named query 계약.

- [ ] Step 1. WAF logging contract를 추가한다.

  검사에는 WAF logging configuration, default DROP, BLOCK·COUNT KEEP, authorization·cookie·x-api-key header와 query string redaction을 모두 포함한다.

- [ ] Step 2. RED 상태를 확인한다.

  Run: bash scripts/test-waf-logging-athena-contract.sh.

  Expected: WAF logging resource가 없어 실패한다.

- [ ] Step 3. ALB parser contract를 확장한다.

  검사에는 transformed_host, transformed_uri, request_transform_status column, non-capturing future tail, alb_top_client_rate named query를 포함한다.

- [ ] Step 4. RED 상태를 확인한다.

  Run: bash scripts/test-athena-alb-contract.sh.

  Expected: transform column과 5분 집계 query가 없어 실패한다.

- [ ] Step 5. 계약 검사 변경을 커밋한다.

  Run: git add scripts/test-waf-logging-athena-contract.sh scripts/test-athena-alb-contract.sh checklist.md context-notes.md.

  Run: git commit -m "test: LAN-210 WAF logging과 Athena 계약을 추가한다".

### Task 2: WAF S3 logging과 Athena 분석을 구현한다.

**Files:**

- Modify: modules/app-platform/main.tf.
- Modify: modules/app-platform/outputs.tf.
- Modify: docs/observability.md.

**Interfaces:**

- Consumes: waf_count_enabled, local.name_prefix, AWS account ID, 기존 ALB Athena database·workgroup.
- Produces: WAF log S3 bucket·policy·lifecycle, WAF logging configuration, waf_logs table, WAF query, ALB 5분 집계 query.

- [ ] Step 1. private WAF S3 destination을 추가한다.

  Bucket name은 aws-waf-logs-prod-landit-account-id 형식을 사용한다. public access block, SSE-S3, 30일 lifecycle과 delivery.logs.amazonaws.com의 account·region 조건 bucket policy를 함께 추가한다.

- [ ] Step 2. BLOCK·COUNT filter와 redaction을 가진 logging configuration을 추가한다.

  WAF logging destination은 새 bucket ARN이다. logging filter의 default behavior는 DROP이며 BLOCK 또는 COUNT action일 때만 KEEP한다. Authorization, Cookie, X-Api-Key single header와 query string을 redacted fields에 추가한다.

- [ ] Step 3. ALB parser와 Athena named query를 수정한다.

  Glue table에 transformed_host, transformed_uri, request_transform_status를 추가한다. Regex의 future trailing field는 non-capturing으로 만들고 총 37개 capture group과 37개 column을 맞춘다. alb_top_client_rate query는 KST 5분 구간·client IP별 요청량을 내림차순 반환한다.

- [ ] Step 4. WAF JSON table과 query를 추가한다.

  OpenX JSON SerDe와 시간 partition projection을 사용하는 waf_logs table을 기존 Glue database에 추가한다. waf_recent_matches query는 KST 시각, action, terminating rule, client IP, method, URI, User-Agent를 반환한다.

- [ ] Step 5. GREEN 검증을 실행한다.

  Run: bash scripts/test-waf-logging-athena-contract.sh.

  Run: bash scripts/test-athena-alb-contract.sh.

  Run: terraform fmt -recursive.

  Run: AWS_PROFILE=landit terraform -chdir=environments/dev validate.

  Run: AWS_PROFILE=landit terraform -chdir=environments/prod validate.

  Run: git diff --check.

  Expected: 계약 검사, format, validate, diff check가 성공한다.

- [ ] Step 6. IaC 구현을 커밋한다.

  Run: git add modules/app-platform/main.tf modules/app-platform/outputs.tf docs/observability.md.

  Run: git commit -m "feat: LAN-210 WAF logging과 Athena 분석을 추가한다".

### Task 3: BE prod Actuator 공개 범위를 health로 제한한다.

**Files:**

- Modify: /private/tmp/landit-LAN-210.qgpOGN/landit-be/src/main/resources/application-prod.yml.
- Modify: /private/tmp/landit-LAN-210.qgpOGN/landit-be/src/main/java/com/landit/landitbe/config/security/AuthSecurityConfig.java.
- Modify: /private/tmp/landit-LAN-210.qgpOGN/landit-be/src/test/java/com/landit/landitbe/ProductionOpenApiDocsDisabledIntegrationTests.java.

**Interfaces:**

- Consumes: Spring Boot management exposure and discovery properties.
- Produces: prod health 200, Actuator root·info 404 regression contract.

- [ ] Step 1. RED test를 추가한다.

  ProductionOpenApiDocsDisabledIntegrationTests에 actuator root와 info의 404, health의 200 assertion을 추가한다.

- [ ] Step 2. RED 상태를 확인한다.

  Run: ./gradlew test --tests '*ProductionOpenApiDocsDisabledIntegrationTests' --no-daemon.

  Expected: actuator root와 info가 200이라 실패한다.

- [ ] Step 3. prod profile을 수정한다.

  management.endpoints.web.exposure.include은 health만 남긴다. management.endpoints.web.discovery.enabled는 false로 둔다. AuthSecurityConfig public matcher에서는 actuator info를 제거한다.

- [ ] Step 4. GREEN 검증과 커밋을 완료한다.

  Run: ./gradlew test --tests '*ProductionOpenApiDocsDisabledIntegrationTests' --no-daemon.

  Run: ./gradlew check --no-daemon.

  Run: git diff --check origin/develop...HEAD.

  Expected: prod 문서와 불필요 Actuator path는 404, health는 200이며 전체 검증이 성공한다.

  Run: git add src/main/resources/application-prod.yml src/main/java/com/landit/landitbe/config/security/AuthSecurityConfig.java src/test/java/com/landit/landitbe/ProductionOpenApiDocsDisabledIntegrationTests.java.

  Run: git commit -m "fix: prod Actuator 노출을 health로 제한한다".

### Task 4: prod saved plan과 승인 가능한 live 검증을 준비한다.

**Files:**

- Modify: checklist.md.
- Modify: context-notes.md.

**Interfaces:**

- Consumes: Task 2 Terraform changes and Task 3 BE commit.
- Produces: apply 전 정확한 plan 요약과 apply 뒤 WAF·Athena·endpoint 검증 절차.

- [ ] Step 1. prod saved plan을 생성하고 검토한다.

  Run: AWS_PROFILE=landit terraform -chdir=environments/prod plan -out=/tmp/lan210-waf-logging-prod.tfplan.

  Run: terraform -chdir=environments/prod show -no-color /tmp/lan210-waf-logging-prod.tfplan.

  Expected: WAF log S3·policy·lifecycle·logging configuration, Glue·Athena와 ALB table 수정만 포함하며 삭제가 없다.

- [ ] Step 2. apply·배포 승인 뒤 live 상태를 확인한다.

  Run: aws wafv2 list-logging-configurations, aws s3api list-objects-v2, WAF·ALB Athena aggregate query, 운영 endpoint curl.

  Expected: redaction된 WAF log가 저장되고 ALB count(type), count(client_ip), count(*)가 같으며 운영 배포 뒤 health만 200이다.
