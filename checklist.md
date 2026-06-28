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

## 아키텍처 결정 전 질문

- [ ] dev/prod를 별도 Terraform root로 계속 분리할지 결정한다.
- [x] Terraform state bucket 이름과 AWS account를 결정한다.
- [x] Terraform state key를 `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate` 후보로 둘지 결정한다.
- [x] AWS profile 이름과 기본 region을 결정한다.
- [ ] SSM Parameter Store path를 `/landit/prod`, `/landit/develop` 후보로 둘지 결정한다.
- [ ] backend 배포 방식을 결정한다.
- [ ] frontend 배포 방식을 결정한다.
- [ ] AI 서비스가 별도 repo와 런타임을 가질지 결정한다.
- [ ] GitHub Actions OIDC 대상 repository와 environment subject를 결정한다.
- [ ] 도메인, DNS provider, TLS 종료 위치를 결정한다.
- [ ] VPC, DB, cache, object storage, CDN 사용 여부를 결정한다.
- [ ] secret을 Terraform 밖에서 관리할 운영 절차를 결정한다.
