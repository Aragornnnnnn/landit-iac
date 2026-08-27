# LAN-347 Terraform Actions OIDC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** public `landit-iac` 저장소에 target·phase별 OIDC 역할, private saved-plan 전달과 GitHub environment 구성을 추가하고 develop·production API가 shared inbox 객체를 조회할 수 있게 한다.

**Architecture:** `bootstrap/terraform-actions`가 기존 GitHub OIDC provider를 조회하고 역할 6개와 전용 private plan 버킷을 소유한다. workflow의 speculative plan은 파일을 저장하지 않고, apply용 saved plan만 실행별 S3 key와 SHA-256으로 전달한다. 콘텐츠 권한은 기존 develop EC2와 production ECS API statement에 `s3:GetObject`만 추가한다.

**Tech Stack:** Terraform >= 1.6, AWS provider >= 5 and < 7, GitHub Actions OIDC, S3, Bash 계약 테스트, GitHub REST API.

**Spec:** `docs/superpowers/specs/2026-08-27-lan-347-terraform-actions-oidc-design.md`.

## Global Constraints

- 저장소는 public으로 유지한다.
- 역할은 shared·develop·production의 plan·apply 6개로 분리한다.
- OIDC trust는 `repo:Aragornnnnnn/landit-iac:environment:terraform-{phase}-{target}` 정확 일치만 허용한다.
- apply environment는 `main`만 허용하며 required reviewer는 설정하지 않는다.
- saved plan은 GitHub artifact에 올리지 않고 private S3에서 1일만 보관한다.
- 기존 `bootstrap/github-actions` state와 BE·AI 배포 역할은 변경하지 않는다.
- `GetObject`는 develop EC2와 production ECS API의 `content/inbox/*`에만 추가한다.
- bootstrap apply와 GitHub environment write는 saved plan 검토 후 별도 사용자 승인 전까지 실행하지 않는다.

---

### Task 1: Shared inbox GetObject 최소 권한

**Files:**
- Modify: `scripts/test-admin-content-upload-contract.sh`.
- Modify: `environments/dev/ec2.tf`.
- Modify: `modules/app-platform/main.tf`.
- Modify: `docs/content-storage.md`.

**Interfaces:**
- Consumes: 기존 shared `content/inbox/*` PutObject statement와 `content_bucket_name` remote-state 계약.
- Produces: develop EC2 role과 production ECS API task role의 inbox Get·Put 계약.

- [x] **Step 1: 계약 테스트를 GetObject 요구사항으로 변경한다.**

`scripts/test-admin-content-upload-contract.sh`에 dev EC2 policy block과 API policy block을 추출하고 다음 검사를 추가한다.

```bash
assert_contains "${dev_ec2_policy}" '"s3:GetObject"' "develop EC2는 inbox 객체를 조회할 수 있어야 한다."
assert_contains "${dev_ec2_policy}" '"s3:PutObject"' "develop EC2는 inbox 객체를 업로드할 수 있어야 한다."
assert_contains "${api_policy}" '"s3:GetObject"' "API Task Role은 inbox 객체를 조회할 수 있어야 한다."
assert_contains "${api_policy}" '"s3:PutObject"' "API Task Role은 inbox 객체를 업로드할 수 있어야 한다."
assert_not_contains "${worker_policy}" 'content_bucket_name' "worker IAM에는 shared 콘텐츠 bucket 권한을 추가하면 안 된다."
```

- [x] **Step 2: RED 테스트를 확인한다.**

Run: `bash scripts/test-admin-content-upload-contract.sh`.

Expected: develop 또는 API의 `s3:GetObject` 누락으로 실패한다.

- [x] **Step 3: 두 기존 statement에 GetObject를 추가한다.**

`environments/dev/ec2.tf`와 `modules/app-platform/main.tf`에서 shared inbox statement만 다음 형태로 바꾼다.

```hcl
statement {
  actions = [
    "s3:GetObject",
    "s3:PutObject"
  ]
  resources = ["arn:aws:s3:::${content_bucket_name}/content/inbox/*"]
}
```

각 파일의 기존 bucket-name expression은 그대로 사용한다. application bucket statement, worker policy와 shared bucket policy는 바꾸지 않는다.

- [x] **Step 4: 문서와 GREEN 테스트를 갱신한다.**

`docs/content-storage.md`의 develop EC2 설명과 API 역할 설명을 `GetObject`, `PutObject`로 맞춘다.

Run: `bash scripts/test-admin-content-upload-contract.sh`.

Expected: `관리자 콘텐츠 이미지 업로드 IaC 계약이 통과했다.`.

- [x] **Step 5: 첫 논리 변경을 커밋한다.**

```bash
git add scripts/test-admin-content-upload-contract.sh environments/dev/ec2.tf modules/app-platform/main.tf docs/content-storage.md
git commit -m "chore: 콘텐츠 inbox 조회 권한을 추가한다"
```

### Task 2: Terraform Actions bootstrap과 계약 테스트

**Files:**
- Create: `scripts/test-terraform-actions-oidc-contract.sh`.
- Create: `bootstrap/terraform-actions/backend.tf`.
- Create: `bootstrap/terraform-actions/versions.tf`.
- Create: `bootstrap/terraform-actions/providers.tf`.
- Create: `bootstrap/terraform-actions/variables.tf`.
- Create: `bootstrap/terraform-actions/locals.tf`.
- Create: `bootstrap/terraform-actions/main.tf`.
- Create: `bootstrap/terraform-actions/outputs.tf`.
- Create: `bootstrap/terraform-actions/.terraform.lock.hcl` through `terraform init`.

**Interfaces:**
- Consumes: account `982529430654`, region `ap-northeast-2`, existing GitHub OIDC provider and state bucket.
- Produces: six role ARN outputs and `plan_bucket_name` output for GitHub environment configuration.

- [x] **Step 1: bootstrap 정적 계약 테스트를 작성한다.**

새 Bash 테스트는 다음 정확한 계약을 `grep -F`와 block 추출로 검사한다.

```text
backend key = bootstrap/terraform-actions/terraform.tfstate
OIDC provider = data.aws_iam_openid_connect_provider.github
role count = 6
aud = sts.amazonaws.com
sub = repo:Aragornnnnnn/landit-iac:environment:terraform-{phase}-{target}
plan bucket public access = all four true
server-side encryption = AES256
lifecycle expiration = 1 day
plan role state PutObject = absent
apply role state PutObject = present
plan role plan-prefix PutObject = present
apply role plan-prefix GetObject = present
plan/apply role plan-prefix DeleteObject = absent
AdministratorAccess, PowerUserAccess, ReadOnlyAccess, iam:* = absent
```

- [x] **Step 2: RED 테스트를 확인한다.**

Run: `bash scripts/test-terraform-actions-oidc-contract.sh`.

Expected: `bootstrap/terraform-actions`가 없어 실패한다.

- [x] **Step 3: provider와 backend 뼈대를 만든다.**

버전 제약은 기존 bootstrap과 같은 Terraform `>= 1.6.0`, AWS provider `>= 5.0, < 7.0`을 사용한다. backend는 다음 값으로 고정한다.

```hcl
terraform {
  backend "s3" {
    bucket       = "landit-terraform-state-982529430654"
    key          = "bootstrap/terraform-actions/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
```

- [x] **Step 4: locals와 OIDC trust를 구현한다.**

`targets = toset(["shared", "develop", "production"])`, `phases = toset(["plan", "apply"])`와 두 집합의 product로 여섯 역할을 만든다. provider ARN은 다음 URL의 data source로 찾는다.

```hcl
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}
```

각 assume-role policy는 `aud`와 환경별 `sub` 두 `StringEquals` 조건만 둔다.

- [x] **Step 5: private plan bucket을 구현한다.**

bucket 이름 기본값은 `landit-terraform-plan-artifacts-982529430654`이다. public access block 네 항목, AES256 encryption, HTTPS-only bucket policy와 다음 lifecycle을 추가한다.

```hcl
rule {
  id     = "expire-terraform-plans"
  status = "Enabled"
  filter { prefix = "plans/" }
  expiration { days = 1 }
  abort_incomplete_multipart_upload { days_after_initiation = 1 }
}
```

- [x] **Step 6: target·phase별 inline policy를 구현한다.**

state S3 권한은 target key와 `${target_key}.tflock`에만 부여한다. develop·production에는 shared state `GetObject`를 추가한다. plan role은 state `GetObject`, lockfile `GetObject|PutObject|DeleteObject`만, apply role은 여기에 state `PutObject`를 추가한다.

AWS 조회 action은 root가 사용하는 서비스의 `Describe*`, `Get*`, `List*` 중 Terraform refresh에 필요한 명시적 action만 둔다. SSM 값 조회는 public AL2023 AMI parameter ARN으로 제한한다. apply action은 현재 root의 AWS resource type에 대응하는 create·update·delete action을 명시하고 `iam:PassRole`은 `landit-*` runtime role ARN 및 `iam:PassedToService` 조건으로 제한한다.

plan 객체 권한은 `arn:aws:s3:::${bucket}/plans/${target}/*`에 plan `PutObject`, apply `GetObject`만 부여한다. bucket 조회는 자기 prefix에 대한 `s3:ListBucket` 조건으로 제한한다.

- [x] **Step 7: output과 GREEN 검증을 수행한다.**

outputs는 `plan_role_arns`, `apply_role_arns`, `plan_bucket_name` map/string만 노출한다.

Run:

```bash
bash scripts/test-terraform-actions-oidc-contract.sh
terraform fmt -recursive
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions init -backend=false
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions validate
```

Expected: 계약 테스트 통과와 `Success! The configuration is valid.`.

- [x] **Step 8: bootstrap 구현을 커밋한다.**

```bash
git add bootstrap/terraform-actions scripts/test-terraform-actions-oidc-contract.sh
git commit -m "chore: Terraform Actions OIDC 역할을 정의한다"
```

### Task 3: Private S3 plan handoff workflow

**Files:**
- Create: `scripts/test-terraform-workflow-contract.sh`.
- Modify: `.github/workflows/terraform.yml`.
- Modify: `docs/developer-guide.md`.

**Interfaces:**
- Consumes: environment `AWS_ROLE_ARN`, bootstrap output `plan_bucket_name`, GitHub run ID와 attempt.
- Produces: artifact 없이 speculative plan 또는 SHA-256 검증 saved-plan apply를 실행하는 workflow.

- [x] **Step 1: workflow RED 계약 테스트를 작성한다.**

테스트는 다음을 검사한다.

```text
actions/upload-artifact absent
actions/download-artifact absent
PLAN_BUCKET=landit-terraform-plan-artifacts-982529430654
plan-only executes terraform plan without -out
plan-and-apply key contains target/run_id/run_attempt
aws s3 cp uploads and downloads exact key
sha256sum is generated and checked
apply remains main-only
production confirmation remains
checkout SHA = 11d5960a326750d5838078e36cf38b85af677262
setup-terraform SHA = b9cd54a3c349d3f38e8881555d616ced269862dd
configure-aws-credentials SHA = ff717079ee2060e4bcee96c4779b553acc87447c
```

- [x] **Step 2: RED 테스트를 확인한다.**

Run: `bash scripts/test-terraform-workflow-contract.sh`.

Expected: GitHub artifact step과 mutable action tag 때문에 실패한다.

- [x] **Step 3: plan-only와 plan-and-apply를 분리한다.**

`plan-only` step은 `terraform plan -input=false`만 실행한다. `plan-and-apply` step은 `$RUNNER_TEMP/${plan-file}`로 saved plan을 만들고 표시한 뒤 다음 key를 job output으로 내보낸다.

```text
plans/${target}/${GITHUB_RUN_ID}/${GITHUB_RUN_ATTEMPT}/${plan-file}
```

saved plan의 `sha256sum` 첫 필드를 `plan-sha256` output으로 기록하고 `aws s3 cp`로 전용 bucket의 정확한 key에 올린다.

- [x] **Step 4: apply 다운로드와 integrity gate를 구현한다.**

apply job은 exact key를 `$RUNNER_TEMP/terraform-plan/${plan-file}`로 내려받고 다음 검증 뒤 같은 파일을 적용한다.

```bash
echo "${EXPECTED_PLAN_SHA256}  ${PLAN_PATH}" | sha256sum --check --strict
terraform -chdir="${ROOT}" apply -input=false "${PLAN_PATH}"
```

- [x] **Step 5: action ref와 운영 문서를 갱신한다.**

세 action을 위 commit SHA로 고정하고 원래 major tag를 주석으로 남긴다. `docs/developer-guide.md`에는 6개 environment, reviewer 없음, branch policy, private plan bucket, 1일 lifecycle과 별도 bootstrap apply gate를 기록한다.

- [x] **Step 6: GREEN 테스트와 YAML 구조를 확인한다.**

Run:

```bash
bash scripts/test-terraform-workflow-contract.sh
git diff --check
```

Expected: 계약 테스트와 whitespace 검증 통과.

- [x] **Step 7: workflow 변경을 커밋한다.**

```bash
git add .github/workflows/terraform.yml scripts/test-terraform-workflow-contract.sh docs/developer-guide.md
git commit -m "chore: Terraform plan을 private S3로 전달한다"
```

### Task 4: 전체 정적 검증과 bootstrap plan

**Files:**
- Modify: `checklist.md`.
- Modify: `context-notes.md`.

**Interfaces:**
- Consumes: Task 1~3의 Terraform, workflow와 계약 테스트.
- Produces: apply 승인 판단에 사용할 fresh bootstrap saved plan과 LAN-347 dev·prod plan 범위.

- [x] **Step 1: 전체 계약과 format을 실행한다.**

Run:

```bash
bash scripts/test-admin-content-upload-contract.sh
bash scripts/test-dev-ec2-contract.sh
bash scripts/test-dev-ec2-runtime.sh
bash scripts/test-terraform-actions-oidc-contract.sh
bash scripts/test-terraform-workflow-contract.sh
terraform fmt -recursive
terraform fmt -recursive -check
git diff --check
```

Expected: 모두 exit 0.

- [x] **Step 2: 네 root를 validate한다.**

Run:

```bash
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions init -backend=false
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions validate
AWS_PROFILE=landit terraform -chdir=environments/shared init -reconfigure
AWS_PROFILE=landit terraform -chdir=environments/shared validate
AWS_PROFILE=landit terraform -chdir=environments/dev init -reconfigure
AWS_PROFILE=landit terraform -chdir=environments/dev validate
AWS_PROFILE=landit terraform -chdir=environments/prod init -reconfigure
AWS_PROFILE=landit terraform -chdir=environments/prod validate
```

Expected: 네 root 모두 valid.

- [x] **Step 3: fresh saved plan을 만든다.**

Run:

```bash
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions init -reconfigure
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions plan -input=false -out=/tmp/lan347-terraform-actions.tfplan
AWS_PROFILE=landit terraform -chdir=environments/dev plan -input=false -out=/tmp/lan347-dev-getobject.tfplan
AWS_PROFILE=landit terraform -chdir=environments/prod plan -input=false -out=/tmp/lan347-prod-getobject.tfplan
```

Expected: bootstrap은 역할 6개·inline policy 6개·plan bucket 보안 리소스만 생성한다. dev는 기존 LAN-372·LAN-347 변경과 EC2 IAM GetObject만, prod는 LAN-347 task definition 교체·service update와 API IAM GetObject만 포함한다. destroy가 추가되면 중단한다.

- [x] **Step 4: 기록을 갱신하고 커밋한다.**

실제 plan summary, 변경 주소와 미실행 apply gate를 `checklist.md`, `context-notes.md`에 기록한다.

```bash
git add checklist.md context-notes.md
git commit -m "docs: Terraform OIDC plan 검증 결과를 기록한다"
```

### Task 5: 별도 승인 뒤 bootstrap과 GitHub environment 생성

**Files:**
- Modify: `checklist.md`.
- Modify: `context-notes.md`.

**Interfaces:**
- Consumes: 사용자가 승인한 `/tmp/lan347-terraform-actions.tfplan`과 실제 role ARN outputs.
- Produces: AWS OIDC 역할·plan bucket, GitHub environment 6개와 검증된 `AWS_ROLE_ARN`.

- [ ] **Step 1: 사용자에게 bootstrap saved plan 승인을 받는다.**

승인 전에는 아래 apply나 GitHub write를 실행하지 않는다.

- [ ] **Step 2: 승인된 saved plan을 적용하고 post-apply를 확인한다.**

Run:

```bash
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions apply -input=false /tmp/lan347-terraform-actions.tfplan
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions plan -input=false
```

Expected: apply 완료 후 `No changes.`.

- [ ] **Step 3: environment와 branch policy를 생성한다.**

각 `terraform-{phase}-{target}`에 대해 GitHub REST API로 environment를 만들고 `deployment_branch_policy`를 custom mode로 설정한다. plan에는 `main`, `feat/*`, apply에는 `main` policy를 만든다. required reviewers와 wait timer는 보내지 않는다.

- [ ] **Step 4: environment별 AWS_ROLE_ARN을 설정한다.**

bootstrap output의 정확한 target·phase role ARN을 다음 endpoint의 `value`로 설정한다.

```text
PUT /repos/Aragornnnnnn/landit-iac/environments/{environment_name}/variables/AWS_ROLE_ARN
```

- [ ] **Step 5: AWS와 GitHub live 구성을 재조회한다.**

여섯 role의 trust subject와 inline policy, plan bucket public block·encryption·lifecycle을 AWS API로 확인한다. GitHub API로 여섯 environment의 branch policy와 `AWS_ROLE_ARN` 변수 존재를 확인하되 ARN 이외 값은 출력하지 않는다.

- [ ] **Step 6: feature plan-only를 재실행한다.**

develop과 production `plan-only`를 실행하고 Terraform plan 단계까지 성공하는지 확인한다. plan-only run에 saved plan S3 object와 GitHub artifact가 생기지 않는지 검증한다.

- [ ] **Step 7: 결과를 기록하고 커밋한다.**

```bash
git add checklist.md context-notes.md
git commit -m "docs: Terraform Actions OIDC 구성을 검증한다"
```
