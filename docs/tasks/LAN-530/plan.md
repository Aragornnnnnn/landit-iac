# LAN-530 Jev SSM 등록과 AI 런타임 주입

## 승인된 최종 정책

2026-09-21 사용자 후속 결정으로 develop도 E1을 포함한 7개 목록을 저장하고 Jev는 비활성화한다. develop·prod 모두 `JEV_ENABLED=false`, `JEV_ENABLED_WORKFLOWS=["E1","E2","E3","E4","E7","E10","E13"]`, `CODE_SESSION_SUMMARY_ENABLED=false`다. E14 세션 요약은 기존 LLM을 유지한다.

각 환경의 `/landit/{environment}/{변수명}`에 9개 값을 String으로 등록한다. 모델·시간 제한·URL 값은 [Parameter Registry](../../ssm-parameters.md)를 따른다. 기존 `OPENROUTER_API_KEY`를 재사용하고 BE·AI 애플리케이션 버전을 바꾸지 않는다.

## 배포 전 확인

- IaC 작업 트리는 깨끗한 detached `6e85e5f`에서 시작했다. 원격 main `44a3277`의 Grafana 변경을 포함해 `feat/LAN-530`을 생성했다. BE·AI의 무관한 작업 트리는 수정하지 않는다.
- develop BE 실행 이미지의 소스 태그는 `017bd55241070672263673fb24493d5193f2629e`다. 해당 소스의 `RemoteExpressionRecommendationsResponse`는 빈 추천 목록을 `AI_RESPONSE_INVALID`로 거절한다. LAN-530의 NO_MATCH 수용 커밋 `f011c5214`는 현재 배포에 포함되지 않았다.
- develop AI 태그는 `825197adbcef45b8e691c9c206851db18bd0ac15`, digest는 `sha256:f34885158d7fdb08cbe85eba8d626866abb8d81071eceb167874b476597b71c9`다. 실행 컨테이너의 `app/core/config.py`에는 Jev·코드 요약 설정이 없다.
- prod AI 태그는 `fbf1459562e721dedca95c8040493e9f85d7bf69`, digest는 `sha256:7789a554f87a68332ee44837bf8aacd49a12ceff952c435bd2b31baef6d9ae4b`다. 해당 Git 소스에 LAN-530 설정이 없다.
- E1은 최종 사용자 결정에 따라 목록에서 제외하지 않는다. 전체 Jev가 꺼져 있으므로 E1도 실행되지 않는다. 이후 활성화 전 BE NO_MATCH 지원과 LAN-530 AI 배포를 확인해야 한다.
- 개발 IAM은 환경 경로의 `ssm:GetParametersByPath`, 운영 ECS execution role은 `ssm:GetParameters`를 이미 허용한다. 설정 주입을 위한 권한 확대는 없다.

## 변경 분리와 실행 경로

전체 plan에서 개발 EC2 IAM 및 배포 스크립트의 미적용 변경, 운영 BE task 교체와 구독 시점 매핑 제거, Sentry Lambda hash 변경이 발견됐다. 이번 적용에서 제외한다.

- 개발: 현재 SSM 문서 v14의 runtime-env·deploy-service·compose 내용과 실제 호스트 파일의 SHA-256이 일치함을 확인했다. 비커밋 임시 Terraform override로 기존 문서를 그대로 보존하고 runtime-env의 AI 목록에 9개 이름만 추가한다. 대상 plan은 `aws_ssm_document.ec2_deploy` 1개 update다. 저장소의 기존 배포 개선 코드는 보존하며 배포하지 않는다.
- 운영: 실행 중 API·AI digest를 `scripts/capture-prod-images.py`로 저장하고 AI task definition·service만 대상으로 plan한다. 실제 운영 AI container 정의와 비교해 AWS 기본값 정규화 및 9개 secrets 추가 외에는 변경이 없음을 확인했다. 기존 BE task는 보존한다.
- 개발 `user_data`는 ignore_changes 대상이다. 기존 인스턴스에는 user-data 수정이 실행되지 않는다. 적용된 SSM 문서를 실행해야 `/opt/landit/bin/runtime-env`가 갱신되고 `/run/landit/ai.env` 생성 후 AI 컨테이너가 재생성된다.
- 실제 tfvars·plan·state·호스트 정보·SSM 응답은 비공개 임시 디렉터리에만 보관하고 커밋하지 않는다. 비밀값은 출력하지 않는다.

## 검증 및 적용 결과

- SSM: develop·prod 각각 9개 String parameter를 배포 전에 등록하고 값·타입을 재조회했다. 작업 목록은 양쪽 모두 E1 포함 7개 JSON 배열이다.
- develop: SSM 문서 v15 적용 후 기존 AI 태그·digest가 일치함을 다시 확인해 AI만 재배포했다. Run Command `5ae8921a-e162-4420-ace2-f6b5b12c822e`가 Success다.
- develop 실행 검증: `5140dca9-3c8c-463b-8a7f-b18c94bfaa78`에서 9개 값과 실제 JSON 배열, runtime-env hash, 기존 AI 환경값 및 api.env 보존, 양쪽 이미지 보존, BE 컨테이너 생성 시각 불변을 확인했다. BE health UP, AI health ok다.
- prod: API revision 19와 기존 이미지·task를 유지하고 AI revision 9에서 10으로 주입 매핑을 갱신했다. 내부 검증 시 rollout COMPLETED, desired/running 1, pending 0이다.
- prod 실행 검증: revision 10 task `c3783b1977a647b49a0f8dde6ebb46bf`의 `/proc/1/environ`에서 9개 값과 JSON 배열을 확인했다. 컨테이너 코드에서도 Jev·코드 요약 설정 부재를 확인했고 loopback AI health는 ok다.
- 임시 ECS Exec: 자동 승인 검토가 정확한 IAM 범위 승인 부재로 거절한 뒤, 사용자가 task role의 ssmmessages 채널 4개 권한과 검증 후 원복을 명시 승인했다. 검증 후 임시 policy 삭제와 service Exec 비활성화만 포함한 plan을 검토·적용했다. [AWS ECS Exec 문서](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-exec.html)에 따라 실행 task의 Exec 설정은 생성 시 정해지므로, 같은 revision·이미지로 Exec 없이 새 task를 시작해 원복했다.

- 최종 운영 AI task `b984b4f7c51b455d99a8d61c2a233e29`는 RUNNING, Exec false다. 임시 role policy 부재와 BE 기존 task 불변을 재조회했다. 최종 task의 시작 로그 100개에 ERROR·Traceback은 없었다.
- 최종 공개 health: `api-develop.landit.im/actuator/health`, `ai-develop.landit.im/health`, `api.landit.im/actuator/health`, `ai.landit.im/health` 모두 HTTP 200, BE UP·AI ok다. 운영 양쪽 ALB target healthy, rollout COMPLETED, running 1·pending 0이다.
- Exec 원복 후 최종 task는 동일 revision 10·동일 digest·동일 SSM 값으로 정상 시작했다. 내부 환경변수 직접 조회는 원복 직전 검증 task에서 수행했다. 최종 task에서는 Exec을 다시 열지 않고 task 설정·이미지·SSM·health로 확인했다.
- 실제 컨테이너에 주입된 `JEV_ENABLED`와 `CODE_SESSION_SUMMARY_ENABLED`는 양쪽 false다. 실행 중 이미지에 해당 설정 코드가 없으므로 실제 Jev 경로 실행 확인은 하지 않았다.

검증 명령:

- `terraform fmt -recursive`, `terraform fmt -recursive -check`, `git diff --check`: 통과.
- `terraform -chdir=environments/dev validate -no-color`, `terraform -chdir=environments/prod validate -no-color`: 통과. 최초 sandbox 내 provider 실행은 실패해 동일 명령을 scoped escalation으로 재실행했다.
- 양쪽 전체 `terraform plan`, 위 범위의 `-target` 저장 plan·JSON 비교·apply: 완료. 운영 apply 직전 `capture-prod-images.py --check`로 실행 이미지와 배포가 plan 기준과 일치함을 확인했다.
- 개발 적용 범위의 `terraform plan -detailed-exitcode -target=aws_ssm_document.ec2_deploy`, 운영 적용 범위의 `terraform plan -detailed-exitcode -target=module.app_platform.aws_ecs_service.worker[0]`(실행 이미지 tfvars 사용): 모두 exit 0. 개발 검증은 제한 적용 override 상태에서 수행했다. 전체 drift가 없다는 뜻은 아니다.
- `bash scripts/test-dev-ec2-runtime.sh`: 통과. SSM → env_file JSON 인용, 9개 값 보존, API에 주입하지 않음, 기존 이미지·rollback 경계를 검증했다. 출력의 모의 health 실패 문구는 의도된 rollback 테스트다.
- `bash scripts/test-dev-ec2-contract.sh`, `bash scripts/test-prod-ai-memory-contract.sh`: 통과.
- `python3 -m unittest discover -s scripts/tests -p test_capture_prod_images.py`: 4개 통과.

## 남은 작업

- BE NO_MATCH 수용 변경과 LAN-530 AI 애플리케이션 배포는 수행하지 않았다. 두 환경의 기존 이미지 digest를 보존했다.
- Jev는 양쪽 모두 비활성화다. 실제 공급자 `decision_call`, 품질·비용·지연 개선은 확인하지 않았고 이 작업의 설정 주입 완료와 구분한다.
- develop 활성화 전 BE 호환과 LAN-530 AI 이미지 배포를 먼저 확인한다. E1은 목록에 포함되어 있어 전체 플래그를 켜면 함께 활성화되므로 선행 조건을 건너뛰지 않는다. E14는 계속 비활성화한다.
- 기존 전체 plan의 개발 배포 개선·IAM drift, 운영 BE/Sentry drift는 해당 작업에서 별도로 검토한다. 이번에 제외한 변경을 전체 apply로 함께 반영하지 않는다.
