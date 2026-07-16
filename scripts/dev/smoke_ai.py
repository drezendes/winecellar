"""Live smoke test for the AI sommelier — hits the real Claude API (pennies per run).

Usage (from the repo root, venv python):
    .venv\\Scripts\\python.exe scripts\\dev\\smoke_ai.py label path\\to\\label.jpg
    .venv\\Scripts\\python.exe scripts\\dev\\smoke_ai.py window   # uses first Vintage in DB
    .venv\\Scripts\\python.exe scripts\\dev\\smoke_ai.py email path\\to\\email.txt

Validates that the Pydantic schemas parse against the real model. Run sparingly.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from assistant import sommelier  # noqa: E402


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"label", "window", "email"}:
        print(__doc__)
        raise SystemExit(1)

    mode = sys.argv[1]
    if mode == "label":
        if len(sys.argv) != 3:
            raise SystemExit("Usage: smoke_ai.py label <image-path>")
        with open(sys.argv[2], "rb") as f:
            result = sommelier.scan_label(f)
    elif mode == "email":
        if len(sys.argv) != 3:
            raise SystemExit("Usage: smoke_ai.py email <text-file-path>")
        raw = Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace")
        result = sommelier.digest_email(raw)
    else:
        from cellar.models import Vintage

        vintage = Vintage.objects.first()
        if vintage is None:
            raise SystemExit("No vintages in the DB yet — add a wine first.")
        print(f"Suggesting window for: {vintage}")
        result = sommelier.suggest_window(vintage)

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
