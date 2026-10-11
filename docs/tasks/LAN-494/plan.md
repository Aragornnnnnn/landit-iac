# LAN-494 오전 8시 표현 복습 스케줄

## 승인된 범위

- dev와 운영에 매일 오전 8시, `Asia/Seoul` 기준 복습 알림을 설정한다.
- `${prefix}-expression-review`가 기존 Push SQS에 `REVIEW_NOTIFICATION_BATCH`를 발행한다.
- 기존 오후 8시 학습 알림과 사용자별 복습 대상 조건은 유지한다.

## 설정과 검증

- 공통 일정은 `cron(0 8 * * ? *)`, flexible window는 `OFF`다.
- `expression_review_schedule_enabled`는 dev와 운영 모두 기본 `true`다.
- 두 환경의 `terraform validate`, `terraform fmt -check -recursive`, 기존 Push 인프라 계약 검사를 통과했다.
- 각 환경의 저장된 plan에서 복습 Scheduler 한 개 생성만 확인했다. 기존 리소스 변경·삭제는 없다.
- plan의 큐·실행 역할·시간대와 context token이 포함된 실제 JSON 메시지 계약을 검증했다.

## 적용 상태: 2026-09-24

- dev: 저장된 plan 적용 완료. `develop-landit-expression-review`가 오전 8시 `ENABLED`인 것을 AWS에서 다시 확인했다.
- 적용 후 전체 dev plan에서 복습 스케줄은 `no-op`이다. 기존 EC2 IAM 정책 두 건과 SSM 배포 문서의 변경은 작업 범위 밖이라 적용하지 않았다.
- dev 실행 이미지 `70ec76ec5b0849c9c0bc1c424c88ea2aecdefbb8`는 복습 배치를 지원한다. 실행 컨테이너의 Consumer 활성화와 dev Push 큐 연결도 확인했다.
- 운영: 새 저장 plan에서 오전 8시 `ENABLED` Scheduler 한 개 생성만 확인하고 적용했다. AWS에서 `prod-landit-expression-review`의 시각·시간대·활성 상태·메시지 유형·운영 Push 큐 연결을 재확인했다.
- 운영 적용 후 현재 실행 이미지 digest를 입력한 전체 plan에서 복습 스케줄은 `no-op`이다. 기존 Sentry Lambda와 API·Worker의 Task Definition·Service 변경은 작업 범위 밖이라 적용하지 않았다.
- 운영 실행 이미지 `ed13aa0f0b2b56fdf82769e4a05b852821a72e54`의 복습 배치 분기, ECS 배포 완료, Consumer 활성화와 운영 Push 큐 연결을 확인했다. API health는 HTTP 200, `UP`이다.
- 9월 22일에는 구버전 운영 BE가 복습 배치를 지원하지 않아 적용을 보류했다. 사용자의 운영 배포 완료 안내 후 실제 실행 이미지로 선행 조건 해소를 확인했다.
- 기존 dev·운영 학습 알림은 오후 8시 `ENABLED` 상태를 유지한다.
- 운영 첫 정기 실행 예정은 2026년 9월 24일 오전 8시(KST)다.
- 정시 배치 실행과 기기 수신은 아직 확인하지 않았다. 이 작업에서 운영 BE 배포나 즉시 일괄 발송은 실행하지 않는다.

## 운영 변경 원칙

운영의 `expression_review_schedule_enabled`와 AWS 상태를 함께 관리한다. 해당 Scheduler만 포함하는 저장된 plan을 검증·적용하고 실제 상태와 메시지 종류를 다시 확인한다.
