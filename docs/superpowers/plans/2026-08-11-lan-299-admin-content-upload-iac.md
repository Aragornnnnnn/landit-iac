# LAN-299 관리자 콘텐츠 이미지 업로드 IaC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** shared 콘텐츠 버킷에 관리자 브라우저 업로드 CORS를 추가하고 develop·production API ECS에 `content/inbox/*` presigned PUT 권한과 콘텐츠 위치를 제공한다.

**Architecture:** dev·prod root가 shared remote state의 버킷명과 CloudFront URL을 app-platform module로 전달한다. API Task Role만 inbox prefix에 쓸 수 있고 AI worker와 기존 CloudFront read 정책은 변경하지 않는다.

**Tech Stack:** Terraform, AWS S3, CloudFront, IAM, ECS Fargate, Bash.

## Global Constraints

- 객체 key는 `content/inbox/{uuid}.{extension}`이다.
- API 권한은 `s3:PutObject`와 `content/inbox/*`로 제한한다.
- CORS는 승인된 웹 origin 2개와 기존 로컬 프론트 origin 5개에서 `PUT`만 허용한다.
- apply와 임시 객체 생성은 saved plan 검토 뒤 별도 사용자 승인을 받는다.
- 백엔드 API, 파일 검증과 이미지 블록은 수정하지 않는다.

---

### Task 1: 계약 테스트와 Terraform 구현

**Files:**
- Create: `scripts/test-admin-content-upload-contract.sh`
- Modify: `environments/shared/main.tf`
- Modify: `environments/shared/variables.tf`
- Modify: `environments/dev/main.tf`
- Modify: `environments/prod/main.tf`
- Modify: `modules/app-platform/variables.tf`
- Modify: `modules/app-platform/main.tf`

**Interfaces:**
- Consumes: shared outputs `content_bucket_name`, `cloudfront_url`.
- Produces: module inputs `content_bucket_name`, `content_cloudfront_url`; API env `CONTENT_BUCKET_NAME`, `CONTENT_CLOUDFRONT_URL`.

- [ ] **Step 1: 실패하는 계약 테스트를 작성한다.**

```bash
assert_contains "${shared_main}" 'resource "aws_s3_bucket_cors_configuration" "content" {'
assert_contains "${shared_main}" 'allowed_methods = ["PUT"]'
assert_contains "${dev_main}" 'key = "shared/landit-iac/terraform.tfstate"'
assert_contains "${prod_main}" 'key = "shared/landit-iac/terraform.tfstate"'
assert_contains "${api_policy}" 'actions   = ["s3:PutObject"]'
assert_contains "${api_policy}" '/content/inbox/*'
assert_contains "${api_task}" '{ name = "CONTENT_BUCKET_NAME", value = var.content_bucket_name }'
assert_contains "${api_task}" '{ name = "CONTENT_CLOUDFRONT_URL", value = var.content_cloudfront_url }'
assert_not_contains "${worker_task}" 'CONTENT_BUCKET_NAME'
```

origin 7개, 허용 header 4개와 `ETag`도 각각 literal assertion으로 검사한다.

- [ ] **Step 2: RED를 확인한다.**

Run: `bash scripts/test-admin-content-upload-contract.sh`.

Expected: CORS resource가 없어 실패한다.

- [ ] **Step 3: 최소 Terraform을 구현한다.**

```hcl
resource "aws_s3_bucket_cors_configuration" "content" {
  bucket = aws_s3_bucket.content.id

  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = var.content_upload_allowed_origins
    allowed_headers = ["Content-Type", "Cache-Control", "If-None-Match", "x-amz-*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}
```

shared origin 변수는 승인된 7개 값을 default list로 정의한다. dev·prod는 아래 remote state와 module 입력을 사용한다.

```hcl
data "terraform_remote_state" "shared" {
  backend = "s3"
  config = {
    bucket = "landit-terraform-state-982529430654"
    key    = "shared/landit-iac/terraform.tfstate"
    region = var.aws_region
  }
}

content_bucket_name   = data.terraform_remote_state.shared.outputs.content_bucket_name
content_cloudfront_url = data.terraform_remote_state.shared.outputs.cloudfront_url
```

app-platform API IAM에는 아래 statement만 추가한다.

```hcl
statement {
  actions   = ["s3:PutObject"]
  resources = ["arn:aws:s3:::${var.content_bucket_name}/content/inbox/*"]
}
```

API container environment에 두 값을 추가하고 worker block은 건드리지 않는다.

- [ ] **Step 4: GREEN과 formatting을 확인한다.**

Run: `terraform fmt -recursive && bash scripts/test-admin-content-upload-contract.sh && git diff --check`.

Expected: 모두 exit code 0.

- [ ] **Step 5: Terraform 구현을 커밋한다.**

```bash
git add scripts/test-admin-content-upload-contract.sh environments/shared/main.tf environments/shared/variables.tf environments/dev/main.tf environments/prod/main.tf modules/app-platform/variables.tf modules/app-platform/main.tf
git commit -m "feat: 관리자 콘텐츠 이미지 업로드 권한을 구성한다"
```

### Task 2: 문서와 Terraform plan 검증

**Files:**
- Modify: `docs/content-storage.md`
- Modify: `checklist.md`
- Modify: `context-notes.md`

- [ ] **Step 1: 관리자 업로드 계약과 IaC 책임 범위를 문서화한다.**

`docs/content-storage.md`에 inbox key, presigned PUT header, CloudFront URL 조합, 백엔드 파일 검증 책임과 미사용 파일 정리 제외를 기록한다. 기존 “업로드 API는 만들지 않는다” 문구는 시나리오 이미지에만 적용되도록 고친다.

- [ ] **Step 2: 세 root를 검증하고 saved plan을 만든다.**

```bash
AWS_PROFILE=landit terraform -chdir=environments/shared init -input=false
AWS_PROFILE=landit terraform -chdir=environments/dev init -input=false
AWS_PROFILE=landit terraform -chdir=environments/prod init -input=false
terraform -chdir=environments/shared validate
terraform -chdir=environments/dev validate
terraform -chdir=environments/prod validate
AWS_PROFILE=landit terraform -chdir=environments/shared plan -out=/tmp/lan299-shared.tfplan
AWS_PROFILE=landit terraform -chdir=environments/dev plan -out=/tmp/lan299-develop.tfplan
AWS_PROFILE=landit terraform -chdir=environments/prod plan -out=/tmp/lan299-production.tfplan
```

Expected: shared는 CORS configuration 1개 추가만 포함한다. develop·production은 API IAM policy 갱신, API Task Definition 교체와 ECS Service 갱신만 포함하며 다른 리소스 삭제는 없어야 한다.

- [ ] **Step 3: 검증 결과를 기록하고 커밋한다.**

```bash
git add docs/content-storage.md checklist.md context-notes.md
git commit -m "docs: 관리자 콘텐츠 업로드와 검증 절차를 반영한다"
```

### Task 3: 승인 후 적용과 live 확인

- [ ] **Step 1: 사용자가 확인한 saved plan만 순서대로 적용한다.**

```bash
AWS_PROFILE=landit terraform -chdir=environments/shared apply /tmp/lan299-shared.tfplan
AWS_PROFILE=landit terraform -chdir=environments/dev apply /tmp/lan299-develop.tfplan
AWS_PROFILE=landit terraform -chdir=environments/prod apply /tmp/lan299-production.tfplan
```

- [ ] **Step 2: live CORS·IAM·ECS를 확인한다.**

`aws s3api get-bucket-cors`, `aws iam get-role-policy`, `aws ecs describe-task-definition`으로 CORS allowlist, API inbox PutObject와 두 환경 변수를 확인한다. IAM simulation으로 API Role의 inbox 허용·다른 prefix 거부와 worker 거부를 확인한다.

- [ ] **Step 3: 승인받은 UUID 임시 객체로 CloudFront를 확인한다.**

운영자 권한으로 `content/inbox/{uuid}.png` 한 건을 immutable header와 `If-None-Match: *`로 올린 뒤 CloudFront `HEAD`가 `200`, 올바른 `Content-Type`과 cache header를 반환하는지 확인한다. 정확한 key를 제시해 사용자 승인을 받은 뒤 검증 객체를 삭제한다.

- [ ] **Step 4: post-apply plan과 작업 기록을 완료한다.**

세 root plan이 `No changes`인지 확인하고 `checklist.md`, `context-notes.md`에 실제 결과만 기록한다.
