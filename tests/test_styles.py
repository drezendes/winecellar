"""Phase A: style vectors — generation, backfill, research piggyback. AI mocked."""

from unittest import mock

import pytest
from django.contrib.auth.models import User

from assistant import sommelier
from assistant.schemas import StyleVector
from assistant.styles import backfill_styles, refresh_style
from cellar.models import Producer, TastingNote, Vintage, Wine


@pytest.fixture
def user(db):
    return User.objects.create_user(username="owner", password="test-pass-123")


@pytest.fixture
def wine(db):
    producer = Producer.objects.create(name="Ridge", region="Santa Cruz Mountains")
    return Wine.objects.create(
        producer=producer, name="Monte Bello", wine_type=Wine.WineType.RED,
        varietals="Cabernet Sauvignon",
    )


STYLE = StyleVector(
    body=8, acidity=6, tannin=8, sweetness=0, fruit_savory=6, oak=7, intensity=8,
    caption="Structured mountain cab built for the long haul",
    confidence="",
)


def fake_response(parsed):
    response = mock.Mock()
    response.parsed_output = parsed
    response.model = "claude-opus-4-8"
    response.usage.input_tokens = 800
    response.usage.output_tokens = 200
    response.usage.cache_read_input_tokens = 0
    return response


@pytest.fixture
def mock_parse():
    with mock.patch.object(sommelier, "_get_client") as get_client:
        yield get_client.return_value.messages.parse


class TestStyleVector:
    def test_prompt_grounded_in_facts_and_notes(self, db, user, wine, mock_parse):
        vintage = Vintage.objects.create(wine=wine, year=2019)
        TastingNote.objects.create(
            vintage=vintage, author=user, rating=95, notes="Iron fist, velvet glove."
        )
        mock_parse.return_value = fake_response(STYLE)
        result = sommelier.style_vector(wine)
        assert result.body == 8
        prompt = mock_parse.call_args.kwargs["messages"][0]["content"]
        assert "Monte Bello" in prompt
        assert "Cabernet Sauvignon" in prompt
        assert "Iron fist" in prompt

    def test_refresh_saves_to_wine(self, db, wine, mock_parse):
        mock_parse.return_value = fake_response(STYLE)
        refresh_style(wine)
        wine.refresh_from_db()
        assert wine.style_vector["tannin"] == 8
        assert wine.style_caption.startswith("Structured mountain")


class TestBackfill:
    def test_backfills_only_blanks(self, db, wine, mock_parse):
        producer2 = Producer.objects.create(name="Huet")
        done_wine = Wine.objects.create(
            producer=producer2, name="Le Mont", wine_type="white",
            style_vector={"body": 3}, style_caption="already done",
        )
        mock_parse.return_value = fake_response(STYLE)
        stats = backfill_styles()
        assert stats == {"done": 1, "failed": 0}
        assert mock_parse.call_count == 1
        done_wine.refresh_from_db()
        assert done_wine.style_caption == "already done"  # untouched

    def test_refresh_flag_redoes_everything(self, db, wine, mock_parse):
        wine.style_vector = {"body": 1}
        wine.save()
        mock_parse.return_value = fake_response(STYLE)
        stats = backfill_styles(refresh=True)
        assert stats["done"] == 1
        wine.refresh_from_db()
        assert wine.style_vector["body"] == 8

    def test_failure_skips_and_continues(self, db, wine, mock_parse):
        producer2 = Producer.objects.create(name="Huet")
        Wine.objects.create(producer=producer2, name="Le Mont", wine_type="white")
        mock_parse.side_effect = [
            sommelier.anthropic.APIConnectionError(request=mock.Mock()),
            fake_response(STYLE),
        ]
        stats = backfill_styles()
        assert stats == {"done": 1, "failed": 1}


class TestCommand:
    def test_command_reports_stats(self, db, wine, mock_parse):
        from django.core.management import call_command

        from assistant.management.commands.assistant_backfill_styles import Command

        mock_parse.return_value = fake_response(STYLE)
        cmd = Command()
        call_command(cmd, quiet=True)
        assert cmd.stats == {"done": 1, "failed": 0}
