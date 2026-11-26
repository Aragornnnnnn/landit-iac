#!/usr/bin/env python3
# 운영 블루·그린 스크립트의 전환, 롤백, 재시도를 로컬에서 검증한다.
import json
import os
import pathlib
import subprocess
import tempfile
import unittest


ROLLOUT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "environments/prod/ec2-transition/rollout/deploy-api.sh"
)
OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64

MOCK = """#!/usr/bin/env python3
import json, os, pathlib, re, sys

root = pathlib.Path(os.environ["LANDIT_RUNTIME_DIR"])
state_file = root / "fake-state.json"
state = json.loads(state_file.read_text())
operation = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
registry = "944011958218.dkr.ecr.ap-northeast-2.amazonaws.com/prod-landit-api@"
with (root / "calls.log").open("a") as calls:
    print(operation, *args, file=calls)

if operation == "aws":
    print("test-password")
elif operation == "flock" and os.getenv("BLOCK_DEPLOYMENT"):
    sys.exit(1)
elif operation == "mv":
    if os.getenv("FAIL_ACTIVATION") and args[-1].endswith("/active-slot"):
        sys.exit(1)
    os.replace(args[-2], args[-1])
elif operation == "docker":
    action = args[0]
    name = args[-1]
    if action == "login":
        sys.stdin.read()
    elif action == "pull":
        pass
    elif action == "image" and args[1] == "inspect":
        print("slot-scheduling-v1")
    elif action == "image" and args[1] == "prune":
        pass
    elif action == "ps":
        if os.getenv("FAIL_INVENTORY"):
            sys.exit(1)
        name = args[args.index("--filter") + 1][7:-1]
        if name in state["slots"]:
            print(name)
    elif action == "inspect":
        if name == "landit-caddy":
            print("172.18.0.2")
            sys.exit(0)
        if name not in state["slots"]:
            sys.exit(1)
        if ".Config.Image" in " ".join(args):
            print(registry + state["slots"][name])
        elif ".State.Running" in " ".join(args):
            print("true" if name in state["running"] else "false")
    elif action == "exec":
        route = (root / "caddy/routes/api.caddy").read_text()
        match = re.search(r"reverse_proxy (landit-be-(blue|green)):8080", route)
        target = match.group(1) if match else None
        if os.getenv("FAIL_ROLLBACK") and state["proxy"] == "landit-be-green":
            sys.exit(1)
        state["proxy"] = target
    elif action == "start":
        if name not in state["running"]:
            state["running"].append(name)
    elif action == "stop":
        if os.getenv("ASSERT_HANDOFF") and name == "landit-be-blue":
            assert (root / "rollout-state/active-slot").read_text().strip() == "blue"
        state["running"].remove(name)
    elif action == "rm":
        del state["slots"][name]
    elif action == "run" and "--entrypoint" in args:
        sys.exit(1 if os.getenv("FAIL_MIGRATION") else 0)
    elif action == "run":
        name = args[args.index("--name") + 1]
        state["slots"][name] = args[-1].split("@")[-1]
        state["running"].append(name)
    else:
        sys.exit("Unexpected Docker command: " + str(args))
    state_file.write_text(json.dumps(state))
elif operation == "curl":
    url = args[-1]
    via_proxy = ":18080" in url or url.startswith("https://")
    if via_proxy:
        target = state["proxy"]
        if target == "landit-be-blue" and os.getenv("FAIL_PREVIOUS"):
            sys.exit(1)
        if url.startswith("https://") and os.getenv("FAIL_PUBLIC"):
            sys.exit(1)
    else:
        target = "landit-be-blue" if ":18081" in url else "landit-be-green"
        if os.getenv("FAIL_HEALTH"):
            sys.exit(1)
    if target not in state["running"]:
        sys.exit(1)
    header = "X-Landit-Image-Digest: " + state["slots"][target] if via_proxy else ""
    pathlib.Path(args[args.index("-D") + 1]).write_text(header + "\\r\\n")
    pathlib.Path(args[args.index("-o") + 1]).write_text('{"status":"UP"}')
"""


class ProductionRolloutTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / "caddy/routes").mkdir(parents=True)
        (self.root / "rollout-state").mkdir()
        self.active = self.root / "rollout-state/active-slot"
        self.active.write_text("blue\n")
        self.route = self.root / "caddy/routes/api.caddy"
        self.route.write_text(
            f"reverse_proxy landit-be-blue:8080 {{\n"
            "  header_up X-Forwarded-For {client_ip}\n"
            f"  header_down X-Landit-Image-Digest {OLD}\n  stream_close_delay 2m\n}}\n"
        )
        self.original_route = self.route.read_text()
        (self.root / "scheduler.lock").touch()
        (self.root / "rds-ca.pem").write_text("test-ca")
        (self.root / "rds-cacerts").write_text("test-java-ca")
        credentials = self.root / "aws/api"
        credentials.mkdir(parents=True)
        (credentials / "config").write_text("[default]")
        (credentials / "credentials.json").write_text('{"Expiration":"2099-01-01T00:00:00Z"}')
        db_url = "DB_URL=jdbc:postgresql://example.rds.amazonaws.com:5432/landit?sslmode=verify-full\n"
        for name in ("api.env", "migration.env"):
            (self.root / name).write_text(db_url)
        self.state_file = self.root / "fake-state.json"
        self.state_file.write_text(
            json.dumps(
                {"slots": {"landit-be-blue": OLD}, "proxy": "landit-be-blue", "running": ["landit-be-blue"]}
            )
        )
        mock = self.root / "fake-command"
        mock.write_text(MOCK)
        mock.chmod(0o755)
        (self.root / "bin").mkdir()
        for command in ("aws", "docker", "curl", "flock", "sleep", "mv"):
            (self.root / "bin" / command).symlink_to(mock)

    def deploy(self, digest=NEW, *args, **flags):
        return subprocess.run(
            ["bash", str(ROLLOUT), digest, *args],
            env={
                **os.environ,
                "PATH": f"{self.root}/bin:{os.environ['PATH']}",
                "LANDIT_RUNTIME_DIR": str(self.root),
                **flags,
            },
            capture_output=True,
            text=True,
            timeout=30,
        )

    def assert_running(self, *slots):
        self.assertEqual(json.loads(self.state_file.read_text())["running"], list(slots))

    def test_rollout_checks_proxy_before_stopping_blue(self):
        result = self.deploy(ASSERT_HANDOFF="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("active_slot=green", result.stdout)
        self.assertIn(f"previous_image_digest={OLD}", result.stdout)
        self.assertEqual(self.active.read_text(), "green\n")
        self.assert_running("landit-be-green")
        calls = (self.root / "calls.log").read_text()
        for mount in ("aws/api,dst=/run/landit-aws,readonly", "rds-cacerts,dst=/run/landit/rds-cacerts,readonly"):
            self.assertIn(mount, calls)
        self.assertLess(calls.index("https://api.landit.im"), calls.index("stop --time 120"))

    def test_unhealthy_candidate_leaves_previous_route_in_place(self):
        self.assertNotEqual(self.deploy(FAIL_HEALTH="1").returncode, 0)
        self.assertEqual(self.route.read_text(), self.original_route)
        self.assertEqual(self.active.read_text(), "blue\n")
        self.assert_running("landit-be-blue")

    def test_new_image_can_recover_an_unhealthy_active_slot(self):
        result = self.deploy(FAIL_PREVIOUS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("active_slot=green", result.stdout)
        self.assert_running("landit-be-green")

    def test_rollout_recovers_when_previous_container_is_missing(self):
        self.state_file.write_text(json.dumps({"slots": {}, "proxy": "landit-be-blue", "running": []}))
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"previous_image_digest={OLD}", result.stdout)
        self.assert_running("landit-be-green")

    def test_failed_public_probe_restores_previous_route(self):
        self.assertNotEqual(self.deploy(FAIL_PUBLIC="1").returncode, 0)
        self.assertEqual(self.route.read_text(), self.original_route)
        self.assertEqual(json.loads(self.state_file.read_text())["proxy"], "landit-be-blue")
        self.assertEqual(self.active.read_text(), "blue\n")
        self.assert_running("landit-be-blue")

    def test_inventory_failure_cannot_activate_the_candidate(self):
        self.assertNotEqual(self.deploy(FAIL_INVENTORY="1").returncode, 0)
        self.assertEqual(self.active.read_text(), "blue\n")
        self.assert_running("landit-be-blue")

    def test_activation_failure_restarts_the_stopped_previous_slot(self):
        self.assertNotEqual(self.deploy(FAIL_ACTIVATION="1").returncode, 0)
        self.assertEqual(self.route.read_text(), self.original_route)
        self.assertEqual(self.active.read_text(), "blue\n")
        self.assert_running("landit-be-blue")

    def test_failed_rollback_keeps_both_containers_for_recovery(self):
        result = self.deploy(FAIL_PUBLIC="1", FAIL_ROLLBACK="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("두 슬롯을 유지합니다", result.stderr)
        self.assert_running("landit-be-blue", "landit-be-green")

    def test_running_same_release_does_not_rebuild_or_migrate(self):
        result = self.deploy(OLD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("docker pull", (self.root / "calls.log").read_text())
        self.assert_running("landit-be-blue")

    def test_migration_failure_never_starts_new_slot(self):
        self.assertNotEqual(self.deploy(FAIL_MIGRATION="1").returncode, 0)
        self.assertEqual(self.route.read_text(), self.original_route)
        self.assert_running("landit-be-blue")

    def test_deployment_lock_prevents_parallel_routine(self):
        self.assertNotEqual(self.deploy(BLOCK_DEPLOYMENT="1").returncode, 0)
        self.assertEqual((self.root / "calls.log").read_text().strip(), "flock -n 9")

    def test_first_deployment_can_activate_blue(self):
        self.active.write_text("none\n")
        self.route.write_text("respond 503\n")
        self.state_file.write_text(json.dumps({"slots": {}, "proxy": None, "running": []}))
        self.assertNotEqual(self.deploy().returncode, 0)
        result = self.deploy(NEW, "--bootstrap", FAIL_PUBLIC="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("active_slot=blue", result.stdout)
        self.assert_running("landit-be-blue")
        self.assertNotIn("https://api.landit.im", (self.root / "calls.log").read_text())

    def test_different_flyway_database_fails_before_docker(self):
        migration_env = self.root / "migration.env"
        migration_env.write_text(migration_env.read_text().replace("example.", "other."))
        result = self.deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("같은 운영 RDS", result.stderr)
        self.assertEqual((self.root / "calls.log").read_text().strip(), "flock -n 9")


if __name__ == "__main__":
    unittest.main()
