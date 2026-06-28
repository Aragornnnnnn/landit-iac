# AGENTS.md

## 기본 원칙

- 한국어로 작업하고, 한국어 문장은 마침표, 물음표, 느낌표로 끝낸다.
- 작업 전에 현재 파일 상태와 git 상태를 먼저 확인한다.
- 관련 파일을 실제로 읽은 뒤 편집한다.
- 변경 범위는 요청된 작업에 필요한 최소 범위로 유지한다.
- Landit 독립 레포 기준으로 문서와 설정을 유지한다.
- 애매한 인프라 선택은 임의로 확정하지 않고 `context-notes.md`나 관련 문서에 결정 필요 항목으로 남긴다.

## 문서와 기록

- 비 trivial 작업 전에는 짧은 계획을 세우고 `checklist.md`, `context-notes.md`를 먼저 갱신한다.
- 작업 중 내린 결정, 보류한 결정, 검증 결과는 `context-notes.md`에 남긴다.
- 체크리스트는 실제 진행 상태와 맞게 갱신한다.
- 인프라 구조, 실행 절차, 검증 방법, 보안 규칙이 바뀌면 `README.md` 또는 `docs/` 하위 문서를 함께 갱신한다.
- 아키텍처 레벨 결정은 GitHub Wiki ADR에 정리하고, PR에는 코드 레벨 변경과 검증 결과를 남긴다.
- 문서화 내용도 사람 검토를 전제로 작성한다.

## Terraform / IaC

- Terraform 파일을 수정한 뒤에는 `terraform fmt -recursive`를 실행한다.
- 가능한 경우 `terraform validate`와 `terraform plan`으로 검증하되, backend, profile, tfvars가 미정이면 실행하지 않은 이유를 보고한다.
- `terraform plan` 없이 `terraform apply`를 실행하지 않는다.
- `terraform apply`, `terraform destroy`, 실제 AWS 리소스 생성, 변경, 삭제는 사용자 확인 후에만 실행한다.
- GitHub Actions apply는 `terraform-apply-develop` 또는 `terraform-apply-production` environment required reviewer 승인 뒤에만 실행한다.
- 일반 Terraform workflow는 `develop`과 `production` target만 노출하고, bootstrap 작업은 일반 workflow에서 실행하지 않는다.
- AWS profile은 `landit`, 기본 region은 `ap-northeast-2`, AWS account는 `982529430654`를 기준으로 한다.
- Terraform state bucket은 `landit-terraform-state-982529430654`를 사용한다.
- production state key는 `prod/landit-iac/terraform.tfstate`, development state key는 `dev/landit-iac/terraform.tfstate`를 사용한다.
- bootstrap state key는 `bootstrap/state-backend/terraform.tfstate`를 사용한다.
- state bucket은 `bootstrap/state-backend`에서 별도 bootstrap하고, bucket 생성 전 dev/prod 검증은 `terraform init -backend=false`로 제한한다.
- 실제 `*.tfvars`, `*.tfplan`, Terraform state, secret 값, 접근 키, IP, security group id는 커밋하지 않는다.
- secret 값은 Terraform state에 남기지 않는 방식을 우선 검토한다.
- SSM Parameter Store path 후보는 `/landit/prod`, `/landit/develop`이며 확정 전까지 문서에 결정 필요로 표시한다.
- `resource_name_environment`처럼 환경 표시 이름을 뒤집는 구조는 Landit 기본 패턴으로 사용하지 않는다.

## 파일 작성 규칙

- 새 source 파일 첫 줄에는 파일 역할을 설명하는 한 줄짜리 한국어 주석을 넣는다.
- 필수 directive, shebang, generated marker가 있으면 그 바로 아래에 역할 주석을 둔다.
- config 파일, lockfile, generated file에는 역할 주석 규칙을 적용하지 않는다.
- 기존 파일의 무관한 포맷, 주석, 구조는 바꾸지 않는다.

## Git / 검증

- 작업에는 issue number가 필요하며, 없으면 사용자에게 issue number를 요청한다.
- 작업 브랜치는 `feat/{issue number}` 형식으로 만들고, 환경별 브랜치 이름을 만들지 않는다.
- 변경 후 `git diff`와 `git status --short`로 의도하지 않은 변경이 없는지 확인한다.
- 검증 명령은 최종 응답에 실제 실행한 명령과 결과를 함께 보고한다.
- 커밋 메시지는 BE 컨벤션인 `{type}: 커밋 메시지` 형식을 사용한다.
- 커밋 타입은 아래 표를 기준으로 판단한다.

| Tag | 설명 |
| --- | --- |
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `refactor` | 동작은 그대로, 코드 구조와 가독성 개선 |
| `docs` | 문서 수정 |
| `comment` | 주석 추가 및 변경 |
| `chore` | 빌드, 패키지 매니저, 환경 설정 등 개발 환경 관련, 의존성 추가 |
| `deploy` | 빌드 및 배포 작업 |
| `test` | 테스트 코드 추가 및 수정 |
| `rename` | 파일 또는 폴더명 변경 |
| `remove` | 파일 삭제만 한 경우 |

- GitHub Actions, Terraform bootstrap, 개발 환경, 설정 변경은 `ci`가 아니라 `chore`를 사용한다.
- 커밋 메시지는 무엇을 왜 또는 어떻게 바꿨는지 한국어로 설명하고, 단순 나열로 쓰지 않는다.
- 타입 선택이 애매하면 변경 내용을 설명하고 사용자에게 확인한다.
- 커밋은 원칙적으로 변경 30줄 이내로 끊고, 한 커밋에 여러 논리 변경을 섞지 않는다.
- PR은 이슈 단위로 만들고, 제목은 이슈 제목을 따른다.
