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

# Variety for design review: a white in its window, a sparkling on the
# wishlist, and a red already past its window (exercises dots + gauge states).
huet, _ = Producer.objects.get_or_create(
    name="Domaine Huet", defaults={"region": "Vouvray", "country": "France"}
)
le_mont, _ = Wine.objects.get_or_create(
    producer=huet, name="Le Mont Sec", defaults={"wine_type": "white", "varietals": "Chenin Blanc"}
)
white_v, _ = Vintage.objects.get_or_create(
    wine=le_mont, year=2022, defaults={"drink_from": 2024, "drink_until": 2040}
)
if not white_v.bottles.exists():
    Bottle.objects.create(vintage=white_v, purchase_price="42.00", location="rack B")

roederer, _ = Producer.objects.get_or_create(
    name="Louis Roederer", defaults={"region": "Champagne", "country": "France"}
)
cristal, _ = Wine.objects.get_or_create(
    producer=roederer, name="Collection 244", defaults={"wine_type": "sparkling", "varietals": ""}
)
Vintage.objects.get_or_create(wine=cristal, year=None, defaults={"wishlist": True})

faded, _ = Wine.objects.get_or_create(
    producer=tempier, name="Rosé", defaults={"wine_type": "rose", "varietals": "Mourvèdre, Grenache"}
)
faded_v, _ = Vintage.objects.get_or_create(
    wine=faded, year=2021, defaults={"drink_from": 2022, "drink_until": 2024}
)
if not faded_v.bottles.exists():
    Bottle.objects.create(vintage=faded_v, purchase_price="38.00", location="rack A")

print(
    "seeded: user 'smoke' + Monte Bello (red, ready), Le Mont Sec (white, ready), "
    "Tempier Rosé (past window), Cristal (sparkling wishlist), Geyserville, Bandol"
)
