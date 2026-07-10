# Context Notes

## 2026-06-28 Landit IaC 초기 세팅

### 이번 초기화의 목적

- `landit-iac`는 Landit 서비스의 IaC 레포이다.
- 이번 작업은 실제 인프라를 확정하거나 배포하는 작업이 아니다.
- 목적은 앞으로 IaC 작업을 안전하게 시작할 수 있도록 문서, 작업 규칙, 최소 디렉터리 구조를 준비하는 것이다.
- EC2, ECS, RDS, Vercel, S3, CloudFront, Route53 같은 인프라 선택은 아직 결정하지 않는다.

### 현재 레포 상태

- 작업 시작 시점의 `landit-iac`는 `LICENSE`만 있는 상태였다.
- 작업 시작 시점의 `git status --short`는 출력이 없어 깨끗했다.
- 현재 브랜치는 `main`이다.

### 초기 세팅에 유지할 작업 패턴

- `AGENTS.md`, `README.md`, `checklist.md`, `context-notes.md`로 작업 규칙과 의사결정을 남기는 문서 구조는 재사용한다.
- Terraform 변경 전후에 `terraform fmt -recursive`, 가능한 validate/plan, `git diff`, `git status`로 검증하는 흐름은 재사용한다.
- 실제 `*.tfvars`, `*.tfplan`, Terraform state, secret 값은 커밋하지 않는 규칙을 재사용한다.
- dev와 prod를 별도 Terraform root로 분리할 수 있는 `environments/` 구조는 후보로 재사용한다.
- provider `default_tags`로 공통 태그를 넣는 패턴은 최소 뼈대에 반영한다.
- S3 backend와 S3 native lockfile은 Landit bucket/key 기준으로만 사용한다.
- 환경 이름은 Terraform root, state key, workflow target에서 일관되게 사용한다.
- 실제 `*.tfvars`, `*.tfplan`, Terraform state, security group id, IP, secret 값은 복사하지 않는다.
- `terraform apply`, `terraform destroy`, AWS 리소스 생성, 변경, 삭제는 실행하지 않는다.

### Landit 기본 네이밍 후보

| 항목 | 후보 |
| --- | --- |
| project name | `landit` |
| repository | `landit-iac` |
| backend repo | `landit-be` |
| frontend repo | `landit-fe` |
| AI repo | `landit-ai` |
| production SSM path | `/landit/prod` |
| development SSM path | `/landit/develop` |
| production state key | `prod/landit-iac/terraform.tfstate` |
| development state key | `dev/landit-iac/terraform.tfstate` |

### 아직 결정하지 않은 사항

- dev/prod Terraform root를 완전히 분리할지, module을 공유할지.
- backend, frontend, AI의 실제 배포 방식.
- 도메인과 DNS provider.
- GitHub Actions OIDC owner/repository/environment subject.
- VPC, subnet, database, cache, object storage, CDN, logging 구성.
- secret rotation, 접근 권한, 감사 절차.

## 2026-06-28 S3 backend 구성

### 확인한 기준

- `landit` AWS profile은 STS 기준 account `982529430654`, IAM user `arn:aws:iam::982529430654:user/sm-iac`이다.
- 기본 AWS region은 `ap-northeast-2`로 둔다.
- S3 backend bucket 이름은 account id를 포함해 `landit-terraform-state-982529430654`로 둔다.
- bootstrap state key는 `bootstrap/state-backend/terraform.tfstate`로 둔다.
- production state key는 `prod/landit-iac/terraform.tfstate`로 둔다.
- development state key는 `dev/landit-iac/terraform.tfstate`로 둔다.
- S3 backend locking은 Terraform S3 backend의 `use_lockfile = true`를 사용한다.

### 현재 AWS 상태

- `aws s3api head-bucket --bucket landit-terraform-state-982529430654 --profile landit` 결과는 `404 Not Found`이다.
- 따라서 backend block을 바로 활성화한 `terraform init`은 bucket 생성 전까지 성공할 수 없다.
- 실제 S3 bucket 생성은 AWS 리소스 생성이므로 사용자 확인 전까지 실행하지 않는다.

### 구현 방향

- `bootstrap/state-backend`는 로컬 state로 실행해 S3 state bucket 자체를 만들기 위한 별도 root로 둔다.
- dev/prod root에는 S3 backend block을 미리 추가한다.
- bucket 생성 전 dev/prod 검증은 `terraform validate`까지만 가능하다.
- bucket 생성 후에는 dev/prod root에서 `terraform init -reconfigure`로 S3 backend를 활성화한다.

### 검증 결과

- `bootstrap/state-backend` root의 `terraform init -backend=false`는 성공했다.
- `bootstrap/state-backend` root의 `AWS_PROFILE=landit terraform plan`은 `5 to add, 0 to change, 0 to destroy`로 성공했다.
- plan 생성 대상은 S3 bucket, public access block, versioning, AES256 기본 암호화, HTTPS-only bucket policy이다.
- dev/prod root의 `terraform init -backend=false -reconfigure`와 `terraform validate`는 성공했다.
- dev/prod root의 `terraform plan`은 S3 backend가 아직 초기화되지 않아 `Backend initialization required` 오류로 중단됐다.
- 이 오류는 state bucket이 아직 생성되지 않은 현재 단계에서는 예상 가능한 제한이다.

## 2026-06-28 S3 backend apply

- 사용자 요청에 따라 `bootstrap/state-backend` plan 파일을 만들고 apply했다.
- apply 결과는 `5 added, 0 changed, 0 destroyed`이다.
- 생성된 리소스는 S3 bucket, public access block, versioning, AES256 기본 암호화, HTTPS-only bucket policy이다.
- S3 bucket `landit-terraform-state-982529430654`는 `ap-northeast-2`에 생성됐다.
- bucket versioning은 `Enabled`이다.
- public access block은 `BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`가 모두 `true`이다.
- 기본 서버 측 암호화는 `AES256`이다.
- apply 후 bootstrap root plan은 `No changes`이다.
- dev/prod root의 S3 backend 초기화는 성공했고, 두 root 모두 plan 결과는 `No changes`이다.
- dev/prod root는 아직 실제 리소스가 없어 S3 state object가 생성되지 않았다.
- bootstrap root state도 S3 backend로 마이그레이션했다.
- S3 object `bootstrap/state-backend/terraform.tfstate`가 생성된 것을 확인했다.
- migration 후 bootstrap root의 `terraform validate`와 `terraform plan`은 모두 성공했고 plan 결과는 `No changes`이다.

## 2026-06-28 GitHub Actions Terraform workflow

- remote는 `origin https://github.com/Aragornnnnnn/landit-iac.git`이다.
- 현재 branch는 `main`이고 작업 시작 시점의 `git status --short`는 깨끗했다.
- workflow는 `.github/workflows/terraform.yml`에 둔다.
- workflow trigger는 자동 push apply를 피하기 위해 `workflow_dispatch`만 사용한다.
- `target` input은 최종적으로 `develop`, `production` 중 하나를 고른다.
- `operation=plan-only`면 plan까지만 실행한다.
- `operation=plan-and-apply`면 plan artifact를 만들고 target별 apply GitHub environment 승인을 기다린 뒤 같은 plan 파일로 apply한다.
- apply는 `refs/heads/main`에서만 허용한다.
- plan job은 `terraform-plan-develop` 또는 `terraform-plan-production` environment를 사용한다.
- apply job은 `terraform-apply-develop` 또는 `terraform-apply-production` environment를 사용한다.
- AWS 인증은 long-lived key를 workflow에 넣지 않고 GitHub OIDC를 사용한다.
- workflow는 repository variable 또는 environment variable `AWS_ROLE_ARN`을 요구한다.
- OIDC role trust policy는 target별 plan/apply environment subject를 허용해야 한다.
- 아직 GitHub Actions용 AWS IAM role은 이 Terraform 코드로 만들지 않았다.
- workflow YAML은 Ruby YAML parser로 로드에 성공했다.
- `actionlint`는 로컬에 설치되어 있지 않아 실행하지 못했다.
- `terraform fmt -recursive -check`는 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform validate`는 모두 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform plan`은 모두 `No changes`이다.
- 민감정보 패턴 검색에서 AWS access key나 secret key 문자열은 발견되지 않았다.
- `git fetch origin` 후 `origin/main...HEAD` 차이는 `0 5`였고, `git push origin main`으로 `1c6a35a..8eade66` 범위를 push했다.

## 2026-06-28 Terraform workflow 환경 명확화

- 사용자가 이번 작업은 issue number 없이 진행해도 된다고 명시했다.
- 일반 작업 규칙으로는 issue number를 요구하고 `feat/{issue number}` 브랜치에서 작업하도록 `AGENTS.md`에 남긴다.
- 환경별 브랜치는 만들지 않는다. 브랜치는 작업 단위이고, 환경은 Terraform root/state/workflow target으로 구분한다.
- 일반 Terraform workflow target에서는 bootstrap을 제거한다.
- bootstrap은 state bucket 자체를 다루는 관리자 절차이므로 일반 develop/production workflow와 섞지 않는다.
- workflow target은 `develop`, `production`만 노출한다.
- apply 실행 여부는 boolean이 아니라 `operation=plan-only` 또는 `operation=plan-and-apply`로 고른다.
- production apply는 `confirm_environment=production`, `refs/heads/main`, `terraform-apply-production` environment 승인이 모두 있어야 가능하다.
- workflow 실행 로그에는 target, operation, Terraform root, AWS account, AWS region, state bucket, state key, apply environment를 출력한다.
- workflow YAML은 Ruby YAML parser로 로드에 성공했다.
- `terraform fmt -recursive -check`는 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform validate`는 모두 성공했다.
- `bootstrap/state-backend`, `environments/dev`, `environments/prod` 세 root의 `terraform plan`은 모두 `No changes`이다.
- `actionlint`는 로컬에 설치되어 있지 않아 실행하지 못했다.

## 2026-06-28 팀 공통 규칙 IaC 반영

- 사용자는 PR 템플릿은 추후 추가하겠다고 명시했다. 이번 작업에서는 PR 템플릿 파일을 만들지 않는다.
- Landit IaC 커밋 컨벤션은 BE 형식인 `{type}: 커밋 메시지`를 따른다.
- GitHub Actions, Terraform bootstrap, 개발 환경, 설정 변경은 `ci`가 아니라 `chore` 타입을 사용한다.
- 커밋 크기 기준은 기존 50줄 내외에서 가능하면 변경 30줄 내외로 낮춘다.
- 아키텍처 레벨 결정은 GitHub Wiki ADR로 남기고, PR에는 코드 레벨 변경과 검증 결과를 남긴다.
- 문서 변경도 사람 검토를 전제로 작성한다.
- `Initial commit`과 `ci:` 커밋 3개를 새 커밋 컨벤션에 맞게 reword했다.

## 2026-06-28 외부 참고 레포 언급 제거

- Landit IaC를 독립 레포로 보고 문서의 이전 서비스 전환 배경과 참고 범위를 제거한다.
- 작업 규칙은 Landit 자체 운영 기준으로 표현한다.
- 과거 참고 레포의 경로, 도메인, repository 문자열, OS user, 배포 경로는 문서에 남기지 않는다.

## 2026-06-28 커밋 타입 설명 보강

- 커밋 타입 이름만 있으면 판단 기준이 약하므로 `AGENTS.md`에 팀 공통 타입 설명 표를 직접 둔다.
- README는 표를 중복하지 않고 `AGENTS.md`의 커밋 타입 표를 기준으로 삼는다.

## 2026-06-28 커밋 크기 표현 조정

- 30줄 기준은 강제 제한이 아니라 가능한 기준으로 둔다.
- 커밋은 논리 단위로 작게 나누고, PR은 사람이 리뷰 가능한 크기로 유지한다.

## 2026-06-28 README 가독성 개선

- README는 상세 구조보다 현재 상태와 안전한 실행 흐름을 먼저 보여주도록 재배치한다.
- Terraform local 실행, GitHub Actions 실행, Git 작업 흐름, state와 secret 규칙을 독립 섹션으로 분리한다.
- 디렉터리 구조는 길이가 길어서 하단으로 이동한다.
- README 재구성은 한 파일 안의 단일 논리 변경이라 하나의 README 커밋으로 묶는다.

## 2026-06-28 README와 개발자 문서 분리

- README는 레포의 첫 화면이므로 현재 상태와 주요 문서 링크만 남긴다.
- 개발자가 따라야 하는 Terraform 실행, GitHub Actions, Git 작업 흐름, state와 secret 규칙은 `docs/developer-guide.md`로 분리한다.
- README에서 `docs/developer-guide.md`와 `docs/architecture-questions.md`로 연결한다.

## 2026-06-28 Landit SSM Parameter Store 초기 작성

- 사용자 요청에 따라 Landit runtime parameter를 SSM Parameter Store에 작성했다.
- AWS account는 `982529430654`, region은 `ap-northeast-2`, profile은 `landit`이다.
- 기존 `/landit/develop`, `/landit/prod` path에는 parameter가 없었다.
- development와 production에 각각 7개 parameter를 작성했다.
- 전체 14개 parameter 중 8개는 `SecureString`, 6개는 `String`이다.
- `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `OPENROUTER_API_KEY`는 `SecureString`으로 관리한다.
- `LLM_PROVIDER`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`은 `String`으로 관리한다.
- DB URL에는 `sslmode=require`와 `prepareThreshold=0` query parameter를 붙인다.
- 현재 받은 Supabase pooler URL은 session pooler 형태로 취급한다.
- secret 값은 출력하지 않았고 repo 파일에도 기록하지 않았다.
- 검증은 `get-parameters-by-path`에서 parameter name, type, version만 조회하는 방식으로 수행했다.

## 2026-06-28 SSM DB_URL JDBC 형식 수정

- BE 로컬 연결 확인 결과 기존 `DB_URL` 형식이 Java JDBC 연결에 맞지 않는 것으로 확인됐다.
- 기존 `DB_URL`은 일반 Postgres URI 형태였고 username과 password를 URL 안에 포함했다.
- BE는 `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`를 별도 env var로 읽으므로 `DB_URL`에는 credential을 넣지 않는다.
- develop과 prod의 `DB_URL`을 `jdbc:postgresql://{host}:5432/postgres?sslmode=require&prepareThreshold=0` 형식으로 갱신했다.
- develop과 prod의 `DB_URL` parameter version은 `2`가 됐다.
- `DB_USERNAME`, `DB_PASSWORD`는 기존 version `1`을 유지했다.
- 값 검증은 하지 않고 parameter name, type, version만 조회했다.

## 2026-07-07 develop API ECS health check grace period 수정

- GitHub Actions run `28803359543`은 Docker build와 push가 아니라 `Verify ECS service` 단계에서 길어졌다.
- `develop-landit-api`의 새 task가 Spring Boot 부팅 완료 전에 ALB `/actuator/health` 검사에 실패했고, ECS stopped reason은 `Task failed ELB health checks`였다.
- 수정 전 `develop-landit-api`의 `healthCheckGracePeriodSeconds`는 `0`이었다.
- 현재 Landit IaC repo는 ECS service 리소스를 Terraform으로 관리하지 않으므로, 이번 수정은 live ECS service 설정 변경으로 처리한다.
- 최소 수정은 `healthCheckGracePeriodSeconds`를 `180`으로 올리는 것이다.
- `aws ecs update-service --health-check-grace-period-seconds 180`으로 live ECS service 설정을 수정했다.
- 이미 실패한 deployment가 새 설정으로 재시도되지 않아 `--force-new-deployment`를 한 번 실행했다.
- 검증 결과 `develop-landit-api`는 `healthCheckGracePeriodSeconds=180`, PRIMARY deployment `COMPLETED`, desired/running `1/1` 상태가 됐다.
- ALB target `10.20.0.254:8080`은 `healthy`이고, `https://api-develop.landit.im/actuator/health`는 `HTTP 200`과 `{"status":"UP"}`를 반환했다.

## 2026-07-09 BE와 AI ALB 라우팅 구성

- 사용자가 이번 작업은 issue number 없이 시작하라고 명시했다.
- 작업 브랜치는 issue number 대신 `feat/alb-routing`으로 만든다.
- 도메인은 `be-prod=api.landit.im`, `be-develop=api-develop.landit.im`, `ai-prod=ai.landit.im`, `ai-develop=ai-develop.landit.im`로 결정했다.
- `be-develop`은 기존 `api-develop.landit.im` 설정을 유지한다.
- Vercel에서 DNS를 등록해야 하므로 Terraform이 Route53 record를 직접 만들지는 않는다.
- develop은 기존 `develop-landit-alb`를 재사용하고, AI target group과 host rule을 추가하는 방향으로 간다.
- prod는 운영 배포 전 준비를 위해 `prod-landit-alb`와 BE, AI target group을 Terraform으로 준비한다.
- AI는 Fargate task public IP를 직접 쓰지 않는다. task public IP는 Elastic IP가 아니며 재배포 때 바뀔 수 있다.
- live develop Terraform state에는 `module.app_platform` 리소스가 있지만 현재 `main` checkout에는 `modules/app-platform` 코드가 없다.
- `feat/LAN-45` 브랜치에 app platform module과 dev HTTPS ALB 작업 코드가 있으므로 이번 브랜치에 필요한 Terraform 코드를 먼저 가져온 뒤 수정한다.
- `feat/LAN-45`의 app platform module, dev/prod root module call, outputs, variables를 현재 브랜치로 가져왔다.
- 기존 develop ACM 인증서 `2bc5fd3c-33cd-4c12-8867-ba3bf537b68d`는 `api-develop.landit.im`, `api.landit.im`만 포함하고, `ai-develop.landit.im`, `ai.landit.im`은 포함하지 않는다.
- `ai.landit.im`, `api-develop.landit.im`, `ai-develop.landit.im`은 `*.landit.im` wildcard 인증서로 처리할 수 있다.
- `api.landit.im`도 `*.landit.im` wildcard 인증서로 처리할 수 있으므로 별도 ACM 인증서는 필요 없다.
- ACM wildcard 인증서 `arn:aws:acm:ap-northeast-2:982529430654:certificate/c27457fe-4469-4944-a5d4-322569ddd549`를 요청했다.
- wildcard 인증서는 현재 `PENDING_VALIDATION` 상태이고, Vercel DNS에 ACM validation CNAME을 추가해야 한다.
- develop과 prod의 `alb_certificate_arn` 기본값은 새 wildcard 인증서 ARN으로 맞췄다.
- Vercel validation 전에는 wildcard 인증서가 `ISSUED`가 아니므로 Terraform apply를 실행하지 않는다.
- SSM에 `/landit/develop/LANDIT_AI_CLIENT_MODE`, `/landit/develop/LANDIT_AI_BASE_URL`, `/landit/prod/LANDIT_AI_CLIENT_MODE`, `/landit/prod/LANDIT_AI_BASE_URL`을 `String` type으로 추가했다.
- SSM parameter 검증은 값 없이 name, type, version만 조회했고 네 parameter 모두 version `1`이다.
- 사용자가 Vercel에 ACM validation CNAME과 `ai-develop.landit.im` CNAME을 추가한 뒤 wildcard 인증서가 `ISSUED` 상태가 됐다.
- `ai-develop.landit.im`은 `develop-landit-alb-786000484.ap-northeast-2.elb.amazonaws.com`으로 resolve된다.
- `terraform -chdir=environments/dev apply /tmp/landit-develop-alb-routing.tfplan`을 실행했고 결과는 `5 added, 4 changed, 2 destroyed`이다.
- develop output은 `api_domain_name=api-develop.landit.im`, `ai_domain_name=ai-develop.landit.im`, `alb_dns_name=develop-landit-alb-786000484.ap-northeast-2.elb.amazonaws.com`, `alb_zone_id=ZWKZPGTI48KDX`이다.
- develop HTTPS listener에는 wildcard ACM 인증서 `arn:aws:acm:ap-northeast-2:982529430654:certificate/c27457fe-4469-4944-a5d4-322569ddd549`가 붙었다.
- develop HTTPS listener host rule은 priority `100`의 `api-develop.landit.im` -> API target group, priority `110`의 `ai-develop.landit.im` -> AI target group이다.
- ECS service는 `develop-landit-api` task definition revision `4`, `develop-landit-worker` task definition revision `2`로 배포 완료됐다.
- AI target group은 `10.20.0.138:8000`이 `healthy` 상태이고, `https://ai-develop.landit.im/health`는 `HTTP 200`과 `{"status":"ok"}`를 반환했다.
- API는 `https://api-develop.landit.im/actuator/health`에서 `HTTP 200`과 `status=UP`을 반환했다.
- `terraform -chdir=environments/prod apply /tmp/landit-prod-alb-routing.tfplan`을 실행했고 결과는 `37 added, 0 changed, 0 destroyed`이다.
- prod 첫 apply output은 `api_domain_name=api-landit.im`, `ai_domain_name=ai.landit.im`, `alb_dns_name=prod-landit-alb-1073541301.ap-northeast-2.elb.amazonaws.com`, `alb_zone_id=ZWKZPGTI48KDX`이다.
- prod HTTPS listener에는 wildcard ACM 인증서 `arn:aws:acm:ap-northeast-2:982529430654:certificate/c27457fe-4469-4944-a5d4-322569ddd549`가 붙었다.
- prod 첫 apply 직후 HTTPS listener host rule은 priority `100`의 `api-landit.im` -> API target group, priority `110`의 `ai.landit.im` -> AI target group이다.
- prod ECR `prod-landit-api`, `prod-landit-worker`는 생성됐지만 아직 image가 없어 ECS task가 `CannotPullContainerError`로 시작하지 못한다.
- prod API task image는 `982529430654.dkr.ecr.ap-northeast-2.amazonaws.com/prod-landit-api:latest`, AI task image는 `982529430654.dkr.ecr.ap-northeast-2.amazonaws.com/prod-landit-worker:latest`를 참조한다.
- prod target group은 image push와 task 정상 기동 전까지 target health가 비어 있는 상태가 정상이다.
- `api-landit.im`은 사용하지 않는 도메인이므로 prod API host를 `api.landit.im`으로 정정한다.
- `terraform -chdir=environments/prod apply /tmp/landit-prod-api-domain-fix.tfplan`을 실행했고 결과는 `0 added, 1 changed, 0 destroyed`이다.
- prod HTTPS listener host rule은 priority `100`의 `api.landit.im` -> API target group, priority `110`의 `ai.landit.im` -> AI target group으로 정정됐다.
- prod output은 `api_domain_name=api.landit.im`, `ai_domain_name=ai.landit.im`, `alb_dns_name=prod-landit-alb-1073541301.ap-northeast-2.elb.amazonaws.com`, `alb_zone_id=ZWKZPGTI48KDX`이다.
- 잘못 요청한 `api-landit.im`용 pending ACM 인증서 `arn:aws:acm:ap-northeast-2:982529430654:certificate/9134c8af-df0a-4a94-9906-061135f23996`는 삭제했다.
- 사용자가 Vercel에 prod `api`와 `ai` CNAME을 추가했다.
- `api.landit.im`과 `ai.landit.im`은 모두 `prod-landit-alb-1073541301.ap-northeast-2.elb.amazonaws.com`으로 resolve된다.
- `https://api.landit.im/actuator/health`와 `https://ai.landit.im/health`는 TLS와 ALB 연결은 성공하지만 현재 `HTTP 503`을 반환한다.
- 사용자가 BE와 AI prod를 모두 배포했다고 알려준 뒤 다시 검증했다.
- `https://api.landit.im/actuator/health`는 `HTTP 200`과 `{"groups":["liveness","readiness"],"status":"UP"}`를 반환했다.
- `https://ai.landit.im/health`는 `HTTP 200`과 `{"status":"ok"}`를 반환했다.
- `prod-landit-api`, `prod-landit-worker` ECS service는 모두 `ACTIVE`, desired/running `1/1`, PRIMARY deployment `COMPLETED` 상태이다.
- `prod-landit-api` target group은 새 target `10.10.0.180:8080`이 `healthy`이고 이전 target `10.10.0.253:8080`은 draining 상태이다.
- `prod-landit-ai` target group은 `10.10.1.233:8000`이 `healthy` 상태이다.
- 이전 `HTTP 503` 원인은 prod ECR `prod-landit-api`, `prod-landit-worker`가 비어 있어 ECS task가 `CannotPullContainerError`로 시작하지 못하고 target group에 target이 없었기 때문이다.

## 2026-07-09 Auth token 만료시간 SSM 추가

- 사용자 요청에 따라 BE auth token 만료시간 runtime parameter를 SSM에 추가한다.
- 대상 path는 기존 Landit runtime path인 `/landit/develop`, `/landit/prod`이다.
- `LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS` 값은 `21600`초로 둔다.
- `LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS` 값은 `1209600`초로 둔다.
- 두 값은 secret이 아니므로 `String` type으로 저장한다.
- 작업 전 SSM 이름 조회에서 `LANDIT_AUTH_TOKEN_SECRET`만 있었고, 두 만료시간 parameter는 없었다.
- 현재 checkout에는 기존 미커밋 변경이 있으므로 이번 작업은 해당 SSM 값과 registry 기록만 최소 범위로 갱신한다.
- SSM 작성 결과 네 parameter 모두 `Standard` tier, version `1`로 생성됐다.
- 검증은 값 없이 name, type, version, last modified date만 조회하는 방식으로 수행했다.

## 2026-07-09 prod GitHub Actions 배포 설정

- landit-ai run `29005059322`, job `86074581657`은 `Validate deployment settings` 단계에서 실패했다.
- landit-ai 실패 시점의 env는 `AWS_ROLE_ARN`, `ECR_REPOSITORY`, `ECR_IMAGE_URI`, `ECS_CLUSTER`, `ECS_SERVICE`가 비어 있었다.
- landit-be run `29005068940`, job `86074610849`도 `Validate deployment settings` 단계에서 실패했다.
- landit-be 실패 시점의 env는 `AWS_ROLE_ARN`, `AWS_ACCOUNT_ID`, `AWS_REGION`, `ECR_REGISTRY`, `ECR_REPOSITORY`, `ECS_CLUSTER`, `ECS_SERVICE`, `HEALTH_CHECK_URL`이 비어 있었다.
- 기존 AWS IAM role은 `landit-github-actions-develop-deploy`만 있었고, trust policy는 `repo:Aragornnnnnn/landit-be:environment:develop`, `repo:Aragornnnnnn/landit-ai:environment:develop`만 허용했다.
- 사용자 승인 후 prod GitHub Actions OIDC role `landit-github-actions-prod-deploy`를 생성했다.
- prod role ARN은 `arn:aws:iam::982529430654:role/landit-github-actions-prod-deploy`이다.
- prod role trust policy는 `repo:Aragornnnnnn/landit-be:environment:prod`, `repo:Aragornnnnnn/landit-ai:ref:refs/heads/main`을 허용한다.
- prod role inline policy는 `prod-landit-api`, `prod-landit-worker` ECR push와 ECS service update/describe를 허용한다.
- prod role에는 BE migration workflow가 사용하는 `/landit/prod/DB_URL`, `/landit/prod/DB_USERNAME`, `/landit/prod/DB_PASSWORD` SSM read 권한도 추가했다.
- landit-be `prod` GitHub Environment variables에 `AWS_ROLE_ARN`, `AWS_ACCOUNT_ID`, `AWS_REGION`, `ECR_REGISTRY`, `ECR_REPOSITORY`, `ECS_CLUSTER`, `ECS_SERVICE`, `HEALTH_CHECK_URL`을 설정했다.
- landit-ai repository variables에 `PROD_AWS_ROLE_ARN`, `PROD_WORKER_ECR_REPOSITORY`, `PROD_WORKER_ECR_IMAGE_URI`, `PROD_WORKER_ECS_CLUSTER`, `PROD_WORKER_ECS_SERVICE`를 설정했다.

## 2026-07-09 API task auth/CORS SSM 주입 수정

- develop BE 소셜 로그인 실패는 앱 기동 문제가 아니라 CORS preflight 단계에서 재현됐다.
- `OPTIONS https://api-develop.landit.im/api/v1/auth/social-login`에 `Origin: https://test.landit.im`을 보내면 `HTTP 403`과 `Invalid CORS request`가 반환됐다.
- SSM `/landit/develop`에는 `LANDIT_CORS_ALLOWED_ORIGINS`, `LANDIT_AUTH_TOKEN_SECRET`, `LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES`, `LANDIT_AUTH_OIDC_KAKAO_AUDIENCES`, `LANDIT_AUTH_OIDC_APPLE_AUDIENCES`가 이미 존재했다.
- 하지만 `develop-landit-api:4` task definition의 API container secrets에는 `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `LANDIT_AI_CLIENT_MODE`, `LANDIT_AI_BASE_URL`만 들어 있었다.
- 원인은 SSM parameter 생성과 ECS task definition secret 주입을 별도 작업으로 취급했는데, ALB/ECS 플랫폼 구성에서 CORS와 auth runtime key 주입을 누락한 것이다.
- API task `secrets`에 CORS, auth token, OIDC audience SSM parameter를 추가한다.
- `terraform fmt -recursive`를 실행했다.
- sandbox 안의 `terraform validate`는 AWS provider plugin 실행 실패로 막혔고, 외부 권한으로 재실행한 develop/prod validate는 모두 성공했다.
- `AWS_PROFILE=landit terraform -chdir=environments/dev plan -out=/tmp/landit-dev-auth-cors-secrets.tfplan` 결과는 API task definition replacement와 ECS service task definition update만 포함했다.
- `AWS_PROFILE=landit terraform -chdir=environments/prod plan -out=/tmp/landit-prod-auth-cors-secrets.tfplan` 결과도 API task definition replacement와 ECS service task definition update만 포함했다.
- develop apply 결과는 `1 added, 1 changed, 1 destroyed`이고 `develop-landit-api`는 task definition revision `5`로 배포됐다.
- prod apply 결과는 `1 added, 1 changed, 1 destroyed`이고 `prod-landit-api`는 task definition revision `2`로 배포됐다.
- develop/prod API task definition 모두 `LANDIT_CORS_ALLOWED_ORIGINS`, `LANDIT_AUTH_TOKEN_SECRET`, `LANDIT_AUTH_TOKEN_ACCESS_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_TOKEN_REFRESH_EXPIRES_IN_SECONDS`, `LANDIT_AUTH_OIDC_GOOGLE_AUDIENCES`, `LANDIT_AUTH_OIDC_KAKAO_AUDIENCES`, `LANDIT_AUTH_OIDC_APPLE_AUDIENCES`를 secrets로 포함한다.
- `develop-landit-api`, `prod-landit-api` ECS service는 모두 PRIMARY deployment `COMPLETED`, desired/running `1/1` 상태이다.
- `OPTIONS https://api-develop.landit.im/api/v1/auth/social-login`에 `Origin: https://test.landit.im`을 보내면 `HTTP 200`과 `access-control-allow-origin: https://test.landit.im`을 반환한다.
- develop social-login invalid token smoke는 `HTTP 400`, `OIDC_TOKEN_INVALID`, `access-control-allow-origin: https://test.landit.im`을 반환해 브라우저가 오류 응답을 읽을 수 있는 상태로 바뀌었다.
- prod도 task definition secrets 주입은 반영됐지만, `https://api.landit.im` CORS smoke 응답에는 아직 `access-control-allow-origin` header가 없다.
- prod SSM `/landit/prod/LANDIT_CORS_ALLOWED_ORIGINS` 값에는 `https://landit.im`, `https://test.landit.im`이 포함되어 있으므로, prod CORS header 부재는 이번 IaC secret wiring과 별개로 prod BE image/code 또는 rollout 상태를 추가 확인해야 한다.
- apply 후 develop/prod `terraform plan -detailed-exitcode`는 모두 `No changes`를 반환했다.

## 2026-07-09 SSM runtime 주입 규칙 문서화

- 이번 CORS/auth 누락은 SSM parameter 생성과 ECS task definition secret 주입이 별도 단계라는 점을 문서에 충분히 드러내지 못해 발생했다.
- 새 SSM parameter를 추가할 때는 Parameter Store 생성, registry 기록, Terraform task definition `secrets` 연결, plan/apply, `describe-task-definition` 확인, 실제 endpoint 검증을 한 흐름으로 처리한다.
- 기존 SSM parameter 값만 바꿀 때도 running task에는 자동 반영되지 않는다. ECS secret은 container 시작 시점에 주입되므로 값 변경 후 새 deployment가 필요하다.

## 2026-07-11 develop ECS 배포 태스크 진단 권한 추가

- `landit-be`의 새 ECS 배포 검증 스크립트가 `ecs:ListTasks`, `ecs:DescribeTasks`를 호출하면서 GitHub Actions role `landit-github-actions-develop-deploy`이 `AccessDeniedException`으로 실패했다.
- 이 역할은 현재 Terraform으로 관리하지 않는 inline policy `landit-github-actions-develop-deploy`을 사용한다.
- 사용자 승인 후 태스크 진단 전용 Statement `DescribeDevelopEcsDeploymentTasks`에 `ecs:ListTasks`, `ecs:DescribeTasks`, `Resource: "*"`를 추가했다.
- `aws iam get-role-policy`로 두 액션이 정책에 반영된 것을 확인했다.
