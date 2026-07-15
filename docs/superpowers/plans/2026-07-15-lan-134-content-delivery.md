# LAN-134 콘텐츠 이미지 CloudFront 제공 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** develop와 prod가 하나의 private 콘텐츠 버킷에 저장된 이미지를 CloudFront로 조회하도록 구성한다.

**Architecture:** 공유 리소스는 `environments/shared` root와 독립 state에서 관리한다. CloudFront OAC만 `content/*`를 읽고, 운영자는 S3에 새 UUID key로 업로드한 뒤 DB에 CloudFront URL을 저장한다.

**Tech Stack:** Terraform 1.6 이상, hashicorp/aws provider, Amazon S3, Amazon CloudFront, GitHub Actions.

## Global Constraints

- 콘텐츠 버킷은 public access를 허용하지 않는다.
- CloudFront OAC는 `content/*`만 원본에서 읽는다.
- 사용자 음성은 기존 환경별 application bucket에 남기며 이번 변경으로 application bucket IAM을 축소하지 않는다.
- 콘텐츠 교체는 새 UUID key와 DB URL 변경으로 수행하며 CloudFront invalidation을 사용하지 않는다.
- `terraform apply`는 plan 검토와 사용자 확인 뒤에만 실행한다.

---

### Task 1: 공유 콘텐츠 Terraform root 추가

**Files:**
- Create: `environments/shared/backend.tf`
- Create: `environments/shared/locals.tf`
- Create: `environments/shared/main.tf`
- Create: `environments/shared/outputs.tf`
- Create: `environments/shared/providers.tf`
- Create: `environments/shared/variables.tf`
- Create: `environments/shared/versions.tf`

**Interfaces:**
- Produces: `content_bucket_name`, `cloudfront_distribution_id`, `cloudfront_domain_name`, `cloudfront_url` outputs.
- Consumes: AWS account ID from `aws_caller_identity.current` and region `ap-northeast-2`.

- [x] **Step 1: 기존 root 검증 기준을 실행한다.**

Run: `terraform fmt -recursive -check && terraform -chdir=environments/dev validate && terraform -chdir=environments/prod validate`

Expected: 기존 dev와 prod root가 검증을 통과한다.

- [x] **Step 2: shared backend와 provider를 작성한다.**

```hcl
terraform {
  backend "s3" {
    bucket       = "landit-terraform-state-982529430654"
    key          = "shared/landit-iac/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
```

- [x] **Step 3: private 콘텐츠 버킷, OAC, CloudFront distribution과 bucket policy를 작성한다.**

```hcl
resource "aws_cloudfront_origin_access_control" "content" {
  name                              = "${local.name_prefix}-content"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
```

The S3 policy must allow `cloudfront.amazonaws.com` only when `AWS:SourceArn` equals this distribution ARN, and only for `${aws_s3_bucket.content.arn}/content/*`.

- [x] **Step 4: shared root를 초기화하고 검증한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/shared init -reconfigure && terraform -chdir=environments/shared validate`

Expected: provider schema and Terraform configuration validation succeed without creating resources.

### Task 2: 공유 root를 GitHub Actions workflow에 연결

**Files:**
- Modify: `.github/workflows/terraform.yml`

**Interfaces:**
- Consumes: workflow `target=shared`.
- Produces: root `environments/shared`, plan artifact `shared.tfplan`, state key `shared/landit-iac/terraform.tfstate`, and `terraform-apply-shared` approval environment.

- [x] **Step 1: workflow target 선택지에 `shared`를 추가한다.**

```yaml
options:
  - develop
  - production
  - shared
```

- [x] **Step 2: target resolution case를 추가한다.**

```bash
shared)
  echo "root=environments/shared" >> "$GITHUB_OUTPUT"
  echo "plan-file=shared.tfplan" >> "$GITHUB_OUTPUT"
  echo "state-key=shared/landit-iac/terraform.tfstate" >> "$GITHUB_OUTPUT"
  echo "apply-environment=terraform-apply-shared" >> "$GITHUB_OUTPUT"
  ;;
```

- [x] **Step 3: workflow YAML을 parse하고 shared root를 검증한다.**

Run: `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/terraform.yml")' && terraform -chdir=environments/shared validate`

Expected: YAML parsing and Terraform validation succeed.

### Task 3: 운영 문서와 작업 기록 갱신

**Files:**
- Create: `docs/content-storage.md`
- Modify: `README.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/architecture-questions.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

**Interfaces:**
- Produces: 운영자가 UUID key, cache header, CloudFront URL, DB 반영, 이전 파일 삭제 순서를 재현할 수 있는 문서.

- [x] **Step 1: 콘텐츠 key, CloudFront 조회, DB URL 반영, 교체 절차를 문서화한다.**

```text
content/scenarios/{scenarioId}/thumbnail/{assetId}.{ext}
content/scenarios/{scenarioId}/expressions/{expressionId}/practice-examples/{assetId}.{ext}
```

- [x] **Step 2: shared root와 GitHub environment 준비 항목을 README와 developer guide에 반영한다.**

The guide must name `terraform-plan-shared` and `terraform-apply-shared`, and state that apply remains main-branch-only and reviewer-gated.

- [x] **Step 3: CDN 결정을 architecture questions와 작업 기록에 반영한다.**

Record that no custom CDN domain is provisioned in this task and the CloudFront default domain is the initial DB URL base.

### Task 4: 포맷, validate, plan, 독립 검토

**Files:**
- Verify: all changed Terraform and documentation files.

- [x] **Step 1: Terraform 포맷과 정적 검증을 실행한다.**

Run: `terraform fmt -recursive && terraform fmt -recursive -check && terraform -chdir=environments/shared validate && terraform -chdir=environments/dev validate && terraform -chdir=environments/prod validate`

Expected: all commands exit 0.

- [x] **Step 2: shared root plan을 생성하고 변경 범위를 검토한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/shared plan -out=/tmp/lan-134-shared.tfplan`

Expected: only the content bucket, its private-access controls and policy, OAC, and CloudFront distribution are added.

- [x] **Step 3: diff와 독립 검토를 수행한다.**

Run: `git diff --check && git diff --stat && git status --short`

Expected: whitespace 오류와 의도하지 않은 파일 변경이 없다.

- [x] **Step 4: 검증된 논리 변경을 커밋한다.**

```bash
git add environments/shared .github/workflows/terraform.yml README.md docs checklist.md context-notes.md
git commit -m "feat: 공통 콘텐츠 CloudFront 조회 기반을 추가한다"
```
