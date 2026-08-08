# LAN-284 개발 EC2 통합 설계

## 목표

개발 BE와 AI를 단일 `t3.small` EC2로 이전해 전체 AWS 예상 비용을 월 약 `$114.55`에서 `$86.70`으로 줄인다.

## 1차 범위

- 기존 개발 ECS API·AI Service와 ALB를 그대로 유지한다.
- 기존 개발 VPC의 public subnet에 `t3.small` EC2, Elastic IP, 암호화된 gp3 20GB를 추가한다.
- EC2에서 Docker Compose로 BE, AI, Caddy를 실행한다.
- 기존 개발 ECR, SSM Parameter Store, S3, SQS, CloudWatch Log Group을 재사용한다.
- `api-ec2-develop.landit.im`, `ai-ec2-develop.landit.im`을 병행 검증 도메인으로 사용한다. DNS 변경은 Terraform 밖의 Vercel에서 별도 승인 후 진행한다.
- 운영 환경과 공유 콘텐츠 인프라는 변경하지 않는다.

## 실행 구조

- Caddy만 80번과 443번 포트를 공개한다. SSH, BE 8080, AI 8000 포트는 공개하지 않는다.
- Caddy는 병행 검증 도메인을 Compose 내부의 BE와 AI로 전달한다.
- EC2의 BE는 기존 ECS용 `/landit/develop/LANDIT_AI_BASE_URL`을 변경하지 않고 `http://ai:8000`으로 덮어쓴다.
- BE와 AI에는 각각 768MiB와 512MiB 메모리 제한을 두고 EC2에 2GB swap을 둔다.
- 예측하지 않은 CPU credit 과금을 막기 위해 T3 credit mode는 `standard`로 둔다.
- EC2는 IMDSv2를 강제하고 SSM Session Manager로만 관리한다.
- EC2 instance role은 ECR pull, `/landit/develop/*` 조회, KMS 복호화, 기존 S3·SQS·CloudWatch Logs 접근만 허용한다.
- 한 instance role을 두 컨테이너가 공유해 기존 ECS의 BE·AI IAM 분리가 사라지는 점은 테스트 환경의 비용 절감 조건으로 수용한다.

## 배포

- BE와 AI의 기존 개발 workflow는 ECS 배포와 검증을 먼저 완료한다.
- ECS 성공 후 같은 `${GITHUB_SHA}` 이미지를 SSM Run Command로 EC2에 미러링한다.
- EC2 배포 스크립트는 BE와 AI SHA를 따로 저장하고 `flock`으로 동시 실행을 직렬화한다.
- 비밀값은 EC2가 instance role로 읽어 권한 `0600`의 runtime env 파일에 기록한다. Terraform state와 GitHub Actions 로그에는 값을 남기지 않는다.
- EC2 배포가 실패해도 기존 ECS와 원래 개발 도메인은 계속 서비스한다.

## 전환과 검증

1. Terraform plan에서 EC2 관련 추가만 확인하고 별도 승인 후 적용한다.
2. EC2 running, SSM Online, IMDSv2, 보안 그룹과 컨테이너 내부 health를 확인한다.
3. 병행 검증 DNS를 연결하고 HTTPS, BE API, AI API, BE에서 AI를 호출하는 실제 기능을 확인한다.
4. 기존 개발 도메인과 ECS target health가 계속 정상인지 함께 확인한다.
5. CloudWatch Logs, Grafana metric, 메모리, swap, 디스크, OOM, `CPUCreditBalance`를 24~48시간 관찰한다.
6. 직전 이미지 SHA로 EC2만 롤백하는 절차를 검증한다.
7. 별도 승인 후 원래 개발 도메인을 EC2 Elastic IP로 전환한다. 실패하면 DNS를 ALB로 되돌린다.

## 기존 인프라 제거

- ECS와 ALB 제거는 DNS 전환과 관찰 완료 뒤 별도 작업과 승인으로 진행한다.
- ECR, S3, SQS, SSM, CloudWatch Log Group과 Grafana 전달 경로는 보존한다.
- 현재 `app-platform` 모듈을 통째로 제거하면 보존 대상도 함께 삭제되므로 금지한다.

## 적용 전 선행 조건

- 현재 dev plan에는 이미 반영되지 않은 LAN-184 Push 인프라 제거가 `1 add, 2 change, 8 destroy`로 남아 있다.
- LAN-284 apply 전에 LAN-184를 별도 적용해 기준 plan을 `No changes`로 만들거나 함께 적용할지 사용자의 별도 승인을 받는다.
- LAN-284 1차 plan의 완료 기준은 기준 plan 대비 EC2 관련 추가만 생기고 기존 ECS·ALB 변경이나 추가 삭제가 없는 것이다.

## 비용

| 구분 | 현재 | 전환 후 |
| --- | ---: | ---: |
| 개발 환경 | 약 `$52.74` | 약 `$24.89` |
| 전체 인프라 | 약 `$114.55` | 약 `$86.70` |
| 월 절감액 | - | 약 `$27.85` |
