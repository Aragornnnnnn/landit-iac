# LAN-609 운영 100점 평가 활성화.

- 기존 BE·AI 평가 전환 계획은 [BE LAN-609](https://github.com/Aragornnnnnn/landit-be/blob/develop/docs/tasks/LAN-609/plan.md)을 따른다. 사용자가 2026-10-20 운영 활성화를 승인했다.
- 운영 API에 `LANDIT_AI_ASSESSMENT_VERSION=text-score-v2.0`을 주입한다. 공통 모듈의 기본값은 기존 `text-level-v1.3`이며 운영 root만 새 척도를 선택한다.
- 현재 운영 이미지 digest를 고정하고 API task만 순차 교체한다. AI 이미지·서비스와 기존 평가 이력은 변경하지 않는다. SSM 파라미터는 추가하지 않는다.
- 사전 확인: 운영 BE·AI 이미지의 코드가 버전 헤더를 지원하며, 성공한 운영 FE 배포가 `scoreMax`에 따른 표시를 지원한다. 운영 DB의 V134가 적용됐고 점수 여섯 컬럼이 NUMERIC(5,2)다.
- 되돌릴 필요가 생기면 호환 BE 이미지에서 설정을 `text-level-v1.3`으로 변경한 새 task를 사용한다. v2 이력을 변경하거나 구형 바이너리로 되돌리지 않는다. 실제 롤백은 별도 사용자 확인을 받는다.
- 적용 계획과 실제 배포·평가 검증 결과는 아래에 기록한다.

## 사전 검증과 적용.

- 운영 BE `b0caf2e1acbb3a4d5c4ff1173a1691922b16f1e3`, AI `33d07ccd230822d2a1f4d0b533b9ff901743890a`, FE 성공 배포 `ac2a21e3de84dba2f22dfce457d1a655915f250d`의 버전 선택/표시 계약을 확인했다.
- 운영 AI 합성 발화 3개 요청은 HTTP 200, `text-score-v2.0`이며 영역별 58·86·78 등 1~100 정수 점수를 반환했다. 합성 요청은 DB에 저장하지 않았다.
- `terraform fmt -recursive`, 운영 root `terraform validate`, `git diff --check` 통과. 전체 production plan은 API task definition과 API service 두 리소스만 변경한다. 입력에서 현재 `revenuecat_apply_sandbox_events=false`를 보존했다.
- 이미지 snapshot을 apply 직전에 다시 대조했다. container 정의를 정규화해 평가 버전 환경변수 하나만 추가되는 것을 검증했다. 이미지·secret 참조·기존 환경변수·역할·CPU·메모리는 동일하다.
- 2026-10-20 17:37 KST 저장 plan 적용 성공. API revision 38 → 39 순차 교체 시작. 기존 revision은 `skip_destroy=true`로 보존한다. Terraform의 replacement 집계는 기존 AWS task definition 삭제를 의미하지 않는다.

## 배포 진행 중 관측.

- 새 API는 17:41:36 KST 애플리케이션 시작을 완료했다. 기동 로그의 `APPLICATION FAILED TO START` 및 DB connection timeout은 없었고 공개 BE·AI health는 정상이다.
- 두 API task가 공존하는 구간에서 별도 읽기 전용 DB 검증 연결이 session pool 한도 15개로 거부됐다. 이 때문에 pool 설정을 임의 변경하지 않았으며 연결 정리 이후 동일한 읽기 전용 조회가 정상 복구됐다.
- 적용 후 동일 입력의 전체 Terraform plan은 `No changes`다.
- 17:43:55 KST ECS rollout `COMPLETED`, desired/running 1, pending 0 및 실행 revision 39를 확인했다. 운영 API image digest는 그대로이며 AI revision 22·image digest·실행 task도 변경되지 않았다.
- 이후 공개 API health `UP`, AI health `ok` 및 읽기 전용 운영 DB 재접속을 확인했다. 신규 task의 설정은 `LANDIT_AI_ASSESSMENT_VERSION=text-score-v2.0`이다. 이전 revision 38은 ACTIVE로 보존됐다.
- 신규 실사용 평가의 v2 저장과 앱 실기기 표시는 아직 미확인이다. 전환 이후 새 평가가 아직 저장되지 않아 합성 AI 응답을 실사용 저장 검증으로 대체하지 않았다. 기존 이력 재평가나 사용자 계정의 테스트 세션 생성은 하지 않았다.
