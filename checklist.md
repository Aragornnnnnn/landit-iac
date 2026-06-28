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
- [ ] `git diff`와 `git status --short`로 변경 범위를 확인한다.

## 아키텍처 결정 전 질문

- [ ] dev/prod를 별도 Terraform root로 계속 분리할지 결정한다.
- [ ] Terraform state bucket 이름과 AWS account를 결정한다.
- [ ] Terraform state key를 `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate` 후보로 둘지 결정한다.
- [ ] AWS profile 이름과 기본 region을 결정한다.
- [ ] SSM Parameter Store path를 `/landit/prod`, `/landit/develop` 후보로 둘지 결정한다.
- [ ] backend 배포 방식을 결정한다.
- [ ] frontend 배포 방식을 결정한다.
- [ ] AI 서비스가 별도 repo와 런타임을 가질지 결정한다.
- [ ] GitHub Actions OIDC 대상 repository와 environment subject를 결정한다.
- [ ] 도메인, DNS provider, TLS 종료 위치를 결정한다.
- [ ] VPC, DB, cache, object storage, CDN 사용 여부를 결정한다.
- [ ] secret을 Terraform 밖에서 관리할 운영 절차를 결정한다.
