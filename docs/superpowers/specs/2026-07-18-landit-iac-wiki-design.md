# Landit IaC GitHub Wiki 설계

## 목표

신규 합류자와 인프라 운영자가 Landit의 인프라 구조를 이해하고, 안전하게 Terraform 작업과 운영 점검을 수행할 수 있는 GitHub Wiki를 만든다.

README는 저장소의 현재 상태와 주요 문서 링크를 짧게 보여준다. Wiki는 저장소 곳곳에 흩어진 구조, 실행 절차, 운영 규칙을 사용 목적에 맞게 연결한다.

## 현재 상태

- 기존 `landit-iac` Wiki에는 기본 문구만 있는 `Home.md` 한 장이 있다.
- Wiki 저장소는 `landit-iac.wiki.git`이며 기본 브랜치는 `master`다.
- 작성 기준은 작업 시작 시 최신 `origin/main`인 `16223d3` 이후 상태다.
- `origin/main`에는 `bootstrap`, `shared`, `dev`, `prod` Terraform root가 있다.
- `modules/app-platform`은 develop과 production의 ECS Fargate application platform을 정의한다.
- `docs/`에는 개발 절차, SSM, 관측성, 콘텐츠 제공 구조가 나뉘어 있다.

기준 커밋은 문서가 어느 시점의 코드를 설명하는지 표시하기 위한 값이다. Wiki를 갱신할 때는 최신 `origin/main`으로 교체한다.

## 참고한 구성

### GitHub Wiki 공식 방식

GitHub는 README와 별도로 긴 프로젝트 문서를 Wiki에 둘 수 있도록 지원한다. `_Sidebar.md`를 만들면 모든 페이지에서 같은 탐색 메뉴를 제공할 수 있다.

### Landit Backend Wiki

Landit Backend Wiki는 `Home`, `Getting Started`, `Project Architecture`, `API Reference`, `Development Guide`, `Release Management`처럼 독자의 목적에 따라 페이지를 나눈다. 페이지 수를 작게 유지하고, Home에서 각 페이지의 역할을 설명한다.

### SayNow Backend Wiki

SayNow Backend Wiki는 `Deployment and Operations`와 `Troubleshooting`을 분리한다. 정상 작업 절차와 장애 확인 순서를 섞지 않아 운영자가 필요한 내용을 빨리 찾을 수 있다.

## 선택한 접근법

역할 중심 구조를 사용한다.

저장소 문서를 그대로 복사하면 같은 내용이 두 곳에서 달라질 수 있다. 반대로 운영 Runbook만 만들면 신규 합류자가 전체 구조를 이해하기 어렵다. 역할 중심 구조는 온보딩, 아키텍처 이해, 일상 작업, 장애 대응을 분리하면서 기존 파일을 기준 소스로 연결할 수 있다.

## 대상 독자와 사용 흐름

### 신규 합류자

1. Home에서 현재 인프라 범위와 문서 기준을 확인한다.
2. Getting Started에서 필요한 도구와 AWS 인증 방식을 준비한다.
3. Infrastructure Architecture에서 환경과 AWS 리소스 관계를 이해한다.
4. Terraform Operations에서 첫 plan을 실행한다.

### 인프라 운영자

1. Terraform Operations에서 변경과 승인 절차를 확인한다.
2. Secrets and Configuration에서 SSM 변경과 ECS 재배포 조건을 확인한다.
3. Observability 또는 Troubleshooting에서 배포 결과와 장애를 점검한다.
4. 구조 변경이 필요하면 Architecture Decisions에서 기존 결정과 보류 항목을 확인한다.

## 페이지 구조

| 파일 | 역할 | 주요 기준 소스 |
| --- | --- | --- |
| `Home.md` | 현재 범위, 기준 시점, 문서 안내, 갱신 원칙 | `README.md`, 최신 `origin/main` |
| `Getting-Started.md` | 도구, AWS 인증, 저장소 준비, 첫 validate와 plan | `docs/developer-guide.md`, Terraform root |
| `Infrastructure-Architecture.md` | 환경, 네트워크, ECS, ALB, ECR, SQS, S3, CloudFront 관계 | `environments/`, `modules/app-platform/` |
| `Terraform-Operations.md` | 로컬 실행, GitHub Actions plan/apply, 승인, 검증 | `.github/workflows/terraform.yml`, `docs/developer-guide.md` |
| `Secrets-and-Configuration.md` | SSM registry, ECS secret 주입, 값 변경 후 재배포 | `docs/ssm-parameters.md`, task definition 코드 |
| `Observability.md` | Sentry, OTLP, CloudWatch Logs, Firehose, Grafana dashboard | `docs/observability.md`, `grafana/`, sync script |
| `Content-Delivery.md` | shared S3, CloudFront OAC, 콘텐츠 key와 교체 절차 | `docs/content-storage.md`, `environments/shared/` |
| `Troubleshooting.md` | 초기화, plan, ECS 배포, health check, SSM, Grafana 문제 확인 순서 | 코드, workflow, 검증 기록 |
| `Architecture-Decisions.md` | 확정된 결정, 보류 항목, ADR 작성 기준 | `docs/architecture-questions.md`, Git history |
| `_Sidebar.md` | 시작하기, 이해하기, 운영하기 순서의 탐색 메뉴 | 전체 Wiki 페이지 |

## 페이지별 내용

### Home

- Landit IaC가 관리하는 범위를 한 문단으로 설명한다.
- 기준 브랜치와 기준 커밋을 표시한다.
- `shared`, `develop`, `production`의 현재 역할을 요약한다.
- 독자의 목적별로 다음에 읽을 페이지를 안내한다.
- 코드와 Wiki가 다르면 최신 `origin/main`을 우선한다는 원칙을 명시한다.

### Getting Started

- Terraform, AWS CLI, Git 준비 항목을 적는다.
- `AWS_PROFILE=landit`, `ap-northeast-2` 기준을 설명한다.
- 저장소를 받은 뒤 확인할 문서와 첫 검증 명령을 순서대로 제시한다.
- `bootstrap`은 state backend 관리자 작업에만 사용한다고 분리한다.
- 실제 apply 명령은 사용자 확인과 plan 검토가 필요하다는 경고를 명령 가까이에 둔다.

### Infrastructure Architecture

- Terraform root와 state key의 소유 관계를 먼저 설명한다.
- develop과 production이 같은 module을 사용하되 별도 state와 리소스를 가진다는 점을 표시한다.
- ALB host rule이 BE API와 AI 서비스를 나누는 흐름을 설명한다.
- API, AI, worker, SQS, application bucket의 관계를 다이어그램으로 보여준다.
- shared 콘텐츠 버킷과 CloudFront가 환경별 application bucket과 별개임을 표시한다.
- DNS는 Vercel에서 관리하므로 Terraform 범위 밖이라는 경계를 적는다.

다이어그램에는 secret 값, 계정 상세 정보, 내부 IP를 넣지 않는다.

### Terraform Operations

- root별 `fmt`, `init`, `validate`, `plan` 명령을 제공한다.
- GitHub Actions의 `target`, `operation`, `confirm_environment` 입력을 설명한다.
- plan artifact와 environment required reviewer 승인 흐름을 순서대로 설명한다.
- apply는 `main`에서만 가능하고 production은 추가 확인값이 필요하다는 조건을 강조한다.
- apply 뒤 Terraform plan, ECS service, target health 등 변경 유형에 맞는 검증을 안내한다.

### Secrets and Configuration

- 실제 값을 제외하고 SSM parameter 이름, 타입, 소비 서비스를 표로 정리한다.
- SSM parameter 생성과 ECS task definition `secrets` 연결이 별도 단계임을 설명한다.
- SSM 값만 변경해도 실행 중인 task에는 자동 반영되지 않는다고 명시한다.
- 값 변경 뒤 새 deployment, task definition 확인, 실제 사용 경로 검증 순서를 제공한다.
- secret 값을 Terraform state, Wiki, shell history, CI log에 남기지 않는 규칙을 적는다.

### Observability

- Sentry, OTLP 애플리케이션 메트릭, CloudWatch Logs, Firehose, Grafana Loki의 책임을 나눈다.
- BE와 AI의 서비스명, 환경 라벨, 로그 그룹 구분을 설명한다.
- `Landit Overview`, `Landit BE`, `Landit AI` 대시보드의 용도를 안내한다.
- Grafana CloudWatch scrape는 현재 조직 권한 제약으로 사용하지 않는다는 범위를 표시한다.
- 임시 token을 파일이나 Wiki에 기록하지 않는 대시보드 동기화 절차를 연결한다.

### Content Delivery

- `environments/shared`가 공통 콘텐츠를 소유하는 이유를 설명한다.
- private S3 bucket, OAC, CloudFront 조회 흐름을 설명한다.
- `content/*`만 CloudFront에서 읽는 정책과 immutable cache 원칙을 적는다.
- 새 UUID key 업로드, DB URL 변경, 캐시 기간 확인, 이전 객체 삭제 순서를 안내한다.
- 사용자 업로드 파일과 Grafana 실패 로그는 환경별 application bucket에 남는다고 구분한다.

### Troubleshooting

각 문제는 증상, 먼저 볼 곳, 확인 명령, 정상 기준, 다음 조치 순서로 작성한다.

- backend initialization required.
- AWS profile 또는 OIDC role 오류.
- Terraform plan의 예상하지 않은 변경.
- ECS task가 시작되지 않거나 target health가 unhealthy인 경우.
- SSM parameter를 바꿨지만 container에 반영되지 않은 경우.
- CORS 또는 인증 설정이 task definition에 주입되지 않은 경우.
- Grafana에 메트릭이나 로그가 없는 경우.
- CloudFront 콘텐츠가 갱신되지 않은 경우.

실제 원인이 여러 개일 수 있는 문제는 하나의 원인으로 단정하지 않고 확인 순서를 제시한다.

### Architecture Decisions

- 현재 코드와 운영에서 확정된 결정만 요약한다.
- 결정되지 않은 항목은 `보류`로 표시하고 현재 동작처럼 쓰지 않는다.
- 새 ADR은 배경, 결정, 대안, 영향, 검증 기준을 포함한다.
- 코드 수준 변경은 PR에 남기고 아키텍처 수준 결정은 이 페이지에서 연결한다.

## 탐색 구조

`_Sidebar.md`는 독자의 작업 순서에 맞게 구성한다.

```text
Landit IaC
  Home
  시작하기
    Getting Started
  구조 이해하기
    Infrastructure Architecture
    Architecture Decisions
  작업하고 운영하기
    Terraform Operations
    Secrets and Configuration
    Observability
    Content Delivery
    Troubleshooting
  Repository
    Source Code
    Actions
    Pull Requests
```

## 기준 소스와 갱신 원칙

| 변경 대상 | 먼저 확인할 기준 소스 | 함께 갱신할 Wiki |
| --- | --- | --- |
| Terraform root와 module | `environments/`, `modules/` | Infrastructure Architecture |
| workflow 입력과 승인 | `.github/workflows/terraform.yml` | Terraform Operations |
| SSM parameter와 ECS 주입 | `docs/ssm-parameters.md`, task definition 코드 | Secrets and Configuration |
| 로그와 메트릭 전송 | `docs/observability.md`, module 코드 | Observability |
| 콘텐츠 저장과 제공 | `docs/content-storage.md`, shared root | Content Delivery |
| 아키텍처 결정 | ADR, `docs/architecture-questions.md` | Architecture Decisions |

Wiki에는 `현재 코드에 있음`, `적용 완료`, `적용 전`, `확인 필요`를 구분해 쓴다. 실제 AWS 상태를 확인하지 않은 리소스는 적용 완료라고 쓰지 않는다.

## 보안 기준

- secret 값, token, 접근 키, private key, DB credential을 기록하지 않는다.
- SSM은 이름과 타입만 공개하고 값은 예시도 만들지 않는다.
- AWS account ID, 내부 IP, security group ID처럼 운영에 불필요한 식별자는 넣지 않는다.
- 공개 URL은 운영 절차에 꼭 필요한 경우에만 사용하고 코드 또는 현재 응답으로 확인한다.
- destructive 명령은 기본 절차에 넣지 않는다. 필요한 경우 별도 경고와 승인 조건을 적는다.

## 작성과 게시 절차

1. 최신 `origin/main`의 코드와 문서를 페이지별 기준 소스로 읽는다.
2. 필요한 현재 상태만 AWS와 공개 endpoint에서 읽기 전용으로 확인한다.
3. `landit-iac.wiki.git`의 `master`에서 페이지와 `_Sidebar.md`를 작성한다.
4. 페이지 간 중복을 줄이고 기준 소스 링크를 추가한다.
5. Markdown, 링크, 민감정보, 현재 상태 표현을 검토한다.
6. Wiki 변경을 하나의 문서 커밋으로 만든다.
7. 사용자 검토 뒤 Wiki `master`에 push한다.
8. 게시된 모든 페이지와 사이드바 링크를 확인한다.

## 검증

### 작성 전

- Wiki 기준 브랜치가 최신 `origin/main`인지 확인한다.
- 기존 Wiki 변경과 충돌이 없는지 확인한다.
- live 상태를 단정할 항목은 읽기 전용 검증 근거를 확보한다.

### 로컬

- 예상한 Markdown 파일 10개만 변경됐는지 확인한다.
- Wiki 내부 링크의 대상 파일이 모두 존재하는지 확인한다.
- 코드 블록과 표가 Markdown에서 깨지지 않는지 확인한다.
- `git diff --check`를 실행한다.
- access key, secret, token, Authorization header 패턴이 없는지 검색한다.
- 최신 `origin/main`의 경로와 Wiki에 적은 경로가 일치하는지 확인한다.

### 게시 후

- Home과 8개 본문 페이지가 HTTP `200`을 반환하는지 확인한다.
- `_Sidebar.md`의 모든 내부 링크가 열리는지 확인한다.
- Home의 Repository, Actions, Pull Requests 링크가 올바른 저장소를 가리키는지 확인한다.
- 게시된 페이지에서 secret 값이나 내부 식별자가 노출되지 않았는지 다시 확인한다.

## 제외 범위

- Terraform 또는 AWS 리소스 변경.
- SSM 값 생성과 변경.
- Grafana dashboard 변경과 token 발급.
- 애플리케이션 저장소의 문서 변경.
- 확정되지 않은 아키텍처 결정.
- Wiki 자동 동기화 workflow 추가.

이번 작업은 현재 인프라를 설명하는 Wiki 작성과 게시까지만 수행한다.
