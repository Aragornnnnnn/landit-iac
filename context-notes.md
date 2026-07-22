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
- develop/prod 배포 역할은 현재 Terraform으로 관리하지 않는 각각의 inline policy를 사용한다.
- 사용자 승인 후 develop `DescribeDevelopEcsDeploymentTasks`, prod `DescribeProdEcsDeploymentTasks` Statement에 `ecs:ListTasks`, `ecs:DescribeTasks`, `Resource: "*"`를 추가했다.
- `aws iam get-role-policy`로 두 역할에 해당 액션이 반영된 것을 확인했다.

## 2026-07-11 develop API health check grace period 확대

- GitHub Actions 실행 `29107872234`에서 새 API 태스크는 Spring Boot 기동 완료까지 160.882초가 걸렸다.
- 현재 180초 grace period 안에는 ALB의 30초 간격 2회 성공 헬스 체크를 마칠 시간이 없어 태스크가 `Task failed ELB health checks`로 중지됐다.
- API ECS service의 grace period를 300초로 변경해 최대 기동 시간과 ALB 헬스 체크 시간을 수용한다.
- `AWS_PROFILE=landit terraform -chdir=environments/dev apply /tmp/landit-dev-api-grace-300.tfplan`은 ECS service in-place 변경 1건으로 성공했다.
- apply 뒤 `aws ecs describe-services`로 `healthCheckGracePeriodSeconds = 300`을 확인했다.

## 2026-07-13 LAN-122 Sentry DSN ECS 주입

- 사용자 제공 DSN은 `/landit/develop`과 `/landit/prod`에 서비스별 `LANDIT_BE_SENTRY_DSN`, `LANDIT_AI_SENTRY_DSN` `SecureString`으로 작성했다. 값은 문서와 검증 출력에 남기지 않는다.
- 동일한 환경에서 BE와 AI가 서로 다른 Sentry 프로젝트를 사용하므로 SSM parameter 이름은 서비스별로 분리한다.
- BE와 AI 애플리케이션은 모두 `SENTRY_DSN` 환경변수만 읽으므로, ECS API와 AI container의 `secrets`에서 각각 서비스별 SSM parameter를 `SENTRY_DSN`으로 매핑한다.
- BE는 `SENTRY_ENVIRONMENT`, AI는 `APP_ENV`를 각각 읽으므로 ECS 일반 환경변수에 Terraform `environment` 값을 연결한다.
- task definition 변경은 새 ECS deployment를 만들며, Terraform apply 후 task definition의 `secrets`와 service rollout 상태를 확인해야 한다.
- `terraform fmt -recursive -check`와 develop/prod `terraform validate`가 통과했다. 각 환경 plan은 API·AI task definition replacement와 ECS service task definition update만 포함했다.
- develop apply와 prod apply는 각각 `2 added, 2 changed, 2 destroyed`로 완료됐다.
- 새 task definition은 BE `SENTRY_DSN`을 `LANDIT_BE_SENTRY_DSN`으로, AI `SENTRY_DSN`을 `LANDIT_AI_SENTRY_DSN`으로 매핑한다. 값은 조회하지 않았다.
- BE API에는 `SENTRY_ENVIRONMENT=develop` 또는 `prod`, AI에는 `APP_ENV=develop` 또는 `prod`가 포함됐다.
- develop/prod API·AI ECS service는 모두 PRIMARY deployment `COMPLETED`, desired/running `1/1` 상태가 됐다. develop 새 API target도 `healthy` 상태로 전환됐다.

## 2026-07-13 LAN-122 Grafana Cloud 통합 모니터링

- 기존 Grafana Cloud stack `scarletmyrtle3008`을 사용한다. 새 stack이나 유료 plan은 만들지 않는다. 현재 portal에는 14일 trial 상태로 표시된다.
- 조직 SCP의 `tag:GetResources` 명시적 거부를 수정할 관리 계정 접근이 없어 Grafana Cloud CloudWatch scrape는 범위에서 제외한다. 따라서 ALB TPS와 ECS CPU·memory 지표는 Grafana Cloud에서 수집하지 않는다.
- BE와 AI 애플리케이션 지표는 Grafana Cloud OTLP endpoint로 직접 전송한다. 현재 규모에서는 서비스별 Alloy sidecar의 리소스, 설정 배포, 장애 지점을 추가하지 않는 편이 단순하다. Alloy는 전송 재시도와 로컬 버퍼링 요구가 생길 때 도입한다.
- BE 로그와 AI 로그는 기존 CloudWatch Logs를 유지하고 Data Firehose로 Grafana Loki에 전달한다. 환경별 delivery stream 하나를 API와 AI log group이 공유하고, log stream 이름은 별도 Loki label로 추가하지 않는다.
- OTLP 인증 header는 Terraform 변수나 state에 넣지 않고 환경별 SSM `SecureString`에 기록한다.
- Loki access policy token은 Terraform 변수나 state에 넣지 않는다. AWS Secrets Manager에 `{"api_key":"<Loki instance ID>:<logs write token>"}` 형식으로 작성하고 Firehose가 secret ARN으로 조회한다.
- Grafana Cloud access policy token 생성은 외부 상태 변경이므로 실제 생성 직전에 사용자 확인을 받고 진행한다.
- metric과 log label에는 사용자 ID, session ID, message ID, 요청 본문, query string, 인증 header를 넣지 않는다.
- BE는 `MANAGEMENT_OTLP_METRICS_EXPORT_ENABLED`, `MANAGEMENT_OTLP_METRICS_EXPORT_STEP`, signal-specific metrics endpoint를 사용하고, AI는 `OTEL_METRICS_ENABLED`, `OTEL_EXPORTER_OTLP_PROTOCOL`, base OTLP endpoint를 사용하도록 각 레포의 현재 설정 계약에 맞췄다.
- BE와 AI 모두 `OTEL_TRACES_EXPORTER=none`, `OTEL_LOGS_EXPORTER=none`을 명시해 자동 계측 모듈이 trace나 log를 의도치 않게 전송하지 않고 metrics만 전송하도록 제한한다.
- `terraform fmt -recursive`, develop/prod `terraform validate`, `git diff --check`가 통과했다. validate는 샌드박스에서 provider plugin 통신이 차단되어 같은 명령을 샌드박스 밖에서 재실행했다.
- OTLP base endpoint는 `https://otlp-gateway-prod-ap-northeast-0.grafana.net/otlp`, OTLP stack instance ID는 `1721357`이다. Prometheus service instance ID `3366938`과 구분하며 Basic 인증 username에는 OTLP stack instance ID를 사용한다. dev/prod의 환경별 OTLP header SSM `SecureString`은 작성됐다.
- AWS Logs endpoint는 `https://aws-logs-prod-030.grafana.net/aws-logs/api/v1/push`, Loki instance ID는 `1679144`이다. 인증값은 Terraform 밖의 Secrets Manager에 작성됐으며 Terraform에는 secret ARN만 연결한다.
- Grafana Cloud access policy는 OTLP용 `metrics:write`와 Logs용 `logs:write`로 분리했다. 두 token은 자동 만료가 없으므로 정기 점검과 수동 rotation 및 폐기가 필요하다.
- 실제 endpoint와 secret ARN을 dev/prod에 연결하고 OTLP 및 로그 전송 enable flag를 `true`로 변경했다. `terraform plan`과 `apply`는 별도 검토와 사용자 승인 전까지 보류한다.
- develop plan은 `9 added, 2 changed, 2 destroyed`이며, 환경별 Firehose·IAM·log subscription 생성과 API·AI task definition 교체 및 ECS service 갱신만 포함한다.
- production plan은 공용 Grafana CloudWatch read role까지 포함해 `11 added, 2 changed, 2 destroyed`였으며, CloudWatch scrape 범위 제외에 따라 해당 role과 policy를 삭제한다.
- 두 plan 모두 `/tmp/lan122-dev.tfplan`, `/tmp/lan122-prod.tfplan`에 저장했고 예상하지 않은 기존 리소스 변경은 없다. apply는 사용자 승인 전까지 실행하지 않는다.
- 사용자 지시에 따라 저장한 plan 파일을 적용했다. develop은 `9 added, 2 changed, 2 destroyed`, production은 `11 added, 2 changed, 2 destroyed`로 계획과 동일하게 완료됐다.
- apply 후 develop/prod API·AI ECS service는 모두 desired/running `1/1`, PRIMARY deployment `COMPLETED`, failed task `0` 상태다.
- develop/prod Firehose delivery stream은 `ACTIVE`이고 API·AI log group 네 곳의 subscription filter가 환경별 stream을 가리킨다.
- Firehose의 `IncomingRecords`와 `DeliveryToHttpEndpoint.Success`가 develop/prod에서 계속 발생하며, `FailedValidation.Records`와 `SecretsManager.AccessDeniedException`은 `0`이다.
- Grafana Logs Drilldown에서 `service_name=cloud/aws` 로그와 `environment`, `project`, `aws_log_group` label을 확인했다. 최근 15분 범위에서 develop과 prod 로그가 모두 조회된다.
- Grafana Cloud AWS account `landit` 등록과 role assume은 성공했다. 다만 CloudWatch scrape job 생성 시 `tag:GetResources` 검증이 실패했다.
- `tag:GetResources` 직접 호출은 조직 SCP `p-5soyo0ar`의 명시적 거부로 실패하고 `cloudwatch:ListMetrics`는 성공한다. Grafana Cloud 생성 화면은 resource tag 옵션을 해제해도 이 권한을 필수 검증하므로, 조직 관리자가 해당 SCP에서 `tag:GetResources`를 허용하기 전에는 scrape job을 만들 수 없다.
- 관리 계정 접근이 불가능한 상태에서는 별도 exporter나 Alloy를 운영해 우회하지 않는다. CloudWatch scrape 관련 IAM role과 정책을 제거하고 Sentry, Firehose Loki 로그, BE·AI OTLP 애플리케이션 메트릭만 운영한다.
- 제거 plan은 develop `No changes`, production `0 added, 0 changed, 2 destroyed`였으며 production에서는 `landit-grafana-cloudwatch-integration` IAM role과 `landit-grafana-cloudwatch-read` inline policy만 대상으로 확인했다.
- production 제거 apply는 `0 added, 0 changed, 2 destroyed`로 완료됐고, IAM role 조회는 `NoSuchEntity`를 반환했다.
- 제거 후 develop/prod Terraform plan은 모두 `No changes`이며, 두 Firehose delivery stream은 `ACTIVE`, 네 ECS service는 `ACTIVE`, desired/running `1/1`, PRIMARY deployment `COMPLETED` 상태다.
- BE·AI develop PR merge와 배포 후 초기 OTLP 전송은 Basic username에 Prometheus service instance ID `3366938`을 사용해 두 서비스 모두 `401 Unauthorized`가 발생했다.
- 기존 access policy는 `metrics:write`, active, 만료 없음 상태이며 token은 유지했다. username만 OTLP stack instance ID `1721357`로 바꾼 일회성 OTLP 요청이 HTTP `200`을 반환해 원인을 확인했다.
- dev/prod `LANDIT_GRAFANA_CLOUD_OTLP_HEADERS`를 version `2`로 갱신했다. develop API·AI는 강제 새 배포 후 health `200`, 새 log stream에서 `401`, `Unauthorized`, export 실패 메시지 없이 안정화됐다.
- Grafana Explore에서 develop BE HTTP 6, JVM GC 8, JVM memory 25개 시계열과 AI HTTP 17, CPython GC 9, process 6개 시계열을 확인했다.
- production BE·AI 최신 image 배포 후 기존 태스크가 SSM version `1` 인증값을 유지해 OTLP `401 Unauthorized`를 반환하는 것을 확인했다. 같은 task definition으로 두 ECS service를 강제 재배포해 SSM version `2`를 다시 주입했다.
- 재배포 후 production API·AI는 desired/running `1/1`, PRIMARY deployment `COMPLETED`, health `200` 상태이며 새 log stream에서 `401`과 지표 전송 실패 메시지가 조회되지 않았다.
- Grafana Explore에서 develop과 production 각각 BE HTTP·JVM GC·JVM memory, AI HTTP·CPython GC·process 지표가 모두 조회되어 총 12개 환경·서비스·분류 조합을 확인했다.
- 적용 후 `terraform fmt -recursive -check`, develop/prod `terraform validate`, `git diff --check`가 통과했다. develop/prod `terraform plan -detailed-exitcode`는 모두 exit code `0`과 `No changes`를 반환했다.

## 2026-07-13 LAN-122 Grafana Cloud 대시보드

- Grafana에는 Landit 전용 dashboard가 없으며 Prometheus UID는 `grafanacloud-prom`, Loki UID는 `grafanacloud-logs`이다.
- 환경별 dashboard를 복제하지 않고 모든 dashboard에 `prod`, `develop` 환경 변수를 둔다. 기본값은 `prod`이다.
- `Landit Overview`, `Landit BE`, `Landit AI` 세 dashboard를 `Landit` folder에 구성한다.
- 세 dashboard 모두 전체 로그와 에러 로그 패널을 포함한다. Overview는 BE·AI 통합 로그를, 상세 dashboard는 서비스별 log group을 조회한다.
- 에러 로그는 현재 별도 `level` label이 없어 `error`, `exception`, `traceback`, `critical`, `fatal` 본문 정규식으로 구분한다.
- 공개 JVM dashboard `11892`와 FastAPI dashboard `18739`는 레이아웃만 참고하고 Landit의 실제 메트릭 이름과 label에 맞게 쿼리를 작성한다.
- dashboard JSON은 `landit-iac`에서 관리하고 단기 Grafana service account token으로 HTTP API에 배포한다. 별도 Grafana Terraform state와 provider는 추가하지 않는다.
- service account token은 환경변수로만 사용하고 배포·검증 후 폐기한다. dashboard 자동 배포 workflow와 alert rule은 이번 범위에서 제외한다.
- Grafana Cloud API로 stack 표시 이름을 `landitobservability`로 변경했다. 기존 stack slug는 그대로여서 Grafana URL은 계속 `https://scarletmyrtle3008.grafana.net`이다.
- Grafana HTTP API용 service account `landit-dashboard-provisioner`를 Editor 역할로 만들고, 단기 token으로 `Landit` folder의 `landit-overview`, `landit-be`, `landit-ai` dashboard를 upsert했다. URL은 각각 `/d/landit-overview/landit-overview`, `/d/landit-be/landit-be`, `/d/landit-ai/landit-ai`다. 배포와 조회 검증에 쓴 token은 모두 즉시 폐기했다.
- dashboard 동기화 스크립트는 folder를 먼저 생성하고 이미 존재할 때만 UID로 조회한다. Editor 역할 token이 존재하지 않는 folder UID를 먼저 조회하면 권한 오류가 나는 Grafana RBAC 동작을 반영한 순서다.
- Grafana service account의 datasource query API 호출은 해당 account의 datasource query 권한이 없어 403을 반환했다. 대신 Grafana Cloud access policy의 metrics·logs read scope로 Prometheus와 Loki endpoint를 직접 조회해 dashboard에 사용한 BE HTTP·JVM, AI HTTP·process·CPython GC 쿼리 12개가 성공하는 것을 확인했다.
- Loki의 24시간 집계는 develop·prod의 API·worker log group 네 개를 모두 반환했다. 전체 로그와 에러 로그 selector도 `query_range` endpoint에서 정상 동작했다.
- service account token과 Cloud Access Policy token은 repo, Terraform state, 문서, 명령 출력에 기록하지 않았다. Cloud Access Policy token은 이번 작업 후 사용자가 Grafana Cloud에서 rotation해야 한다.

## 2026-07-15 LAN-134 공통 콘텐츠 CloudFront 제공

- 시나리오 썸네일과 연습 예문 이미지는 develop과 prod가 공유하는 private 콘텐츠 버킷에 둔다. 사용자 음성과 Grafana 실패 로그는 기존 환경별 application bucket에 남긴다.
- 콘텐츠 이미지는 S3 URL이 아니라 CloudFront URL로 조회한다. S3 public access는 차단하고 CloudFront OAC만 `content/*`를 읽도록 제한한다.
- 공유 리소스는 dev/prod state에 중복 선언하지 않고 `shared/landit-iac/terraform.tfstate`의 별도 root가 소유한다.
- custom CDN domain과 ACM 인증서는 이번 범위에 포함하지 않는다. 초기 DB URL은 Terraform output으로 제공하는 CloudFront 기본 domain을 사용한다.
- 콘텐츠 업로드 API는 만들지 않는다. 운영자가 UUID 기반 새 key로 업로드하고 `Cache-Control: public, max-age=31536000, immutable`을 설정한 뒤 DB의 CloudFront URL을 갱신한다.
- 이전 객체는 develop과 prod의 참조 URL 변경 및 최대 캐시 TTL 경과를 확인한 뒤 삭제한다. Terraform apply와 실제 객체 업로드는 별도 사용자 확인이 필요하다.
- `AWS_PROFILE=landit terraform -chdir=environments/shared init -reconfigure`와 shared/dev/prod `terraform validate`가 통과했다. 샌드박스 안에서는 AWS provider가 실행되지 않아 동일 검증을 샌드박스 밖에서 실행했다.
- shared plan은 `landit-content-982529430654` bucket, ownership controls, public access block, AES256 기본 암호화, bucket policy, CloudFront OAC, CloudFront distribution만 추가하는 `7 to add, 0 to change, 0 to destroy` 결과다.
- CloudFront는 HTTP를 HTTPS로 redirect하고 GET·HEAD만 허용한다. default cache TTL과 max TTL은 1년이다. CloudFront 기본 domain의 default certificate는 보안 정책을 `TLSv1`로 고정하므로, TLS 1.2 이상을 강제하려면 custom domain과 us-east-1 ACM 인증서가 필요하다.
- 독립 검토는 S3 private 설정, OAC의 `content/*` 제한, CloudFront 조회 제한, shared state와 workflow 연결에서 P1·P2를 찾지 못했다. README의 apply 전 리소스 상태를 완료처럼 보이게 하는 P3 표현은 `Terraform 구성 추가, apply 전`으로 수정했고 `git diff --check`와 workflow YAML parsing을 다시 통과했다.
- 실제 apply 뒤 CloudFront API가 기본 certificate의 TLS 최소 버전을 `TLSv1`로 반환했고 Terraform plan에도 지원되지 않는 `TLSv1.2_2021` 변경이 반복됐다. 공식 CloudFront 문서의 기본 certificate 제약에 따라 해당 선언을 제거하고 no-change plan으로 다시 검증한다.

## 2026-07-17 메시지 피드백 worker 환경 변수 추가

- 사용자 요청에 따라 `/landit/develop`, `/landit/prod`에 `MESSAGE_FEEDBACK_MODEL=openai/gpt-5.4`, `MESSAGE_FEEDBACK_REVIEW_ENABLED=false` `String` parameter를 각각 작성했다.
- 값은 secret이 아니지만, 검증 출력에는 이름, 타입, version만 남긴다.
- AI worker task definition은 두 SSM parameter를 같은 이름의 환경 변수로 주입하도록 변경했다.
- task definition을 실제 ECS service에 반영하려면 develop·prod Terraform plan 확인 뒤 별도 apply 승인이 필요하다.
- 현재 배포된 AI 코드에는 두 환경 변수 설정이 없어, 후속 AI 코드 배포 전에는 새 환경 변수가 주입되어도 런타임 동작은 바뀌지 않는다.
- `terraform fmt -recursive`, `git diff --check`, sandbox 밖에서 실행한 develop·prod `terraform validate`가 통과했다.
- develop plan과 prod plan은 각각 worker task definition 교체 1건, ECS worker service task definition 갱신 1건만 포함하며 모두 `1 to add, 1 to change, 1 to destroy`다.
- 사용자 승인 후 두 plan을 apply했다. develop과 prod 모두 `1 added, 1 changed, 1 destroyed`로 완료됐다.
- develop worker는 revision `5`, prod worker는 revision `4`가 됐다. 두 revision의 `secrets`에는 환경별 `MESSAGE_FEEDBACK_MODEL`, `MESSAGE_FEEDBACK_REVIEW_ENABLED` SSM path가 포함된다.
- apply 후 develop·prod worker service는 모두 desired/running `1/1`, PRIMARY deployment `COMPLETED` 상태다.

## 2026-07-22 LAN-192 prod Discord 장애 알림

- Discord 알림은 prod만 대상으로 하고 develop은 제외한다.
- Sentry와 Grafana 알림은 각각 `#alerts-sentry-prod`, `#alerts-grafana-prod` 채널로 분리한다.
- Sentry는 prod BE·AI project마다 신규·회귀 rule과 반복 급증 rule을 둔다. 신규·회귀 예외는 즉시 알리고, 같은 issue가 5분 동안 10회 이상 발생하면 급증 알림을 보내며, 같은 rule의 재발송은 issue별 30분 간격으로 제한한다. 개별 반복 event와 resolved 상태는 알리지 않는다.
- Grafana는 초기에는 prod BE·AI의 HTTP 5xx 장애만 알린다. 5분 동안 5xx가 5건 이상이면서 오류율이 20% 이상인 조건을 1분마다 평가하고, 2분 동안 유지되면 firing한다.
- Grafana P95 응답시간, 트래픽 없음, 지표 없음, 에러 로그 발생량은 정상 기준이나 수집 공백을 장애와 구분하기 어려워 초기 범위에서 제외한다.
- Grafana 복구 알림은 incident 종료 확인을 위해 발송한다. Sentry resolved 알림은 제외한다.
- Grafana는 기본 Discord webhook contact point를 사용한다. contact point test notification이 `#alerts-grafana-prod`에 도착한 것을 확인했다.
- Sentry 공식 Discord integration은 현재 Saynow 플랜에서 `Requires Team Plan or above`로 차단된다. 현재 조직의 project service hook API도 `unavailable_feature`이므로 직접 webhook 방식은 사용할 수 없다.
- 사용자는 Sentry Team 업그레이드 대신 prod 전용 AWS Lambda relay 사용을 승인했다. Sentry Internal Integration의 alert rule action이 API Gateway endpoint를 호출하고, Lambda가 payload를 Discord webhook 형식으로 변환해 `#alerts-sentry-prod`로 전달한다.
- 초기 Function URL ingress가 Sentry 기본 1초 timeout을 안정적으로 충족하지 못해 API Gateway의 비동기 Lambda 통합으로 외부 수신 경로를 변경했다. Sentry custom header는 조직 보안 정책으로 설정할 수 없어 Sentry App의 공식 `Sentry-Hook-Signature` HMAC-SHA256을 검증한다.
- Discord webhook URL과 Sentry App signing secret은 Terraform 변수나 state에 넣지 않고 `/landit/prod` SSM에 Terraform 밖에서 작성한다. 기존 `/landit/prod/LANDIT_SENTRY_RELAY_AUTH_TOKEN` path에는 signing secret을 저장하고 Terraform은 parameter ARN과 이름만 참조한다.
- Discord webhook URL과 integration credential은 저장소, Terraform 변수와 state, 문서에 기록하지 않는다.
- Lambda handler는 invalid signature `401`, malformed JSON `400`, non-prod와 environment 누락 `204` 제외, prod Discord payload 변환, base64 body decode, SSM batch 조회, Discord explicit User-Agent를 unit test로 검증했고 8개 테스트가 통과했다.
- prod Terraform은 Python 3.13 arm64 Lambda, reserved concurrency 2, 14일 log group, Function URL과 공개 URL 호출에 필요한 두 permission을 추가한다. 실행 role의 secret 권한은 signing secret과 Discord webhook SSM parameter 두 개에 대한 `ssm:GetParameters`다.
- prod plan은 Lambda relay 관련 리소스만 `8 to add, 0 to change, 0 to destroy`이며 기존 ECS와 네트워크 변경은 없다. Function URL output은 sensitive로 표시되고 secret 값은 plan에 포함되지 않았다.
- 사용자 승인 후 초기 plan을 apply해 `8 added, 0 changed, 0 destroyed`로 Lambda relay를 생성했다. 후속 apply에서는 SSM batch 조회 IAM과 Discord User-Agent를 Lambda에 반영했다.
- 실제 Sentry 서명 request에서 invalid signature는 `401`, develop은 `204`, warm prod delivery는 `204`였지만 약 4.07초가 걸렸고 cold prod는 Lambda 5초 timeout으로 `502`가 발생했다.
- 로컬에서 같은 Python `urllib` Discord request는 약 0.36초였으므로 4초 지연은 Lambda에서 Discord로 나가는 경로에서만 재현됐다.
- Sentry 공식 소스의 Sentry App webhook 기본 timeout은 1초, hard timeout은 5초다. 사용자는 Sentry ingress가 즉시 응답하고 같은 Lambda의 비동기 invocation이 signature 검증과 Discord delivery를 처리하는 구조를 승인했다.
- 사용자는 AI WARNING 로그의 `Value error` 문자열 오분류와 prod 미매핑 404 재발 관측도 LAN-192 하나에서 처리하도록 범위를 확장했다.
- AI는 root·Uvicorn 로그에 logfmt `level` 필드를 추가하고 Grafana AI·Overview가 AI error를 `ERROR|CRITICAL` level로만 조회한다. 기존 workflow log level과 message는 바꾸지 않는다.
- prod ALB는 전용 비공개 S3 bucket에 access log를 저장하고 30일 뒤 만료한다. WAF는 Common Rule Set, Amazon IP Reputation List, IP당 5분 2,000회 rate rule을 모두 `Count`로 시작하며 develop에는 적용하지 않는다.
- WAF `Block` 전환은 이번 범위에서 제외한다. 7일간 access log, WAF metric, sampled request를 관찰한 뒤 정상 사용자와 공유 NAT 영향을 검토하고 별도 승인을 받아야 한다.
- Sentry relay는 공개 ingress에서 서명 형식과 700,000 bytes 제한만 검사하고 자기 Lambda를 비동기 호출한다. 내부 delivery가 SSM signing secret으로 HMAC을 검증하고 prod payload만 Discord로 전달하도록 구현했으며 unit test 12개가 통과했다.
- relay Terraform은 memory 512 MiB, timeout 10초, reserved concurrency 2, 비동기 최대 event age 300초와 retry 2회, 자기 함수 invoke 권한으로 갱신했다.
- BE는 Spring Boot 기본 콘솔 포맷이 로그 레벨을 보존하므로 애플리케이션 변경 없이 Grafana에서 레벨 위치를 조회한다.
- AI `feat/LAN-192`는 root와 Uvicorn 로그를 `level`, `logger`, `message` 형식으로 통합했고 전체 unittest 188개가 통과했다.
- Grafana AI 에러 패널은 `logfmt`의 `ERROR|CRITICAL`, Overview의 BE 에러 target은 Spring `ERROR|FATAL` 위치만 조회하도록 분리했다. JSON과 dashboard 계약 스크립트가 통과했다.
- prod module은 ALB access log 전용 SSE-S3 bucket, public access block, 30일 lifecycle과 account·region 제한 log delivery policy를 추가했다.
- prod WAF Web ACL은 default allow이며 Common Rule Set, Amazon IP Reputation List, IP당 5분 2,000회 rate rule을 모두 Count로 구성했다. develop은 module 기본값으로 비활성 상태를 유지한다.
- `terraform fmt -recursive -check`, dev·prod `terraform validate`, `git diff --check`가 통과했다. prod plan과 apply, live 검증은 다음 단계에서 수행한다.
- 저장한 prod plan `/tmp/lan192-prod-observability.tfplan`은 `8 added, 3 changed, 0 destroyed`다. Sentry Lambda·IAM·비동기 설정, ALB access log 속성, 전용 S3 구성, WAF Web ACL과 association만 포함하며 ECS·VPC 교체는 없다.
- 사용자 승인 후 관측성 plan을 apply해 `8 added, 3 changed, 0 destroyed`를 확인했다. Lambda 설정, ALB access log, 전용 S3 bucket, WAF Web ACL association과 세 Count rule을 live 상태에서 확인했고 실제 ALB `.log.gz` object도 생성됐다.
- Function URL ingress는 valid request에서 약 1.12~1.41초가 걸렸다. API Gateway 비동기 Lambda integration을 별도 plan `8 added, 0 changed, 0 destroyed`로 적용한 뒤 cold prod 요청은 약 0.10초, warm prod와 develop 요청은 약 0.05초에 `204`를 반환했다.
- Sentry Internal Integration `Landit Prod Discord Relay`을 API Gateway endpoint로 교체했다. prod BE·AI 각각 신규·회귀 rule과 5분 10회 급증 rule을 생성했고 기존 email rule은 유지했다. 합성 prod BE event에서 Sentry rule trigger 시각과 Lambda ingress·delivery의 오류 없는 실행을 확인했다.
- 기존 Function URL과 공개 invoke permission 제거 plan은 `0 added, 0 changed, 3 destroyed`였고 적용 결과도 동일했다. 외부 Sentry ingress는 API Gateway 경로만 남았다.
- AI prod 최신 task의 CloudWatch 로그 44건이 모두 `level`과 `logger` 필드를 포함했다. Grafana `Landit AI`와 `Landit Overview`는 운영본과 저장소 차이가 요청한 네 LogQL target뿐임을 확인한 뒤 각각 version 5와 4로 동기화했다.
- 반영 뒤 두 dashboard 운영 JSON은 저장소 JSON과 정확히 일치했고 화면에 query error가 없었다. Grafana datasource query API에서 AI `logfmt` query가 오류 없이 20건을 반환했다. 동기화용 임시 Editor service account와 token은 검증 직후 삭제했다.
- 독립 리뷰에서 공개 API Gateway가 HMAC 검증 전 비동기 큐를 점유할 수 있는 P2를 확인했다. Sentry 공식 US·US2·EU outbound IPv4만 허용하는 resource policy와 초당 1건, burst 5건의 method settings를 추가했다. 일반 사용자 ALB WAF의 Count 정책에는 영향을 주지 않는다.
- Lambda async 실패 destination과 DLQ가 없어 최대 300초와 재시도 2회를 모두 소진한 이벤트는 폐기되는 P3 위험이 남는다. 별도 SQS와 재처리 운영이 필요한지 관찰 후 결정하고 이번 범위에는 추가하지 않는다.
- API Gateway 보호 saved plan은 deployment 교체와 policy·stage 갱신만 포함해 `2 added, 2 changed, 1 destroyed`였고 동일하게 적용됐다. 일반 외부 IP는 `403`, Sentry 합성 prod event는 alert 처리 뒤 Lambda ingress·delivery 두 호출과 오류 0건을 확인했다.
- live API Gateway stage는 초당 1건, burst 5건이며 resource policy는 Sentry outbound IPv4 10개만 Allow한다.
- AWS가 축약 resource policy ARN을 전체 ARN으로 정규화해 발생한 plan drift는 `aws_api_gateway_rest_api_policy` 분리로 제거했다. 정규화 plan은 `2 added, 1 changed, 1 destroyed`로 적용했고 후속 prod plan은 `No changes`였다.
- 독립 재리뷰는 Sentry 공식 outbound 10개와 allowlist 일치, POST root 범위, live throttling 연결을 확인했고 criterion-linked P1·P2 blocker가 남지 않았다고 결론냈다. Lambda unit 12개, API 보호 계약, Grafana JSON·LogQL, fmt, diff-check, dev·prod validate와 secret 패턴 검사를 독립적으로 통과했다.
- 기존 Grafana 단일 5xx 조건은 `4/4`처럼 오류율이 높아도 5건 미만이면 알리지 않고, 요청 metric No Data를 Normal로 처리해 관측 공백을 놓치는 사각지대가 있다.
- 사용자는 알림 노이즈와 탐지 속도를 함께 고려하는 균형형 개선안을 승인했다. BE·AI에 최근 2분 3건·50%를 1분 유지하는 CRITICAL, 최근 10분 10건·20%를 3분 유지하는 WARNING, runtime metric이 10분간 사라진 상태를 5분 유지하는 MONITORING rule을 각각 둔다.
- 5xx 오류율에서는 BE `/actuator` 계열과 AI `/health`를 제외한다. 알림은 `service`, `severity`로 그룹화하고 group wait 30초, group interval 5분, repeat interval 1시간을 적용하며 Firing과 Resolved를 모두 `#alerts-grafana-prod`로 보낸다.
- MONITORING은 BE `jvm_threads_live`, AI `process_thread_count`를 사용한다. 관측 공백은 서비스 장애와 수집 장애를 단정하지 않고 두 상태를 함께 확인해야 하는 운영 신호로 표시한다.
