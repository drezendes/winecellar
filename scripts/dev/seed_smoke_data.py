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

from cellar.models import Bottle, Producer, TastingNote, Vintage, Wine

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

# A wishlist entry and a tried-at-a-restaurant record (no bottles), so the
# non-inventory views have something to show.
geyserville, _ = Wine.objects.get_or_create(
    producer=producer, name="Geyserville", defaults={"wine_type": "red", "varietals": "Zinfandel"}
)
Vintage.objects.get_or_create(wine=geyserville, year=2021, defaults={"wishlist": True})

tempier, _ = Producer.objects.get_or_create(
    name="Domaine Tempier", defaults={"region": "Bandol", "country": "France"}
)
bandol, _ = Wine.objects.get_or_create(
    producer=tempier, name="Bandol Rouge", defaults={"wine_type": "red", "varietals": "Mourvèdre"}
)
tried, _ = Vintage.objects.get_or_create(wine=bandol, year=2020)
smoke_user = User.objects.get(username="smoke")
if not tried.tasting_notes.exists():
    TastingNote.objects.create(
        vintage=tried, author=smoke_user, rating=92,
        notes="Had at Le Petit Bistro — savory, herbal, want to own this.",
    )

print("seeded: user 'smoke', Monte Bello (1 bottle), Geyserville (wishlist), Bandol (tried)")
