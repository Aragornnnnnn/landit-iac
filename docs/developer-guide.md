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

## 개발 EC2 병행 전환 검증

개발 EC2는 기존 ECS·ALB를 대체하지 않고 병행 검증한다. saved plan을 만든 뒤 주소별 변경을 감사하고, plan 파일과 JSON은 `/tmp`에만 둔다.

```bash
AWS_PROFILE=landit terraform -chdir=environments/dev plan -input=false -out=/tmp/lan284-dev.tfplan
terraform -chdir=environments/dev show -json /tmp/lan284-dev.tfplan > /tmp/lan284-dev-plan.json
jq -r '.resource_changes[] | select(.change.actions != ["no-op"]) | [.address, (.change.actions | join(","))] | @tsv' /tmp/lan284-dev-plan.json
```

2026-08-08 saved plan의 `10 add, 2 change, 8 destroy`는 당시 LAN-184 Push drift를 함께 보였던 역사 기록이다. LAN-284 경계는 `aws_instance.app`, `aws_eip.app`, `aws_eip_association.app`, EC2 IAM·instance profile·security group의 9개 create였고, 당시 나머지 API ECS Service update, API Task Definition replacement와 Push Queue·DLQ·Scheduler·IAM·Alarm 삭제는 LAN-184 제거였다.

2026-08-15 최신 `origin/main` baseline은 `No changes`이며 LAN-184 destroy는 더 이상 없다. 최신 LAN-284 plan은 EC2·EIP·security group·IAM의 `9 add, 0 change, 0 destroy`만 포함하고 ALB·listener·target group과 ECS Service 변경은 없다. 따라서 현재 LAN-184 apply·post-apply 확인은 승인 게이트가 아니며, Terraform apply와 Vercel DNS 변경은 계속 별도 승인 전까지 실행하지 않는다.

BE·AI workflow의 EC2 미러링 구현과 로컬 검증은 완료됐다. 현재 순서는 다음과 같다.

1. IaC LAN-284 PR만 병합한다.
2. 최신 state 기준 EC2 create-only plan을 재생성하고 별도 apply 승인을 받은 뒤 EC2를 apply한다.
3. SSM, Docker, Caddy, loopback health, 로그, rollback을 검증한다.
4. 임시 Vercel DNS `api-ec2-develop.landit.im`, `ai-ec2-develop.landit.im` 등록 승인을 받는다.
5. 임시 도메인으로 외부 HTTPS, API, AI, BE→AI를 검증한다.
6. BE·AI GitHub Environment에 `EC2_INSTANCE_ID`를 등록한다.
7. 그 뒤에만 BE·AI application workflow PR을 병합하고, 각 workflow의 ECS 검증 뒤 동일 SHA EC2 미러링 dual deploy를 검증한다.
8. 24~48시간 병행 관찰 뒤 원래 개발 DNS 전환의 별도 승인을 받는다.

EC2 runtime과 두 `EC2_INSTANCE_ID` 준비 전에는 BE·AI application workflow PR을 병합하지 않는다. 실제 instance ID와 SHA를 확인하기 전에는 아래 명령도 실행하지 않는다.

```bash
aws ssm send-command --region ap-northeast-2 \
  --document-name AWS-RunShellScript \
  --instance-ids "$INSTANCE_ID" \
  --parameters 'commands=["/opt/landit/bin/deploy-service api <GIT_SHA>"]'
```

health check 실패 시 EC2 스크립트는 저장된 직전 SHA로 자동 복구한다. 수동 복구가 필요하면 확인한 직전 SHA를 같은 명령의 인자로 사용한다.

```bash
aws ssm send-command --region ap-northeast-2 \
  --document-name AWS-RunShellScript \
  --instance-ids "$INSTANCE_ID" \
  --parameters 'commands=["/opt/landit/bin/deploy-service api <PREVIOUS_GIT_SHA>"]'
```

EC2 복구는 ECS·ALB 변경을 포함하지 않는다. 원래 개발 DNS가 ALB를 가리키는 동안 EC2 실패는 EC2에서만 롤백한다. DNS 전환 뒤 장애가 나면 먼저 Vercel DNS를 ALB로 되돌리고, ECS 장애가 확인된 경우에만 기존 ECS 배포 절차로 복구한다. ECS·ALB 제거는 DNS 전환과 24~48시간 관찰을 마친 뒤 별도 승인으로만 수행한다.

production root도 같은 흐름을 사용합니다.

```bash
terraform fmt -recursive
AWS_PROFILE=landit terraform -chdir=environments/prod init -reconfigure
terraform -chdir=environments/prod validate
AWS_PROFILE=landit terraform -chdir=environments/prod plan
```

공통 콘텐츠 root는 private 콘텐츠 bucket과 CloudFront를 관리합니다.

```bash
terraform fmt -recursive
AWS_PROFILE=landit terraform -chdir=environments/shared init -reconfigure
terraform -chdir=environments/shared validate
AWS_PROFILE=landit terraform -chdir=environments/shared plan
```

`terraform apply`와 `terraform destroy`는 plan 결과를 먼저 확인하고, 실제 변경 내용을 사용자에게 보고한 뒤에만 실행합니다.

## GitHub Actions Terraform

[`.github/workflows/terraform.yml`](../.github/workflows/terraform.yml)은 수동 실행 `workflow_dispatch`만 지원합니다.

| 입력 | 값 |
| --- | --- |
| `target` | `shared`, `develop`, `production` |
| `operation` | `plan-only`, `plan-and-apply` |
| `confirm_environment` | production apply 때만 `production` 입력 |

필요한 GitHub 설정입니다.

- Repository variable 또는 environment variable `AWS_ROLE_ARN`에 GitHub Actions OIDC assume role ARN을 설정합니다.
- `terraform-plan-shared`, `terraform-plan-develop`, `terraform-plan-production` environment를 만듭니다.
- `terraform-apply-shared`, `terraform-apply-develop`, `terraform-apply-production` environment를 만들고 required reviewer를 설정합니다.
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
- `repo:Aragornnnnnn/landit-iac:environment:terraform-plan-shared`.
- `repo:Aragornnnnnn/landit-iac:environment:terraform-apply-shared`.
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
- state key는 `shared/landit-iac/terraform.tfstate`, `prod/landit-iac/terraform.tfstate`, `dev/landit-iac/terraform.tfstate`입니다.
