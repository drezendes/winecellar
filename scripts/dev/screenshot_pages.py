"""Screenshot every page at iPhone size (390x844) for design review.

Run: .venv\\Scripts\\python.exe scripts\\dev\\screenshot_pages.py [--dark]
Needs the dev server running (default :8000; override with WINECELLAR_BASE —
e.g. when foundation's runserver already owns :8000) and the smoke seed data
(scripts/dev/seed_smoke_data.py). Writes PNGs to logs/screenshots/.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from playwright.sync_api import sync_playwright

from cellar.models import Wine

BASE = os.environ.get("WINECELLAR_BASE", "http://127.0.0.1:8000")
OUT = Path(__file__).resolve().parents[2] / "logs" / "screenshots"

PAGES = [
    ("dashboard", "/"),
    ("wines", "/wines/"),
    ("intake", "/bottles/add/"),
    ("scan", "/assistant/scan/"),
    ("menu", "/assistant/menu/"),
    ("pairing", "/assistant/pairing/"),
    ("profile", "/assistant/profile/"),
    ("usage", "/assistant/usage/"),
    ("more", "/more/"),
]


def main():
    dark = "--dark" in sys.argv
    suffix = "-dark" if dark else ""
    OUT.mkdir(parents=True, exist_ok=True)

    wine = Wine.objects.filter(name="Monte Bello").first()
    pages = list(PAGES)
    if wine:
        pages.insert(2, ("wine-detail", f"/wines/{wine.pk}/"))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            color_scheme="dark" if dark else "light",
        )
        page = context.new_page()

        page.goto(f"{BASE}/accounts/login/")
        page.screenshot(path=OUT / f"login{suffix}.png")
        page.fill('input[name="username"]', "smoke")
        page.fill('input[name="password"]', "smoke-pass-123")
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE}/")

        for name, path in pages:
            page.goto(f"{BASE}{path}")
            page.screenshot(path=OUT / f"{name}{suffix}.png", full_page=True)
            print(f"{name}{suffix}.png")

        browser.close()
    print(f"done -> {OUT}")


if __name__ == "__main__":
    main()
