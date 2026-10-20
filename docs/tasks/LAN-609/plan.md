# LAN-609 운영 100점 평가 활성화.

- 기존 BE·AI 평가 전환 계획은 [BE LAN-609](https://github.com/Aragornnnnnn/landit-be/blob/develop/docs/tasks/LAN-609/plan.md)을 따른다. 사용자가 2026-10-20 운영 활성화를 승인했다.
- 운영 API에 `LANDIT_AI_ASSESSMENT_VERSION=text-score-v2.0`을 주입한다. 공통 모듈의 기본값은 기존 `text-level-v1.3`이며 운영 root만 새 척도를 선택한다.
- 현재 운영 이미지 digest를 고정하고 API task만 순차 교체한다. AI 이미지·서비스와 기존 평가 이력은 변경하지 않는다. SSM 파라미터는 추가하지 않는다.
- 사전 확인: 운영 BE·AI 이미지의 코드가 버전 헤더를 지원하며, 성공한 운영 FE 배포가 `scoreMax`에 따른 표시를 지원한다. 운영 DB의 V134가 적용됐고 점수 여섯 컬럼이 NUMERIC(5,2)다.
- 되돌릴 필요가 생기면 호환 BE 이미지에서 설정을 `text-level-v1.3`으로 변경한 새 task를 사용한다. v2 이력을 변경하거나 구형 바이너리로 되돌리지 않는다. 실제 롤백은 별도 사용자 확인을 받는다.
- 적용 계획과 실제 배포·평가 검증 결과는 아래에 기록한다.
