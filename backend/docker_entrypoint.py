"""Prepare persistent storage, then run the app without root privileges."""

import os
import pwd
import sys


def main() -> None:
    user = pwd.getpwnam("agent_emsp")
    storage_root = os.environ.get("DOCUMENT_STORAGE_ROOT", "/app/backend/storage")
    os.makedirs(storage_root, exist_ok=True)

    # A Render Persistent Disk can replace the directory created in the image.
    # Own its contents before dropping privileges so uploads remain writable.
    for current, directories, files in os.walk(storage_root):
        os.chown(current, user.pw_uid, user.pw_gid)
        for name in directories + files:
            os.chown(os.path.join(current, name), user.pw_uid, user.pw_gid)

    os.setgroups(os.getgrouplist(user.pw_name, user.pw_gid))
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)

    port = os.environ.get("PORT", "10000")
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "app.main:app",
            "--app-dir",
            "/app/backend",
            "--host",
            "0.0.0.0",
            "--port",
            port,
        ],
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Container startup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
