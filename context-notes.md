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

- AWS account, AWS profile, region.
- Terraform state bucket 이름과 bootstrap 방식.
- dev/prod Terraform root를 완전히 분리할지, module을 공유할지.
- backend, frontend, AI의 실제 배포 방식.
- 도메인과 DNS provider.
- GitHub Actions OIDC owner/repository/environment subject.
- VPC, subnet, database, cache, object storage, CDN, logging 구성.
- SSM Parameter Store path를 후보값 그대로 사용할지.
- secret 주입 방식과 운영자 접근 절차.
