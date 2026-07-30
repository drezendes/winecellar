"""The personal rating scale: 5 points in half steps, and its anchors.

The 50–100 point scale is built for professionally calibrated palates; this
household wanted five plain categories instead, with half steps for the
"leaning up/down" margin. Whole numbers carry the meaning, halves sit between.

A 50–100 score found in research is a *critic* score — a fact about the
vintage, not about one of our tastings — so it lives on `Vintage.critic_score`,
not here. See `docs/rating_scale_plan.md`.
"""

from decimal import Decimal

# Whole-number anchors, in the owner's own words. Halves read as "between".
RATING_ANCHORS = {
    Decimal("1.0"): "never again",
    Decimal("2.0"): "not good, not offensive",
    Decimal("3.0"): "okay, don't seek out or avoid",
    Decimal("4.0"): "good, I like this",
    Decimal("5.0"): "amazing",
}

RATING_CHOICES = [
    (Decimal("1.0"), "1 — never again"),
    (Decimal("1.5"), "1.5"),
    (Decimal("2.0"), "2 — not good, not offensive"),
    (Decimal("2.5"), "2.5"),
    (Decimal("3.0"), "3 — okay, don't seek out or avoid"),
    (Decimal("3.5"), "3.5"),
    (Decimal("4.0"), "4 — good, I like this"),
    (Decimal("4.5"), "4.5"),
    (Decimal("5.0"), "5 — amazing"),
]

# Spelled out for the AI prompts: bare numbers mean nothing to a model that
# doesn't know whether 4 is good or mediocre.
SCALE_LEGEND = (
    "personal 5-point scale, half steps: "
    + ", ".join(f"{value:.0f}={anchor}" for value, anchor in RATING_ANCHORS.items())
)

# (inclusive upper bound of the old 50–100 score, new rating). The old scale is
# compressed in practice — nearly everything lands 85–95 — so these bands are
# deliberately uneven rather than a linear remap. Mirrored in the data migration
# `0008_migrate_ratings_to_five_point` (migrations must not import app code, so
# the table is duplicated there on purpose; test_ratings.py guards both).
LEGACY_BANDS = [
    (69, Decimal("1.0")),
    (74, Decimal("1.5")),
    (79, Decimal("2.0")),
    (83, Decimal("2.5")),
    (86, Decimal("3.0")),
    (89, Decimal("3.5")),
    (92, Decimal("4.0")),
    (94, Decimal("4.5")),
    (100, Decimal("5.0")),
]


def format_rating(rating):
    """'4.5' / '4' — the trailing .0 stripped, for prompts and plain text.

    Decimal keeps its trailing zero under both str() and ':g' (unlike float),
    and "5.0/5" reads like a precision the scale doesn't have.
    """
    return f"{rating.normalize():f}"


def band_legacy_rating(score):
    """Map an old 50–100 personal rating onto the 5-point scale.

    Scores outside 50–100 clamp to the end bands: the old field validated that
    range, but a hand-edited row shouldn't crash the migration.
    """
    for upper, rating in LEGACY_BANDS:
        if score <= upper:
            return rating
    return LEGACY_BANDS[-1][1]
