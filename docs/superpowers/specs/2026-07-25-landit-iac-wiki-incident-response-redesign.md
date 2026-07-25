# Landit IaC Wiki 장애 대응 중심 개편 설계

## 목표

Landit 인프라를 처음 접한 개발자와 production 장애 대응자가 같은 Wiki에서 구조, 정상 운영 절차, 관측 신호, 장애 대응 순서를 찾을 수 있게 한다.

현재 IaC Wiki의 역할 중심 틀은 유지하되 최신 `origin/main`을 기준으로 전체 내용을 다시 검증한다. production 장애 대응 Runbook과 Push 알림 운영 문서를 추가하고, 정상 운영과 장애 대응 문서의 책임을 분리한다.

## 현재 상태와 문제

게시된 IaC Wiki `master`는 `0f52816`이며 코드 기준을 `16223d3`으로 기록한다. 이번 설계의 소스 기준은 작업 시작 시점 `origin/main`의 `a2729e1`이다.

기존 Wiki 작성 뒤 다음 운영 구조가 추가되거나 크게 바뀌었다.

- Sentry production issue alert의 API Gateway와 Lambda 비동기 Discord 중계.
- Grafana production 다단계 장애 규칙과 Discord notification policy.
- production ALB access log와 WAF Count 관측.
- Grafana 병목·배포 영향 dashboard와 Loki 배포 마커.
- dev·prod Push Queue, DLQ, Scheduler, Alarm과 운영 절차.

기존 `Troubleshooting`은 증상별 확인 순서를 제공하지만 장애 감지부터 종료까지의 공통 지휘 흐름은 없다. `Observability`는 현재 소스의 알림 경로와 운영 제약을 충분히 설명하지 않는다. Home의 현재 상태와 기준 커밋도 최신 소스와 다르다.

## 참고 구조에서 채택할 원칙

### Landit Backend Wiki

- 정상 릴리즈 절차와 Troubleshooting을 분리한다.
- Troubleshooting 첫 화면에 빠른 증상 분류표를 둔다.
- 반복되는 문제는 증상, 확인, 조치, 복구 확인 순서로 작성한다.
- 애플리케이션 오류를 BE 단독 원인으로 단정하지 않고 같은 시각의 AI와 인프라 증거를 연결한다.

### Landit AI Wiki

- 배포 절차, 관측성, 장애 진단의 문서 책임을 분리한다.
- 문서 기준 커밋과 실제 배포 SHA를 별도 개념으로 다룬다.
- 오류 코드만으로 provider, model, network 원인을 단정하지 않는다.
- 사용자 원문, prompt, credential을 진단 기록에 남기지 않는다.

## 선택한 접근법

역할 중심 전면 개편을 사용한다.

Runbook 한 장만 추가하면 최신 관측성과 Push 운영 구조가 계속 누락된다. 반대로 AWS 리소스별로 페이지를 세분화하면 처음 대응하는 사람이 여러 페이지를 오가야 하고 갱신 비용이 커진다.

기존 페이지 이름은 가능한 한 유지해 외부 링크를 보존한다. 역할이 달라진 페이지는 본문과 Sidebar 설명을 다시 쓰고, 새로운 책임이 필요한 경우에만 페이지를 추가한다.

## 대상 독자와 사용 흐름

### 신규 합류자

1. Home에서 관리 범위와 최신 문서 기준을 확인한다.
2. Getting Started에서 인증과 첫 read-only 검증을 수행한다.
3. Infrastructure Architecture에서 환경, state, 런타임과 관측 경계를 이해한다.
4. Terraform Operations에서 plan과 승인 절차를 확인한다.

### 일상 운영자

1. 변경 대상에 맞는 운영 페이지를 선택한다.
2. plan과 변경 영향 범위를 검토한다.
3. 승인된 변경만 적용한다.
4. 변경 유형별 실제 리소스와 사용자 경로를 검증한다.

### production 장애 대응자

1. Incident Response Runbook에서 대응 단계와 권한 경계를 확인한다.
2. Observability에서 알림의 의미와 원본 신호를 확인한다.
3. Troubleshooting의 빠른 분류표에서 증상별 조사 순서로 이동한다.
4. 복구 뒤 Runbook의 종료 조건과 기록 항목을 확인한다.

## 정보 구조

`_Sidebar.md`는 다음 순서로 구성한다.

```text
Landit IaC
  시작하기
    Home
    Getting Started
  구조 이해하기
    Infrastructure Architecture
    Architecture Decisions
  변경하고 운영하기
    Terraform Operations
    Secrets and Configuration
    Observability and Alerting
    Push Notifications
    Content Delivery
  장애 대응하기
    Incident Response Runbook
    Troubleshooting
  Repository
    Source Code
    Actions
    Pull Requests
```

## 페이지 책임

| 파일 | 책임 | 변경 방식 |
| --- | --- | --- |
| `Home.md` | 현재 관리 범위, 문서 기준, 독자별 진입점 | 전면 갱신 |
| `Getting-Started.md` | 인증, 저장소 준비, 첫 read-only 확인과 plan | 최신 workflow 기준 갱신 |
| `Infrastructure-Architecture.md` | 환경, state, 네트워크, 런타임, 비동기 작업, 관측 경계 | 최신 리소스 흐름으로 갱신 |
| `Architecture-Decisions.md` | 확정된 결정, 보류 항목, ADR 작성 기준 | 실제 코드와 운영 근거로 갱신 |
| `Terraform-Operations.md` | 정상적인 plan, 승인, apply, 변경 유형별 검증 | 정상 운영 절차에 집중 |
| `Secrets-and-Configuration.md` | SSM 이름, 소비 서비스, 변경과 재배포 조건 | 최신 registry 기준 갱신 |
| `Observability.md` | Sentry, Grafana, CloudWatch, ALB log, WAF, Discord 알림 | 제목과 본문을 Observability and Alerting 역할로 확장 |
| `Push-Notifications.md` | Queue, DLQ, Scheduler, Alarm, 활성화와 검증 | 새 페이지 |
| `Content-Delivery.md` | shared content 저장, 배포, cache, 삭제 조건 | 최신 적용 상태로 갱신 |
| `Incident-Response-Runbook.md` | production 장애의 감지부터 종료까지 공통 대응 | 새 페이지 |
| `Troubleshooting.md` | 증상별 확인, 조치, 복구 확인 | 빠른 분류표와 반복 형식으로 전면 갱신 |
| `_Sidebar.md` | 역할과 작업 순서 기반 탐색 | 전면 갱신 |

기존 파일은 삭제하거나 이름을 바꾸지 않는다. `Observability.md`의 파일명도 기존 링크 보존을 위해 유지한다.

## Incident Response Runbook

### 범위

Runbook은 production 장애 대응을 기준으로 한다. develop은 production 변경 전 재현, 수정 검증, 안전한 smoke test 용도로만 사용한다.

Runbook은 개별 장애의 원인을 미리 단정하지 않는다. 장애 대응자가 같은 순서로 범위를 좁히고, 승인 경계를 지키며, 복구를 증명하도록 한다.

### 대응 단계

1. **감지와 접수.** 알림 상태, 발생 시각, 환경, 서비스, 조건을 기록한다.
2. **영향 확인.** 사용자 경로, health endpoint, 오류율, 지연, 영향 기능과 범위를 확인한다.
3. **대응 선언.** 한 명을 진행 담당으로 두고 사실, 가설, 조치, 결과를 시간순으로 기록한다.
4. **증거 수집.** Sentry, Grafana, CloudWatch, ECS, ALB와 관련 BE·AI 로그를 같은 시간대로 맞춘다.
5. **원인 경계 좁히기.** 애플리케이션, 설정, 배포, 네트워크, 인프라와 관측 공백을 구분한다.
6. **완화 선택.** 최소 영향의 가역적 조치를 선택하고 필요한 승인을 받는다.
7. **복구 검증.** 사용자 경로, ECS deployment, target health, 오류 신호, Terraform drift를 함께 확인한다.
8. **종료와 후속 조치.** 장애 종료 시각, 남은 위험, 재발 방지 작업과 문서 갱신 대상을 남긴다.

### 심각도 해석

- `CRITICAL`은 즉시 사용자 영향과 서비스 상태를 확인하는 장애 신호다.
- `WARNING`은 제한적 오류나 성능 저하가 지속되는지 확인하는 신호다.
- `MONITORING`은 telemetry 공백 신호이며 서비스 장애와 수집 장애를 모두 조사한다.
- Sentry 신규·회귀·급증 알림은 원인을 확정하지 않는다. event와 같은 시각의 서비스·인프라 증거를 연결한다.

Grafana의 현재 임계치와 notification policy는 `docs/observability.md`를 기준으로 옮긴다. Wiki에는 검증되지 않은 새 임계치를 만들지 않는다.

### 증거 수집 순서

1. Discord 알림의 원본 Sentry 또는 Grafana 링크.
2. production BE와 AI health endpoint.
3. Grafana의 동일 시간대 지표와 Loki 로그.
4. Sentry event, trace, release와 stack trace.
5. ECS service deployment, task stop reason과 CloudWatch startup log.
6. ALB target health, access log와 WAF Count 결과.
7. 최근 BE·AI 배포 SHA와 IaC 변경 이력.
8. 필요할 때 Terraform state와 read-only plan.

`AI_GENERATION_FAILED`, HTTP 5xx, telemetry missing 같은 상위 신호만으로 model, provider, BE, AI 또는 인프라 실패라고 단정하지 않는다.

### 변경 권한 경계

다음 조회는 장애 범위를 확인하기 위한 read-only 기본 절차로 둔다.

- Sentry event와 trace 조회.
- Grafana dashboard, alert rule 상태와 Loki 조회.
- AWS `describe`, `list`, `get` 계열 조회.
- health endpoint와 비민감 API smoke test.
- Terraform state 조회와 plan.

다음 조치는 실행 전에 정확한 대상, 예상 영향, 복구 방법을 제시하고 사용자 승인을 받는다.

- Terraform apply와 destroy.
- ECS 재배포, scale 변경과 task 강제 교체.
- SSM 값과 runtime secret 변경.
- WAF Count에서 Block으로 전환.
- Grafana·Sentry alert rule과 notification route 변경.
- Queue, DLQ 메시지 이동·삭제·재처리.
- S3 object, log, state와 운영 데이터 삭제.

### 복구 완료 조건

장애 종료는 알림이 사라졌다는 사실 하나로 판단하지 않는다.

- 사용자 경로와 서비스 health가 정상이다.
- ECS PRIMARY deployment가 완료되고 desired count와 running count가 일치한다.
- ALB target이 healthy다.
- 동일 오류의 신규 발생과 오류율이 정상 범위로 돌아왔다.
- Sentry와 Grafana에서 대응 이후의 새 이상 신호가 없다.
- IaC 변경이 있었다면 후속 plan에 의도하지 않은 drift가 없다.
- 임시 조치, 남은 위험, 추적할 후속 작업이 기록됐다.

## Troubleshooting 작성 규칙

페이지 첫 부분에 다음 열을 가진 빠른 분류표를 둔다.

| 증상 | 첫 확인 지점 | 관련 절차 |
| --- | --- | --- |

각 문제는 다음 순서로 작성한다.

1. 증상.
2. 확인.
3. 조치.
4. 복구 확인.

초기 범위는 다음 문제를 포함한다.

- production 5xx 또는 telemetry missing 알림.
- Sentry 신규·회귀·급증 알림.
- ECS deployment 정체와 task 반복 종료.
- ALB target unhealthy와 public health 실패.
- SSM 변경 미반영과 잘못된 task definition mapping.
- Grafana metric·log 수집 공백.
- Sentry Discord relay 또는 Grafana Discord 알림 미수신.
- WAF Count와 ALB access log 조사.
- Push Queue 적체, DLQ 발생, Scheduler·Alarm 문제.
- Terraform plan의 예상하지 않은 변경과 backend·OIDC 오류.
- CloudFront 콘텐츠 미반영.

정상 변경 절차는 각 운영 페이지로 연결하고 Troubleshooting에서 반복하지 않는다.

## 기준 소스

| Wiki 영역 | 기준 소스 |
| --- | --- |
| 현재 범위와 root | `README.md`, `environments/`, `modules/` |
| Terraform 실행과 승인 | `.github/workflows/terraform.yml`, `docs/developer-guide.md` |
| SSM과 ECS 주입 | `docs/ssm-parameters.md`, task definition 코드 |
| 관측성과 장애 알림 | `docs/observability.md`, `grafana/`, relay Terraform과 Lambda |
| Push 알림 인프라 | `docs/push-notifications.md`, app platform module |
| 콘텐츠 제공 | `docs/content-storage.md`, shared root |
| 장애 진단 | 실제 코드, workflow, 운영 문서와 확인된 live 계약 |

Wiki와 요약 문서가 실제 코드와 다르면 최신 `origin/main`의 Terraform과 workflow를 우선한다. 적용 상태는 코드 존재만으로 단정하지 않고 현재 문서의 검증 기록이나 read-only live 조회로 구분한다.

## 보안과 기록 원칙

- secret 값, token, webhook URL, access key, private key와 DB credential을 기록하지 않는다.
- 사용자 원문, raw prompt, authorization header와 cookie를 장애 기록에 붙이지 않는다.
- AWS account ID, 내부 IP, security group ID와 resource ARN은 절차 이해에 필요하지 않으면 예시로 고정하지 않는다.
- 명령은 `<cluster>`, `<service>`, `<task-arn>` 같은 명시적 placeholder를 사용한다.
- 실제 출력 예시는 비밀이 아닌 상태와 필드만 보여준다.
- 사실, 가설, 실행한 조치, 검증 결과를 구분한다.

## 문서 갱신과 이동

- 기존 Wiki 페이지는 최신 기준으로 다시 쓰되 기존 URL을 유지한다.
- 새 Runbook과 Push 페이지를 Sidebar와 Home에 연결한다.
- Observability와 Troubleshooting의 중복 절차는 각 책임 페이지로 이동한다.
- 기존 내용이 최신 소스와 다르면 삭제하거나 현재 상태로 고친다.
- 아직 적용하지 않은 계획은 현재 운영 상태처럼 쓰지 않는다.
- BE·AI의 애플리케이션 배포와 릴리즈 정책은 해당 저장소 Wiki로 연결하고 IaC Wiki에서 복제하지 않는다.

## 검증

### 로컬 Wiki 검증

- 예상한 Markdown 파일만 변경됐는지 확인한다.
- 모든 파일에 H1이 하나 있는지 확인한다.
- Sidebar와 본문 내부 링크의 대상 파일과 anchor가 존재하는지 확인한다.
- `git diff --check`를 실행한다.
- secret, token, webhook, private key와 access key 패턴을 검색한다.
- 미완성 문구와 값이 정해지지 않은 placeholder가 없는지 확인한다.
- 코드 경로, workflow 입력, alert 이름과 운영 상태를 최신 기준 소스와 대조한다.

### 게시 검증

- Wiki `master`의 새 commit을 확인한다.
- Home, 기존 페이지와 새 페이지가 공개 URL에서 HTTP `200`을 반환하는지 확인한다.
- Sidebar에서 모든 페이지로 이동할 수 있는지 확인한다.
- 표, 코드 블록과 Mermaid가 GitHub에서 깨지지 않는지 확인한다.
- 게시본에 secret과 내부 식별자가 노출되지 않았는지 다시 검색한다.

## 제외 범위

- Terraform 코드와 AWS 리소스 변경.
- SSM 값, Grafana·Sentry 설정과 Discord webhook 변경.
- BE·AI Wiki와 애플리케이션 저장소 변경.
- 자동 Wiki 동기화 workflow 추가.
- 새로운 장애 임계치와 운영 정책 결정.
- 과거 incident를 사실 확인 없이 예시로 재구성하는 작업.
