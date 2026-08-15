# LAN-284 개발 EC2 이전 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** 기존 개발 ECS·ALB를 유지한 채 단일 `t3.small` EC2에 BE·AI·Caddy 병행 실행 경로를 추가하고 기존 개발 배포를 EC2에도 미러링한다.

**구조:** 기존 dev `app-platform`의 VPC, subnet, ECR, S3, SQS, CloudWatch Log Group을 재사용하는 EC2를 dev root에 직접 추가한다. BE와 AI workflow는 ECS 배포 성공 후 동일 Git SHA 이미지를 SSM Run Command로 EC2에 배포하며, DNS 전환과 ECS·ALB 제거는 이번 구현과 apply 범위에서 제외한다.

**기술:** Terraform, AWS EC2, IAM, SSM, ECR, Docker Compose, Caddy, Bash, GitHub Actions.

## Global Constraints

- 작업 이슈와 브랜치는 LAN-284와 `feat/284`를 사용한다. BE·AI 저장소는 각 저장소 규칙에 따라 `feat/LAN-284`를 사용한다.
- 기존 개발 ECS API·AI Service와 ALB는 변경하거나 제거하지 않는다.
- 운영 환경과 shared root는 변경하지 않는다.
- Terraform state, user-data, GitHub Actions 로그에 SSM 값이나 secret을 남기지 않는다.
- 실제 Terraform apply, Vercel DNS 변경, GitHub 변수 변경은 사용자 별도 승인 전까지 실행하지 않는다.
- 2026-08-08 dev baseline plan의 LAN-184 `1 add, 2 change, 8 destroy`는 당시 기록으로 보존한다. 최신 적용 판단은 2026-08-15 사전 검증 계획을 따른다.
- EC2 관련 신규 source 파일은 필수 directive 아래 첫 줄에 한국어 역할 주석을 둔다.

---

### Task 1: EC2 인프라 계약 테스트와 app-platform 출력

**Files:**
- Create: `scripts/test-dev-ec2-contract.sh`
- Modify: `modules/app-platform/outputs.tf`

**Interfaces:**
- Consumes: 기존 `aws_vpc.this`, `aws_subnet.public`, ECR, S3, SQS, CloudWatch Log Group 리소스.
- Produces: `vpc_id`, `public_subnet_ids`, ECR ARN·URL, app bucket ARN·이름, jobs Queue ARN·URL, API·worker Log Group ARN·이름 output.

- [ ] **Step 1: 신규 dev EC2 계약 테스트를 작성한다.**

`scripts/test-dev-ec2-contract.sh`에서 `rg`로 아래 계약을 검사한다.

```bash
#!/usr/bin/env bash
# 개발 EC2 병행 인프라의 보안과 기존 리소스 보존 계약을 검증한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_OUTPUTS="${ROOT_DIR}/modules/app-platform/outputs.tf"
for output_name in vpc_id public_subnet_ids api_ecr_repository_arn worker_ecr_repository_arn app_bucket_arn jobs_queue_arn api_log_group_name worker_log_group_name; do
  rg -q "output \"${output_name}\"" "${MODULE_OUTPUTS}"
done
```

- [ ] **Step 2: 계약 테스트가 예상대로 실패하는지 확인한다.**

Run: `bash scripts/test-dev-ec2-contract.sh`.

Expected: `output "vpc_id"`가 없어 실패한다.

- [ ] **Step 3: app-platform에 EC2가 소비할 출력만 추가한다.**

`modules/app-platform/outputs.tf`에 기존 리소스를 그대로 노출하는 output을 추가한다. 새 리소스나 기존 동작 변경은 만들지 않는다.

```hcl
output "vpc_id" {
  description = "VPC ID for environment-specific companion resources."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs for environment-specific companion resources."
  value       = values(aws_subnet.public)[*].id
}
```

같은 형식으로 ECR ARN, app bucket ARN, jobs Queue ARN, API·worker Log Group ARN·이름을 출력한다.

- [ ] **Step 4: output 계약이 통과하는지 확인한다.**

Run: `bash scripts/test-dev-ec2-contract.sh`.

Expected: 모든 module output 검사가 통과한다.

- [ ] **Step 5: 출력 변경을 검증하고 커밋한다.**

Run: `terraform fmt -recursive -check && AWS_PROFILE=landit terraform -chdir=environments/dev validate`.

Expected: fmt와 validate가 통과한다.

```bash
git add scripts/test-dev-ec2-contract.sh modules/app-platform/outputs.tf
git commit -m "test: 개발 EC2 리소스 계약과 모듈 출력을 추가한다"
```

### Task 2: 단일 EC2와 최소 권한 IAM 구성

**Files:**
- Create: `environments/dev/ec2.tf`
- Modify: `environments/dev/variables.tf`
- Modify: `environments/dev/outputs.tf`
- Modify: `scripts/test-dev-ec2-contract.sh`

**Interfaces:**
- Consumes: Task 1의 app-platform outputs, `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`, 기존 `landit-github-actions-develop-deploy` role.
- Produces: `aws_instance.app`, `aws_eip.app`, instance profile, `ec2_instance_id`, `ec2_public_ip` output과 GitHub role의 SSM SendCommand 권한.

- [ ] **Step 1: 인프라 보안 계약을 테스트에 추가한다.**

아래 항목을 `scripts/test-dev-ec2-contract.sh`에 추가한다.

```bash
DEV_EC2="${ROOT_DIR}/environments/dev/ec2.tf"
test -f "${DEV_EC2}"
rg -q 'instance_type[[:space:]]*=[[:space:]]*var.dev_ec2_instance_type' "${DEV_EC2}"
rg -q 'default[[:space:]]*=[[:space:]]*"t3.small"' "${ROOT_DIR}/environments/dev/variables.tf"
rg -q 'http_tokens[[:space:]]*=[[:space:]]*"required"' "${DEV_EC2}"
rg -q 'http_put_response_hop_limit[[:space:]]*=[[:space:]]*2' "${DEV_EC2}"
rg -q 'cpu_credits[[:space:]]*=[[:space:]]*"standard"' "${DEV_EC2}"
rg -q 'encrypted[[:space:]]*=[[:space:]]*true' "${DEV_EC2}"
rg -q 'volume_size[[:space:]]*=[[:space:]]*20' "${DEV_EC2}"
if rg -q 'from_port[[:space:]]*=[[:space:]]*22' "${DEV_EC2}"; then
  echo '계약 위반. SSH 22번 포트를 열면 안 된다.' >&2
  exit 1
fi
```

- [ ] **Step 2: 새 보안 계약이 실패하는지 확인한다.**

Run: `bash scripts/test-dev-ec2-contract.sh`.

Expected: `environments/dev/ec2.tf`가 없어 실패한다.

- [ ] **Step 3: dev 전용 EC2 리소스를 최소 구성으로 추가한다.**

`environments/dev/ec2.tf`에 다음 리소스를 추가한다.

- AL2023 x86_64 public SSM AMI data.
- EC2 trust role, instance profile, `AmazonSSMManagedInstanceCore` attachment.
- ECR pull, `/landit/develop/*`, KMS via SSM, 기존 S3·SQS, 기존 CloudWatch Log Group, `Landit/EC2` PutMetricData 정책.
- 80·443 ingress와 전체 egress만 있는 security group.
- 첫 번째 기존 public subnet의 `t3.small` EC2, IMDSv2 required, hop limit 2, T3 standard credit, 암호화된 gp3 20GB.
- Elastic IP 연결.
- 기존 GitHub deploy role에 해당 instance와 검증된 `api|ai`, 40자리 SHA만 받는 전용 SSM 문서만 허용하는 SendCommand inline policy.

`environments/dev/variables.tf`에는 `dev_ec2_instance_type` 기본값 `t3.small`과 두 임시 검증 도메인만 추가한다. `environments/dev/outputs.tf`에는 instance ID와 public IP를 추가한다.

- [ ] **Step 4: 인프라 계약을 다시 실행한다.**

Run: `bash scripts/test-dev-ec2-contract.sh`.

Expected: EC2 보안 계약이 모두 통과한다.

- [ ] **Step 5: Terraform 정적 검증을 실행한다.**

Run: `terraform fmt -recursive && terraform fmt -recursive -check && AWS_PROFILE=landit terraform -chdir=environments/dev validate`.

Expected: 모두 통과한다.

- [ ] **Step 6: EC2 인프라 변경을 커밋한다.**

```bash
git add environments/dev/ec2.tf environments/dev/variables.tf environments/dev/outputs.tf scripts/test-dev-ec2-contract.sh
git commit -m "feat: 기존 개발 플랫폼에 단일 EC2 실행 경로를 추가한다"
```

### Task 3: EC2 Docker Compose와 안전한 배포 runtime

**Files:**
- Create: `environments/dev/templates/ec2-user-data.sh.tftpl`
- Create: `environments/dev/templates/docker-compose.yml.tftpl`
- Create: `environments/dev/templates/Caddyfile.tftpl`
- Modify: `environments/dev/ec2.tf`
- Modify: `scripts/test-dev-ec2-contract.sh`

**Interfaces:**
- Consumes: EC2 instance role, ECR URL, S3 bucket, SQS Queue, Log Group, 임시 도메인.
- Produces: `/opt/landit/compose.yml`, `/opt/landit/Caddyfile`, `/opt/landit/bin/deploy-service`, `/run/landit/api.env`, `/run/landit/ai.env`.

- [ ] **Step 1: runtime 계약을 테스트에 추가한다.**

아래 항목을 검사한다.

```bash
USER_DATA="${ROOT_DIR}/environments/dev/templates/ec2-user-data.sh.tftpl"
COMPOSE="${ROOT_DIR}/environments/dev/templates/docker-compose.yml.tftpl"
CADDY="${ROOT_DIR}/environments/dev/templates/Caddyfile.tftpl"
test -f "${USER_DATA}"
test -f "${COMPOSE}"
test -f "${CADDY}"
rg -q 'LANDIT_AI_BASE_URL=http://ai:8000' "${USER_DATA}"
rg -q 'chmod 0600' "${USER_DATA}"
rg -q 'flock' "${USER_DATA}"
rg -q 'mkswap' "${USER_DATA}"
rg -q 'amazon-cloudwatch-agent' "${USER_DATA}"
rg -q 'mem_limit: 768m' "${COMPOSE}"
rg -q 'mem_limit: 512m' "${COMPOSE}"
rg -q '127.0.0.1:8080:8080' "${COMPOSE}"
rg -q '127.0.0.1:8000:8000' "${COMPOSE}"
rg -q 'awslogs-group' "${COMPOSE}"
rg -q 'reverse_proxy api:8080' "${CADDY}"
rg -q 'reverse_proxy ai:8000' "${CADDY}"
```

- [ ] **Step 2: runtime 계약이 파일 부재로 실패하는지 확인한다.**

Run: `bash scripts/test-dev-ec2-contract.sh`.

Expected: 첫 번째 누락 runtime 계약에서 실패한다.

- [ ] **Step 3: Compose와 Caddy 설정을 추가한다.**

Compose는 `api`, `ai`, `caddy` 세 서비스와 내부 network 하나만 정의한다. API·AI는 loopback에만 publish하고 Caddy만 80·443을 공개한다. 이미지는 `${API_IMAGE}:${API_TAG}`, `${AI_IMAGE}:${AI_TAG}`를 사용하고 기존 CloudWatch Log Group으로 `awslogs`를 전송한다.

Caddy는 `api-ec2-develop.landit.im`과 `ai-ec2-develop.landit.im`을 각각 `api:8080`, `ai:8000`으로 전달한다.

- [ ] **Step 4: user-data bootstrap을 추가한다.**

Bootstrap은 다음 순서만 수행한다.

1. Docker, jq, curl, amazon-cloudwatch-agent와 고정 버전 Docker Compose plugin을 설치한다.
2. 2GB swap, Compose, Caddy, 이미지 tag 파일을 만든다.
3. SSM 값을 `/run/landit/*.env`에 `0600`으로 만들고 EC2 API에만 내부 AI URL을 기록한다.
4. ECR login 후 기존 `latest` 이미지를 최초 기동한다.
5. `deploy-service api|ai <40자리 Git SHA>`를 설치한다. 스크립트는 `flock`, SSM refresh, ECR login, 해당 서비스 pull·up, loopback health 확인을 수행한다.
6. CloudWatch agent로 host CPU, memory, swap, disk 지표를 `Landit/EC2` namespace에 보낸다. `CPUCreditBalance`는 AWS가 제공하는 `AWS/EC2` native metric으로 확인한다.

- [ ] **Step 5: 전체 정적 계약과 Terraform validate를 통과시킨다.**

Run: `bash scripts/test-dev-ec2-contract.sh && terraform fmt -recursive && terraform fmt -recursive -check && AWS_PROFILE=landit terraform -chdir=environments/dev validate`.

Expected: 모두 통과한다.

- [ ] **Step 6: runtime 구성을 커밋한다.**

```bash
git add environments/dev/ec2.tf environments/dev/templates scripts/test-dev-ec2-contract.sh
git commit -m "feat: 개발 BE와 AI를 Compose로 병행 실행한다"
```

### Task 4: IaC plan 경계와 운영 문서 검증

**Files:**
- Modify: `README.md`
- Modify: `docs/developer-guide.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**
- Consumes: Task 1~3의 Terraform과 runtime 계약.
- Produces: apply 전 검토 가능한 plan 증거와 병행 운영·복구 절차.

- [ ] **Step 1: 전체 IaC 검증을 실행한다.**

Run:

```bash
bash scripts/test-dev-ec2-contract.sh
terraform fmt -recursive
terraform fmt -recursive -check
AWS_PROFILE=landit terraform -chdir=environments/dev validate
```

Expected: 모두 통과한다.

- [ ] **Step 2: dev saved plan과 JSON을 만든다.**

Run:

```bash
AWS_PROFILE=landit terraform -chdir=environments/dev plan -input=false -out=/tmp/lan284-dev.tfplan
terraform -chdir=environments/dev show -json /tmp/lan284-dev.tfplan > /tmp/lan284-dev-plan.json
```

Expected: 기준 plan 대비 EC2, EIP, IAM, SSM 문서, security group 관련 create만 추가된다. 기존 ECS·ALB 주소에는 LAN-284로 인한 변경이 없다.

- [ ] **Step 3: plan 주소를 감사한다.**

Run:

```bash
jq -r '.resource_changes[] | select(.change.actions != ["no-op"]) | [.address, (.change.actions | join(","))] | @tsv' /tmp/lan284-dev-plan.json
```

Expected: 승인된 LAN-284 관련 주소만 출력된다. LAN-184 항목이 다시 나타나면 LAN-284와 분리해 별도 승인 대상으로 기록한다.

- [ ] **Step 4: README와 개발자 가이드를 갱신한다.**

다음 내용만 반영한다.

- 개발 환경은 ECS·ALB와 단일 EC2를 병행 운영 중이다.
- apply → loopback 검증 → 임시 DNS → 외부 검증 → dual deploy → 24~48시간 관찰 → 원래 DNS 전환 → 별도 ECS·ALB 제거 순서다.
- SSM 배포와 직전 SHA 롤백 명령, ECS 복구 경계를 적는다.
- 실제 apply와 DNS 변경은 승인 전까지 실행하지 않았다고 기록한다.

- [ ] **Step 5: 체크리스트와 context-notes에 실제 검증 결과를 기록한다.**

추정이나 예정 결과를 완료로 표시하지 않고 실행한 명령과 plan 결과만 적는다.

- [ ] **Step 6: 문서와 검증 결과를 커밋한다.**

```bash
git add README.md docs/developer-guide.md checklist.md context-notes.md
git commit -m "docs: 개발 EC2 병행 운영과 검증 절차를 기록한다"
```

### Task 5: BE 개발 배포를 EC2에 미러링

**Files:**
- Create worktree: `/Users/sangmin8817/Soma/landit-be/.worktrees/lan-284` from `origin/develop` on `feat/LAN-284`.
- Create: `.github/scripts/deploy-ec2-service.sh`
- Create: `.github/scripts/test/deploy-ec2-service_test.sh`
- Modify: `.github/workflows/deploy-dev.yml`
- Create: `docs/tasks/LAN-284/plan.md`

**Interfaces:**
- Consumes: GitHub Environment variable `EC2_INSTANCE_ID`, `${GITHUB_SHA}`, existing develop deploy role.
- Produces: ECS 검증 후 `/opt/landit/bin/deploy-service api ${GITHUB_SHA}` SSM 실행과 성공 여부.

- [ ] **Step 1: 기존 사용자 작업을 건드리지 않는 BE worktree를 만든다.**

Run: worktree 격리 확인 후 `git worktree add .worktrees/lan-284 -b feat/LAN-284 origin/develop`.

Expected: 기존 `feat/LAN-282` dirty checkout은 그대로이고 새 worktree가 clean이다.

- [ ] **Step 2: fake aws를 사용하는 실패 테스트를 작성한다.**

테스트는 다음 동작을 검증한다.

- `EC2_INSTANCE_ID`, service, image tag 누락 시 실패한다.
- service가 `api` 또는 `ai`가 아니면 AWS를 호출하지 않고 실패한다.
- SendCommand가 반환한 command ID로 `get-command-invocation`을 polling한다.
- `Success`만 성공하고 `Failed`, `TimedOut`, `Cancelled`는 실패한다.
- SSM command는 `sudo /opt/landit/bin/deploy-service api <SHA>`만 전달한다.

- [ ] **Step 3: 테스트가 helper 부재로 실패하는지 확인한다.**

Run: `bash .github/scripts/test/deploy-ec2-service_test.sh`.

Expected: `.github/scripts/deploy-ec2-service.sh` 부재로 실패한다.

- [ ] **Step 4: 최소 SSM 배포 helper를 구현한다.**

Helper는 AWS CLI `ssm send-command`와 `ssm get-command-invocation`만 사용한다. secret이나 전체 command stdout을 출력하지 않는다.

- [ ] **Step 5: helper 테스트를 통과시킨다.**

Run: `bash .github/scripts/test/deploy-ec2-service_test.sh`.

Expected: 모든 shell test가 통과한다.

- [ ] **Step 6: 기존 ECS 검증 뒤 EC2 배포 단계를 추가한다.**

`.github/workflows/deploy-dev.yml`에 `EC2_INSTANCE_ID`를 추가하고 기존 `Verify ECS service` 다음에 아래 단계만 추가한다.

```yaml
- name: Deploy the same image to develop EC2
  env:
    EC2_INSTANCE_ID: ${{ vars.EC2_INSTANCE_ID }}
  run: bash .github/scripts/deploy-ec2-service.sh api "$GITHUB_SHA"
```

- [ ] **Step 7: BE 전체 검증을 실행한다.**

Run: `bash .github/scripts/test/deploy-ec2-service_test.sh && ./gradlew check --rerun-tasks --no-daemon`.

Expected: shell test와 Gradle check가 통과한다.

- [ ] **Step 8: BE 변경을 논리 단위로 커밋한다.**

```bash
git add .github/scripts/deploy-ec2-service.sh .github/scripts/test/deploy-ec2-service_test.sh
git commit -m "deploy: 개발 EC2 배포 명령을 검증한다"
git add .github/workflows/deploy-dev.yml docs/tasks/LAN-284/plan.md
git commit -m "deploy: ECS 성공 이미지를 개발 EC2에 미러링한다"
```

### Task 6: AI 개발 배포를 EC2에 미러링

**Files:**
- Create worktree: `/Users/sangmin8817/Soma/landit-ai/.worktrees/lan-284` from `origin/develop` on `feat/LAN-284`.
- Create: `.github/scripts/deploy-ec2-service.sh`
- Create: `.github/scripts/test/deploy-ec2-service_test.sh`
- Modify: `.github/workflows/deploy-dev-worker.yml`
- Create: `docs/tasks/LAN-284/plan.md`

**Interfaces:**
- Consumes: GitHub Environment variable `EC2_INSTANCE_ID`, `${GITHUB_SHA}`, existing develop deploy role.
- Produces: ECS 검증 후 `/opt/landit/bin/deploy-service ai ${GITHUB_SHA}` SSM 실행과 성공 여부.

- [ ] **Step 1: 기존 사용자 작업을 건드리지 않는 AI worktree를 만든다.**

Run: worktree 격리 확인 후 `git worktree add .worktrees/lan-284 -b feat/LAN-284 origin/develop`.

Expected: 기존 `feat/LAN-252` checkout의 `tmp/`는 그대로이고 새 worktree가 clean이다.

- [ ] **Step 2: BE와 동일한 helper 계약을 AI 저장소에서 실패 테스트로 작성한다.**

Run: `bash .github/scripts/test/deploy-ec2-service_test.sh`.

Expected: helper 부재로 실패한다.

- [ ] **Step 3: 검증된 최소 SSM helper를 AI 저장소에 구현한다.**

BE helper와 같은 CLI 계약을 사용하되 저장소 사이에 공용 패키지나 새 의존성을 만들지 않는다.

- [ ] **Step 4: helper 테스트를 통과시킨다.**

Run: `bash .github/scripts/test/deploy-ec2-service_test.sh`.

Expected: 모든 shell test가 통과한다.

- [ ] **Step 5: 기존 ECS 검증 뒤 AI EC2 배포 단계를 추가한다.**

`.github/workflows/deploy-dev-worker.yml`에 `EC2_INSTANCE_ID`를 추가하고 기존 `Verify ECS service` 다음에 `bash .github/scripts/deploy-ec2-service.sh ai "$GITHUB_SHA"`를 실행한다.

- [ ] **Step 6: AI 전체 검증을 실행한다.**

Run: `bash .github/scripts/test/deploy-ec2-service_test.sh && .venv/bin/python -m unittest discover -s tests`.

Expected: shell test와 전체 unittest가 통과한다.

- [ ] **Step 7: AI 변경을 논리 단위로 커밋한다.**

```bash
git add .github/scripts/deploy-ec2-service.sh .github/scripts/test/deploy-ec2-service_test.sh
git commit -m "deploy: 개발 EC2 배포 명령을 검증한다"
git add .github/workflows/deploy-dev-worker.yml docs/tasks/LAN-284/plan.md
git commit -m "deploy: ECS 성공 이미지를 개발 EC2에 미러링한다"
```

### Task 7: 교차 저장소 최종 검증과 독립 리뷰

**Files:**
- Modify: `checklist.md`
- Modify: `context-notes.md`
- Modify: `docs/tasks/LAN-284/plan.md` in BE and AI only with actual verification results.

**Interfaces:**
- Consumes: 세 저장소의 LAN-284 diff와 검증 출력.
- Produces: apply 전 코드 완료 증거와 남은 외부 변경 목록.

- [ ] **Step 1: 세 저장소의 diff와 상태를 확인한다.**

Run: 각 worktree에서 `git diff origin/main...HEAD` 또는 `git diff origin/develop...HEAD`, `git status --short`.

Expected: LAN-284 파일만 변경되고 사용자 원본 checkout의 dirty 파일은 건드리지 않는다.

- [ ] **Step 2: IaC와 애플리케이션 검증을 새로 실행한다.**

Run:

```bash
# landit-iac
bash scripts/test-dev-ec2-contract.sh
terraform fmt -recursive -check
AWS_PROFILE=landit terraform -chdir=environments/dev validate

# landit-be
bash .github/scripts/test/deploy-ec2-service_test.sh
./gradlew check --rerun-tasks --no-daemon

# landit-ai
bash .github/scripts/test/deploy-ec2-service_test.sh
.venv/bin/python -m unittest discover -s tests
```

Expected: 모든 검증이 통과한다.

- [ ] **Step 3: 고위험 독립 리뷰를 수행한다.**

독립 Sol reviewer가 세 저장소 diff, Terraform plan 주소, secret 처리, IAM, 기존 ECS 우선 배포, rollback 절차를 검토한다. blocker가 있으면 수정하고 최대 두 번 재검토한다.

- [ ] **Step 4: 검증 결과와 미적용 상태를 기록한다.**

`checklist.md`, `context-notes.md`, BE·AI plan 문서에 실행 명령과 결과를 기록한다. 실제 apply, DNS, GitHub 변수, ECS·ALB 제거가 미실행임을 명시한다.

- [ ] **Step 5: 최종 문서 기록을 커밋한다.**

```bash
git add checklist.md context-notes.md
git commit -m "docs: LAN-284 구현과 적용 전 검증 결과를 기록한다"
```

## 적용 후 별도 승인 단계

아래 단계는 이번 코드 구현 완료와 분리한다.

1. 최신 main의 기준 plan이 `No changes`인지 확인한다. LAN-184 drift가 다시 나타날 때만 별도 처리 방향을 승인한다.
2. dev saved plan 검토와 Terraform apply 승인을 받는다.
3. EC2 loopback 검증 뒤 임시 Vercel DNS 두 개를 등록하고 외부 검증한다.
4. GitHub Environment `EC2_INSTANCE_ID`를 등록한다.
5. BE·AI dual deploy와 24~48시간 관찰을 수행한다.
6. 원래 개발 DNS의 EC2 전환 승인을 받는다.
7. 기존 ECS·ALB 제거 설계와 별도 Terraform apply 승인을 받는다.
