# 운영 이미지 캡처가 혼합 배포와 오래된 Terraform plan을 거부하는지 검증한다.
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("capture", Path(__file__).parents[1] / "capture-prod-images.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureProdImagesTest(unittest.TestCase):
    def setUp(self):
        self.mode = "stable"

    def aws(self, *args):
        operation = args[1]
        if operation == "describe-task-definition":
            secrets = [{"name": "LANDIT_CONTENT_AUTHORING_ASSETS_ENABLED"}]
            if self.mode != "partial-authoring":
                secrets.append({"name": "LANDIT_CONTENT_AUTHORING_PUBLISH_ENABLED"})
            return {"taskDefinition": {"containerDefinitions": [{"name": "api",
                "environment": [{"name": "LANDIT_REVENUECAT_APPLY_SANDBOX_EVENTS", "value": "false"}],
                "secrets": secrets if self.mode in ("authoring-enabled", "partial-authoring") else []}]}}
        if operation == "describe-services":
            name = args[-1]
            return {"services": [{"desiredCount": 1, "runningCount": 1, "pendingCount": 0,
                                  "taskDefinition": name + ":2",
                                  "deployments": [{"id": name + "-deployment", "rolloutState":
                                      "IN_PROGRESS" if self.mode == "deploying" else "COMPLETED"}]}]}
        if operation == "list-tasks":
            return {"taskArns": [args[5] + "-task"]}
        name = args[-1].removesuffix("-task")
        container = name.removeprefix("prod-landit-")
        digest = "" if self.mode == "no-digest" else "sha256:" + "a" * 64
        return {"tasks": [{"lastStatus": "RUNNING",
                            "taskDefinitionArn": name + (":1" if self.mode == "old-task" else ":2"),
                            "containers": [{"name": container, "imageDigest": digest,
                                "image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/" + name + ":latest"}]}]}

    def test_pins_actual_running_digest_even_when_task_definition_uses_latest(self):
        with patch.object(capture, "aws", self.aws):
            actual = capture.snapshot()
        self.assertTrue(actual["api"]["image_ref"].endswith("@sha256:" + "a" * 64))
        self.assertEqual(actual["api"]["task_definition"], "prod-landit-api:2")

    def test_rejects_unstable_or_uninspectable_task(self):
        for mode in ("deploying", "old-task", "no-digest"):
            with self.subTest(mode=mode), patch.object(capture, "aws", self.aws):
                self.mode = mode
                with self.assertRaises(ValueError):
                    capture.snapshot()

    def test_rejects_deployment_change_during_capture(self):
        calls = 0
        def changing_aws(*args):
            nonlocal calls
            response = self.aws(*args)
            if args[1] == "describe-services":
                calls += 1
                if calls == 2:
                    response["services"][0]["deployments"][0]["id"] = "new-deployment"
            return response
        with patch.object(capture, "aws", changing_aws), self.assertRaises(ValueError):
            capture.snapshot()

    def test_apply_rejects_new_deployment_or_overridden_image(self):
        with patch.object(capture, "aws", self.aws):
            actual = capture.snapshot()
        with patch.object(capture, "aws", self.aws):
            plan = {"variables": {name: {"value": value} for name, value in capture.inputs(actual).items()}}
        capture.verify(plan, actual)
        changed = copy.deepcopy(actual)
        changed["api"]["deployment_id"] = "new-deployment"
        with self.assertRaises(ValueError):
            capture.verify(plan, changed)
        plan["variables"]["api_image_ref"]["value"] = "different-image"
        with self.assertRaises(ValueError):
            capture.verify(plan, actual)

    def test_preserves_existing_runtime_switches_instead_of_defaults(self):
        for mode, expected in (("stable", False), ("authoring-enabled", True)):
            with self.subTest(mode=mode), patch.object(capture, "aws", self.aws):
                self.mode = mode
                values = capture.inputs(capture.snapshot())
                self.assertFalse(values["revenuecat_apply_sandbox_events"])
                self.assertEqual(values["content_authoring_configuration_enabled"], expected)

    def test_partial_authoring_configuration_fails_closed(self):
        self.mode = "partial-authoring"
        with patch.object(capture, "aws", self.aws), self.assertRaises(ValueError):
            capture.inputs(capture.snapshot())


if __name__ == "__main__":
    unittest.main()
