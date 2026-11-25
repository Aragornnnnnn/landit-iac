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

## 2026-11-25 검증 결과

- 격리 root의 `terraform plan`에 추가 14개, 변경·삭제 0개를 확인했고, 저장한 plan으로 적용했다. 운영 EC2는 SSM Online으로 등록됐고 Docker Compose와 PostgreSQL 클라이언트가 준비됐다. RDS PostgreSQL 17.11은 `available` 상태이며, 백업 보존 7일과 삭제 보호를 확인했다.
- RDS는 공인 엔드포인트를 발급받았다. 보안 그룹에는 운영 EC2 보안 그룹을 출발지로 하는 `5432` 규칙 한 개가 있다. 외부 CIDR 규칙은 0개다.
- 운영 Supabase CA와 AWS RDS CA로 확인한 TLS 경로로 시험 복원했다. 원본 스냅샷과 `public` 테이블 132개의 행 수가 모두 일치했다. Supabase 관리 트리거 2개를 시험에서 제외했고, 추천인 위험 알림 트리거는 시험 DB에서 비활성화했다. 최종 이관 대상 `landit` DB와 별도로 `landit_rehearsal` DB를 유지한다.
- 복원된 Flyway 이력은 버전 189, 성공 210건, 실패 0건이다. 현재 운영 BE 이미지로 Flyway가 211개 마이그레이션을 검증했고 버전 189에서 추가 적용할 항목이 없음을 확인했다.
- SSM Run Command로 시험 Compose를 실행했고 Caddy 루프백에서 BE `/actuator/health`와 AI `/health`가 모두 응답했다. 기존 운영 ECS의 BE·AI는 각각 실행 1, 목표 1, 배포 완료 상태를 확인했다.
- 시험 후 한시적 IAM 정책 한 개만 제거했다. 최종 `terraform plan -detailed-exitcode`는 0과 무변경을 반환했다.
