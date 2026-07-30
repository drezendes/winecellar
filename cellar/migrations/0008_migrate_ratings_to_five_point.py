"""Band the old 50–100 personal ratings onto the 5-point scale.

The old scale is compressed in practice (nearly everything lands 85–95), so
these bands are deliberately uneven rather than a linear remap. The table
mirrors `cellar.ratings.LEGACY_BANDS` — duplicated on purpose, because a
migration must keep working after app code moves on; `tests/test_ratings.py`
guards both against the table documented in `docs/rating_scale_plan.md`.

Every conversion is logged old → new. That log is the owner's review artifact:
the mapping is a judgement call, so he eyeballs the list afterwards and
hand-adjusts any bottle the bands got wrong.
"""

import logging
from decimal import Decimal

from django.db import migrations

logger = logging.getLogger("winecellar")

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


def band(score):
    for upper, rating in LEGACY_BANDS:
        if score <= upper:
            return rating
    return LEGACY_BANDS[-1][1]


def to_five_point(apps, schema_editor):
    TastingNote = apps.get_model("cellar", "TastingNote")
    notes = (
        TastingNote.objects.filter(rating__isnull=False)
        .select_related("vintage__wine__producer")
        .order_by("tasted_date")
    )

    converted = []
    for note in notes:
        note.rating_5 = band(note.rating)
        converted.append(note)

    if not converted:
        return

    TastingNote.objects.bulk_update(converted, ["rating_5"])

    lines = ["Rating scale migration — review these and hand-adjust any that read wrong:"]
    for note in converted:
        vintage = note.vintage
        label = f"{vintage.wine.producer.name} {vintage.wine.name} {vintage.year or 'NV'}"
        lines.append(f"  {note.tasted_date}  {label}: {note.rating}/100 → {note.rating_5}/5")
    report = "\n".join(lines)

    logger.info(report)
    print(report)  # noqa: T201 — deploy-time review artifact, not app output


def back_to_null(apps, schema_editor):
    """The old `rating` column is untouched here, so undoing is just a clear."""
    TastingNote = apps.get_model("cellar", "TastingNote")
    TastingNote.objects.filter(rating_5__isnull=False).update(rating_5=None)


class Migration(migrations.Migration):

    dependencies = [
        ('cellar', '0007_tastingnote_rating_5_vintage_critic_score_and_more'),
    ]

    operations = [
        migrations.RunPython(to_five_point, back_to_null),
    ]
