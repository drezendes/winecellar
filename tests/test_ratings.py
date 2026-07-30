"""The 5-point rating scale: legacy banding, choices, and critic scores."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from cellar.models import Producer, Vintage, Wine
from cellar.ratings import (
    LEGACY_BANDS,
    RATING_ANCHORS,
    RATING_CHOICES,
    SCALE_LEGEND,
    band_legacy_rating,
    format_rating,
)


@pytest.fixture
def vintage(db):
    producer = Producer.objects.create(name="Château Test", region="Bordeaux", country="France")
    wine = Wine.objects.create(producer=producer, name="Grand Vin", wine_type=Wine.WineType.RED)
    return Vintage.objects.create(wine=wine, year=2018)


class TestLegacyBands:
    """Every band edge from docs/rating_scale_plan.md, both sides."""

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            (50, "1.0"), (69, "1.0"),
            (70, "1.5"), (74, "1.5"),
            (75, "2.0"), (79, "2.0"),
            (80, "2.5"), (83, "2.5"),
            (84, "3.0"), (86, "3.0"),
            (87, "3.5"), (89, "3.5"),
            (90, "4.0"), (92, "4.0"),
            (93, "4.5"), (94, "4.5"),
            (95, "5.0"), (100, "5.0"),
        ],
    )
    def test_band(self, old, new):
        assert band_legacy_rating(old) == Decimal(new)

    def test_out_of_range_clamps(self):
        """The old field validated 50–100, but a hand-edited row shouldn't crash."""
        assert band_legacy_rating(10) == Decimal("1.0")
        assert band_legacy_rating(140) == Decimal("5.0")

    def test_monotonic(self):
        results = [band_legacy_rating(score) for score in range(50, 101)]
        assert results == sorted(results)

    def test_every_band_is_a_valid_choice(self):
        valid = {value for value, _ in RATING_CHOICES}
        assert {rating for _, rating in LEGACY_BANDS} <= valid

    def test_bands_cover_the_whole_old_scale(self):
        assert LEGACY_BANDS[0][0] >= 50 and LEGACY_BANDS[-1][0] >= 100


class TestScale:
    def test_nine_choices_from_one_to_five(self):
        assert [value for value, _ in RATING_CHOICES] == [
            Decimal(str(n / 2)) for n in range(2, 11)
        ]

    def test_anchors_are_the_whole_numbers(self):
        assert list(RATING_ANCHORS) == [Decimal(n) for n in range(1, 6)]

    @pytest.mark.parametrize(
        ("rating", "shown"), [("5.0", "5"), ("4.5", "4.5"), ("1.0", "1"), ("3.5", "3.5")]
    )
    def test_format_strips_the_trailing_zero(self, rating, shown):
        assert format_rating(Decimal(rating)) == shown

    def test_legend_spells_out_both_ends(self):
        """The AI prompts ship this; a bare number tells a model nothing."""
        assert "1=never again" in SCALE_LEGEND
        assert "5=amazing" in SCALE_LEGEND


class TestCriticScore:
    def test_accepts_a_published_score(self, vintage):
        vintage.critic_score = 94
        vintage.critic_source = "Wine Spectator 2022"
        vintage.full_clean()
        vintage.save()
        vintage.refresh_from_db()
        assert vintage.critic_score == 94

    def test_blank_by_default(self, vintage):
        assert vintage.critic_score is None
        assert vintage.critic_source == ""

    @pytest.mark.parametrize("score", [49, 101])
    def test_rejects_out_of_range(self, vintage, score):
        vintage.critic_score = score
        with pytest.raises(ValidationError):
            vintage.full_clean()
