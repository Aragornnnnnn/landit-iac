# LAN-184 Push 알림 인프라 실행 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

## 목표

EventBridge Scheduler가 Push 전용 SQS Standard Queue에 복습 리마인더 메시지를 발행하고, 기존 API ECS Service 내부 Consumer가 처리할 수 있는 환경별 인프라를 구성한다.

별도 Push Worker ECS Service, Fargate Task, ECR repository, log group은 만들지 않는다. 기존 AI jobs Queue와 AI Worker는 변경하지 않는다.

## 확정 계약

### 환경과 활성화

- dev와 prod에 Push main queue, DLQ, API IAM·환경 변수, Scheduler, CloudWatch Alarm을 모두 구성한다.
- Scheduler timezone은 `Asia/Seoul`이다.
- 기본 cron은 매일 20시인 `cron(0 20 * * ? *)`이다.
- cron은 환경 root variable로 변경할 수 있게 한다.
- BE Consumer 배포 전이므로 dev와 prod Scheduler의 최초 state는 모두 `DISABLED`다.
- dev BE 배포 후 dev Scheduler를 별도 plan으로 활성화한다.
- prod Scheduler는 dev E2E 검증 뒤 별도 plan으로 활성화한다.

### Queue와 DLQ

- main queue 이름은 `${local.name_prefix}-push-notifications`다.
- DLQ 이름은 `${local.name_prefix}-push-notifications-dlq`다.
- Queue 유형은 Standard다.
- visibility timeout은 `300`초다.
- main queue retention은 명시적으로 4일인 `345600`초를 사용한다.
- DLQ retention은 14일인 `1209600`초다.
- redrive `maxReceiveCount`는 `3`이다.
- 기존 `${local.name_prefix}-jobs` Queue와 리소스·권한을 공유하지 않는다.

### API IAM과 환경 변수

API Task Role에는 Push main queue ARN에 대해서만 다음 권한을 추가한다.

- `sqs:ReceiveMessage`.
- `sqs:DeleteMessage`.
- `sqs:ChangeMessageVisibility`.
- `sqs:GetQueueAttributes`.
- `sqs:SendMessage`.

`sqs:GetQueueUrl`과 DLQ 권한은 추가하지 않는다.

API container에는 다음 일반 환경 변수를 추가한다.

- `SQS_PUSH_NOTIFICATIONS_QUEUE_URL=<Push main queue URL>`.
- `LANDIT_NOTIFICATION_CONSUMER_ENABLED=true`.

AI Worker Task Role과 Worker container에는 Push 관련 권한이나 환경 변수를 추가하지 않는다.

### Scheduler

환경별 Scheduler execution role을 만들고 `scheduler.amazonaws.com`만 assume할 수 있게 한다.

- execution role은 해당 환경의 Push main queue에 `sqs:SendMessage`만 허용한다.
- flexible time window는 `OFF`다.
- 초기 state는 `DISABLED`다.
- target은 해당 환경의 Push main queue ARN이다.
- Scheduler 자체 DLQ와 별도 retry 설정은 이번 범위에서 추가하지 않는다.

target input은 version 1, Scheduler execution ID `messageId`, `REVIEW_REMINDER_BATCH`, Scheduler scheduled time `occurredAt`, 빈 `payload`로 구성한다. 상세 운영 계약은 `docs/push-notifications.md`에 둔다.

API가 발행하는 `PUSH_RECEIPT_CHECK` 메시지는 같은 main queue를 사용하고 요청별 `DelaySeconds=900`을 지정한다. 이 동작과 Consumer 동시성 `2`는 BE 책임이다.

### CloudWatch Alarm

외부 SNS action은 연결하지 않고 CloudWatch Alarm 상태만 만든다.

- main queue backlog alarm은 `AWS/SQS`의 `ApproximateAgeOfOldestMessage`를 사용한다.
- main queue 조건은 `Maximum >= 300`, period `300`, evaluation periods `1`이다.
- DLQ alarm은 `AWS/SQS`의 `ApproximateNumberOfMessagesVisible`을 사용한다.
- DLQ 조건은 `Maximum >= 1`, period `300`, evaluation periods `1`이다.
- 두 alarm 모두 `treat_missing_data = "notBreaching"`을 사용한다.
- `alarm_actions`, `ok_actions`, `insufficient_data_actions`는 설정하지 않는다.

## 파일별 변경

### 새 파일

- `modules/app-platform/push-notifications.tf`.
  - Push main queue와 DLQ.
  - Scheduler assume role, execution policy, Scheduler.
  - main queue backlog alarm과 DLQ visible alarm.
- `scripts/test-push-notification-infra-contract.sh`.
  - Terraform source를 대상으로 확정 계약을 정적으로 검증한다.
- `docs/push-notifications.md`.
  - 메시지 계약, 환경별 리소스, 경보, 배포·활성화·검증 순서를 기록한다.

### 수정 파일

- `modules/app-platform/main.tf`.
  - API Task Role에 Push main queue 권한을 추가한다.
  - API container에 Push Queue URL과 Consumer enabled 값을 추가한다.
- `modules/app-platform/variables.tf`.
  - `review_reminder_schedule_expression`.
  - `review_reminder_schedule_enabled`.
  - Queue와 Alarm 값은 확정 상수이므로 불필요한 variable로 만들지 않는다.
- `modules/app-platform/outputs.tf`.
  - Push main queue URL.
  - Push DLQ URL.
  - Review reminder Scheduler ARN.
- `environments/dev/main.tf`, `environments/prod/main.tf`.
  - 환경별 Scheduler expression과 enabled 값을 module에 전달한다.
- `environments/dev/variables.tf`, `environments/prod/variables.tf`.
  - expression 기본값은 `cron(0 20 * * ? *)`다.
  - enabled 기본값은 `false`다.
- `environments/dev/outputs.tf`, `environments/prod/outputs.tf`.
  - module의 Push queue와 Scheduler 출력을 전달한다.
- `checklist.md`.
  - LAN-184 구현과 검증 상태만 짧게 기록한다.
- `context-notes.md`.
  - 확정 값, plan 결과, apply 보류 상태만 기록한다.

## Task 1. 정적 계약 테스트와 app-platform 구현

**Files**

- Create: `scripts/test-push-notification-infra-contract.sh`.
- Create: `modules/app-platform/push-notifications.tf`.
- Modify: `modules/app-platform/main.tf`.
- Modify: `modules/app-platform/variables.tf`.
- Modify: `modules/app-platform/outputs.tf`.

**작업**

- [ ] 정적 계약 테스트를 먼저 작성하고 Push 리소스 부재로 실패하는지 확인한다.
- [ ] Queue·DLQ 이름, timeout, retention, redrive 값을 검사한다.
- [ ] API Task Role의 정확한 다섯 action과 main queue ARN 범위를 검사한다.
- [ ] API container의 두 환경 변수를 검사한다.
- [ ] Worker에 Push queue 연결이 없는지 검사한다.
- [ ] Scheduler role, timezone, cron input, disabled state를 검사한다.
- [ ] 두 CloudWatch Alarm metric과 임계값, action 부재를 검사한다.
- [ ] 최소 Terraform 구현으로 정적 계약 테스트를 통과시킨다.

**검증**

```bash
bash scripts/test-push-notification-infra-contract.sh
terraform fmt -recursive -check
```

**커밋**

```bash
git commit -m "feat: Push 알림 Queue와 Scheduler를 구성한다"
```

## Task 2. dev·prod root 연결과 Terraform 검증

**Files**

- Modify: `environments/dev/main.tf`.
- Modify: `environments/dev/variables.tf`.
- Modify: `environments/dev/outputs.tf`.
- Modify: `environments/prod/main.tf`.
- Modify: `environments/prod/variables.tf`.
- Modify: `environments/prod/outputs.tf`.

**작업**

- [ ] dev와 prod에 같은 기본 cron과 disabled 기본값을 정의한다.
- [ ] 두 root에서 module input과 output을 연결한다.
- [ ] `terraform fmt -recursive`를 실행한다.
- [ ] 정적 계약 테스트와 dev·prod validate를 통과시킨다.
- [ ] dev·prod saved plan을 생성한다.
- [ ] plan JSON에서 허용된 API Task Definition 새 revision과 API ECS Service in-place update, 금지된 Worker·jobs Queue·DLQ 변경 여부를 확인한다.
- [ ] prod Athena·Glue 4개 create가 LAN-184 범위 밖 apply blocker인지 기록한다.
- [ ] apply는 실행하지 않는다.

**검증**

```bash
terraform fmt -recursive
terraform fmt -recursive -check
bash scripts/test-push-notification-infra-contract.sh
AWS_PROFILE=landit terraform -chdir=environments/dev validate
AWS_PROFILE=landit terraform -chdir=environments/prod validate
AWS_PROFILE=landit terraform -chdir=environments/dev plan -out=/tmp/lan184-dev-push.tfplan
AWS_PROFILE=landit terraform -chdir=environments/prod plan -out=/tmp/lan184-prod-push.tfplan
terraform -chdir=environments/dev show -json /tmp/lan184-dev-push.tfplan
terraform -chdir=environments/prod show -json /tmp/lan184-prod-push.tfplan
```

**plan 허용 범위**

- Push main queue와 DLQ 생성.
- Scheduler role·policy·비활성 Scheduler 생성.
- 두 CloudWatch Alarm 생성.
- API Task Role inline policy 갱신.
- 두 환경 API Task Definition 새 revision.
- API ECS Service의 새 task definition 참조를 위한 in-place update.
- module·root output 갱신.

**plan 금지 범위**

- ECS Service delete 또는 replace action.
- 기존 AI jobs Queue와 jobs DLQ 변경.
- AI Worker IAM, Task Definition, ECS Service 변경.
- 별도 Push Worker 관련 리소스 생성.

API Task Definition의 `delete,create`는 새 revision을 위한 허용된 action이고 API ECS Service의 `update`는 허용된 in-place 갱신이다. prod plan의 ALB access-log Athena·Glue 4개 create는 LAN-184 범위 밖이므로 apply blocker로 기록한다.

**커밋**

```bash
git commit -m "feat: dev와 prod에 Push 알림 인프라를 연결한다"
```

## Task 3. 운영 문서와 최종 기록 정리

**Files**

- Create: `docs/push-notifications.md`.
- Modify: `checklist.md`.
- Modify: `context-notes.md`.
- Modify: `docs/superpowers/plans/2026-07-24-lan-184-push-notification-infrastructure.md`.

**작업**

- [ ] 환경별 리소스와 Scheduler 메시지 계약을 운영 문서에 기록한다.
- [ ] disabled 상태로 apply한 뒤 BE를 먼저 배포하는 순서를 기록한다.
- [ ] dev E2E 뒤 dev 활성화, 이후 prod 활성화 순서를 기록한다.
- [ ] Queue·DLQ·Task Definition·Scheduler·Alarm의 live 검증 명령을 기록한다.
- [ ] DLQ 메시지 본문과 Push token을 로그나 문서에 노출하지 않는 주의사항을 기록한다.
- [ ] checklist에는 완료 상태와 apply 보류만 남긴다.
- [ ] context-notes에는 확정 값과 plan 결과만 남긴다.
- [ ] 이 실행 계획을 200~300줄 범위로 유지한다.

**검증**

```bash
terraform fmt -recursive -check
bash scripts/test-push-notification-infra-contract.sh
git diff --check
git status --short
```

**커밋**

```bash
git commit -m "docs: Push 알림 인프라 운영 절차를 정리한다"
```

## 배포 순서

1. dev·prod plan에서 허용 범위와 삭제·교체 부재를 확인한다.
2. 사용자 승인 뒤 Queue, IAM, API 환경 변수, 비활성 Scheduler, Alarm을 apply한다.
3. Push Consumer가 포함된 BE를 dev에 배포한다.
4. dev main queue 수동 메시지로 발송, Receipt 900초 지연, 멱등성, DLQ 이동을 확인한다.
5. dev Scheduler 활성화 plan을 별도 검토하고 apply해 예약 실행 E2E를 확인한다.
6. dev E2E 성공 뒤 prod Scheduler 활성화 plan을 별도 검토하고 apply한다.

## 현재 보류 사항

- dev와 prod Scheduler 활성화.
- SNS, Discord 등 CloudWatch Alarm 외부 전달.
- Scheduler 자체 전송 실패용 별도 DLQ 또는 `TargetErrorCount` 경보.

2026-07-24 사용자 승인 후 dev와 prod saved plan을 적용했다. 두 환경 post-apply plan은 `No changes`이고 Scheduler는 모두 `DISABLED`다.
