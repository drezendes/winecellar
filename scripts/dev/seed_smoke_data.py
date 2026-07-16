"""Seed a demo user and one wine for manual smoke-testing the dev server.

Run: .venv\\Scripts\\python.exe scripts\\dev\\seed_smoke_data.py
Idempotent. User: smoke / smoke-pass-123
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth.models import User

from cellar.models import Bottle, Producer, Vintage, Wine

if not User.objects.filter(username="smoke").exists():
    User.objects.create_user("smoke", password="smoke-pass-123")

producer, _ = Producer.objects.get_or_create(
    name="Ridge", defaults={"region": "Santa Cruz Mountains", "country": "USA"}
)
wine, _ = Wine.objects.get_or_create(
    producer=producer,
    name="Monte Bello",
    defaults={"wine_type": "red", "varietals": "Cabernet Sauvignon"},
)
vintage, _ = Vintage.objects.get_or_create(
    wine=wine, year=2019, defaults={"drink_from": 2024, "drink_until": 2045}
)
if not vintage.bottles.exists():
    Bottle.objects.create(vintage=vintage, purchase_price="180.00", location="rack A")

print("seeded: user 'smoke', Ridge Monte Bello 2019 with 1 bottle")
