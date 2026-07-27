# LAN-184 Push 알림 인프라 제거 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 앱 로컬 알림 전환에 따라 LAN-184로 추가한 서버 Push 알림 인프라와 API 연결을 dev·prod에서 제거한다.

**Architecture:** Push 전용 SQS·DLQ와 EventBridge Scheduler를 삭제하고 기존 API ECS Service에서 Push Consumer 권한과 환경변수를 제거한다. 기존 AI jobs Queue·DLQ, AI Worker, ECS Service, WAF·Athena·Glue와 관측성 리소스는 유지한다.

**Tech Stack:** Terraform, AWS SQS, EventBridge Scheduler, IAM, ECS, CloudWatch.

## Global Constraints

- 작업 기준은 `origin/main`의 `00aa5f2`다.
- 이슈와 브랜치는 `LAN-184`, `feat/LAN-184`를 사용한다.
- dev·prod Push main Queue와 DLQ는 visible·in-flight·delayed 메시지가 모두 0개다.
- dev·prod Review reminder Scheduler는 모두 `DISABLED`다.
- 실제 AWS apply는 사용자 별도 승인 전까지 실행하지 않는다.
- 기존 AI jobs Queue·DLQ, AI Worker, ECS Service, WAF·Athena·Glue와 관측성 리소스를 변경하지 않는다.
- API ECS Service 삭제·교체는 금지한다. 새 API Task Definition revision과 Service의 in-place 갱신만 허용한다.
- `LANDIT_NOTIFICATION_TEST_API_ENABLED`는 Push 수동 테스트 전용이므로 함께 제거한다.
- Push 관련 운영 문서와 정적 계약 테스트는 삭제하고, 작업 기록에는 제거 결정과 plan 결과만 남긴다.
- Wiki는 실제 AWS 삭제 적용 뒤 현재 상태에 맞춰 별도로 동기화한다.

---

### Task 1: Push 인프라와 API 연결 제거

**Files:**

- Delete: `modules/app-platform/push-notifications.tf`.
- Modify: `modules/app-platform/main.tf`.
- Modify: `modules/app-platform/variables.tf`.
- Modify: `modules/app-platform/outputs.tf`.
- Modify: `environments/dev/main.tf`.
- Modify: `environments/dev/variables.tf`.
- Modify: `environments/dev/outputs.tf`.
- Modify: `environments/prod/main.tf`.
- Modify: `environments/prod/variables.tf`.
- Modify: `environments/prod/outputs.tf`.
- Delete: `scripts/test-push-notification-infra-contract.sh`.
- Delete: `scripts/test-push-notification-scheduler-plan-contract.sh`.
- Delete: `docs/push-notifications.md`.
- Modify: `checklist.md`.
- Modify: `context-notes.md`.
- Modify: `docs/superpowers/plans/2026-07-24-lan-184-push-notification-infrastructure.md`.

**Interfaces:**

- Consumes: dev·prod Terraform state의 LAN-184 Push 리소스와 현재 API Task Definition.
- Produces: Push 전용 AWS 리소스 삭제, API Push IAM·환경변수 제거, Push root 변수·output 제거만 포함하는 dev·prod plan.

- [x] **Step 1: RED plan 계약을 확인한다.**

현재 코드로 dev plan을 생성한 뒤 `/tmp/lan184-push-removal-plan-contract.sh`를 실행한다.

```bash
AWS_PROFILE=landit terraform -chdir=environments/dev plan \
  -input=false \
  -out=/tmp/lan184-push-removal-red-dev.tfplan
bash /tmp/lan184-push-removal-plan-contract.sh \
  /tmp/lan184-push-removal-red-dev.tfplan \
  environments/dev
```

Expected: `missing required Push deletion`으로 실패한다.

- [x] **Step 2: app-platform의 Push 리소스와 API 연결을 제거한다.**

`modules/app-platform/push-notifications.tf`를 삭제한다. `main.tf`의 API Task Role에서 Push Queue 전용 statement를 제거하고 API container에서 다음 환경변수를 제거한다.

```text
SQS_PUSH_NOTIFICATIONS_QUEUE_URL
LANDIT_NOTIFICATION_CONSUMER_ENABLED
LANDIT_NOTIFICATION_TEST_API_ENABLED
```

`variables.tf`에서 다음 변수를 제거한다.

```text
review_reminder_schedule_expression
review_reminder_schedule_enabled
notification_test_api_enabled
```

`outputs.tf`에서 다음 output을 제거한다.

```text
push_notifications_queue_url
push_notifications_dlq_url
review_reminder_scheduler_arn
```

- [x] **Step 3: dev·prod root 연결을 제거한다.**

두 root의 module input에서 `review_reminder_schedule_expression`, `review_reminder_schedule_enabled`를 제거한다. dev에서만 있던 `notification_test_api_enabled = true`도 제거한다. 두 root의 변수와 Push 관련 output을 제거한다.

- [x] **Step 4: Push 전용 테스트와 운영 문서를 제거한다.**

다음 파일을 삭제한다.

```text
scripts/test-push-notification-infra-contract.sh
scripts/test-push-notification-scheduler-plan-contract.sh
docs/push-notifications.md
```

기존 구현 계획 상단에 앱 로컬 알림 전환으로 폐기됐다는 상태를 기록한다. `checklist.md`와 `context-notes.md`에는 제거 결정, live 사전 확인, 검증 상태와 apply 보류만 남긴다.

- [x] **Step 5: Terraform 형식과 정적 참조를 검증한다.**

```bash
terraform fmt -recursive
terraform fmt -recursive -check
rg -n \
  'push_notifications|review_reminder|SQS_PUSH_NOTIFICATIONS|LANDIT_NOTIFICATION_(CONSUMER|TEST_API)|push-notifications' \
  modules environments scripts docs \
  --glob '!docs/superpowers/plans/2026-07-24-lan-184-push-notification-infrastructure.md' \
  --glob '!docs/superpowers/plans/2026-07-28-lan-184-push-infrastructure-removal.md'
```

Expected: Terraform과 실행 문서에서 Push 인프라 참조가 남지 않는다.

- [x] **Step 6: dev·prod validate와 removal plan을 실행한다.**

```bash
AWS_PROFILE=landit terraform -chdir=environments/dev validate
AWS_PROFILE=landit terraform -chdir=environments/prod validate
AWS_PROFILE=landit terraform -chdir=environments/dev plan \
  -input=false \
  -out=/tmp/lan184-push-removal-dev.tfplan
AWS_PROFILE=landit terraform -chdir=environments/prod plan \
  -input=false \
  -out=/tmp/lan184-push-removal-prod.tfplan
bash /tmp/lan184-push-removal-plan-contract.sh \
  /tmp/lan184-push-removal-dev.tfplan \
  environments/dev
bash /tmp/lan184-push-removal-plan-contract.sh \
  /tmp/lan184-push-removal-prod.tfplan \
  environments/prod
```

Expected: 각 환경에서 Push 관리 리소스 7개 삭제, API IAM policy 갱신, API Task Definition 새 revision, API ECS Service in-place 갱신만 계획된다.

- [x] **Step 7: diff와 plan을 검토하고 커밋한다.**

```bash
git diff --check
git status --short
git diff --stat
git commit -m "remove: 서버 Push 알림 인프라를 제거한다"
```

실제 `terraform apply`와 Wiki 게시본 변경은 실행하지 않는다.
