# Push 알림 운영 절차

## 운영 범위

Push 알림은 환경별 Push 전용 SQS Standard Queue를 기존 API ECS Service의 Consumer가 처리하는 구조다. 별도 Push Worker ECS Service, Task Definition, ECR repository, log group은 만들지 않는다. 기존 AI jobs Queue와 AI Worker도 이 흐름에 참여하지 않는다.

| 환경 | 이름 접두사 | Scheduler 초기 상태 | 기본 일정 |
| --- | --- | --- | --- |
| dev | `develop-landit` | `DISABLED` | `cron(0 20 * * ? *)`, `Asia/Seoul` |
| prod | `prod-landit` | `DISABLED` | `cron(0 20 * * ? *)`, `Asia/Seoul` |

각 환경에는 main queue `${prefix}-push-notifications`, DLQ `${prefix}-push-notifications-dlq`, `${prefix}-review-reminder` Scheduler, backlog와 DLQ CloudWatch Alarm이 있다. main queue visibility timeout은 300초, retention은 4일, redrive `maxReceiveCount`는 3이다. DLQ retention은 14일이다.

API Task Role만 Push main queue에 `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility`, `GetQueueAttributes`, `SendMessage` 권한을 가진다. API container는 `SQS_PUSH_NOTIFICATIONS_QUEUE_URL`과 `LANDIT_NOTIFICATION_CONSUMER_ENABLED=true`를 받는다.

## Scheduler 메시지 계약

Scheduler는 main queue에 아래 필드를 가진 `REVIEW_REMINDER_BATCH` 메시지를 발행한다.

| 필드 | 값 | Consumer 규칙 |
| --- | --- | --- |
| `version` | `1` | 현재 계약 버전이다. |
| `messageId` | Scheduler execution ID | UUID로 가정하지 않고 문자열로 처리한다. |
| `messageType` | `REVIEW_REMINDER_BATCH` | 복습 리마인더 배치 처리다. |
| `occurredAt` | Scheduler scheduled time | BE가 `Asia/Seoul`로 변환해 `reviewDate`를 계산한다. |
| `payload` | 빈 객체 | Scheduler가 동적 `reviewDate`를 넣지 않는다. |

API가 발행하는 `PUSH_RECEIPT_CHECK`도 같은 main queue를 사용하며 요청별 `DelaySeconds=900`을 지정한다. Standard Queue의 중복 전달과 순서 변경을 전제로 두 메시지 유형을 모두 멱등 처리한다. 처리 시간이 300초를 넘으면 BE가 visibility를 연장하거나 배치 크기를 줄여야 한다.

## 배포와 활성화 순서

1. dev와 prod plan에서 LAN-184 허용 범위를 먼저 감사한다. API Task Definition의 `delete,create` 새 revision과 API ECS Service의 in-place `update`는 허용한다.
2. ECS Service delete 또는 replace, Worker IAM·Task Definition·Service 변경, 기존 jobs Queue·DLQ 변경이 있으면 진행하지 않는다.
3. prod plan에 현재 포함된 ALB access-log Athena·Glue 4개 create는 LAN-184 범위 밖이므로 분리 또는 정합화 전에는 apply를 요청하지 않는다.
4. 사용자 승인 뒤 dev와 prod에 Queue, IAM, API 환경 변수, 비활성 Scheduler, CloudWatch Alarm을 apply한다. Scheduler는 이 단계에서 활성화하지 않는다.
5. Push Consumer가 포함된 BE를 dev에 배포한다.
6. dev main queue의 수동 메시지, `PUSH_RECEIPT_CHECK` 900초 지연, 멱등성, DLQ 이동을 검증한다.
7. dev Scheduler 활성화 plan을 별도로 감사하고 승인·apply해 예약 실행 E2E를 검증한다.
8. dev E2E 성공 뒤 prod Scheduler 활성화 plan을 별도로 감사하고 승인·apply한다.

Scheduler 활성화는 기본값을 바꾸지 않고 해당 환경의 별도 plan으로만 수행한다.

```bash
AWS_PROFILE=landit terraform -chdir=environments/dev plan \
  -var='review_reminder_schedule_enabled=true' \
  -out=/tmp/lan184-dev-scheduler-enable.tfplan
AWS_PROFILE=landit terraform -chdir=environments/prod plan \
  -var='review_reminder_schedule_enabled=true' \
  -out=/tmp/lan184-prod-scheduler-enable.tfplan
```

각 saved plan을 감사하고 사용자 승인을 받은 뒤에만 같은 plan 파일을 apply한다.

## Apply 후 live 검증

아래 명령은 해당 환경 apply와 BE 배포가 끝난 뒤 실행한다. `LAN184_ROOT`는 `environments/dev` 또는 `environments/prod`이고, `LAN184_PREFIX`는 각각 `develop-landit` 또는 `prod-landit`이다.

```bash
LAN184_ROOT=environments/dev
LAN184_PREFIX=develop-landit
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws sqs get-queue-attributes \
  --queue-url "$(terraform -chdir=$LAN184_ROOT output -raw push_notifications_queue_url)" \
  --attribute-names QueueArn VisibilityTimeout MessageRetentionPeriod RedrivePolicy ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws sqs get-queue-attributes \
  --queue-url "$(terraform -chdir=$LAN184_ROOT output -raw push_notifications_dlq_url)" \
  --attribute-names QueueArn MessageRetentionPeriod ApproximateNumberOfMessages
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws ecs describe-task-definition \
  --task-definition "$LAN184_PREFIX-api" \
  --query 'taskDefinition.containerDefinitions[?name==`api`].environment[?name==`SQS_PUSH_NOTIFICATIONS_QUEUE_URL` || name==`LANDIT_NOTIFICATION_CONSUMER_ENABLED`]' \
  --output json
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws scheduler get-schedule \
  --name "$LAN184_PREFIX-review-reminder" \
  --query '{State:State,ScheduleExpression:ScheduleExpression,Timezone:ScheduleExpressionTimezone,TargetArn:Target.Arn}' \
  --output json
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws cloudwatch describe-alarms \
  --alarm-names "$LAN184_PREFIX-push-notifications-backlog" "$LAN184_PREFIX-push-notifications-dlq" \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Metric:MetricName,Threshold:Threshold,Period:Period,AlarmActions:AlarmActions,OKActions:OKActions,InsufficientDataActions:InsufficientDataActions}' \
  --output table
```

수동 메시지 검증은 BE 운영 절차에 따라 수행한다. Queue attribute와 Alarm 상태만 조회하고, 운영 문서·터미널 기록·로그에 메시지 본문을 남기지 않는다.

## 민감 데이터와 DLQ 안전 수칙

- Push token, 사용자 식별자, 메시지 본문, DLQ message body를 문서, issue, 로그, 배포 출력에 기록하지 않는다.
- DLQ 원인 분석은 message count, receive count, timestamp, 오류 분류처럼 본문이 아닌 메타데이터로 시작한다.
- 반드시 본문 확인이 필요한 경우에는 승인된 제한된 접근 경로에서 최소 인원만 확인하고, 값을 복사하거나 공유 채널에 붙여 넣지 않는다.
- Queue URL과 Scheduler ARN은 secret이 아니지만, credential이나 SSM secret과 함께 출력하거나 기록하지 않는다.
- Alarm은 초기에는 CloudWatch 상태만 생성하며 SNS나 Discord 같은 외부 action은 연결하지 않는다.
