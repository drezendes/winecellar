# Rating scale rework — 50–100 → 5-point halves

> **Status: SHIPPED 2026-07-30** — migrations `0007`–`0010`, 236 tests green,
> deployed to prod (winecellar `4d0b2c2`). All 5 rated notes converted; the
> owner's reviewed corrections were applied straight after (see the deploy
> note at the bottom). Kept as the record of *why* the scale is shaped this
> way. Deviations from the plan as written are listed at the end.

## Decision (made by the owner, 2026-07-30)

The 50–100 point scale is for professionally calibrated palates; for the
household it's overwhelming and too granular. Replace the **personal** rating
with a **5-point scale in 0.5 steps** (9 possible values, 1.0–5.0). The whole
numbers carry the owner's own five anchors:

| Rating | Anchor |
|---|---|
| 1 | garbage — never drink again |
| 2 | not good, but not offensive |
| 3 | okay — don't seek out, don't avoid |
| 4 | good — I like this |
| 5 | amazing |

Half-points express "leaning up/down" between anchors — the marginal
information a 10-point scale would have offered, without inventing meanings
for ten levels. This also matches the Vivino/CellarTracker convention, so
numbers stay comparable to community scores.

**The 50–100 scale survives as a *critic score***: a score found during
research is a fact about the **vintage**, not about one of our tastings, so it
moves to `Vintage`, and `TastingNote.rating` becomes purely personal.

## Schema changes

All in `cellar/models.py`. House rules apply: never hand-write **schema**
migrations (`makemigrations`); the **data** migration is hand-written via
`makemigrations cellar --empty` (that's the standard Django mechanism, not a
violation of the rule).

### 1. `TastingNote.rating` → 5-point decimal

Keep the field name `rating`. Target definition:

```python
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

rating = models.DecimalField(
    max_digits=2, decimal_places=1,
    null=True, blank=True,
    choices=RATING_CHOICES,
    help_text="Personal 5-point scale, half steps",
)
```

Put `RATING_CHOICES` at module level in `cellar/models.py` (it's needed by the
form and tests). Because 4.5 doesn't fit the old `PositiveSmallIntegerField`
semantics and 90 doesn't fit `max_digits=2`, the migration must be a
three-step dance, in this order:

1. Schema migration A (`makemigrations`): add a temporary nullable field
   `rating_5` with the target definition above.
2. Data migration (hand-written, `--empty`): `rating_5 = band(rating)` for
   every note with `rating__isnull=False` (mapping below). Provide a reverse
   that nulls `rating_5` so the migration is reversible.
3. Schema migration B (`makemigrations`): remove old `rating`, rename
   `rating_5` → `rating`. (Django will ask interactively about the rename;
   answer or use `RenameField` — verify the generated migration is
   RemoveField + RenameField, not a destructive AddField/RemoveField pair
   that would drop the migrated data.)

### 2. Banded mapping for existing notes

The 50–100 scale is compressed in real use (most scores land 85–95), so a
linear remap is wrong. Bands (monotone, aligned to conventional Wine
Spectator-style bands):

| Old (50–100) | New |
|---|---|
| 50–69 | 1.0 |
| 70–74 | 1.5 |
| 75–79 | 2.0 |
| 80–83 | 2.5 |
| 84–86 | 3.0 |
| 87–89 | 3.5 |
| 90–92 | 4.0 |
| 93–94 | 4.5 |
| 95–100 | 5.0 |

Implement the band function as a plain importable function (suggested:
`cellar/ratings.py::band_legacy_rating(score: int) -> Decimal`) so pytest can
reach it directly and the data migration just imports the table logic
inline (data migrations must not import app code that may drift — copy the
band table into the migration, and test the *function*, which shares the
table by construction — simplest: define the table once in the migration AND
in `cellar/ratings.py`, with a test asserting the module function matches the
documented table).

### 3. Owner review before prod migration

`scripts/dev/preview_rating_migration.py` — read-only script that prints every
rated note: vintage label, tasted date, old rating, proposed new rating. The
owner eyeballs the list (small dataset, minutes) and can hand-adjust any note
afterwards via the note edit form or admin. Run it on the prod DB before
deploying the migration (or accept the bands and spot-check after — owner's
call at deploy time).

### 4. `Vintage.critic_score` (+ source)

```python
critic_score = models.PositiveSmallIntegerField(
    null=True, blank=True,
    validators=[MinValueValidator(50), MaxValueValidator(100)],
    help_text="Official/critic score (50–100) found in research",
)
critic_source = models.CharField(
    max_length=100, blank=True,
    help_text='Who scored it, e.g. "Wine Spectator 2022"',
)
```

Manual entry for now (admin + the vintage edit form if convenient). **Not in
scope:** auto-filling from dossier research — noted as a possible follow-up
(would fit the existing research-backfill pattern; it's a label fact, not a
taste judgment).

## Ripple effects — every touch point

### `cellar/models.py`
- `Vintage.rating_trend` (~line 172): noise threshold **±1 point → ±0.5**
  (`delta > Decimal("0.5")` = improving, `< -0.5` = declining). Update the
  docstring ("changes within ±0.5 read as steady").
- `rated_notes()` unchanged.

### `cellar/forms.py`
- `TastingNoteForm`: no field-list change; with `choices` on the model the
  widget becomes a 9-option select automatically. Verify the empty label
  reads sensibly (e.g. "———") since rating stays optional.
- If `critic_score`/`critic_source` get a form surface, `VintageWindowForm`
  is the existing vintage-edit form — owner's call whether they join it or
  stay admin-only for now.

### `assistant/sommelier.py`
- `cellar_inventory` (~line 249): `f", our avg rating {v.avg_rating:.1f}/5"`.
  Consider appending critic score where present: `f", critics {v.critic_score}/100"`.
- `rating_history` (~line 260): `-rating` ordering still works; format lines
  as `{rating}/5`; change the header to include the anchor legend once, e.g.
  `"Highest-rated recent wines (personal 5-point scale: 1=never again,
  3=okay, 5=amazing):"` — the legend makes the numbers *more* semantic for
  the LLM than the old raw 92/100.
- Style-vector grounding (~line 516): `f"Our note ({note.rating or 'unrated'}): …"`
  still works; make it `{note.rating}/5` when present.

### Templates
- `templates/cellar/wine_detail.html:93` — trajectory points print
  `{{ note.rating }}`; DecimalField renders `4.5` — fine as-is.
- `templates/cellar/wine_detail.html:106` — `/100` → `/5`.
- If critic_score is displayed (recommended: on the wine page near the
  vintage header, mono per the design system — data wears the mono, ink not
  accent), keep it visually distinct from the personal rating.

### `cellar/admin.py`
- `TastingNoteAdmin` unchanged (`rating` in list_display/list_filter still
  valid). Add `critic_score` to the Vintage admin list/fields.

### Tests (`tests/`)
- `test_cellar.py::TestRatingTrajectory`: rewrite literals to the new scale
  (e.g. 90→4.0, 94→4.5 becomes a 3.5→4.5 improving case; steady = within
  ±0.5). Note-creation literals elsewhere (`rating=90`, `rating=93`) → valid
  new values. Form POST test at ~line 471 posts `rating: 93` → `"4.5"`.
- `test_guest.py:146` posts `rating: 90` → `"4"` (or `"4.0"`).
- `test_assistant.py:229` / `test_styles.py:55`: `rating=95` → `Decimal("5.0")`.
- New: band-function tests asserting the documented table (each band edge:
  69→1.0, 70→1.5, 74→1.5, 75→2.0, 83→2.5, 84→3.0, 86→3.0, 87→3.5, 89→3.5,
  90→4.0, 92→4.0, 93→4.5, 94→4.5, 95→5.0).
- New: critic_score validator bounds.

### `scripts/dev/seed_smoke_data.py`
- `rating=92` → `Decimal("4.0")`.

## Order of work

1. `cellar/ratings.py` (band function) + its tests — green.
2. Model changes (`RATING_CHOICES`, `rating_5` add, `critic_score`/`critic_source`)
   → migration A (`makemigrations`).
3. Data migration (`--empty`, band table inline, reversible).
4. Migration B (remove + rename). Inspect all three migration files.
5. Ripple pass: models trend, sommelier strings, templates, admin, forms,
   seed script.
6. Test updates + new tests → full suite green
   (`.venv\Scripts\python.exe -m pytest tests -q`).
7. `scripts/dev/preview_rating_migration.py` — but note: on a dev DB that has
   already migrated, the old column is gone. Either run the preview **before**
   migrating dev, or have the script read the pre-migration values from a
   backup. Simplest honest version: the *data migration itself* logs each
   `old → new` line via the `winecellar` logger (curated stdout is for
   management commands; a migration printing a short table is acceptable and
   becomes the review artifact when it runs on prod).
8. Update `CLAUDE.md` current-state + this doc's status line + `TODO.md`;
   then ask the owner before committing (house rule).

## Deploy note — done 2026-07-30

Deployed 2026-07-30. The migration logged its conversion of every rated note,
and the owner had reviewed that exact mapping against live data beforehand —
then adjusted most of it upward by half a point. Anonymized (this repo is
public; the named record lives in the private infra repo):

| Old | Banded | Owner's final |
|---|---|---|
| 75 | 2.0 | **2.5** |
| 80 | 2.5 | **3.0** |
| 85 | 3.0 | **3.5** |
| 85 | 3.0 | **3.0** |
| 92 | 4.0 | **4.5** |

**The two 85s ended at different values.** No band table can produce that, and
it is the whole argument for "migrate mechanically, then hand-adjust" over
trying to tune the bands until they match remembered bottles. Expect the
banding to be approximately right and individually wrong.

**The deploy was gated on an unrelated find:** checking the restore point
first revealed the nightly backup had been dead for seven nights (CRLF
`/opt/box/.env`). That was fixed and a fresh snapshot taken before this
migration ran — see the infra repo's CLAUDE.md.

## What was built, and where it differs from the plan

Migrations, in order — each auto-generated by `makemigrations`, none
hand-written:

| # | Operation |
|---|---|
| `0007` | AddField `tastingnote.rating_5`, `vintage.critic_score`, `vintage.critic_source` |
| `0008` | RunPython: band old ratings into `rating_5`, log every `old → new` |
| `0009` | RemoveField `tastingnote.rating` (the old 50–100 column) |
| `0010` | RenameField `rating_5` → `rating` |

New files: `cellar/ratings.py` (anchors, choices, `SCALE_LEGEND`,
`format_rating`, `band_legacy_rating`) and `tests/test_ratings.py`.

Deviations, all deliberate:

- **`RATING_CHOICES` lives in `cellar/ratings.py`, not `models.py`.** The plan
  said models.py; a dedicated module keeps the whole scale — anchors, choices,
  legend, banding — in one place, and `models.py` just imports it. Django
  serializes choices literally into migrations, so this creates no
  migration-time import dependency.
- **`format_rating()` was added** (not in the plan). `Decimal("5.0")` keeps its
  trailing zero under `str()` *and* under `:g` (unlike float), so prompts read
  "5.0/5". The helper normalizes to "5"; templates use `|floatformat`.
- **`critic_score`/`critic_source` joined `VintageWindowForm`**, which the plan
  left as the owner's call. Admin-only would have made the field unreachable
  from the phone, and that form already carried a non-window field (`abv`).
  The page's heading widened from "Drinking window" to "Edit — {vintage}".
- **No `scripts/dev/preview_rating_migration.py`.** The plan offered this or
  in-migration logging and called the logging "the simplest honest version";
  a preview script can't read the old column once dev has migrated, so the
  migration's own log is the review artifact.
- **Migration generation needed two mechanical workarounds**, worth knowing if
  this pattern is repeated: `makemigrations --skip-checks` (the admin and the
  note form both reference `rating`, which doesn't exist between `0009` and
  `0010`), and piping `y` to the rename prompt from the **Bash** tool —
  PowerShell's `"y" |` reached Django's `input()` as an empty line and it
  died on EOF.

Verified beyond the suite: a throwaway SQLite DB was migrated to `0007`,
loaded with rows holding old scores (68/72/78/82/85/88/91/93/96 + a NULL),
then migrated forward. All nine banded correctly, the NULL stayed NULL, note
text survived, and the final table has `rating` with no leftover `rating_5`.
