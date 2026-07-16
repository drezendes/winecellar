"""Cellar valuation: runs, the cost-basis rule, and the paid-vs-worth series.

The rules (docs/ideas.md, stress-tested with the owner 2026-07-16):
- purchase_price is ACTUALS-ONLY — never estimated, never edited by AI.
- A bottle's COST BASIS = purchase_price if set, else its FIRST valuation
  mark while held. Missing actuals therefore contribute zero phantom gain.
- Estimated values are per-vintage per-run (750 ml basis); bottle values
  scale by size. Unpriceable vintages carry null — skipped, never guessed.
- The series values the bottles HELD AT EACH RUN, so appreciation is never
  confused with composition changes (buying more ≠ gaining value).
"""

import logging
import threading
import uuid
from decimal import Decimal

from django.db import close_old_connections
from django.utils import timezone

from cellar.models import Bottle, Vintage

from . import sommelier
from .models import ValuationRun, VintageValuation

logger = logging.getLogger("winecellar.assistant")

# 750 ml basis → per-size multipliers.
SIZE_FACTORS = {
    Bottle.Size.HALF: Decimal("0.5"),
    Bottle.Size.STANDARD: Decimal("1"),
    Bottle.Size.LITER: Decimal("1000") / Decimal("750"),
    Bottle.Size.MAGNUM: Decimal("2"),
    Bottle.Size.DOUBLE_MAGNUM: Decimal("4"),
}


def start_valuation(user=None):
    """Create a pending run and value the cellar in a background thread."""
    run = ValuationRun.objects.create(created_by=user)
    thread = threading.Thread(target=run_valuation, args=(run.pk,), daemon=True)
    thread.start()
    return run, thread


def run_valuation(run_pk):
    """Worker body: one batched AI call, one VintageValuation row per vintage."""
    close_old_connections()
    try:
        try:
            vintages = list(
                Vintage.objects.filter(bottles__status__in=Bottle.DRINKABLE_STATUSES)
                .distinct()
                .select_related("wine", "wine__producer")
            )
            if not vintages:
                raise sommelier.SommelierError("No drinkable bottles to value.")
            result = sommelier.value_cellar(vintages)
        except Exception as exc:  # noqa: BLE001 — failures land on the row
            logger.exception("valuation run %s failed", run_pk)
            ValuationRun.objects.filter(pk=run_pk).update(
                status=ValuationRun.Status.FAILED, error=str(exc), modified=timezone.now()
            )
            return

        run = ValuationRun.objects.get(pk=run_pk)
        known = {v.pk: v for v in vintages}
        saved = 0
        for item in result.items:
            try:
                vintage_pk = uuid.UUID(item.vintage_id)
            except ValueError:
                continue  # hallucinated id
            vintage = known.get(vintage_pk)
            if vintage is None:
                continue
            value = (
                Decimal(str(round(item.per_bottle_usd, 2)))
                if item.per_bottle_usd is not None
                else None
            )
            VintageValuation.objects.update_or_create(
                run=run, vintage=vintage,
                defaults={"per_bottle_value": value, "note": item.note[:300]},
            )
            saved += 1
        ValuationRun.objects.filter(pk=run_pk).update(
            status=ValuationRun.Status.COMPLETE,
            general_note=result.general_note,
            modified=timezone.now(),
        )
        logger.info("valuation run %s complete: %s vintages", run_pk, saved)
    finally:
        close_old_connections()


def _bottle_factor(bottle):
    return SIZE_FACTORS.get(bottle.size, Decimal("1"))


def _held_at(bottle, moment):
    """Was this bottle in the cellar (or open) at `moment`?"""
    if bottle.created > moment:
        return False
    if bottle.status in Bottle.DRINKABLE_STATUSES:
        return True
    # Consumed/gifted: consumed_date is a date; treat end-of-day as the cutoff.
    if bottle.consumed_date is None:
        return False
    return bottle.consumed_date >= moment.date()


def bottle_basis(bottle, valuation_history):
    """The cost-basis rule: actual price, else first mark while held.

    valuation_history: vintage_id → [(run_created, per_bottle_value), ...]
    ascending by run date, priced entries only. Returns (Decimal|None, kind)
    with kind in 'actual' | 'first_mark' | 'none'.
    """
    if bottle.purchase_price is not None:
        return bottle.purchase_price, "actual"
    for run_created, value in valuation_history.get(bottle.vintage_id, []):
        if run_created >= bottle.created:
            return value * _bottle_factor(bottle), "first_mark"
    return None, "none"


def _history():
    """vintage_id → ascending [(run_created, value)] for priced valuations."""
    history = {}
    rows = (
        VintageValuation.objects.filter(
            per_bottle_value__isnull=False, run__status=ValuationRun.Status.COMPLETE
        )
        .select_related("run")
        .order_by("run__created")
    )
    for row in rows:
        history.setdefault(row.vintage_id, []).append(
            (row.run.created, row.per_bottle_value)
        )
    return history


def summarize():
    """Current paid-vs-worth headline + per-run series.

    Returns None when no completed runs exist yet.
    """
    runs = list(
        ValuationRun.objects.filter(status=ValuationRun.Status.COMPLETE).order_by("created")
    )
    if not runs:
        return None
    history = _history()
    bottles = list(Bottle.objects.select_related("vintage"))

    series = []
    for run in runs:
        values = {
            row.vintage_id: row.per_bottle_value
            for row in run.valuations.filter(per_bottle_value__isnull=False)
        }
        est = Decimal("0")
        basis_total = Decimal("0")
        counted = 0
        basis_kinds = {"actual": 0, "first_mark": 0, "none": 0}
        for bottle in bottles:
            if not _held_at(bottle, run.created):
                continue
            value = values.get(bottle.vintage_id)
            if value is None:
                continue  # unpriceable at this run — excluded from both sides
            basis, kind = bottle_basis(bottle, history)
            if basis is None:
                # No actual and no mark yet at this run: its first mark IS this
                # run, so basis == value (zero gain at first sight — the rule).
                basis, kind = value * _bottle_factor(bottle), "first_mark"
            est += value * _bottle_factor(bottle)
            basis_total += basis
            counted += 1
            basis_kinds[kind] += 1
        series.append(
            {
                "run": run,
                "estimated": est,
                "basis": basis_total,
                "gain": est - basis_total,
                "bottles": counted,
                "basis_kinds": basis_kinds,
            }
        )

    latest = series[-1]
    unpriced = (
        runs[-1].valuations.filter(per_bottle_value__isnull=True)
        .select_related("vintage__wine__producer")
    )
    return {"series": series, "latest": latest, "unpriced": list(unpriced)}
