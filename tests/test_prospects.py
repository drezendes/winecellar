"""Phase C: prospects — the unvetted staging area. AI mocked."""

from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from assistant import sommelier
from assistant.models import LabelScan, Prospect
from assistant.schemas import ProspectIdea, ProspectIdeas, StyleVector, WineDossier
from assistant.tasks import _save_worth_watching
from cellar.models import Producer, Wine


@pytest.fixture
def user(db):
    return User.objects.create_user(username="owner", password="test-pass-123")


STYLE = StyleVector(
    body=8, acidity=6, tannin=8, sweetness=0, fruit_savory=7, oak=4, intensity=8,
    caption="Savory southern red",
)

IDEA = ProspectIdea(
    producer_name="Clos Rougeard",
    wine_name="Le Bourg",
    wine_type="red",
    varietals="Cabernet Franc",
    region="Saumur-Champigny",
    why="You rate savory, structured reds highly and own no Loire cab franc.",
    style=STYLE,
)


def fake_response(parsed):
    response = mock.Mock()
    response.parsed_output = parsed
    response.model = "claude-opus-4-8"
    response.usage.input_tokens = 3000
    response.usage.output_tokens = 800
    response.usage.cache_read_input_tokens = 0
    return response


@pytest.fixture
def mock_parse():
    with mock.patch.object(sommelier, "_get_client") as get_client:
        yield get_client.return_value.messages.parse


def make_dossier(**overrides):
    base = {
        "producer_background": "bg",
        "style_and_tasting": "style",
        "worth_watching": [],
    }
    base.update(overrides)
    return WineDossier(**base)


class TestResearchByproduct:
    def test_worth_watching_saved_as_research_prospects(self, db):
        _save_worth_watching(make_dossier(worth_watching=[IDEA]))
        prospect = Prospect.objects.get()
        assert prospect.source == Prospect.Source.RESEARCH
        assert prospect.producer_name == "Clos Rougeard"
        assert prospect.status == Prospect.Status.WATCHING

    def test_dedupes_against_catalog_and_prospects(self, db):
        producer = Producer.objects.create(name="Clos Rougeard")
        Wine.objects.create(producer=producer, name="Le Bourg", wine_type="red")
        _save_worth_watching(make_dossier(worth_watching=[IDEA]))
        assert Prospect.objects.count() == 0  # already in the catalog

        other = IDEA.model_copy(update={"producer_name": "Overnoy", "wine_name": "Ploussard"})
        _save_worth_watching(make_dossier(worth_watching=[other]))
        _save_worth_watching(make_dossier(worth_watching=[other]))  # re-research
        assert Prospect.objects.count() == 1


class TestSuggestProspects:
    def test_explicit_ask_creates_with_style(self, client, user, mock_parse):
        mock_parse.return_value = fake_response(ProspectIdeas(ideas=[IDEA]))
        client.force_login(user)
        response = client.post(
            reverse("assistant:prospect_suggest"), {"hint": "under $80, more savory"}
        )
        assert response.status_code == 302
        prospect = Prospect.objects.get()
        assert prospect.source == Prospect.Source.REQUESTED
        assert prospect.style_vector["fruit_savory"] == 7
        assert prospect.created_by == user
        prompt = mock_parse.call_args.kwargs["messages"][0]["content"]
        assert "under $80" in prompt

    def test_existing_watchlist_in_prompt_and_deduped(self, client, user, mock_parse):
        Prospect.objects.create(
            producer_name="Clos Rougeard", wine_name="Le Bourg",
            source=Prospect.Source.RESEARCH,
        )
        mock_parse.return_value = fake_response(ProspectIdeas(ideas=[IDEA]))
        client.force_login(user)
        client.post(reverse("assistant:prospect_suggest"), {})
        assert Prospect.objects.count() == 1  # duplicate suggestion dropped
        prompt = mock_parse.call_args.kwargs["messages"][0]["content"]
        assert "Clos Rougeard Le Bourg" in prompt  # told not to repeat


class TestScanToProspect:
    def test_scan_saved_for_later(self, client, user):
        scan = LabelScan.objects.create(
            image="label_scans/x.jpg", status=LabelScan.Status.COMPLETE,
            result={
                "producer_name": "Niepoort", "wine_name": "10 Year Tawny",
                "wine_type": "fortified", "varietals": "", "producer_region": "Douro",
            },
            created_by=user,
        )
        client.force_login(user)
        response = client.post(
            reverse("assistant:scan_to_prospect", kwargs={"pk": scan.pk})
        )
        assert response.status_code == 302
        prospect = Prospect.objects.get()
        assert prospect.source == Prospect.Source.SCANNED
        assert prospect.label_scan == scan
        assert prospect.region == "Douro"


class TestPromotion:
    def test_intake_promotes_prospect(self, client, user):
        prospect = Prospect.objects.create(
            producer_name="Clos Rougeard", wine_name="Le Bourg",
            wine_type="red", source=Prospect.Source.REQUESTED,
        )
        client.force_login(user)
        response = client.post(
            reverse("cellar:bottle_add"),
            {
                "mode": "wishlist",
                "producer_name": "Clos Rougeard",
                "wine_name": "Le Bourg",
                "wine_type": "red",
                "year": 2019,
                "quantity": 1,
                "size": "750ml",
                "prospect": str(prospect.pk),
            },
        )
        assert response.status_code == 302
        prospect.refresh_from_db()
        assert prospect.status == Prospect.Status.PROMOTED
        assert prospect.promoted_wine.name == "Le Bourg"

    def test_dismiss(self, client, user):
        prospect = Prospect.objects.create(
            producer_name="X", wine_name="Y", source=Prospect.Source.RESEARCH
        )
        client.force_login(user)
        client.post(reverse("assistant:prospect_dismiss", kwargs={"pk": prospect.pk}))
        prospect.refresh_from_db()
        assert prospect.status == Prospect.Status.DISMISSED


class TestProspectsOnMap:
    def test_watching_prospect_with_style_plotted_dashed(self, client, user, db):
        producer = Producer.objects.create(name="P")
        Wine.objects.create(
            producer=producer, name="Mapped", wine_type="red",
            style_vector=STYLE.model_dump(),
        )
        Prospect.objects.create(
            producer_name="Clos Rougeard", wine_name="Le Bourg",
            source=Prospect.Source.REQUESTED, style_vector=STYLE.model_dump(),
        )
        Prospect.objects.create(  # no vector → never plotted
            producer_name="No", wine_name="Vector", source=Prospect.Source.RESEARCH
        )
        client.force_login(user)
        response = client.get(reverse("cellar:taste_map"))
        prospect_points = [p for p in response.context["points"] if p["prospect"]]
        assert len(prospect_points) == 1
        assert b"map-dot-prospect" in response.content

        # cellar-only mode excludes prospects entirely
        response = client.get(reverse("cellar:taste_map"), {"cellar": "1"})
        assert not any(p["prospect"] for p in response.context["points"])
