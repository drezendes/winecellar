"""Background execution for slow AI work (currently: dossier research).

One daemon thread per request — no queue or broker, which is plenty for a
household app. The state machine lives on the Vintage row (dossier_status),
so a thread that dies or a server restart just leaves a stale 'pending' that
Vintage.dossier_state ages into 'failed' after RESEARCH_TIMEOUT, where the UI
offers a retry.
"""

import logging
import threading

from django.db import close_old_connections
from django.utils import timezone

from cellar.models import Vintage

from . import sommelier

logger = logging.getLogger("winecellar.assistant")


def start_research(vintage):
    """Mark the vintage as researching and kick off the worker thread."""
    vintage.dossier_status = Vintage.DossierStatus.PENDING
    vintage.dossier_error = ""
    vintage.dossier_requested_at = timezone.now()
    vintage.save(
        update_fields=["dossier_status", "dossier_error", "dossier_requested_at", "modified"]
    )
    thread = threading.Thread(target=run_research, args=(vintage.pk,), daemon=True)
    thread.start()
    return thread


def run_research(vintage_pk):
    """Worker body: research the wine and write the outcome back to the row.

    Uses queryset .update() so a slow run never clobbers fields edited in the
    meantime; auto_now doesn't fire on .update(), hence the explicit modified.
    """
    close_old_connections()
    try:
        try:
            vintage = Vintage.objects.get(pk=vintage_pk)
            dossier = sommelier.research_wine(vintage)
        except Exception as exc:  # noqa: BLE001 — any failure must land on the row, not die with the thread
            logger.exception("dossier research failed for vintage %s", vintage_pk)
            Vintage.objects.filter(pk=vintage_pk).update(
                dossier_status=Vintage.DossierStatus.FAILED,
                dossier_error=str(exc),
                modified=timezone.now(),
            )
            return
        backfilled = _backfill_catalog_fields(vintage, dossier)
        Vintage.objects.filter(pk=vintage_pk).update(
            dossier={**dossier.model_dump(), "backfilled": backfilled},
            dossier_status="",
            dossier_error="",
            modified=timezone.now(),
        )
        logger.info(
            "dossier saved for vintage %s (backfilled: %s)",
            vintage_pk, ", ".join(backfilled) or "nothing",
        )
    finally:
        close_old_connections()


def _backfill_catalog_fields(vintage, dossier):
    """Fill catalog fields the label couldn't provide (e.g. unlabeled blends).

    Blanks only — research never overwrites user-entered data, same rule as
    the intake form. Returns the list of field names filled, which the wine
    page surfaces so it's clear where the values came from.
    """
    from decimal import Decimal

    filled = []
    wine, producer = vintage.wine, vintage.wine.producer

    updates = []
    if not wine.varietals and dossier.varietals:
        wine.varietals = dossier.varietals
        updates.append("varietals")
    if not wine.appellation and dossier.appellation:
        wine.appellation = dossier.appellation
        updates.append("appellation")
    if wine.keeps_open_days is None and dossier.keeps_open_days:
        wine.keeps_open_days = dossier.keeps_open_days
        updates.append("keeps_open_days")
    if updates:
        wine.save(update_fields=updates + ["modified"])
        filled += updates

    updates = []
    if not producer.region and dossier.producer_region:
        producer.region = dossier.producer_region
        updates.append("region")
    if not producer.country and dossier.producer_country:
        producer.country = dossier.producer_country
        updates.append("country")
    if updates:
        producer.save(update_fields=updates + ["modified"])
        filled += updates

    if vintage.abv is None and dossier.abv:
        vintage.abv = Decimal(str(round(dossier.abv, 1)))
        vintage.save(update_fields=["abv", "modified"])
        filled.append("abv")

    return filled
