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

## 개발 EC2 배포와 제거 검증

개발 BE·AI는 단일 EC2에서 실행한다. ECS·ALB 제거 전에는 saved plan을 만든 뒤 주소별 변경을 감사하고 plan 파일과 JSON은 `/tmp`에만 둔다.

```bash
AWS_PROFILE=landit terraform -chdir=environments/dev plan -input=false -out=/tmp/lan284-dev.tfplan
terraform -chdir=environments/dev show -json /tmp/lan284-dev.tfplan > /tmp/lan284-dev-plan.json
jq -r '.resource_changes[] | select(.change.actions != ["no-op"]) | [.address, (.change.actions | join(","))] | @tsv' /tmp/lan284-dev-plan.json
```

2026-08-08 saved plan의 `10 add, 2 change, 8 destroy`는 당시 LAN-184 Push drift를 함께 보였던 역사 기록이다. 당시 LAN-284 경계는 `aws_instance.app`, `aws_eip.app`, `aws_eip_association.app`, EC2 IAM·instance profile·security group의 9개 create였고, 당시 나머지 API ECS Service update, API Task Definition replacement와 Push Queue·DLQ·Scheduler·IAM·Alarm 삭제는 LAN-184 제거였다.

2026-08-15 최신 `origin/main` baseline은 `No changes`이며 LAN-184 destroy는 더 이상 없다. 리뷰 보완 뒤 LAN-284 plan은 EC2·EIP·security group·IAM과 전용 SSM 배포 문서의 `10 add, 0 change, 0 destroy`만 포함하고 ALB·listener·target group과 ECS Service 변경은 없다. 따라서 현재 LAN-184 apply·post-apply 확인은 승인 게이트가 아니다.

BE·AI workflow는 ECR push 뒤 SSM으로 EC2 컨테이너를 배포하며, BE는 먼저 Flyway migration을 실행한다. SSM 문서는 배포 전에 최신 runtime env와 Compose 설정을 원자적으로 동기화하므로 기존 EC2에도 AI `mem_limit: 1024m`이 적용된다.

EC2는 주간 `landit-docker-cleanup.timer`로 생성 후 24시간이 지난 미사용 Docker image와 14일 이상 system journal을 정리한다. 정리 작업은 배포·rollback과 같은 lock을 사용하고 실행 중 image와 Docker volume은 삭제하지 않는다. SSM 배포 성공 뒤에도 정리를 한 번 실행한다.

제거 절차는 다음과 같다.

1. BE·AI GitHub Actions 재배포와 Flyway 성공을 확인한다.
2. EC2의 실제 이미지 SHA, 컨테이너 상태, 외부 HTTPS와 BE→AI 내부 health를 확인한다.
3. 기존 개발 DNS가 EC2 Elastic IP를 가리키는지 확인한다.
4. 제거 plan이 개발 ECS·ALB 전용 리소스만 삭제하고 EC2·EIP, VPC, ECR, S3, SQS, SSM, CloudWatch Logs를 보존하는지 확인한다.
5. 승인된 saved plan을 적용하고 post-apply `No changes`와 외부 health를 재확인한다.

실제 instance ID와 SHA를 확인하기 전에는 아래 명령을 실행하지 않는다.

```bash
aws ssm send-command --region ap-northeast-2 \
  --document-name develop-landit-ec2-deploy \
  --instance-ids "$INSTANCE_ID" \
  --parameters 'service=api,imageSha=<GIT_SHA>'
```

health check 실패 시 EC2 스크립트는 저장된 직전 SHA로 자동 복구한다. 수동 복구가 필요하면 확인한 직전 SHA를 같은 명령의 인자로 사용한다.

```bash
aws ssm send-command --region ap-northeast-2 \
  --document-name develop-landit-ec2-deploy \
  --instance-ids "$INSTANCE_ID" \
  --parameters 'service=api,imageSha=<PREVIOUS_GIT_SHA>'
```

ECS·ALB 제거 전 장애가 나면 Vercel DNS를 기존 ALB로 되돌릴 수 있다. 제거 뒤에는 EC2의 직전 이미지 SHA 자동 복구와 Terraform 재생성이 복구 경계다.

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

- `terraform-plan-shared`, `terraform-plan-develop`, `terraform-plan-production` environment를 만들고 `main`, `feat/*` branch를 허용합니다.
- `terraform-apply-shared`, `terraform-apply-develop`, `terraform-apply-production` environment를 만들고 `main` branch만 허용합니다.
- 각 environment variable `AWS_ROLE_ARN`에는 같은 phase와 target의 전용 OIDC role ARN을 설정합니다. repository 공용 변수는 사용하지 않습니다.
- apply required reviewer와 wait timer는 현재 설정하지 않습니다. repository write 권한자가 `main`에서 apply를 실행할 수 있으므로 reviewer는 후속 보안 강화 항목입니다.
- workflow도 apply를 `refs/heads/main`으로 제한하고 production에는 `confirm_environment=production`을 추가로 요구합니다.

workflow 실행 순서입니다.

1. 선택한 target의 Terraform root, state key, AWS account, AWS region, apply environment를 로그에 출력합니다.
2. 선택한 root에서 `terraform fmt -recursive -check`, `terraform init`, `terraform validate`를 실행합니다.
3. `plan-only`는 저장 파일 없는 speculative plan만 실행합니다.
4. `plan-and-apply`는 saved plan과 SHA-256을 만들고 `plans/{target}/{run_id}/{run_attempt}` 아래 private S3 객체로 업로드합니다.
5. apply job은 target별 apply environment에서 별도 OIDC role을 받은 뒤 같은 실행의 정확한 S3 key를 내려받습니다.
6. SHA-256이 일치할 때만 saved plan을 `terraform apply`에 전달합니다.

saved plan에는 민감 값이 평문으로 포함될 수 있으므로 public GitHub Actions artifact에는 올리지 않습니다. `landit-terraform-plan-artifacts-982529430654` bucket은 public access를 차단하고 AES256으로 암호화하며 `plans/` 객체를 1일 후 만료합니다. plan role은 자기 target prefix 업로드만, apply role은 조회만 허용합니다.

production apply는 `operation=plan-and-apply`, `target=production`, `confirm_environment=production`, `refs/heads/main`이 모두 충족되어야 실행됩니다. required reviewer는 현재 없으므로 apply environment 진입 자체가 사람 승인을 기다리지는 않습니다.

OIDC IAM role과 plan bucket은 `bootstrap/terraform-actions`에서 관리합니다. 기존 GitHub OIDC provider를 data source로 참조하며 `bootstrap/github-actions`의 BE·AI 배포 역할 state는 변경하지 않습니다.

apply role은 범용 Terraform 관리자 역할이 아닙니다. LAN-347 saved plan의 exact SSM document·production ECS API service와 prod request tag task definition 등록만 허용하며 shared에는 AWS resource mutation 권한이 없습니다. Actions에는 runtime role 권한 상승을 막기 위해 `iam:PutRolePolicy`를 주지 않습니다. develop EC2·deploy role과 production API task role의 IAM 변경은 로컬 관리자 profile의 별도 saved plan으로 먼저 적용해야 합니다. 후속 인프라 변경은 bootstrap policy를 먼저 확장해 별도 검토해야 합니다. production API task definition은 account-wide deregister 권한 대신 `skip_destroy=true`로 이전 revision을 유지합니다.

```bash
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions init -reconfigure
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions validate
AWS_PROFILE=landit terraform -chdir=bootstrap/terraform-actions plan
```

bootstrap apply와 GitHub environment·variable 생성은 위 plan의 역할 6개, inline policy 6개와 private plan bucket 보안 리소스를 검토하고 별도 승인받은 뒤에만 실행합니다. 승인 뒤에는 GitHub environment 6개, branch policy와 결정 가능한 `AWS_ROLE_ARN`을 먼저 생성·재조회하고, 그 다음 같은 bootstrap saved plan을 적용합니다. 각 role trust policy는 다음 subject 하나만 허용합니다.

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
