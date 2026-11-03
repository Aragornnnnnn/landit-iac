# 썸네일 토큰 준비가 환경을 분리하고 기존 secret를 덮어쓰지 않는지 검증한다.
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

from botocore.exceptions import ClientError

spec = importlib.util.spec_from_file_location(
    "thumbnail_parameters", Path(__file__).parents[1] / "configure-roleplay-thumbnail-parameters.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ThumbnailParametersTests(unittest.TestCase):
    def test_check_never_creates_missing_token(self):
        ssm = Mock()
        ssm.get_parameter.side_effect = [
            {"Parameter": {"Type": "SecureString", "Value": "existing-key"}},
            ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter"),
        ]
        self.assertEqual(module.prepare(ssm, "develop"), "token_missing")
        ssm.put_parameter.assert_not_called()

    def test_apply_creates_only_missing_environment_token_without_overwrite(self):
        ssm = Mock()
        ssm.get_parameter.side_effect = [
            {"Parameter": {"Type": "SecureString", "Value": "existing-key"}},
            ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter"),
            {"Parameter": {"Type": "SecureString", "Value": "x" * 64}},
        ]
        self.assertEqual(module.prepare(ssm, "prod", apply=True), "ready")
        request = ssm.put_parameter.call_args.kwargs
        self.assertEqual(request["Name"], "/landit/prod/ROLEPLAY_THUMBNAIL_WORKER_TOKEN")
        self.assertFalse(request["Overwrite"])
        self.assertEqual(request["Type"], "SecureString")
        self.assertGreaterEqual(len(request["Value"]), 32)

    def test_existing_token_is_preserved_and_invalid_key_is_rejected(self):
        ssm = Mock()
        ssm.get_parameter.side_effect = [
            {"Parameter": {"Type": "SecureString", "Value": "existing-key"}},
            {"Parameter": {"Type": "SecureString", "Value": "x" * 64}},
        ]
        self.assertEqual(module.prepare(ssm, "develop", apply=True), "ready")
        ssm.put_parameter.assert_not_called()
        ssm.get_parameter.side_effect = None
        ssm.get_parameter.return_value = {"Parameter": {"Type": "String", "Value": "bad-key"}}
        with self.assertRaises(ValueError):
            module.prepare(ssm, "prod", apply=True)
        ssm.put_parameter.assert_not_called()
