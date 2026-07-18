"""Read-only guest role: the server-side wall + UI redactions. No AI calls.

The wall is ``core.middleware.GuestPolicyMiddleware``; the templates only hide
buttons. These tests exercise both layers, and a non-guest control proves the
policy is a strict no-op for everyone else.
"""

import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from assistant.models import Prospect
from cellar.models import Bottle, Producer, TastingNote, Vintage, Wine
from core.guest import GUEST_GROUP, is_guest

CURRENT_YEAR = timezone.localdate().year

# A style fingerprint (the 7 numeric axes taste_map projects on).
VEC = {
    "body": 8, "acidity": 6, "tannin": 8, "sweetness": 0,
    "fruit_savory": 7, "oak": 4, "intensity": 8,
}


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="owner", password="pw")


@pytest.fixture
def guest(db):
    group, _ = Group.objects.get_or_create(name=GUEST_GROUP)
    user = User.objects.create_user(username="guest", password="pw")
    user.groups.add(group)
    return user


@pytest.fixture
def vintage(db):
    producer = Producer.objects.create(name="Château Test", region="Bordeaux", country="France")
    wine = Wine.objects.create(producer=producer, name="Grand Vin", wine_type="red")
    return Vintage.objects.create(
        wine=wine, year=2018, drink_from=CURRENT_YEAR - 2, drink_until=CURRENT_YEAR + 5
    )


@pytest.fixture
def bottle(vintage):
    return Bottle.objects.create(vintage=vintage, purchase_price="50.00")


def bounced_to_dashboard(response):
    return response.status_code == 302 and response.url == reverse("cellar:dashboard")


class TestGuestIdentity:
    def test_is_guest_true_for_group_member(self, guest):
        assert is_guest(guest) is True

    def test_is_guest_false_for_owner(self, owner):
        assert is_guest(owner) is False

    def test_request_flag_set_for_guest(self, client, guest):
        client.force_login(guest)
        response = client.get(reverse("cellar:dashboard"))
        assert response.wsgi_request.is_guest is True

    def test_request_flag_false_for_owner(self, client, owner):
        client.force_login(owner)
        response = client.get(reverse("cellar:dashboard"))
        assert response.wsgi_request.is_guest is False


class TestCreateGuestCommand:
    def test_creates_nonstaff_group_member(self, db):
        call_command("create_guest", "--password", "sekret")
        user = User.objects.get(username="guest")
        assert user.is_staff is False
        assert user.is_superuser is False
        assert user.check_password("sekret")
        assert is_guest(user)

    def test_idempotent_update(self, db):
        call_command("create_guest", "--password", "one")
        call_command("create_guest", "--password", "two")
        assert User.objects.filter(username="guest").count() == 1
        assert User.objects.get(username="guest").check_password("two")

    def test_demotes_a_staff_account(self, db):
        User.objects.create_user(
            username="guest", password="x", is_staff=True, is_superuser=True
        )
        call_command("create_guest", "--password", "x")
        user = User.objects.get(username="guest")
        assert user.is_staff is False
        assert user.is_superuser is False


class TestGuestBrowse:
    """The read-only surfaces a guest is allowed to see."""

    def test_dashboard(self, client, guest, bottle):
        client.force_login(guest)
        assert client.get(reverse("cellar:dashboard")).status_code == 200

    def test_wine_list(self, client, guest, bottle):
        client.force_login(guest)
        assert client.get(reverse("cellar:wine_list")).status_code == 200

    def test_wine_detail(self, client, guest, bottle):
        client.force_login(guest)
        url = reverse("cellar:wine_detail", kwargs={"pk": bottle.vintage.wine.pk})
        assert client.get(url).status_code == 200

    def test_taste_map(self, client, guest):
        client.force_login(guest)
        assert client.get(reverse("cellar:taste_map")).status_code == 200

    def test_more(self, client, guest):
        client.force_login(guest)
        assert client.get(reverse("cellar:more")).status_code == 200


class TestGuestBlockedMutations:
    """Every write bounces, and the DB is untouched."""

    def test_drink_blocked(self, client, guest, bottle):
        client.force_login(guest)
        url = reverse("cellar:bottle_action", kwargs={"pk": bottle.pk, "action": "drink"})
        assert bounced_to_dashboard(client.post(url))
        bottle.refresh_from_db()
        assert bottle.status == Bottle.Status.IN_CELLAR

    def test_wishlist_toggle_blocked(self, client, guest, vintage):
        client.force_login(guest)
        url = reverse("cellar:vintage_wishlist", kwargs={"pk": vintage.pk})
        assert bounced_to_dashboard(client.post(url))
        vintage.refresh_from_db()
        assert vintage.wishlist is False

    def test_note_add_blocked(self, client, guest, vintage):
        client.force_login(guest)
        url = reverse("cellar:note_add") + f"?vintage={vintage.pk}"
        response = client.post(url, {"tasted_date": timezone.localdate(), "rating": 90})
        assert bounced_to_dashboard(response)
        assert TastingNote.objects.count() == 0

    def test_bottle_add_blocked(self, client, guest):
        client.force_login(guest)
        response = client.post(
            reverse("cellar:bottle_add"),
            {
                "mode": "wishlist", "producer_name": "X", "wine_name": "Y",
                "wine_type": "red", "year": 2020, "size": "750ml",
            },
        )
        assert bounced_to_dashboard(response)
        assert Wine.objects.count() == 0

    def test_window_edit_blocked(self, client, guest, vintage):
        client.force_login(guest)
        url = reverse("cellar:vintage_window", kwargs={"pk": vintage.pk})
        response = client.post(url, {"drink_from": 2019, "drink_until": 2030})
        assert bounced_to_dashboard(response)
        vintage.refresh_from_db()
        assert vintage.drink_from == CURRENT_YEAR - 2  # untouched


class TestGuestBlockedAI:
    """AI is POST-only and namespaced under /assistant/ — doubly blocked, and
    the Anthropic client is never even constructed (no spend)."""

    def test_research_blocked_and_client_untouched(self, client, guest, vintage, monkeypatch):
        import assistant.sommelier as sommelier

        calls = []
        monkeypatch.setattr(sommelier, "_get_client", lambda: calls.append(1))
        client.force_login(guest)
        url = reverse("assistant:research_wine", kwargs={"pk": vintage.pk})
        assert bounced_to_dashboard(client.post(url))
        assert calls == []

    def test_suggest_blocked(self, client, guest):
        client.force_login(guest)
        response = client.post(reverse("assistant:prospect_suggest"), {"hint": "x"})
        assert bounced_to_dashboard(response)
        assert Prospect.objects.count() == 0


PRIVATE_GET_NAMES = [
    "assistant:prospects",
    "assistant:suggestions",
    "assistant:usage",
    "assistant:cellar_value",
    "assistant:profile",
    "assistant:label_scan",
    "assistant:menu_scan",
    "assistant:pairing",
    "cellar:bottle_add",
    "cellar:note_add",
]


class TestGuestBlockedPrivateGets:
    @pytest.mark.parametrize("name", PRIVATE_GET_NAMES)
    def test_private_get_bounced(self, client, guest, name):
        client.force_login(guest)
        assert bounced_to_dashboard(client.get(reverse(name)))

    def test_window_form_get_bounced(self, client, guest, vintage):
        client.force_login(guest)
        url = reverse("cellar:vintage_window", kwargs={"pk": vintage.pk})
        assert bounced_to_dashboard(client.get(url))

    def test_htmx_block_returns_bare_403(self, client, guest, vintage):
        client.force_login(guest)
        url = reverse("assistant:dossier_fragment", kwargs={"pk": vintage.pk})
        response = client.get(url, HTTP_HX_REQUEST="true")
        assert response.status_code == 403

    def test_admin_stays_shut_for_nonstaff_guest(self, client, guest):
        client.force_login(guest)
        response = client.get("/admin/")
        # GuestPolicy lets the safe GET through; admin's own gate bounces
        # the non-staff user to its login (never the app index).
        assert response.status_code in (302, 403)


class TestGuestValueRedactions:
    """Per-bottle price stays (the owner shares it); the aggregate total is hidden."""

    def test_dashboard_hides_total_value_tile(self, client, guest, owner, bottle):
        client.force_login(owner)
        assert b"purchase value" in client.get(reverse("cellar:dashboard")).content
        client.force_login(guest)
        assert b"purchase value" not in client.get(reverse("cellar:dashboard")).content

    def test_wine_page_keeps_per_bottle_price(self, client, guest, bottle):
        client.force_login(guest)
        url = reverse("cellar:wine_detail", kwargs={"pk": bottle.vintage.wine.pk})
        assert b"$50" in client.get(url).content


class TestGuestMapRedactions:
    @pytest.fixture
    def mapped_and_prospect(self, db):
        Wine.objects.create(
            producer=Producer.objects.create(name="P"),
            name="Mapped", wine_type="red", style_vector=VEC,
        )
        Prospect.objects.create(
            producer_name="Clos Rougeard", wine_name="Le Bourg",
            source=Prospect.Source.REQUESTED, style_vector=VEC,
        )

    def test_owner_map_plots_the_prospect(self, client, owner, mapped_and_prospect):
        client.force_login(owner)
        response = client.get(reverse("cellar:taste_map"))
        assert any(p["prospect"] for p in response.context["points"])
        assert b"watch list" in response.content

    def test_guest_map_strips_prospects_and_legend(self, client, guest, mapped_and_prospect):
        client.force_login(guest)
        response = client.get(reverse("cellar:taste_map"))
        assert not any(p["prospect"] for p in response.context["points"])
        assert b"watch list" not in response.content


class TestGuestNavRedactions:
    def test_dashboard_omits_scan_and_menu_tabs(self, client, guest, owner):
        client.force_login(owner)
        owner_html = client.get(reverse("cellar:dashboard")).content
        assert b"/assistant/scan/" in owner_html and b"/assistant/menu/" in owner_html
        client.force_login(guest)
        guest_html = client.get(reverse("cellar:dashboard")).content
        assert b"/assistant/scan/" not in guest_html
        assert b"/assistant/menu/" not in guest_html

    def test_more_hides_private_links_keeps_map_and_logout(self, client, guest):
        client.force_login(guest)
        html = client.get(reverse("cellar:more")).content
        assert b"Taste map" in html
        assert b"Log out" in html
        for needle in (
            b"Keep an eye out", b"Cellar value", b"Food pairing", b"Buying suggestions",
            b"taste profile", b"AI usage", b"Add wine by hand", b"Admin",
        ):
            assert needle not in html

    def test_more_shows_private_links_for_owner(self, client, owner):
        client.force_login(owner)
        html = client.get(reverse("cellar:more")).content
        assert b"Keep an eye out" in html and b"AI usage" in html


class TestGuestWineDetailRedactions:
    def test_action_controls_hidden_for_guest(self, client, guest, bottle):
        client.force_login(guest)
        url = reverse("cellar:wine_detail", kwargs={"pk": bottle.vintage.wine.pk})
        html = client.get(url).content
        for needle in (
            b"Drink</button>", b"Gift</button>", b"Add to wishlist",
            b"add tasting note", b"Add more bottles", b"edit window",
        ):
            assert needle not in html

    def test_action_controls_shown_for_owner(self, client, owner, bottle):
        client.force_login(owner)
        url = reverse("cellar:wine_detail", kwargs={"pk": bottle.vintage.wine.pk})
        html = client.get(url).content
        assert b"Drink</button>" in html and b"add tasting note" in html

    def test_wishlist_badge_stays_but_toggle_goes(self, client, guest, vintage):
        vintage.wishlist = True
        vintage.save()
        client.force_login(guest)
        url = reverse("cellar:wine_detail", kwargs={"pk": vintage.wine.pk})
        html = client.get(url).content
        assert b"badge-wishlist" in html          # informational badge kept
        assert b"Add to wishlist" not in html     # the toggle is gone
        assert b"Remove from wishlist" not in html


class TestNonGuestControl:
    """The policy must be a strict no-op for real users."""

    def test_owner_can_mutate(self, client, owner, vintage):
        client.force_login(owner)
        url = reverse("cellar:vintage_wishlist", kwargs={"pk": vintage.pk})
        assert client.post(url).status_code == 302
        vintage.refresh_from_db()
        assert vintage.wishlist is True

    def test_owner_reaches_private_pages(self, client, owner):
        client.force_login(owner)
        assert client.get(reverse("assistant:prospects")).status_code == 200
        assert client.get(reverse("assistant:usage")).status_code == 200
