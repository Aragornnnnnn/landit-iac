#!/usr/bin/env python3
# 개발·운영 썸네일 공유 토큰을 기존 값 보존 방식으로 준비하고 값 노출 없이 검증한다.
import argparse
import secrets

import boto3
from botocore.exceptions import ClientError


def prepare(ssm, environment, *, apply=False):
    prefix = f"/landit/{environment}"
    # 이미지 키는 기존 환경 전용 키를 사용하며 다른 환경이나 로컬 키로 덮어쓰지 않는다.
    key = ssm.get_parameter(Name=f"{prefix}/OPENAI_API_KEY", WithDecryption=True)["Parameter"]
    if key["Type"] != "SecureString" or not key["Value"].strip():
        raise ValueError("The environment OpenAI SecureString is missing or blank")
    name = f"{prefix}/ROLEPLAY_THUMBNAIL_WORKER_TOKEN"
    try:
        token = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ParameterNotFound":
            raise
        if not apply:
            return "token_missing"
        try:
            ssm.put_parameter(Name=name, Type="SecureString", Value=secrets.token_urlsafe(48),
                              Overwrite=False)
        except ClientError as race:
            if race.response["Error"]["Code"] != "ParameterAlreadyExists":
                raise
        token = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    if token["Type"] != "SecureString" or len(token["Value"].strip()) < 32:
        raise ValueError("The thumbnail SecureString token is invalid")
    return "ready"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("develop", "prod", "both"), default="both")
    parser.add_argument("--apply", action="store_true", help="승인된 경우에만 누락 토큰을 생성한다.")
    args = parser.parse_args()
    session = boto3.Session(profile_name="landit", region_name="ap-northeast-2")
    if session.client("sts").get_caller_identity()["Account"] != "982529430654":
        raise SystemExit("Unexpected AWS account")
    ssm = session.client("ssm")
    environments = ("develop", "prod") if args.environment == "both" else (args.environment,)
    for environment in environments:
        print(f"{environment}: {prepare(ssm, environment, apply=args.apply)}")


if __name__ == "__main__":
    main()
