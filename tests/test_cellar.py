"""Inventory core tests: window logic, intake form, and the drink flow."""

import datetime

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from cellar.forms import BottleIntakeForm
from cellar.models import Bottle, Producer, TastingNote, Vintage, Wine

CURRENT_YEAR = timezone.localdate().year


@pytest.fixture
def user(db):
    return User.objects.create_user(username="owner", password="test-pass-123")


@pytest.fixture
def vintage(db):
    producer = Producer.objects.create(name="Château Test", region="Bordeaux", country="France")
    wine = Wine.objects.create(
        producer=producer, name="Grand Vin", wine_type=Wine.WineType.RED,
        varietals="Cabernet Sauvignon, Merlot",
    )
    return Vintage.objects.create(
        wine=wine, year=2018, drink_from=CURRENT_YEAR - 2, drink_until=CURRENT_YEAR + 5
    )


def make_bottle(vintage, **kwargs):
    return Bottle.objects.create(vintage=vintage, **kwargs)


class TestWindowLogic:
    def test_window_status_ready(self, vintage):
        assert vintage.window_status == "ready"

    def test_window_status_hold(self, vintage):
        vintage.drink_from = CURRENT_YEAR + 2
        assert vintage.window_status == "hold"

    def test_window_status_past(self, vintage):
        vintage.drink_from = CURRENT_YEAR - 10
        vintage.drink_until = CURRENT_YEAR - 1
        assert vintage.window_status == "past"

    def test_window_status_unknown(self, vintage):
        vintage.drink_from = None
        vintage.drink_until = None
        assert vintage.window_status == "unknown"

    def test_drink_soon_requires_stock(self, vintage):
        vintage.drink_until = CURRENT_YEAR
        vintage.save()
        assert vintage not in Vintage.objects.drink_soon()
        make_bottle(vintage)
        assert vintage in Vintage.objects.drink_soon()

    def test_drink_soon_excludes_far_windows(self, vintage):
        make_bottle(vintage)  # drink_until is CURRENT_YEAR + 5
        assert vintage not in Vintage.objects.drink_soon()
        assert vintage in Vintage.objects.drink_soon(horizon_years=10)

    def test_ready_excludes_consumed_bottles(self, vintage):
        bottle = make_bottle(vintage)
        assert vintage in Vintage.objects.ready()
        bottle.mark_consumed()
        assert vintage not in Vintage.objects.ready()


class TestBottleIntakeForm:
    def valid_data(self, **overrides):
        data = {
            "producer_name": "Ridge",
            "wine_name": "Monte Bello",
            "wine_type": "red",
            "year": 2019,
            "quantity": 3,
            "size": "750ml",
            "purchase_price": "180.00",
        }
        data.update(overrides)
        return data

    def test_creates_full_chain(self, db):
        form = BottleIntakeForm(data=self.valid_data())
        assert form.is_valid(), form.errors
        vintage, bottles = form.save()
        assert vintage.wine.producer.name == "Ridge"
        assert vintage.wine.name == "Monte Bello"
        assert vintage.year == 2019
        assert len(bottles) == 3
        assert Bottle.objects.filter(status=Bottle.Status.IN_CELLAR).count() == 3

    def test_reuses_existing_chain(self, db, vintage):
        form = BottleIntakeForm(
            data=self.valid_data(
                producer_name="Château Test", wine_name="Grand Vin", year=2018, quantity=1
            )
        )
        assert form.is_valid(), form.errors
        saved_vintage, _ = form.save()
        assert saved_vintage == vintage
        assert Producer.objects.count() == 1
        assert Wine.objects.count() == 1

    def test_does_not_overwrite_existing_window(self, db, vintage):
        form = BottleIntakeForm(
            data=self.valid_data(
                producer_name="Château Test", wine_name="Grand Vin", year=2018,
                quantity=1, drink_from=1990, drink_until=1995,
            )
        )
        assert form.is_valid(), form.errors
        saved_vintage, _ = form.save()
        saved_vintage.refresh_from_db()
        assert saved_vintage.drink_from == CURRENT_YEAR - 2  # untouched

    def test_rejects_inverted_window(self, db):
        form = BottleIntakeForm(data=self.valid_data(drink_from=2030, drink_until=2020))
        assert not form.is_valid()


class TestDrinkFlow:
    def test_drink_marks_consumed_and_redirects_to_note(self, client, user, vintage):
        bottle = make_bottle(vintage)
        client.force_login(user)
        url = reverse("cellar:bottle_action", kwargs={"pk": bottle.pk, "action": "drink"})
        response = client.post(url)
        bottle.refresh_from_db()
        assert bottle.status == Bottle.Status.CONSUMED
        assert bottle.consumed_date == timezone.localdate()
        assert reverse("cellar:note_add") in response.url

    def test_drink_requires_post(self, client, user, vintage):
        bottle = make_bottle(vintage)
        client.force_login(user)
        url = reverse("cellar:bottle_action", kwargs={"pk": bottle.pk, "action": "drink"})
        response = client.get(url)
        assert response.status_code == 405

    def test_tasting_note_saved_with_author(self, client, user, vintage):
        bottle = make_bottle(vintage)
        client.force_login(user)
        url = reverse("cellar:note_add") + f"?vintage={vintage.pk}&bottle={bottle.pk}"
        response = client.post(
            url,
            {"tasted_date": timezone.localdate(), "rating": 93, "notes": "Singing right now."},
        )
        assert response.status_code == 302
        note = TastingNote.objects.get()
        assert note.author == user
        assert note.bottle == bottle
        assert note.rating == 93


class TestViews:
    def test_dashboard_shows_counts(self, client, user, vintage):
        make_bottle(vintage, purchase_price="50.00")
        make_bottle(vintage, purchase_price="50.00")
        client.force_login(user)
        response = client.get(reverse("cellar:dashboard"))
        assert response.status_code == 200
        assert response.context["bottle_count"] == 2
        assert response.context["cellar_value"] == 100

    def test_wine_list_search(self, client, user, vintage):
        client.force_login(user)
        response = client.get(reverse("cellar:wine_list"), {"q": "Grand"})
        assert vintage.wine in response.context["wines"]
        response = client.get(reverse("cellar:wine_list"), {"q": "zzz-no-match"})
        assert len(response.context["wines"]) == 0

    def test_wine_detail_renders(self, client, user, vintage):
        make_bottle(vintage)
        client.force_login(user)
        response = client.get(reverse("cellar:wine_detail", kwargs={"pk": vintage.wine.pk}))
        assert response.status_code == 200
        assert b"Drink" in response.content

    def test_intake_prefill_from_get_params(self, client, user):
        client.force_login(user)
        response = client.get(
            reverse("cellar:bottle_add"), {"producer_name": "Ridge", "wine_type": "red"}
        )
        assert response.status_code == 200
        assert response.context["form"].initial["producer_name"] == "Ridge"
