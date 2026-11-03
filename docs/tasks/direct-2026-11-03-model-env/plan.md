# AI 모델 환경변수 주입 준비.

사용자가 AI 모델 적용 PR과 개발·운영 환경변수 사전 반영을 승인했다. 기존 이슈 없는 작업을 이어가며 제목은 “AI 기능별 모델 환경변수 주입 통일”로 정했다. AI PR #184와 연결한다.

모델/추론 설정 16개를 개발 EC2 runtime-env와 운영 ECS worker secrets에 같은 이름의 SSM 경로로 연결한다. 값은 Terraform state에 넣지 않고 `/landit/develop/`, `/landit/prod/` Parameter Store에서 관리한다. 공통 OPENROUTER_MODEL과 키·URL은 바꾸지 않는다.

사전 조건: 16개 파라미터를 두 환경에 먼저 생성해야 새 task/환경파일 생성이 실패하지 않는다. 기존 코드가 모르는 설정은 무시되며, 기존 기억 경로는 FREE_TALK_MEMORY_MODEL의 Luna/low를 지원한다. 임베딩과 단어 음성 기본값은 유지한다.

AWS 계정 982529430654, ap-northeast-2의 `/landit/develop/`와 `/landit/prod/`에 각각 16개(총 32개) String 파라미터를 신규 생성하고 전체 값 일치를 다시 조회해 확인했다. 기존 값·키·URL은 변경하지 않았다. 실행 중인 서비스의 이미지·task definition·컨테이너는 변경하지 않았다.

개발 실행 이미지는 4ebd187, 운영은 d5426677이며 기존 Settings의 extra=ignore와 기억 Luna/low 호출 호환성을 확인했다. 이 PR의 주입 설정은 이후 인프라 반영 시 적용된다. 현재는 SSM 값 사전 준비까지 완료한 상태이며, 새 모델 전체 전환은 AI PR #184 배포가 필요하다.

검증: `terraform fmt -recursive -check`, `bash scripts/test-dev-ec2-runtime.sh`, `bash scripts/test-dev-ec2-contract.sh`, `git diff --check` 통과. runtime 테스트는 SSM 모의 응답으로 16개 전부 ai.env에 주입되고 api.env로 새지 않는지 확인한다. 전체 Terraform validate/plan/apply는 실행하지 않았다. 전체 인프라 변경이나 서비스 재시작은 범위에 포함하지 않는다.

별도 리뷰어 `model_pr_review`가 base d9b1817 대비 변경 3파일과 이 문서를 검토했다. 동일 16개 설정의 개발·운영 주입, SSM 경로·권한, 구버전 설정 호환성을 확인했고 실제 결함은 발견하지 못했다.
