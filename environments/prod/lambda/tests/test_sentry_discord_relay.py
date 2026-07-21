# Sentry 알림 relay Lambda의 인증, 필터링, Discord 변환을 검증한다.
import base64
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

    def valid_event(self, token="expected-token", environment="prod", base64_encoded=False):
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
        body = json.dumps(payload, ensure_ascii=False)
        if base64_encoded:
            body = base64.b64encode(body.encode("utf-8")).decode("ascii")

        return {
            "headers": {"X-Landit-Sentry-Token": token},
            "body": body,
            "isBase64Encoded": base64_encoded,
        }

    def test_lambda_handler_rejects_invalid_token(self):
        with (
            patch.object(relay, "get_secret", return_value="expected-token"),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(self.valid_event(token="wrong-token"), None)

        self.assertEqual(401, response["statusCode"])
        send_discord.assert_not_called()

    def test_lambda_handler_rejects_malformed_json(self):
        event = self.valid_event()
        event["body"] = "not-json"

        with (
            patch.object(relay, "get_secret", return_value="expected-token"),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(event, None)

        self.assertEqual(400, response["statusCode"])
        send_discord.assert_not_called()

    def test_lambda_handler_skips_non_prod_event(self):
        with (
            patch.object(relay, "get_secret", return_value="expected-token"),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(
                self.valid_event(environment="develop"),
                None,
            )

        self.assertEqual(204, response["statusCode"])
        send_discord.assert_not_called()

    def test_lambda_handler_skips_event_without_environment(self):
        event = self.valid_event()
        payload = json.loads(event["body"])
        del payload["data"]["event"]["environment"]
        event["body"] = json.dumps(payload, ensure_ascii=False)

        with (
            patch.object(relay, "get_secret", return_value="expected-token"),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(event, None)

        self.assertEqual(204, response["statusCode"])
        send_discord.assert_not_called()

    def test_lambda_handler_sends_prod_alert(self):
        secrets = {
            "auth-param": "expected-token",
            "discord-param": "https://discord.example/webhook",
        }

        with (
            patch.object(relay, "get_secret", side_effect=secrets.__getitem__),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(self.valid_event(), None)

        self.assertEqual(204, response["statusCode"])
        send_discord.assert_called_once()
        webhook_url, discord_payload = send_discord.call_args.args
        self.assertEqual("https://discord.example/webhook", webhook_url)
        embed = discord_payload["embeds"][0]
        self.assertIn("[PROD]", embed["title"])
        self.assertIn("BE", embed["title"])
        self.assertEqual("https://sentry.example/issues/1", embed["url"])
        self.assertIn("prod-be-new-regression", embed["description"])

    def test_lambda_handler_decodes_base64_body(self):
        secrets = {
            "auth-param": "expected-token",
            "discord-param": "https://discord.example/webhook",
        }

        with (
            patch.object(relay, "get_secret", side_effect=secrets.__getitem__),
            patch.object(relay, "send_discord") as send_discord,
        ):
            response = relay.lambda_handler(
                self.valid_event(base64_encoded=True),
                None,
            )

        self.assertEqual(204, response["statusCode"])
        send_discord.assert_called_once()


if __name__ == "__main__":
    unittest.main()
