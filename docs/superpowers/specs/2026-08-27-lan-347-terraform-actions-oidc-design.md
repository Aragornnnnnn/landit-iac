# LAN-347 Terraform Actions OIDC와 콘텐츠 조회 권한 설계

## 목표

public `landit-iac` 저장소가 장기 AWS access key 없이 shared·develop·production Terraform plan과 apply를 실행하도록 전용 GitHub Actions OIDC 역할과 environment 변수를 구성한다. 저장된 Terraform plan은 GitHub artifact에 노출하지 않고 private S3에서 짧게 보관하며, develop EC2와 production ECS API에는 기존 shared 콘텐츠 inbox 객체 조회 권한을 최소 범위로 추가한다.

## 결정 사항

- 저장소는 public으로 유지한다.
- 기존 BE·AI 배포 역할을 재사용하지 않고 `landit-iac` 전용 역할을 만든다.
- shared·develop·production의 plan과 apply를 분리한 IAM 역할 6개를 사용한다.
- GitHub apply environment는 `main`만 허용하고 required reviewer는 지금 설정하지 않는다.
- production apply의 `confirm_environment=production` 확인은 유지한다.
- plan 전달에는 전용 private S3 버킷을 사용하고 GitHub Actions artifact는 사용하지 않는다.
- 기존 GitHub OIDC provider는 data source로 참조한다.
- 과거 `bootstrap/github-actions` state와 기존 BE·AI 역할은 이번 작업에서 변경하거나 삭제하지 않는다.
- 실제 Terraform apply와 GitHub environment 변경은 bootstrap plan 검토 뒤 별도 사용자 승인을 받는다.

## 현재 상태와 위험

현재 workflow는 saved plan을 GitHub Actions artifact로 업로드한 뒤 apply job에서 내려받는다. saved plan에는 구성 전체, 입력값과 민감 값이 평문으로 포함될 수 있으므로 public 저장소의 전달 수단으로 사용하지 않는다.

`main` 브랜치는 현재 branch protection이 없고 사용자는 apply required reviewer도 두지 않기로 했다. 따라서 저장소 write 권한자가 `main`에서 workflow를 실행할 수 있다는 잔여 위험을 수용한다. 환경별 deployment branch policy와 production 확인 문자열은 유지하지만 사람 승인을 대체하지는 않는다.

## Terraform bootstrap 경계

새 root `bootstrap/terraform-actions`는 다음 리소스만 소유한다.

- 기존 `token.actions.githubusercontent.com` OIDC provider 조회.
- target과 phase별 IAM 역할 6개와 inline policy.
- saved plan 전용 private S3 버킷과 public access block.
- S3 AES256 기본 암호화, HTTPS-only bucket policy와 1일 lifecycle.

bootstrap state는 기존 state bucket의 `bootstrap/terraform-actions/terraform.tfstate`를 사용한다. 기존 `bootstrap/github-actions/terraform.tfstate`는 과거 BE·AI develop 배포 역할을 소유한 별도 상태이므로 import, state move 또는 destroy를 수행하지 않는다.

## OIDC 신뢰 정책

역할 이름은 다음과 같다.

- `landit-iac-terraform-plan-shared`.
- `landit-iac-terraform-plan-develop`.
- `landit-iac-terraform-plan-production`.
- `landit-iac-terraform-apply-shared`.
- `landit-iac-terraform-apply-develop`.
- `landit-iac-terraform-apply-production`.

각 역할은 audience `sts.amazonaws.com`과 정확히 하나의 subject만 허용한다.

```text
repo:Aragornnnnnn/landit-iac:environment:terraform-{phase}-{target}
```

owner, repository, environment wildcard는 사용하지 않는다. 세션 이름에는 GitHub run ID와 attempt를 포함해 CloudTrail에서 실행을 추적할 수 있게 한다.

## IAM 권한 경계

plan 역할은 해당 target state 조회, native lockfile 생성·조회·삭제, Terraform refresh와 plan에 필요한 조회 작업만 허용한다. state 본문 `PutObject`, 실제 리소스 변경과 `iam:PassRole`은 허용하지 않는다.

apply 역할은 승인된 LAN-347 saved plan 적용에 필요한 비-IAM mutation만 허용한다. develop은 정확한 SSM document 갱신, production은 정확한 ECS API service 갱신과 `Project=landit`, `Environment=prod` request tag를 가진 task definition 등록만 허용한다. production `iam:PassRole`은 정확한 API task·execution role과 `ecs-tasks.amazonaws.com`으로 제한한다. shared apply 역할은 state·lock·plan 외 AWS resource mutation 권한이 없다.

Actions에는 `iam:PutRolePolicy`를 주지 않는다. 이번 develop EC2·deploy role과 production API task role의 `GetObject` policy 변경은 로컬 관리자 profile의 별도 saved plan과 승인 경로로 먼저 적용한다. 이는 workflow가 runtime role에 임의 inline policy를 넣어 자체 권한을 상승시키는 경로를 차단한다.

현재 saved plan에 없는 mutation은 fail-closed로 거부한다. 후속 IaC 변경은 bootstrap policy에 필요한 action과 정확한 resource 경계를 추가하고 별도 plan·리뷰를 거쳐야 한다. ECS task definition 교체에는 account-wide `ecs:DeregisterTaskDefinition`을 주지 않고 API task definition의 `skip_destroy=true`로 이전 revision을 보존한다. AWS 관리형 `AdministratorAccess`, `PowerUserAccess`, `ReadOnlyAccess`, `iam:*`, `iam:PutRolePolicy`와 범용 mutation `Resource="*"`는 사용하지 않는다. 단, resource-level 권한을 지원하지 않는 `ecs:RegisterTaskDefinition`은 위 두 request tag 조건을 모두 만족할 때만 `Resource="*"`를 사용한다.

develop과 production은 shared remote state를 읽으므로 두 역할 모두 `shared/landit-iac/terraform.tfstate` 조회를 추가한다. 다른 target state에는 접근할 수 없다.

plan 전달 권한은 target별 prefix로 분리한다.

```text
plans/{target}/{github_run_id}/{github_run_attempt}/terraform.tfplan
```

- plan 역할은 자기 target prefix의 `PutObject`만 허용한다.
- apply 역할은 같은 target prefix의 `GetObject`만 허용한다.
- workflow는 실행별 정확한 key를 만들고 SHA-256을 job output으로 넘겨 다운로드 후 대조한다.
- 역할에는 plan 객체 `DeleteObject`를 주지 않고 bucket lifecycle이 1일 후 정리한다.

## GitHub environment 구성

다음 environment 6개를 만든다.

- `terraform-plan-shared`.
- `terraform-plan-develop`.
- `terraform-plan-production`.
- `terraform-apply-shared`.
- `terraform-apply-develop`.
- `terraform-apply-production`.

각 environment에는 해당 역할 ARN을 일반 변수 `AWS_ROLE_ARN`으로 저장한다. ARN은 secret 값이 아니며 repository 공용 변수로 승격하지 않는다.

plan environment는 `main`과 `feat/*` deployment branch를 허용한다. apply environment는 `main`만 허용한다. required reviewer와 wait timer는 설정하지 않는다.

OIDC role보다 GitHub environment 보호를 먼저 만든다. 여섯 environment, branch policy와 결정 가능한 role ARN 변수까지 생성·재조회한 뒤 bootstrap saved plan을 적용한다. 이렇게 해야 role 생성 직후 보호 설정이 없는 environment subject로 세션을 얻는 창을 만들지 않는다.

## Workflow 변경

workflow는 수동 `workflow_dispatch`와 현재 target·operation 입력을 유지한다.

- `plan-only`는 `-out` 없이 speculative plan을 실행하고 S3에 파일을 쓰지 않는다.
- `plan-and-apply`는 `main` 확인과 production 문자열 확인 뒤 saved plan을 만든다.
- plan job은 saved plan SHA-256을 계산하고 실행별 S3 key에 업로드한다.
- apply job은 자기 environment의 역할로 정확한 key를 내려받고 SHA-256이 일치할 때만 적용한다.
- GitHub artifact upload/download step은 제거한다.
- checkout, Terraform setup과 AWS credential action은 검토한 commit SHA로 고정한다.
- plan과 apply는 현재 target별 concurrency group을 유지한다.

apply job이 승인자 없이 실행되는 현재 정책을 workflow 문서에 명시하고, 향후 required reviewer를 추가해도 IAM 역할이나 workflow를 바꿀 필요가 없게 한다.

## Shared 콘텐츠 GetObject

develop은 현재 EC2 instance role, production은 ECS API task role이 presigned URL을 생성한다. 두 identity policy의 기존 shared content statement를 다음과 같이 확장한다.

```text
Action: s3:GetObject, s3:PutObject
Resource: arn:aws:s3:::${content_bucket_name}/content/inbox/*
```

`s3:ListBucket`, `s3:DeleteObject`, 다른 `content/*` prefix, AI worker 권한과 bucket policy는 변경하지 않는다. 계약 테스트와 IAM simulation에서 inbox Get·Put 허용, 다른 prefix Get 거부를 확인한다.

## 검증과 배포 순서

1. shell 계약 테스트가 역할 수, 정확한 OIDC subject, state·plan prefix 분리, public 차단과 workflow artifact 제거를 검사한다.
2. 기존 콘텐츠 계약 테스트가 develop EC2와 production API의 inbox Get·Put, 다른 role 미변경을 검사한다.
3. `terraform fmt -recursive`, `git diff --check`, bootstrap·shared·dev·prod validate를 실행한다.
4. 로컬 AWS profile로 bootstrap saved plan을 생성하고 역할·정책·bucket 외 변경이 없는지 검토한다.
5. 사용자가 bootstrap plan을 별도 승인한 뒤에만 apply한다.
6. GitHub environment 6개와 각 `AWS_ROLE_ARN`을 생성하고 branch policy를 재조회한다.
7. feature 브랜치에서 develop·production `plan-only`를 실행해 plan 역할만으로 성공하는지 확인한다.
8. PR 병합과 별도 승인 뒤 `main`에서 develop, production 순서로 `plan-and-apply`를 실행한다.
9. IAM simulation, EC2 role과 ECS task role live policy, 서비스 정상 기동과 post-apply `No changes`를 확인한다.

bootstrap apply 전까지 기존 로컬 profile plan 경로는 유지된다. workflow 전환에 문제가 있으면 GitHub environment 변수를 제거하고 workflow를 직전 버전으로 되돌린다. 기존 BE·AI 배포 역할과 OIDC provider는 롤백 대상이 아니다.
