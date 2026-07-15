# landit-iac

Landit 서비스의 Infrastructure as Code 레포입니다.

이 레포는 Landit의 Terraform backend, SSM runtime parameter, ECS Fargate application platform을 관리합니다. production 적용은 Terraform plan과 사용자 확인을 먼저 거친 뒤 진행합니다.

## 현재 상태

| 영역 | 현재 상태 |
| --- | --- |
| Terraform state | S3 backend 사용 준비 완료 |
| State bucket | `landit-terraform-state-982529430654` |
| Terraform roots | `bootstrap/state-backend`, `environments/shared`, `environments/dev`, `environments/prod` |
| GitHub Actions | 수동 `workflow_dispatch`로 plan 또는 승인 후 apply |
| 일반 workflow target | `shared`, `develop`, `production` |
| Bootstrap | state bucket 관리자 절차로 분리 |
| SSM Parameter Store | develop/prod 기본 runtime parameter 준비 완료 |
| Application platform | develop/prod ECS, ALB, ECR, SQS, S3 구성 생성 완료 |
| Shared content delivery | private S3 bucket과 CloudFront OAC Terraform 구성 추가, apply 전 |
| Production platform | prod runtime image push 필요 |
| Public ingress | 환경별 BE와 AI host rule로 분리 |

## 문서

- [AGENTS.md](AGENTS.md): 에이전트 작업 규칙.
- [Developer Guide](docs/developer-guide.md): 개발자용 Terraform 실행, GitHub Actions, Git 작업 흐름.
- [Architecture Questions](docs/architecture-questions.md): 아키텍처 확정 전 질문.
- [SSM Parameters](docs/ssm-parameters.md): runtime parameter 이름, 타입, 운영 규칙.
- [Observability](docs/observability.md): Sentry와 Grafana Cloud 지표·로그 연동 구조와 검증 절차.
- [Content Storage](docs/content-storage.md): 공통 콘텐츠 S3 key, CloudFront 조회, DB URL 반영, 파일 교체 절차.
- [checklist.md](checklist.md): 작업 체크리스트.
- [context-notes.md](context-notes.md): 작업 결정과 검증 기록.

## 기본 값

| 항목 | 값 |
| --- | --- |
| project name | `landit` |
| repository | `landit-iac` |
| backend repository | `landit-be` |
| frontend repository | `landit-fe` |
| AI repository | `landit-ai` |
| production SSM path | `/landit/prod` |
| development SSM path | `/landit/develop` |
| production state key | `prod/landit-iac/terraform.tfstate` |
| development state key | `dev/landit-iac/terraform.tfstate` |
| bootstrap state key | `bootstrap/state-backend/terraform.tfstate` |
| shared state key | `shared/landit-iac/terraform.tfstate` |
| AWS profile | `landit` |
| AWS region | `ap-northeast-2` |
| backend develop URL | `https://api-develop.landit.im` |
| backend production URL | `https://api.landit.im` |
| AI develop URL | `https://ai-develop.landit.im` |
| AI production URL | `https://ai.landit.im` |

## 범위

- Terraform backend, GitHub Actions, ECS Fargate application platform을 관리합니다.
- develop은 기존 ALB에 BE와 AI host rule을 함께 둡니다.
- production은 별도 ALB에 BE와 AI host rule을 함께 둡니다.
- DNS record는 Vercel에서 관리하므로 Terraform은 Route53 record를 만들지 않습니다.
- SSM Parameter Store에는 runtime parameter를 Terraform 밖에서 준비합니다.
- `terraform apply`, `terraform destroy`, 실제 AWS 리소스 생성, 변경, 삭제는 사용자 확인 없이는 실행하지 않습니다.
- 공통 콘텐츠 이미지는 private S3 bucket에서 CloudFront OAC를 통해서만 조회합니다.

## 주요 경로

| 경로 | 역할 |
| --- | --- |
| `bootstrap/state-backend` | Terraform state bucket 관리자 root |
| `environments/shared` | 공통 콘텐츠 S3 bucket과 CloudFront root |
| `environments/dev` | development Terraform root |
| `environments/prod` | production Terraform root |
| `modules/app-platform` | ECS Fargate application platform module |
| `.github/workflows/terraform.yml` | 수동 Terraform plan/apply workflow |
| `docs/` | 개발자 가이드와 아키텍처 질문 |
