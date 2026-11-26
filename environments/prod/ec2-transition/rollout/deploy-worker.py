# 운영 AI의 HTTP 슬롯과 썸네일 소비권을 각각 검증하고 인계한다.
from datetime import datetime
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(os.environ.get("LANDIT_RUNTIME_DIR", "/opt/landit"))
STATE = ROOT / "ai-rollout"
CADDY = ROOT / "caddy"
ROUTE = CADDY / "routes/ai.caddy"
REGISTRY = "944011958218.dkr.ecr.ap-northeast-2.amazonaws.com"
REPO = REGISTRY + "/prod-landit-worker"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
NAMES = {"blue": "landit-ai-blue", "green": "landit-ai-green", "legacy": "landit-ai"}
PORTS = {"blue": 18085, "green": 18086}
IMPORT = "import /etc/caddy/routes/ai.caddy"
RESERVE = 384 * 1024 * 1024


def run(*args, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, **kwargs).stdout.decode().strip()


def put(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write((content.rstrip() + "\n").encode())
    os.chmod(tmp.name, 0o644)
    os.replace(tmp.name, path)


def wait(check, seconds, description):
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() >= deadline:
            raise RuntimeError(description)
        time.sleep(2)


def container(slot):
    name = NAMES[slot]
    if name not in run("docker", "ps", "-a", "--format", "{{.Names}}").splitlines():
        return None
    return json.loads(run("docker", "inspect", name))[0]


def image_digest(info):
    repo, _, digest = info["Config"]["Image"].partition("@")
    if repo != REPO or not DIGEST.fullmatch(digest):
        raise RuntimeError("기존 AI 이미지의 저장소와 다이제스트를 확인하세요.")
    return digest


def enabled(info):
    values = {key.upper(): value for key, value in (entry.split("=", 1) for entry in info["Config"]["Env"])}
    return values.get("ROLEPLAY_THUMBNAIL_CONSUMER_ENABLED", "false").lower() in {"true", "1", "yes", "on", "t", "y"}


def migrate_config(config):
    pattern = (r"(?m)^([ \t]*)reverse_proxy landit-ai:8000(?:[ \t]*\{\n"
               r"[ \t]*header_up X-Forwarded-For \{client_ip\}\n[ \t]*\})?[ \t]*$")
    if config.count(IMPORT) == 2 and "reverse_proxy landit-ai:8000" not in config:
        return config
    changed, count = re.subn(pattern, lambda m: m[1] + IMPORT, config)
    if count != 2 or changed.count(IMPORT) != 2 or "reverse_proxy landit-ai:8000" in changed:
        raise RuntimeError("운영 Caddy의 AI 라우트 두 곳을 확인하세요.")
    return changed


def health(url, digest=None, slot=None):
    try:
        with urlopen(url, timeout=3) as reply:
            return (reply.status == 200 and json.load(reply).get("status") == "ok"
                    and (digest is None or reply.headers.get("X-Landit-Image-Digest") == digest)
                    and (slot is None or reply.headers.get("X-Landit-AI-Slot") == slot))
    except (OSError, ValueError):
        return False


def route(slot, digest):
    content = "respond 503" if slot == "none" else (
        f"reverse_proxy {NAMES[slot]}:8000 {{\n"
        f" header_up X-Forwarded-For {{client_ip}}\n header_down X-Landit-Image-Digest {digest}\n"
        f" header_down X-Landit-AI-Slot {slot}\n stream_close_delay 15m\n}}")
    put(ROUTE, content)
    conf = CADDY / "Caddyfile"
    original = conf.read_text()
    updated = migrate_config(original)
    if updated != original:
        put(conf, updated)
    try:
        run("docker", "exec", "landit-caddy", "caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile")
    except subprocess.CalledProcessError:
        if updated != original:
            put(conf, original)
        raise
    if slot != "none":
        for url in ("http://127.0.0.1:18080/health", "https://ai.landit.im/health"):
            wait(lambda: health(url, digest, slot), 30, "Caddy 슬롯 확인 실패 " + url)


def available():
    match = re.search(r"^MemAvailable:\s+(\d+) kB", Path("/proc/meminfo").read_text(), re.M)
    return int(match[1]) * 1024


def memory_used(slot):
    info = container(slot)
    if not info or not info["State"]["Running"] or info["State"].get("Restarting"):
        return 0
    path = Path("/sys/fs/cgroup/system.slice") / ("docker-" + info["Id"] + ".scope/memory.current")
    if path.exists():
        return int(path.read_text())
    return int(run("docker", "exec", NAMES[slot], "cat", "/sys/fs/cgroup/memory.current"))


def check_memory(active):
    working = memory_used(active) if active != "none" else 0
    if available() < max(768 * 1024 * 1024, working) + RESERVE:
        raise RuntimeError("두 AI 슬롯을 함께 실행할 가용 메모리가 부족합니다.")


# Docker의 격리된 네트워크에서 8000번 포트의 기존 연결이 닫힌 뒤에만 종료한다.
SOCKETS = """from pathlib import Path
ports = (Path('/proc/net/tcp'), Path('/proc/net/tcp6'))
rows = [line.split() for table in ports if table.exists() for line in table.read_text().splitlines()[1:]]
print(sum(r[1].endswith(':1F40') and r[3] not in {'0A','06','07'} for r in rows))
"""


def retire(slot):
    info = container(slot)
    if not info or not info["State"]["Running"]:
        return
    started = info["State"]["StartedAt"]

    def drained():
        state = container(slot)["State"]
        if state.get("Restarting") or not state["Running"] or state["StartedAt"] != started:
            return True
        try:
            return run("docker", "exec", NAMES[slot], "python", "-c", SOCKETS) == "0"
        except subprocess.CalledProcessError:
            # 다음 조회에서 컨테이너 재시작과 일시적인 exec 실패를 구분한다.
            return False

    wait(drained, 720, "기존 HTTP 연결이 남아 두 슬롯을 유지합니다.")
    run("docker", "stop", "--time", "120", NAMES[slot])


def consumer_timeout(_signum, _frame):
    raise TimeoutError("이전 소비자 작업이 남아 두 슬롯을 유지합니다.")


def handoff(active):
    owner = (STATE / "consumer").read_text().strip()
    if owner == active:
        return
    if owner in PORTS:
        with (STATE / (owner + ".lock")).open("rb") as lock:
            handler = signal.signal(signal.SIGALRM, consumer_timeout)
            signal.alarm(720)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, handler)
            put(STATE / "consumer", active)
    elif owner == "legacy":
        guard_legacy()
        retire(owner)
        put(STATE / "consumer", active)
        (STATE / "legacy-consumer-drained").unlink(missing_ok=True)
    elif owner == "none":
        put(STATE / "consumer", active)
    else:
        raise RuntimeError("AI 소비 슬롯 기록을 확인하세요.")


def guard_legacy():
    info = container("legacy")
    if info and info["State"]["Running"] and enabled(info):
        marker = STATE / "legacy-consumer-drained"
        if not (marker.is_file() and marker.stat().st_uid == 0 and
                marker.read_text().strip() == info["Id"] and time.time() - marker.stat().st_mtime < 1800):
            raise RuntimeError("기존 썸네일 작업을 비우고 운영 절차에 따라 인계를 승인하세요.")


def cleanup(active):
    handoff(active)
    for slot in NAMES:
        if slot != active:
            retire(slot)


def restore_memory_budget(slot):
    # 이전 AI가 해제한 메모리를 새 활성 슬롯이 다시 사용할 수 있게 한다.
    info = container(slot)
    allocated = info["HostConfig"]["Memory"]
    limit = memory_used(slot) + available() - RESERVE
    if allocated and limit > allocated + 64 * 1024 * 1024:
        run("docker", "update", "--memory", str(limit), "--memory-swap", str(limit), NAMES[slot])


def direct_ready(slot):
    if not health(f"http://127.0.0.1:{PORTS[slot]}/health"):
        return False
    info = container(slot)
    if not info or not info["State"]["Running"]:
        return False
    if enabled(info):
        return subprocess.run(["docker", "exec", NAMES[slot], "test", "-f",
                               "/tmp/landit-thumbnail-ready"]).returncode == 0
    return True


def env_revision():
    return hashlib.sha256((ROOT / "ai.env").read_bytes()).hexdigest()


def memory_budget():
    budget = available() - RESERVE
    if budget < 768 * 1024 * 1024:
        raise RuntimeError("후보 슬롯을 기동할 메모리가 부족합니다.")
    return str(budget)


def launch(slot, digest):
    name = NAMES[slot]
    if container(slot):
        run("docker", "rm", name)  # retire가 먼저 완료된 슬롯만 재사용한다.
    credentials = ROOT / "aws/ai"
    limit = memory_budget()
    run("docker", "run", "-d", "--memory", limit, "--memory-swap", limit, "--name", name, "--network", "landit-prod", "--restart", "unless-stopped",
        "-p", f"127.0.0.1:{PORTS[slot]}:8000", "--env-file", str(ROOT / "ai.env"),
        "--label", "im.landit.ai-env=" + env_revision(),
        "-e", "LANDIT_AI_SLOT=" + slot, "-e", "AWS_CONFIG_FILE=/run/landit-aws/config",
        "-e", "AWS_SHARED_CREDENTIALS_FILE=/dev/null", "-e", "AWS_PROFILE=default",
        "-e", "AWS_EC2_METADATA_DISABLED=true",
        "--mount", f"type=bind,src={credentials},dst=/run/landit-aws,readonly",
        "--mount", f"type=bind,src={STATE},dst=/run/landit-ai-rollout,readonly",
        "--log-opt", "max-size=10m", "--log-opt", "max-file=3", REPO + "@" + digest)


def deploy(digest):
    STATE.mkdir(mode=0o755, exist_ok=True)
    for slot in PORTS:
        (STATE / (slot + ".lock")).touch(mode=0o644, exist_ok=True)
    record = STATE / "http.json"
    if not record.exists():
        if any(container(slot) for slot in PORTS):
            raise RuntimeError("활성 AI 슬롯 기록이 필요합니다.")
        old = container("legacy")
        all_names = run("docker", "ps", "-a", "--format", "{{.Names}}").splitlines()
        if "landit-ai-previous" in all_names and (not old or
                json.loads(run("docker", "inspect", "landit-ai-previous"))[0]["State"]["Running"]):
            raise RuntimeError("기존 단일 슬롯 배포의 복구를 먼저 완료하세요.")
        if old and not old["State"]["Running"]:
            raise RuntimeError("기존 AI 컨테이너 상태를 먼저 복구하세요.")
        active = "legacy" if old else "none"
        put(STATE / "consumer", active)
        put(record, json.dumps([active, image_digest(old) if old else "", ""]))
    active, current, previous = json.loads(record.read_text())
    try:
        if active != "none":
            info = container(active)
            if info is None:
                if active == "legacy":
                    raise RuntimeError("기존 단일 슬롯을 복구하세요.")
                check_memory("none")
                launch(active, current)
            elif image_digest(info) != current:
                raise RuntimeError("활성 슬롯 기록과 컨테이너 이미지가 일치하지 않습니다.")
            elif not info["State"]["Running"]:
                run("docker", "start", NAMES[active])
        # 전환 직후 중단돼도 마지막으로 커밋한 HTTP 경로를 복구한 뒤에만 슬롯을 재사용한다.
        route(active, current)
        if active in PORTS:
            wait(lambda: direct_ready(active), 120, "현재 슬롯의 HTTP 또는 소비자가 준비되지 않았습니다.")
    except Exception:
        if active not in PORTS or previous != digest or current == digest:
            raise
        # 손상된 활성 슬롯 때문에 직전 호환 버전으로 되돌리는 경로가 막히지 않도록 한다.
        fallback = "green" if active == "blue" else "blue"
        backup = container(fallback)
        if not backup or image_digest(backup) != previous:
            raise
        if not backup["State"]["Running"]:
            check_memory("none")
            limit = memory_budget()
            run("docker", "update", "--memory", limit, "--memory-swap", limit, NAMES[fallback])
            run("docker", "start", NAMES[fallback])
        wait(lambda: direct_ready(fallback), 120, "보존한 직전 슬롯이 준비되지 않았습니다.")
        route(fallback, previous)
        put(record, json.dumps([fallback, previous, current]))
        cleanup(fallback)
        restore_memory_budget(fallback)
        return fallback, current
    if active in PORTS:
        cleanup(active)
        if digest == current and container(active)["Config"]["Labels"].get("im.landit.ai-env") == env_revision():
            restore_memory_budget(active)
            return active, previous
    elif active == "legacy":
        guard_legacy()
    candidate = "green" if active == "blue" else "blue"
    retire(candidate)
    check_memory(active)
    try:
        launch(candidate, digest)
        wait(lambda: direct_ready(candidate), 120, "새 AI HTTP 또는 썸네일 준비 실패")
        info = container(candidate)
        if image_digest(info) != digest or available() < RESERVE:
            raise RuntimeError("후보 AI 다이제스트 또는 메모리 여유를 확인하세요.")
        if active == "none" and enabled(info):
            raise RuntimeError("최초 기동 전 ai.env의 큐 소비를 끄고 기존 소비자를 확인하세요.")
    except Exception:
        retire(candidate)
        raise
    try:
        route(candidate, digest)
        if not direct_ready(candidate) or available() < RESERVE:
            raise RuntimeError("전환 후 새 슬롯 준비 상태 또는 메모리 여유가 부족합니다.")
        put(record, json.dumps([candidate, digest, current]))
    except Exception:
        route(active, current)
        retire(candidate)
        raise
    cleanup(candidate)
    restore_memory_budget(candidate)
    if not direct_ready(candidate):
        raise RuntimeError("인계 후 AI 슬롯 상태를 확인하세요.")
    return candidate, current


if __name__ == "__main__":
    digest = os.environ["SSM_ImageDigest"]
    if not DIGEST.fullmatch(digest):
        raise ValueError("유효한 AI 이미지 다이제스트가 필요합니다.")
    with (ROOT / "deploy-api.lock").open("a") as deploy_lock:
        fcntl.flock(deploy_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        account_files = ROOT / "aws/ai"
        for name in ("config", "credentials.json"):
            stat = (account_files / name).stat()
            if stat.st_uid != 0 or stat.st_mode & 0o777 != 0o600 or not stat.st_size:
                raise RuntimeError("AI 자격 증명 파일 권한을 확인하세요.")
        expiration = json.loads((account_files / "credentials.json").read_text())["Expiration"]
        if datetime.fromisoformat(expiration.replace("Z", "+00:00")).timestamp() <= time.time() + 300:
            raise RuntimeError("AI 자격 증명 갱신이 필요합니다.")
        with tempfile.TemporaryDirectory() as config:
            env = dict(os.environ, DOCKER_CONFIG=config)
            password = run("aws", "ecr", "get-login-password", "--region", "ap-northeast-2")
            run("docker", "login", "--username", "AWS", "--password-stdin", REGISTRY,
                input=password.encode(), env=env)
            ref = REPO + "@" + digest
            run("docker", "pull", ref, env=env)
        label = run("docker", "image", "inspect", "--format", '{{index .Config.Labels "im.landit.ai-rollout"}}', ref)
        if label != "slot-consumer-v1":
            raise RuntimeError("슬롯 인계를 지원하는 AI 이미지가 필요합니다.")
        slot, previous = deploy(digest)
        print(f"active_slot={slot}\nimage_digest={digest}\nprevious_image_digest={previous}")
