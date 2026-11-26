# 운영 EC2의 BE 환경 파일에 사전 API 키를 기록한다.
import fcntl
import getpass
import os
from pathlib import Path
import tempfile
import warnings


KEY_NAME = b"LANDIT_DICTIONARY_API_KEY"


def update_api_env(api_env: Path, key: bytes) -> None:
    if not key or key != key.strip() or any(char in key for char in (b"\n", b"\r", b"\0")):
        raise ValueError("비어 있지 않은 한 줄의 사전 인증키를 입력해야 합니다.")

    with (api_env.parent / "deploy-api.lock").open("ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not api_env.is_file() or api_env.is_symlink():
            raise ValueError("기존 api.env 일반 파일을 확인해야 합니다.")

        fd, filename = tempfile.mkstemp(prefix=".api.env.", dir=api_env.parent)
        staged = Path(filename)
        try:
            with os.fdopen(fd, "wb") as updated, api_env.open("rb") as current:
                for line in current:
                    entry_name = line.lstrip(b" \t").rstrip(b"\r\n").split(b"=", 1)[0]
                    if entry_name != KEY_NAME:
                        updated.write(line if line.endswith(b"\n") else line + b"\n")
                updated.write(KEY_NAME + b"=" + key + b"\n")
            staged.replace(api_env)
        finally:
            staged.unlink(missing_ok=True)


if __name__ == "__main__":
    os.umask(0o077)
    warnings.simplefilter("error", getpass.GetPassWarning)
    try:
        key = getpass.getpass("운영 사전 API 키: ").encode()
        update_api_env(Path("/opt/landit/api.env"), key)
    except BlockingIOError:
        raise SystemExit("운영 BE 배포가 진행 중입니다. 배포 완료 후 다시 실행하세요.") from None
    except (EOFError, getpass.GetPassWarning):
        raise SystemExit("입력을 숨길 수 있는 운영 EC2 터미널에서 실행하세요.") from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print("운영 BE 환경 파일에 사전 API 키를 반영했습니다.")
