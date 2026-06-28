# AGENTS.md

## 기본 원칙

- 한국어로 작업하고, 한국어 문장은 마침표, 물음표, 느낌표로 끝낸다.
- 작업 전에 현재 파일 상태와 git 상태를 먼저 확인한다.
- 관련 파일을 실제로 읽은 뒤 편집한다.
- 변경 범위는 요청된 작업에 필요한 최소 범위로 유지한다.
- 기존 SayNow IaC의 좋은 작업 방식은 참고하되, SayNow 전용 운영 부채는 그대로 가져오지 않는다.
- 애매한 인프라 선택은 임의로 확정하지 않고 `context-notes.md`나 관련 문서에 결정 필요 항목으로 남긴다.

## 문서와 기록

- 비 trivial 작업 전에는 짧은 계획을 세우고 `checklist.md`, `context-notes.md`를 먼저 갱신한다.
- 작업 중 내린 결정, 보류한 결정, 검증 결과는 `context-notes.md`에 남긴다.
- 체크리스트는 실제 진행 상태와 맞게 갱신한다.
- 인프라 구조, 실행 절차, 검증 방법, 보안 규칙이 바뀌면 `README.md` 또는 `docs/` 하위 문서를 함께 갱신한다.

## Terraform / IaC

- Terraform 파일을 수정한 뒤에는 `terraform fmt -recursive`를 실행한다.
- 가능한 경우 `terraform validate`와 `terraform plan`으로 검증하되, backend, profile, tfvars가 미정이면 실행하지 않은 이유를 보고한다.
- `terraform plan` 없이 `terraform apply`를 실행하지 않는다.
- `terraform apply`, `terraform destroy`, 실제 AWS 리소스 생성, 변경, 삭제는 사용자 확인 후에만 실행한다.
- backend bucket, state key, AWS account가 확정되기 전에는 동작하는 `backend` block을 성급하게 만들지 않는다.
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

- 변경 후 `git diff`와 `git status --short`로 의도하지 않은 변경이 없는지 확인한다.
- 검증 명령은 최종 응답에 실제 실행한 명령과 결과를 함께 보고한다.
- 커밋 메시지는 하나의 논리 변경을 설명하는 한글 문장으로 작성한다.
