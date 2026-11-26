# AI 배포의 라우팅 복구와 소비권 인계 및 재실행 동작을 검증한다.
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

module_path = Path(__file__).resolve().parents[1] / "deploy-worker.py"
spec = importlib.util.spec_from_file_location("deploy_worker", module_path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
BLUE = "sha256:" + "a" * 64
GREEN = "sha256:" + "b" * 64


class DrainTests(unittest.TestCase):
    def test_restart_loop_is_stopped_without_exec(self):
        state = {"Running": True, "Restarting": True, "StartedAt": "before"}
        with patch.object(worker, "container", return_value={"State": state}), patch.object(worker, "run") as run:
            worker.retire("green")
        run.assert_called_once_with("docker", "stop", "--time", "120", "landit-ai-green")


class DeployTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        state = root / "ai-rollout"
        state.mkdir()
        (state / "http.json").write_text(json.dumps(["blue", BLUE, ""]))
        (state / "consumer").write_text("blue")
        self.state = state
        self.slots = {"blue": self.info(BLUE)}
        self.routes = []
        self.retired = []
        self.ready = True
        self.low_memory = False
        self.bad_proxy = False
        self.interrupt_cleanup = False
        self.env_id = "env1"
        for name, replacement in {
            "restore_memory_budget": lambda slot: None, "memory_budget": lambda: "1000000000",
            "ROOT": root, "STATE": state, "container": self.slots.get,
            "launch": self.launch, "retire": self.retire, "route": self.route,
            "available": lambda: worker.RESERVE * 2,
            "check_memory": self.check_memory,
            "direct_ready": lambda slot: (slot == "blue" or self.ready),
            "wait": self.wait, "env_revision": lambda: self.env_id,
        }.items():
            mock = patch.object(worker, name, replacement)
            mock.start()
            self.addCleanup(mock.stop)

    def info(self, digest):
        return {"Config": {"Image": worker.REPO + "@" + digest, "Env": [],
                           "Labels": {"im.landit.ai-env": "env1"}}, "State": {"Running": True}}

    def launch(self, slot, digest):
        self.slots[slot] = self.info(digest)

    def retire(self, slot):
        if self.interrupt_cleanup and self.routes[-1] == "green" and slot == "blue":
            raise RuntimeError("drain timeout")
        if slot in self.slots and self.slots[slot]["State"]["Running"]:
            self.retired.append(slot)
            self.slots[slot]["State"]["Running"] = False

    def route(self, slot, digest):
        self.routes.append(slot)
        if self.bad_proxy and slot == "green":
            raise RuntimeError("public health mismatch")

    def check_memory(self, active):
        if self.low_memory:
            raise RuntimeError("memory")

    def wait(self, check, seconds, description):
        if not check():
            raise RuntimeError(description)

    def test_success_and_same_digest_retry(self):
        self.assertEqual(worker.deploy(GREEN), ("green", BLUE))
        self.assertEqual((self.state / "consumer").read_text().strip(), "green")
        self.assertEqual(self.retired, ["blue"])
        self.assertEqual(worker.deploy(GREEN), ("green", BLUE))
        self.assertEqual(self.retired, ["blue"])

    def test_changed_environment_restarts_same_digest(self):
        self.env_id = "updated"
        self.assertEqual(worker.deploy(BLUE), ("green", BLUE))

    def test_readiness_failure_preserves_current(self):
        self.ready = False
        with self.assertRaises(RuntimeError):
            worker.deploy(GREEN)
        self.assertEqual(self.routes, ["blue"])
        self.assertEqual(self.retired, ["green"])

    def test_proxy_failure_restores_route_before_retirement(self):
        self.bad_proxy = True
        with self.assertRaises(RuntimeError):
            worker.deploy(GREEN)
        self.assertEqual(self.routes, ["blue", "green", "blue"])
        self.assertEqual(self.retired, ["green"])
        self.assertEqual((self.state / "consumer").read_text().strip(), "blue")

    def test_committed_route_survives_interrupted_drain(self):
        self.interrupt_cleanup = True
        with self.assertRaisesRegex(RuntimeError, "drain timeout"):
            worker.deploy(GREEN)
        self.assertTrue(self.slots["blue"]["State"]["Running"])
        self.interrupt_cleanup = False
        self.assertEqual(worker.deploy(GREEN), ("green", BLUE))
        self.assertEqual(self.retired, ["blue"])

    def test_memory_gate_preserves_current(self):
        self.low_memory = True
        with self.assertRaisesRegex(RuntimeError, "memory"):
            worker.deploy(GREEN)
        self.assertEqual(set(self.slots), {"blue"})
        self.assertEqual(self.retired, [])

    def test_recovers_committed_slot_when_container_is_missing(self):
        self.slots.clear()
        self.assertEqual(worker.deploy(BLUE), ("blue", ""))
        self.assertEqual(self.slots["blue"]["Config"]["Image"], worker.REPO + "@" + BLUE)

    def test_failed_active_restores_retained_compatible_digest(self):
        worker.deploy(GREEN)
        self.ready = False
        def start(*args):
            if args == ("docker", "start", "landit-ai-blue"):
                self.slots["blue"]["State"]["Running"] = True
            elif args[:2] != ("docker", "update"):
                self.fail(args)
        with patch.object(worker, "run", start):
            self.assertEqual(worker.deploy(BLUE), ("blue", GREEN))
        self.assertEqual(self.routes[-1], "blue")
        self.assertEqual(self.retired[-1], "green")

    def test_running_legacy_consumer_requires_attestation(self):
        legacy = self.info(BLUE)
        legacy["Config"]["Env"] = ["ROLEPLAY_THUMBNAIL_CONSUMER_ENABLED=true"]
        self.slots["legacy"] = legacy
        with self.assertRaisesRegex(RuntimeError, "썸네일"):
            worker.guard_legacy()

    def test_caddy_migration_is_idempotent_and_rejects_unknown_directives(self):
        original = ("(ai) {\n reverse_proxy landit-ai:8000 {\n"
                    "  header_up X-Forwarded-For {client_ip}\n }\n}\n"
                    ":8081 {\n reverse_proxy landit-ai:8000\n}\n")
        updated = worker.migrate_config(original)
        self.assertEqual(updated.count(worker.IMPORT), 2)
        self.assertEqual(worker.migrate_config(updated), updated)
        with self.assertRaisesRegex(RuntimeError, "라우트"):
            worker.migrate_config(original.replace("header_up", "header_down"))
