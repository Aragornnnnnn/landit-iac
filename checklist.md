# Checklist

## 2026-07-22 LAN-192 prod 관측성과 Discord 장애 알림

- [x] Sentry relay를 ingress와 비동기 delivery로 분리하고 HMAC 검증 테스트를 통과한다.
- [x] AI 로그가 실제 `WARNING`, `ERROR` 레벨을 보존하도록 수정하고 전체 테스트를 통과한다.
- [x] BE 로그가 Spring 기본 포맷에서 실제 레벨을 보존하는지 확인한다.
- [x] Grafana AI·Overview 에러 패널을 실제 레벨 기반으로 변경한다.
- [x] prod ALB access log용 비공개 S3 bucket과 30일 lifecycle을 구성한다.
- [x] prod WAF 관리형 규칙 두 개와 IP rate rule을 모두 `Count`로 구성한다.
- [x] dev·prod Terraform validate를 통과한다.
- [x] prod Terraform plan에서 변경 범위와 삭제 없음 여부를 확인한다.
- [x] 저장된 prod plan을 적용하고 Lambda·S3·WAF live 상태를 확인한다.
- [ ] AI prod 배포 후 CloudWatch 로그 레벨과 Grafana dashboard를 검증한다.
- [ ] Sentry prod BE·AI alert rule을 구성하고 Discord 수신을 확인한다.
- [ ] 완료 전 독립 리뷰와 최종 검증을 통과한다.

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

## 2026-07-09 API task auth/CORS SSM 주입 수정

- [x] develop 소셜 로그인 실패 원인을 CORS preflight와 ECS task definition으로 재현한다.
- [x] API task definition에 CORS와 auth SSM parameter 주입이 빠진 것을 확인한다.
- [x] 누락된 CORS와 auth parameter 이름 검증을 실패 상태로 확인한다.
- [x] API task `secrets`에 CORS와 auth SSM parameter를 추가한다.
- [x] `terraform fmt -recursive`를 실행한다.
- [x] develop과 prod Terraform validate를 실행한다.
- [x] develop과 prod Terraform plan을 확인한다.
- [x] develop과 prod Terraform apply를 실행한다.
- [x] develop과 prod API task definition에 CORS와 auth secret 이름이 포함됐는지 확인한다.
- [x] develop CORS preflight와 health check를 검증한다.
- [x] 변경 내용을 커밋하고 `origin/main`으로 push한다.

## 2026-07-09 SSM runtime 주입 규칙 문서화

- [x] 현재 git 상태와 SSM 문서를 확인한다.
- [x] SSM 생성과 ECS task definition secret 주입이 별도 단계임을 문서화한다.
- [x] 기존 SSM 값 변경 후에도 ECS 새 deployment가 필요함을 문서화한다.
- [x] `git diff`와 `git status --short`로 변경 범위를 확인한다.
- [x] 변경 내용을 커밋한다.

## 2026-07-11 develop ECS 배포 태스크 진단 권한 추가

- [x] GitHub Actions 역할의 AccessDenied 원인을 확인한다.
- [x] develop/prod 역할에 `ecs:ListTasks`, `ecs:DescribeTasks` 조회 권한을 추가한다.
- [x] 두 IAM 정책 반영 결과를 확인하고 context note에 기록한다.

## 2026-07-11 develop API health check grace period 확대

- [x] ALB health check 실패 태스크의 기동 시간을 확인한다.
- [x] API ECS health check grace period를 300초로 변경한다.
- [x] Terraform plan/apply와 ECS 서비스 설정을 확인한다.
- [x] 변경 내용을 `origin/main`에 푸시한다.

## 2026-07-13 LAN-122 Sentry DSN ECS 주입

- [x] develop/prod BE·AI Sentry DSN SSM parameter를 `SecureString`으로 작성한다.
- [x] 최신 app platform task definition과 BE·AI 설정 이름을 확인한다.
- [x] API와 AI task definition에 서비스별 SSM 값을 `SENTRY_DSN`으로 주입한다.
- [x] BE `SENTRY_ENVIRONMENT`와 AI `APP_ENV`를 Terraform environment 값으로 주입한다.
- [x] SSM parameter registry와 작업 기록을 갱신한다.
- [x] `terraform fmt -recursive`, develop/prod `terraform validate`, `terraform plan`을 실행한다.
- [x] 사용자 승인 후 develop/prod Terraform apply를 실행한다.
- [x] 새 ECS task definition의 secret과 서비스 deployment 상태를 검증한다.

## 2026-07-13 LAN-122 Grafana Cloud 통합 모니터링

- [x] 기존 Grafana Cloud stack을 확인하고 CloudWatch scrape는 조직 SCP 제약으로 범위에서 제외한다.
- [x] 애플리케이션 지표 전송 방식을 OTLP 직접 전송으로 결정한다.
- [x] BE와 AI task definition에 서비스명, 환경, OTLP endpoint와 인증 header를 주입한다.
- [x] CloudWatch Logs를 Grafana Loki로 전달할 Data Firehose 구성을 추가한다.
- [x] Grafana Cloud OTLP 인증 header를 환경별 SSM parameter로 작성한다.
- [x] Grafana Cloud Logs 인증값을 AWS Secrets Manager에 작성한다.
- [x] `terraform fmt -recursive`, develop/prod `terraform validate`를 실행한다.
- [x] 실제 endpoint와 secret ARN 준비 후 develop/prod `terraform plan`을 실행한다.
- [x] 사용자 승인 후 develop/prod Terraform apply를 실행한다.
- [x] Firehose 전송 지표와 Grafana Loki에서 develop·prod BE·AI 로그 조회를 확인한다.
- [x] 사용하지 않는 Grafana CloudWatch IAM role과 policy를 production에서 제거한다.
- [x] 제거 후 dev/prod Terraform 상태와 Firehose·ECS 서비스 상태를 확인한다.
- [x] develop BE·AI 변경을 배포한 뒤 BE JVM·GC·HTTP와 AI process·GC·HTTP 지표 조회를 확인한다.
- [x] production BE·AI 변경을 배포한 뒤 같은 애플리케이션 지표 조회를 확인한다.

## 2026-07-13 LAN-122 Grafana Cloud 대시보드

- [x] Grafana 데이터 소스와 실제 메트릭·로그 라벨을 확인한다.
- [x] 공개 JVM·FastAPI 대시보드와 환경 분리 방식을 검토한다.
- [x] 환경 변수 기반 Overview·BE·AI 대시보드 설계를 확정한다.
- [x] 대시보드 설계 문서를 작성하고 자체 검토한다.
- [x] 사용자가 설계 문서를 검토한다.
- [x] dashboard 구현 계획을 작성하고 자체 검토한다.
- [x] Grafana stack 표시 이름을 `landitobservability`로 변경하고 수집 상태를 다시 확인한다.
- [x] dashboard JSON과 동기화 스크립트를 구현한다.
- [x] 단기 Grafana service account token으로 대시보드를 배포한다.
- [x] develop·prod의 필수 메트릭과 전체·에러 로그 패널을 검증한다.
- [x] 배포 token을 폐기하고 운영 문서를 갱신한다.

## 2026-07-15 LAN-134 공통 콘텐츠 CloudFront 제공

- [x] 공유 Terraform root와 state key를 추가한다.
- [x] private 콘텐츠 버킷, CloudFront OAC, distribution, bucket policy를 추가한다.
- [x] GitHub Actions shared target과 승인 environment 안내를 추가한다.
- [x] 콘텐츠 key, cache header, DB URL 반영, 이전 객체 삭제 절차를 문서화한다.
- [x] `terraform fmt`, shared/dev/prod validate, shared plan을 실행한다.
- [x] diff 독립 검토와 사용자 승인 전 apply 보류를 확인한다.

## 2026-07-17 메시지 피드백 worker 환경 변수 추가

- [x] develop·prod SSM에 메시지 피드백 전용 model과 review enable parameter를 `String`으로 작성한다.
- [x] AI worker task definition에 두 SSM parameter를 환경 변수로 주입한다.
- [x] SSM parameter registry와 작업 기록을 갱신한다.
- [x] `terraform fmt`, develop/prod `terraform validate`, `terraform plan`을 실행한다.
- [x] 사용자 승인 후 develop/prod Terraform apply를 실행한다.
- [x] 새 worker task definition과 ECS deployment에서 두 환경 변수 주입을 확인한다.

## 2026-07-22 LAN-192 prod 관측성과 Discord 장애 알림

- [x] 현재 Sentry·Grafana 수집 범위와 대시보드 쿼리를 확인한다.
- [x] prod 전용 채널 분리와 장애성 알림 범위를 확정한다.
- [x] Sentry 신규·회귀·반복 급증 조건과 Grafana 5xx 조건을 확정한다.
- [x] Discord 연동과 alert rule 설계를 문서화하고 자체 검토한다.
- [x] 사용자가 설계 문서를 검토한다.
- [x] Sentry Team 플랜 제한을 확인하고 Lambda relay 방식으로 설계를 변경한다.
- [x] Lambda handler를 테스트 우선으로 구현한다.
- [x] prod Terraform에 Lambda Function URL과 최소 IAM 권한을 추가한다.
- [x] Discord webhook과 Sentry App signing secret을 Terraform 밖의 prod SSM `SecureString`으로 준비한다.
- [x] `terraform fmt`, prod `terraform validate`, `terraform plan`을 실행한다.
- [x] 사용자 승인 후 초기 prod Terraform apply를 실행한다.
- [x] 실제 Sentry 서명 request로 동기 relay의 cold timeout과 Discord 응답 지연을 확인한다.
- [x] AI 로그 오분류와 prod 미매핑 404 관측 작업을 LAN-192 범위에 포함한다.
- [x] 비동기 relay, AI level 필드, ALB access log, WAF Count 설계를 문서화하고 자체 검토한다.
- [x] 사용자가 확장된 LAN-192 설계 문서를 검토한다.
- [x] Lambda ingress와 delivery를 비동기로 분리하고 API Gateway cold 1초 이내 응답을 검증한다.
- [ ] Sentry Internal Integration과 BE·AI issue alert rule을 relay에 연결한다.
- [ ] 실제 Sentry test alert가 `#alerts-sentry-prod`에 도착하는지 확인한다.
- [x] Landit AI 로그에 명시적인 level 필드를 추가하고 테스트한다.
- [ ] AI와 Overview Grafana 에러 패널을 AI level 필드 기준으로 변경하고 배포한다.
- [x] prod ALB access log 전용 S3 bucket과 30일 lifecycle을 추가한다.
- [x] prod ALB에 AWS managed rule과 IP rate rule을 WAF Count 모드로 연결한다.
- [x] Terraform plan을 검증하고 승인 뒤 prod apply를 실행한다.
- [x] 실제 S3 access log object와 WAF Count rule live 상태를 확인한다.
- [ ] 운영 문서와 검증 기록을 최종 반영한다.

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
