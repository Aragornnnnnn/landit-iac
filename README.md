# landit-iac

Landit 서비스의 Infrastructure as Code 레포입니다.

이 레포는 현재 초기 세팅 단계입니다. 최종 인프라 구성과 아키텍처는 아직 확정되지 않았고, 실제 애플리케이션 리소스도 만들지 않았습니다.

## 한눈에 보기

| 영역 | 현재 상태 |
| --- | --- |
| Terraform state | S3 backend 사용 준비 완료 |
| State bucket | `landit-terraform-state-982529430654` |
| Terraform roots | `bootstrap/state-backend`, `environments/dev`, `environments/prod` |
| GitHub Actions | 수동 `workflow_dispatch`로 plan 또는 승인 후 apply |
| 일반 workflow target | `develop`, `production` |
| Bootstrap | state bucket 관리자 절차로 분리 |
| 실제 서비스 리소스 | 아직 만들지 않음 |
| 아키텍처 | 결정 필요 |

## 기본 값과 후보

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

## 현재 범위

- IaC 작업 규칙과 문서 구조를 준비합니다.
- dev/prod Terraform root를 나중에 확장할 수 있도록 최소 구조만 둡니다.
- Terraform provider, version, 공통 태그, S3 backend 기준만 둡니다.
- EC2, ECS, RDS, Vercel, CloudFront, Route53, SSM 같은 실제 서비스 리소스는 아직 만들지 않습니다.
- `terraform apply`, `terraform destroy`, 실제 AWS 리소스 생성, 변경, 삭제는 사용자 확인 없이는 실행하지 않습니다.

## 작업 시작 전

1. issue number를 확인하고 `feat/{issue number}` 브랜치에서 작업합니다.
2. 예외적으로 issue number 없이 작업할 때는 사용자의 명시적인 허용을 기록합니다.
3. [AGENTS.md](AGENTS.md), [checklist.md](checklist.md), [context-notes.md](context-notes.md)를 먼저 읽습니다.
4. 비 trivial 작업은 계획을 세우고 `checklist.md`, `context-notes.md`를 갱신합니다.
5. 변경 후 실제 실행한 검증 명령과 결과를 최종 응답에 남깁니다.

## Terraform state

Terraform state는 S3 backend를 사용합니다.

```text
Bucket: landit-terraform-state-982529430654
Bootstrap key: bootstrap/state-backend/terraform.tfstate
Production key: prod/landit-iac/terraform.tfstate
Development key: dev/landit-iac/terraform.tfstate
Region: ap-northeast-2
Locking: S3 native lockfile
```

S3 bucket은 생성 완료됐고, `bootstrap/state-backend` state도 같은 bucket의 `bootstrap/state-backend/terraform.tfstate` key로 마이그레이션했습니다.

state bucket은 versioning, 기본 AES256 암호화, public access block, HTTPS-only bucket policy를 사용합니다.

## 로컬 Terraform 실행

`bootstrap/state-backend`는 state bucket 자체를 다루는 관리자 root입니다. 일반 dev/prod 작업에서는 사용하지 않습니다.

state bucket이나 backend 정책을 바꿔야 할 때만 bootstrap root를 확인합니다.

```bash
terraform fmt -recursive
terraform -chdir=bootstrap/state-backend init -backend=false
AWS_PROFILE=landit terraform -chdir=bootstrap/state-backend plan
```

bootstrap apply는 사용자 확인을 받은 뒤에만 실행합니다.

```bash
AWS_PROFILE=landit terraform -chdir=bootstrap/state-backend apply
AWS_PROFILE=landit terraform -chdir=bootstrap/state-backend init -migrate-state
```

dev root는 S3 backend로 초기화하고 plan까지 확인합니다.

```bash
terraform fmt -recursive
AWS_PROFILE=landit terraform -chdir=environments/dev init -reconfigure
terraform -chdir=environments/dev validate
AWS_PROFILE=landit terraform -chdir=environments/dev plan
```

production root도 같은 흐름을 사용합니다.

```bash
terraform fmt -recursive
AWS_PROFILE=landit terraform -chdir=environments/prod init -reconfigure
terraform -chdir=environments/prod validate
AWS_PROFILE=landit terraform -chdir=environments/prod plan
```

`terraform apply`와 `terraform destroy`는 plan 결과를 먼저 확인하고, 실제 변경 내용을 사용자에게 보고한 뒤에만 실행합니다.

## GitHub Actions Terraform

[`.github/workflows/terraform.yml`](.github/workflows/terraform.yml)은 수동 실행 `workflow_dispatch`만 지원합니다.

| 입력 | 값 |
| --- | --- |
| `target` | `develop`, `production` |
| `operation` | `plan-only`, `plan-and-apply` |
| `confirm_environment` | production apply 때만 `production` 입력 |

필요한 GitHub 설정입니다.

- Repository variable 또는 environment variable `AWS_ROLE_ARN`에 GitHub Actions OIDC assume role ARN을 설정합니다.
- `terraform-plan-develop`, `terraform-plan-production` environment를 만듭니다.
- `terraform-apply-develop`, `terraform-apply-production` environment를 만들고 required reviewer를 설정합니다.
- `terraform-apply-production`에는 production 담당자의 required reviewer와 prevent self-review를 설정합니다.
- apply는 `refs/heads/main`에서만 허용합니다.

workflow 실행 순서입니다.

1. 선택한 target의 Terraform root, state key, AWS account, AWS region, apply environment를 로그에 출력합니다.
2. 선택한 root에서 `terraform fmt -recursive -check`, `terraform init`, `terraform validate`를 실행합니다.
3. `terraform plan -out`으로 plan 파일을 만들고 plan 내용을 로그에 출력합니다.
4. plan 파일을 1일 보관 artifact로 업로드합니다.
5. `operation=plan-and-apply`일 때만 target별 apply environment 승인을 기다립니다.
6. 승인 후 같은 plan artifact를 내려받아 `terraform apply`를 실행합니다.

production apply는 `operation=plan-and-apply`, `target=production`, `confirm_environment=production`, `refs/heads/main`, `terraform-apply-production` 승인이 모두 충족되어야 실행됩니다.

OIDC IAM role은 아직 Terraform으로 만들지 않았습니다. role trust policy는 최소한 아래 subject를 허용해야 합니다.

- `repo:Aragornnnnnn/landit-iac:environment:terraform-plan-develop`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-plan-production`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-apply-develop`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-apply-production`.

## Git 작업 흐름

- 일반 작업은 issue number를 먼저 정하고 `feat/{issue number}` 브랜치에서 진행합니다.
- 브랜치는 작업 단위를 나타내고, `develop`/`production`은 Terraform target과 state key로만 구분합니다.
- 환경별 브랜치인 `develop` 또는 `production` 브랜치는 만들지 않습니다.
- 커밋 메시지는 BE 컨벤션인 `{type}: 커밋 메시지` 형식을 사용합니다.
- 타입별 의미는 `AGENTS.md`의 커밋 타입 표를 따릅니다.
- GitHub Actions, Terraform bootstrap, 개발 환경, 설정 변경은 `ci`가 아니라 `chore` 타입을 사용합니다.
- 가능하면 커밋 1개는 변경 30줄 내외로 하고, PR은 리뷰 가능한 크기로 유지합니다.
- 아키텍처 레벨 결정은 GitHub Wiki ADR로 남기고, PR에는 코드 레벨 변경과 검증 결과를 남깁니다.
- 문서 변경도 사람이 검토합니다.

## State와 secret

- 실제 `*.tfvars`, `*.tfplan`, Terraform state 파일은 커밋하지 않습니다.
- secret 값은 Terraform state에 남기지 않는 방식을 우선 검토합니다.
- 접근 키, IP, security group id, secret 값은 커밋하지 않습니다.
- SSM path 후보는 `/landit/prod`, `/landit/develop`입니다.
- state key는 `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate`입니다.

## 디렉터리 구조

```text
.
├── AGENTS.md
├── README.md
├── checklist.md
├── context-notes.md
├── docs/
│   └── architecture-questions.md
├── .github/
│   └── workflows/
│       └── terraform.yml
├── bootstrap/
│   └── state-backend/
│       ├── locals.tf
│       ├── main.tf
│       ├── outputs.tf
│       ├── providers.tf
│       ├── variables.tf
│       └── versions.tf
└── environments/
    ├── dev/
    │   ├── backend.tf
    │   ├── locals.tf
    │   ├── providers.tf
    │   ├── variables.tf
    │   └── versions.tf
    └── prod/
        ├── backend.tf
        ├── locals.tf
        ├── providers.tf
        ├── variables.tf
        └── versions.tf
```
