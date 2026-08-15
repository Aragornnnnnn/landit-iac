# LAN-284 Safe Rollout Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최신 소스와 개발 AWS state를 기준으로 LAN-284 적용 경계를 다시 검증하고, 실제 변경 전 승인 가능한 saved plan을 준비한다.

**Architecture:** 기존 개발 ECS·ALB는 그대로 둔 채 세 저장소의 LAN-284 브랜치를 최신 기준으로 갱신한다. 최신 `origin/main`의 기준 plan과 LAN-284 plan을 별도로 생성해 기존 LAN-184 drift와 신규 EC2 추가분을 주소 단위로 분리한다.

**Tech Stack:** Git worktree, Terraform, AWS provider, Bash, Gradle, Python unittest.

## Global Constraints

- 이 계획에서는 `terraform apply`, AWS 리소스 변경, GitHub 변수 변경, DNS 변경, push, PR 생성을 실행하지 않는다.
- 기존 개발 ECS API·AI와 ALB를 변경하거나 제거하지 않는다.
- 사용자 원본 BE·AI checkout의 dirty 파일을 수정, stash, reset, reformat하지 않는다.
- IaC `feat/284`는 최신 `origin/main`, BE·AI `feat/LAN-284`는 최신 `origin/develop`을 기준으로 갱신한다.
- Terraform plan 파일과 JSON은 `/tmp` 아래에만 저장하고 커밋하지 않는다.
- `terraform -target`을 사용하지 않는다.
- 기준 plan과 LAN-284 plan에 포함된 create, update, replace, destroy 주소를 모두 분류한다.
- 2026-08-15 baseline은 LAN-184 drift가 없는 `No changes`다. 이후 drift가 다시 검출될 때만 LAN-184 적용을 별도 승인으로 분리하고, LAN-284 적용은 별도 사용자 승인 전까지 실행하지 않는다.

---

### Task 1: 세 저장소 브랜치 최신화와 회귀 검증

**Files:**
- Verify: `/Users/sangmin8817/Soma/landit-iac/.worktrees/feat-284`
- Verify: `/Users/sangmin8817/Soma/landit-be/.worktrees/feat-LAN-284`
- Verify: `/Users/sangmin8817/Soma/landit-ai/.worktrees/feat-LAN-284`

**Interfaces:**
- Consumes: 기존 LAN-284 IaC, BE, AI 커밋과 최신 원격 기본 브랜치.
- Produces: 최신 기본 브랜치 위에 놓인 clean LAN-284 worktree 세 개와 fresh test evidence.

- [x] **Step 1: 원격과 격리 상태를 확인한다.**

각 저장소에서 `git fetch origin --prune`, `git status --short`, `git rev-list --left-right --count <base>...HEAD`를 실행한다. 모든 feature worktree는 rebase 전에 clean이어야 한다.

- [x] **Step 2: feature branch를 최신 기준으로 갱신한다.**

```bash
git -C /Users/sangmin8817/Soma/landit-iac/.worktrees/feat-284 rebase origin/main
git -C /Users/sangmin8817/Soma/landit-be/.worktrees/feat-LAN-284 rebase origin/develop
git -C /Users/sangmin8817/Soma/landit-ai/.worktrees/feat-LAN-284 rebase origin/develop
```

충돌이 발생하면 정확한 파일과 양쪽 의도를 확인한다. LAN-284 범위를 벗어난 충돌이거나 운영 동작 판단이 필요하면 rebase를 중단하고 보고한다.

- [x] **Step 3: IaC 검증을 실행한다.**

```bash
bash scripts/test-dev-ec2-contract.sh
bash scripts/test-dev-ec2-runtime.sh
terraform fmt -recursive -check
AWS_PROFILE=landit terraform -chdir=environments/dev validate
git diff --check origin/main...HEAD
```

Expected: 모든 명령이 exit code 0이고 LAN-284 이외의 의도하지 않은 변경이 없다.

- [x] **Step 4: BE 검증을 실행한다.**

```bash
bash .github/scripts/test/deploy-ec2-service_test.sh
./gradlew check --rerun-tasks --no-daemon
git diff --check origin/develop...HEAD
```

Expected: 모든 명령이 exit code 0이고 ECS 검증 뒤 EC2 mirror 순서가 유지된다.

- [x] **Step 5: AI 검증을 실행한다.**

```bash
bash .github/scripts/test/deploy-ec2-service_test.sh
PYTHONDONTWRITEBYTECODE=1 /Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests
git diff --check origin/develop...HEAD
```

Expected: 모든 명령이 exit code 0이고 ECS 검증 뒤 EC2 mirror 순서가 유지된다.

### Task 2: 최신 state 기반 plan 분리 감사

**Files:**
- Modify: `checklist.md`
- Modify: `context-notes.md`
- Verify: `environments/dev/`

**Interfaces:**
- Consumes: Task 1의 최신 IaC branch와 현재 development Terraform state.
- Produces: 최신 `origin/main` 기준 plan과 LAN-284 plan의 주소별 차이, apply 승인 전 검토 기록.

- [x] **Step 1: 최신 origin/main 기준 plan을 생성한다.**

`origin/main` detached 임시 worktree를 `/tmp` 아래에 만들고 다음 명령을 실행한다.

```bash
AWS_PROFILE=landit terraform -chdir=environments/dev init -reconfigure -input=false
AWS_PROFILE=landit terraform -chdir=environments/dev plan -input=false -out=/tmp/lan284-main-baseline.tfplan
terraform -chdir=environments/dev show -json /tmp/lan284-main-baseline.tfplan > /tmp/lan284-main-baseline.json
```

Expected: 현재 main만으로 발생하는 LAN-184 또는 기타 drift가 식별된다. apply는 실행하지 않는다.

- [x] **Step 2: 최신 LAN-284 plan을 생성한다.**

```bash
AWS_PROFILE=landit terraform -chdir=environments/dev init -reconfigure -input=false
AWS_PROFILE=landit terraform -chdir=environments/dev plan -input=false -out=/tmp/lan284-dev.tfplan
terraform -chdir=environments/dev show -json /tmp/lan284-dev.tfplan > /tmp/lan284-dev-plan.json
```

Expected: plan이 성공하고 saved plan과 JSON은 `/tmp`에만 존재한다.

- [x] **Step 3: 두 plan의 변경 주소를 분류한다.**

```bash
jq -r '.resource_changes[] | select(.change.actions != ["no-op"]) | [.address, (.change.actions | join(","))] | @tsv' /tmp/lan284-main-baseline.json
jq -r '.resource_changes[] | select(.change.actions != ["no-op"]) | [.address, (.change.actions | join(","))] | @tsv' /tmp/lan284-dev-plan.json
```

다음을 별도로 확인한다.

- `aws_lb` 및 listener/target group의 변경 여부.
- ECS Service의 delete 또는 replace 여부.
- LAN-184 Push 리소스 destroy 여부.
- LAN-284 EC2, EIP, security group, IAM 리소스 create 여부.
- LAN-299 이후 최신 main 변경이 의도치 않게 포함되는지 여부.

- [x] **Step 4: 현재 live 안전 기준을 재확인한다.**

AWS read-only API로 개발 EC2 부재, ECS API·AI desired/running, rollout state, ALB state를 조회한다. secret 값과 SSM parameter 값은 조회하지 않는다.

- [x] **Step 5: 검증 결과를 문서화하고 커밋한다.**

`checklist.md`와 `context-notes.md`에 날짜, 브랜치 기준 SHA, 테스트 결과, 두 plan summary, 변경 주소 분류, 아직 실행하지 않은 apply·DNS·GitHub 변수·ECS 제거를 기록한다.

```bash
git add checklist.md context-notes.md docs/superpowers/plans/2026-08-15-lan-284-safe-rollout-preflight.md
git commit -m "docs: LAN-284 적용 전 최신 검증 결과를 기록한다"
```

## 다음 승인 게이트

이 계획 완료 뒤 아래 작업은 자동으로 이어서 실행하지 않는다.

2026-08-15 `origin/main` baseline이 이미 `No changes`이므로 LAN-184 drift apply와 그 뒤의 post-apply 확인은 해당 없음으로 닫는다. 2026-08-08의 LAN-184 8개 destroy는 당시 기록으로만 유지하며 현재 후속 순서에는 사용하지 않는다.

1. IaC LAN-284 PR만 병합한다.
2. 최신 state 기준 EC2 create-only plan을 재생성하고 별도 apply 승인을 받는다.
3. EC2를 apply한다.
4. SSM, Docker, Caddy, loopback health, 로그, rollback을 검증한다.
5. 임시 Vercel DNS `api-ec2-develop.landit.im`, `ai-ec2-develop.landit.im` 등록 승인을 받는다.
6. 임시 도메인에서 외부 HTTPS, API, AI, BE→AI를 검증한다.
7. BE·AI GitHub Environment에 `EC2_INSTANCE_ID`를 등록한다.
8. BE·AI workflow PR을 병합하고, 기존 ECS 검증 뒤 동일 SHA를 EC2에도 미러링하는 dual deploy를 검증한다.
9. 24~48시간 병행 관찰을 수행한다.
10. 원래 개발 DNS 전환의 별도 승인을 받는다.
11. 기존 ECS·ALB 제거용 별도 PR과 destroy plan 승인을 받는다.

EC2 apply·runtime 검증과 두 `EC2_INSTANCE_ID` 등록 전에는 BE·AI application workflow PR을 병합하지 않는다.
