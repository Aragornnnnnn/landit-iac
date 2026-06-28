# landit-iac

Landit 서비스의 Infrastructure as Code 레포입니다.

Landit은 기존 SayNow 이전 MVP를 대체할 새 서비스로 준비 중입니다. 이 레포는 현재 초기 세팅 단계이며, 최종 인프라 구성과 아키텍처는 아직 확정되지 않았습니다.

## 현재 범위

- IaC 작업 규칙과 문서 구조를 준비한다.
- dev/prod Terraform root를 나중에 만들 수 있도록 기본 디렉터리 구조를 둔다.
- Terraform provider, version, 공통 태그 후보만 최소로 둔다.
- 실제 EC2, ECS, RDS, Vercel, S3, CloudFront, Route53, SSM 리소스는 아직 만들지 않는다.
- backend 설정은 bucket과 key가 확정되기 전까지 문서 후보로만 남긴다.

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
| production state key | `prod/landit-iac/terraform.tfstate` |
| development state key | `dev/landit-iac/terraform.tfstate` |

## 디렉터리 구조

```text
.
├── AGENTS.md
├── README.md
├── checklist.md
├── context-notes.md
├── docs/
│   └── architecture-questions.md
└── environments/
    ├── dev/
    │   ├── locals.tf
    │   ├── providers.tf
    │   ├── variables.tf
    │   └── versions.tf
    └── prod/
        ├── locals.tf
        ├── providers.tf
        ├── variables.tf
        └── versions.tf
```

## 아직 결정 필요

- AWS account, AWS profile, region.
- Terraform state bucket 이름과 bootstrap 방식.
- dev/prod Terraform root 분리 방식과 module 공유 방식.
- backend 배포 방식.
- frontend 배포 방식.
- AI 서비스 분리 여부와 배포 방식.
- SSM Parameter Store path 최종 규칙.
- GitHub Actions OIDC owner, repository, environment subject.
- 도메인, DNS provider, TLS 종료 위치.
- VPC, subnet, database, cache, object storage, CDN, logging 구성.
- secret 주입 방식과 운영자 접근 절차.

## 예비 Terraform 흐름

현재는 backend block과 실제 리소스를 만들지 않았습니다. 아래 흐름은 Terraform root가 구체화된 뒤 사용할 예비 흐름입니다.

```bash
terraform fmt -recursive
terraform -chdir=environments/dev init -backend=false
terraform -chdir=environments/dev validate
terraform -chdir=environments/dev plan -out=dev-landit.tfplan
```

production root도 같은 흐름을 사용하되 `environments/prod`에서 실행합니다.

`terraform apply`와 `terraform destroy`는 사용자 확인 없이는 실행하지 않습니다. `terraform plan` 결과를 먼저 확인한 뒤 실제 리소스 변경 여부를 명확히 보고해야 합니다.

## State와 secret

- 실제 `*.tfvars`, `*.tfplan`, Terraform state 파일은 커밋하지 않는다.
- secret 값은 Terraform state에 남기지 않는 방식을 우선 검토한다.
- SSM path 후보는 `/landit/prod`, `/landit/develop`이다.
- state key 후보는 `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate`이다.
- state bucket 이름, AWS account, lock 방식은 아직 확정 전이다.

## SayNow 참고 범위

SayNow IaC에서 가져올 수 있는 것은 작업 흐름과 문서 구조입니다. SayNow 전용 운영값, 런타임 역전환 구조, 도메인, repository 문자열, OS user, 배포 경로, 실제 state, tfvars, plan, IP, security group id, secret 값은 Landit 기본값으로 가져오지 않습니다.
