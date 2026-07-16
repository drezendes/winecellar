"""Phase B: taste-map projection math + the map view. No AI calls."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from cellar import taste_map
from cellar.models import Bottle, Producer, Vintage, Wine


def vector(**overrides):
    base = {
        "body": 5, "acidity": 5, "tannin": 5, "sweetness": 1,
        "fruit_savory": 5, "oak": 5, "intensity": 5,
    }
    base.update(overrides)
    return base


BIG_RED = vector(body=9, tannin=9, oak=8, intensity=9, acidity=4)
BIG_RED_TOO = vector(body=8, tannin=8, oak=7, intensity=8, acidity=4)
CRISP_WHITE = vector(body=2, tannin=0, oak=1, intensity=3, acidity=9)
CRISP_WHITE_TOO = vector(body=2, tannin=0, oak=0, intensity=4, acidity=8)


class TestProjection:
    def test_clusters_separate(self):
        items = [
            ("red1", BIG_RED), ("red2", BIG_RED_TOO),
            ("white1", CRISP_WHITE), ("white2", CRISP_WHITE_TOO),
        ]
        result = taste_map.project(items)
        positions = result["positions"]
        # Same-cluster distance is much smaller than cross-cluster distance.
        import math

        within = math.dist(positions["red1"], positions["red2"])
        across = math.dist(positions["red1"], positions["white1"])
        assert across > within * 2

    def test_axis_label_only_when_dominant(self):
        # Reds vs whites differ mostly on body/tannin/oak together — mixed
        # loadings may or may not clear dominance, but a pure single-attribute
        # spread must label, and identical vectors must not.
        items = [(f"w{i}", vector(sweetness=i)) for i in range(0, 10, 2)]
        result = taste_map.project(items)
        assert result["x_axis"] == ("drier", "sweeter") or result["x_axis"] == ("sweeter", "drier")

        same = [(f"s{i}", vector()) for i in range(4)]
        result = taste_map.project(same)
        assert result["x_axis"] is None  # zero variance → no claimed axis

    def test_single_wine_centers(self):
        result = taste_map.project([("only", BIG_RED)])
        assert result["positions"]["only"] == (50.0, 50.0)

    def test_positions_within_padded_range(self):
        items = [("a", BIG_RED), ("b", CRISP_WHITE), ("c", vector())]
        for x, y in taste_map.project(items)["positions"].values():
            assert 8 <= x <= 92 and 8 <= y <= 92

    def test_neighbors_ranked_by_similarity(self):
        items = [("red2", BIG_RED_TOO), ("white1", CRISP_WHITE), ("mid", vector())]
        ranked = taste_map.neighbors(BIG_RED, items, count=2)
        assert ranked[0] == "red2"
        assert "white1" not in ranked


@pytest.fixture
def user(db):
    return User.objects.create_user(username="owner", password="test-pass-123")


@pytest.fixture
def mapped_wines(db):
    producer = Producer.objects.create(name="Various")
    wines = []
    for name, wine_type, vec, stocked in [
        ("Big Red", "red", BIG_RED, True),
        ("Other Red", "red", BIG_RED_TOO, False),
        ("Crisp White", "white", CRISP_WHITE, True),
    ]:
        wine = Wine.objects.create(
            producer=producer, name=name, wine_type=wine_type,
            style_vector=vec, style_caption=f"{name} caption",
        )
        vintage = Vintage.objects.create(wine=wine, year=2020)
        if stocked:
            Bottle.objects.create(vintage=vintage)
        wines.append(wine)
    # One wine with no vector — should be counted as unmapped, never plotted.
    Wine.objects.create(producer=producer, name="Unmapped", wine_type="red")
    return wines


class TestMapView:
    def test_plots_mapped_wines_and_counts_unmapped(self, client, user, mapped_wines):
        client.force_login(user)
        response = client.get(reverse("cellar:taste_map"))
        assert response.status_code == 200
        assert len(response.context["points"]) == 3
        assert response.context["unmapped"] == 1
        assert b"map-dot" in response.content

    def test_cellar_filter(self, client, user, mapped_wines):
        client.force_login(user)
        response = client.get(reverse("cellar:taste_map"), {"cellar": "1"})
        names = {p["wine"].name for p in response.context["points"]}
        assert names == {"Big Red", "Crisp White"}

    def test_focus_emphasis(self, client, user, mapped_wines):
        big_red = mapped_wines[0]
        client.force_login(user)
        response = client.get(reverse("cellar:taste_map"), {"focus": str(big_red.pk)})
        points = {p["wine"].name: p for p in response.context["points"]}
        assert points["Big Red"]["is_focus"]
        assert points["Other Red"]["is_neighbor"]  # nearest to Big Red
        assert response.context["neighbor_wines"][0].name == "Other Red"

    def test_wine_detail_links_to_map(self, client, user, mapped_wines):
        client.force_login(user)
        response = client.get(
            reverse("cellar:wine_detail", kwargs={"pk": mapped_wines[0].pk})
        )
        assert b"Wines like this" in response.content
