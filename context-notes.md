# Context Notes

## 2026-06-28 Landit IaC 초기 세팅

### 이번 초기화의 목적

- `landit-iac`는 Landit 서비스의 IaC 레포이다.
- 이번 작업은 실제 인프라를 확정하거나 배포하는 작업이 아니다.
- 목적은 앞으로 IaC 작업을 안전하게 시작할 수 있도록 문서, 작업 규칙, 최소 디렉터리 구조를 준비하는 것이다.
- EC2, ECS, RDS, Vercel, S3, CloudFront, Route53 같은 인프라 선택은 아직 결정하지 않는다.

### 현재 레포 상태

- 작업 시작 시점의 `landit-iac`는 `LICENSE`만 있는 상태였다.
- 작업 시작 시점의 `git status --short`는 출력이 없어 깨끗했다.
- 현재 브랜치는 `main`이다.

### 초기 세팅에 유지할 작업 패턴

- `AGENTS.md`, `README.md`, `checklist.md`, `context-notes.md`로 작업 규칙과 의사결정을 남기는 문서 구조는 재사용한다.
- Terraform 변경 전후에 `terraform fmt -recursive`, 가능한 validate/plan, `git diff`, `git status`로 검증하는 흐름은 재사용한다.
- 실제 `*.tfvars`, `*.tfplan`, Terraform state, secret 값은 커밋하지 않는 규칙을 재사용한다.
- dev와 prod를 별도 Terraform root로 분리할 수 있는 `environments/` 구조는 후보로 재사용한다.
- provider `default_tags`로 공통 태그를 넣는 패턴은 최소 뼈대에 반영한다.
- S3 backend와 S3 native lockfile은 Landit bucket/key 기준으로만 사용한다.
- 환경 이름은 Terraform root, state key, workflow target에서 일관되게 사용한다.
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
- `target` input은 최종적으로 `develop`, `production` 중 하나를 고른다.
- `operation=plan-only`면 plan까지만 실행한다.
- `operation=plan-and-apply`면 plan artifact를 만들고 target별 apply GitHub environment 승인을 기다린 뒤 같은 plan 파일로 apply한다.
- apply는 `refs/heads/main`에서만 허용한다.
- plan job은 `terraform-plan-develop` 또는 `terraform-plan-production` environment를 사용한다.
- apply job은 `terraform-apply-develop` 또는 `terraform-apply-production` environment를 사용한다.
- AWS 인증은 long-lived key를 workflow에 넣지 않고 GitHub OIDC를 사용한다.
- workflow는 repository variable 또는 environment variable `AWS_ROLE_ARN`을 요구한다.
- OIDC role trust policy는 target별 plan/apply environment subject를 허용해야 한다.
- 아직 GitHub Actions용 AWS IAM role은 이 Terraform 코드로 만들지 않았다.
- workflow YAML은 Ruby YAML parser로 로드에 성공했다.
- `actionlint`는 로컬에 설치되어 있지 않아 실행하지 못했다.
- `terraform fmt -recursive -check`는 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform validate`는 모두 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform plan`은 모두 `No changes`이다.
- 민감정보 패턴 검색에서 AWS access key나 secret key 문자열은 발견되지 않았다.
- `git fetch origin` 후 `origin/main...HEAD` 차이는 `0 5`였고, `git push origin main`으로 `1c6a35a..8eade66` 범위를 push했다.

## 2026-06-28 Terraform workflow 환경 명확화

- 사용자가 이번 작업은 issue number 없이 진행해도 된다고 명시했다.
- 일반 작업 규칙으로는 issue number를 요구하고 `feat/{issue number}` 브랜치에서 작업하도록 `AGENTS.md`에 남긴다.
- 환경별 브랜치는 만들지 않는다. 브랜치는 작업 단위이고, 환경은 Terraform root/state/workflow target으로 구분한다.
- 일반 Terraform workflow target에서는 bootstrap을 제거한다.
- bootstrap은 state bucket 자체를 다루는 관리자 절차이므로 일반 develop/production workflow와 섞지 않는다.
- workflow target은 `develop`, `production`만 노출한다.
- apply 실행 여부는 boolean이 아니라 `operation=plan-only` 또는 `operation=plan-and-apply`로 고른다.
- production apply는 `confirm_environment=production`, `refs/heads/main`, `terraform-apply-production` environment 승인이 모두 있어야 가능하다.
- workflow 실행 로그에는 target, operation, Terraform root, AWS account, AWS region, state bucket, state key, apply environment를 출력한다.
- workflow YAML은 Ruby YAML parser로 로드에 성공했다.
- `terraform fmt -recursive -check`는 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform validate`는 모두 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform plan`은 모두 `No changes`이다.
- `actionlint`는 로컬에 설치되어 있지 않아 실행하지 못했다.

## 2026-06-28 팀 공통 규칙 IaC 반영

- 사용자는 PR 템플릿은 추후 추가하겠다고 명시했다. 이번 작업에서는 PR 템플릿 파일을 만들지 않는다.
- Landit IaC 커밋 컨벤션은 BE 형식인 `{type}: 커밋 메시지`를 따른다.
- GitHub Actions, Terraform bootstrap, 개발 환경, 설정 변경은 `ci`가 아니라 `chore` 타입을 사용한다.
- 커밋 크기 기준은 기존 50줄 내외에서 가능하면 변경 30줄 내외로 낮춘다.
- 아키텍처 레벨 결정은 GitHub Wiki ADR로 남기고, PR에는 코드 레벨 변경과 검증 결과를 남긴다.
- 문서 변경도 사람 검토를 전제로 작성한다.
- `Initial commit`과 `ci:` 커밋 3개를 새 커밋 컨벤션에 맞게 reword했다.

## 2026-06-28 외부 참고 레포 언급 제거

- Landit IaC를 독립 레포로 보고 문서의 이전 서비스 전환 배경과 참고 범위를 제거한다.
- 작업 규칙은 Landit 자체 운영 기준으로 표현한다.
- 과거 참고 레포의 경로, 도메인, repository 문자열, OS user, 배포 경로는 문서에 남기지 않는다.

## 2026-06-28 커밋 타입 설명 보강

- 커밋 타입 이름만 있으면 판단 기준이 약하므로 `AGENTS.md`에 팀 공통 타입 설명 표를 직접 둔다.
- README는 표를 중복하지 않고 `AGENTS.md`의 커밋 타입 표를 기준으로 삼는다.

## 2026-06-28 커밋 크기 표현 조정

- 30줄 기준은 강제 제한이 아니라 가능한 기준으로 둔다.
- 커밋은 논리 단위로 작게 나누고, PR은 사람이 리뷰 가능한 크기로 유지한다.
