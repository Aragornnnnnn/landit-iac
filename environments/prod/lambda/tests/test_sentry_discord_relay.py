# Sentry 알림 relay Lambda의 인증, 필터링, Discord 변환을 검증한다.
import base64
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).parents[1] / "sentry_discord_relay.py"
SPEC = importlib.util.spec_from_file_location("sentry_discord_relay", MODULE_PATH)
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)


class SentryDiscordRelayTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "AUTH_TOKEN_PARAMETER_NAME": "auth-param",
                "DISCORD_WEBHOOK_PARAMETER_NAME": "discord-param",
            },
            clear=True,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_get_secret_batches_configured_parameters(self):
        ssm_client = Mock()
        ssm_client.get_parameter.side_effect = AssertionError(
            "expected one batched get_parameters call"
        )
        ssm_client.get_parameters.return_value = {
            "Parameters": [
                {"Name": "auth-param", "Value": "expected-secret"},
                {"Name": "discord-param", "Value": "https://discord.example/webhook"},
            ]
        }

        with (
            patch.object(relay, "_ssm_client", ssm_client),
            patch.object(relay, "_secret_cache", {}),
        ):
            self.assertEqual("expected-secret", relay.get_secret("auth-param"))
            self.assertEqual(
                "https://discord.example/webhook",
                relay.get_secret("discord-param"),
            )

        ssm_client.get_parameters.assert_called_once_with(
            Names=["auth-param", "discord-param"],
            WithDecryption=True,
        )

    def test_send_discord_sets_explicit_user_agent(self):
        with patch.object(relay.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 204

            relay.send_discord(
                "https://discord.example/webhook",
                {"content": "test"},
            )

        webhook_request = urlopen.call_args.args[0]
        self.assertEqual(
            "Landit-Sentry-Relay/1.0",
            webhook_request.get_header("User-agent"),
        )

    def test_dispatch_delivery_invokes_same_lambda_asynchronously(self):
        lambda_client = Mock()
        lambda_client.invoke.return_value = {"StatusCode": 202}

        with patch.object(relay, "get_lambda_client", return_value=lambda_client):
            relay.dispatch_delivery("요청 본문", "a" * 64, "relay-arn")

        lambda_client.invoke.assert_called_once()
        invocation = lambda_client.invoke.call_args.kwargs
        self.assertEqual("relay-arn", invocation["FunctionName"])
        self.assertEqual("Event", invocation["InvocationType"])
        delivery = json.loads(invocation["Payload"])
        self.assertEqual("delivery", delivery["relayMode"])
        self.assertEqual("a" * 64, delivery["signature"])
        self.assertEqual(
            "요청 본문",
            base64.b64decode(delivery["bodyBase64"]).decode("utf-8"),
        )

    def valid_event(
        self,
        signing_secret="expected-secret",
        environment="prod",
        base64_encoded=False,
    ):
        payload = {
            "action": "triggered",
            "data": {
                "event": {
                    "project": "be-prod",
                    "environment": environment,
                    "title": "IllegalStateException: 테스트 장애",
                    "level": "error",
                    "web_url": "https://sentry.example/issues/1",
                    "metadata": {
                        "type": "IllegalStateException",
                        "value": "테스트 장애",
                    },
                },
                "triggered_rule": "prod-be-new-regression",
            },
        }
        raw_body = json.dumps(payload, ensure_ascii=False)
        signature = hmac.new(
            signing_secret.encode("utf-8"),
            raw_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        body = raw_body
        if base64_encoded:
            body = base64.b64encode(body.encode("utf-8")).decode("ascii")

        return {
            "headers": {"Sentry-Hook-Signature": signature},
            "body": body,
            "isBase64Encoded": base64_encoded,
            "requestContext": {"domainName": "relay.lambda-url.example"},
        }

    def delivery_event(
        self,
        signing_secret="expected-secret",
        environment="prod",
    ):
        ingress = self.valid_event(
            signing_secret=signing_secret,
            environment=environment,
        )
        return {
            "relayMode": "delivery",
            "bodyBase64": base64.b64encode(ingress["body"].encode("utf-8")).decode(
                "ascii"
            ),
            "signature": ingress["headers"]["Sentry-Hook-Signature"],
        }

    def test_ingress_dispatches_delivery_without_reading_secrets(self):
        event = self.valid_event()
        context = Mock(
            invoked_function_arn="arn:aws:lambda:region:account:function:relay"
        )

        with (
            patch.object(relay, "dispatch_delivery", create=True) as dispatch_delivery,
            patch.object(relay, "get_secret", return_value="expected-secret") as get_secret,
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(event, context)

        self.assertEqual(204, response["statusCode"])
        dispatch_delivery.assert_called_once_with(
            event["body"],
            event["headers"]["Sentry-Hook-Signature"],
            context.invoked_function_arn,
        )
        get_secret.assert_not_called()
        send_discord.assert_not_called()

    def test_ingress_rejects_invalid_signature_format(self):
        event = self.valid_event()
        event["headers"]["Sentry-Hook-Signature"] = "invalid"

        with (
            patch.object(relay, "dispatch_delivery", create=True) as dispatch_delivery,
            patch.object(relay, "get_secret", return_value="expected-secret"),
        ):
            response = relay.lambda_handler(
                event,
                Mock(invoked_function_arn="relay"),
            )

        self.assertEqual(401, response["statusCode"])
        dispatch_delivery.assert_not_called()

    def test_ingress_rejects_body_larger_than_async_limit(self):
        event = self.valid_event()
        event["body"] = "x" * 700_001
        event["headers"]["Sentry-Hook-Signature"] = "a" * 64

        with (
            patch.object(relay, "dispatch_delivery", create=True) as dispatch_delivery,
            patch.object(relay, "get_secret", return_value="expected-secret"),
        ):
            response = relay.lambda_handler(
                event,
                Mock(invoked_function_arn="relay"),
            )

        self.assertEqual(413, response["statusCode"])
        dispatch_delivery.assert_not_called()

    def test_delivery_rejects_invalid_sentry_signature(self):
        with (
            patch.object(relay, "get_secret", return_value="expected-secret"),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(
                self.delivery_event(signing_secret="wrong-secret"),
                None,
            )

        self.assertEqual(401, response["statusCode"])
        send_discord.assert_not_called()

    def test_delivery_rejects_malformed_json(self):
        raw_body = "not-json"
        event = {
            "relayMode": "delivery",
            "bodyBase64": base64.b64encode(raw_body.encode("utf-8")).decode("ascii"),
            "signature": hmac.new(
                b"expected-secret",
                raw_body.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest(),
        }

        with (
            patch.object(relay, "get_secret", return_value="expected-secret"),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(event, None)

        self.assertEqual(400, response["statusCode"])
        send_discord.assert_not_called()

    def test_delivery_skips_non_prod_event(self):
        with (
            patch.object(relay, "get_secret", return_value="expected-secret"),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(
                self.delivery_event(environment="develop"),
                None,
            )

        self.assertEqual(204, response["statusCode"])
        send_discord.assert_not_called()

    def test_delivery_skips_event_without_environment(self):
        event = self.delivery_event()
        raw_body = base64.b64decode(event["bodyBase64"]).decode("utf-8")
        payload = json.loads(raw_body)
        del payload["data"]["event"]["environment"]
        raw_body = json.dumps(payload, ensure_ascii=False)
        event["bodyBase64"] = base64.b64encode(raw_body.encode("utf-8")).decode(
            "ascii"
        )
        event["signature"] = hmac.new(
            b"expected-secret",
            raw_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        with (
            patch.object(relay, "get_secret", return_value="expected-secret"),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(event, None)

        self.assertEqual(204, response["statusCode"])
        send_discord.assert_not_called()

    def test_delivery_sends_prod_alert(self):
        secrets = {
            "auth-param": "expected-secret",
            "discord-param": "https://discord.example/webhook",
        }

        with (
            patch.object(relay, "get_secret", side_effect=secrets.__getitem__),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(self.delivery_event(), None)

        self.assertEqual(204, response["statusCode"])
        send_discord.assert_called_once()
        webhook_url, discord_payload = send_discord.call_args.args
        self.assertEqual("https://discord.example/webhook", webhook_url)
        embed = discord_payload["embeds"][0]
        self.assertIn("[PROD]", embed["title"])
        self.assertIn("BE", embed["title"])
        self.assertEqual("https://sentry.example/issues/1", embed["url"])
        self.assertIn("prod-be-new-regression", embed["description"])

    def test_ingress_decodes_base64_body_before_dispatch(self):
        event = self.valid_event(base64_encoded=True)
        expected_body = base64.b64decode(event["body"]).decode("utf-8")
        context = Mock(invoked_function_arn="relay")

        with (
            patch.object(relay, "dispatch_delivery", create=True) as dispatch_delivery,
            patch.object(relay, "get_secret", return_value="expected-secret"),
        ):
            response = relay.lambda_handler(event, context)

        self.assertEqual(204, response["statusCode"])
        dispatch_delivery.assert_called_once_with(
            expected_body,
            event["headers"]["Sentry-Hook-Signature"],
            context.invoked_function_arn,
        )

    def build_embed(self, event):
        payload = json.loads(self.valid_event()["body"])
        payload["data"]["event"].update(event)
        return relay.build_discord_payload(payload)["embeds"][0]

    def fields(self, embed):
        return {field["name"]: field["value"] for field in embed["fields"]}

    def test_ai_alert_shows_cause_request_and_app_location(self):
        embed = self.build_embed({
            "project": "ai-prod",
            "title": "APITimeoutError: Request timed out.",
            "exception": {"values": [
                {"type": "ReadTimeout", "value": "The read operation timed out"},
                {"type": "APITimeoutError", "value": "Request timed out.", "stacktrace": {"frames": [
                    {"filename": "app/handler.py", "function": "analyze", "lineno": 20, "in_app": True},
                    {"filename": "app/provider.py", "function": "generate", "lineno": 42, "in_app": True},
                    {"filename": "openai/client.py", "function": "request", "lineno": 1000, "in_app": False},
                ]}},
            ]},
            "request": {"method": "POST", "url": "http://ai.landit.im/api/v1/pronunciation/analyze"},
            "tags": [["provider", "openai"], ["error_code", "AI_GENERATION_FAILED"]],
            "timestamp": 0.5,
            "release": "abc123",
            "event_id": "event123",
            "contexts": {"trace": {"trace_id": "trace123"}},
        })
        fields = self.fields(embed)
        self.assertIn("[AI]", embed["title"])
        self.assertEqual("ReadTimeout: The read operation timed out\n→ APITimeoutError: Request timed out.", fields["예외 (원인 → 최종)"])
        self.assertEqual("POST http://ai.landit.im/api/v1/pronunciation/analyze", fields["요청"])
        stack = fields["앱 호출 위치 (오류 지점부터)"]
        self.assertLess(stack.index("generate"), stack.index("analyze"))
        self.assertIn("app/provider.py:42", stack)
        self.assertNotIn("openai/client.py", stack)
        self.assertIn("provider: openai", fields["처리 정보"])
        self.assertEqual("abc123", fields["릴리스"])
        self.assertIn("trace: trace123", fields["추적 ID"])
        self.assertEqual("1970-01-01T00:00:00.500000+00:00", embed["timestamp"])

    def test_be_api_event_and_webhook_show_same_stack(self):
        raw_exception = {"values": [{"type": "IllegalStateException", "value": "failure", "stacktrace": {"frames": [
            {"filename": "Controller.java", "function": "submit", "lineno": 30, "in_app": True},
            {"filename": "Service.java", "function": "save", "lineno": 80, "in_app": True},
        ]}}]}
        api_exception = json.loads(json.dumps(raw_exception).replace('"lineno"', '"lineNo"').replace('"in_app"', '"inApp"'))
        request_data = {"method": "POST", "url": "https://api.landit.im/api/v1/sessions"}
        webhook = self.build_embed({"exception": raw_exception, "request": request_data})
        api = self.build_embed({"entries": [
            {"type": "exception", "data": api_exception},
            {"type": "request", "data": request_data},
        ]})
        self.assertEqual(webhook, api)
        self.assertIn("Service.java:80", self.fields(api)["앱 호출 위치 (오류 지점부터)"])

    def test_library_only_stack_uses_inner_cause_throw_site(self):
        embed = self.build_embed({"exception": {"values": [
            {"type": "ReadTimeout", "stacktrace": {"frames": [
                {"filename": "httpcore/sync.py", "function": "read", "lineno": 126},
                {"filename": "httpcore/exceptions.py", "function": "map_exceptions", "lineno": 14},
            ]}},
            {"type": "APITimeoutError", "stacktrace": {"frames": [
                {"filename": "openai/client.py", "function": "request", "lineno": 1000},
            ]}},
        ]}})
        stack = self.fields(embed)["호출 경로 (오류 지점부터)"]
        self.assertLess(stack.index("map_exceptions"), stack.index("read"))
        self.assertNotIn("openai/client.py", stack)

    def test_missing_request_and_stack_are_explicit(self):
        fields = self.fields(self.build_embed({}))
        self.assertEqual("요청 경로 미수집", fields["요청"])
        self.assertEqual("스택 미수집", fields["호출 경로 (오류 지점부터)"])
        self.assertEqual("IllegalStateException: 테스트 장애", fields["예외 (원인 → 최종)"])
        self.assertNotIn("릴리스", fields)

    def test_endpoint_tag_is_used_without_guessing_http_method(self):
        for tags in ({"endpoint": "/api/analyze?token=secret"}, [{"key": "endpoint", "value": "/api/analyze?token=secret"}]):
            with self.subTest(tags=tags):
                fields = self.fields(self.build_embed({"tags": tags, "transaction": "analyze_job"}))
                self.assertEqual("/api/analyze", fields["요청"])
                self.assertIn("transaction: analyze_job", fields["처리 정보"])

    def test_sensitive_request_and_stack_data_are_not_forwarded(self):
        url = "https://username:password@api.landit.im/path?token=querysecret#fragmentsecret"
        embed = self.build_embed({
            "title": "Failure " + url,
            "request": {"url": url, "method": "POST", "data": "bodysecret", "headers": {"Authorization": "headersecret"}, "cookies": "cookiesecret"},
            "user": {"email": "usersecret@example.com"},
            "exception": {"values": [{"type": "Error", "value": "Bearer bearer-secret " + url, "stacktrace": {"frames": [
                {"filename": "app/client.py", "function": "call```", "lineno": 12, "in_app": True, "vars": {"key": "localsecret"}, "context_line": "sourcesecret"},
            ]}}]},
            "extra": {"payload": "extrasecret"},
            "tags": {"private": "tagsecret"},
        })
        rendered = json.dumps(embed)
        for secret in ("username", "password", "querysecret", "fragmentsecret", "bodysecret", "headersecret", "cookiesecret", "usersecret", "bearer-secret", "localsecret", "sourcesecret", "extrasecret", "tagsecret"):
            self.assertNotIn(secret, rendered)
        self.assertEqual("POST https://api.landit.im/path", self.fields(embed)["요청"])
        self.assertEqual(2, self.fields(embed)["앱 호출 위치 (오류 지점부터)"].count("```"))

    def test_long_multibyte_event_stays_within_discord_limits(self):
        long_text = "오류😀" * 6000
        embed = self.build_embed({
            "title": long_text, "project": long_text, "environment": long_text, "level": long_text,
            "release": {"version": long_text}, "event_id": long_text,
            "request": {"url": "https://example.com/" + long_text, "method": "POST"},
            "tags": {key: long_text for key in ("workflow", "provider", "model", "error_code", "status_code")},
            "transaction": long_text, "contexts": {"trace": {"trace_id": long_text}},
            "exception": {"values": [{"type": str(index), "value": long_text, "stacktrace": {"frames": [
                {"filename": long_text, "function": str(frame), "lineno": frame, "in_app": True} for frame in range(100)
            ]}} for index in range(10)]},
        })
        units = lambda value: len(value.encode("utf-16-le")) // 2
        self.assertLessEqual(units(embed["title"]), 256)
        self.assertLessEqual(len(embed["fields"]), 25)
        total = units(embed["title"]) + units(embed["description"])
        for field in embed["fields"]:
            self.assertTrue(field["value"])
            self.assertLessEqual(units(field["value"]), 1024)
            total += units(field["name"]) + units(field["value"])
        self.assertLessEqual(total, 6000)
        self.assertIn("9:", self.fields(embed)["예외 (원인 → 최종)"])

    def test_malformed_optional_details_do_not_break_alert(self):
        for value in (None, "invalid", 42, [], [None, "invalid"]):
            with self.subTest(value=value):
                embed = self.build_embed({"request": value, "exception": value, "entries": value, "tags": value, "contexts": value, "timestamp": "not-a-date"})
                self.assertEqual("요청 경로 미수집", self.fields(embed)["요청"])
                self.assertNotIn("timestamp", embed)

    def test_invalid_request_url_does_not_break_alert(self):
        for url in ("https://[invalid", "javascript:alert(1)"):
            with self.subTest(url=url):
                embed = self.build_embed({"request": {"url": url}, "web_url": url})
                self.assertNotIn("url", embed)
                self.assertEqual("요청 경로 미수집", self.fields(embed)["요청"])


if __name__ == "__main__":
    unittest.main()
