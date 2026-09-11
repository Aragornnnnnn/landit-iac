# 배포 중 학습 보존.

공개 순서는 dev 테스트 → 심사 → 출시 → 오픈이다. 코드 배포와 결제 공개는 분리한다. 결제 공개는 기존 SSM `LANDIT_SUBSCRIPTION_LAUNCHED_AT`과 FE `NEXT_PUBLIC_PAYMENT_ENABLED`를 유지한다. DB 공개 정책으로 대체하지 않는다. 기존 학습의 24시간 재개 권한과 작업 복구는 BE가 관리한다.

## 이미지와 되돌리기.

- BE·AI 저장소가 코드 이미지를 배포한다. 운영 workflow는 새 digest를 넣은 task revision을 배포하고 직전 revision을 기록해야 한다. `latest` task의 강제 재배포를 사용하지 않는다.
- IaC 운영 plan은 `scripts/capture-prod-images.py`로 현재 실행 중인 두 서비스의 digest를 고정한다. 혼합 배포 중이면 중단하고, apply 직전 실행 revision·digest가 plan 때와 다르면 다시 plan한다. 승인부터 apply 종료까지 BE·AI 코드 배포를 멈춘다. 마지막 검사와 apply 사이의 변경까지 원자적으로 잠그는 장치는 아니다.
- API와 AI task definition은 `skip_destroy=true`로 이전 revision을 보존한다. 롤백할 revision의 이미지가 ECR에 남아 있어야 하며, 호환 기간에는 이전 revision과 SHA 이미지를 삭제하거나 태그를 덮어쓰지 않는다.
- 개발 배포는 Git SHA를 ECR digest로 해석해 고정한다. 배포 전에 실제 실행 컨테이너의 digest를 캡처하고 `/opt/landit/{api,ai}.previous.ref`·`.previous.tag`와 `deployments.log`에 남긴다. 같은 SHA를 재빌드해도 health 실패 시 이전 digest를 다시 받는다. 수동 롤백은 `deploy-service api|ai sha256:<기록한 digest>`를 사용한다.

로컬 운영 plan도 같은 입력을 사용한다. 생성된 파일은 커밋하지 않는다.

```bash
AWS_PROFILE=landit python3 scripts/capture-prod-images.py --output /tmp/landit-release.tfvars.json
AWS_PROFILE=landit terraform -chdir=environments/prod plan -var-file=/tmp/landit-release.tfvars.json -out=/tmp/landit-production.tfplan
```

운영 BE·AI 코드 배포 역할 `landit-github-actions-prod-deploy`에는 새 revision 등록을 위한 `ecs:RegisterTaskDefinition`, 해당 task definition의 `ecs:TagResource`, 기존 ECS 실행·task 역할에 한정한 `iam:PassRole`이 필요하다. 이 IAM 추가 코드 작성은 자동 승인 검토가 거절해 포함하지 않았다. 역할 추가 권한의 코드 작성 승인·plan 검토·apply를 마치기 전 새 운영 코드 workflow를 실행하지 않는다.

승인된 plan을 적용하기 직전 `terraform show -json`을 `capture-prod-images.py --check`에 전달한다. 일반 운영 apply workflow에 이 검사가 포함되어 있다. 새 조회에 필요한 `ecs:ListTasks`, `ecs:DescribeTasks`는 별도 bootstrap plan·승인·apply 후 Terraform Actions 역할에 반영한다.

## AI 호출과 샌드박스.

AI 컨테이너 포트는 운영에서는 ALB 보안 그룹에서만, 개발에서는 loopback에서만 접근된다. 공개 ALB·Caddy의 AI 주소는 유지하며, AI의 `/api/v1`은 `X-Landit-Internal-Token`으로 BE 호출을 검증한다. 네트워크 자체를 private으로 바꾸는 작업은 포함하지 않는다. `/health`만 인증에서 제외한다.

1. 같은 환경의 `/landit/{develop,prod}/LANDIT_AI_INTERNAL_TOKEN`을 비어 있지 않은 `SecureString`으로 준비한다. 실제 값은 Terraform에 넣지 않는다.
2. 헤더를 보내는 BE와 인증을 지원하는 AI 코드를 먼저 배포하되, AI 토큰 강제는 끈다.
3. 개발은 토큰 등록 후 API 배포 → AI 배포 순서다. 운영은 `ai_internal_token_enabled=true`, `ai_internal_auth_enabled=false`로 BE에 먼저 주입한다. 모든 BE task가 교체되어 실제 요청에 토큰을 보내는지 확인한다.
4. 운영 `ai_internal_auth_enabled=true`로 AI에도 주입한다. 인증 없는 학습 API는 401, BE 학습 요청은 성공하는지 확인한다. 토큰 없는 기본값은 구버전 공존용이며, 이 상태는 AI 보호 완료가 아니다. 롤백할 BE도 헤더를 보내는 버전이어야 한다.

운영 두 입력은 Terraform workflow의 `AI_INTERNAL_TOKEN_ENABLED`, `AI_INTERNAL_AUTH_ENABLED` 환경 변수로 설정한다. 모두 기본 `false`이며, 준비되지 않은 SSM 때문에 기존 task 배포가 실패하지 않는다.

`LANDIT_REVENUECAT_APPLY_SANDBOX_EVENTS`는 개발·운영 기본 `true`로 기존 BE 기본값을 유지한다. 스토어 심사 뒤 Terraform 입력 `revenuecat_apply_sandbox_events`를 명시적으로 `false`로 변경한다. workflow 변수는 `REVENUECAT_APPLY_SANDBOX_EVENTS`다. 설정은 새 API task에서 적용되며, 결제 공개 시점이나 실결제 구독 상태를 변경하는 스위치는 아니다.

## 최초 전환과 확인.

- 구 AI 응답을 읽을 수 있는 BE와 구 BE 요청을 받을 수 있는 AI를 먼저 배포한다. 기존 AI 메모리 피드백이 DB로 옮겨지기 전에는 AI를 교체하지 않는다. 옮길 수 없는 세션은 별도로 신규 진입을 제한할 운영 수단을 준비해 기존 결과 수거를 완료한 뒤 교체한다. 이번 범위에는 DB 신규 시작 중지 스위치가 없다. 대화 진행 권한 24시간과 AI 메모리 TTL은 다르므로 시간만 기다려서 안전해졌다고 판단하지 않는다.
- ECS·Compose 종료 유예는 120초다. BE는 HTTP graceful 50초와 executor 대기 50초, AI는 graceful 110초 계약을 사용한다. ALB idle 130초·drain 150초로 120초 피드백 응답을 수용한다. 종료 제한을 넘거나 강제 종료된 작업은 BE DB에서 재시도해야 한다. [AWS 종료 유예 문서](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ContainerDefinition.html).
- dev에서 피드백 생성 중 AI 교체, BE 저장 직전 재시작, 같은 메시지 재요청을 실행한다. 다음 질문 지연, 중복 결과, 영구 PREPARING이 없어야 한다. 이전 BE+새 AI와 새 BE+이전 AI 조합도 확인한다.
- 결제 오픈 전 시작한 학습이 같은 ID로 마무리되는지, 무료 대화 한 번 뒤 새 유료 학습이 막히는지, 구매·취소·복원이 실제 구독과 맞는지 확인한다. 실기기/구매 결과와 서버별 image digest를 함께 기록한다. health 성공만으로 완료하지 않는다.
- 기능 롤백은 BE 오픈 시각을 비우고 재기동하는 절차와 FE 플래그 false 재배포를 함께 수행한다. DB에 저장한 학습·피드백·실결제 권한은 유지한다. 코드 롤백 시 이전 BE·AI가 새 저장 데이터와 인증 계약을 읽을 수 있는지 먼저 확인한다.

## 결제 비활성 선배포 조건.

- BE 오픈 시각은 미설정으로 유지한다. FE 공개는 기존 플래그를 따른다. 학습·피드백의 DB 보존은 유료 잠금을 켜지 않는다.
- 2026-09-11 운영 API revision 12에는 오픈 시각의 SSM 주입이 없었다. 현 IaC의 API secrets 목록에도 없으므로 SSM 값만 추가해도 활성화되지 않는다. 오픈 전에 파라미터 준비와 task definition 연결을 별도로 완료해야 한다. 존재하지 않는 SSM을 무조건 연결하면 새 task가 시작하지 못하므로 이번 선배포 수정에서 강제로 추가하지 않았다.
- ECS에 주입한 환경변수는 새 task 시작 때 읽는다. SSM 값 변경만으로 실행 중 BE가 즉시 전환되는 구조가 아니다. 오픈·롤백 때 새 task의 실제 설정을 확인한다.
- 오픈 후 24시간 기존 학습 재개까지 보장하려면 FE의 재개 화면·페이월도 BE 학습 권한을 반영해야 한다. 결제 비활성 선배포에는 이 FE 변경이 필요하지 않다.
