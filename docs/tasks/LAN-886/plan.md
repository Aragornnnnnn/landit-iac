# LAN-886 운영 EC2·RDS 준비와 시험 이관

운영 BE·AI는 서울 리전 `t3.medium` 한 대와 Caddy로 이전할 예정이다. 운영 PostgreSQL은 `db.t4g.micro` Single-AZ와 암호화된 gp3 20 GiB로 준비한다. 이 단계는 별도 운영 EC2와 RDS 생성, 운영 이미지 검증, 원본 DB 스냅샷 시험 복원을 포함한다.

## 인프라

- 기존 운영 VPC의 퍼블릭 서브넷 두 곳을 사용한다. 운영 EC2와 Single-AZ RDS는 같은 AZ의 서브넷을 사용한다.
- 기존 ECS를 관리하는 Terraform plan에서 준비 리소스의 삭제가 나타나지 않도록 `environments/prod/ec2-transition`과 별도 S3 상태를 사용한다. 이 root에 대한 변경은 승인된 plan을 로컬에서 적용하며 기존 Actions workflow의 대상은 유지한다.
- RDS는 공개 엔드포인트를 발급한다. PostgreSQL 인바운드는 EC2 보안 그룹에서 허용하고, 사용자가 승인한 외부 조회 IP는 별도 `database_client_ipv4` 입력에 IPv4 /32만 허용한다. 허용할 IP가 미정이므로 외부 규칙은 빈 목록으로 적용한다.
- EC2의 HTTP·HTTPS 인바운드는 트래픽 전환 때 연다. 시험은 SSM을 통해 EC2에서 Caddy의 루프백 주소와 호스트별 헬스체크를 확인한다.
- DB 관리자 비밀번호는 RDS가 Secrets Manager에서 관리한다. 이관을 실행할 때만 원본 연결에 필요한 SSM 파라미터 세 개와 대상 RDS 관리자 secret을 EC2에 한시적으로 허용한다. 시험이 끝나면 이 IAM 정책을 제거한다.

## 시험 복원

1. Supabase PostgreSQL 17.11에서 읽기 전용 스냅샷을 열고 `public` 스키마의 덤프와 테이블별 행 수를 같은 스냅샷에서 읽는다.
2. RDS의 별도 `landit_rehearsal` DB에서 `vector`, `pgcrypto`, `uuid-ossp` 확장을 만들고 복원한다. 원본 소유권과 ACL은 서비스 계정에 맞게 별도로 설계하며, RLS 정책이 참조하는 `landit_push_reader` 역할은 로그인 권한 없이 만들어 둔다. Supabase 전용 함수에 직접 연결된 트리거는 시험 복원 목록에서 제외한다.
3. 복원 직후 테이블별 행 수를 비교하고, 현재 운영 BE의 ECR 다이제스트로 Flyway를 실행한다. 이후 조회용 계정으로 연결한 BE, 썸네일 소비를 끈 AI, Caddy의 헬스체크를 검증한다.

재실행 시 `migration_access_until`에 짧은 UTC 만료 시각을 주고 plan을 확인한다. 운영 EC2의 SSM Run Command에서 `rehearse-database.py`에 대상 RDS DNS와 관리자 secret ARN을 전달한다. `rehearse-runtime.sh`에는 현재 운영 BE·AI의 ECR 다이제스트 URL을 전달한다. 두 스크립트는 root 권한으로 실행하며, DB 비밀번호를 명령 인자나 Run Command 출력에 넣지 않는다. `--resume-empty`는 복원 트랜잭션이 실패한 빈 시험 DB에서만 사용한다.

## 운영 전환 전 결정할 항목

- 원본에는 `landit_alerts`를 호출하는 활성 `pg_cron` 작업 하나, `pg_net`을 참조하는 `public.notify_landit_referral` 트리거, `supabase_functions`의 함수에 연결된 별도 웹훅 트리거가 있다. 시험 DB에서는 알림을 비활성화하며, 운영 이전 시 웹훅, 추천인 위험 알림 및 스케줄의 실행 위치를 결정한다.
- 원본의 푸시 조회 계정은 56개 RLS 정책과 연동된다. 이 계정의 실제 로그인과 `SELECT` 권한, 운영 애플리케이션의 DB 역할·권한은 전환 전 운영 계약과 대조한다.
- 서비스 공개 IP와 TLS 인증서, AWS WAF의 차단·요청 제한 대체, Caddy 뒤 클라이언트 IP 판별, 기존 운영 SSM 환경 변수의 매핑, 애플리케이션 CI 배포 대상 변경은 트래픽 전환 계획에서 검증한다.

## 현재 운영 이미지로 먼저 전환

- BE `v1.10.5`와 AI `v1.9.10`의 운영 ECS 이미지 다이제스트로 EC2 최초 기동을 준비한다. BE·AI 릴리스 PR은 전환과 안정화 이후 병합한다. 첫 BE 업그레이드에서는 기존 `v1.10.5`에 슬롯별 예약 작업 제어가 없으므로 구버전 예약 작업 종료 후 새 슬롯이 활성화되도록 검증한다.
- 운영 Supabase의 `public` 테이블은 132개이고 인덱스를 포함해 약 725 MiB다. Flyway는 V189다. 성공한 시험 복원의 SSM 실행은 2분 55초였고 테이블별 행 수가 일치했다. 실제 작업창에는 이 시간에 더해 쓰기 중지, 애플리케이션 검증 및 DNS 전환을 포함한다.
- 한 번의 전환에는 작업창에서 쓰기를 중지하고 새 스냅샷을 검증한 빈 운영 RDS `landit` DB에 복원하는 방식을 사용한다. ECS·예약 작업·웹훅 등 원본에 쓰는 경로를 모두 중지한 뒤 덤프한다. 복원 직후 테이블별 행 수, Flyway 이력, 시퀀스 값, 앱·푸시 조회 계정 권한을 대조한다. 기존 `landit_rehearsal`은 V190·V191 검증에 사용한 시험본으로 유지한다.
- 작업창을 더 줄여야 하면 Supabase에서 RDS로 단방향 논리 복제를 별도 리허설한다. 읽기 전용 조회 기준 `wal_level=logical`, 사용 중인 슬롯 0개, 슬롯 상한 5개, 복제 식별자가 없는 `public` 테이블 0개다. 실제 복제 계정·네트워크·지연은 별도로 확인한다. PostgreSQL 17의 논리 복제는 DDL과 시퀀스를 옮기지 않으므로 별도로 맞추고, 원본 쓰기 중지 후 남은 변경이 모두 반영됐는지 확인한다. Supabase 전용 웹훅·위험 알림·스케줄도 별도 이관 항목이다.
- 운영 앱의 쓰기를 허용하기 전까지 실패하면 기존 ECS·Supabase 경로를 복구한다. RDS에 운영 쓰기가 들어간 이후에 원본으로 복귀하려면 새로운 쓰기의 역방향 반영과 데이터 검증을 먼저 수행한다.

### SSM·IAM 적용 후 운영 이미지 리허설

- 현재 ECS BE `:6`과 AI `:5`의 이미지 다이제스트로 전환 EC2를 확인했다. 격리 Caddy의 BE DB readiness와 AI `/health`가 통과했다. 확인 시 가용 메모리는 1,936 MiB였다. BE는 `landit_rehearsal`에 TLS로 연결했고, 테스트 계정에는 `public` 테이블 쓰기 권한이 없었다. 알림·썸네일 큐 소비를 끄고 관리 DB의 Flyway는 실행하지 않았다. 해당 시험 DB는 V191이며 실패한 이력은 0건이다.
- 최종 `landit`은 TLS 읽기 전용 점검 기준 `public` 테이블·시퀀스·Flyway 이력이 없다. 원본은 시퀀스 82개이며, 활성 Supabase 웹훅 2개와 추천인 트리거·스케줄이 각 1개다. RDS에는 `pg_cron`이 제공되고 `pg_net`은 제공되지 않는다. 시험 RDS에 복원한 56개 푸시 RLS 정책의 `landit_push_reader`는 로그인 불가 상태이므로 운영용 로그인과 권한 검증이 필요하다.
- 임시 컨테이너와 DB 조회 터널을 종료했다. 기존 시험 스택은 계속 실행 중이다. 운영 ECS의 BE·AI 리비전이 그대로이고 공개 BE·AI 헬스체크는 모두 HTTP 200이었다. 최종 복원, 공개 DNS, 운영 큐 인계는 진행 전이다.

## 2026-11-25 검증 결과

- 격리 root의 `terraform plan`에 추가 14개, 변경·삭제 0개를 확인했고, 저장한 plan으로 적용했다. 운영 EC2는 SSM Online으로 등록됐고 Docker Compose와 PostgreSQL 클라이언트가 준비됐다. RDS PostgreSQL 17.11은 `available` 상태이며, 백업 보존 7일과 삭제 보호를 확인했다.
- RDS는 공인 엔드포인트를 발급받았다. 보안 그룹에는 운영 EC2 보안 그룹을 출발지로 하는 `5432` 규칙 한 개가 있다. 외부 CIDR 규칙은 0개다.
- 운영 Supabase CA와 AWS RDS CA로 확인한 TLS 경로로 시험 복원했다. 원본 스냅샷과 `public` 테이블 132개의 행 수가 모두 일치했다. Supabase 관리 트리거 2개를 시험에서 제외했고, 추천인 위험 알림 트리거는 시험 DB에서 비활성화했다. 최종 이관 대상 `landit` DB와 별도로 `landit_rehearsal` DB를 유지한다.
- 복원된 Flyway 이력은 버전 189, 성공 210건, 실패 0건이다. 현재 운영 BE 이미지로 Flyway가 211개 마이그레이션을 검증했고 버전 189에서 추가 적용할 항목이 없음을 확인했다.
- SSM Run Command로 시험 Compose를 실행했고 Caddy 루프백에서 BE `/actuator/health`와 AI `/health`가 모두 응답했다. 기존 운영 ECS의 BE·AI는 각각 실행 1, 목표 1, 배포 완료 상태를 확인했다.
- 시험 후 한시적 IAM 정책 한 개만 제거했다. 최종 `terraform plan -detailed-exitcode`는 0과 무변경을 반환했다.

## 운영 BE 재배포

- BE 배포 워크플로의 `target=ec2`는 SHA 태그로 ECR 이미지 다이제스트를 조회하고 운영 EC2에만 허용된 `prod-landit-ec2-deploy-api` SSM 문서를 실행한다. GitHub의 `prod` 환경 변수 `EC2_INSTANCE_ID`가 대상이다. 기존 ECS 경로는 기본값으로 계속 사용한다.
- 시험 스택이 남았다면 운영 호스트에서 `docker compose -p landit-rehearsal --env-file /run/landit-rehearsal/compose-cleanup.env -f /run/landit-rehearsal/compose.yml down`으로 종료한다. `compose-cleanup.env`에는 보존된 시험 BE·AI 이미지 참조를 `API_IMAGE`와 `AI_IMAGE`로 넣는다. 이후 `rollout/prepare-proxy.sh`를 root로 실행한다. AI는 `landit-prod` 네트워크의 `landit-ai:8000`에서 독립적으로 동작한다. Caddy 관리 포트는 컨테이너 내부에 두고 라우트 디렉터리를 마운트한다.
- 최초 전환은 최종 DB 동기화와 기존 ECS의 DB 쓰기·큐 소비 종료 후 호스트에서 `bash rollout/deploy-api.sh sha256:<digest> --bootstrap`으로 시작한다. 이 모드에서는 로컬 프록시로 첫 슬롯을 검증한다. 공개 DNS·TLS를 전환한 뒤 GitHub Actions의 `target=ec2`로 같은 다이제스트 응답을 확인한다. 평상시 GitHub Actions 배포에는 초기 전환 예외를 제공하지 않는다.
- 호스트의 `/opt/landit/api.env`와 `migration.env`는 root만 읽을 수 있게 두고 동일한 운영 RDS의 `landit`에 연결한다. `DB_URL`에 `sslmode=verify-full`과 `sslrootcert=/run/landit/rds-ca.pem`을 지정하고, 앱과 마이그레이션의 사용자·비밀번호는 각 역할에 맞춰 설정한다. `/opt/landit/rds-ca.pem`에서 AWS CA를 제공한다. Flyway는 EC2에서 실행하므로 러너에 PostgreSQL 인바운드를 열 필요가 없다.
- 배포는 호스트 잠금으로 직렬화한다. 호환되는 Flyway 변경을 먼저 적용하고, 빈 슬롯에서 새 BE의 `readinessState`와 DB health를 확인한다. Caddy reload 후 내부·공개 주소의 응답에서 새 이미지 다이제스트를 확인한 다음 활성 슬롯을 바꾸고 이전 BE에 SIGTERM을 보낸다. 검증 실패 시 이전 Caddy 라우트를 복구하고, 복귀를 확인하지 못하면 두 컨테이너를 유지한다.
- 배포 완료 뒤 활성·직전 슬롯이 참조하지 않는 BE 배포 이미지를 정리하고 컨테이너 로그를 순환시킨다. 이전 다이제스트로 복구하려면 승인된 운영 권한으로 `prod-landit-ec2-deploy-api` SSM 문서의 `ImageDigest`에 이전 값을 넘긴다. 후보가 기존 스키마와 호환되는지 먼저 확인한다.
- Caddy는 `landit-prod` 네트워크의 `172.30.86.2`를 사용하고 나머지 컨테이너는 `172.30.86.128/25`에서 동적으로 주소를 받는다. BE는 재배포 시 Caddy의 단일 주소를 신뢰 프록시로 설정한다. 운영 호스트의 기존 네트워크와 충돌이 없는지 확인한다.
- 두 슬롯 모두 RDS에서 Hikari 최대 10개와 최소 유휴 1개를 사용한다. 예약 작업은 공유 활성 슬롯 파일과 파일 잠금으로 인계한다. SQS는 두 소비자가 잠시 공존하므로 기존 메시지 선점과 중복 방지 계약을 유지한다. 최초 운영 전환 전에는 실제 큐 환경에서 전환과 롤백을 각각 검증한다.
- 준비 EC2의 역할은 현재 ECR pull과 SSM 접속을 제공한다. 운영 컨테이너가 실제 SQS·S3 등에 접근할 최소 권한과 자격 증명 전달 방법을 정하고, IMDSv2 hop limit 1에서 Docker 브리지 컨테이너의 AWS 호출이 성공하는지 실제 역할로 확인한다.
- 최초 운영 전환과 두 슬롯 배포 전에 운영 수준의 요청을 유지한 채 BE 2개와 AI 1개가 겹치는 동안 가용 메모리와 요청 오류를 측정한다. 앱의 프록시 신뢰 설정, 도메인별 TLS, 기존 WAF 동작의 대체 여부는 운영 전환 검증에서 확인한다.
- 로컬에서 Caddy 2.8.4 reload 중 기존 요청은 이전 슬롯에서 완료되고 새 요청은 새 슬롯으로 도달했다. 호스트 스크립트의 전환·실패 복구 테스트와 SSM 결과 검증, BE Gradle 검사, Terraform validate를 통과했다. EC2 전환 root의 plan은 기존 EC2·RDS를 보존하면서 SSM 배포 문서와 권한을 추가하고, 호스트의 상시 SSM 관리형 정책을 Parameter Store 조회가 없는 전송 권한으로 교체한다.

## 운영 AI 배포

- AI의 `Deploy prod worker`는 기본 `target=ecs`를 유지한다. EC2 전환 root를 적용한 뒤 결과의 `worker_ec2_deploy_role_arn`과 전환 EC2 인스턴스 ID를 AI 저장소의 `PROD_WORKER_EC2_ROLE_ARN`과 `PROD_WORKER_EC2_INSTANCE_ID` 변수에 설정한다. 전용 역할은 AI `main`의 GitHub OIDC만 신뢰하며, 운영 워커 이미지 조회와 이 EC2의 `prod-landit-ec2-deploy-worker` 실행을 허용한다.
- 운영 프로세스를 띄우기 전에 `prepare-proxy.sh`로 Caddy를 준비하고, 운영 AI 환경 변수는 root만 읽을 수 있는 `/opt/landit/ai.env`에 둔다. 첫 실행과 전환 리허설 동안 `ROLEPLAY_THUMBNAIL_CONSUMER_ENABLED=false`를 유지한다. ECS의 기존 소비자가 종료되고 SQS·S3 자격 증명과 BE 내부 API 접속을 확인한 뒤 이 값을 활성화해 같은 릴리스를 다시 배포한다.
- 기존 버전의 EC2 배포는 GitHub Release가 기록한 검증 이미지 다이제스트를 재사용한다. 첫 기동과 재배포 모두 호스트 루프백의 Caddy `/health` 및 실제 컨테이너 이미지로 확인한다. 교체와 롤백 동안 AI 응답은 잠시 중단될 수 있다. AI와 BE는 호스트 잠금을 공유하므로 두 배포를 차례로 실행한다.
- 새 AI가 기동하거나 헬스체크를 통과하지 못하면 보존한 직전 컨테이너를 기존 이름으로 복구한다. 이미 성공한 배포를 되돌릴 때는 `target=ec2`에서 이전 `ai-v` 버전을 선택한다. 공개 DNS·HTTPS와 운영 큐 소비 검증은 전환 단계에서 수행한다.
- 호스트 모의 검증에서 최초 기동, 정상 교체, 헬스체크 실패 후 복귀, 최초 기동 실패 시 정리, 중단된 교체 재시도를 확인했다. 전환 root의 Terraform plan에는 기존 BE 변경과 함께 AI의 SSM 문서·배포 역할·권한이 포함되며 EC2와 RDS 변경은 없다.
- 2026-11-25 승인한 저장 plan을 적용했다. SSM 문서와 IAM 리소스 6개를 추가하고 기존 SSM 관리 정책 연결 1개를 전송 전용 정책으로 교체했다. 적용 후 Terraform plan은 무변경이고, BE와 AI의 SSM 문서는 모두 `Active`, 전환 EC2 에이전트는 `Online`이다. 기존 운영 ECS의 BE와 AI는 각각 기존 리비전으로 실행 중이며 RDS는 `available`이다.
