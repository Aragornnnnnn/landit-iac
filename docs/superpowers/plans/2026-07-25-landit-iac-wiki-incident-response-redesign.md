# Landit IaC Wiki Incident Response Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최신 Landit IaC 구조와 production 운영 상태를 설명하고 장애 감지부터 종료까지 안내하는 역할 중심 GitHub Wiki를 작성해 게시한다.

**Architecture:** `origin/main`의 Terraform, workflow, 운영 문서를 기준 소스로 사용하고 별도 `landit-iac.wiki.git`의 `master`에서 기존 URL을 보존하며 전체 페이지를 갱신한다. 정상 운영, 관측성과 알림, production 장애 대응, 증상별 문제 해결을 서로 다른 페이지 책임으로 분리한다.

**Tech Stack:** GitHub Wiki, Markdown, Git, Terraform source, AWS CLI read-only queries, ripgrep, Ruby.

## Global Constraints

- 설계 기준은 `docs/superpowers/specs/2026-07-25-landit-iac-wiki-incident-response-redesign.md`다.
- 사용자가 이번 작업을 이슈 번호 없이 진행하도록 승인했다.
- 소스 작업 브랜치는 `feat/wiki-incident-runbook`이다.
- Wiki 작성 경로는 `/tmp/landit-iac-wiki-authoring-20260725`다.
- Wiki 기본 브랜치는 `master`이며 기존 파일명과 공개 URL을 유지한다.
- 새 페이지는 `Incident-Response-Runbook.md`, `Push-Notifications.md` 두 개만 추가한다.
- Runbook은 production 장애 대응이 기준이고 develop은 재현과 검증에만 사용한다.
- Terraform apply, AWS 리소스 변경, SSM 값 변경, Grafana·Sentry 설정 변경은 수행하지 않는다.
- secret 값, token, webhook URL, access key, private key, DB credential, 사용자 원문과 raw prompt를 기록하지 않는다.
- 현재 동작은 최신 `origin/main`의 코드와 workflow를 우선하고, 적용 상태는 검증 기록이나 read-only live 조회 근거가 있을 때만 단정한다.
- BE·AI 애플리케이션 배포와 릴리즈 정책은 해당 Wiki로 연결하고 IaC Wiki에 복제하지 않는다.
- Wiki 문서 커밋은 탐색 구조, 정상 운영, 관측성과 알림, 장애 대응의 네 논리 단위로 나눈다.

---

### Task 1: 최신 기준선과 Wiki 작성 저장소 준비

**Files:**
- Reference: `/Users/sangmin8817/.codex/worktrees/3178/landit-iac/README.md`
- Reference: `/Users/sangmin8817/.codex/worktrees/3178/landit-iac/.github/workflows/terraform.yml`
- Reference: `/Users/sangmin8817/.codex/worktrees/3178/landit-iac/environments/`
- Reference: `/Users/sangmin8817/.codex/worktrees/3178/landit-iac/modules/`
- Reference: `/Users/sangmin8817/.codex/worktrees/3178/landit-iac/docs/`
- Clone: `/tmp/landit-iac-wiki-authoring-20260725`
- Modify: `/Users/sangmin8817/.codex/worktrees/3178/landit-iac/context-notes.md`

**Interfaces:**
- Consumes: 최신 source `origin/main`과 Wiki `origin/master`.
- Produces: 변경 없는 source 기준 SHA, Wiki 기준 SHA, 깨끗한 Wiki authoring checkout.

- [ ] **Step 1: source 작업 상태와 원격 기준을 갱신한다.**

Run:

```bash
git status --short
git fetch origin main
git rev-parse --short origin/main
git log -1 --oneline origin/main
```

Expected: source 작업트리는 계획 문서 커밋 이후 깨끗하고 `origin/main`의 최신 SHA와 제목이 출력된다.

- [ ] **Step 2: Wiki 원격 master를 확인한다.**

Run:

```bash
git ls-remote https://github.com/Aragornnnnnn/landit-iac.wiki.git HEAD refs/heads/master
```

Expected: `HEAD`와 `refs/heads/master`가 같은 SHA를 반환한다.

- [ ] **Step 3: 새 authoring checkout을 만든다.**

Run:

```bash
test ! -e /tmp/landit-iac-wiki-authoring-20260725
git clone https://github.com/Aragornnnnnn/landit-iac.wiki.git /tmp/landit-iac-wiki-authoring-20260725
git -C /tmp/landit-iac-wiki-authoring-20260725 branch --show-current
git -C /tmp/landit-iac-wiki-authoring-20260725 status --short
```

Expected: branch는 `master`이고 변경 파일은 없다. 대상 경로가 이미 있으면 재사용하거나 삭제하지 말고 작업을 중단해 정확한 경로를 다시 정한다.

- [ ] **Step 4: 최신 사실의 기준 소스를 확인한다.**

Run:

```bash
rg -n '^#|^##|workflow_dispatch|develop|production|shared' README.md .github/workflows/terraform.yml docs/*.md
rg -n '^resource |^module |^output |^variable ' environments modules
git log --since='2026-07-18' --oneline -- README.md docs .github environments modules grafana scripts
```

Expected: Wiki 작성 뒤 추가된 관측성, WAF, Push, dashboard 변경과 실제 workflow target이 확인된다.

- [ ] **Step 5: 적용 상태가 필요한 AWS 항목을 read-only로 확인한다.**

Run:

```bash
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output json
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws ecs describe-services --cluster prod-landit-cluster --services prod-landit-api prod-landit-worker --query 'services[].{Name:serviceName,Desired:desiredCount,Running:runningCount,Primary:deployments[?status==`PRIMARY`]|[0].rolloutState}' --output table
AWS_PROFILE=landit AWS_REGION=ap-northeast-2 aws scheduler get-schedule --name prod-landit-review-reminder --query '{Name:Name,State:State,ScheduleExpression:ScheduleExpression,Timezone:ScheduleExpressionTimezone}' --output json
```

Expected: Landit 계정 identity, production ECS 상태와 production Push Scheduler 상태가 secret 없이 출력된다. 실제 resource 이름이 코드와 다르면 Terraform output과 AWS 목록 조회로 정확한 이름을 먼저 찾고 문서에는 안정적인 역할과 확인 방법만 기록한다.

- [ ] **Step 6: 기준 SHA와 live 확인 범위를 작업 기록에 남긴다.**

`context-notes.md`의 `2026-07-25 IaC Wiki 장애 대응 중심 개편`에 다음 사실을 추가한다.

- 확인한 source `origin/main` SHA.
- 확인한 Wiki `master` SHA.
- live 조회에 성공한 항목과 조회하지 못한 항목.
- Wiki에서 현재 상태로 단정할 수 있는 범위.

- [ ] **Step 7: source 기록 변경을 검증한다.**

Run:

```bash
git diff --check
git diff -- context-notes.md
git status --short
```

Expected: `context-notes.md`만 기준선 기록으로 변경되고 whitespace 오류가 없다.

### Task 2: Home, 탐색 구조와 아키텍처 페이지 개편

**Files:**
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/Home.md`
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/_Sidebar.md`
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/Getting-Started.md`
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/Infrastructure-Architecture.md`
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/Architecture-Decisions.md`

**Interfaces:**
- Consumes: Task 1의 source SHA, Wiki SHA, root·module·workflow 사실.
- Produces: 독자별 진입점, 최신 인프라 경계, 이후 운영·장애 페이지로 연결되는 고정 탐색 구조.

- [ ] **Step 1: Home을 최신 범위와 독자별 진입점으로 다시 쓴다.**

`Home.md`의 H2를 다음 순서로 둔다.

```markdown
## 이 저장소가 맡는 일
## 현재 문서 기준
## 환경과 관리 경계
## 처음 합류했다면
## 운영 중이라면
## 장애 대응 중이라면
## 문서와 코드가 다를 때
```

현재 문서 기준에는 Task 1의 `origin/main` SHA와 검증 날짜 `2026-07-25`를 기록한다. 실제 배포 revision이나 일시적인 task IP는 기록하지 않는다.

- [ ] **Step 2: Sidebar를 승인된 역할 순서로 다시 쓴다.**

`_Sidebar.md`는 설계 문서의 시작하기, 구조 이해하기, 변경하고 운영하기, 장애 대응하기, Repository 순서를 그대로 사용한다. `Observability.md` 링크의 표시 이름은 `Observability and Alerting`으로 둔다.

- [ ] **Step 3: Getting Started를 read-only 첫 확인 중심으로 갱신한다.**

다음 H2를 사용한다.

```markdown
## 준비할 도구
## 저장소와 기준 문서
## AWS 인증 확인
## Terraform root 선택
## 첫 read-only 확인
## 첫 validate와 plan
## 변경 전 확인
## 막혔을 때
```

실제 workflow target은 `.github/workflows/terraform.yml`의 현재 입력과 일치시킨다. apply 명령은 기본 시작 절차에 넣지 않고 [Terraform Operations](Terraform-Operations)로 연결한다.

- [ ] **Step 4: Infrastructure Architecture를 최신 데이터 흐름으로 갱신한다.**

다음 H2를 사용한다.

```markdown
## 책임 경계
## Terraform root와 state
## 요청 경로
## 비동기 작업 경로
## 관측성과 장애 알림 경로
## 스토리지 경계
## Runtime 설정 경로
## Terraform 밖의 책임
```

Mermaid에는 환경별 ALB, BE API, AI worker, jobs Queue, Push Queue·DLQ·Scheduler, Sentry relay, Grafana 전달과 shared content 경계를 표시한다. secret, account ID, ARN, 내부 IP는 넣지 않는다.

- [ ] **Step 5: Architecture Decisions를 현재 결정과 재검토 조건 중심으로 갱신한다.**

확정된 결정에는 환경별 state, SSM 값의 Terraform 외부 관리, private shared content, application metrics와 logs의 분리 경로, production 전용 장애 알림을 포함한다. 보류 또는 재검토 조건에는 WAF Block 전환, Sentry relay DLQ, Grafana CloudWatch integration, Push Scheduler 활성화를 현재 근거에 맞게 기록한다.

- [ ] **Step 6: 탐색 구조 페이지를 검증한다.**

Run:

```bash
git -C /tmp/landit-iac-wiki-authoring-20260725 diff --check
rg -n '^# |^## ' /tmp/landit-iac-wiki-authoring-20260725/Home.md /tmp/landit-iac-wiki-authoring-20260725/Getting-Started.md /tmp/landit-iac-wiki-authoring-20260725/Infrastructure-Architecture.md /tmp/landit-iac-wiki-authoring-20260725/Architecture-Decisions.md
rg -n 'Incident-Response-Runbook|Push-Notifications|Observability' /tmp/landit-iac-wiki-authoring-20260725/Home.md /tmp/landit-iac-wiki-authoring-20260725/_Sidebar.md
```

Expected: H1은 파일당 하나이고 승인된 H2와 새 페이지 링크가 존재하며 whitespace 오류가 없다.

- [ ] **Step 7: 탐색 구조를 Wiki에 커밋한다.**

Run:

```bash
git -C /tmp/landit-iac-wiki-authoring-20260725 add Home.md _Sidebar.md Getting-Started.md Infrastructure-Architecture.md Architecture-Decisions.md
git -C /tmp/landit-iac-wiki-authoring-20260725 commit -m "docs: IaC Wiki 탐색 구조와 아키텍처를 갱신한다"
```

Expected: 다섯 파일만 포함한 Wiki 커밋이 생성된다.

### Task 3: 정상 운영 페이지 개편

**Files:**
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/Terraform-Operations.md`
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/Secrets-and-Configuration.md`
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/Content-Delivery.md`
- Create: `/tmp/landit-iac-wiki-authoring-20260725/Push-Notifications.md`

**Interfaces:**
- Consumes: `.github/workflows/terraform.yml`, `docs/developer-guide.md`, `docs/ssm-parameters.md`, `docs/content-storage.md`, `docs/push-notifications.md`, Terraform module code.
- Produces: 장애가 아닌 정상 변경과 검증의 역할별 Runbook.

- [ ] **Step 1: Terraform Operations를 현재 workflow와 승인 경계로 다시 쓴다.**

다음 H2를 사용한다.

```markdown
## 작업 원칙
## Root 선택
## 로컬 validate와 plan
## GitHub Actions plan
## Apply 승인 조건
## 변경 유형별 검증
## Drift와 예상하지 않은 변경
## Git 작업 흐름
```

workflow input, environment, main 제한은 실제 YAML과 일치시킨다. destroy를 정상 운영 절차에 포함하지 않는다.

- [ ] **Step 2: Secrets and Configuration을 최신 registry와 재배포 조건으로 갱신한다.**

SSM 값은 표시하지 않고 이름, 타입, 소비 container와 반영 조건만 적는다. SSM 변경, task definition mapping, 새 deployment, 실제 사용 경로 검증을 별도 단계로 설명한다.

- [ ] **Step 3: Content Delivery를 현재 적용 상태와 안전한 교체 절차로 갱신한다.**

shared bucket과 CloudFront OAC, UUID key, immutable cache, DB URL 전환, 이전 object 삭제 조건을 설명한다. Terraform 구성과 live 적용 상태를 구분하고 실제 삭제 명령은 제공하지 않는다.

- [ ] **Step 4: Push Notifications를 새로 작성한다.**

다음 H2를 사용한다.

```markdown
## 책임 범위
## 메시지 흐름
## Queue와 DLQ
## Scheduler와 활성화 조건
## 배포 순서
## Live 검증
## 적체와 DLQ 대응
## 민감 데이터와 금지 사항
```

`docs/push-notifications.md`의 실제 retention, visibility timeout, redrive, Scheduler 상태와 활성화 전제만 사용한다. 메시지 body는 조회·복사하지 않고 속성 수와 상태만 확인하도록 작성한다.

- [ ] **Step 5: 정상 운영 페이지를 검증한다.**

Run:

```bash
git -C /tmp/landit-iac-wiki-authoring-20260725 diff --check
rg -n '^# |^## ' /tmp/landit-iac-wiki-authoring-20260725/Terraform-Operations.md /tmp/landit-iac-wiki-authoring-20260725/Secrets-and-Configuration.md /tmp/landit-iac-wiki-authoring-20260725/Content-Delivery.md /tmp/landit-iac-wiki-authoring-20260725/Push-Notifications.md
rg -n 'terraform-apply-develop|terraform-apply-production|DISABLED|DLQ|immutable' /tmp/landit-iac-wiki-authoring-20260725/*.md
```

Expected: 네 페이지의 책임과 필수 운영 조건이 확인되고 whitespace 오류가 없다.

- [ ] **Step 6: 정상 운영 페이지를 Wiki에 커밋한다.**

Run:

```bash
git -C /tmp/landit-iac-wiki-authoring-20260725 add Terraform-Operations.md Secrets-and-Configuration.md Content-Delivery.md Push-Notifications.md
git -C /tmp/landit-iac-wiki-authoring-20260725 commit -m "docs: IaC 정상 운영 절차를 최신화한다"
```

Expected: 네 파일만 포함한 Wiki 커밋이 생성된다.

### Task 4: Observability and Alerting 개편

**Files:**
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/Observability.md`

**Interfaces:**
- Consumes: `docs/observability.md`, Grafana dashboard JSON, alert contract scripts, Sentry relay Terraform과 Lambda.
- Produces: 장애 알림의 의미, 신호 경로, 보안 경계와 원본 조사 위치.

- [ ] **Step 1: Observability를 알림 우선 흐름으로 다시 쓴다.**

다음 H2를 사용한다.

```markdown
## 먼저 볼 곳
## Production 장애 알림
## Grafana Alerting
## Sentry Alerting
## 지표와 Dashboard
## 로그와 ALB 요청 분석
## WAF Count
## 인증과 비밀정보
## 변경 후 검증
## 현재 제약
```

Sentry와 Grafana Discord 채널 역할, Grafana `CRITICAL`·`WARNING`·`MONITORING`, Sentry 신규·회귀·급증, Firing·Resolved 차이를 실제 운영 문서와 일치시킨다.

- [ ] **Step 2: 원인을 단정하지 않는 경계를 명시한다.**

다음 원칙을 포함한다.

- `MONITORING`은 서비스 장애와 수집 장애를 함께 확인한다.
- Sentry issue alert는 원인 확정이 아니라 조사 시작 신호다.
- metric label만으로 특정 사용자나 raw 요청을 알 수 없다.
- ALB access log와 WAF Count는 요청 경로와 분포 근거이며 caller 신원을 단정하지 않는다.
- `AI_GENERATION_FAILED` wrapper만으로 model 실패를 단정하지 않는다.

- [ ] **Step 3: Observability 페이지를 검증한다.**

Run:

```bash
git -C /tmp/landit-iac-wiki-authoring-20260725 diff --check
rg -n 'CRITICAL|WARNING|MONITORING|Firing|Resolved|Sentry|Grafana|CloudWatch|WAF|ALB' /tmp/landit-iac-wiki-authoring-20260725/Observability.md
rg -n 'secret|token|webhook|Authorization|사용자 원문|raw prompt' /tmp/landit-iac-wiki-authoring-20260725/Observability.md
```

Expected: 모든 관측 경로와 보안 경계가 설명되고 실제 credential 값은 없다.

- [ ] **Step 4: Observability 페이지를 Wiki에 커밋한다.**

Run:

```bash
git -C /tmp/landit-iac-wiki-authoring-20260725 add Observability.md
git -C /tmp/landit-iac-wiki-authoring-20260725 commit -m "docs: 관측성과 장애 알림 흐름을 정리한다"
```

Expected: `Observability.md`만 포함한 Wiki 커밋이 생성된다.

### Task 5: Incident Response Runbook과 Troubleshooting 작성

**Files:**
- Create: `/tmp/landit-iac-wiki-authoring-20260725/Incident-Response-Runbook.md`
- Modify: `/tmp/landit-iac-wiki-authoring-20260725/Troubleshooting.md`

**Interfaces:**
- Consumes: Task 3의 정상 운영 페이지와 Task 4의 관측 신호.
- Produces: production 장애 공통 대응 흐름과 증상별 조사·복구 절차.

- [ ] **Step 1: Incident Response Runbook을 작성한다.**

다음 H2를 사용한다.

```markdown
## 적용 범위
## 대응 원칙
## 1. 감지와 접수
## 2. 영향 확인
## 3. 대응 선언과 기록
## 4. 증거 수집
## 5. 원인 경계 좁히기
## 6. 완화와 승인
## 7. 복구 확인
## 8. 종료와 후속 조치
## 상황 공유 형식
## 관련 문서
```

사실, 가설, 조치, 검증 결과를 구분하는 paste-ready 상황 공유 형식을 포함한다. 실제 incident 식별자, 내부 URL, 사용자 데이터는 예시로 만들지 않는다.

- [ ] **Step 2: 승인 없는 변경을 금지하는 조치 표를 작성한다.**

표는 read-only 기본 확인과 승인 필수 변경을 구분한다. 승인 필수에는 Terraform apply·destroy, ECS 재배포·scale, SSM·secret, WAF Block, alert route, Queue·DLQ 메시지 이동·삭제·재처리, 운영 데이터 삭제를 포함한다.

- [ ] **Step 3: Troubleshooting 첫 화면에 빠른 분류표를 작성한다.**

다음 증상을 포함한다.

- production 5xx 또는 telemetry missing.
- Sentry 신규·회귀·급증.
- ECS deployment 정체와 task 반복 종료.
- ALB target unhealthy.
- SSM 변경 미반영.
- Grafana metric·log 수집 공백.
- Discord 알림 미수신.
- WAF Count와 ALB access log 조사.
- Push Queue 적체와 DLQ.
- Terraform plan 예상 밖 변경, backend와 OIDC.
- CloudFront 콘텐츠 미반영.

- [ ] **Step 4: 각 문제를 같은 형식으로 다시 쓴다.**

모든 문제는 `### 증상`, `### 확인`, `### 조치`, `### 복구 확인`을 사용한다. 조사 순서는 같은 시각의 BE·AI·ALB·ECS·Sentry·Grafana 증거를 연결하고 wrapper 오류만으로 하위 원인을 단정하지 않게 한다.

- [ ] **Step 5: 장애 대응 페이지를 검증한다.**

Run:

```bash
git -C /tmp/landit-iac-wiki-authoring-20260725 diff --check
rg -n '^# |^## ' /tmp/landit-iac-wiki-authoring-20260725/Incident-Response-Runbook.md /tmp/landit-iac-wiki-authoring-20260725/Troubleshooting.md
test "$(rg -c '^### 증상$' /tmp/landit-iac-wiki-authoring-20260725/Troubleshooting.md)" -eq "$(rg -c '^### 복구 확인$' /tmp/landit-iac-wiki-authoring-20260725/Troubleshooting.md)"
rg -n 'Terraform apply|ECS 재배포|SSM|WAF|DLQ|사실|가설|검증 결과' /tmp/landit-iac-wiki-authoring-20260725/Incident-Response-Runbook.md
```

Expected: 모든 Troubleshooting 항목이 같은 형식을 사용하고 Runbook에 승인 경계와 상황 공유 형식이 있다.

- [ ] **Step 6: 장애 대응 페이지를 Wiki에 커밋한다.**

Run:

```bash
git -C /tmp/landit-iac-wiki-authoring-20260725 add Incident-Response-Runbook.md Troubleshooting.md
git -C /tmp/landit-iac-wiki-authoring-20260725 commit -m "docs: production 장애 대응 Runbook을 추가한다"
```

Expected: 두 파일만 포함한 Wiki 커밋이 생성된다.

### Task 6: 전체 Wiki 검증, source 기록과 게시

**Files:**
- Verify: `/tmp/landit-iac-wiki-authoring-20260725/*.md`
- Modify: `/Users/sangmin8817/.codex/worktrees/3178/landit-iac/checklist.md`
- Modify: `/Users/sangmin8817/.codex/worktrees/3178/landit-iac/context-notes.md`

**Interfaces:**
- Consumes: Tasks 2~5의 네 Wiki 커밋.
- Produces: 검증된 Wiki `master`, 공개 페이지와 source 저장소의 게시 증거.

- [ ] **Step 1: 예상한 Wiki 파일 집합을 확인한다.**

Run:

```bash
rg --files /tmp/landit-iac-wiki-authoring-20260725 | sort
git -C /tmp/landit-iac-wiki-authoring-20260725 status --short
git -C /tmp/landit-iac-wiki-authoring-20260725 log -5 --oneline
```

Expected: 기존 10개 파일과 새 2개 페이지만 있고 Wiki 작업트리는 깨끗하며 네 개의 새 논리 커밋이 순서대로 보인다.

- [ ] **Step 2: Markdown H1과 내부 페이지 링크를 검사한다.**

Run:

```bash
ruby -e 'files=Dir["/tmp/landit-iac-wiki-authoring-20260725/*.md"]; abort("H1") unless files.all?{|f| expected=File.basename(f)=="_Sidebar.md" ? 0 : 1; File.readlines(f).count{|l| l.start_with?("# ")}==expected}; names=files.map{|f| File.basename(f,".md")}; links=files.flat_map{|f| File.read(f).scan(/\]\(([A-Za-z0-9_-]+)(?:#[^)]+)?\)/).flatten}; missing=links.uniq-names; abort("missing: #{missing.join(",")}") unless missing.empty?'
git -C /tmp/landit-iac-wiki-authoring-20260725 diff --check HEAD~4..HEAD
```

Expected: 본문 Markdown 파일에는 H1이 하나 있고 특수 파일 `_Sidebar.md`에는 H1이 없으며, 내부 링크 대상 파일이 존재하고 whitespace 오류가 없다.

- [ ] **Step 3: 미완성 문구와 민감정보 패턴을 검사한다.**

Run:

```bash
! rg -n '\b(T[B]D|T[O]DO)\b|실제값을 입력|채워 넣기' /tmp/landit-iac-wiki-authoring-20260725
! rg -n 'https://(discord(app)?\.com/api/webhooks|hooks\.slack\.com)|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY|Authorization: Bearer [A-Za-z0-9]' /tmp/landit-iac-wiki-authoring-20260725
```

Expected: 두 명령 모두 일치 항목 없이 성공한다.

- [ ] **Step 4: source 계약과 Wiki의 핵심 표현을 대조한다.**

Run:

```bash
rg -n 'choices:|develop|production|shared|terraform-apply-' .github/workflows/terraform.yml
rg -n 'CRITICAL|WARNING|MONITORING|discord-prod-incidents|Sentry|WAF' docs/observability.md
rg -n 'DISABLED|maxReceiveCount|visibility|DLQ' docs/push-notifications.md
rg -n 'CRITICAL|WARNING|MONITORING|terraform-apply-|DISABLED|maxReceiveCount|DLQ' /tmp/landit-iac-wiki-authoring-20260725
```

Expected: workflow, 관측성, Push 계약과 Wiki 표현이 일치한다.

- [ ] **Step 5: source 작업 기록을 게시 전 상태로 갱신한다.**

`checklist.md`에서 Wiki 작성과 검증 항목만 완료로 갱신하고 게시 항목은 미완료로 둔다. `context-notes.md`에는 Wiki commit 범위, 검증 명령, 게시 전 Wiki SHA를 기록한다.

- [ ] **Step 6: source 기록을 검증하고 커밋한다.**

Run:

```bash
git diff --check
git status --short
git add checklist.md context-notes.md docs/superpowers/plans/2026-07-25-landit-iac-wiki-incident-response-redesign.md
git commit -m "docs: IaC Wiki 개편 실행과 검증을 기록한다"
```

Expected: 계획과 최종 기록만 포함한 source 문서 커밋이 생성된다.

- [ ] **Step 7: Wiki `master`를 게시한다.**

Run:

```bash
git -C /tmp/landit-iac-wiki-authoring-20260725 status --short
git -C /tmp/landit-iac-wiki-authoring-20260725 push origin master
git ls-remote https://github.com/Aragornnnnnn/landit-iac.wiki.git refs/heads/master
git -C /tmp/landit-iac-wiki-authoring-20260725 rev-parse HEAD
```

Expected: push가 성공하고 원격 `master` SHA와 로컬 Wiki `HEAD`가 일치한다.

- [ ] **Step 8: 공개 Wiki 렌더링을 확인한다.**

Run:

```bash
curl -L --fail --silent --show-error -o /dev/null -w '%{http_code}\n' https://github.com/Aragornnnnnn/landit-iac/wiki
curl -L --fail --silent --show-error -o /dev/null -w '%{http_code}\n' https://github.com/Aragornnnnnn/landit-iac/wiki/Incident-Response-Runbook
curl -L --fail --silent --show-error -o /dev/null -w '%{http_code}\n' https://github.com/Aragornnnnnn/landit-iac/wiki/Push-Notifications
curl -L --fail --silent --show-error -o /dev/null -w '%{http_code}\n' https://github.com/Aragornnnnnn/landit-iac/wiki/Troubleshooting
```

Expected: 네 URL이 모두 HTTP `200`을 반환한다. 공개 페이지의 Sidebar에서 새 페이지와 기존 페이지 링크가 보이는지 함께 확인한다.

- [ ] **Step 9: source에 게시 결과를 기록하고 커밋한다.**

`checklist.md`의 게시 항목을 완료로 갱신한다. `context-notes.md`에는 원격 Wiki SHA, 공개 URL의 HTTP 결과와 렌더링 확인 결과를 기록한다.

Run:

```bash
git diff --check
git add checklist.md context-notes.md
git commit -m "docs: IaC Wiki 게시 결과를 기록한다"
```

Expected: 성공한 게시 결과만 source 기록에 추가된다.

- [ ] **Step 10: 최종 source와 Wiki 상태를 확인한다.**

Run:

```bash
git status --short
git log -5 --oneline
git -C /tmp/landit-iac-wiki-authoring-20260725 status --short
git -C /tmp/landit-iac-wiki-authoring-20260725 log -5 --oneline
```

Expected: 두 작업트리가 깨끗하고 source에는 설계·실행 기록 커밋, Wiki에는 네 개의 내용 커밋이 확인된다.
