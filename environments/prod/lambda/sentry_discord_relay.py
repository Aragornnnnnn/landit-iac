# Sentry issue alert를 검증해 prod Discord 장애 채널로 전달한다.
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from urllib import request


MAX_RAW_BODY_BYTES = 700_000
SIGNATURE_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
_secret_cache = {}
_ssm_client = None
_lambda_client = None


def get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        import boto3

        _lambda_client = boto3.client("lambda")
    return _lambda_client


def get_secret(parameter_name):
    if parameter_name in _secret_cache:
        return _secret_cache[parameter_name]

    global _ssm_client
    if _ssm_client is None:
        import boto3

        _ssm_client = boto3.client("ssm")

    parameter_names = [
        os.environ["AUTH_TOKEN_PARAMETER_NAME"],
        os.environ["DISCORD_WEBHOOK_PARAMETER_NAME"],
    ]
    parameters = _ssm_client.get_parameters(
        Names=parameter_names,
        WithDecryption=True,
    )["Parameters"]
    _secret_cache.update(
        {parameter["Name"]: parameter["Value"] for parameter in parameters}
    )

    if any(name not in _secret_cache for name in parameter_names):
        raise RuntimeError("required SSM parameter is missing")
    return _secret_cache[parameter_name]


def send_discord(webhook_url, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    webhook_request = request.Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Landit-Sentry-Relay/1.0",
        },
        method="POST",
    )
    with request.urlopen(webhook_request, timeout=4) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord webhook returned {response.status}")


def normalize_headers(headers):
    return {str(key).lower(): str(value) for key, value in headers.items()}


def decode_body(event):
    body = event.get("body")
    if not isinstance(body, str):
        raise ValueError("request body is required")
    if event.get("isBase64Encoded"):
        return base64.b64decode(body, validate=True).decode("utf-8")
    return body


def dispatch_delivery(body, signature, function_name):
    payload = json.dumps(
        {
            "relayMode": "delivery",
            "bodyBase64": base64.b64encode(body.encode("utf-8")).decode("ascii"),
            "signature": signature,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    result = get_lambda_client().invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=payload,
    )
    if result.get("StatusCode") != 202:
        raise RuntimeError("asynchronous Lambda invocation was not accepted")


def extract_event(payload):
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    event = data.get("event")
    return event if isinstance(event, dict) else {}


def extract_environment(payload):
    event = extract_event(payload)
    environment = event.get("environment")
    if environment:
        return str(environment).lower()

    tags = event.get("tags")
    if isinstance(tags, dict):
        value = tags.get("environment")
        return str(value).lower() if value else None
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict) and tag.get("key") == "environment":
                value = tag.get("value")
                return str(value).lower() if value else None
            if isinstance(tag, (list, tuple)) and len(tag) == 2 and tag[0] == "environment":
                return str(tag[1]).lower()
    return None


def truncate(value, limit):
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def project_name(event, rule_name):
    project = event.get("project_name") or event.get("projectName") or event.get("project")
    if isinstance(project, dict):
        project = project.get("slug") or project.get("name")
    if isinstance(project, str) and project:
        return project

    normalized_rule = str(rule_name).lower()
    if "be" in normalized_rule:
        return "be-prod"
    if "ai" in normalized_rule:
        return "ai-prod"
    return "unknown"


def service_label(project):
    normalized = project.lower()
    if "be" in normalized:
        return "BE"
    if "ai" in normalized:
        return "AI"
    return project.upper()


def build_discord_payload(payload):
    event = extract_event(payload)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rule_name = data.get("triggered_rule") or "Sentry issue alert"
    project = project_name(event, rule_name)
    environment = extract_environment(payload) or "prod"
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    title = event.get("title") or metadata.get("title") or metadata.get("type") or "Sentry issue"
    issue_url = event.get("web_url") or event.get("webUrl") or event.get("url")
    exception_type = metadata.get("type") or "unknown"
    level = event.get("level") or "error"

    embed = {
        "title": truncate(f"[PROD][{service_label(project)}] {title}", 256),
        "description": truncate(
            f"**Rule** {rule_name}\n**Exception** {exception_type}",
            4096,
        ),
        "color": 15158332,
        "fields": [
            {"name": "Project", "value": truncate(project, 1024), "inline": True},
            {"name": "Environment", "value": truncate(environment, 1024), "inline": True},
            {"name": "Level", "value": truncate(level, 1024), "inline": True},
        ],
    }
    if issue_url:
        embed["url"] = str(issue_url)

    return {
        "username": "Sentry Prod",
        "allowed_mentions": {"parse": []},
        "embeds": [embed],
    }


def response(status_code):
    return {"statusCode": status_code, "body": ""}


def is_delivery_event(event):
    return (
        isinstance(event, dict)
        and event.get("relayMode") == "delivery"
        and "requestContext" not in event
    )


def handle_ingress(event, context):
    headers = normalize_headers(event.get("headers") or {})
    try:
        body = decode_body(event)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return response(400)

    if len(body.encode("utf-8")) > MAX_RAW_BODY_BYTES:
        return response(413)

    provided_signature = headers.get("sentry-hook-signature", "")
    if SIGNATURE_PATTERN.fullmatch(provided_signature) is None:
        return response(401)

    function_name = getattr(context, "invoked_function_arn", None)
    if not function_name:
        raise RuntimeError("invoked function ARN is required")
    dispatch_delivery(body, provided_signature, function_name)
    return response(204)


def decode_delivery_body(event):
    body_base64 = event.get("bodyBase64")
    if not isinstance(body_base64, str):
        raise ValueError("delivery body is required")
    return base64.b64decode(body_base64, validate=True).decode("utf-8")


def handle_delivery(event):
    try:
        body = decode_delivery_body(event)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return response(400)

    signing_secret = get_secret(os.environ["AUTH_TOKEN_PARAMETER_NAME"])
    expected_signature = hmac.new(
        signing_secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    provided_signature = event.get("signature", "")
    if not hmac.compare_digest(provided_signature, expected_signature):
        return response(401)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return response(400)

    if not isinstance(payload, dict):
        return response(400)
    if extract_environment(payload) != "prod":
        return response(204)

    webhook_url = get_secret(os.environ["DISCORD_WEBHOOK_PARAMETER_NAME"])
    send_discord(webhook_url, build_discord_payload(payload))
    return response(204)


def lambda_handler(event, context):
    if is_delivery_event(event):
        return handle_delivery(event)
    return handle_ingress(event, context)
