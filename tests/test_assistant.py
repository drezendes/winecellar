"""Assistant tests with a mocked Anthropic client — no live API calls."""

import io
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from PIL import Image

from assistant import sommelier
from assistant.models import ApiUsage, LabelScan, MenuAnalysis
from assistant.schemas import (
    DrinkingWindow,
    LabelData,
    MenuAdvice,
    MenuOffering,
    MenuRecommendation,
    Pairing,
    PairingAdvice,
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
    def test_taste_profile_included_when_notes_exist(
        self, db, user, mock_parse, stocked_vintage
    ):
        TastingNote.objects.create(
            vintage=stocked_vintage, author=user, rating=95, notes="Superb"
        )
        mock_parse.return_value = fake_response(
            MenuAdvice(offerings=[], recommendations=[], general_note="")
        )
        sommelier.analyze_menu(fake_image_file(), occasion="steak dinner")
        content = mock_parse.call_args.kwargs["messages"][0]["content"]
        text_block = next(b for b in content if b["type"] == "text")
        assert "95/100" in text_block["text"]
        assert "steak dinner" in text_block["text"]

    def test_menu_view_persists_analysis(self, client, user, mock_parse):
        mock_parse.return_value = fake_response(
            MenuAdvice(
                offerings=[MenuOffering(name="Barolo Fontanafredda 2018", style="red", price="$88")],
                recommendations=[
                    MenuRecommendation(name="Barolo Fontanafredda 2018", price="$88", reasoning="Classic.")
                ],
                general_note="",
            )
        )
        client.force_login(user)
        response = client.post(
            reverse("assistant:menu_scan"),
            {"image": fake_image_file("menu.jpg"), "occasion": "date night"},
        )
        assert response.status_code == 200
        assert response.context["advice"].recommendations[0].name.startswith("Barolo")
        analysis = MenuAnalysis.objects.get()
        assert analysis.status == MenuAnalysis.Status.COMPLETE
        assert analysis.occasion == "date night"


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
