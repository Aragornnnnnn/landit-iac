# Context Notes

## 2026-06-28 Landit IaC 초기 세팅

### 이번 초기화의 목적

- `landit-iac`는 SayNow 이전 MVP를 대체할 Landit 서비스의 IaC 레포 후보이다.
- 이번 작업은 실제 인프라를 확정하거나 배포하는 작업이 아니다.
- 목적은 앞으로 IaC 작업을 안전하게 시작할 수 있도록 문서, 작업 규칙, 최소 디렉터리 구조를 준비하는 것이다.
- EC2, ECS, RDS, Vercel, S3, CloudFront, Route53 같은 인프라 선택은 아직 결정하지 않는다.

### 현재 레포 상태

- 작업 시작 시점의 `landit-iac`는 `LICENSE`만 있는 상태였다.
- 작업 시작 시점의 `git status --short`는 출력이 없어 깨끗했다.
- 현재 브랜치는 `main`이다.

### SayNow에서 재사용할 패턴

- `AGENTS.md`, `README.md`, `checklist.md`, `context-notes.md`로 작업 규칙과 의사결정을 남기는 문서 구조는 재사용한다.
- Terraform 변경 전후에 `terraform fmt -recursive`, 가능한 validate/plan, `git diff`, `git status`로 검증하는 흐름은 재사용한다.
- 실제 `*.tfvars`, `*.tfplan`, Terraform state, secret 값은 커밋하지 않는 규칙을 재사용한다.
- dev와 prod를 별도 Terraform root로 분리할 수 있는 `environments/` 구조는 후보로 재사용한다.
- provider `default_tags`로 공통 태그를 넣는 패턴은 최소 뼈대에 반영한다.
- S3 backend와 S3 native lockfile 사용 경험은 참고하되, Landit bucket/key가 확정되기 전에는 backend block을 만들지 않는다.

### SayNow에서 가져오지 않을 패턴

- `resource_name_environment`로 Terraform root 이름과 AWS 콘솔 표시 이름을 분리하거나 뒤집는 구조는 Landit 기본값으로 가져오지 않는다.
- `/saynow/*` SSM path는 Landit 후보인 `/landit/prod`, `/landit/develop`으로 바꾼다.
- `saynow.p-e.kr`, `dev-saynow.p-e.kr` 도메인은 Landit 기본값으로 가져오지 않는다.
- `Aragornnnnnn/saynow-be`, `Aragornnnnnn/saynow-fe`, `Aragornnnnnn/saynow-ai` repository 문자열은 Landit 후보 repo 이름으로 바꾼다.
- `/opt/saynow`, `saynow` OS user, SayNow systemd service 이름은 Landit 기본값으로 가져오지 않는다.
- 실제 `*.tfvars`, `*.tfplan`, Terraform state, security group id, IP, secret 값은 복사하지 않는다.
- `terraform apply`, `terraform destroy`, AWS 리소스 생성, 변경, 삭제는 실행하지 않는다.

### Landit 기본 네이밍 후보

| 항목 | 후보 |
| --- | --- |
| project name | `landit` |
| repository | `landit-iac` |
| backend repo | `landit-be` |
| frontend repo | `landit-fe` |
| AI repo | `landit-ai` |
| production SSM path | `/landit/prod` |
| development SSM path | `/landit/develop` |
| production state key | `prod/landit-iac/terraform.tfstate` |
| development state key | `dev/landit-iac/terraform.tfstate` |

### 아직 결정하지 않은 사항

- dev/prod Terraform root를 완전히 분리할지, module을 공유할지.
- backend, frontend, AI의 실제 배포 방식.
- 도메인과 DNS provider.
- GitHub Actions OIDC owner/repository/environment subject.
- VPC, subnet, database, cache, object storage, CDN, logging 구성.
- SSM Parameter Store path를 후보값 그대로 사용할지.
- secret 주입 방식과 운영자 접근 절차.

## 2026-06-28 S3 backend 구성

### 확인한 기준

- `landit` AWS profile은 STS 기준 account `982529430654`, IAM user `arn:aws:iam::982529430654:user/sm-iac`이다.
- 기본 AWS region은 `ap-northeast-2`로 둔다.
- S3 backend bucket 이름은 account id를 포함해 `landit-terraform-state-982529430654`로 둔다.
- bootstrap state key는 `bootstrap/state-backend/terraform.tfstate`로 둔다.
- production state key는 `prod/landit-iac/terraform.tfstate`로 둔다.
- development state key는 `dev/landit-iac/terraform.tfstate`로 둔다.
- S3 backend locking은 Terraform S3 backend의 `use_lockfile = true`를 사용한다.

### 현재 AWS 상태

- `aws s3api head-bucket --bucket landit-terraform-state-982529430654 --profile landit` 결과는 `404 Not Found`이다.
- 따라서 backend block을 바로 활성화한 `terraform init`은 bucket 생성 전까지 성공할 수 없다.
- 실제 S3 bucket 생성은 AWS 리소스 생성이므로 사용자 확인 전까지 실행하지 않는다.

### 구현 방향

- `bootstrap/state-backend`는 로컬 state로 실행해 S3 state bucket 자체를 만들기 위한 별도 root로 둔다.
- dev/prod root에는 S3 backend block을 미리 추가한다.
- bucket 생성 전 dev/prod 검증은 `terraform validate`까지만 가능하다.
- bucket 생성 후에는 dev/prod root에서 `terraform init -reconfigure`로 S3 backend를 활성화한다.

### 검증 결과

- `bootstrap/state-backend` root의 `terraform init -backend=false`는 성공했다.
- `bootstrap/state-backend` root의 `AWS_PROFILE=landit terraform plan`은 `5 to add, 0 to change, 0 to destroy`로 성공했다.
- plan 생성 대상은 S3 bucket, public access block, versioning, AES256 기본 암호화, HTTPS-only bucket policy이다.
- dev/prod root의 `terraform init -backend=false -reconfigure`와 `terraform validate`는 성공했다.
- dev/prod root의 `terraform plan`은 S3 backend가 아직 초기화되지 않아 `Backend initialization required` 오류로 중단됐다.
- 이 오류는 state bucket이 아직 생성되지 않은 현재 단계에서는 예상 가능한 제한이다.

## 2026-06-28 S3 backend apply

- 사용자 요청에 따라 `bootstrap/state-backend` plan 파일을 만들고 apply했다.
- apply 결과는 `5 added, 0 changed, 0 destroyed`이다.
- 생성된 리소스는 S3 bucket, public access block, versioning, AES256 기본 암호화, HTTPS-only bucket policy이다.
- S3 bucket `landit-terraform-state-982529430654`는 `ap-northeast-2`에 생성됐다.
- bucket versioning은 `Enabled`이다.
- public access block은 `BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`가 모두 `true`이다.
- 기본 서버 측 암호화는 `AES256`이다.
- apply 후 bootstrap root plan은 `No changes`이다.
- dev/prod root의 S3 backend 초기화는 성공했고, 두 root 모두 plan 결과는 `No changes`이다.
- dev/prod root는 아직 실제 리소스가 없어 S3 state object가 생성되지 않았다.
- bootstrap root state도 S3 backend로 마이그레이션했다.
- S3 object `bootstrap/state-backend/terraform.tfstate`가 생성된 것을 확인했다.
- migration 후 bootstrap root의 `terraform validate`와 `terraform plan`은 모두 성공했고 plan 결과는 `No changes`이다.

## 2026-06-28 GitHub Actions Terraform workflow

- remote는 `origin https://github.com/Aragornnnnnn/landit-iac.git`이다.
- 현재 branch는 `main`이고 작업 시작 시점의 `git status --short`는 깨끗했다.
- workflow는 `.github/workflows/terraform.yml`에 둔다.
- workflow trigger는 자동 push apply를 피하기 위해 `workflow_dispatch`만 사용한다.
- `target` input은 `bootstrap-state-backend`, `dev`, `prod` 중 하나를 고른다.
- `apply=false`면 plan까지만 실행한다.
- `apply=true`면 plan artifact를 만들고 `terraform-apply` GitHub environment 승인을 기다린 뒤 같은 plan 파일로 apply한다.
- apply는 `refs/heads/main`에서만 허용한다.
- plan job은 `terraform-plan` environment를 사용하고, apply job은 `terraform-apply` environment를 사용한다.
- AWS 인증은 long-lived key를 workflow에 넣지 않고 GitHub OIDC를 사용한다.
- workflow는 repository variable 또는 environment variable `AWS_ROLE_ARN`을 요구한다.
- OIDC role trust policy는 `repo:Aragornnnnnn/landit-iac:environment:terraform-plan`과 `repo:Aragornnnnnn/landit-iac:environment:terraform-apply` subject를 허용해야 한다.
- 아직 GitHub Actions용 AWS IAM role은 이 Terraform 코드로 만들지 않았다.
- workflow YAML은 Ruby YAML parser로 로드에 성공했다.
- `actionlint`는 로컬에 설치되어 있지 않아 실행하지 못했다.
- `terraform fmt -recursive -check`는 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform validate`는 모두 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform plan`은 모두 `No changes`이다.
- 민감정보 패턴 검색에서 AWS access key나 secret key 문자열은 발견되지 않았다.
- `git fetch origin` 후 `origin/main...HEAD` 차이는 `0 5`였고, `git push origin main`으로 `1c6a35a..8eade66` 범위를 push했다.
