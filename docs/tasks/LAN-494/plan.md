# LAN-494 오전 8시 표현 복습 스케줄

## 승인된 범위

- dev와 운영에 매일 오전 8시, `Asia/Seoul` 기준 복습 알림을 설정한다.
- `${prefix}-expression-review`가 기존 Push SQS에 `REVIEW_NOTIFICATION_BATCH`를 발행한다.
- 기존 오후 8시 학습 알림과 사용자별 복습 대상 조건은 유지한다.

## 설정과 검증

- 공통 일정은 `cron(0 8 * * ? *)`, flexible window는 `OFF`다.
- `expression_review_schedule_enabled`는 dev 기본 `true`, 운영 기본 `false`다.
- 두 환경의 `terraform validate`, `terraform fmt -check -recursive`, 기존 Push 인프라 계약 검사를 통과했다.
- 각 환경의 저장된 plan에서 복습 Scheduler 한 개 생성만 확인했다. 기존 리소스 변경·삭제는 없다.
- plan의 큐·실행 역할·시간대와 context token이 포함된 실제 JSON 메시지 계약을 검증했다.

## 적용 상태: 2026-09-22

- dev: 저장된 plan 적용 완료. `develop-landit-expression-review`가 오전 8시 `ENABLED`인 것을 AWS에서 다시 확인했다.
- 적용 후 전체 dev plan에서 복습 스케줄은 `no-op`이다. 기존 EC2 IAM 정책 두 건과 SSM 배포 문서의 변경은 작업 범위 밖이라 적용하지 않았다.
- dev 실행 이미지 `70ec76ec5b0849c9c0bc1c424c88ea2aecdefbb8`는 복습 배치를 지원한다. 실행 컨테이너의 Consumer 활성화와 dev Push 큐 연결도 확인했다.
- 운영: 오전 8시 `DISABLED` 생성 plan만 준비했다. 비활성 생성 여부에 대한 사용자 답변을 기다린다.
- 현재 운영 실행 이미지 `feed886215860e6687843c3fc294fd7b1b628d6c`에는 복습 배치 분기가 없다. 미지원 메시지는 예외가 발생하므로 활성화하지 않았다.
- 기존 dev·운영 학습 알림은 오후 8시 `ENABLED` 상태를 유지한다.
- 정시 배치 실행과 기기 수신은 아직 확인하지 않았다. 이 작업에서 운영 BE 배포나 즉시 일괄 발송은 실행하지 않는다.

## 운영 활성화 조건

복습 BE와 FE 배포를 확인한 뒤 운영의 `expression_review_schedule_enabled` 기본값을 `true`로 바꾼다. 해당 Scheduler의 변경 plan을 검증·적용하고 AWS의 실제 상태와 메시지 종류를 다시 확인한다.
