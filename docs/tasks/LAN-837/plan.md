# LAN-837 개발·운영 썸네일 실행 준비

## 승인된 범위와 실행 경계

- 사용자가 배포 후 즉시 사용할 수 있는 개발/운영 환경 설정을 요청했다. 같은 캐릭터만 공용 임베딩 검색으로 재사용하며 신규 생성은 Flare Low, 참조 입력은 캐릭터 얼굴·신체와 공통 화풍 3장이다.
- 코드·Terraform·배포 workflow와 안전한 시크릿 준비 스크립트를 구성한다. 실제 이미지 호출, 앱 배포, 운영 DB 변경은 실행하지 않는다.
- `AGENTS.md`의 `terraform apply`, 실제 AWS 리소스 변경 전 사용자 확인 규칙에 따라 apply는 검토 가능한 plan 준비 뒤 승인받는다. 시크릿 값은 문서/출력/state에 기록하지 않는다.

## 실행 구성

- 개발: 기존 EC2 Compose에 `thumbnail` profile 소비자를 추가한다. AI와 같은 digest, 256MiB 제한, 별도 root 전용 env, 포트 노출 없음. AI 배포 때 함께 시작하고 구버전으로 rollback할 때 이미지 capability label을 확인해 지원하지 않는 소비자는 정지한다.
- 운영: 별도 Fargate 서비스 `prod-landit-thumbnail`, CPU 256/메모리 512, 외부 ingress 없음, 기존 AI 저장소의 같은 이미지 digest를 사용한다. Terraform은 최초 desired_count=0으로 만들어 구버전 AI에서 소비자가 시작되지 않게 한다. AI workflow가 새 이미지를 고정한 뒤 0→1로 시작하고 후속 배포도 같은 workflow가 관리한다. task/desired_count는 Terraform이 배포 버전으로 되돌리지 않는다.
- 큐는 환경별 `${environment}-landit-roleplay-thumbnails`와 DLQ다. visibility=900초, long polling=20초, maxReceiveCount=5, SQS managed encryption, DLQ 적체 경보를 둔다.
- BE는 큐 발행만 허용한다. 전용 운영 소비자 역할은 해당 큐 Receive/Delete/GetQueueAttributes와 공용 버킷 `content/roleplay-thumbnails/*` PutObject만 허용한다. EC2는 동일 역할 정책을 기존 인스턴스 역할에 별도로 연결한다.
- BE 설정은 thumbnail enabled/queue URL/worker token을 주입한다. 제품 롤플레이 스위치 `LANDIT_ROLEPLAY_ENABLED`는 기존 SSM 주입을 유지한다(확인 시 develop/prod 모두 true).
- Worker만 LLM_PROVIDER=openai와 기존 OPENAI_API_KEY를 사용한다. 이미지와 상황 임베딩은 OpenAI 직접 호출하며 기존 대화 서버의 모델·provider 설정을 바꾸지 않는다. backend는 기존 환경별 HTTPS API 도메인이다.
- `/landit/{develop|prod}/ROLEPLAY_THUMBNAIL_WORKER_TOKEN` 한 SecureString을 BE/Worker 양쪽 이름으로 주입한다. `scripts/configure-roleplay-thumbnail-parameters.py`는 기본 읽기 검증이며 `--apply`일 때만 누락 토큰을 생성한다. 기존 값/키는 덮어쓰지 않는다. 환경별 난수 토큰이며 Terraform state에 값을 넣지 않는다.
- bootstrap Terraform에는 환경별 큐·경보·소비자 생성과 새 운영 서비스/태스크 배포를 위한 제한된 권한을 추가한다. 기존 environment required reviewer 경계를 유지한다.

## 적용 순서

1. `landit` AWS account 982529430654를 확인하고 `configure-roleplay-thumbnail-parameters.py --apply`로 누락된 개발/운영 토큰만 만든다.
2. bootstrap 권한 plan을 적용한 뒤 dev/prod 환경 plan을 적용한다. 새 소비자는 아직 시작하지 않는다. 운영 API는 같은 기존 이미지의 설정 추가 태스크로 교체되므로 변경 창을 고려한다.
3. LAN-837 BE를 배포한다. 기존 Flyway migration workflow가 DB 변경을 적용하고 `/reuse`·claim·complete 계약을 준비한다.
4. LAN-837 AI를 배포한다. 개발은 동일 SHA의 Compose 소비자, 운영은 동일 digest의 별도 ECS 소비자를 기동한다. 참조 자산은 AI 이미지 안에 포함되어 런타임 호스트 경로에 의존하지 않는다.
5. 실제 생성/저장/재사용 기능 검증은 배포 후 별도 수행한다. 큐·IAM·프로세스 검증이나 HTTP health만으로 이미지 품질·정확한 캐릭터를 보장했다고 표현하지 않는다.

## 확인한 상태와 검증

- 2026-11-04 기준 개발/운영 OpenAI SecureString 키는 유효하며 썸네일 전용 토큰은 모두 미등록이다. 값은 출력하지 않았다. SSM 수정은 하지 않았다.
- 최신 IaC origin/main `e72345f371dcf40803aab5d021c0df5560d5bbf2` 기준이다. 초기 오래된 로컬 기준에서 보인 모델·ALB 되돌림은 최신 main 반영으로 제거했다. 원래 IaC/BE/AI 작업 트리의 사용자 변경은 보존했다.
- dev/prod `terraform validate` 통과. `terraform fmt -check -recursive`와 diff check 통과. 모의 SSM/Compose runtime·rollback, EC2 보안 계약 테스트 통과. 토큰 준비 3개 unittest 통과.
- 최종 plan: bootstrap 2 add/2 change/0 destroy, dev 5 add/3 change/0 destroy, prod 9 add/2 change/1 replacement. 운영 replacement는 기존 이미지 digest를 보존한 API task definition이며 skip_destroy=true로 이전 revision을 보존한다. 실제 DB/버킷/큐/서버 삭제 계획은 없다. 준비 상태 healthcheck 수정 후 dev/prod plan을 재실행해 같은 변경 건수를 확인했다. 실제 apply 전 원격 변경 여부를 다시 확인한다.
- AI 전체 unittest 1,314건 통과(9 skip), 배포 스크립트 16건과 ECS 검증 shell 테스트 통과. BE 전체 `./gradlew spotlessApply check` 통과. 실제 provider/AWS write/앱 배포는 실행하지 않았다.

## 독립 리뷰와 수정

- 별도 infra_config_review가 IaC e72345f 대비 staged/unstaged/new files 전체의 IAM·환경 분리·SSM·저장 계약·배포/롤백을 검토했다. 추가 보안 확정 결함은 없었다. 그래프를 구축했으나 조회에서 신규 HCL 누락이 있어 직접 전체 소스와 호출 계약으로 보완했다.
- 개발 소비자가 준비 검사를 끝내기 전에 running 상태만으로 배포 성공 처리되는 P2를 확인했다. Worker 준비 marker를 Compose/ECS healthcheck로 확인하고 개발 배포는 healthy까지 최대 90초 대기하게 수정했다. HTTP 서버가 건강해도 소비자가 준비되지 않으면 실패/rollback한다. 모의 지연 준비 성공과 timeout/구버전 소비자 정지 회귀 검사를 추가해 통과했다. 수정 경로를 재검토했다.
