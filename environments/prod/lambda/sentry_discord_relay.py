# Sentry issue alert를 검증해 prod Discord 장애 채널로 전달한다.
import base64
import binascii
import hmac
import json
import os
from urllib import request


_secret_cache = {}
_ssm_client = None


def get_secret(parameter_name):
    if parameter_name in _secret_cache:
        return _secret_cache[parameter_name]

    global _ssm_client
    if _ssm_client is None:
        import boto3

        _ssm_client = boto3.client("ssm")

    value = _ssm_client.get_parameter(
        Name=parameter_name,
        WithDecryption=True,
    )["Parameter"]["Value"]
    _secret_cache[parameter_name] = value
    return value


def send_discord(webhook_url, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    webhook_request = request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
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


def lambda_handler(event, context):
    headers = normalize_headers(event.get("headers") or {})
    expected_token = get_secret(os.environ["AUTH_TOKEN_PARAMETER_NAME"])
    provided_token = headers.get("x-landit-sentry-token", "")
    if not hmac.compare_digest(provided_token, expected_token):
        return response(401)

    try:
        payload = json.loads(decode_body(event))
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        return response(400)

    if not isinstance(payload, dict):
        return response(400)
    if extract_environment(payload) != "prod":
        return response(204)

    webhook_url = get_secret(os.environ["DISCORD_WEBHOOK_PARAMETER_NAME"])
    send_discord(webhook_url, build_discord_payload(payload))
    return response(204)
