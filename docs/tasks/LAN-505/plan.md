# LAN-505 이메일 발송 기반

## 확정 범위

- AWS SES, `Landit <no-reply@landit.im>` 발신 주소, 개발 서버 관리자 임의 주소 테스트를 준비한다.
- 별도 수신 허용 목록을 두지 않는다. AWS SES 샌드박스의 인증된 수신자 제한은 해제 승인 전까지 적용된다.
- 후속 사용자 요청으로 운영 SES·IAM·상품 설정과 ECS 환경 설정까지 반영한다. 새 BE 알림 코드의 main 병합·배포는 별도다.

## 구성

- 서울 리전 `landit.im` 발신 도메인은 개발 Terraform root에서 한 번만 소유한다. 향후 운영도 동일 identity를 참조하며 중복 생성하지 않는다.
- `develop-landit-transactional` 설정은 반송·불만 주소 차단과 CloudWatch `AWS/SES`, `Environment=develop` 전달 지표를 사용한다.
- 개발 EC2 역할은 `no-reply@landit.im` 발신만 허용하고, 기존 Scheduler 그룹의 `notification-job-*` 생성·조회를 허용한다. 기존 PassRole 정책을 재사용한다.
- 개발 runtime-env 템플릿은 발신 주소와 SES configuration set을 전달한다. 이메일 발송·자동 체험 예약의 중복 환경 변수 스위치는 제거하고 BE DB의 채널 설정으로 ON/OFF를 통일했다. DB 기본값은 BE V106부터 모두 ON이다. SANDBOX 체험 허용은 ON이며 실제 연간 상품 ID 설정이 필요하다. 관리자가 OFF로 변경한 경우에만 채널을 다시 켠다.
- CloudWatch는 집계 전달 지표다. BE의 ACCEPTED는 SES 접수이며 개별 메일의 최종 수신 상태를 뜻하지 않는다. 별도 이벤트 소비자나 경보 수신처는 이번 변경에 추가하지 않는다.

## DNS 인증

Vercel의 `landit.im` DNS에 다음 CNAME 3개를 등록했다. Host는 도메인을 뺀 값이며, 기존 레코드는 유지했다. TTL은 60초다.

| Host | Value |
| --- | --- |
| `swpudjxbjxpdsuhzqa7v56qna2ahzzwk._domainkey` | `swpudjxbjxpdsuhzqa7v56qna2ahzzwk.dkim.amazonses.com` |
| `eeqvbxb4l3cosghzvet32oledzefgpsk._domainkey` | `eeqvbxb4l3cosghzvet32oledzefgpsk.dkim.amazonses.com` |
| `xm2fiaszxaakbdkjqmwgstlqegqibbbv._domainkey` | `xm2fiaszxaakbdkjqmwgstlqegqibbbv.dkim.amazonses.com` |

- CNAME 3개는 `ns1.vercel-dns.com`과 공용 DNS `1.1.1.1`에서 모두 기대값과 일치한다.
- 후속 조회에서 `VerificationStatus=SUCCESS`, `VerifiedForSendingStatus=true`, `DkimAttributes.Status=SUCCESS`를 확인했다.
- 샌드박스에서 테스트 수신 주소를 인증한 뒤 실제 메일을 발송했다. 임의의 미인증 수신 주소로 보내려면 SES 샌드박스 해제가 필요하다.
- Apple 비공개 릴레이 주소의 수신은 Apple Developer에서 발신 도메인 등록도 필요하다.
- SES 샌드박스 해제 신청이 승인됐다. 서울 리전 `ProductionAccessEnabled=true`, `ReviewDetails.Status=GRANTED`를 확인했다.

## 2026-09-16 검증과 적용

- 원본 저장소의 기존 작업을 보존하고 `origin/main`에 해당하는 `aaea650`에서 `feat/LAN-505`를 만들었다.
- `terraform fmt -recursive`, 개발 root `terraform init`, `terraform validate` 성공.
- 전체 개발 plan은 4개 추가·3개 변경·0개 삭제였다. 기존 ECR 배포 권한 등 선행 미적용 변경이 포함되어 전체 계획을 적용하지 않았다.
- SES identity, configuration set, event destination, EC2 이메일 정책만 target 계획으로 제한했다. 해당 계획은 4개 추가·0개 변경·0개 삭제였으며 saved plan apply에 성공했다.
- AWS 읽기 검증으로 configuration set의 BOUNCE/COMPLAINT 차단 및 SEND/DELIVERY/BOUNCE/COMPLAINT/REJECT/DELIVERY_DELAY 지표 활성화를 확인했다.
- runtime-env 템플릿과 SSM 배포 문서 변경은 아직 서버에 적용하지 않았다. BE 코드 배포와 함께 반영해야 한다. 기존 개발 API 이미지나 프로세스는 바꾸지 않았다.
- SES API 직접 호출로 테스트 메일 1통의 접수를 확인했고, 사용자가 네이버 메일함의 실제 수신 화면을 제공했다. 발신 주소·제목·본문 표시가 정상이다. 이 결과는 관리자 API나 개발 서버의 종단 발송 검증을 포함하지 않는다.

## DB 채널 제어 통일 검증

- 개발 runtime-env의 중복 이메일 발송·체험 예약 환경 변수 스위치를 제거했다. 발신 주소와 configuration set은 유지하고 ON/OFF는 BE 관리자 API가 변경하는 DB 설정을 사용한다.
- `terraform fmt -check -recursive`, `terraform validate`, `terraform plan -input=false -lock-timeout=30s` 성공. 계획은 기존 미적용 IAM·SSM 변경을 포함해 0개 추가·3개 변경·0개 삭제다. 실제 적용과 서버 배포는 하지 않았다.

## 운영 알림 인프라

- RevenueCat landit 프로젝트의 상품 목록에서 iOS `com.saynow.app.premium.yearly`, Android `com.saynow.app.premium.yearly:yearly`를 확인했다. Android 웹훅 식별자는 subscription ID와 base plan ID를 콜론으로 연결한다.
- 두 상품을 쉼표로 연결해 `/landit/prod/LANDIT_TRIAL_REMINDER_ANNUAL_PRODUCT_IDS`와 `/landit/develop/LANDIT_TRIAL_REMINDER_ANNUAL_PRODUCT_IDS`에 String으로 등록하고 재조회했다. 채널 ON/OFF는 계속 DB에서 관리한다.
- ECS module에 운영 SES configuration set, BOUNCE/COMPLAINT 차단, 전달 지표, 발신 주소가 `no-reply@landit.im`인 SES SendEmail 및 `notification-job-*` 예약 권한을 추가했다. 도메인 identity는 기존 개발 root 소유 리소스를 참조한다.
- API 작업 정의에 발신 주소, `prod-landit-transactional`, 체험 SANDBOX 제외 설정과 상품 ID SSM 연결을 추가했다. 개발 runtime-env도 같은 상품 ID SSM을 읽도록 수정했다.
- `terraform fmt -recursive`, 개발·운영 `terraform validate`, 운영 전체 plan 성공. 전체 계획의 5개 추가·5개 변경·2개 교체 삭제에는 기존 ALB·AI 변경이 포함되어 적용하지 않았다.
- 현재 API·AI image digest를 capture-prod-images.py로 고정하고 apply 직전 일치를 확인했다. SES configuration set·이벤트 지표·IAM만 별도 saved plan으로 적용했다. 결과는 3개 추가·0개 변경·0개 삭제다.
- 운영 API 환경 설정은 실행 중 revision 14를 복제해 알림 환경 변수 3개와 상품 ID SSM 연결 1개만 추가했다. 이미지와 그 밖의 설정을 보존하고 revision 15로 서비스를 전환했다. ALB·AI 및 기존 task revision은 유지했다. Terraform 소스에는 동일한 알림 설정을 반영했고 기존 미적용 인프라 차이는 남아 있다.
- `scripts/test-dev-ec2-runtime.sh` 성공. SES 템플릿 입력 및 상품 목록 SSM fixture를 보완하고 API 환경 전달과 폐기한 중복 스위치의 부재를 검증했다. 실제 개발 runtime-env/SSM 배포 문서 반영은 BE 개발 배포 때 필요하다.
- 적용 후 IAM 시뮬레이션에서 지정 발신자의 SES SendEmail, 알림 Scheduler CreateSchedule/GetSchedule, 기존 Scheduler 역할의 PassRole이 모두 allowed임을 확인했다. 운영 SES suppression·지표 설정을 재조회했다.
- 최종 운영 ECS 확인: API revision 15, desired/running 1/1, pending 0, rollout COMPLETED. 새 태스크의 image digest는 기존과 같고 ALB healthy 및 `/actuator/health` UP을 확인했다. 이번 작업은 환경 설정 반영이며 새 BE 알림 코드나 마이그레이션 배포는 아니다.
