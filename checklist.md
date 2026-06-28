# Checklist

## 2026-06-28 Landit IaC 초기 세팅

- [x] 현재 `landit-iac` 레포 파일 상태를 확인한다.
- [x] 현재 `landit-iac` git 상태를 확인한다.
- [x] `/Users/sangmin8817/Soma/saynow-iac`의 문서 구조와 Terraform 기본 패턴을 확인한다.
- [x] SayNow 특수 운영 부채와 Landit 재사용 후보를 분리한다.
- [x] 작업 전 짧은 계획을 세운다.
- [x] `checklist.md`를 만든다.
- [x] `context-notes.md`를 만든다.
- [x] `AGENTS.md`에 Landit IaC 작업 규칙을 기록한다.
- [x] `README.md`에 초기 세팅 단계와 아키텍처 미정 상태를 기록한다.
- [x] `.gitignore`에 Terraform state, plan, tfvars, override, crash log, `.terraform/`, `.DS_Store` 제외 규칙을 추가한다.
- [x] `docs/architecture-questions.md`에 아키텍처 결정 전 질문을 정리한다.
- [x] `environments/dev`와 `environments/prod`에 최소 Terraform root 후보 구조를 만든다.
- [x] `terraform fmt -recursive`를 실행한다.
- [x] `terraform fmt -recursive -check`를 실행한다.
- [x] `git diff`와 `git status --short`로 변경 범위를 확인한다.

## 2026-06-28 S3 backend 구성

- [x] `landit` AWS profile의 계정과 IAM user를 확인한다.
- [x] S3 backend bucket 후보 `landit-terraform-state-982529430654`의 존재 여부를 확인한다.
- [x] bucket이 아직 없으므로 실제 생성 없이 bootstrap Terraform root로 준비한다.
- [x] `bootstrap/state-backend`에 state bucket 리소스 뼈대를 추가한다.
- [x] `environments/dev/backend.tf`에 S3 backend block을 추가한다.
- [x] `environments/prod/backend.tf`에 S3 backend block을 추가한다.
- [x] `README.md`, `AGENTS.md`, `docs/architecture-questions.md`에 S3 backend 기준을 반영한다.
- [x] `terraform fmt -recursive`를 실행한다.
- [x] bootstrap root `terraform init`과 `terraform plan`을 실행한다.
- [x] dev/prod root `terraform validate`를 실행한다.
- [x] dev/prod root `terraform plan`이 backend 초기화 전에는 실행되지 않는 것을 확인한다.
- [x] 실제 S3 bucket 생성은 사용자 확인 전까지 실행하지 않는다.
- [x] `git diff`와 `git status --short`로 변경 범위를 확인한다.

## 2026-06-28 S3 backend apply

- [x] bootstrap root plan 파일을 생성한다.
- [x] bootstrap root plan 파일을 apply한다.
- [x] S3 bucket 생성 상태를 확인한다.
- [x] bucket versioning을 확인한다.
- [x] bucket public access block을 확인한다.
- [x] bucket 기본 암호화 설정을 확인한다.
- [x] bootstrap root no-change plan을 확인한다.
- [x] dev/prod root S3 backend init을 실행한다.
- [x] dev/prod root validate를 실행한다.
- [x] dev/prod root plan이 `No changes`임을 확인한다.
- [x] bootstrap root state를 S3 backend로 마이그레이션한다.
- [x] 작업 기록 문서를 갱신한다.
- [x] `git diff`와 `git status --short`로 변경 범위를 확인한다.

## 2026-06-28 GitHub Actions Terraform workflow

- [x] 현재 branch와 remote를 확인한다.
- [x] workflow 구조를 plan 후 environment approval apply 방식으로 정한다.
- [x] `.github/workflows/terraform.yml`을 추가한다.
- [x] workflow가 장기 AWS key 대신 OIDC role ARN 변수 `AWS_ROLE_ARN`을 사용하도록 한다.
- [x] apply가 `refs/heads/main`에서만 가능하도록 제한한다.
- [x] README에 workflow 실행 조건과 GitHub environment 설정을 기록한다.
- [x] context-notes에 workflow 결정 사항을 기록한다.
- [x] workflow YAML 문법과 Terraform 검증을 실행한다.
- [x] 변경 내용을 커밋한다.
- [x] `main`을 `origin/main`으로 push한다.

## 2026-06-28 Terraform workflow 환경 명확화

- [x] 이번 작업은 사용자가 issue number 예외를 명시했음을 확인한다.
- [x] 일반 workflow에서 bootstrap target을 제거한다.
- [x] workflow target을 `develop`, `production`으로 명확히 바꾼다.
- [x] apply boolean을 `plan-only`, `plan-and-apply` operation으로 바꾼다.
- [x] production apply에 `confirm_environment=production` 입력을 요구한다.
- [x] apply environment를 `terraform-apply-develop`, `terraform-apply-production`으로 분리한다.
- [x] README와 architecture questions를 새 workflow 기준으로 갱신한다.
- [x] AGENTS.md에 issue number와 `feat/{issue number}` 브랜치 규칙을 명시한다.
- [x] workflow YAML 문법과 Terraform 검증을 실행한다.
- [x] 변경 내용을 커밋한다.
- [x] `main`을 `origin/main`으로 push한다.

## 2026-06-28 팀 공통 규칙 IaC 반영

- [x] PR 템플릿은 이번 작업에서 추가하지 않는 것으로 정한다.
- [x] 커밋 컨벤션을 BE 형식인 `{type}: 커밋 메시지`로 정한다.
- [x] GitHub Actions와 설정 변경은 `ci`가 아니라 `chore`를 쓰도록 기록한다.
- [x] 커밋 크기 기준을 변경 30줄 이내로 기록한다.
- [x] 아키텍처 레벨 결정은 GitHub Wiki ADR로 남기도록 기록한다.
- [x] 문서 변경도 사람 검토 대상임을 기록한다.
- [x] 기존 커밋 메시지를 새 컨벤션에 맞게 reword한다.
- [x] 변경 검증과 push를 완료한다.

## 아키텍처 결정 전 질문

- [ ] dev/prod를 별도 Terraform root로 계속 분리할지 결정한다.
- [x] Terraform state bucket 이름과 AWS account를 결정한다.
- [x] Terraform state key를 `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate` 후보로 둘지 결정한다.
- [x] AWS profile 이름과 기본 region을 결정한다.
- [ ] SSM Parameter Store path를 `/landit/prod`, `/landit/develop` 후보로 둘지 결정한다.
- [ ] backend 배포 방식을 결정한다.
- [ ] frontend 배포 방식을 결정한다.
- [ ] AI 서비스가 별도 repo와 런타임을 가질지 결정한다.
- [x] GitHub Actions OIDC 대상 repository와 environment subject를 결정한다.
- [ ] 도메인, DNS provider, TLS 종료 위치를 결정한다.
- [ ] VPC, DB, cache, object storage, CDN 사용 여부를 결정한다.
- [ ] secret을 Terraform 밖에서 관리할 운영 절차를 결정한다.
