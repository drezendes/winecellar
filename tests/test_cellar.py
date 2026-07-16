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


class TestIntakeModes:
    """Wishlist and tried-it records: vintages with no bottles."""

    def data(self, mode, **overrides):
        data = {
            "mode": mode,
            "producer_name": "Ridge",
            "wine_name": "Monte Bello",
            "wine_type": "red",
            "year": 2019,
            "size": "750ml",
        }
        data.update(overrides)
        return data

    def test_wishlist_mode_creates_flagged_vintage_without_bottles(self, db):
        form = BottleIntakeForm(data=self.data("wishlist"))
        assert form.is_valid(), form.errors
        vintage, bottles = form.save()
        assert bottles == []
        assert vintage.wishlist is True
        assert not vintage.bottles.exists()

    def test_tried_mode_creates_plain_vintage_without_bottles(self, db):
        form = BottleIntakeForm(data=self.data("tried"))
        assert form.is_valid(), form.errors
        vintage, bottles = form.save()
        assert bottles == []
        assert vintage.wishlist is False
        assert not vintage.bottles.exists()

    def test_cellar_mode_requires_quantity(self, db):
        form = BottleIntakeForm(data=self.data("cellar"))
        assert not form.is_valid()
        assert "quantity" in form.errors

    def test_missing_mode_defaults_to_cellar(self, db):
        data = self.data("", quantity=2)
        form = BottleIntakeForm(data=data)
        assert form.is_valid(), form.errors
        _, bottles = form.save()
        assert len(bottles) == 2

    def test_buying_a_wishlisted_wine_clears_the_flag(self, db):
        wish_form = BottleIntakeForm(data=self.data("wishlist"))
        assert wish_form.is_valid(), wish_form.errors
        vintage, _ = wish_form.save()

        buy_form = BottleIntakeForm(data=self.data("cellar", quantity=1))
        assert buy_form.is_valid(), buy_form.errors
        bought_vintage, bottles = buy_form.save()
        assert bought_vintage == vintage
        assert len(bottles) == 1
        bought_vintage.refresh_from_db()
        assert bought_vintage.wishlist is False

    def test_tried_mode_view_redirects_to_tasting_note(self, client, user):
        client.force_login(user)
        response = client.post(reverse("cellar:bottle_add"), self.data("tried"))
        assert response.status_code == 302
        assert reverse("cellar:note_add") in response.url
        vintage = Vintage.objects.get(wine__name="Monte Bello")
        assert f"vintage={vintage.pk}" in response.url

    def test_wishlist_toggle_view(self, client, user, vintage):
        client.force_login(user)
        url = reverse("cellar:vintage_wishlist", kwargs={"pk": vintage.pk})
        client.post(url)
        vintage.refresh_from_db()
        assert vintage.wishlist is True
        client.post(url)
        vintage.refresh_from_db()
        assert vintage.wishlist is False


class TestWineListFilters:
    def test_show_filters(self, client, user, vintage):
        # vintage's wine: no bottles yet. A second wine is stocked; a third tried.
        make_bottle(vintage)  # now in cellar
        producer = vintage.wine.producer
        wish_wine = Wine.objects.create(
            producer=producer, name="Wish Cuvée", wine_type=Wine.WineType.WHITE
        )
        Vintage.objects.create(wine=wish_wine, year=2022, wishlist=True)
        tried_wine = Wine.objects.create(
            producer=producer, name="Tried Blanc", wine_type=Wine.WineType.WHITE
        )
        tried_vintage = Vintage.objects.create(wine=tried_wine, year=2021)
        TastingNote.objects.create(vintage=tried_vintage, author=user, rating=90)

        client.force_login(user)
        url = reverse("cellar:wine_list")

        wines = client.get(url, {"show": "stock"}).context["wines"]
        assert [w.name for w in wines] == ["Grand Vin"]

        wines = client.get(url, {"show": "wishlist"}).context["wines"]
        assert [w.name for w in wines] == ["Wish Cuvée"]

        wines = client.get(url, {"show": "tried"}).context["wines"]
        assert [w.name for w in wines] == ["Tried Blanc"]

        wines = client.get(url).context["wines"]
        assert len(wines) == 3

    def test_legacy_in_stock_param_still_filters(self, client, user, vintage):
        make_bottle(vintage)
        Wine.objects.create(
            producer=vintage.wine.producer, name="Empty", wine_type=Wine.WineType.RED
        )
        client.force_login(user)
        wines = client.get(reverse("cellar:wine_list"), {"in_stock": "1"}).context["wines"]
        assert [w.name for w in wines] == ["Grand Vin"]

    def test_dashboard_wishlist_count(self, client, user, vintage):
        vintage.wishlist = True
        vintage.save()
        client.force_login(user)
        response = client.get(reverse("cellar:dashboard"))
        assert response.context["wishlist_count"] == 1


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
