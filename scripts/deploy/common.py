"""Shared helpers for the deploy scripts: .env loading + a tiny JSON client.

Stdlib only — these run from the repo venv with no extra dependencies.
Secrets come from the environment or the repo-root .env (gitignored; see
.env.example). Never print token values.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from os import environ
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env(name: str) -> str:
    """Return a secret from the environment or the repo-root .env file."""
    if environ.get(name):
        return environ[name]
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip().strip('"').strip("'")
    sys.exit(f"{name} not set — add it to .env (template: .env.example)")


def api(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    """One JSON request with a Bearer token; exits loudly on HTTP errors."""
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        sys.exit(f"{method} {url} -> HTTP {exc.code}\n{detail}")
    return json.loads(body) if body else {}
