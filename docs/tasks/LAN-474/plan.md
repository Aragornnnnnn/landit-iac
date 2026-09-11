# LAN-474 배포 중 학습 보존.

기준: origin/main 0c1fca9. 이 저장소에는 develop 브랜치와 열린 PR이 없다. 사용자 확정 정책은 시작 후 24시간 같은 학습 재개, 첫 무료 기회는 해당 대화에 고정이다. 공개 순서는 dev 테스트 → 심사 → 출시 → 오픈을 유지한다.

- [x] BE·AI 배포 소유권과 이미지·환경변수 계약을 확인했다. prod 코드 workflow의 새 digest task revision 배포는 각 코드 저장소에서 변경한다.
- [x] 개발 optional 토큰과 운영 BE→AI 단계별 토큰 주입, sandbox 기본 dev 반영/prod 무시, 종료 유예를 연결했다. 실제 비밀값은 변경하지 않았다.
- [x] 운영 Terraform plan에 현재 실행 digest와 deployment snapshot을 고정하고 apply 직전 변경을 검사한다. 개발은 실제 실행 digest와 SHA를 기록하고 해당 digest로 rollback한다. 같은 SHA 재빌드 실패 회귀 테스트도 통과했다.
- [x] 구 AI 캐시 수거, 교차 버전·재시작 복구 스모크와 운영 적용 절차를 [배포 중 학습 보존](../../deployment-safety.md)에 기록했다. 블루그린은 필수 구현이 아니다.
- [x] `terraform fmt -recursive -check`, dev/prod `validate`, dev/prod 저장 `plan`, 실행 snapshot 캡처·saved plan 비교를 통과했다.
- [x] `python3 -m unittest discover -s scripts/tests -p 'test_capture_prod_images.py'` 4개와 `test-dev-ec2-{runtime,contract,cleanup}.sh`, `test-terraform-{workflow,actions-oidc}-contract.sh`를 통과했다.
- [x] bootstrap `validate`와 저장 `plan`을 통과했다. 운영 plan/apply 역할 두 개에 `ecs:ListTasks`, `ecs:DescribeTasks`만 추가한다.
- [x] 앞선 독립 검토 지적을 수정하고 이후 검토와 최종 검증은 사용자의 요청대로 주 에이전트가 직접 수행했다.
- [ ] 운영 코드 배포 역할의 revision 등록·태깅·PassRole 추가 코드 작성 승인이 필요하다. 자동 승인 검토가 이 권한 확대를 거절해 파일을 생성하지 않았다. apply·운영 배포는 별도다.

## 검증 결과.

2026-09-11 live read-only plan 기준이다. AWS 리소스·SSM 값·운영 앱은 변경하지 않았다.

- prod: ECS service 2개, API/AI task revision 2개, ALB idle와 target group drain 3개만 변경한다. task revision은 `skip_destroy=true`로 이전 버전을 보존한다. 기본값에서는 새 토큰 secret을 요구하지 않는다.
- dev: EC2 IAM, 배포 IAM, SSM 배포문서 변경이다. EC2 재생성·삭제는 없다.
- bootstrap: 운영 Terraform Actions 두 역할의 조회 권한 추가만 있으며 생성·삭제는 없다.
- provider 다운로드와 IPC, AWS read-only 호출은 샌드박스 밖에서 검증했다. private plan·JSON·digest 입력은 `/private/tmp/lan474-*`에만 보관하며 커밋하지 않는다.
- 실제 graceful 종료·HTTP 인증·학습 복구·스토어 결제는 코드 통합 후 dev/실기기에서 확인할 항목이다. Terraform plan과 mock 테스트는 이를 대신하지 않는다.
- plan 직전·apply 직전 검사는 원자적 배포 잠금이 아니다. 인프라 승인·apply 동안 다른 코드 배포를 멈추는 운영 규칙을 유지한다.

최종 개발 plan도 landit 프로필로 재실행해 `0 to add, 3 to change, 0 to destroy`를 확인했다. 세 환경 validate, fmt check와 배포 스크립트 테스트를 직접 다시 통과했다.
