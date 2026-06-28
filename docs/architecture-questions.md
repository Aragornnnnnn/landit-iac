# Landit Architecture Questions

이 문서는 Landit IaC에서 실제 리소스를 만들기 전에 결정해야 할 질문을 모은다.

## 환경과 state

- dev/prod를 별도 Terraform root로 계속 분리할지 결정 필요.
- 공통 module을 둘지, 초기에는 root별 단순 구성을 유지할지 결정 필요.
- AWS account는 `982529430654`, AWS profile은 `landit`, 기본 region은 `ap-northeast-2`로 둔다.
- Terraform state bucket은 `landit-terraform-state-982529430654`로 둔다.
- state key는 `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate`로 둔다.
- lock 방식은 S3 native lockfile을 사용한다.
- state bucket 생성은 `bootstrap/state-backend` root로 별도 진행한다.

## 서비스 경계

- backend repository 후보 `landit-be`를 확정할지 결정 필요.
- frontend repository 후보 `landit-fe`를 확정할지 결정 필요.
- AI repository 후보 `landit-ai`를 별도 서비스로 둘지 결정 필요.
- backend, frontend, AI 사이의 네트워크 경계와 인증 방식을 결정 필요.

## 배포 방식

- backend를 EC2, ECS, Lambda, App Runner, 다른 방식 중 무엇으로 배포할지 결정 필요.
- frontend를 Vercel, S3 plus CloudFront, Amplify, 다른 방식 중 무엇으로 배포할지 결정 필요.
- AI 서비스를 backend 내부 기능으로 둘지, 별도 런타임으로 둘지 결정 필요.
- Terraform GitHub Actions는 `Aragornnnnnn/landit-iac`에서 실행한다.
- plan job OIDC subject는 `repo:Aragornnnnnn/landit-iac:environment:terraform-plan`로 둔다.
- apply job OIDC subject는 `repo:Aragornnnnnn/landit-iac:environment:terraform-apply`로 둔다.
- GitHub Actions용 AWS IAM role과 세부 권한은 결정 필요.

## 도메인과 네트워크

- production 도메인 결정 필요.
- development 도메인 결정 필요.
- DNS provider와 hosted zone 관리 주체 결정 필요.
- TLS 인증서 발급과 종료 위치 결정 필요.
- public/private subnet, NAT, security group 기본 정책 결정 필요.

## 데이터와 secret

- RDS, DynamoDB, Redis, S3 같은 managed service 사용 여부 결정 필요.
- secret 저장소를 AWS SSM Parameter Store, Secrets Manager, 외부 secret manager 중 무엇으로 할지 결정 필요.
- SSM path 후보 `/landit/prod`, `/landit/develop`을 그대로 사용할지 결정 필요.
- Terraform이 secret 값을 직접 관리하지 않도록 운영 절차 결정 필요.

## 운영과 비용

- 로그 수집, metric, alerting 기준 결정 필요.
- preview, staging 같은 추가 환경이 필요한지 결정 필요.
- 비용 상한과 삭제 정책 결정 필요.
- backup, retention, disaster recovery 기준 결정 필요.
