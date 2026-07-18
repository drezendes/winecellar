#!/usr/bin/env python3
"""Export all Buttondown subscribers to a dated JSON file (nightly backup).

Absorbed verbatim from the blog repo (deploy/box/backup/) per the shared-box
tenancy contract: one nightly B2 job for the whole box. Runs box-side from
backup.sh with BUTTONDOWN_API_KEY in the environment. Stdlib only — the box
has bare python3, no venv. Paginates /v1/subscribers so the export stays
complete past 100 subscribers.
"""

import json
import os
import sys
import urllib.request
from datetime import date

API = "https://api.buttondown.com/v1/subscribers"


def fetch_all(key: str) -> list[dict]:
    subscribers: list[dict] = []
    url = API
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Token {key}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.load(resp)
        subscribers.extend(page.get("results", []))
        url = page.get("next")
    return subscribers


def main() -> None:
    key = os.environ.get("BUTTONDOWN_API_KEY", "")
    if not key:
        sys.exit("BUTTONDOWN_API_KEY not set")
    dest_dir = sys.argv[1] if len(sys.argv) > 1 else "."

    subscribers = fetch_all(key)
    path = os.path.join(dest_dir, f"subscribers-{date.today().isoformat()}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(subscribers, fh, indent=2)
    os.replace(tmp, path)
    print(f"{len(subscribers)} subscriber(s) -> {path}")


if __name__ == "__main__":
    main()
