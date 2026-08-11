# LAN-299 관리자 콘텐츠 이미지 업로드 IaC 설계

## 목표

관리자 웹이 공지·업데이트 본문 이미지를 shared private S3 버킷에 직접 업로드하고 기존 CloudFront로 조회할 수 있도록 브라우저 CORS, develop·production API ECS 최소 권한과 런타임 설정을 Terraform으로 관리한다.

## 범위

이번 저장소에서 구현하는 범위는 다음과 같다.

- shared 콘텐츠 S3 버킷의 브라우저 직접 업로드 CORS.
- develop·production API Task Role의 shared 콘텐츠 업로드 권한.
- API 컨테이너가 presigned URL과 CloudFront URL을 만들 때 사용할 환경 변수.
- shared·develop·production Terraform state 연결.
- IaC 계약 테스트, Terraform 검증, plan과 적용 후 live 검증 절차.
- 콘텐츠 저장 문서의 관리자 업로드 계약.

다음 항목은 landit-be 후속 범위다.

- 관리자 전용 presigned URL 발급 API.
- 파일 확장자, MIME type과 크기 검증.
- presigned URL 만료 시간과 서명 header 구성.
- 공지·업데이트 구조화 이미지 블록의 URL과 대체 텍스트 저장.
- 미사용 객체 자동 삭제와 정리 작업.

## 기존 구조

`environments/shared`는 account 단위 private 콘텐츠 버킷과 CloudFront distribution을 소유한다. S3 public access는 차단되어 있고 CloudFront OAC만 `content/*` 객체를 읽을 수 있다. develop과 production의 API·AI ECS는 `modules/app-platform`에서 환경별 application bucket과 Task Role을 사용한다.

새 관리자 이미지도 `content/*` 아래에 저장하므로 CloudFront distribution이나 OAC read 범위를 넓힐 필요가 없다. 변경이 필요한 지점은 shared 버킷 CORS와 두 API Task Role의 write 권한이다.

## 아키텍처

### Shared root

shared 콘텐츠 버킷에 다음 CORS rule을 추가한다.

- 허용 method: `PUT`.
- 허용 origin: `https://landit.im`, `https://develop.landit.im`, `http://localhost:3000`, `http://127.0.0.1:3000`, `http://10.0.2.2:3000`, `http://172.16.103.142:3000`, `http://192.168.219.107:3000`.
- 허용 header: `Content-Type`, `Cache-Control`, `If-None-Match`, `x-amz-*`.
- 노출 header: `ETag`.
- preflight cache: 3,600초.

끝에 `/`가 있는 `https://develop.landit.im/`은 브라우저 Origin 형식에 맞춰 `https://develop.landit.im`로 저장한다. CORS는 브라우저 접근 제어이며 인증 수단으로 사용하지 않는다.

### Environment roots

`environments/dev`와 `environments/prod`는 S3 backend의 `shared/landit-iac/terraform.tfstate`를 `terraform_remote_state`로 읽는다. 각 root는 다음 shared output을 app-platform module에 전달한다.

- `content_bucket_name`.
- `cloudfront_url`.

shared state가 없거나 output 계약이 깨지면 environment plan이 리소스 변경 전에 실패한다. 같은 값을 dev·prod 변수에 중복 작성하거나 SSM Parameter Store에 복제하지 않는다.

### App platform module

app-platform module은 콘텐츠 버킷 이름과 CloudFront 기준 URL을 필수 입력으로 받는다. API Task Role에는 다음 권한만 추가한다.

```text
Action: s3:PutObject
Resource: arn:aws:s3:::${content_bucket_name}/content/inbox/*
```

같은 AWS account의 identity policy이므로 shared bucket policy에 API Role별 allow statement를 중복 추가하지 않는다. 기존 bucket policy의 HTTPS 강제 deny와 CloudFront read allow는 유지한다. AI worker 권한은 변경하지 않는다.

API container definition에는 다음 일반 환경 변수를 추가한다.

```text
CONTENT_BUCKET_NAME=${content_bucket_name}
CONTENT_CLOUDFRONT_URL=${cloudfront_url}
```

두 값은 secret이 아니므로 SSM secret으로 주입하지 않는다.

## 객체와 API 계약

객체 key는 다음 형식을 사용한다.

```text
content/inbox/{uuid}.{extension}
```

공지·업데이트 유형이나 아직 생성되지 않은 DB ID를 key에 넣지 않는다. 이를 통해 본문 저장 전에도 업로드 URL을 발급할 수 있고 콘텐츠 유형 변경이 객체 경로에 영향을 주지 않는다.

백엔드 presigned PUT 구현은 다음 조건을 지켜야 한다.

- 관리자인지 확인한 뒤 URL을 발급한다.
- 요청한 확장자와 MIME type의 허용 여부를 검증하고 업로드 방식에서 최대 파일 크기를 강제한다. 실제 파일 signature 검증이 필요하면 업로드 완료 뒤 별도 검증을 수행한다.
- 서버가 UUID를 생성하고 클라이언트가 key를 지정하지 못하게 한다.
- `Content-Type`, `Cache-Control: public, max-age=31536000, immutable`, `If-None-Match: *`를 서명 계약에 포함한다.
- 짧은 만료 시간을 사용한다.
- 응답에 객체 key와 `${CONTENT_CLOUDFRONT_URL}/${key}`를 함께 제공한다.

IaC는 파일 내용이나 크기를 검증할 수 없고 CORS도 이를 보장하지 않는다. 요청 metadata만 검사하고 실제 업로드 크기를 제한하지 않는 구현도 완료로 볼 수 없다. 따라서 해당 백엔드 완료 기준을 IaC 작업 완료로 표시하지 않는다.

## 데이터 흐름

1. 관리자가 backend presigned URL API에 파일 metadata를 보낸다.
2. backend가 관리자 권한, 형식과 크기를 검증하고 UUID key를 만든다.
3. backend가 API Task Role credentials로 presigned PUT URL을 만든다.
4. 관리자 웹이 CORS preflight 뒤 S3에 직접 PUT한다.
5. backend 또는 frontend가 CloudFront 기준 URL과 key를 조합한다.
6. 공지·업데이트 이미지 블록이 CloudFront URL과 대체 텍스트를 저장한다.
7. 클라이언트가 CloudFront URL을 요청하고 OAC가 private S3 객체를 읽는다.

## 실패와 보안 경계

- shared remote state를 읽지 못하면 dev·prod plan을 중단한다.
- API Role의 다른 shared 콘텐츠 prefix 쓰기는 AccessDenied가 되어야 한다.
- AI worker의 `content/inbox/*` 쓰기는 AccessDenied가 되어야 한다.
- UUID와 `If-None-Match: *`를 함께 사용해 기존 key 덮어쓰기를 거부한다.
- presigned URL은 만료 전까지 bearer credential이므로 로그나 DB에 원문을 저장하지 않는다.
- S3 CORS origin allowlist는 비브라우저 요청을 차단하지 않으므로 관리자 API 인증을 대체하지 않는다.
- 미사용 객체 삭제, lifecycle과 정리 job은 후속 범위로 유지한다.

## 검증

구현 검증은 다음 순서로 진행한다.

1. 계약 테스트에서 shared CORS origin·method·header, remote state 연결, API Role prefix 제한, API 환경 변수와 worker 미변경을 검사한다.
2. `terraform fmt -recursive`와 `git diff --check`를 실행한다.
3. shared·dev·prod root에서 `terraform validate`를 실행한다.
4. shared·develop·production saved plan을 각각 생성한다.
5. shared plan은 S3 CORS 변경만, develop·production plan은 API IAM policy와 API Task Definition·Service 갱신만 포함하는지 확인한다.
6. 사용자가 세 plan을 승인한 뒤에만 apply한다.
7. live S3 CORS, 두 API Task Role policy와 API Task Definition 환경 변수를 조회한다.
8. IAM policy simulation으로 API Role의 `content/inbox/*` PutObject 허용, 다른 prefix 거부와 worker 거부를 확인한다.
9. 별도 운영자 권한으로 UUID 임시 객체를 `content/inbox/*`에 업로드한다.
10. CloudFront URL이 `200`과 올바른 `Content-Type`, immutable cache header를 반환하는지 확인한다.
11. 검증용 객체는 삭제 권한을 이번 API Role에 주지 않는다. 별도 운영자 권한으로 제거할 때는 대상 key를 명시하고 사용자 승인을 받는다.

실제 presigned API와 이미지 블록 연동 확인은 landit-be 구현·배포 뒤 별도로 수행한다.

## 배포와 롤백

shared CORS를 먼저 적용한 뒤 develop, production 순서로 API IAM과 Task Definition을 적용한다. 각 environment는 기존 ECS rolling deployment와 health check를 사용한다.

문제가 생기면 환경별 API Task Role의 shared PutObject statement와 두 환경 변수를 제거해 롤백한다. shared CORS rule은 업로드 경로가 더 이상 필요 없을 때 별도 shared plan으로 제거한다. 기존 CloudFront 조회와 시나리오 콘텐츠 경로는 변경하지 않는다.
