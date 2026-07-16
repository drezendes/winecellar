"""Assistant tests with a mocked Anthropic client — no live API calls."""

import io
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from PIL import Image

from assistant import sommelier
from assistant.models import ApiUsage, LabelScan, MenuAnalysis, TasteProfile
from assistant.schemas import (
    DrinkingWindow,
    LabelData,
    MenuAdvice,
    MenuOffering,
    MenuRecommendation,
    Pairing,
    PairingAdvice,
    ProfileDraft,
    WineDossier,
)
from cellar.models import Bottle, Producer, TastingNote, Vintage, Wine


@pytest.fixture
def user(db):
    return User.objects.create_user(username="owner", password="test-pass-123")


def fake_image_file(name="label.jpg", size=(800, 1200)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(114, 47, 55)).save(buffer, format="JPEG")
    buffer.seek(0)
    buffer.name = name
    return buffer


def fake_response(parsed, input_tokens=2000, output_tokens=300):
    response = mock.Mock()
    response.parsed_output = parsed
    response.model = "claude-opus-4-8"
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    response.usage.cache_read_input_tokens = 0
    return response


LABEL = LabelData(
    producer_name="Ridge",
    producer_region="Santa Cruz Mountains",
    producer_country="USA",
    wine_name="Monte Bello",
    wine_type="red",
    varietals="Cabernet Sauvignon, Merlot",
    appellation="Santa Cruz Mountains",
    year=2019,
    abv=13.5,
    confidence_notes="",
)


@pytest.fixture
def mock_parse():
    with mock.patch.object(sommelier, "_get_client") as get_client:
        client = get_client.return_value
        yield client.messages.parse


class TestPrepareImage:
    def test_downscales_and_encodes(self):
        block = sommelier.prepare_image(fake_image_file(size=(4000, 3000)))
        assert block["type"] == "image"
        assert block["source"]["media_type"] == "image/jpeg"
        assert len(block["source"]["data"]) > 100


def fake_heic_file(name="label.heic", size=(800, 1200)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(114, 47, 55)).save(buffer, format="HEIF")
    buffer.seek(0)
    buffer.name = name
    return buffer


class TestHeicUploads:
    """iPhone photo-library uploads arrive as HEIC; we store browser-safe JPEG."""

    def test_heic_transcodes_to_jpeg(self):
        from assistant.images import ensure_browser_displayable

        result = ensure_browser_displayable(fake_heic_file())
        assert result.name.endswith(".jpg")
        assert Image.open(result).format == "JPEG"

    def test_jpeg_passes_through_unchanged(self):
        from assistant.images import ensure_browser_displayable

        upload = fake_image_file()
        assert ensure_browser_displayable(upload) is upload
        assert upload.tell() == 0  # rewound, ready for the next reader

    def test_scan_view_accepts_heic_and_stores_jpeg(self, client, user, mock_parse):
        mock_parse.return_value = fake_response(LABEL)
        client.force_login(user)
        response = client.post(
            reverse("assistant:label_scan"), {"image": fake_heic_file()}
        )
        assert response.status_code == 302
        scan = LabelScan.objects.get()
        assert scan.status == LabelScan.Status.COMPLETE
        assert scan.image.name.endswith(".jpg")
        with scan.image.open("rb") as stored:
            assert Image.open(stored).format == "JPEG"


class TestScanLabel:
    def test_returns_label_and_logs_usage(self, db, mock_parse):
        mock_parse.return_value = fake_response(LABEL)
        result = sommelier.scan_label(fake_image_file())
        assert result.producer_name == "Ridge"
        usage = ApiUsage.objects.get()
        assert usage.feature == "scan_label"
        assert usage.input_tokens == 2000

    def test_missing_api_key_raises(self, db, settings):
        settings.ANTHROPIC_API_KEY = ""
        with pytest.raises(sommelier.SommelierError, match="ANTHROPIC_API_KEY"):
            sommelier.scan_label(fake_image_file())

    def test_schema_mismatch_raises(self, db, mock_parse):
        mock_parse.return_value = fake_response(None)
        with pytest.raises(sommelier.SommelierError, match="schema"):
            sommelier.scan_label(fake_image_file())


class TestSuggestWindow:
    def test_prompt_includes_wine_details(self, db, mock_parse):
        producer = Producer.objects.create(name="Ridge", region="Santa Cruz Mountains")
        wine = Wine.objects.create(
            producer=producer, name="Monte Bello", wine_type=Wine.WineType.RED
        )
        vintage = Vintage.objects.create(wine=wine, year=2019)
        mock_parse.return_value = fake_response(
            DrinkingWindow(drink_from=2027, drink_until=2045, rationale="Structured mountain cab.")
        )
        result = sommelier.suggest_window(vintage)
        assert result.drink_from == 2027
        prompt = mock_parse.call_args.kwargs["messages"][0]["content"]
        assert "Ridge" in prompt
        assert "Monte Bello" in prompt
        assert "2019" in prompt


@pytest.fixture
def stocked_vintage(db):
    producer = Producer.objects.create(name="Ridge", region="Santa Cruz Mountains")
    wine = Wine.objects.create(
        producer=producer, name="Monte Bello", wine_type=Wine.WineType.RED,
        varietals="Cabernet Sauvignon",
    )
    vintage = Vintage.objects.create(wine=wine, year=2019, drink_from=2024, drink_until=2045)
    Bottle.objects.create(vintage=vintage)
    return vintage


class TestPairFood:
    def test_open_bottle_marked_in_inventory(self, db, stocked_vintage):
        bottle = stocked_vintage.bottles.first()
        bottle.mark_opened()
        summary = sommelier.inventory_summary()
        assert "1 ALREADY OPEN" in summary

    def test_inventory_in_prompt_and_ids_resolved(self, db, mock_parse, stocked_vintage):
        mock_parse.return_value = fake_response(
            PairingAdvice(
                pairings=[
                    Pairing(
                        vintage_id=str(stocked_vintage.pk),
                        wine_label="Ridge Monte Bello 2019",
                        reasoning="Structure matches the dish.",
                    )
                ],
                general_advice="",
            )
        )
        advice = sommelier.pair_food("braised short ribs")
        prompt = mock_parse.call_args.kwargs["messages"][0]["content"]
        assert str(stocked_vintage.pk) in prompt
        assert "braised short ribs" in prompt
        assert advice.pairings[0].vintage_id == str(stocked_vintage.pk)

    def test_pairing_view_drops_hallucinated_ids(self, client, user, mock_parse, stocked_vintage):
        mock_parse.return_value = fake_response(
            PairingAdvice(
                pairings=[
                    Pairing(vintage_id=str(stocked_vintage.pk), wine_label="Real", reasoning="ok"),
                    Pairing(vintage_id="not-a-real-id", wine_label="Fake", reasoning="no"),
                ],
                general_advice="Try something bold.",
            )
        )
        client.force_login(user)
        response = client.post(reverse("assistant:pairing"), {"dish": "short ribs"})
        assert response.status_code == 200
        pairings = response.context["pairings"]
        assert len(pairings) == 1
        assert pairings[0]["vintage"] == stocked_vintage


class TestAnalyzeMenu:
    def test_taste_context_and_inputs_included(self, db, user, mock_parse, stocked_vintage):
        TastingNote.objects.create(
            vintage=stocked_vintage, author=user, rating=95, notes="Superb"
        )
        TasteProfile.objects.create(
            user=user,
            text="I love structured mountain cabernet.",
            menu_notes="I usually want the cost-effective option.",
        )
        mock_parse.return_value = fake_response(MenuAdvice(offerings=[]))
        sommelier.analyze_menu(
            fake_image_file(), food="ribeye", notes="celebrating, okay to splurge", user=user
        )
        content = mock_parse.call_args.kwargs["messages"][0]["content"]
        text = next(b for b in content if b["type"] == "text")["text"]
        assert "95/100" in text
        assert "ribeye" in text
        assert "okay to splurge" in text
        assert "cost-effective option" in text
        assert "structured mountain cabernet" in text

    def test_disabled_categories_marked_skipped(self, db, user, mock_parse):
        TasteProfile.objects.create(user=user, menu_most_interesting=False)
        mock_parse.return_value = fake_response(MenuAdvice(offerings=[]))
        sommelier.analyze_menu(fake_image_file(), user=user)
        content = mock_parse.call_args.kwargs["messages"][0]["content"]
        text = next(b for b in content if b["type"] == "text")["text"]
        assert "opted out): most_interesting" in text
        assert "taste_match — up to 3" in text

    def test_menu_view_persists_ranked_picks(self, client, user, mock_parse):
        mock_parse.return_value = fake_response(
            MenuAdvice(
                offerings=[MenuOffering(name="Barolo Fontanafredda 2018", style="red", price="$88")],
                taste_match=[
                    MenuRecommendation(name="Barolo Fontanafredda 2018", price="$88", reasoning="Classic."),
                    MenuRecommendation(name="Chinon Baudry", price="$54", reasoning="Savory."),
                ],
                best_value=[
                    MenuRecommendation(name="Muscadet Sevre et Maine", price="$38", reasoning="Steal."),
                ],
                most_interesting=[
                    MenuRecommendation(name="Trousseau Arbois", price="$62", reasoning="Rare grape."),
                ],
            )
        )
        client.force_login(user)
        response = client.post(
            reverse("assistant:menu_scan"),
            {"image": fake_image_file("menu.jpg"), "food": "ribeye", "notes": "date night"},
        )
        assert response.status_code == 200
        advice = response.context["advice"]
        assert advice.taste_match[0].name.startswith("Barolo")
        assert len(advice.taste_match) == 2
        assert b"most interesting" in response.content
        analysis = MenuAnalysis.objects.get()
        assert analysis.status == MenuAnalysis.Status.COMPLETE
        assert analysis.food == "ribeye"
        assert analysis.result["taste_match"][0]["name"].startswith("Barolo")


DOSSIER = WineDossier(
    producer_background="Ridge is a historic Santa Cruz Mountains estate.",
    style_and_tasting="Structured, age-worthy mountain cabernet.",
    vintage_notes="2019 was a long, cool season.",
    drinking_advice="Best 2027-2045.",
    typical_price="$250-300",
    varietals="Cabernet Sauvignon, Merlot, Petit Verdot",
    appellation="Santa Cruz Mountains",
    abv=13.9,
    producer_region="Santa Cruz Mountains (research)",
    producer_country="USA",
    sources=["https://www.ridgewine.com/wines/monte-bello/"],
)


class TestResearchWine:
    def _research_client(self, mock_parse):
        """The mocked client, with messages.create returning a web-search text turn."""
        client = mock_parse._mock_parent._mock_parent  # client.messages.parse -> client
        text_block = mock.Mock(type="text")
        text_block.text = "Research notes: Ridge Monte Bello is..."
        create_response = fake_response(None)
        create_response.content = [text_block]
        create_response.stop_reason = "end_turn"
        client.messages.create.return_value = create_response
        return client

    def test_two_step_research(self, db, mock_parse, stocked_vintage):
        client = self._research_client(mock_parse)
        mock_parse.return_value = fake_response(DOSSIER)
        result = sommelier.research_wine(stocked_vintage)
        assert result.typical_price == "$250-300"
        # Step 1 used web search; step 2 structured the notes.
        tools = client.messages.create.call_args.kwargs["tools"]
        assert tools[0]["type"].startswith("web_search")
        assert "Ridge Monte Bello" in client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Research notes" in mock_parse.call_args.kwargs["messages"][0]["content"]
        assert ApiUsage.objects.filter(feature="research_wine").count() == 2

    def test_empty_dossier_raises_instead_of_saving_blank(self, db, mock_parse, stocked_vintage):
        self._research_client(mock_parse)
        mock_parse.return_value = fake_response(
            WineDossier(producer_background="", style_and_tasting="")
        )
        with pytest.raises(sommelier.SommelierError, match="couldn't find"):
            sommelier.research_wine(stocked_vintage)

    def test_research_prompt_includes_origin(self, db, mock_parse, stocked_vintage):
        client = self._research_client(mock_parse)
        mock_parse.return_value = fake_response(DOSSIER)
        sommelier.research_wine(stocked_vintage)
        prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "from Santa Cruz Mountains" in prompt  # producer region grounds the search

    def test_pause_turn_resumes(self, db, mock_parse, stocked_vintage):
        client = self._research_client(mock_parse)
        paused = fake_response(None)
        paused.content = [mock.Mock(type="server_tool_use")]
        paused.stop_reason = "pause_turn"
        done = client.messages.create.return_value
        client.messages.create.side_effect = [paused, done]
        mock_parse.return_value = fake_response(DOSSIER)
        sommelier.research_wine(stocked_vintage)
        assert client.messages.create.call_count == 2
        resumed_messages = client.messages.create.call_args.kwargs["messages"]
        assert resumed_messages[1]["role"] == "assistant"

class EagerThread:
    """Stand-in for threading.Thread that runs the target inline on start()."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class InertThread(EagerThread):
    """Thread stand-in that never runs — freezes the vintage in 'pending'."""

    instances = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        InertThread.instances.append(self)

    def start(self):
        pass


class TestResearchWineView:
    """The research POST is async: it marks the row pending, spawns a worker,
    and redirects immediately; the outcome lands on the Vintage row."""

    def test_view_saves_dossier_via_worker(self, client, user, stocked_vintage):
        with (
            mock.patch("assistant.tasks.threading.Thread", EagerThread),
            mock.patch.object(sommelier, "research_wine", return_value=DOSSIER),
        ):
            client.force_login(user)
            response = client.post(
                reverse("assistant:research_wine", kwargs={"pk": stocked_vintage.pk})
            )
        assert response.status_code == 302
        stocked_vintage.refresh_from_db()
        assert stocked_vintage.dossier["producer_background"].startswith("Ridge")
        assert stocked_vintage.dossier_state == "ready"
        assert stocked_vintage.dossier_status == ""

    def test_view_returns_immediately_with_pending_state(self, client, user, stocked_vintage):
        InertThread.instances = []
        with mock.patch("assistant.tasks.threading.Thread", InertThread):
            client.force_login(user)
            response = client.post(
                reverse("assistant:research_wine", kwargs={"pk": stocked_vintage.pk})
            )
        assert response.status_code == 302
        stocked_vintage.refresh_from_db()
        assert stocked_vintage.dossier is None
        assert stocked_vintage.dossier_state == "pending"
        assert len(InertThread.instances) == 1

    def test_pending_vintage_is_not_restarted(self, client, user, stocked_vintage):
        InertThread.instances = []
        client.force_login(user)
        url = reverse("assistant:research_wine", kwargs={"pk": stocked_vintage.pk})
        with mock.patch("assistant.tasks.threading.Thread", InertThread):
            client.post(url)
            client.post(url)  # second click while researching
        assert len(InertThread.instances) == 1

    def test_worker_backfills_blank_catalog_fields(self, client, user, stocked_vintage):
        # Fixture state: wine has varietals but no appellation; producer has
        # region but no country; vintage has no ABV.
        with (
            mock.patch("assistant.tasks.threading.Thread", EagerThread),
            mock.patch.object(sommelier, "research_wine", return_value=DOSSIER),
        ):
            client.force_login(user)
            client.post(reverse("assistant:research_wine", kwargs={"pk": stocked_vintage.pk}))

        stocked_vintage.refresh_from_db()
        wine = stocked_vintage.wine
        producer = wine.producer
        assert wine.varietals == "Cabernet Sauvignon"  # existing value untouched
        assert producer.region == "Santa Cruz Mountains"  # existing value untouched
        assert wine.appellation == "Santa Cruz Mountains"  # blank → filled
        assert producer.country == "USA"  # blank → filled
        assert float(stocked_vintage.abv) == 13.9  # blank → filled
        assert sorted(stocked_vintage.dossier["backfilled"]) == [
            "abv", "appellation", "country",
        ]

    def test_worker_failure_lands_on_row(self, client, user, stocked_vintage):
        with (
            mock.patch("assistant.tasks.threading.Thread", EagerThread),
            mock.patch.object(
                sommelier, "research_wine",
                side_effect=sommelier.SommelierError("Claude API call failed: boom"),
            ),
        ):
            client.force_login(user)
            client.post(reverse("assistant:research_wine", kwargs={"pk": stocked_vintage.pk}))
        stocked_vintage.refresh_from_db()
        assert stocked_vintage.dossier_state == "failed"
        assert "boom" in stocked_vintage.dossier_error

    def test_stale_pending_reads_failed_and_allows_retry(self, client, user, stocked_vintage):
        from datetime import timedelta

        from django.utils import timezone

        stocked_vintage.dossier_status = Vintage.DossierStatus.PENDING
        stocked_vintage.dossier_requested_at = timezone.now() - timedelta(minutes=20)
        stocked_vintage.save()
        assert stocked_vintage.dossier_state == "failed"  # aged out, worker died

        with (
            mock.patch("assistant.tasks.threading.Thread", EagerThread),
            mock.patch.object(sommelier, "research_wine", return_value=DOSSIER),
        ):
            client.force_login(user)
            client.post(reverse("assistant:research_wine", kwargs={"pk": stocked_vintage.pk}))
        stocked_vintage.refresh_from_db()
        assert stocked_vintage.dossier_state == "ready"

    def test_fragment_renders_each_state(self, client, user, stocked_vintage):
        from django.utils import timezone

        client.force_login(user)
        url = reverse("assistant:dossier_fragment", kwargs={"pk": stocked_vintage.pk})

        response = client.get(url)  # idle, no dossier
        assert b"Research this wine" in response.content
        assert b"hx-get" not in response.content

        stocked_vintage.dossier_status = Vintage.DossierStatus.PENDING
        stocked_vintage.dossier_requested_at = timezone.now()
        stocked_vintage.save()
        response = client.get(url)  # fresh pending: polling on
        assert b"hx-get" in response.content
        assert b"Researching this wine" in response.content

        stocked_vintage.dossier_status = Vintage.DossierStatus.FAILED
        stocked_vintage.dossier_error = "Claude API call failed"
        stocked_vintage.save()
        response = client.get(url)
        assert b"Retry research" in response.content
        assert b"hx-get" not in response.content


class TestTasteProfile:
    def test_profile_saved(self, client, user):
        client.force_login(user)
        response = client.post(
            reverse("assistant:profile"), {"text": "I drink mostly Loire whites."}
        )
        assert response.status_code == 302
        assert user.taste_profile.text == "I drink mostly Loire whites."

    def test_draft_prefills_form_without_saving(self, client, user, mock_parse):
        TasteProfile.objects.create(user=user, text="old text")
        mock_parse.return_value = fake_response(
            ProfileDraft(profile_text="I favor high-acid whites and savory reds.")
        )
        client.force_login(user)
        response = client.post(reverse("assistant:profile_draft"), follow=True)
        form = response.context["form"]
        assert form.initial["text"] == "I favor high-acid whites and savory reds."
        user.taste_profile.refresh_from_db()
        assert user.taste_profile.text == "old text"  # draft not auto-saved

    def test_pair_food_includes_profile(self, db, user, mock_parse, stocked_vintage):
        TasteProfile.objects.create(user=user, text="No oaky chardonnay ever.")
        mock_parse.return_value = fake_response(PairingAdvice(pairings=[]))
        sommelier.pair_food("roast chicken", user=user)
        prompt = mock_parse.call_args.kwargs["messages"][0]["content"]
        assert "No oaky chardonnay ever." in prompt

    def test_household_context_labels_all_profiles(self, db, mock_parse, stocked_vintage):
        from django.contrib.auth.models import User as UserModel

        alex = UserModel.objects.create_user("alex")
        sam = UserModel.objects.create_user("sam")
        TasteProfile.objects.create(user=alex, text="Loves Burgundy.")
        TasteProfile.objects.create(user=sam, text="Loves Riesling.")
        context = sommelier.taste_context()
        assert "TASTE PROFILE (alex)" in context
        assert "Loves Riesling." in context


class TestSuggestWindowView:
    def test_redirects_with_prefill(self, client, user, mock_parse, stocked_vintage):
        mock_parse.return_value = fake_response(
            DrinkingWindow(drink_from=2027, drink_until=2045, rationale="Built to age.")
        )
        client.force_login(user)
        response = client.post(
            reverse("assistant:suggest_window", kwargs={"pk": stocked_vintage.pk})
        )
        assert response.status_code == 302
        assert "drink_from=2027" in response.url
        assert "drink_until=2045" in response.url
        # Nothing saved yet — suggestion only prefills the form.
        stocked_vintage.refresh_from_db()
        assert stocked_vintage.drink_from == 2024

    def test_window_form_prefills_from_get(self, client, user, stocked_vintage):
        client.force_login(user)
        url = reverse("cellar:vintage_window", kwargs={"pk": stocked_vintage.pk})
        response = client.get(url, {"drink_from": 2027, "drink_until": 2045})
        assert response.context["form"].initial["drink_from"] == "2027"


class TestUsageView:
    def test_cost_estimate(self):
        from assistant.views import estimate_cost

        # 1M input + 1M output on Opus 4.8 = $5 + $25
        assert estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000) == 30.0

    def test_usage_page_aggregates(self, client, user):
        ApiUsage.objects.create(
            feature="scan_label", model="claude-opus-4-8",
            input_tokens=2000, output_tokens=500,
        )
        ApiUsage.objects.create(
            feature="scan_label", model="claude-opus-4-8",
            input_tokens=1000, output_tokens=250,
        )
        client.force_login(user)
        response = client.get(reverse("assistant:usage"))
        assert response.status_code == 200
        row = response.context["month_rows"][0]
        assert row["calls"] == 2
        assert row["input"] == 3000
        assert response.context["month_total"] > 0


class TestLabelScanView:
    def test_scan_redirects_to_prefilled_intake(self, client, user, mock_parse):
        mock_parse.return_value = fake_response(LABEL)
        client.force_login(user)
        response = client.post(
            reverse("assistant:label_scan"),
            {"image": fake_image_file()},
        )
        assert response.status_code == 302
        assert reverse("cellar:bottle_add") in response.url
        assert "producer_name=Ridge" in response.url
        assert "year=2019" in response.url
        scan = LabelScan.objects.get()
        assert scan.status == LabelScan.Status.COMPLETE
        assert scan.result["wine_name"] == "Monte Bello"
        assert scan.created_by == user

    def test_scan_links_to_vintage_confirmed_through_intake(self, client, user, mock_parse):
        mock_parse.return_value = fake_response(LABEL)
        client.force_login(user)
        response = client.post(reverse("assistant:label_scan"), {"image": fake_image_file()})
        scan = LabelScan.objects.get()
        assert f"label_scan={scan.pk}" in response.url

        # Confirming intake (any mode) links the scan to the created vintage.
        response = client.post(
            reverse("cellar:bottle_add"),
            {
                "mode": "wishlist",
                "producer_name": "Ridge",
                "wine_name": "Monte Bello",
                "wine_type": "red",
                "year": 2019,
                "size": "750ml",
                "label_scan": str(scan.pk),
            },
        )
        assert response.status_code == 302
        scan.refresh_from_db()
        assert scan.vintage is not None
        assert scan.vintage.wine.name == "Monte Bello"
        assert scan.vintage.wishlist is True

    def test_already_linked_scan_is_not_repointed(self, client, user, mock_parse, stocked_vintage):
        from django.core.files.uploadedfile import SimpleUploadedFile

        image = SimpleUploadedFile(
            "label.jpg", fake_image_file().read(), content_type="image/jpeg"
        )
        scan = LabelScan.objects.create(
            image=image, status=LabelScan.Status.COMPLETE,
            created_by=user, vintage=stocked_vintage,
        )
        client.force_login(user)
        client.post(
            reverse("cellar:bottle_add"),
            {
                "mode": "tried",
                "producer_name": "Other",
                "wine_name": "Different Wine",
                "wine_type": "white",
                "size": "750ml",
                "label_scan": str(scan.pk),
            },
        )
        scan.refresh_from_db()
        assert scan.vintage == stocked_vintage  # unchanged

    def test_failed_scan_recorded_and_reported(self, client, user, mock_parse):
        mock_parse.side_effect = sommelier.anthropic.APIConnectionError(request=mock.Mock())
        client.force_login(user)
        response = client.post(
            reverse("assistant:label_scan"),
            {"image": fake_image_file()},
        )
        assert response.status_code == 200  # re-rendered form with error message
        scan = LabelScan.objects.get()
        assert scan.status == LabelScan.Status.FAILED
        assert scan.error
