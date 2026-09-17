# Sentry issue alert를 검증해 prod Discord 장애 채널로 전달한다.
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from urllib import parse, request


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
    encoded = text.encode("utf-16-le", errors="replace")
    if len(encoded) <= limit * 2:
        return text
    return encoded[: (limit - 1) * 2].decode("utf-16-le", errors="ignore") + "…"


def safe_url(value):
    try:
        url = parse.urlsplit(str(value or ""))
        if url.scheme not in ("", "http", "https"):
            return ""
        # 요청 식별에 필요 없는 인증 정보, 쿼리, fragment는 전달하지 않는다.
        host = url.netloc.rsplit("@", 1)[-1]
        return parse.urlunsplit((url.scheme, host, url.path, "", ""))
    except ValueError:
        return ""


def display_text(value):
    text = re.sub(
        r"https?://[^\s<>\"']+", lambda match: safe_url(match[0]), str(value or "")
    )
    text = re.sub(r"(?i)\bBearer\s+[\w./+=-]+", "Bearer [Filtered]", text)
    return text.replace("`", "'")


def event_tags(event):
    tags = event.get("tags")
    if isinstance(tags, dict):
        return tags
    result = {}
    for tag in tags if isinstance(tags, list) else []:
        if isinstance(tag, dict) and isinstance(tag.get("key"), str):
            result[tag["key"]] = tag.get("value")
        elif isinstance(tag, (list, tuple)) and len(tag) == 2 and isinstance(tag[0], str):
            result[tag[0]] = tag[1]
    return result


def event_interface(event, name):
    interface = event.get(name)
    if isinstance(interface, dict):
        return interface
    # webhook 원본과 Sentry API의 entries 형식을 모두 지원한다.
    entries = event.get("entries")
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and entry.get("type") == name:
            data = entry.get("data")
            if isinstance(data, dict):
                return data
    return {}


def exception_values(event):
    values = event_interface(event, "exception").get("values")
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def exception_summary(event, exceptions):
    metadata = event.get("metadata")
    values = exceptions or ([metadata] if isinstance(metadata, dict) else [])
    lines = []
    for value in values:
        line = ": ".join(str(value[key]) for key in ("type", "value") if value.get(key))
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    if len(lines) > 4:
        lines = lines[:2] + ["… 중간 예외 생략 …"] + lines[-2:]
    summary = "\n→ ".join(truncate(display_text(line), 240) for line in lines)
    return summary or "예외 상세 미수집"


def stack_frames(interface):
    stack = interface.get("stacktrace")
    frames = stack.get("frames") if isinstance(stack, dict) else None
    if not isinstance(frames, list):
        return []
    return [frame for frame in frames if isinstance(frame, dict)]


def stack_summary(event, exceptions):
    app_frames = []
    for exception in reversed(exceptions):
        for frame in reversed(stack_frames(exception)):
            if frame.get("in_app") is True or frame.get("inApp") is True:
                app_frames.append(frame)
    frames = app_frames
    if not frames:
        # 앱 프레임이 없으면 가장 안쪽 원인 예외의 throw 위치부터 보여준다.
        for exception in exceptions:
            frames = list(reversed(stack_frames(exception)))
            if frames:
                break
    if not frames:
        frames = list(reversed(stack_frames(event)))
    lines = []
    for frame in frames:
        filename = frame.get("filename") or frame.get("module") or "unknown"
        line_number = frame.get("lineno") or frame.get("lineNo")
        location = f"{filename}:{line_number}" if line_number else str(filename)
        function = frame.get("function") or "<unknown>"
        line = truncate(display_text(f"{function}  {location}"), 180)
        if line not in lines:
            lines.append(line)
        if len(lines) == 5:
            break
    label = "앱 호출 위치 (오류 지점부터)" if app_frames else "호출 경로 (오류 지점부터)"
    summary = "```\n" + "\n".join(lines) + "\n```" if lines else "스택 미수집"
    return label, summary


def event_timestamp(event):
    value = event.get("timestamp")
    if value is None:
        value = event.get("dateCreated")
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)) or str(value).replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


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
    level = event.get("level") or "error"
    tags = event_tags(event)
    exceptions = exception_values(event)

    embed = {
        "title": truncate(display_text(f"[PROD][{service_label(project)}] {title}"), 256),
        "description": "**알림 규칙** " + truncate(display_text(rule_name), 180),
        "color": 15158332,
        "fields": [],
    }

    def add_field(name, value, limit=1024, inline=False):
        if value:
            embed["fields"].append(
                {"name": name, "value": truncate(value, limit), "inline": inline}
            )

    # 모든 선택 필드가 있어도 Discord embed 전체 6,000자 한도 안에 머문다.
    add_field("프로젝트", display_text(project), 80, True)
    add_field("환경", display_text(environment), 40, True)
    add_field("레벨", display_text(level), 20, True)
    add_field("예외 (원인 → 최종)", exception_summary(event, exceptions))
    request_data = event_interface(event, "request")
    endpoint = safe_url(
        request_data.get("url") or tags.get("endpoint") or tags.get("http.route")
    )
    method = request_data.get("method") or tags.get("http.method")
    request_text = " ".join(str(value) for value in (method, endpoint) if value)
    add_field("요청", display_text(request_text) if endpoint else "요청 경로 미수집", 768)
    stack_label, stack = stack_summary(event, exceptions)
    add_field(stack_label, stack)
    details = []
    for key in ("workflow", "provider", "model", "error_code", "status_code"):
        if tags.get(key):
            details.append(f"{key}: {truncate(display_text(tags[key]), 120)}")
    if event.get("transaction"):
        details.append("transaction: " + truncate(display_text(event["transaction"]), 120))
    add_field("처리 정보", "\n".join(details), 768)
    release = event.get("release") or tags.get("release")
    if isinstance(release, dict):
        release = release.get("version")
    add_field("릴리스", display_text(release), 120)
    contexts = event.get("contexts")
    trace = contexts.get("trace") if isinstance(contexts, dict) else None
    identifiers = []
    if isinstance(trace, dict) and trace.get("trace_id"):
        identifiers.append("trace: " + truncate(display_text(trace["trace_id"]), 64))
    event_id = event.get("event_id") or event.get("eventID")
    if event_id:
        identifiers.append("event: " + truncate(display_text(event_id), 64))
    add_field("추적 ID", "\n".join(identifiers), 160)
    timestamp = event_timestamp(event)
    if timestamp:
        embed["timestamp"] = timestamp
    link = safe_url(issue_url)
    if link.startswith(("https://", "http://")):
        embed["url"] = link

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
