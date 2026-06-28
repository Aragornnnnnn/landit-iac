# landit-iac

Landit 서비스의 Infrastructure as Code 레포입니다.

Landit은 기존 SayNow 이전 MVP를 대체할 새 서비스로 준비 중입니다. 이 레포는 현재 초기 세팅 단계이며, 최종 인프라 구성과 아키텍처는 아직 확정되지 않았습니다.

## 현재 범위

- IaC 작업 규칙과 문서 구조를 준비한다.
- dev/prod Terraform root를 나중에 만들 수 있도록 기본 디렉터리 구조를 둔다.
- Terraform provider, version, 공통 태그, S3 backend 기준만 최소로 둔다.
- 실제 EC2, ECS, RDS, Vercel, CloudFront, Route53, SSM 리소스는 아직 만들지 않는다.
- Terraform state bucket은 bootstrap root로 준비하되, 사용자 확인 전까지 실제 생성하지 않는다.

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
- GitHub Actions OIDC owner, repository, environment subject.
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

현재 `aws s3api head-bucket --bucket landit-terraform-state-982529430654 --profile landit` 결과는 `404 Not Found`입니다. bucket 생성은 `bootstrap/state-backend` root로 별도 진행하며, 사용자 확인 전에는 `terraform apply`를 실행하지 않습니다.

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

state bucket이 아직 없으면 dev/prod root의 `terraform plan`은 `Backend initialization required` 또는 backend 초기화 오류로 중단될 수 있습니다. 이 단계에서는 `terraform validate`와 bootstrap root의 `terraform plan`까지만 검증합니다.

`terraform apply`와 `terraform destroy`는 사용자 확인 없이는 실행하지 않습니다. `terraform plan` 결과를 먼저 확인한 뒤 실제 리소스 변경 여부를 명확히 보고해야 합니다.

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
