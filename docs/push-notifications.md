# Push 알림 운영 절차

## 운영 범위

Push 알림은 환경별 Push 전용 SQS Standard Queue를 기존 BE API 런타임의 Consumer가 처리하는 구조다. develop은 EC2 Compose API, production은 ECS API Service가 소비한다. 별도 Push Worker ECS Service, Task Definition, ECR repository, log group은 만들지 않는다. 기존 AI jobs Queue와 AI Worker도 이 흐름에 참여하지 않는다.

| 환경 | 이름 접두사 | Scheduler 기본 상태 | 기본 일정 |
| --- | --- | --- | --- |
| dev | `develop-landit` | `ENABLED` | `cron(0 20 * * ? *)`, `Asia/Seoul` |
| prod | `prod-landit` | `DISABLED` | `cron(0 20 * * ? *)`, `Asia/Seoul` |

각 환경에는 main queue `${prefix}-push-notifications`, DLQ `${prefix}-push-notifications-dlq`, `${prefix}-review-reminder` Scheduler, backlog와 DLQ CloudWatch Alarm이 있다. main queue visibility timeout은 300초, retention은 4일, redrive `maxReceiveCount`는 3이다. DLQ retention은 14일이다.

production API Task Role과 develop EC2 instance role만 Push main queue에 `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility`, `GetQueueAttributes`, `SendMessage` 권한을 가진다. production ECS API container와 develop EC2의 `api.env`는 `SQS_PUSH_NOTIFICATIONS_QUEUE_URL`과 `LANDIT_NOTIFICATION_CONSUMER_ENABLED=true`를 받는다.

## Scheduler 메시지 계약

Scheduler는 매일 `Asia/Seoul` 20시에 main queue로 `SCHEDULED_NOTIFICATION_BATCH` 한 건을 발행한다. 20시는 배치 시작 시각이며, 실제 발송은 사용자 수와 페이지 처리 시간에 따라 수 분에 걸쳐 진행될 수 있다. Scheduler는 사용자, Push token, 기준 날짜를 계산하지 않는다.

| 필드 | 값 | Consumer 규칙 |
| --- | --- | --- |
| `version` | `1` | 현재 계약 버전이다. |
| `messageId` | Scheduler execution ID | 비어 있지 않은 문자열이다. 실행 시도별 식별자이므로 발송 멱등성의 근거로 쓰지 않는다. |
| `messageType` | `SCHEDULED_NOTIFICATION_BATCH` | BE가 최신 DB 상태로 발송 대상을 계산하는 시작 메시지다. |
| `occurredAt` | Scheduler scheduled time | ISO-8601 UTC 문자열이며 BE가 Java `Instant`로 역직렬화한 뒤 `Asia/Seoul` 날짜를 계산한다. |
| `payload` | 빈 객체 | Scheduler가 동적 `reviewDate`를 넣지 않는다. |

```json
{
  "version": 1,
  "messageId": "<aws.scheduler.execution-id>",
  "messageType": "SCHEDULED_NOTIFICATION_BATCH",
  "occurredAt": "<aws.scheduler.scheduled-time>",
  "payload": {}
}
```

`<aws.scheduler.execution-id>`와 `<aws.scheduler.scheduled-time>`은 EventBridge Scheduler가 target input에서 실제 값으로 치환하는 context attribute다. Terraform `jsonencode`는 꺾쇠 문자를 Unicode escape하므로, Scheduler input은 raw JSON heredoc으로 작성해 context token을 문자 그대로 전달한다. Standard Queue의 중복 전달과 순서 변경은 정상 동작으로 취급한다. BE는 예정 시각의 한국 날짜, 사용자, 기기, 알림 유형을 기준으로 `push_delivery` 멱등성을 보장한다.

BE가 SQS에서 소비하는 메시지 유형은 `SCHEDULED_NOTIFICATION_BATCH`와 `PUSH_RECEIPT_CHECK`뿐이다. `SCHEDULED_NOTIFICATION_BATCH`를 받으면 `occurredAt`을 기준으로 사용자 프로필을 500명씩 Keyset Pagination하여 최신 대상을 계산하고, Expo API에 최대 100건씩 직접 발송한다. `PUSH_SEND` 메시지와 `NOTIFICATION_TARGET_BATCH` 같은 중간 queue는 사용하지 않는다. `PUSH_RECEIPT_CHECK`는 같은 queue를 사용하며 요청별 `DelaySeconds=900`을 지정한다.

## Visibility Timeout과 런타임 설정

main queue visibility timeout은 300초를 유지한다. Consumer는 `ON_SUCCESS`로 정상 반환한 뒤에만 메시지를 삭제하고, 예약 배치 시작과 각 500명 페이지 전후에 `Visibility.changeTo(300)`으로 현재 메시지의 visibility를 연장한다.

전체 배치 시간은 `ceil(대상 사용자 수 / 500) × (페이지 일괄 조회 + 후보 계산 + Expo 최대 100건 단위 발송 시간)`이다. 현재 활성 사용자 수, DB 실행계획, Expo 발송 지연의 실측값이 없으므로 IaC timeout을 임의로 늘리지 않는다. 한 페이지가 300초를 넘으면 중복 전달은 가능하지만 `push_delivery`가 실제 Expo 중복 발송을 막는다. dev 부하 측정 결과가 나온 뒤에만 timeout 변경을 검토한다.

| 환경 변수 | IaC 주입 | 기본값 또는 SSM |
| --- | --- | --- |
| `LANDIT_NOTIFICATION_CONSUMER_ENABLED` | dev·prod `true` | 일반 환경 변수 |
| `SQS_PUSH_NOTIFICATIONS_QUEUE_URL` | dev·prod | Terraform Queue URL |
| `LANDIT_NOTIFICATION_TEST_API_ENABLED` | dev만 `true` | prod는 미주입 |
| `LANDIT_NOTIFICATION_EXPO_BASE_URL` | 미주입 | BE 기본값 사용 |
| `LANDIT_NOTIFICATION_CONNECT_TIMEOUT` | 미주입 | BE 기본값 `5s` 사용 |
| `LANDIT_NOTIFICATION_REQUEST_TIMEOUT` | 미주입 | BE 기본값 `10s` 사용 |
| `LANDIT_NOTIFICATION_RECEIPT_DELAY_SECONDS` | 미주입 | BE 기본값 `900` 사용 |
| `LANDIT_NOTIFICATION_EXPO_ACCESS_TOKEN` | Expo 보안 토큰 사용 시에만 | SSM SecureString 필요 |

`LANDIT_NOTIFICATION_RECEIPT_DELAY_SECONDS`는 BE가 정확히 `900`만 허용하므로 IaC에서 별도 값을 주입하지 않는다. Expo access token 값은 문서나 Terraform state에 기록하지 않는다.

## 배포와 활성화 순서

1. dev와 prod plan에서 LAN-184 허용 범위를 먼저 감사한다. API Task Definition의 `delete,create` 새 revision과 API ECS Service의 in-place `update`는 허용한다.
2. ECS Service delete 또는 replace, Worker IAM·Task Definition·Service 변경, 기존 jobs Queue·DLQ 변경이 있으면 진행하지 않는다.
3. prod plan에 LAN-184와 무관한 WAF logging·Athena·Glue 변경이나 삭제가 있으면 source와 state를 정합화하기 전에는 apply를 요청하지 않는다.
4. dev Scheduler는 검증된 현재 운영 상태에 맞춰 기본 `ENABLED`로 유지한다.
5. `SCHEDULED_NOTIFICATION_BATCH`, `PUSH_RECEIPT_CHECK`와 visibility 연장 구현이 포함된 BE를 dev에 먼저 배포한다.
6. dev main queue에 두 메시지 유형을 각각 수동 발행하고, 500명 페이지 경계, Expo 최대 100건 단위 직접 발송, `PUSH_RECEIPT_CHECK` 900초 지연, 멱등성, DLQ 이동과 배치 처리 시간을 검증한다.
7. prod Scheduler는 dev 실기기 E2E와 운영 검토가 완료될 때까지 반드시 `DISABLED`로 유지한다. prod enable plan과 apply는 별도 승인 범위다.

prod Scheduler 활성화는 기본값을 바꾸지 않고 별도 plan으로만 수행한다.

```bash
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
  --queue-url "$(AWS_PROFILE=landit AWS_REGION=ap-northeast-2 terraform -chdir="$LAN184_ROOT" output -raw push_notifications_queue_url)" \
  --attribute-names QueueArn VisibilityTimeout MessageRetentionPeriod RedrivePolicy ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws sqs get-queue-attributes \
  --queue-url "$(AWS_PROFILE=landit AWS_REGION=ap-northeast-2 terraform -chdir="$LAN184_ROOT" output -raw push_notifications_dlq_url)" \
  --attribute-names QueueArn MessageRetentionPeriod ApproximateNumberOfMessages
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws scheduler get-schedule \
  --name "$LAN184_PREFIX-review-reminder" \
  --query '{State:State,ScheduleExpression:ScheduleExpression,Timezone:ScheduleExpressionTimezone,TargetArn:Target.Arn}' \
  --output json
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws cloudwatch describe-alarms \
  --alarm-names "$LAN184_PREFIX-push-notifications-backlog" "$LAN184_PREFIX-push-notifications-dlq" \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Metric:MetricName,Threshold:Threshold,Period:Period,AlarmActions:AlarmActions,OKActions:OKActions,InsufficientDataActions:InsufficientDataActions}' \
  --output table
```

develop은 EC2 Compose runtime의 `/run/landit/api.env`를 값 출력 없이 검사한다.

```bash
LAN184_ROOT=environments/dev
DEV_INSTANCE_ID="$(AWS_PROFILE=landit AWS_REGION=ap-northeast-2 terraform -chdir="$LAN184_ROOT" output -raw ec2_instance_id)"
DEV_CHECK_COMMAND_ID="$(AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws ssm send-command \
  --instance-ids "$DEV_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo grep -Eq \"^SQS_PUSH_NOTIFICATIONS_QUEUE_URL=.+$\" /run/landit/api.env && sudo grep -qx \"LANDIT_NOTIFICATION_CONSUMER_ENABLED=true\" /run/landit/api.env && sudo grep -qx \"LANDIT_NOTIFICATION_TEST_API_ENABLED=true\" /run/landit/api.env"]' \
  --query 'Command.CommandId' \
  --output text)"
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws ssm get-command-invocation \
  --command-id "$DEV_CHECK_COMMAND_ID" \
  --instance-id "$DEV_INSTANCE_ID" \
  --query '{Status:Status,ResponseCode:ResponseCode}' \
  --output json
```

production은 ECS API Task Definition의 환경 변수를 검사한다.

```bash
LAN184_PREFIX=prod-landit
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws ecs describe-task-definition \
  --task-definition "$LAN184_PREFIX-api" \
  --query 'taskDefinition.containerDefinitions[?name==`api`].environment[?name==`SQS_PUSH_NOTIFICATIONS_QUEUE_URL` || name==`LANDIT_NOTIFICATION_CONSUMER_ENABLED`]' \
  --output json
```

수동 메시지 검증은 BE 운영 절차에 따라 수행한다. Queue attribute와 Alarm 상태만 조회하고, 운영 문서·터미널 기록·로그에 메시지 본문을 남기지 않는다.

## 민감 데이터와 DLQ 안전 수칙

- Push token, 사용자 식별자, 메시지 본문, DLQ message body를 문서, issue, 로그, 배포 출력에 기록하지 않는다.
- DLQ 원인 분석은 message count, receive count, timestamp, 오류 분류처럼 본문이 아닌 메타데이터로 시작한다.
- 반드시 본문 확인이 필요한 경우에는 승인된 제한된 접근 경로에서 최소 인원만 확인하고, 값을 복사하거나 공유 채널에 붙여 넣지 않는다.
- Queue URL과 Scheduler ARN은 secret이 아니지만, credential이나 SSM secret과 함께 출력하거나 기록하지 않는다.
- Alarm은 초기에는 CloudWatch 상태만 생성하며 SNS나 Discord 같은 외부 action은 연결하지 않는다.
