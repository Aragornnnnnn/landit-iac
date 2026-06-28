# landit-iac

Landit 서비스의 Infrastructure as Code 레포입니다.

Landit은 기존 SayNow 이전 MVP를 대체할 새 서비스로 준비 중입니다. 이 레포는 현재 초기 세팅 단계이며, 최종 인프라 구성과 아키텍처는 아직 확정되지 않았습니다.

## 현재 범위

- IaC 작업 규칙과 문서 구조를 준비한다.
- dev/prod Terraform root를 나중에 만들 수 있도록 기본 디렉터리 구조를 둔다.
- Terraform provider, version, 공통 태그, S3 backend 기준만 최소로 둔다.
- 실제 EC2, ECS, RDS, Vercel, CloudFront, Route53, SSM 리소스는 아직 만들지 않는다.
- Terraform state bucket은 bootstrap root로 생성했고, dev/prod root는 S3 backend를 사용한다.

## 기본 후보

| 항목 | 후보 |
| --- | --- |
| project name | `landit` |
| repository | `landit-iac` |
| backend repository | `landit-be` |
| frontend repository | `landit-fe` |
| AI repository | `landit-ai` |
| production SSM path | `/landit/prod` |
| development SSM path | `/landit/develop` |
| Terraform state bucket | `landit-terraform-state-982529430654` |
| production state key | `prod/landit-iac/terraform.tfstate` |
| development state key | `dev/landit-iac/terraform.tfstate` |
| AWS profile | `landit` |
| AWS region | `ap-northeast-2` |

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

## 아직 결정 필요

- dev/prod Terraform root 분리 방식과 module 공유 방식.
- backend 배포 방식.
- frontend 배포 방식.
- AI 서비스 분리 여부와 배포 방식.
- SSM Parameter Store path 최종 규칙.
- GitHub Actions OIDC IAM role과 trust policy.
- 도메인, DNS provider, TLS 종료 위치.
- VPC, subnet, database, cache, object storage, CDN, logging 구성.
- secret 주입 방식과 운영자 접근 절차.

## Terraform state backend

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

## Terraform 실행 흐름

처음 한 번은 state bucket bootstrap 계획을 확인합니다.

```bash
terraform fmt -recursive
terraform -chdir=bootstrap/state-backend init -backend=false
AWS_PROFILE=landit terraform -chdir=bootstrap/state-backend plan
```

bucket 생성에 사용자 확인을 받은 뒤에만 아래 명령을 실행합니다.

```bash
AWS_PROFILE=landit terraform -chdir=bootstrap/state-backend apply
AWS_PROFILE=landit terraform -chdir=bootstrap/state-backend init -migrate-state
```

state bucket이 생성된 뒤 dev root를 초기화합니다.

```bash
terraform fmt -recursive
AWS_PROFILE=landit terraform -chdir=environments/dev init -reconfigure
terraform -chdir=environments/dev validate
AWS_PROFILE=landit terraform -chdir=environments/dev plan
```

production root도 같은 흐름을 사용하되 `environments/prod`에서 실행합니다.

state bucket이 이미 준비되어 있으므로 dev/prod root는 S3 backend로 `terraform init`, `terraform validate`, `terraform plan`을 실행합니다.

`terraform apply`와 `terraform destroy`는 사용자 확인 없이는 실행하지 않습니다. `terraform plan` 결과를 먼저 확인한 뒤 실제 리소스 변경 여부를 명확히 보고해야 합니다.

## GitHub Actions Terraform 흐름

[`.github/workflows/terraform.yml`](.github/workflows/terraform.yml)은 수동 실행 `workflow_dispatch`만 지원합니다.

입력값은 다음과 같습니다.

- `target`: `develop`, `production` 중 하나.
- `operation`: `plan-only` 또는 `plan-and-apply`.
- `confirm_environment`: production apply를 실행할 때만 `production`을 입력한다.

필요한 GitHub 설정입니다.

- Repository variable 또는 environment variable `AWS_ROLE_ARN`에 GitHub Actions OIDC assume role ARN을 설정한다.
- `terraform-plan-develop`, `terraform-plan-production` environment를 만든다. required reviewer는 필요 없다.
- `terraform-apply-develop`, `terraform-apply-production` environment를 만들고 required reviewer를 설정한다.
- `terraform-apply-production`에는 production 담당자의 required reviewer와 prevent self-review를 설정한다.
- apply는 `refs/heads/main`에서만 허용된다.

workflow는 다음 순서로 실행됩니다.

1. 선택한 target의 Terraform root, state key, AWS account, AWS region, apply environment를 로그에 출력한다.
2. 선택한 root에서 `terraform fmt -recursive -check`, `terraform init`, `terraform validate`를 실행한다.
3. `terraform plan -out`으로 plan 파일을 만들고 plan 내용을 로그에 출력한다.
4. plan 파일을 1일 보관 artifact로 업로드한다.
5. `operation=plan-and-apply`일 때만 target별 apply environment 승인을 기다린다.
6. 승인 후 같은 plan artifact를 내려받아 `terraform apply`를 실행한다.

production apply는 `operation=plan-and-apply`, `target=production`, `confirm_environment=production`, `refs/heads/main`, `terraform-apply-production` 승인이 모두 충족되어야 실행됩니다.

`bootstrap/state-backend`는 일반 workflow target으로 노출하지 않습니다. state bucket이나 backend 정책 변경은 별도 관리자 절차로 다룹니다.

OIDC IAM role은 아직 Terraform으로 만들지 않았습니다. role trust policy는 최소한 아래 subject를 허용해야 합니다.

- `repo:Aragornnnnnn/landit-iac:environment:terraform-plan-develop`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-plan-production`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-apply-develop`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-apply-production`.

## Git 작업 흐름

일반 작업은 issue number를 먼저 정하고 `feat/{issue number}` 브랜치에서 진행합니다. 브랜치는 작업 단위를 나타내고, `develop`/`production`은 Terraform target과 state key로만 구분합니다.

환경별 브랜치인 `develop` 또는 `production` 브랜치는 만들지 않습니다. 같은 IaC 코드가 target별 root와 state에 적용되는 구조를 유지합니다.

커밋 메시지는 BE 컨벤션인 `{type}: 커밋 메시지` 형식을 사용합니다. GitHub Actions, Terraform bootstrap, 개발 환경, 설정 변경은 `ci`가 아니라 `chore` 타입을 사용합니다. 커밋은 원칙적으로 변경 30줄 이내로 끊습니다.

아키텍처 레벨 결정은 GitHub Wiki ADR로 남기고, PR에는 코드 레벨 변경과 검증 결과를 남깁니다. 문서 변경도 사람이 검토합니다.

## State와 secret

- 실제 `*.tfvars`, `*.tfplan`, Terraform state 파일은 커밋하지 않는다.
- secret 값은 Terraform state에 남기지 않는 방식을 우선 검토한다.
- SSM path 후보는 `/landit/prod`, `/landit/develop`이다.
- state key는 `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate`이다.
- bootstrap state key는 `bootstrap/state-backend/terraform.tfstate`이다.
- state bucket은 `landit-terraform-state-982529430654`이다.
- state bucket은 versioning, 기본 AES256 암호화, public access block, HTTPS-only bucket policy를 사용한다.

## SayNow 참고 범위

SayNow IaC에서 가져올 수 있는 것은 작업 흐름과 문서 구조입니다. SayNow 전용 운영값, 런타임 역전환 구조, 도메인, repository 문자열, OS user, 배포 경로, 실제 state, tfvars, plan, IP, security group id, secret 값은 Landit 기본값으로 가져오지 않습니다.
