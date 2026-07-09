# Developer Guide

Landit IaC 작업자가 로컬 또는 GitHub Actions에서 Terraform 작업을 진행할 때 확인할 절차입니다.

## 작업 시작 전

1. issue number를 확인하고 `feat/{issue number}` 브랜치에서 작업합니다.
2. 예외적으로 issue number 없이 작업할 때는 사용자의 명시적인 허용을 기록합니다.
3. [AGENTS.md](../AGENTS.md), [checklist.md](../checklist.md), [context-notes.md](../context-notes.md)를 먼저 읽습니다.
4. 비 trivial 작업은 계획을 세우고 `checklist.md`, `context-notes.md`를 갱신합니다.
5. 변경 후 실제 실행한 검증 명령과 결과를 최종 응답에 남깁니다.

## 로컬 Terraform 실행

`bootstrap/state-backend`는 state bucket 자체를 다루는 관리자 root입니다. 일반 dev/prod 작업에서는 사용하지 않습니다.

state bucket이나 backend 정책을 바꿔야 할 때만 bootstrap root를 확인합니다.

```bash
terraform fmt -recursive
terraform -chdir=bootstrap/state-backend init -backend=false
AWS_PROFILE=landit terraform -chdir=bootstrap/state-backend plan
```

bootstrap apply는 사용자 확인을 받은 뒤에만 실행합니다.

```bash
AWS_PROFILE=landit terraform -chdir=bootstrap/state-backend apply
AWS_PROFILE=landit terraform -chdir=bootstrap/state-backend init -migrate-state
```

dev root는 S3 backend로 초기화하고 plan까지 확인합니다.

```bash
terraform fmt -recursive
AWS_PROFILE=landit terraform -chdir=environments/dev init -reconfigure
terraform -chdir=environments/dev validate
AWS_PROFILE=landit terraform -chdir=environments/dev plan
```

production root도 같은 흐름을 사용합니다.

```bash
terraform fmt -recursive
AWS_PROFILE=landit terraform -chdir=environments/prod init -reconfigure
terraform -chdir=environments/prod validate
AWS_PROFILE=landit terraform -chdir=environments/prod plan
```

`terraform apply`와 `terraform destroy`는 plan 결과를 먼저 확인하고, 실제 변경 내용을 사용자에게 보고한 뒤에만 실행합니다.

## GitHub Actions Terraform

[`.github/workflows/terraform.yml`](../.github/workflows/terraform.yml)은 수동 실행 `workflow_dispatch`만 지원합니다.

| 입력 | 값 |
| --- | --- |
| `target` | `develop`, `production` |
| `operation` | `plan-only`, `plan-and-apply` |
| `confirm_environment` | production apply 때만 `production` 입력 |

필요한 GitHub 설정입니다.

- Repository variable 또는 environment variable `AWS_ROLE_ARN`에 GitHub Actions OIDC assume role ARN을 설정합니다.
- `terraform-plan-develop`, `terraform-plan-production` environment를 만듭니다.
- `terraform-apply-develop`, `terraform-apply-production` environment를 만들고 required reviewer를 설정합니다.
- `terraform-apply-production`에는 production 담당자의 required reviewer와 prevent self-review를 설정합니다.
- apply는 `refs/heads/main`에서만 허용합니다.

workflow 실행 순서입니다.

1. 선택한 target의 Terraform root, state key, AWS account, AWS region, apply environment를 로그에 출력합니다.
2. 선택한 root에서 `terraform fmt -recursive -check`, `terraform init`, `terraform validate`를 실행합니다.
3. `terraform plan -out`으로 plan 파일을 만들고 plan 내용을 로그에 출력합니다.
4. plan 파일을 1일 보관 artifact로 업로드합니다.
5. `operation=plan-and-apply`일 때만 target별 apply environment 승인을 기다립니다.
6. 승인 후 같은 plan artifact를 내려받아 `terraform apply`를 실행합니다.

production apply는 `operation=plan-and-apply`, `target=production`, `confirm_environment=production`, `refs/heads/main`, `terraform-apply-production` 승인이 모두 충족되어야 실행됩니다.

OIDC IAM role은 아직 Terraform으로 만들지 않았습니다. role trust policy는 최소한 아래 subject를 허용해야 합니다.

- `repo:Aragornnnnnn/landit-iac:environment:terraform-plan-develop`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-plan-production`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-apply-develop`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-apply-production`.

Application 배포용 prod OIDC role은 수동으로 관리합니다.

- role ARN은 `arn:aws:iam::982529430654:role/landit-github-actions-prod-deploy`입니다.
- trust subject는 `repo:Aragornnnnnn/landit-be:environment:prod`, `repo:Aragornnnnnn/landit-ai:ref:refs/heads/main`입니다.
- 권한은 prod BE/AI ECR push, ECS service update/describe, prod DB SSM parameter read로 제한합니다.
- `landit-be`는 `prod` GitHub Environment variables로 배포 값을 받습니다.
- `landit-ai`는 repository variables의 `PROD_*` 값으로 배포 값을 받습니다.

## Git 작업 흐름

- 일반 작업은 issue number를 먼저 정하고 `feat/{issue number}` 브랜치에서 진행합니다.
- 브랜치는 작업 단위를 나타내고, `develop`/`production`은 Terraform target과 state key로만 구분합니다.
- 환경별 브랜치인 `develop` 또는 `production` 브랜치는 만들지 않습니다.
- 커밋 메시지는 BE 컨벤션인 `{type}: 커밋 메시지` 형식을 사용합니다.
- 타입별 의미는 [AGENTS.md](../AGENTS.md)의 커밋 타입 표를 따릅니다.
- GitHub Actions, Terraform bootstrap, 개발 환경, 설정 변경은 `ci`가 아니라 `chore` 타입을 사용합니다.
- 가능하면 커밋 1개는 변경 30줄 내외로 하고, PR은 리뷰 가능한 크기로 유지합니다.
- 아키텍처 레벨 결정은 GitHub Wiki ADR로 남기고, PR에는 코드 레벨 변경과 검증 결과를 남깁니다.
- 문서 변경도 사람이 검토합니다.

## State와 Secret

- 실제 `*.tfvars`, `*.tfplan`, Terraform state 파일은 커밋하지 않습니다.
- secret 값은 Terraform state에 남기지 않는 방식을 우선 검토합니다.
- 접근 키, IP, security group id, secret 값은 커밋하지 않습니다.
- SSM path는 `/landit/prod`, `/landit/develop`을 사용합니다.
- runtime parameter 이름과 타입은 [SSM Parameters](ssm-parameters.md)를 따릅니다.
- state key는 `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate`입니다.
