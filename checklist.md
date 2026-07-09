# Checklist

## 2026-06-28 Landit IaC 초기 세팅

- [x] 현재 `landit-iac` 레포 파일 상태를 확인한다.
- [x] 현재 `landit-iac` git 상태를 확인한다.
- [x] 기존 IaC 문서 구조와 Terraform 기본 패턴을 확인한다.
- [x] Landit에 필요한 초기 작업 규칙과 보류할 인프라 결정을 분리한다.
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
- [x] 커밋 크기 기준을 가능하면 변경 30줄 내외로 기록한다.
- [x] 아키텍처 레벨 결정은 GitHub Wiki ADR로 남기도록 기록한다.
- [x] 문서 변경도 사람 검토 대상임을 기록한다.
- [x] 기존 커밋 메시지를 새 컨벤션에 맞게 reword한다.
- [x] 변경 검증과 push를 완료한다.

## 2026-06-28 외부 참고 레포 언급 제거

- [x] Landit 독립 레포 기준으로 기본 원칙을 정리한다.
- [x] README에서 이전 서비스 전환 배경과 참고 범위를 제거한다.
- [x] 초기화 기록에서 외부 레포 이름과 운영값을 제거한다.
- [x] 변경 검증과 push를 완료한다.

## 2026-06-28 커밋 타입 설명 보강

- [x] `AGENTS.md`에 커밋 타입별 의미 표를 추가한다.
- [x] README에서 `AGENTS.md`의 커밋 타입 표를 따르도록 연결한다.
- [x] 변경 검증과 push를 완료한다.

## 2026-06-28 커밋 크기 표현 조정

- [x] 30줄 기준을 강제 표현이 아니라 가능한 기준으로 조정한다.
- [x] 논리 단위 커밋과 리뷰 가능한 PR 크기 기준을 함께 기록한다.
- [x] 변경 검증과 push를 완료한다.

## 2026-06-28 README 가독성 개선

- [x] README를 처음 읽는 사람이 현재 상태를 먼저 파악하도록 재구성한다.
- [x] Terraform local 실행과 GitHub Actions 실행 흐름을 분리한다.
- [x] Git 작업 규칙, state와 secret, 결정 필요 항목을 독립 섹션으로 정리한다.
- [x] 변경 검증과 push를 완료한다.

## 2026-06-28 README와 개발자 문서 분리

- [x] README에는 레포 상태, 문서 링크, 기본 값, 범위, 주요 경로만 남긴다.
- [x] 개발자용 Terraform 실행, GitHub Actions, Git 작업 흐름은 별도 문서로 분리한다.
- [x] README에서 개발자용 문서로 링크한다.
- [x] 변경 검증과 push를 완료한다.

## 2026-06-28 Landit SSM Parameter Store 초기 작성

- [x] `landit` AWS profile과 account를 확인한다.
- [x] 기존 `/landit/develop`, `/landit/prod` parameter가 비어 있음을 확인한다.
- [x] development runtime parameter 7개를 작성한다.
- [x] production runtime parameter 7개를 작성한다.
- [x] secret 값은 출력하거나 파일에 저장하지 않는다.
- [x] parameter name, type, version만 조회해 반영 상태를 검증한다.
- [x] SSM parameter registry 문서를 추가한다.

## 2026-06-28 SSM DB_URL JDBC 형식 수정

- [x] 기존 `DB_URL`이 Java JDBC용으로 부적합한 `postgresql://` 형식임을 확인한다.
- [x] develop `DB_URL`을 credential 없는 `jdbc:postgresql://` 형식으로 갱신한다.
- [x] prod `DB_URL`을 credential 없는 `jdbc:postgresql://` 형식으로 갱신한다.
- [x] `DB_USERNAME`, `DB_PASSWORD`는 기존 SecureString parameter로 유지한다.
- [x] parameter name, type, version만 조회해 반영 상태를 검증한다.
- [x] SSM parameter 문서에 DB URL 형식 규칙을 기록한다.

## 2026-07-07 develop API ECS health check grace period 수정

- [x] 현재 `develop-landit-api` ECS service 설정을 확인한다.
- [x] health check grace period를 180초로 수정한다.
- [x] 수정 후 ECS service 설정을 확인한다.
- [x] target group health를 확인한다.

## 2026-07-09 BE와 AI ALB 라우팅 구성

- [x] 이번 작업은 사용자 요청에 따라 issue number 없이 진행한다.
- [x] 현재 git 상태와 기존 미커밋 문서 변경을 확인한다.
- [x] live develop Terraform state와 현재 checkout의 차이를 확인한다.
- [x] `feat/LAN-45`의 app platform Terraform 코드를 현재 작업 브랜치로 가져온다.
- [x] develop ALB에 AI target group과 host rule을 추가한다.
- [x] prod ALB와 BE, AI target group, HTTPS listener 구성을 추가한다.
- [x] BE API task에 AI client SSM parameter 주입 구성을 추가한다.
- [x] wildcard ACM 인증서를 요청하고 Vercel DNS 검증 record를 확인한다.
- [x] develop과 prod SSM에 AI client parameter를 추가한다.
- [x] SSM parameter registry와 작업 문서를 갱신한다.
- [x] `terraform fmt -recursive`를 실행한다.
- [x] develop과 prod Terraform validate를 실행한다.
- [x] 가능한 범위에서 Terraform plan을 확인한다.
- [x] develop Terraform plan을 apply한다.
- [x] develop ALB listener rule, ECS service, target health, 외부 HTTPS health check를 검증한다.
- [x] prod Terraform plan을 apply한다.
- [x] prod ALB listener rule과 Terraform state 정합성을 검증한다.
- [x] prod API host를 `api.landit.im`으로 정정한다.
- [x] 잘못 요청한 `api-landit.im` pending ACM 인증서를 삭제한다.
- [x] Vercel에 추가한 prod `api`, `ai` CNAME의 DNS resolve와 HTTPS ALB 응답을 검증한다.
- [x] prod ECR에 BE와 AI image를 push한 뒤 ECS service와 target health를 검증한다.
- [x] Vercel DNS에 등록할 `Name`, `Type`, `Value`, `Comment`를 정리한다.
- [x] `git diff`와 `git status --short`로 변경 범위를 확인한다.

## 2026-07-09 Auth token 만료시간 SSM 추가

- [x] 현재 git 상태와 관련 문서를 확인한다.
- [x] 기존 `LANDIT_AUTH_TOKEN_*` parameter 등록 상태를 값 없이 확인한다.
- [x] develop SSM에 access token, refresh token 만료시간 parameter를 작성한다.
- [x] prod SSM에 access token, refresh token 만료시간 parameter를 작성한다.
- [x] parameter name, type, version만 조회해 반영 상태를 검증한다.
- [x] SSM parameter registry와 작업 기록을 갱신한다.
- [x] `git diff`와 `git status --short`로 변경 범위를 확인한다.

## 2026-07-09 prod GitHub Actions 배포 설정

- [x] landit-ai prod worker deploy 실패 로그를 확인한다.
- [x] landit-be prod api deploy 실패 로그를 확인한다.
- [x] 실패 원인이 GitHub Actions 배포 변수 누락임을 확인한다.
- [x] prod GitHub Actions OIDC IAM role을 생성한다.
- [x] prod deploy role에 ECR push, ECS update, prod DB SSM read 권한을 추가한다.
- [x] landit-be prod environment variables를 설정한다.
- [x] landit-ai repository variables를 설정한다.
- [x] role trust policy와 GitHub variables 반영 상태를 검증한다.

## 아키텍처 결정 전 질문

- [ ] dev/prod를 별도 Terraform root로 계속 분리할지 결정한다.
- [x] Terraform state bucket 이름과 AWS account를 결정한다.
- [x] Terraform state key를 `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate` 후보로 둘지 결정한다.
- [x] AWS profile 이름과 기본 region을 결정한다.
- [x] SSM Parameter Store path를 `/landit/prod`, `/landit/develop`로 사용한다.
- [ ] backend 배포 방식을 결정한다.
- [ ] frontend 배포 방식을 결정한다.
- [ ] AI 서비스가 별도 repo와 런타임을 가질지 결정한다.
- [x] GitHub Actions OIDC 대상 repository와 environment subject를 결정한다.
- [ ] 도메인, DNS provider, TLS 종료 위치를 결정한다.
- [ ] VPC, DB, cache, object storage, CDN 사용 여부를 결정한다.
- [x] 초기 secret은 Terraform 밖에서 SSM에 작성한다.
- [ ] secret rotation, 접근 권한, 감사 절차를 결정한다.
