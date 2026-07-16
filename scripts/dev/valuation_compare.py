"""Compare memory-based vs web-search valuation on the current dev bottles.

LIVE API — costs real (small) money. Run:
    .venv\\Scripts\\python.exe scripts\\dev\\valuation_compare.py

What it does:
1. Deletes existing ValuationRuns (dev DB only — they're demo seeds).
2. Runs the REAL valuation path (knowledge-based) → populates run rows.
3. Runs a web-search variant (probe only, not product code) on the same
   vintages: one research pass with web search, then a structuring pass.
4. Prints values side by side + actual token/search cost per approach.

Findings feed the "web search per run?" decision in docs/ideas.md.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from assistant import sommelier, valuation
from assistant.models import ApiUsage, ValuationRun
from assistant.schemas import CellarValuation
from cellar.models import Bottle, Vintage

# Opus 4.8 $/MTok; web-search fees ($10/1k searches) are NOT in token usage —
# reported separately as "≤ N searches" from the cap we set.
IN_RATE, OUT_RATE = 5.00, 25.00


def cost_of(feature):
    rows = ApiUsage.objects.filter(feature=feature)
    tokens_in = sum(r.input_tokens for r in rows)
    tokens_out = sum(r.output_tokens for r in rows)
    return tokens_in, tokens_out, (tokens_in * IN_RATE + tokens_out * OUT_RATE) / 1_000_000


def value_via_web(vintages, max_searches=8):
    """Probe-only web variant: research pass + structuring pass."""
    lines = [
        f"{v.pk} | {v} | {v.wine.get_wine_type_display()}"
        f" | {v.wine.varietals or 'varietals unknown'}"
        f" | {v.wine.appellation or 'appellation unknown'}"
        for v in vintages
    ]
    research = sommelier._web_research(
        "value_cellar_web",
        (
            "Find the CURRENT typical US retail price for a 750 ml bottle of each "
            "wine below (wine-searcher averages or major US retailers). Report "
            "price + source per wine; say plainly when you can't find one.\n\n"
            + "\n".join(lines)
        ),
        max_searches=max_searches,
    )
    structured = sommelier._parse(
        "value_cellar_web",
        messages=[
            {
                "role": "user",
                "content": (
                    "Convert these price research notes into the structure, one item "
                    "per inventory id. Null where no supportable price was found.\n\n"
                    "INVENTORY:\n" + "\n".join(lines) + "\n\nNOTES:\n" + research
                ),
            }
        ],
        schema=CellarValuation,
    )
    return structured, max_searches


def main():
    ApiUsage.objects.filter(feature__in=["value_cellar", "value_cellar_web"]).delete()
    deleted, _ = ValuationRun.objects.all().delete()
    if deleted:
        print(f"cleared {deleted} demo valuation objects")

    vintages = list(
        Vintage.objects.filter(bottles__status__in=Bottle.DRINKABLE_STATUSES)
        .distinct()
        .select_related("wine", "wine__producer")
    )
    print(f"valuing {len(vintages)} vintages: {', '.join(str(v) for v in vintages)}\n")

    # --- memory-based, through the real product path (populates run rows) ---
    run = ValuationRun.objects.create()
    valuation.run_valuation(run.pk)
    run.refresh_from_db()
    if run.status != ValuationRun.Status.COMPLETE:
        raise SystemExit(f"memory run failed: {run.error}")
    memory = {row.vintage_id: row for row in run.valuations.select_related("vintage")}

    # --- web-search probe ---
    web_result, searches_cap = value_via_web(vintages)
    import uuid as uuid_mod

    web = {}
    for item in web_result.items:
        try:
            web[uuid_mod.UUID(item.vintage_id)] = item
        except ValueError:
            continue

    # --- side by side ---
    print(f"{'wine':<38} {'memory':>10} {'web':>10}")
    print("-" * 62)
    for v in vintages:
        mem_row = memory.get(v.pk)
        web_row = web.get(v.pk)
        mem_val = f"${mem_row.per_bottle_value}" if mem_row and mem_row.per_bottle_value else "null"
        web_val = f"${web_row.per_bottle_usd:.0f}" if web_row and web_row.per_bottle_usd else "null"
        print(f"{str(v):<38} {mem_val:>10} {web_val:>10}")
        if mem_row and mem_row.note:
            print(f"    memory: {mem_row.note}")
        if web_row and web_row.note:
            print(f"    web:    {web_row.note}")

    print()
    for feature, label in [("value_cellar", "memory"), ("value_cellar_web", "web")]:
        tokens_in, tokens_out, dollars = cost_of(feature)
        extra = f" + <= {searches_cap} searches (${searches_cap * 0.01:.2f})" if feature.endswith("web") else ""
        print(f"{label:>6}: {tokens_in} in / {tokens_out} out tokens = ${dollars:.3f}{extra}")


if __name__ == "__main__":
    main()
