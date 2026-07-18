"""Deploy: ship the committed HEAD tree to /opt/box and rebuild the web
container. Deliberate, one command — there is no auto-deploy.

    # look the box up in Hetzner (needs HCLOUD_TOKEN):
    op run --env-file=.env.op -- python scripts/deploy/deploy.py
    # or skip the lookup with an explicit host (no HCLOUD_TOKEN needed):
    python scripts/deploy/deploy.py --host deploy@<box-ip>

Ships committed HEAD via `git archive` (no .git/.venv/.env/media), extracts to
/opt/box normalizing shell scripts to LF, then `docker compose up -d --build` —
which reruns migrate + collectstatic and restarts gunicorn. Ships only what's
committed, so commit (and usually push) first. Needs SSH (the 1Password agent
key). Run from PowerShell so scp/ssh resolve to Windows OpenSSH (the agent).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from common import REPO_ROOT, api, load_env

HCLOUD = "https://api.hetzner.cloud/v1"
BOX_NAME = "box"
COMPOSE = "docker-compose.prod.yml"
REMOTE = "/opt/box"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _box_host() -> str:
    token = load_env("HCLOUD_TOKEN")
    servers = api("GET", f"{HCLOUD}/servers?name={BOX_NAME}", token)["servers"]
    if not servers:
        sys.exit(f"no Hetzner server named '{BOX_NAME}' — pass --host explicitly")
    return "deploy@" + servers[0]["public_net"]["ipv4"]["ip"]


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", help="deploy@<ip> — skips the Hetzner lookup")
    args = parser.parse_args()

    dirty = _git("status", "--porcelain")
    if dirty:
        print("NOTE: deploy ships committed HEAD; these uncommitted changes are NOT shipped:")
        print(dirty)

    host = args.host or _box_host()
    head = _git("rev-parse", "--short", "HEAD")
    print(f"deploying {head} -> {host}:{REMOTE}")

    with tempfile.TemporaryDirectory() as td:
        tar = Path(td) / "winecellar.tar"
        _run(["git", "-C", str(REPO_ROOT), "archive", "--format=tar", "-o", str(tar), "HEAD"])
        _run(["scp", str(tar), f"{host}:/tmp/winecellar.tar"])

    remote = (
        f"tar -xf /tmp/winecellar.tar -C {REMOTE} && rm /tmp/winecellar.tar && "
        f"find {REMOTE} -name '*.sh' -exec sed -i 's/\\r$//' {{}} + && "
        f"chmod +x {REMOTE}/deploy/backup/backup.sh && "
        f"cd {REMOTE} && docker compose -f {COMPOSE} up -d --build && "
        f"docker compose -f {COMPOSE} ps"
    )
    _run(["ssh", host, remote])
    print(f"\ndeployed {head} — web container rebuilt (migrate + collectstatic ran on start).")


if __name__ == "__main__":
    main()
