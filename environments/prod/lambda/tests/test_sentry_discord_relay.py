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


if __name__ == "__main__":
    unittest.main()
