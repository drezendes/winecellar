"""Style-vector generation for the taste map.

`backfill_styles` is the importable engine; the management command
`assistant_backfill_styles` is its CLI shim. Research (assistant.tasks)
also refreshes a wine's vector opportunistically after a dossier lands.
"""

import logging

from django.utils import timezone

from cellar.models import Wine

from . import sommelier

logger = logging.getLogger("winecellar.assistant")


def save_style(wine, style):
    """Persist a StyleVector onto the wine row (update-style, thread-safe)."""
    Wine.objects.filter(pk=wine.pk).update(
        style_vector=style.model_dump(),
        style_caption=style.caption[:200],
        modified=timezone.now(),
    )


def refresh_style(wine):
    """Generate + save one wine's vector. Raises SommelierError on failure."""
    style = sommelier.style_vector(wine)
    save_style(wine, style)
    return style


def backfill_styles(progress=None, refresh=False):
    """Generate style vectors for wines missing one (all wines with --refresh).

    Idempotent; each wine is one cheap AI call, so a failure skips that wine
    and continues. Returns stats.
    """
    progress = progress or (lambda message: None)
    wines = Wine.objects.select_related("producer").order_by("producer__name", "name")
    if not refresh:
        wines = wines.filter(style_vector__isnull=True)

    stats = {"done": 0, "failed": 0}
    total = wines.count()
    for index, wine in enumerate(wines, start=1):
        try:
            style = refresh_style(wine)
        except sommelier.SommelierError as exc:
            stats["failed"] += 1
            logger.error("style vector failed for %s: %s", wine, exc)
            progress(f"[{index}/{total}] FAILED {wine}: {exc}")
            continue
        stats["done"] += 1
        progress(f"[{index}/{total}] {wine} — {style.caption}")
    return stats
