# LAN-454 운영 장기기억 USE 활성화

2026-09-10 작업 기록입니다. 준비와 보류 단계의 문장은 당시 상태를 기록하며, 최종 배포·검증 결과는 아래 운영 전환 기록에 있습니다.

## 작업 상태

- [x] 최신 main에서 작업 브랜치를 만들고 기존 SSM 연결·develop 검색 이력을 확인한다.
- [x] 운영 USE 변경·BE 재배포·복구 절차를 문서화하고 명령과 diff를 검증한다.
- [x] 조건부 운영 반영 승인을 받고 현재 배포된 AI·BE 버전으로 로컬 검증을 실행한다.
- [x] 만료된 PROFILE을 현재 사실로 답하는 LLM 재현 오류를 보완하고 재검증한다.
- [x] 승인된 AI 핫픽스를 main에 병합·배포하고 새 실행 이미지를 확인한다.
- [x] 재검증 통과 후 운영 USE SSM을 활성화하고 동일 BE 이미지 재배포를 시작한다.
- [x] BE 새 태스크·이미지 일치·health와 초기 오류를 확인한다.
- [ ] 활성화 후 실제 사용자 요청에서 기억 검색 기록과 응답 품질을 확인한다.

## 진행과 검증 기록

### 활성화 준비 당시 기록

- 최신 `origin/main`의 `b166ca0`에서 `feat/LAN-454`를 만들었다. USE는 Terraform 밖의 기존 SSM String이며 API task definition에 이미 연결돼 있어 Terraform 변경은 필요 없다.
- develop 읽기 조회에서 검색 기록 57건, 후보가 있는 기록 40건, 사용 표시 12건을 확인했다. 사용 표시는 모두 이전 `memory-retrieval-v1`이고 v2는 검색 기록 18건 중 사용 표시 0건이다. 기록 수는 세션 수나 인과적으로 검증된 사용률이 아니다.
- 기존 WRITE를 유지하고 운영 USE만 활성화한다. 별도 계정 제한 기능을 추가하지 않는다. 현재 BE 이미지와 같은 이미지로 API를 재배포하고, 복구 시 USE를 끈 뒤 API를 다시 배포한다.
- 이 브랜치는 운영 절차를 준비한다. SSM 변경과 실제 재배포는 아직 실행하지 않았다.
- 운영 읽기 확인에서 USE는 String v1, WRITE는 String v2이며 각각 변경 전 기대 상태와 일치했다. API revision 10은 두 parameter를 참조하고 PRIMARY·COMPLETED, desired/running 1/1이다. 실행 이미지와 ECR latest의 digest가 일치했다. 실제 적용 직전에 다시 확인한다.
- 활성화 명령 블록의 `bash -n`과 `git diff --check`를 통과했다. 문서만 변경했으므로 Terraform fmt·validate·plan과 애플리케이션 테스트는 실행하지 않았다.

### 현재 운영 버전의 로컬 검증과 활성화 보류

- 사용자는 로컬 재검증에서 문제가 없으면 USE 변경과 동일 BE 이미지 재배포를 승인했다. 운영 AI `d26182f`의 tree는 로컬과 동일하며, BE `7c0f3457`은 별도 임시 디렉터리에 export해 기존 dirty 파일을 보존했다.
- AI `.venv/bin/python -m unittest discover -s tests`는 504개 중 7개 skip, 실패 0건이다. 운영 BE 소스의 `./gradlew check --no-daemon`은 889개 테스트·Spotless·Checkstyle을 통과했다. 실제 로컬 HTTP 서버로 기억 쿼리 timeout과 일반 생성 timeout 유지도 검증했다. BE DB 통합 테스트는 H2 기반이며 운영 PostgreSQL 실행 증거가 아니다.
- 운영 SSM의 `openai/gpt-5.4-mini`로 합성 발화를 실제 호출했다. 현재 발화 반복, 정정, 기억 회상, 날짜 경계와 정정 resolution을 확인했으며 실제 임베딩은 1536차원이었다. 초기 정정 fixture의 불허 필드를 제거한 뒤 해당 사례 2회가 통과했다. `usedMemoryIds`에는 자기보고 오탐·후처리 누락이 남아 있어 정확한 사용률로 해석할 수 없다.
- 자동 승인 검토는 만료 기억을 현재 사실로 답할 위험으로 SSM 변경·ECS 재배포 실행을 거부했다. 추가로 현재 직장 질문과 과거 회상을 분리한 실제 LLM 9회에서 현재 직장 질문 3회 중 2회가 명확히 실패했다. 이전의 계약 테스트 통과를 품질 통과로 간주하지 않는다.
- 재현 조건: 현재 시각 `2026-09-11T00:05:00+09:00`, 기억 `사용자는 베를린의 서점에서 일한다.`, validTo `2026-08-31T23:59:59+09:00`, 질문 `Where do I work now?`. 실패 응답은 `You work at a bookstore in Berlin.`이며 번역도 현재형이고 usedMemoryIds가 포함됐다. 과거 회상을 허용하면서 현재 사실 단정을 막는 보완이 필요하다.
- 운영 USE String v1과 WRITE String v2가 모두 변경 전 기대 상태와 일치함을 재확인했다. SSM 변경·ECS 재배포·애플리케이션 코드 변경은 수행하지 않았다. 합성 검증 보고서는 로컬 `/tmp/lan454-use-llm-smoke.json`, `/tmp/lan454-use-llm-focused.json`, `/tmp/lan454-expiry-focused.json`에 있다.

### AI 보완 후 승인된 운영 전환

- AI `0454ec8`·`c8ace59`는 기억별 시간 상태와 동일 기준 시각을 전달한다. 전체 unittest 508개·기존 skip 7개·실패 0개, 공개 OpenAPI 동일, 실제 LLM 합성 최종 31회에서 만료 사실의 현재형 단정은 관측하지 않았다. 원래 질문은 수정 전 2/3 오답에서 최종 0/3이었다. 소수 합성 검증이며 운영 무오류 보장은 아니다.
- 사용자가 AI 핫픽스 push·main 병합·재배포 후 USE 활성화와 현재 BE 이미지 재배포를 명시적으로 승인했다. AI PR #99의 배포 완료와 실제 image digest 확인이 SSM 변경보다 먼저다. 마지막 배포 ai-v1.3.4의 다음 PATCH인 ai-v1.3.5를 사용한다.
- AI PR #99는 main `86c1888`로 병합됐고, 검증한 hotfix와 main의 Git tree가 일치했다. [운영 배포](https://github.com/Aragornnnnnn/landit-ai/actions/runs/34448857236)와 ai-v1.3.5 릴리즈가 완료됐다. 실행 태스크의 ECR digest가 머지 SHA 이미지와 같고 ECS COMPLETED·ALB healthy·AI health 200을 확인했다.
- 배포된 AI에 합성 질문 4건을 직접 호출해 만료 직장의 현재형 단정 차단, 과거 회상, 현재 유효한 직장과의 구분을 확인했다. 응답에서 과거 기억을 언급하고도 usedMemoryIds가 비어 있는 사례가 있어 사용 자기보고의 누락 한계는 유지된다. 실제 사용자 세션이나 BE 저장을 생성한 검증은 아니다.
- 2026-09-10 18:12 KST에 USE만 String v1 false에서 v2 true로 변경하고 API 재배포를 시작했다. WRITE는 String v2 true로 유지했다. 실행 직전 수정 AI·서비스 안정 상태·health와 기존 BE 실행 digest/ECR latest 일치를 다시 검증했다. API revision 10과 BE 코드 `7c0f3457` 이미지를 유지하며 Terraform apply·BE 빌드·DB 변경은 실행하지 않았다.
- 기존 main → develop PR #98에 두 핫픽스와 최신 배포·검증 결과를 반영했다. 역병합 PR 자체는 열려 있다.
- 18:24 KST 최종 확인에서 API 새 배포와 AI 모두 단일 PRIMARY·COMPLETED, desired/running 1/1, pending 0, failed task 0, ALB healthy였다. API와 AI 외부 health도 HTTP 200이다. API 새 태스크의 image digest는 변경 전과 정확히 같았다. BE는 약 184초 후 기동을 완료했으며 기동 전 ALB 실패 상태는 정상 상태로 전환됐다.
- 새 태스크 시작 이후 CloudWatch Logs Insights 완료 결과는 BE 52개·AI 628개 로그 중 ERROR·Traceback·기억 검색 fallback 일치 0건이다. 운영 검색 trace는 읽기 전용 집계에서 0건이므로 실제 사용자 요청의 검색·응답 품질 검증은 남아 있다. 합성 검증과 건강 검사만으로 실제 사용률을 보장하지 않는다.
- 변경된 운영 기록의 `git diff --check`를 통과했다. 기존 AI untracked 파일과 BE dirty 파일을 보존했으며 IaC는 운영 절차·결과 문서만 변경했다.

### 작업 문서 규칙 통일

- 사용자 요청으로 IaC의 AGENTS.md·README·개발자 가이드를 AI·BE와 같은 이슈별 `plan.md`·`design.md` 기준으로 통일했다. 단순한 작업의 문서 작성은 의무화하지 않는다.
- 이번 LAN-454 기록만 두 누적 문서에서 이 문서로 이동했다. 기존 두 파일은 작업 전 `origin/main`과 바이트 단위로 같고, 옮긴 기록의 누락이 없음을 확인했다. 과거 작업 문서는 유지한다.
- `git diff --check`와 변경 문서의 로컬 링크 검증을 통과했다. 문서만 변경했으므로 Terraform 검증·apply와 애플리케이션 테스트는 실행하지 않았다.
