# landit-iac

Landit 서비스의 Infrastructure as Code 레포입니다.

이 레포는 현재 초기 세팅 단계입니다. 최종 인프라 구성과 아키텍처는 아직 확정되지 않았고, 실제 애플리케이션 리소스도 만들지 않았습니다.

## 현재 상태

| 영역 | 현재 상태 |
| --- | --- |
| Terraform state | S3 backend 사용 준비 완료 |
| State bucket | `landit-terraform-state-982529430654` |
| Terraform roots | `bootstrap/state-backend`, `environments/dev`, `environments/prod` |
| GitHub Actions | 수동 `workflow_dispatch`로 plan 또는 승인 후 apply |
| 일반 workflow target | `develop`, `production` |
| Bootstrap | state bucket 관리자 절차로 분리 |
| 실제 서비스 리소스 | 아직 만들지 않음 |
| 아키텍처 | 확정 전 |

## 문서

- [AGENTS.md](AGENTS.md): 에이전트 작업 규칙.
- [Developer Guide](docs/developer-guide.md): 개발자용 Terraform 실행, GitHub Actions, Git 작업 흐름.
- [Architecture Questions](docs/architecture-questions.md): 아키텍처 확정 전 질문.
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
| AWS profile | `landit` |
| AWS region | `ap-northeast-2` |

## 범위

- IaC 작업 규칙과 문서 구조를 준비합니다.
- dev/prod Terraform root를 나중에 확장할 수 있도록 최소 구조만 둡니다.
- Terraform provider, version, 공통 태그, S3 backend 기준만 둡니다.
- EC2, ECS, RDS, Vercel, CloudFront, Route53, SSM 같은 실제 서비스 리소스는 아직 만들지 않습니다.
- `terraform apply`, `terraform destroy`, 실제 AWS 리소스 생성, 변경, 삭제는 사용자 확인 없이는 실행하지 않습니다.

## 주요 경로

| 경로 | 역할 |
| --- | --- |
| `bootstrap/state-backend` | Terraform state bucket 관리자 root |
| `environments/dev` | development Terraform root |
| `environments/prod` | production Terraform root |
| `.github/workflows/terraform.yml` | 수동 Terraform plan/apply workflow |
| `docs/` | 개발자 가이드와 아키텍처 질문 |
