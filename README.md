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
| Application platform | develop 단일 EC2, production ECS·ALB, 공통 ECR·SQS·S3 |
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
- [작업 문서](docs/tasks/): 이슈별 `plan.md`와 `design.md`.
- [checklist.md](checklist.md): 과거 작업 체크리스트. 새 작업은 이슈별 문서에 기록합니다.
- [context-notes.md](context-notes.md): 과거 결정과 검증 기록. 새 작업은 이슈별 문서에 기록합니다.

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

- Terraform backend, GitHub Actions, EC2와 ECS Fargate application platform을 관리합니다.
- develop은 단일 EC2의 Docker Compose에서 BE·AI·Caddy를 실행합니다.
- production은 별도 ALB에 BE와 AI host rule을 함께 둡니다.
- DNS record는 Vercel에서 관리하므로 Terraform은 Route53 record를 만들지 않습니다.
- SSM Parameter Store에는 runtime parameter를 Terraform 밖에서 준비합니다.
- `terraform apply`, `terraform destroy`, 실제 AWS 리소스 생성, 변경, 삭제는 사용자 확인 없이는 실행하지 않습니다.
- 공통 콘텐츠 이미지는 private S3 bucket에서 CloudFront OAC를 통해서만 조회합니다.

## 개발 EC2 운영

BE·AI는 같은 EC2에서 실행하고 Caddy가 `api-develop.landit.im`, `ai-develop.landit.im`을 서비스한다. 배포 workflow는 ECR push 뒤 SSM으로 각 컨테이너를 갱신하며, BE는 애플리케이션 배포 전에 Flyway migration을 실행한다. BE의 AI 주소는 Compose 내부 `http://ai:8000`으로 고정한다.

Vercel DNS는 EC2 Elastic IP를 가리킨다. 임시 도메인 `api-ec2-develop.landit.im`, `ai-ec2-develop.landit.im`은 검증용으로 유지한다. 배포 health check 실패 시 직전 이미지 SHA로 자동 복구한다.

개발 환경의 08시 복습·20시 학습 알림은 기본 비활성화한다. 개발·운영에 같은 기기 토큰이 등록되어도 개발 자동 알림이 추가로 발송되지 않도록 `expression_review_schedule_enabled`와 `review_reminder_schedule_enabled`를 `false`로 유지한다.

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

## 자동 코드 리뷰

- 리뷰 규칙의 기준은 `AGENTS.md`의 `Code Review Rules`입니다. 경로별로 관련 규칙만 적용합니다.
- [Codex 코드 리뷰 설정](https://chatgpt.com/settings/code-review)에서 이 저장소의 모든 PR에 일반 리뷰를 `푸시할 때마다`, 보안 리뷰를 `PR이 열릴 때` 실행하도록 설정합니다. PR이 없는 브랜치 push는 PR 리뷰 대상이 아닙니다.
- 철저한 검토는 OFF로 두고, 추가 크레딧 사용도 끕니다. 실행 시점과 크레딧 설정은 웹 설정이며 `AGENTS.md`로 변경되지 않습니다.
- 필요하면 PR 댓글의 `@codex review` 또는 `@codex security review`로 수동 리뷰를 요청합니다. 리뷰 지침은 테스트·브랜치 보호·사람의 승인을 대체하지 않습니다.
- CodeRabbit 자동 리뷰는 사용하지 않습니다. `.coderabbit.yaml`은 자동·증분 리뷰와 label·본문 키워드 자동 실행을 끄는 최소 설정만 유지합니다. 파일 삭제만으로는 기본값 또는 상위 설정에 따라 리뷰가 다시 켜질 수 있습니다.
- 기존 PR·작업 문서의 CodeRabbit 리뷰 기록은 과거 근거로 보존합니다. 다른 저장소를 문서에 언급하는 것만으로 Codex의 접근 권한이나 교차 저장소 분석이 설정되지는 않습니다.
