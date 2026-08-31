# Context Notes

## 2026-08-29 LAN-386 PR 리뷰 반영

- PR #22 CodeRabbit 리뷰는 유효하다. 기존 계약 테스트가 첫 `access_control_allow_origins`부터 전역 검색하고 정책 연결도 전체 파일에서 검색해 다른 리소스가 오류를 가릴 수 있었다.
- 임시 두 정책 fixture에서 decoy 정책은 wildcard origin, 실제 `content_cors`는 잘못된 origin을 사용해도 기존 테스트가 exit 0을 반환하는 RED를 재현했다.
- 정확한 `content_cors` 정책, 그 안의 `access_control_allow_origins`, `content` 배포의 `default_cache_behavior` 블록을 brace depth로 추출해 계약 범위를 고정했다.
- 같은 fixture에 수정된 테스트를 적용하면 `CloudFront content_cors 정책은 모든 origin을 허용해야 한다.`로 exit 1을 반환한다.
- 다른 cache behavior에만 `content_cors`를 연결하고 default cache behavior에는 decoy를 연결한 fixture도 실패하도록 회귀 검증을 추가했다.
- `bash -n scripts/test-admin-content-upload-contract.sh`, `bash scripts/test-admin-content-upload-contract.sh`, `terraform fmt -recursive -check`, `git diff --check`가 exit 0을 반환했고, `terraform -chdir=environments/shared validate`도 샌드박스 밖 provider 실행으로 `Success! The configuration is valid.`를 반환했다.
- 수정 커밋 `7dde768`을 `feat/LAN-386`에 push하고 검증 근거를 답변했으며 CodeRabbit 인라인 스레드를 해결 처리했다.

## 2026-08-29 LAN-184 PR 리뷰 반영

- PR #21 CodeRabbit 리뷰 3건은 미해결 상태다. Terraform plan 명령에는 이미 `AWS_PROFILE=landit`이 있으므로 해당 지적은 현재 코드와 불일치하고, `terraform output` 두 호출의 profile 누락만 유효하다.
- develop은 EC2 Compose인데 공통 live 검증 절차가 ECS Task Definition을 조회하는 문제와 Worker 격리 검사가 독립된 `! grep -q` 때문에 `set -e`를 우회하는 문제는 유효하다.
- 임시 fixture의 Worker task에 `SQS_PUSH_NOTIFICATIONS_QUEUE_URL`을 추가해도 기존 Push 계약 스크립트가 exit 0을 반환해 격리 위반을 놓치는 RED를 재현했다.
- Worker 격리 검사를 명시적 `if`와 `exit 1`로 바꾼 뒤 같은 fixture가 `worker task must not contain Push notification configuration`으로 exit 1을 반환했다.
- `bash -n scripts/test-push-notification-infra-contract.sh`, `bash scripts/test-push-notification-infra-contract.sh`, `bash scripts/test-dev-ec2-runtime.sh`, `terraform fmt -recursive -check`, `git diff --check`가 모두 exit 0을 반환했다. dev EC2 runtime 테스트가 출력한 health check 실패 문구는 의도된 rollback 실패 fixture다.
- CodeRabbit의 test API 공개 위험 요약은 merge blocker로 판단하지 않는다. BE Security 설정이 해당 endpoint를 인증 필수로 고정하고 Controller가 인증 사용자 본인만 대상으로 하며 IaC는 develop에서만 test API를 활성화한다.
- 수정 커밋 `0596932`를 `feat/LAN-184`에 push했다. CodeRabbit 인라인 3건은 모두 해결 상태이며 profile 지적에는 실제 누락 범위와 수정 근거를 답변했다.

## 2026-08-28 LAN-184 develop EC2 Push 연결

- BE `feat/LAN-184`의 최신 SHA는 `d615e8e3`다. `SCHEDULED_NOTIFICATION_BATCH`와 `PUSH_RECEIPT_CHECK`만 소비하고, 예약 배치는 500명 페이지마다 visibility를 300초로 연장하며 Receipt 확인은 같은 Queue에 900초 지연 발행한다.
- production ECS API에는 Push Queue URL, consumer flag와 최소 Queue IAM이 이미 연결돼 있다.
- develop은 ECS가 비활성화되고 EC2가 실제 배포 대상이지만 EC2 API runtime env에 Push Queue URL, consumer flag와 dev test API flag가 없고 EC2 role도 Push Queue ARN을 허용하지 않는다.
- Push Queue·DLQ·Scheduler 구조, 300초 visibility, 900초 Receipt 지연 기본값과 production ECS 설정은 변경하지 않는다.
- Expo access token은 BE에서 선택 값이므로 이번 범위에 SSM parameter를 추가하지 않는다.
- 실제 AWS plan·apply와 Scheduler 활성화는 별도 승인 전까지 수행하지 않는다.
- RED 검증에서 Push 계약 테스트는 `push_notifications_queue_arn` output 누락으로, EC2 runtime 테스트는 `SQS_PUSH_NOTIFICATIONS_QUEUE_URL` 누락으로 각각 exit 1을 반환했다.
- module output에 Push Queue ARN을 추가하고 develop EC2 role에 main Queue 전용 최소 권한을 연결했다. DLQ와 AI worker 권한은 추가하지 않았다.
- develop EC2 `api.env`에는 Terraform Queue URL, consumer 활성화와 dev test API 활성화를 일반 환경 변수로 기록한다. receipt delay, Expo URL과 timeout은 BE 기본값을 유지한다.
- GREEN 검증에서 Push 계약과 EC2 runtime 렌더링이 통과했다. 전체 EC2 검증은 기존 rollback 시나리오가 한 차례 간헐 실패했지만 추적 실행과 동일 명령 연속 3회에서 모두 통과했고 관련 rollback 코드는 변경하지 않았다.
- dev saved plan은 `7 added, 3 changed, 0 destroyed`다. Push Queue·DLQ, 비활성 Scheduler·역할, Alarm 2개를 생성하고 EC2 role policy, runtime env를 담는 SSM deploy document와 이를 참조하는 GitHub deploy policy를 갱신한다.
- production saved plan은 `8 added, 2 changed, 1 destroyed`다. 같은 Push 리소스 7개를 생성하고 API Task Definition을 Push 환경 변수 때문에 교체하며 ECS Service와 API Task Role을 갱신한다.
- 두 saved plan의 Scheduler payload 계약 검사가 통과했고 state는 `DISABLED`다. saved plan은 `/tmp/lan184-dev-ec2-push.tfplan`, `/tmp/lan184-prod-push.tfplan`에만 저장했으며 apply하지 않는다.

## 2026-08-28 LAN-184 Push 알림 인프라 복구와 main 동기화

- `feat/LAN-184` 브랜치는 삭제되지 않았고 제거 커밋 `38bb59c`를 가리키고 있었다. 삭제 이력을 지우는 reset 대신 해당 커밋을 되돌려 복구 이력을 남겼다.
- 복구 범위는 제거 커밋이 삭제한 Push Queue·DLQ, Scheduler, IAM, API 환경 변수, Alarm, 문서와 정적 계약 테스트다.
- 최신 `origin/main`은 기존 브랜치보다 50개 커밋 앞서고 복구 커밋 하나만 미포함한 상태였다. `origin/main` 위로 해당 커밋 하나를 rebase한다.
- Terraform 파일은 자동 병합됐고 충돌은 누적 기록 문서인 `checklist.md`, `context-notes.md`에서만 발생했다. 최신 main 기록을 유지하고 이 복구·동기화 기록만 앞에 추가한다.
- BE 작업 뒤 전달될 최종 인프라 계약은 이번 동기화에서 임의로 정하지 않는다. 실제 AWS plan·apply와 Scheduler 활성화도 수행하지 않는다.
- rebase 뒤 브랜치는 최신 `origin/main`보다 복구 커밋 하나만 앞서며 뒤처진 커밋은 없다.
- `terraform fmt -recursive -check`, Push 알림 정적 계약, Scheduler plan 계약 스크립트 문법 검사, dev·prod `terraform validate`, main 대비 `git diff --check`가 모두 통과했다.

## 2026-08-27 LAN-347 장기기억 플래그 배포

- 현재 브랜치는 `feat/LAN-347-6`, HEAD는 `73f6e74`이며 작업 시작 시 worktree는 깨끗하다.
- IaC 변경은 개발 EC2 runtime env에 `LANDIT_MEMORY_WRITE_ENABLED`, `LANDIT_MEMORY_USE_ENABLED`를 필수 SSM 값으로 추가하고, 운영 ECS API task definition의 SSM secrets에도 두 값을 연결한다.
- 두 parameter는 Terraform이 생성하지 않는다. `/landit/develop`, `/landit/prod`에 `String=false`로 선행 준비하되 값이나 secret은 로그와 문서에 남기지 않는다.
- feature 브랜치에서는 develop·production `plan-only`만 실행한다. `plan-and-apply`는 workflow가 `refs/heads/main`만 허용하므로 PR 병합과 plan 검토 뒤 별도 사용자 승인을 받아 진행한다.
- 최초 적용과 재배포에서는 두 플래그를 모두 `false`로 유지한다. 후속 활성화는 `WRITE=true, USE=false` 관찰 후 `USE=true` 순서이며 SSM 값 변경 뒤 BE 재배포가 필요하다.
- 과거 IaC fmt/validate 통과 기록은 현재 검증을 대신하지 않는다. 이번 실행의 plan, apply, 재배포와 런타임 증거를 단계별로 새로 기록한다.
- `terraform fmt -recursive -check`, `git diff --check`, `bash scripts/test-dev-ec2-contract.sh`, `bash scripts/test-dev-ec2-runtime.sh`가 통과했다. dev·prod `terraform validate`는 샌드박스 밖의 provider 실행 경로에서 모두 `Success! The configuration is valid.`로 통과했다.
- 최초 값 원문을 출력하지 않는 SSM 조회에서 네 parameter가 모두 `InvalidParameters`로 확인됐다. 사용자 승인 후 develop·prod에 두 parameter를 `String=false`로 신규 생성했고, 네 항목 모두 version 1, 문자열 `false`이며 누락이 없음을 재검증했다.
- 현재 state를 refresh한 develop saved plan은 `0 added, 2 changed, 0 destroyed`다. `aws_ssm_document.ec2_deploy`와 이를 참조하는 GitHub Actions IAM inline policy만 갱신하며, 아직 apply되지 않은 LAN-372 runtime-env 동기화와 LAN-347 두 플래그 추가가 같은 SSM 문서 변경에 포함된다.
- production saved plan은 `1 added, 1 changed, 1 destroyed`다. API task definition을 교체하고 ECS API service가 새 revision을 가리키는 변경만 있으며, 새 task definition의 secrets에 `/landit/prod/LANDIT_MEMORY_WRITE_ENABLED`, `/landit/prod/LANDIT_MEMORY_USE_ENABLED`가 추가된다.
- 두 saved plan은 `/tmp/lan347-dev.tfplan`, `/tmp/lan347-prod.tfplan`에만 저장했다. SSM parameter는 준비됐지만 사용자 apply 승인 전에는 적용하지 않는다.
- `feat/LAN-347-6`은 사용자 승인 후 `Aragornnnnnn/landit-iac` 원격에 push했다. Terraform apply와 애플리케이션 재배포는 아직 실행하지 않았다.
- PR #17 생성 뒤 최신 `origin/main`의 LAN-351 병합 때문에 충돌 상태임을 확인했다. 세 LAN-347 커밋을 최신 main 위로 rebase하고 LAN-351·LAN-347 문서 섹션을 모두 보존했으며, `range-diff`, 정적 계약, dev·prod validate와 saved plan을 fresh 재실행했다. PR은 현재 `MERGEABLE`, `CLEAN`이다.
- rebase 후 develop plan은 `0 added, 2 changed, 0 destroyed`, production plan은 `1 added, 1 changed, 1 destroyed`로 동일하다. pre-rebase plan은 적용하지 않고 `/tmp/lan347-dev-rebased.tfplan`, `/tmp/lan347-prod-rebased.tfplan`을 새로 생성했다.
- GitHub Actions develop run `33051017951`과 production run `33051019301`은 모두 `Check AWS role variable`에서 실패해 Terraform 단계는 실행되지 않았다. repository와 두 plan environment에 `AWS_ROLE_ARN`이 없고, AWS에도 landit-iac Terraform workflow용 OIDC role이 없다.
- 기존 `landit-github-actions-develop-deploy`, `landit-github-actions-prod-deploy` 역할은 landit-be·landit-ai subject 전용이므로 Terraform workflow에 재사용하지 않는다. 별도 OIDC role·최소 권한과 GitHub environment variable 구성은 추가 승인과 아키텍처 결정이 필요하다.
- 사용자는 `landit-iac` 전용 Terraform OIDC 역할과 GitHub environment 구성, develop EC2와 production ECS API의 shared `content/inbox/*` `s3:GetObject` 추가를 승인했다.
- 저장소는 public으로 유지한다. saved Terraform plan에 민감 값이 평문으로 포함될 수 있으므로 GitHub artifact 전달을 제거하고 전용 private S3 bucket에서 실행별 key와 SHA-256으로 전달한다.
- target과 phase별 6개 IAM role을 사용하고 각 role은 정확한 GitHub environment subject 하나만 신뢰한다. plan은 `main`, `feat/*`, apply는 `main`만 허용한다.
- apply required reviewer는 현재 설정하지 않는다. `main` branch protection도 현재 없으므로 write 권한자의 즉시 apply 위험이 남으며, production 확인 문자열은 유지한다.
- 새 `bootstrap/terraform-actions`는 기존 OIDC provider를 data source로 참조하고 역할·policy·plan bucket만 소유한다. 과거 `bootstrap/github-actions` state와 BE·AI 배포 role은 건드리지 않는다.
- 설계 문서는 `docs/superpowers/specs/2026-08-27-lan-347-terraform-actions-oidc-design.md`에 기록했다. 실제 bootstrap apply와 GitHub environment 변경은 saved plan 검토 뒤 별도 승인 전까지 실행하지 않는다.
- 구현 계획은 `docs/superpowers/plans/2026-08-27-lan-347-terraform-actions-oidc.md`에 기록했다. inbox GetObject, bootstrap 역할·plan bucket, private S3 workflow, 전체 plan 검증과 별도 승인 후 실제 생성의 다섯 작업으로 나눴다.
- develop EC2와 production ECS API의 기존 shared `content/inbox/*` statement에 `s3:GetObject`를 추가했다. 새 경로나 다른 runtime 역할에는 권한을 넓히지 않았다.
- `bootstrap/terraform-actions`는 plan·apply와 shared·develop·production 조합의 OIDC role 6개, inline policy 6개와 private saved-plan bucket 보안 리소스를 정의한다. trust subject는 각 GitHub environment와 정확히 일치하고 audience는 `sts.amazonaws.com`으로 고정한다.
- workflow는 `plan-only`에서 speculative plan만 실행하고, `plan-and-apply`에서만 `/tmp` saved plan을 SHA-256과 함께 `plans/{target}/{run_id}/{run_attempt}` private S3 key로 전달한다. GitHub artifact 업로드는 제거했고 action은 검증한 commit SHA로 고정했다.
- fresh bootstrap saved plan `/tmp/lan347-terraform-actions.tfplan`은 `17 add, 0 change, 0 destroy`다. role 6개, inline policy 6개, S3 bucket·lifecycle·HTTPS-only policy·public access block·AES256 encryption 5개만 생성한다.
- fresh develop saved plan `/tmp/lan347-dev-getobject.tfplan`은 `0 add, 3 change, 0 destroy`다. EC2 app policy의 inbox GetObject, LAN-372·LAN-347 SSM document와 이를 참조하는 deploy policy만 갱신한다.
- fresh production saved plan `/tmp/lan347-prod-getobject.tfplan`은 `1 add, 2 change, 1 destroy`다. API task role의 inbox GetObject, LAN-347 memory secrets를 포함한 task definition 교체와 ECS API service update만 포함한다.
- 독립 보안 리뷰에서 develop plan의 EC2 refresh 조회 권한 누락, apply mutation `Resource="*"`의 target 격리 실패와 `iam:PutRolePolicy`를 통한 runtime role 권한 상승을 blocker로 확인했다. EC2 attribute·volume·instance profile association 조회를 보완하고, Actions apply에서는 `iam:PutRolePolicy`를 완전히 제거했다. apply는 exact SSM document·production ECS API service와 prod request tag task definition 등록만 허용한다.
- `ecs:DeregisterTaskDefinition`은 resource-level·resource-tag 제한을 안전하게 적용할 수 없어 권한에서 제거했다. production API task definition은 `skip_destroy=true`로 이전 revision을 유지하며, 현재 revision 8에 `Project=landit`, `Environment=prod` 태그가 존재함을 읽기 전용으로 확인했다.
- develop EC2·deploy role과 production API task role의 `GetObject` IAM 변경은 OIDC apply보다 먼저 로컬 관리자 profile의 별도 saved plan으로 적용한다. 이 변경을 반영한 fresh full plan에서 IAM diff가 사라진 뒤에만 workflow apply를 사용한다.
- 관리자 전용 develop saved plan `/tmp/lan347-dev-iam.tfplan`은 의존하는 SSM document까지 포함해 `0 add, 3 change, 0 destroy`다. EC2 app policy, develop deploy role policy와 SSM deploy document만 갱신한다. production `/tmp/lan347-prod-iam.tfplan`은 API task role policy 한 건만 갱신하는 `0 add, 1 change, 0 destroy`다. 두 plan은 PR 병합과 사용자 별도 승인 전에는 적용하지 않는다.
- AWS Access Analyzer는 최종 6개 identity policy와 plan bucket resource policy 모두 findings 0건을 반환했고, 여섯 정책 모두 `iam:PutRolePolicy`가 없다. 최대 inline policy JSON은 apply-production의 3,658자다. IAM simulator는 exact develop SSM·prod ECS 대상 허용, 교차 target 암시적 거부, prod request tag 등록 허용과 develop tag 등록 거부, exact ECS PassRole 허용과 다른 role 거부를 확인했다.
- OIDC role을 먼저 만들면 보호 설정 전 environment subject가 사용될 수 있으므로 실제 rollout은 GitHub environment 6개·branch policy·결정 가능한 role ARN 변수를 먼저 생성·재조회한 뒤 bootstrap saved plan을 적용한다.
- `bash scripts/test-admin-content-upload-contract.sh`, `bash scripts/test-dev-ec2-contract.sh`, `bash scripts/test-dev-ec2-runtime.sh`, `bash scripts/test-terraform-actions-oidc-contract.sh`, `bash scripts/test-terraform-workflow-contract.sh`, `terraform fmt -recursive -check`, `git diff --check`가 통과했다. bootstrap·shared·dev·prod `terraform validate`도 모두 성공했다.
- 사용자 승인 후 GitHub environment 6개를 먼저 생성했다. required reviewer와 wait timer는 없고, plan은 `main`·`feat/*`, apply는 `main`만 허용하며 각 environment의 `AWS_ROLE_ARN`은 전용 role ARN과 일치한다.
- bootstrap saved plan SHA-256 `45cabc6716ed52b87be07961f97042144ad3c0bc14da237b1e17b16667b83dac`을 적용해 role·inline policy 6개와 private plan bucket 보안 리소스 등 `17 added, 0 changed, 0 destroyed`를 생성했다. post-apply plan은 `No changes`였다.
- AWS live 검증에서 6개 role의 OIDC audience는 `sts.amazonaws.com`, subject는 각 environment 하나로 고정됐다. plan bucket은 public access block 4종이 모두 true이고 AES256 암호화와 1일 lifecycle이 활성화됐다.
- 최초 OIDC plan-only는 provider refresh에 필요한 읽기 권한 누락으로 실패했다. 실패 로그에 확인된 EC2·SSM·Lambda·ELB attribute 조회 action을 최소 추가하고 계약 테스트에 고정했다.
- 관리 대상 S3 bucket의 `HeadBucket` 403이 삭제로 오인되는 문제는 target별 exact bucket ARN에 `s3:ListBucket`을 허용해 제거했다. AWS provider v6.62.0의 `resourceBucketRead` 구현을 확인해 website·accelerate·request payment·replication·object lock 조회 action도 같은 exact bucket ARN statement에 제한했다.
- 최종 develop plan-only run `33058980660`은 `0 add, 3 change, 0 destroy`, production run `33058983038`은 `1 add, 2 change, 1 destroy`로 성공했다. 두 결과는 관리자 profile 기준 plan과 일치하고 외부 삭제 drift 표시는 없다.
- 두 plan-only run 모두 apply job, saved plan 생성·업로드가 skip됐고 GitHub artifact 수와 run별 private S3 plan prefix 객체 수는 모두 0이다.
- OIDC bootstrap 최종 상태는 post-apply `No changes`이며 branch와 원격 HEAD는 문서 갱신 전 `12d2c65`로 일치한다. PR 병합, 관리자 IAM pre-apply, main workflow apply와 런타임 검증은 아직 실행하지 않았다.

## 2026-08-25 LAN-351 시나리오 고정 질문 TTS 게시

- 이번 저장소 범위는 production DB를 기준으로 고정 질문 MP3를 생성·검증하고 기존 shared private content S3 bucket에 게시하는 작업이다. BE·AI 코드, runtime IAM, DB 컬럼과 런타임 오디오 결합은 후속 이슈로 분리한다.
- production 읽기 전용 집계는 활성 시나리오 40개, 영어 고정 질문 120개, 빈 질문 0개, 시나리오별 3개 질문과 `display_order=1..3` 완전성을 확인했다. 원문·순서·캐릭터 기준 초기 MD5는 `9c79b5aec3333eb7022dca5b9da10f39`다.
- 생성 분포는 Chloe 9개, Marco 24개, Teddy 87개다. LAN-351은 production의 Chloe `microsoft/mai-voice-2` 매핑을 의도적으로 사용하지 않고 사용자 지정 `deepgram/aura-2`의 `aura-2-luna-en`을 사용한다. Marco는 `aura-2-hyperion-en`, Teddy는 `aura-2-draco-en`을 사용한다.
- 출력은 용량과 전송 효율을 위해 OpenRouter `/api/v1/audio/speech`의 MP3 raw byte stream을 변환 없이 저장한다. key fingerprint에는 질문 원문, model, voice와 response format을 포함한다.
- 실제 OpenRouter 과금 호출과 S3 업로드는 아직 실행하지 않았다. 캐릭터별 샘플 승인 뒤 전체 생성하며, 전체 로컬 검증과 S3 변경 목록 승인 뒤에만 업로드한다.
- 설계 문서는 `docs/superpowers/specs/2026-08-25-lan-351-scenario-question-audio-design.md`에 기록했다. 동시 작업 수 4개, 최대 시도 4회, 연결 timeout 10초와 전체 timeout 120초를 고정했고 placeholder 검사와 `git diff --check`를 통과했다.
- 구현 계획은 `docs/superpowers/plans/2026-08-25-lan-351-scenario-question-audio.md`에 기록했다. source 계약, OpenRouter 생성·resume, manifest·S3 gate, production export, 샘플 승인, 전체 생성과 별도 업로드 승인의 일곱 작업으로 나눴다.
- Task 1에서 Python 표준 라이브러리만 사용해 production `EN`/`KR` source의 40개 시나리오·120개 질문, 캐릭터별 9·24·87개, 시나리오별 순서, 중복·빈 원문을 검증한다. 질문 원문·model·voice·MP3 계약의 SHA-256 fingerprint와 캐릭터별 UTF-8 중앙 길이 sample 선택도 추가했고 12개 단위 테스트가 통과했다.
- 새 Python 테스트 실행이 생성하는 `__pycache__/`만 `.gitignore`에 추가했다. MP3나 작업 source는 `/tmp/landit-lan-351-audio`에만 두므로 별도 저장소 ignore 경로를 만들지 않는다.
- Task 2에서 OpenRouter speech 요청의 네 필드 계약, 10초 연결·120초 응답 timeout, 429·5xx·연결 오류 최대 4회 재시도와 영구 오류 즉시 실패를 구현했다. 응답은 `audio/mpeg`, 비어 있지 않은 body와 generation ID를 모두 요구하며 key는 오류에 포함하지 않는다.
- MP3는 `.part` 파일을 `afinfo` 또는 `ffprobe`로 디코딩해 양수 duration을 확인한 뒤 원자적으로 교체한다. 동시성은 4개이며 resume 시 fingerprint, 경로, byte 크기, SHA-256과 decoder probe가 모두 일치하는 파일만 재사용한다. 변조 파일 선택 재생성과 sample 3개 제한을 포함한 전체 단위 테스트 28개가 통과했고 실제 과금 호출은 아직 실행하지 않았다.
- Task 3에서 source SHA-256, 질문·voice 계약, generation ID, MP3 크기·SHA-256과 immutable S3 key를 포함하는 canonical manifest를 구현했다. 게시 계획은 120개 MP3와 content-addressed manifest의 원격 metadata를 먼저 조회하고 일치 객체만 재사용하며, 충돌 객체가 하나라도 있으면 쓰기 전에 실패한다.
- S3 게시 CLI는 기본 dry-run이고 명시적인 `--execute`에서만 `If-None-Match: *`로 신규 객체를 쓴다. 각 MP3를 업로드 직후 검증하고 모든 MP3가 끝난 뒤 manifest를 마지막 completion marker로 올린다. AWS와 OpenRouter를 호출하지 않는 전체 단위 테스트 38개가 통과했으며 실제 S3 변경은 별도 사용자 승인 전까지 금지한다.
- Task 4에서 production SSM credential을 파일이나 출력에 남기지 않고 JDBC read-only transaction으로 source를 재조회했다. 결과는 40개 시나리오, 120개 질문, Chloe 9개, Marco 24개, Teddy 87개이며 source SHA-256은 `bf534681837848ebb45644d2c7add05b023d4fd18880f3139f769017c14c5fce`다.
- 동일 필드의 `scenarioId|scenarioQuestionId|displayOrder|characterId|questionText` 행을 newline으로 연결한 MD5는 초기 audit와 같은 `9c79b5aec3333eb7022dca5b9da10f39`였다. 질문 원문, ID, 순서와 캐릭터 drift가 없으므로 이 snapshot을 샘플 생성 입력으로 고정한다.
- Task 5 과금 직전 Codex 프로세스의 OpenRouter key는 credits API HTTP 200이었고 잔액은 `$578.450179051`이었다. `landit-ai/.env`의 별도 key는 `401 User not found`였으므로 사용하지 않았으며 key 원문은 출력하거나 기록하지 않았다.
- 캐릭터별 중앙 길이 샘플은 Teddy 질문 45번 40,464 bytes·6.744초, Chloe 질문 59번 37,584 bytes·6.264초, Marco 질문 95번 35,136 bytes·5.856초로 생성됐다. 세 파일은 decoder probe, byte size와 SHA-256 검증을 통과했고 사용자가 세 voice와 결과를 모두 승인해 전체 생성 gate를 열었다.
- Task 6 전체 생성은 승인된 샘플 3개를 resume하고 나머지 117개를 호출해 `completed=120, failed=0`으로 끝났다. 결과는 Chloe 9개, Marco 24개, Teddy 87개, 총 4,915,152 bytes, 총 819.192초이며 MP3 120개와 `.part` 잔여 0개를 확인했다.
- canonical manifest SHA-256은 `2e084d63e194f984f0160341889d3df7e610b9de99f8dc528ee3f95211874509`다. source와 manifest 동시 검증에서 MP3 120개의 decoder probe, byte size, audio SHA-256과 generation fingerprint가 모두 일치했고 단위 테스트 39개, Terraform format, 기존 콘텐츠 업로드 계약과 `git diff --check`가 통과했다.
- 전체 생성 후 OpenRouter credits API 잔액은 `$578.103948301`이었다. 전체 생성 직전 확인값 대비 관찰된 감소액은 `$0.346230750`이며 같은 key의 다른 동시 사용 가능성이 있어 LAN-351 단독 청구액으로 단정하지 않는다.
- Task 7 사전 S3 dry-run은 shared bucket의 MP3 120개와 manifest 1개 key를 `head-object`로만 조회했다. 대상 121개가 모두 신규이고 재사용 0개, metadata 충돌 0개였으며 `put-object`와 실제 업로드는 0건이었다. 사용자가 이 변경 목록을 검토하고 실제 게시를 별도로 승인했다.
- 승인 후 MP3 120개를 먼저 `If-None-Match: *`로 게시·검증하고 canonical manifest 1개를 마지막 completion marker로 게시했다. 실행 결과는 신규 업로드 121개, 검증 121개, 충돌 0개였고 후속 dry-run은 신규 0개, 재사용 121개, 충돌 0개였다.
- 원격 prefix를 임시 디렉터리에 다시 내려받아 MP3 120개의 실제 bytes를 전수 계산했다. manifest의 byte size·audio SHA-256 불일치는 0개였고 원격 manifest bytes도 로컬 SHA-256 `2e084d63e194f984f0160341889d3df7e610b9de99f8dc528ee3f95211874509` manifest와 정확히 일치했다. 기존 객체 overwrite와 delete는 수행하지 않았다.
- BE 전달 문서는 `docs/handoffs/lan-351-be-audio-urls.md`에 정리했다. BE는 `scenarioQuestionId`로 manifest 항목을 찾고 shared CloudFront base URL과 정확한 `s3Key`를 결합하며, 대표 MP3와 content-addressed manifest URL의 HTTP 200, content type, content length와 immutable cache header를 확인했다.

## 2026-08-18 LAN-284 개발 DNS 전환과 ECS·ALB 제거

- Caddy는 임시 도메인과 기존 개발 도메인을 함께 수신한다. 실행 중 설정 반영 뒤 Caddy 컨테이너만 재생성해 bind mount inode를 갱신했고 네 도메인의 HTTPS health를 확인했다.
- Vercel DNS의 `api-develop.landit.im`, `ai-develop.landit.im`을 EC2 EIP `3.35.41.213`의 A record로 전환했다. 외부 API·AI health와 Compose 내부 `http://ai:8000/health` 호출이 모두 성공했다.
- BE PR 109와 AI PR 59를 병합해 ECS 의존성을 제거한 EC2 전용 workflow를 적용했다. BE 배포는 Flyway 뒤 SHA `03923db3db259406706f4ae05d8a3e0afc009278`, AI 배포는 SHA `790cb4459bfe0651010586396a666997bf0659e1` 이미지를 EC2에 배포했고 두 컨테이너가 실행 중이다.
- BE·AI 컨테이너에 기존 OTLP 환경 변수 이름이 모두 주입돼 있다. Grafana 애플리케이션 설정 변경은 필요 없고, EC2 host 지표는 `Landit/EC2`, CPU credit은 `AWS/EC2` CloudWatch namespace에서 확인한다.
- 제거 saved plan은 `0 add, 0 change, 21 destroy`다. 개발 ECS cluster·service·task definition, ALB·listener·target group, 전용 security group과 IAM만 제거하고 EC2·EIP, VPC, ECR, S3, SQS, SSM, CloudWatch Logs와 Grafana 전달 경로는 보존한다.
- 사용자는 정상 이전과 GitHub Actions 재배포 확인 뒤 24~48시간 관찰 없이 기존 개발 ECS·ALB를 바로 제거하도록 승인했다.
- IaC PR 13 병합 뒤 saved plan을 적용해 `0 added, 0 changed, 21 destroyed`로 제거를 완료했고 post-apply plan은 `No changes`다.
- AWS 확인에서 개발 ECS cluster와 ALB는 없고, EC2 `i-05436b2754740db41`은 `t3.small`, EIP `3.35.41.213`으로 실행 중이다. Firehose `develop-landit-grafana-logs`는 `ACTIVE`이고 API·worker CloudWatch Log Group도 보존됐다.
- 제거 후 API·AI 외부 health, BE→AI 내부 health와 실제 BE·AI 이미지 SHA를 다시 확인했다.

## 2026-08-15 LAN-284 최신 state 적용 전 plan 분리 감사

- 기준은 `origin/main` `145980a`와 Task 1 clean `feat/284` `2431187`이며, `origin/main`은 feature HEAD의 조상이다. 두 plan은 같은 develop state에서 `terraform apply` 없이 생성했고 saved plan·JSON은 `/tmp`에만 저장했다.
- `origin/main` 기준 plan은 `No changes`였다. 이전 기록의 LAN-184 Push 8개 destroy는 최신 state 기준 이 plan에 더 이상 포함되지 않는다.
- 리뷰 보완 뒤 LAN-284 plan은 `10 to add, 0 to change, 0 to destroy`다. 기존 EC2·EIP·IAM·security group create 9개에 입력을 `api|ai`와 40자리 SHA로 제한한 `aws_ssm_document.ec2_deploy` create 1개가 추가됐고, `data.aws_iam_policy_document.github_actions_ec2_deploy`의 plan-time read 1개가 있다.
- 두 plan 모두 `aws_lb`, listener, target group 주소 변경이 없고 ECS Service delete·replace도 없다. LAN-184 Push destroy도 없으며, 최신 main에 반영된 LAN-299 이후 변경도 기준 plan `No changes`로 인해 LAN-284 plan에 추가 변경으로 포함되지 않았다.
- 따라서 2026-08-08 당시의 LAN-184 8개 destroy 기록은 역사적 plan 결과로만 보존한다. 2026-08-15 현재 baseline은 이미 `No changes`이므로 LAN-184 drift apply와 post-apply `No changes`는 다음 승인 게이트가 아니라 해당 없음으로 닫는다.
- AWS 읽기 전용 확인에서 개발 EC2는 0대, ECS API·AI는 각각 desired/running `1/1`, pending `0`, PRIMARY rollout `COMPLETED`였고 ALB는 `active`다. SSM parameter 또는 secret 값은 조회·기록하지 않았다.
- 이 결과는 EC2 create-only 승인을 위한 사전 검토일 뿐이다. Terraform apply, DNS, GitHub `EC2_INSTANCE_ID` 등록, 실제 SSM 배포, 기존 ECS·ALB 제거는 계속 별도 사용자 승인 대상이다.
- 현재 후속 순서는 IaC PR 병합, 최신 create-only plan 재생성·승인, EC2 apply, SSM·Docker·Caddy·loopback health 검증, 임시 Vercel DNS `api-ec2-develop.landit.im`·`ai-ec2-develop.landit.im` 등록 승인, 외부 HTTPS·API·AI·BE→AI 검증, BE·AI `EC2_INSTANCE_ID` 등록, BE·AI workflow PR 병합과 ECS 검증 뒤 동일 SHA EC2 미러링, 24~48시간 관찰, 원래 개발 DNS 전환 별도 승인이다. EC2 runtime과 두 GitHub 변수를 준비하기 전에는 application workflow PR을 병합하지 않는다.

## 2026-08-08 LAN-284 개발 BE·AI 단일 EC2 통합

- 개발 ECS API·AI와 ALB는 EC2 병행 검증과 DNS 전환이 끝날 때까지 유지한다.
- 단일 `t3.small`에서 Docker Compose로 BE, AI, Caddy를 실행하고 기존 ECR, SSM, S3, SQS, CloudWatch Logs를 재사용한다.
- EC2의 BE만 `LANDIT_AI_BASE_URL=http://ai:8000`을 사용한다. 기존 SSM 값을 바꾸면 ECS BE까지 EC2 AI를 호출하므로 변경하지 않는다.
- BE·AI 개발 배포 workflow는 ECS 성공 뒤 같은 Git SHA를 SSM Run Command로 EC2에 미러링하도록 구현했고 shell 계약·BE Gradle check·AI unittest를 통과했다. EC2 apply와 GitHub Environment `EC2_INSTANCE_ID` 등록은 실행하지 않았다.
- 병행 검증 도메인은 `api-ec2-develop.landit.im`, `ai-ec2-develop.landit.im`을 사용하고 Vercel DNS 변경은 별도 승인 후 진행한다.
- EC2 instance role을 두 컨테이너가 공유해 BE·AI IAM 권한이 합쳐지는 점과 단일 장애 지점을 테스트 환경의 비용 절감 조건으로 수용한다.
- ECS·ALB 제거는 별도 단계로 진행하며 ECR, S3, SQS, SSM, CloudWatch Logs와 Grafana 전달 경로를 보존한다.
- `terraform init -reconfigure`, `bash scripts/test-dev-ec2-contract.sh`, `terraform fmt -recursive`, `terraform fmt -recursive -check`, `AWS_PROFILE=landit terraform -chdir=environments/dev validate`를 실행했고 모두 통과했다.
- 2026-08-08 dev saved plan은 `10 add, 2 change, 8 destroy`였다. LAN-284는 `aws_instance.app`, `aws_eip.app`, `aws_eip_association.app`, EC2 IAM role·policy·attachment·instance profile, security group의 9개 create다.
- 나머지 API ECS Service update, API Task Definition `delete,create`, Push Queue·DLQ·Scheduler·IAM·Alarm 8개 delete와 API IAM policy update는 미적용 LAN-184 Push 제거다. summary의 10번째 add는 LAN-184 API Task Definition replacement의 create 부분이다.
- saved plan JSON 감사에서 `aws_lb` 주소는 없었다. ECS API Service delete 또는 replacement도 없고, ECS API의 update와 Task Definition replacement만 LAN-184 경계에 있다. 따라서 기존 ECS·ALB는 LAN-284 apply 전에 유지된다.
- 2026-08-08 당시에는 LAN-184 drift를 먼저 적용해 기준 plan을 `No changes`로 만들지, LAN-284와 함께 적용할지를 별도 승인으로 판단했다. 이 판단은 2026-08-15 baseline `No changes` 확인 뒤 현재 후속 승인 게이트에는 적용하지 않으며, 실제 Terraform apply, Vercel DNS 변경, 기존 리소스 제거는 각각 사용자 승인 뒤에만 실행한다.
- Task 7 재검증에서 `bash scripts/test-dev-ec2-contract.sh`, `terraform fmt -recursive -check`, `AWS_PROFILE=landit terraform -chdir=environments/dev validate`가 통과했다. sandbox는 AWS provider의 Unix socket bind를 막아 validate를 실행 환경에서 재시도했고 `Success! The configuration is valid.`를 확인했다.
- BE는 `bash .github/scripts/test/deploy-ec2-service_test.sh`와 `./gradlew check --rerun-tasks --no-daemon`, AI는 같은 shell test와 기존 가상환경을 읽기 전용으로 사용한 `PYTHONDONTWRITEBYTECODE=1 /Users/sangmin8817/Soma/landit-ai/.venv/bin/python -m unittest discover -s tests`를 통과했다. AI unittest는 241개를 실행했다.
- 세 저장소 diff 검토 뒤 GitHub role의 AWS 관리형 shell 문서 호출 권한을 제거했다. 전용 `develop-landit-ec2-deploy` 문서는 `ENV_VAR` interpolation과 `allowedValues`·`allowedPattern`으로 `api|ai`, 40자리 SHA만 받아 고정된 `/opt/landit/bin/deploy-service`를 실행한다. Docker Compose 바이너리 SHA-256 검증, 최초 API·AI health gate, GNU·BSD 공통 테스트 렌더링도 추가했고 rollback은 EC2 컨테이너만 직전 SHA로 되돌린다.
- apply, GitHub 변수 등록, 실제 SSM 명령, 임시 Vercel DNS, EC2·ECS health, 24~48시간 관찰, 기존 ECS·ALB 제거는 모두 미실행이다.

## 2026-07-28 LAN-184 Push 알림 인프라 제거

- 제품 결정이 서버 Push에서 앱 로컬 알림으로 변경돼 LAN-184 Push 전용 AWS 인프라와 API 연결을 제거한다.
- 제거 범위는 dev·prod Push main Queue·DLQ, Review reminder Scheduler와 execution IAM, Push backlog·DLQ Alarm, API Task Role의 Push Queue 권한, API의 Queue URL·Consumer·dev 테스트 API 환경변수, 관련 variable·output·문서·테스트다.
- 기존 AI jobs Queue·DLQ, AI Worker, ECS Service, WAF·Athena·Glue와 관측성 리소스는 변경하지 않는다.
- 2026-07-28 live 확인에서 dev·prod main Queue와 DLQ의 visible·in-flight·delayed 메시지는 모두 0개이고 두 Scheduler는 `DISABLED`다.
- 제거 전 dev·prod plan은 모두 `No changes`였다.
- RED dev saved plan은 `missing required Push deletion: module.app_platform.aws_cloudwatch_metric_alarm.push_notifications_backlog`로 예상대로 실패했다.
- GREEN dev·prod validate와 `/tmp/lan184-push-removal-plan-contract.sh`는 모두 통과했다. 각 environment plan은 Push 관리 리소스 7개 삭제, API IAM policy in-place 갱신, API Task Definition의 `delete,create`, API ECS Service in-place 갱신만 포함한다.
- dev·prod plan summary는 모두 `1 to add, 2 to change, 8 to destroy`이며, add와 추가 destroy 1개는 API Task Definition revision 교체의 쌍이다.
- 실제 AWS 삭제 apply와 Wiki 동기화는 removal plan 검토와 사용자 별도 승인 뒤 진행한다.

## 2026-07-26 LAN-184 최종 Push Scheduler 계약 정렬

- `jsonencode`는 `<aws.scheduler.*>` token을 `\u003c...\u003e`로 직렬화하므로 Scheduler의 context attribute 치환을 보장하지 않는다. `target.input`을 raw JSON heredoc으로 바꾸고 Terraform plan JSON에서 Unicode escape 없는 정확한 token을 검사한다.
- 실제 dev·prod Scheduler는 `DISABLED`, `cron(0 20 * * ? *)`, `Asia/Seoul`, flexible window `OFF`이며 기존 Push Standard Queue를 target으로 사용한다.
- 실제 Push main Queue는 visibility timeout 300초, retention 4일, DLQ redrive `maxReceiveCount=3`이다.
- API Task Role은 Push main Queue 한 개에 `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility`, `GetQueueAttributes`, `SendMessage`만 허용한다.
- 실제 API Task Definition에는 consumer 활성화와 Push Queue URL이 두 환경 모두 주입돼 있고, 테스트 API flag는 dev에만 `true`다.
- Expo base URL·connect timeout·request timeout·receipt delay는 현재 BE 기본값을 사용하며, 관련 일반 환경 변수나 SSM parameter 이름은 현재 ECS Task Definition과 SSM path에서 확인되지 않았다. Expo access token은 값 없이 optional이므로 원문을 조회하지 않는다.
- Scheduler 입력은 BE `PushQueueMessage`의 `version:int`, `messageId:String`, `messageType:String`, `occurredAt:Instant`, `payload:object`와 맞춰야 한다. EventBridge Scheduler는 `<aws.scheduler.execution-id>`와 `<aws.scheduler.scheduled-time>` context attribute를 실제 지원한다.
- 최종 메시지 유형은 `SCHEDULED_NOTIFICATION_BATCH`다. 현재 BE는 `ON_SUCCESS` ack만 사용하며 visibility 연장은 아직 구현되지 않았다. Scheduler 활성화 전 BE가 `Visibility.changeTo(...)`로 배치 시작과 각 500명 페이지 전후에 300초로 visibility를 연장해야 한다.
- 전체 처리 시간의 실측 상한은 아직 없고 Publisher가 사용자별 SQS `sendMessage(...).join()`을 사용할 수 있으므로, 현재 300초는 유지한다. 한 페이지가 300초를 넘을 때 중복 전달은 가능하지만 `push_delivery`가 Expo 중복 발송을 막으며, dev 부하 측정 결과 후에만 timeout 변경을 검토한다.
- `LANDIT_NOTIFICATION_EXPO_BASE_URL`, connect timeout, request timeout, receipt delay는 BE 기본값을 사용한다. receipt delay는 정확히 900초만 허용하므로 IaC 주입을 추가하지 않는다. Expo access token만 필요한 경우 SSM SecureString으로 별도 주입한다.
- dev plan은 Scheduler input 1건을 `SCHEDULED_NOTIFICATION_BATCH`로 갱신하고 state는 `DISABLED`로 유지한다. prod plan은 같은 Scheduler 변경 외에 LAN-210 WAF logging·Athena 계열 9개 delete와 2개 update를 포함하므로 apply하지 않는다.
- prod plan의 LAN-210 WAF logging·Athena 삭제 위험은 여전히 적용 금지 사유다.

## 2026-07-26 LAN-184 dev 수동 리마인더 테스트 API

- BE의 수동 복습 리마인더 Controller는 기본 비활성화되고 dev에서만 생성돼야 한다.
- 공통 Terraform 모듈의 활성화 변수 기본값은 `false`로 두고 dev root만 `true`를 전달한다.
- dev API 컨테이너에는 `LANDIT_NOTIFICATION_TEST_API_ENABLED=true`를 주입하고 prod에는 환경 변수 자체를 주입하지 않는다.
- 정적 계약 테스트와 dev·prod `terraform validate`는 통과했다.
- dev plan은 `1 add, 2 change, 1 destroy`이며 API Task Definition 교체, API ECS Service 갱신, 기존 브랜치의 ALB idle timeout 70초 갱신으로 구성된다.
- dev planned API 컨테이너에는 consumer와 test API 환경 변수가 모두 `true`로 포함된다.
- prod planned API 컨테이너에는 consumer 환경 변수만 있고 test API 환경 변수는 없다.
- prod plan은 `0 add, 2 change, 9 destroy`이며 현재 `origin/main`에 없는 LAN-210 WAF logging·Athena 리소스가 state에 존재해 삭제가 계획됐다.
- prod saved plan은 요청 범위를 벗어나므로 적용하지 않았으며, main과 production state의 소스 정합성 복구 전에는 사용하면 안 된다.
- 사용자 승인 후 재생성한 dev saved plan의 동일한 세 리소스 변경만 적용했다.
- dev API ECS Service는 Task Definition revision 9에서 desired/running `1/1`, PRIMARY rollout `COMPLETED`로 안정화됐다.
- 실제 revision 9에는 `LANDIT_NOTIFICATION_CONSUMER_ENABLED=true`와 `LANDIT_NOTIFICATION_TEST_API_ENABLED=true`가 포함된다.
- dev ALB idle timeout은 70초이며 공개 API health endpoint는 `HTTP 200`을 반환했다.
- dev post-apply plan은 `No changes`이고 prod apply는 실행하지 않았다.

## 2026-07-25 IaC Wiki 장애 대응 중심 개편

- 사용자는 이번 작업을 이슈 번호 없이 진행하도록 승인했다.
- 현재 소스 작업트리는 `origin/main`의 `a2729e1`에서 시작했고 `feat/wiki-incident-runbook` 브랜치를 만들었다.
- 게시된 IaC Wiki `master`는 `0f52816`이며 코드 기준을 `16223d3`으로 기록하고 있어 현재 소스와 시차가 있다.
- IaC Wiki 작성 뒤 관측성·장애 알림·WAF·Push 인프라 관련 변경이 다수 반영됐지만 현재 Wiki에는 포함되지 않았다.
- BE Wiki는 정상 릴리즈 절차와 Troubleshooting을 분리하고 각 문제를 빠른 구분, 증상, 확인, 조치, 복구 확인 순서로 설명한다.
- AI Wiki는 배포, 관측성, 장애 진단을 분리하고 실제 배포 SHA와 운영 상태를 문서 기준 커밋과 구분한다.
- IaC Wiki는 기존 10개 파일을 최신 기준으로 다시 쓰고 `Incident-Response-Runbook.md`, `Push-Notifications.md`를 추가한다.
- Runbook은 production 장애 대응을 기준으로 하며 develop은 재현과 검증 용도로만 사용한다.
- 페이지 구조는 시작하기, 구조 이해하기, 변경하고 운영하기, 장애 대응하기, 저장소 바로가기 순서로 구성한다.
- 사용자가 확정 설계와 이후 실행을 모두 승인했다.
- 구현 계획은 `docs/superpowers/plans/2026-07-25-landit-iac-wiki-incident-response-redesign.md`에서 탐색 구조, 정상 운영, 관측성과 알림, 장애 대응의 네 Wiki 커밋으로 나눠 실행한다.
- 실행 시작 시 source `origin/main`은 `a2729e1`, Wiki `master`는 `0f52816`이다.
- AWS read-only 확인에서 prod BE·AI ECS Service는 desired/running `1/1`, PRIMARY deployment `COMPLETED`였고 두 public health endpoint는 `HTTP 200`이었다.
- prod Push Scheduler는 `DISABLED`, `cron(0 20 * * ? *)`, `Asia/Seoul`이며 main Queue와 DLQ의 설정은 코드·운영 문서와 일치하고 조회 시점 메시지 수는 모두 `0`이었다.
- prod Sentry relay Lambda는 `Active`, production WAF와 ALB는 존재하며 shared 콘텐츠 CloudFront distribution은 `Deployed`, `Enabled`였다.
- shared Terraform output 조회는 현재 worktree의 backend가 초기화되지 않아 중단됐고, CloudFront 적용 상태는 AWS API로 대체 확인했다. state나 resource는 변경하지 않았다.
- Grafana와 Sentry의 live rule은 임시 credential을 새로 만들지 않고 `docs/observability.md`, 계약 스크립트와 기존 검증 기록을 기준으로 작성한다. Wiki에는 조회하지 않은 현재 alert state를 단정하지 않는다.
- 이번 작업은 Wiki와 소스 문서만 변경하며 Terraform apply, AWS 리소스 변경, SSM 값 변경, Grafana 설정 변경은 수행하지 않는다.
- Wiki는 `49be8c4`, `c629a38`, `7d40a96`, `9658ab5`의 네 논리 커밋으로 탐색 구조, 정상 운영, 관측성과 알림, 장애 대응을 나눠 개편했다.
- 게시 전 Wiki `HEAD`는 `9658ab5`이며 기존 10개 파일을 다시 쓰고 `Incident-Response-Runbook.md`, `Push-Notifications.md`를 추가해 총 12개 Markdown 파일로 구성했다.
- 본문 11개 파일의 H1은 하나이고 GitHub Wiki 특수 파일 `_Sidebar.md`는 H1 없이 `##`부터 시작한다. 내부 페이지와 앵커, code fence, whitespace, 미완성 표시, secret·내부 resource 식별자 패턴 검사를 통과했다.
- `.github/workflows/terraform.yml`, `docs/observability.md`, `docs/push-notifications.md`와 Wiki를 대조해 shared·develop·production target, CRITICAL·WARNING·MONITORING, Push Scheduler `DISABLED`, visibility 300초와 `maxReceiveCount=3` 계약이 일치함을 확인했다.
- Wiki `master`는 `0f52816`에서 `9658ab55ef23df052b64cafd296780a01ae36b4f`로 게시됐고 원격 SHA와 로컬 Wiki `HEAD`가 일치한다.
- Home과 10개 본문 페이지의 공개 URL은 모두 `HTTP 200`을 반환했다. GitHub 게시본에서 Sidebar의 역할별 링크, Incident Response Runbook의 승인 경계와 상황 공유 형식, Troubleshooting의 Push 앵커가 렌더링되는 것을 확인했다.
- Infrastructure Architecture의 root·요청·관측 흐름과 Push Notifications의 Queue·DLQ Mermaid가 화면에 렌더링됐고 Mermaid syntax error는 확인되지 않았다.

## 2026-07-24 LAN-184 Push 알림 인프라 계획

- dev와 prod는 모두 `cron(0 20 * * ? *)`, `Asia/Seoul`, 최초 Scheduler `DISABLED`를 사용한다. Queue는 main 4일, DLQ 14일, visibility timeout 300초, redrive `maxReceiveCount=3`이며 Alarm은 외부 action 없는 상태 전용이다.
- 저장 plan JSON 집계는 dev `8 add, 2 change, 1 destroy`, prod `12 add, 2 change, 1 destroy`다. API Task Definition `delete,create` 새 revision과 API ECS Service in-place `update`는 허용 범위다.
- ECS Service delete 또는 replace, Worker IAM·Task Definition·Service 변경, 기존 jobs Queue·DLQ 변경은 없다.
- 사용자가 prod ALB access-log Athena·Glue 4개 create를 포함한 적용을 승인해 dev·prod saved plan을 적용했다. 두 환경 post-apply plan은 `No changes`이고 API ECS Service는 각각 revision 8과 5에서 안정화됐다.
- Queue·DLQ·IAM·환경 변수·Scheduler·Alarm과 prod Athena·Glue 실상태를 확인했으며, 두 Scheduler는 dev BE E2E 전까지 `DISABLED`로 유지한다.

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
- Grafana live rule group `landit-observability/prod-incidents-1m`은 BE·AI CRITICAL, WARNING, MONITORING의 6개 규칙으로 교체했다. CRITICAL은 2분 3건·50%를 1분 유지하고, WARNING은 10분 10건·20%를 3분 유지하며, MONITORING은 runtime metric 10분 부재를 5분 유지한다.
- 모든 규칙에서 직접 receiver 설정을 제거하고 `alert_scope=landit_incident` notification policy가 `discord-prod-incidents`로 전달하도록 했다. policy는 `service`, `severity`로 그룹화하고 30초 대기, 5분 그룹 간격, 1시간 재발송을 적용한다.
- Grafana Alerting provisioning API의 policy route matcher 필드는 `matchers`가 아니라 `object_matchers`여야 한다. 전자는 HTTP 400이었고 후자로 적용한 뒤 live policy를 다시 조회해 확인했다.
- prod Prometheus query API에서 BE·AI 5xx CRITICAL·WARNING PromQL은 모두 parse error 없이 성공했고 현재 결과 시계열은 없었다. `jvm_threads_live`와 `process_thread_count`는 각각 1개 시계열을 반환해 두 MONITORING 규칙이 정상 상태임을 확인했다.
- 임시 policy-route 검증 rule은 Firing 상태가 Grafana Alertmanager에 등록된 것을 확인한 뒤 삭제했다. 이후 active alert와 rule group에서 임시 rule이 사라진 것을 확인해 Resolved 경로까지 검증했다.
- 동기화와 검증에만 사용한 Grafana Admin service account와 token은 검증 직후 폐기했다. token 값은 저장소와 문서에 남기지 않았다.
- Grafana 기본 Discord 메시지는 raw label, source·silence URL, Grafana version이 본문 대부분을 차지해 장애 판단이 늦다. `landit.discord.title`, `landit.discord.message` template group을 추가하고 `discord-prod-incidents` contact point의 title·message에 연결했다.
- Firing 제목은 심각도별 emoji와 `environment · service`를 표시한다. 본문은 상태, `summary`, `description`, Grafana 상세 링크만 표시하고 Firing·Resolved 모두 같은 형식을 사용한다.
- AI CRITICAL 조건을 `vector(1)`으로 고정한 1회성 검증 rule은 Alertmanager active 상태를 확인한 뒤 삭제했다. 삭제 후 active alert 목록은 비었고 rule 조회는 `404`였다. Discord에는 새 Firing·Resolved 형식의 검증 메시지가 전송됐다.

## 2026-07-25 LAN-210 prod WAF rate limit Block 전환

- prod ALB access log를 2026-07-22 02:58:52부터 2026-07-25 14:59:54 KST까지 분석했다. 운영 서버의 `Java-http-client/21.0.11`에서 `ai.landit.im`의 `/api/v1/conversation/`으로 향한 요청은 5분 최고 42건, 정상 모바일 `/api/v1/` 요청은 5분 최고 21건이었다.
- 외부 스캐너 두 출발지 IP는 각각 5분 최고 2,654건과 5,986건으로 2,000회 rate limit을 초과했다. 현재 관측 범위에서는 운영 서버나 정상 사용자 IP에 별도 allowlist를 두지 않고 rate rule만 Block으로 전환한다.
- 이번 구현은 `ip-rate-limit` action만 `count`에서 `block`으로 바꾼다. Common Rule Set과 Amazon IP Reputation List는 Count, limit 2,000, evaluation window 300초, 기존 Web ACL 이름·리소스 주소는 유지한다.
- `scripts/test-waf-rate-limit-contract.sh`는 기존 Count action에서 `ip-rate-limit` Block 계약이 실패하는 RED 결과를 확인한 뒤 추가했다. 변경 뒤에는 같은 계약 테스트, `terraform fmt -recursive`, `git diff --check`가 통과했다.
- sandbox 안에서는 AWS provider와 archive provider가 plugin stdout을 열지 못해 Terraform validate가 실패했다. provider binary의 arm64 아키텍처와 실행 권한을 확인한 뒤 sandbox 밖에서 같은 `AWS_PROFILE=landit terraform -chdir=environments/dev|prod validate`를 재실행해 두 환경 모두 성공했다.
- `AWS_PROFILE=landit terraform -chdir=environments/prod plan -out=/tmp/lan210-rate-block-prod.tfplan` 결과는 `0 added, 1 changed, 0 destroyed`다. 변경 대상은 기존 `prod-landit-alb-count` Web ACL 한 건이며 `ip-rate-limit`만 Count에서 Block으로 바뀐다. Common·IP Reputation Count, limit 2,000, 평가 구간 300초, ALB idle timeout 70초와 나머지 인프라는 유지된다.
- 사용자 승인 후 saved plan을 적용해 `0 added, 1 changed, 0 destroyed`로 완료했다. live WAF는 Common·IP Reputation Count, `ip-rate-limit` Block, limit 2,000, 평가 구간 300초이며 ALB idle timeout은 70초다. `https://api.landit.im/actuator/health`와 `https://ai.landit.im/health`가 정상 응답했고 post-apply prod plan은 `No changes`다.

## 2026-07-25 LAN-210 WAF logging, Athena parser, Actuator 최소 노출 설계

- 사용자는 WAF logging을 `aws-waf-logs-` 전용 S3에 직접 저장하는 권장안을 승인했다. prod에서만 private SSE-S3 bucket과 30일 lifecycle을 두고 `BLOCK`·`COUNT` action만 저장한다.
- WAF 로그에서는 `Authorization`, `Cookie`, `X-Api-Key` header와 query string을 redaction한다. client IP, URI path, method, User-Agent는 규칙별 보안 분석을 위해 유지한다.
- 2026-07-25 partition의 실제 Athena query는 전체 1,015행, 파싱된 `type` 0행, 파싱된 `client_ip` 0행이었다. 최신 실제 ALB log 10행은 34개 원본 필드이고 기존 regex 자체는 행 문자열에 매칭되지만 Glue table 34개 컬럼과 regex 35개 capture group이 달라 RegexSerDe 결과가 모두 `NULL`이다.
- 최신 transform 필드 `transformed_host`, `transformed_uri`, `request_transform_status`를 table과 regex에 추가하고 future trailing field를 non-capturing 처리하면 37개 컬럼과 37개 capture group이 일치하며 실제 임시 sample 10행이 모두 매칭됐다. sample 원본은 저장소와 문서에 남기지 않는다.
- prod BE의 Grafana metric은 `/actuator` scrape가 아니라 30초 주기의 Micrometer OTLP push를 사용한다. `/actuator/health`만 ALB health check에 필요하므로 prod에서는 health만 노출하고 discovery와 info endpoint를 비활성화한다.
- 실제 apply와 BE·AI 운영 배포는 구현·테스트와 prod saved plan 검토 뒤 별도 사용자 승인을 받아 진행한다.
- 사용자가 설계 문서를 검토하고 구현을 승인했다. 구현 계획은 docs/superpowers/plans/2026-07-25-lan-210-waf-logging-athena-actuator.md에 기록한다. IaC와 BE는 테스트 우선으로 구현하고 apply와 운영 배포 권한은 포함하지 않는다.
- WAF logging은 `aws-waf-logs-prod-landit-982529430654` bucket에 직접 저장한다. bucket은 public access block, SSE-S3, 30일 lifecycle을 적용하고 WAF delivery service의 ACL 확인과 account·region 조건부 쓰기만 허용한다. Count·Block match만 저장하며 `Authorization`, `Cookie`, `X-Api-Key`, query string은 redaction한다.
- Athena는 기존 ALB database와 workgroup을 재사용한다. `waf_logs` JSON table은 분 단위 partition projection을 사용하며 `prod-landit-waf-recent-matches`는 action과 terminating·managed rule match 목록을, `prod-landit-alb-top-client-rate`는 client IP별 5분 요청량을 조회한다.
- ALB Glue table에는 최신 transform 세 컬럼과 37 capture group regex를 반영했다. `scripts/test-athena-alb-contract.sh`, 새 `scripts/test-waf-logging-athena-contract.sh`, 기존 rate limit 계약 검사가 통과했다.
- prod BE는 Springdoc 비활성화에 더해 Actuator discovery를 끄고 web exposure를 `health`만으로 제한한다. 보안 allowlist에서도 `/actuator/info`를 제거했다. prod integration test는 `/actuator`, `/actuator/info`의 404와 `/actuator/health`의 200을 검증하며 `./gradlew check --no-daemon`이 통과했다.
- `AWS_PROFILE=landit terraform -chdir=environments/dev|prod validate`는 성공했다. 최종 prod saved plan은 `9 to add, 1 to change, 0 to destroy`이며 WAF bucket·보호 설정·logging configuration·WAF Glue table·Athena named query 2개를 만들고 기존 ALB Glue parser만 in-place 수정한다. apply와 BE·AI prod 배포는 아직 실행하지 않았다.
- 사용자 승인 뒤 saved plan을 적용해 WAF logging과 Athena 구성을 `9 added, 1 changed, 0 destroyed`로 생성했다. live WAF logging은 전용 S3 destination, `BLOCK`·`COUNT` KEEP, 기본 DROP, query string·authorization·cookie·x-api-key redaction을 모두 반환한다. WAF S3 lifecycle은 30일 Enabled이며 post-apply prod plan은 `No changes`다.
- 초기 ALB parser 검증은 1,127행 중 type·client IP·User-Agent 모두 0행으로 실패했다. 실제 log 한 줄은 Java regex에서 37개 group으로 정상 매칭됐고 Glue table도 37개 column이었다. 원인은 Terraform heredoc이 Glue `input.regex` 끝에 `\n`을 저장한 것이며 RegexSerDe의 전체 행 매칭을 실패시켰다.
- heredoc을 개행 없는 HCL string으로 바꾸고 Glue table만 `0 added, 1 changed, 0 destroyed`로 재적용했다. 같은 Athena 집계에서 전체 1,130행과 type·client IP·User-Agent 파싱 행이 모두 1,130행으로 일치했다. 이 회귀를 막기 위해 ALB contract는 `input.regex` heredoc을 금지한다.
- WAF bucket에는 service가 만든 `AWSLogs/982529430654/` prefix만 있고 아직 Count·Block delivery object는 없다. WAF log delivery는 일관성이 보장되지 않으므로 실제 매칭 log가 도착한 뒤 redaction과 WAF Athena query 결과를 별도로 확인한다. BE·AI prod 배포는 이번 apply 범위에 포함하지 않았다.

## 2026-07-26 LAN-210 IP Reputation 기본 차단 전환

- WAF S3에 2026-07-25 07:45~15:40 UTC 구간의 실제 Count·Block 로그 64개가 도착했다. 3,539건 중 IP Reputation Count는 3,527건, Common Rule Set Count는 500건, rate limit Block은 311건이었다. 같은 요청이 여러 managed rule에 매칭될 수 있어 Count 합계는 요청 수와 다르다.
- IP Reputation Count 3,527건은 23개 출발지에서 발생했고, 최다 한 출발지는 5분 동안 3,253건과 1,316개 경로를 기록했다. WordPress·PHP·PHPUnit·`.env` 등 Landit과 무관한 경로 스캔이 반복됐으며, 이 표본에서는 `api.landit.im`, `ai.landit.im`, 실제 BE API route에 대한 Count 매칭이 없었다.
- Common Rule Set은 XSS 284건, LFI 146건 등 공격성 라벨을 남겼다. 다만 XSS body·query와 body size 계열은 대화·학습 입력의 코드 조각 또는 긴 본문을 오탐할 수 있으므로 managed rule group 전체는 Count를 유지한다.
- 사용자 승인 뒤 `aws-managed-ip-reputation`의 outer `override_action`만 `count`에서 `none`으로 바꿨다. 이는 Rule Group을 비활성화하는 것이 아니라 AWS 관리형 IP Reputation List의 기본 action을 복원한다. Common은 Count, `ip-rate-limit`은 5분 2,000회 Block을 유지한다.
- `terraform fmt -recursive`, WAF와 logging contract, dev·prod validate가 통과했다. prod saved plan과 apply는 모두 `0 added, 1 changed, 0 destroyed`였고, 기존 Web ACL 한 건만 in-place 변경했다. live WAF는 Common Count, IP Reputation None, rate limit Block이며 API `/actuator/health`는 UP, AI `/health`는 ok, post-apply prod plan은 No changes다.
- WAF raw sample에서 Authorization·Cookie·query string은 REDACTED였다. `waf_logs` Athena table은 `projection.log_time.range`가 분 단위 format과 맞지 않아 조회가 실패하므로 별도 Terraform 수정이 필요하다.

## 2026-07-26 LAN-210 WAF Athena 시간 파티션 수정

- `waf_logs`의 `projection.log_time.format`은 `yyyy/MM/dd/HH/mm`인데 range 시작값이 `2026/07/25`여서 Athena가 index 10에서 파싱 실패했다. range 시작값을 `2026/07/25/00/00`으로 맞추고 contract에 format과 range를 함께 검증하도록 추가했다.
- `terraform fmt -recursive`, rate limit·WAF logging contract, dev·prod validate가 통과했다. prod saved plan과 apply는 모두 Glue `waf_logs` table 한 건의 in-place 변경으로 `0 added, 1 changed, 0 destroyed`였다.
- apply 뒤 2026-07-25 07:45~15:40 UTC를 조회한 Athena 집계는 전체 3,539행과 action, client IP, URI, terminating rule 파싱 행이 모두 3,539행으로 일치했다.
- 외부 취약점 스캐너의 malformed multipart·form request가 Sentry 500으로 보이는 조사 기준, WAF 완화·롤백, Athena 파티션 검증 절차를 IaC Wiki `Troubleshooting`에 게시했다. GitHub 공개 렌더링에서 새 섹션을 확인했다.

## 2026-08-01 LAN-210 Common Rule Set 선택적 Label Block 계획

- 2026-07-26 00:00부터 2026-08-01 00:12 KST까지 WAF 로그를 관찰했다. 61,853건 중 IP Reputation 33,299건과 rate rule 27,609건을 Block했고, Common Rule Set Count 로그는 945건이었다.
- 같은 구간의 ALB·target 5xx는 0건이고 API·AI health endpoint와 target health는 정상이다. 정상 API `/api/v1/...` 경로의 WAF 오탐은 확인되지 않았으며, `/api/` Count 잔여 요청도 환경 파일·백업 파일 탐색이었다.
- Common Rule Set 전체를 Block하지 않고, Count 라벨을 뒤쪽 Label Match 규칙에서 선택적으로 Block한다. 우선 대상은 `RestrictedExtensions_URIPath`, `BadBots_Header`, `GenericLFI_URIPath`다.
- `NoUserAgent_Header`, body·query 계열 규칙은 Count를 유지한다. 대화·학습 본문과 일반 클라이언트의 오탐 가능성을 별도 관찰하기 위해서다.
- 구현 규칙은 `aws-managed-common` priority 10, IP Reputation priority 20 뒤인 priority 25에 둔다. 기존 IP Reputation과 rate limit Block의 우선 동작은 유지한다.
- apply 전 prod plan에서 Web ACL 1건의 in-place 변경과 삭제 없음만 허용한다. apply 후 24~48시간 동안 `/api/v1/...` 차단, ALB·target 5xx, health 상태를 재확인한다.

- LAN-210 커밋에 priority 25 `common-label-block`과 세 개의 Label Match 조건을 추가했다. Common managed rule group은 Count, body·query와 `NoUserAgent_Header`는 계속 Count다.
- WAF 계약 테스트, logging·ALB contract, `terraform fmt -recursive`, dev·prod validate가 통과했다.
- 최신 `origin/main`에는 Push 알림 인프라 제거가 반영됐지만 prod state에는 기존 리소스가 남아 있다. 전체 prod plan은 `1 add, 3 change, 8 destroy`로 WAF 외 삭제를 포함해 보류했다.
- WAF-only targeted plan은 `0 add, 1 change, 0 destroy`로 Web ACL in-place 변경만 포함한다. targeted plan은 사용자 승인 전 apply하지 않는다.
- 사용자가 Push 알림 기능을 사용하지 않기로 한 결정을 확인해 관련 queue·DLQ·alarm·scheduler·IAM 제거와 API task 갱신을 포함한 전체 prod plan 적용을 승인했다.
- 승인한 saved plan은 `1 added, 3 changed, 8 destroyed`로 적용됐다. API ECS service는 task definition revision 6으로 롤링 배포됐고 desired 1, running 1, pending 0, rollout `COMPLETED` 상태다.
- 새 API target은 healthy이며 기존 target은 정상 deregistration 과정에서 draining 상태였다. API `/actuator/health`는 `UP`, AI `/health`는 `ok`를 반환했다.
- live WAF는 Common priority 10 Count, IP Reputation priority 20 기본 action, priority 25 `common-label-block`의 세 라벨 Block, priority 30의 5분 2,000회 rate Block을 반환한다.
- post-apply 전체 prod plan은 `No changes`다. Label Block 오탐과 ALB·target 5xx는 24~48시간 추가 관찰한다.

## 2026-08-11 LAN-299 관리자 콘텐츠 이미지 업로드 IaC 설계

- 이번 저장소 범위는 shared 콘텐츠 S3 CORS, develop·production API ECS Task Role 권한, API 컨테이너 환경 변수, 문서와 IaC 검증이다. 관리자 presigned URL API, 파일 형식·크기 검증, 공지·업데이트 이미지 블록 저장은 landit-be 후속 범위이며 이번 IaC 작업에서 완료 처리하지 않는다.
- develop과 production API가 같은 shared 콘텐츠 버킷에 업로드한다. AI worker에는 콘텐츠 버킷 권한이나 환경 변수를 추가하지 않는다.
- 새 객체 key는 `content/inbox/{uuid}.{extension}`을 사용한다. API는 `If-None-Match: *`와 immutable cache header를 presigned PUT 계약에 포함해 같은 key 덮어쓰기를 거부해야 한다.
- shared 콘텐츠 버킷의 CORS는 `PUT`만 허용한다. origin은 `https://landit.im`, `https://develop.landit.im`, 현재 CORS의 로컬 프론트 주소 `http://localhost:3000`, `http://127.0.0.1:3000`, `http://10.0.2.2:3000`, `http://172.16.103.142:3000`, `http://192.168.219.107:3000`으로 제한한다.
- dev·prod root는 `terraform_remote_state`로 shared state의 실제 `content_bucket_name`과 `cloudfront_url` output을 읽어 app-platform module에 전달한다. 값을 환경별로 중복 작성하거나 SSM parameter를 추가하지 않는다.
- API Task Role에는 shared bucket의 `content/inbox/*`에 대한 `s3:PutObject`만 허용한다. 기존 application bucket 권한과 worker 권한은 유지한다.
- API 컨테이너에는 `CONTENT_BUCKET_NAME`, `CONTENT_CLOUDFRONT_URL`을 일반 환경 변수로 주입한다. 기존 CloudFront OAC가 `content/*`를 읽으므로 distribution과 bucket read policy는 넓히지 않는다.
- 구현 검증은 계약 테스트, `terraform fmt -recursive`, shared·dev·prod validate, 세 root의 saved plan 순서로 진행한다. apply와 실제 S3 임시 객체 업로드는 plan 검토 뒤 사용자 승인을 별도로 받는다.
- 사용자가 설계를 승인했고, 구현 계획은 `docs/superpowers/plans/2026-08-11-lan-299-admin-content-upload-iac.md`에 필요한 Terraform 구현·검증·적용 후 live 확인의 세 작업으로만 정리한다.
- LAN-299 계약 테스트가 CORS 7개 origin·PUT/header 계약, shared remote state, API `content/inbox/*` PutObject, API 환경 변수, worker 미변경을 모두 통과했다.
- shared·develop·production Terraform validate는 모두 성공했다. shared saved plan은 `1 to add, 0 to change, 0 to destroy`로 CORS configuration만 추가한다. production saved plan은 `1 to add, 2 to change, 1 to destroy`로 API policy·Task Definition·Service만 반영한다.
- develop saved plan은 현재 state에 남은 Push 알림 리소스 때문에 `1 to add, 2 to change, 8 to destroy`가 되었다. targeted API plan도 이전 Push 권한·환경 변수 제거가 함께 포함된다. LAN-299와 무관한 stale state 삭제를 방지하기 위해 develop·production apply와 실제 업로드 검증은 보류한다.
- 사용자가 Push 정리를 포함한 전체 적용을 승인했다. 삭제 전 develop Push queue·DLQ의 visible·in-flight·delayed 메시지는 모두 0이었다.
- shared apply는 콘텐츠 버킷 CORS만 `1 added, 0 changed, 0 destroyed`로 반영했다. develop apply는 Push queue·DLQ·alarm·Scheduler·IAM 7개와 기존 API task definition을 정리하며 `1 added, 2 changed, 8 destroyed`, production apply는 API task definition 교체와 IAM·Service 갱신으로 `1 added, 2 changed, 1 destroyed`였다.
- develop API revision `10`과 production API revision `8`은 desired/running `1/1`, pending `0`, rollout `COMPLETED`, failed task `0`으로 안정화됐고 두 ALB에는 새 healthy target만 남았다. 두 외부 `/actuator/health` endpoint는 `UP`을 반환했다.
- AWS 실상태에서 CORS 7개 origin, 두 API task role의 `content/inbox/*` `s3:PutObject`, 두 task definition의 콘텐츠 bucket·CloudFront 환경 변수를 확인했다. 기존 콘텐츠 객체의 CloudFront HEAD 요청은 `HTTP 200`, `image/png`을 반환했다.
- post-apply shared·develop·production 전체 plan은 모두 `No changes`다. presigned URL을 이용한 신규 임시 객체 업로드는 BE 구현 후 검증 범위이므로 아직 실행하지 않았다.

## 2026-08-25 LAN-372 개발 Sentry 오류 대응

- BE 개발 Sentry의 S3 presign 오류 원인은 개발 EC2 컨테이너에 `CONTENT_BUCKET_NAME`, `CONTENT_CLOUDFRONT_URL`이 주입되지 않은 상태였다. shared remote state의 `content_bucket_name`, `cloudfront_url`을 dev EC2 user-data에 전달하도록 수정했다.
- 개발 EC2 role에는 shared bucket 전체가 아닌 `content/inbox/*`에 대한 `s3:PutObject`만 추가했다. API ECS task role의 기존 권한은 변경하지 않았다.
- 최초 develop apply는 EC2 role의 IAM 정책만 변경했다. production은 변경 사항이 없었다. 두 role의 IAM simulation에서 `content/inbox/*` PutObject는 허용되고 다른 prefix는 거부되는 것을 확인했다.
- 개발 EC2의 `user_data`는 lifecycle에서 변경을 무시하므로 기존 인스턴스의 `/opt/landit/bin/runtime-env`와 실행 컨테이너에는 콘텐츠 환경 변수가 반영되지 않았다.
- runtime env를 별도 템플릿으로 분리하고, EC2 user-data와 SSM 배포 문서가 같은 렌더링 결과를 사용하도록 수정했다. SSM은 매 배포 전 임시 파일을 생성해 `runtime-env`를 원자적으로 교체한 뒤 기존 `deploy-service`를 실행한다.
- IAC 변경을 적용해 SSM 문서를 갱신한 뒤 BE 핫픽스를 배포해야 실행 중인 개발 API 컨테이너에 새 환경 변수가 반영된다. 현재 API는 재기동하지 않았다.

## 2026-08-29 LAN-386 CloudFront 조회 CORS

- 립싱크가 CloudFront 음성 파일의 파형을 브라우저에서 읽을 수 있도록 조회 응답에 `Access-Control-Allow-Origin: *`가 필요하다.
- 기존 S3 CORS는 브라우저 직접 업로드용 `PUT` 설정이며 CloudFront `GET`/`HEAD` 응답 CORS와 별개다.
- develop과 production은 모두 shared Terraform state의 동일한 `cloudfront_url`을 사용한다. 따라서 환경별 distribution을 변경하지 않고 `environments/shared`의 단일 CloudFront distribution에 Response Headers Policy를 연결한다.
- Terraform plan 없이 apply하지 않으며, saved plan의 변경 범위를 확인한 뒤 사용자 승인을 별도로 받는다.
- 계약 테스트는 정책 리소스, allow origin `*`, origin override, default cache behavior 연결을 검증한다. `terraform fmt -recursive -check`, 계약 테스트, `git diff --check`, shared `terraform validate`가 통과했다.
- saved plan `/tmp/lan386-shared.tfplan`은 `1 added, 2 changed, 0 destroyed`다. Response Headers Policy를 만들고 CloudFront distribution에 연결하며, distribution ARN을 참조하는 기존 S3 bucket policy는 apply 시 동일 내용을 재계산해 in-place 갱신으로 표시된다.
- 사용자 승인 후 fresh saved plan `/tmp/lan386-shared-approved.tfplan`을 적용했다. 실제 결과는 Response Headers Policy 생성과 CloudFront distribution 갱신으로 `1 added, 1 changed, 0 destroyed`였고 기존 S3 bucket policy에는 실변경이 없었다.
- live distribution은 `Deployed`이며 default cache behavior가 새 Response Headers Policy를 참조한다. 정책은 origin `*`, methods `GET`/`HEAD`, credentials `false`, origin override `true`다.
- 실제 MP3에 `Origin: https://develop.landit.im`과 `Origin: https://landit.im`, `Range: bytes=0-15`를 각각 보낸 결과 모두 `HTTP 206`, `content-type: audio/mpeg`, `access-control-allow-origin: *`, 올바른 `content-range`를 반환했다.
- post-apply shared `terraform plan -detailed-exitcode`는 exit code `0`과 `No changes`를 반환했다.

## 2026-08-31 LAN-418 develop AI 메모리와 EBS 정리

- landit-ai PR #79는 ONNX int8 모델의 단일 추론 peak를 약 430MB로 측정하고, 배포 전에 develop AI `mem_limit`을 512MiB에서 1024MiB로 올릴 것을 요구한다.
- 2026-08-31 22:43 KST live 확인에서 develop EC2는 `t3.small` 2GiB, available memory 831MiB, swap 70MiB, 루트 EBS 20GiB 중 89% 사용 상태였다.
- Docker image 13.27GB 중 12.58GB가 reclaimable이다. 실행 중인 image와 volume은 보존하고, 배포·rollback과 같은 lock을 사용해 오래된 미사용 image만 자동 정리한다.
- 기존 EC2는 Terraform에서 `user_data` 변경을 무시하므로 새 인스턴스 초기화만 수정해서는 현재 서버에 반영되지 않는다. SSM 배포 문서가 정리 스크립트를 동기화하는 경로를 사용한다.
- 이번 범위는 develop EC2 로컬 Docker image 자동 정리와 AI `mem_limit: 1024m`이다. EBS 용량 변경, ECR lifecycle, EC2 instance type 변경과 실제 apply는 포함하지 않는다.
- 정리 스크립트는 배포와 같은 `/var/lock/landit-deploy.lock`을 잡고 7일 이상 사용하지 않은 image와 14일 이상 system journal만 정리한다. 실행 중 image와 Docker volume은 삭제하지 않는다.
- 주간 persistent systemd timer는 새 EC2의 user-data와 기존 EC2의 SSM 배포 문서 양쪽에서 설치한다. SSM은 runtime env와 `mem_limit: 1024m` compose도 배포 전에 원자적으로 동기화하고, 배포 성공 뒤 정리를 한 번 실행한다.
- 자동 정리와 EC2 계약 테스트는 구현 전 각각 모델 파일 부재와 `1024m` 계약 부재로 실패했고 구현 후 통과했다. `terraform fmt -recursive -check`, `git diff --check`, EC2 runtime rollback 테스트와 develop `terraform validate`도 통과했다.
- develop 전체 saved plan `/tmp/lan418-develop.tfplan`은 `0 add, 3 change, 0 destroy`지만 LAN-418의 SSM 문서·연쇄 IAM policy 재평가 외에 live `ENABLED` Scheduler를 코드 기본값 `DISABLED`로 되돌리는 무관 변경이 포함되어 apply 대상에서 제외한다.
- LAN-418 SSM 문서만 분리한 saved plan `/tmp/lan418-develop-ssm.tfplan`은 `0 add, 1 change, 0 destroy`다. target plan은 전체 구성 변경을 대표하지 않으므로 사용자 승인 없이 apply하지 않는다.
- 사용자 승인 후 fresh targeted saved plan `/tmp/lan418-develop-approved.tfplan`을 적용했다. 결과는 develop SSM 문서 한 건의 in-place 변경으로 `0 added, 1 changed, 0 destroyed`다.
- AWS의 `develop-landit-ec2-deploy` 문서는 latest/default version `4`, `Active` 상태다. 게시 내용에 AI `mem_limit: 1024m`, 주간 persistent cleanup timer, 7일 이전 미사용 Docker image 정리, 14일 이전 journal 정리가 포함된 것을 확인했다.
- SSM 문서 targeted post-apply plan은 `No changes`다. develop 전체 post-apply plan에는 기존 review reminder Scheduler를 `ENABLED`에서 코드 기본값 `DISABLED`로 되돌리는 무관한 drift 한 건만 남아 있어 적용하지 않았다.
- 현재 실행 중 AI 컨테이너는 재배포하지 않았다. 따라서 1024MiB 제한과 cleanup timer의 EC2 실반영은 다음 AI 배포 후 확인한다.
- AI 재배포 후 cleanup service가 성공해 Docker 기준 2.041GB를 회수했고 루트 EBS 사용률은 89%에서 81%로 낮아졌다. AI 컨테이너는 1GiB 제한, OOM 없음, 재시작 0회이며 cleanup timer는 enabled·active 상태다.
- 사용자는 develop의 최근 미사용 image 누적도 더 빠르게 회수하도록 보존 기간을 7일에서 1일로 줄이고 루트 EBS를 20GiB에서 30GiB로 확장하기로 결정했다. 실제 apply 전 fresh plan을 검토한다.
- production AI는 EC2가 아닌 Fargate task다. live task definition revision 4는 0.25 vCPU, 512MiB, 기본 ephemeral storage를 사용하며 desired/running 1/1, rollout completed, failed task 0이다. 최근 조회 구간의 메모리 최대는 약 25.6%, CPU 최대는 약 8.0%였다.
- 변경 전 테스트는 기존 `until=168h`와 `volume_size = 20` 때문에 각각 실패했고, 구현 뒤 cleanup·EC2 계약·runtime rollback 테스트와 `terraform fmt -recursive -check`, `git diff --check`, develop `terraform validate`가 통과했다.
- develop 전체 saved plan은 `0 add, 4 change, 0 destroy`로 EBS·SSM 문서 외에 연쇄 IAM policy 재평가와 기존 Scheduler `ENABLED -> DISABLED` drift를 포함한다. 이를 적용하지 않고 `aws_instance.app`과 `aws_ssm_document.ec2_deploy`만 분리한 saved plan `/tmp/lan418-develop-ebs30-retention1d-targeted.tfplan`을 생성했다.
- targeted plan은 `0 add, 2 change, 0 destroy`이며 EC2 root volume `20 -> 30GiB`와 cleanup filter `168h -> 24h`만 in-place 변경한다. 현재 root는 `/dev/nvme0n1p1` XFS이므로 apply 후 EBS modification 완료를 기다려 partition과 XFS를 확장하고, 24시간 cleanup script를 기존 EC2에 동기화한 뒤 실상태를 확인해야 한다.
- 사용자 승인 후 fresh targeted saved plan `/tmp/lan418-develop-ebs30-retention1d-approved.tfplan`을 `0 added, 2 changed, 0 destroyed`로 적용했다. EC2 인스턴스 교체 없이 encrypted gp3 root EBS와 SSM 문서만 in-place 변경됐다.
- root EBS는 30GiB `in-use`이고 volume modification은 백그라운드 `optimizing` 상태다. `/dev/nvme0n1p1` partition과 XFS를 온라인 확장해 파일시스템도 30GiB 전체를 사용하며, 서비스 중단은 없었다.
- 기존 EC2 cleanup script를 `until=24h`로 동기화하고 즉시 실행해 8.12GB를 추가 회수했다. 루트 사용량은 8.1GiB, 여유 22GiB, 사용률 27%이며 cleanup timer는 enabled·active다.
- AI 컨테이너는 1GiB 제한, 약 86.77MiB 사용, OOM 없음, 재시작 0회이고 로컬 `/health`는 `{"status":"ok"}`를 반환했다. SSM 문서는 latest/default version 5 `Active`, targeted post-apply plan은 `No changes`다.
- develop 전체 post-apply plan에는 기존 review reminder Scheduler의 `ENABLED -> DISABLED` drift 한 건만 남아 있으며 이번 승인 범위에서 적용하지 않았다.
- 병합 전 독립 리뷰에서 SSM의 runtime·Compose·cleanup 동기화가 deploy-service lock 획득 전에 실행되어 동시 BE·AI 배포가 파일을 교차 갱신할 수 있고, 개발자 문서의 7일 설명이 실제 24시간 정책과 다르다는 문제가 확인됐다.
- SSM은 모든 artifact를 같은 디렉터리의 임시 파일에 준비한 뒤 deploy lock을 잡고 원자적으로 설치하며, 같은 fd 9를 deploy-service에 상속해 전체 동기화·배포를 직렬화한다. 배포 성공 뒤 lock을 해제한 다음 cleanup을 시작해 nested-lock deadlock을 피한다.
- 실제 develop EC2의 Linux `flock`에서 부모가 보유한 fd 9를 자식 프로세스가 `flock -n -x 9`로 재사용할 수 있음을 격리된 임시 lock과 SSM response code 0으로 확인했다. 계약·runtime·cleanup 테스트, 포맷, diff check와 develop validate가 통과했다.
- 개발자 문서는 Docker `until=24h`의 의미에 맞게 생성 후 24시간이 지난 미사용 image를 정리한다고 수정했다. 이 병합 전 리뷰 수정은 아직 live SSM 문서 version 5에 apply하지 않았다.
