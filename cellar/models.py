"""Inventory core: producers, wines, vintages, physical bottles, tasting notes.

Hierarchy: Producer → Wine (a bottling/cuvée) → Vintage (a year, or NV) →
Bottle (a physical bottle). Drinking windows live on Vintage; tasting notes
attach to a Vintage (optionally a specific Bottle).
"""

import datetime

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import BaseModel

# A dossier research run that hasn't written back within this long is treated
# as dead (worker thread crashed or the server restarted mid-run).
RESEARCH_TIMEOUT = datetime.timedelta(minutes=15)


class Producer(BaseModel):
    """A winery / producer."""

    name = models.CharField(max_length=200, unique=True)
    region = models.CharField(max_length=200, blank=True)
    country = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Wine(BaseModel):
    """A specific bottling/cuvée from a producer, independent of vintage."""

    class WineType(models.TextChoices):
        RED = "red", "Red"
        WHITE = "white", "White"
        ROSE = "rose", "Rosé"
        SPARKLING = "sparkling", "Sparkling"
        DESSERT = "dessert", "Dessert"
        FORTIFIED = "fortified", "Fortified"

    producer = models.ForeignKey(Producer, on_delete=models.PROTECT, related_name="wines")
    name = models.CharField(max_length=200)
    wine_type = models.CharField(max_length=20, choices=WineType.choices)
    varietals = models.CharField(
        max_length=200, blank=True, help_text="Comma-separated, e.g. 'Cabernet Sauvignon, Merlot'"
    )
    appellation = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["producer__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["producer", "name"], name="unique_wine_per_producer"),
        ]

    def __str__(self):
        return f"{self.producer.name} {self.name}"


class VintageQuerySet(models.QuerySet):
    def with_stock(self):
        """Vintages with drinkable bottles (unopened or open), annotated with counts."""
        return self.annotate(
            in_cellar=models.Count(
                "bottles", filter=models.Q(bottles__status__in=Bottle.DRINKABLE_STATUSES)
            ),
            open_count=models.Count(
                "bottles", filter=models.Q(bottles__status=Bottle.Status.OPEN)
            ),
        ).filter(in_cellar__gt=0)

    def drink_soon(self, horizon_years=1):
        """In-stock vintages whose window closes within `horizon_years` (or already has)."""
        year = timezone.localdate().year
        return (
            self.with_stock()
            .filter(drink_until__isnull=False, drink_until__lte=year + horizon_years)
            .order_by("drink_until")
        )

    def ready(self):
        """In-stock vintages inside their drinking window."""
        year = timezone.localdate().year
        return (
            self.with_stock()
            .filter(drink_from__isnull=False, drink_from__lte=year)
            .exclude(drink_until__lt=year)
            .order_by("drink_until")
        )


class Vintage(BaseModel):
    """One year (or NV) of a wine; the drinking window lives here.

    A vintage does not need bottles: wishlist entries and wines tasted at
    restaurants are vintages with no Bottle rows.
    """

    class DossierStatus(models.TextChoices):
        PENDING = "pending", "Researching"
        FAILED = "failed", "Failed"

    wine = models.ForeignKey(Wine, on_delete=models.PROTECT, related_name="vintages")
    year = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Blank for non-vintage (NV)"
    )
    abv = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    drink_from = models.PositiveSmallIntegerField(null=True, blank=True)
    drink_until = models.PositiveSmallIntegerField(null=True, blank=True)
    window_rationale = models.TextField(
        blank=True, help_text="Why this window — AI suggestion rationale or your own note"
    )
    dossier = models.JSONField(
        null=True, blank=True,
        help_text="AI web-research background (assistant.schemas.WineDossier shape)",
    )
    dossier_status = models.CharField(
        max_length=20, choices=DossierStatus.choices, blank=True, default="",
        help_text="Blank when idle; research runs in a background thread",
    )
    dossier_error = models.TextField(blank=True)
    dossier_requested_at = models.DateTimeField(null=True, blank=True)
    wishlist = models.BooleanField(
        default=False, help_text="Want to buy — tracked without any bottles in the cellar"
    )

    objects = VintageQuerySet.as_manager()

    class Meta:
        ordering = ["wine__producer__name", "wine__name", "year"]
        constraints = [
            models.UniqueConstraint(fields=["wine", "year"], name="unique_year_per_wine"),
        ]

    def __str__(self):
        return f"{self.wine} {self.year or 'NV'}"

    @property
    def label(self):
        return str(self)

    def bottles_in_cellar(self):
        """Drinkable bottles, open ones first (they want finishing)."""
        return self.bottles.filter(status__in=Bottle.DRINKABLE_STATUSES).order_by(
            "-status", "-created"  # "open" sorts after "in_cellar", so -status leads with open
        )

    def rated_notes(self):
        """Notes that carry a rating, oldest first — the tasting trajectory."""
        return self.tasting_notes.filter(rating__isnull=False).order_by("tasted_date", "created")

    @property
    def rating_trend(self):
        """'improving' | 'declining' | 'steady' | None (needs 2+ rated notes).

        First vs latest rating; changes within ±1 point read as steady since
        that's normal taster noise, not a trajectory.
        """
        ratings = [note.rating for note in self.rated_notes()]
        if len(ratings) < 2:
            return None
        delta = ratings[-1] - ratings[0]
        if delta > 1:
            return "improving"
        if delta < -1:
            return "declining"
        return "steady"

    @property
    def dossier_state(self):
        """'none' | 'pending' | 'failed' | 'ready' — drives the research UI.

        A pending run older than RESEARCH_TIMEOUT reads as failed: the worker
        thread died or the server restarted before writing back, and the UI
        should offer a retry instead of polling forever.
        """
        if self.dossier_status == self.DossierStatus.PENDING:
            expired = (
                self.dossier_requested_at is None
                or timezone.now() - self.dossier_requested_at > RESEARCH_TIMEOUT
            )
            return "failed" if expired else "pending"
        if self.dossier_status == self.DossierStatus.FAILED:
            return "failed"
        return "ready" if self.dossier else "none"

    @property
    def window_status(self):
        """'unknown' | 'hold' | 'ready' | 'past' relative to the current year."""
        year = timezone.localdate().year
        if self.drink_from is None and self.drink_until is None:
            return "unknown"
        if self.drink_from is not None and year < self.drink_from:
            return "hold"
        if self.drink_until is not None and year > self.drink_until:
            return "past"
        return "ready"

    @property
    def window_progress(self):
        """Position of *now* within the drinking window as 0–100 (for the gauge).

        None unless both window years are set. The window is inclusive of the
        drink_until year, so mid-final-year sits near (not at) 100.
        """
        if self.drink_from is None or self.drink_until is None:
            return None
        year = timezone.localdate().year
        span = self.drink_until - self.drink_from + 1
        progress = (year - self.drink_from) / span * 100
        return max(0, min(100, round(progress)))


class Bottle(BaseModel):
    """A physical bottle, in the cellar or already gone."""

    class Size(models.TextChoices):
        HALF = "375ml", "375 ml (half)"
        STANDARD = "750ml", "750 ml"
        LITER = "1l", "1 L"
        MAGNUM = "1.5l", "1.5 L (magnum)"
        DOUBLE_MAGNUM = "3l", "3 L (double magnum)"

    class Status(models.TextChoices):
        IN_CELLAR = "in_cellar", "In cellar"
        OPEN = "open", "Open"  # opened but not finished (port, fridge whites) — opt-in
        CONSUMED = "consumed", "Consumed"
        GIFTED = "gifted", "Gifted"

    # Statuses that count as "we can drink this tonight".
    DRINKABLE_STATUSES = (Status.IN_CELLAR, Status.OPEN)

    vintage = models.ForeignKey(Vintage, on_delete=models.PROTECT, related_name="bottles")
    size = models.CharField(max_length=10, choices=Size.choices, default=Size.STANDARD)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_CELLAR)
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    purchase_source = models.CharField(max_length=200, blank=True)
    location = models.CharField(
        max_length=200, blank=True, help_text="Free text, e.g. 'rack B, row 3'"
    )
    opened_date = models.DateField(null=True, blank=True)
    consumed_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.vintage} ({self.get_size_display()}, {self.get_status_display()})"

    def mark_consumed(self, on_date=None):
        self.status = self.Status.CONSUMED
        self.consumed_date = on_date or timezone.localdate()
        self.save(update_fields=["status", "consumed_date", "modified"])

    def mark_opened(self, on_date=None):
        self.status = self.Status.OPEN
        self.opened_date = on_date or timezone.localdate()
        self.save(update_fields=["status", "opened_date", "modified"])

    def mark_gifted(self, on_date=None):
        self.status = self.Status.GIFTED
        self.consumed_date = on_date or timezone.localdate()
        self.save(update_fields=["status", "consumed_date", "modified"])

    @property
    def days_open(self):
        if self.status != self.Status.OPEN or self.opened_date is None:
            return None
        return (timezone.localdate() - self.opened_date).days


class TastingNote(BaseModel):
    """A tasting record for a vintage (optionally tied to the exact bottle)."""

    vintage = models.ForeignKey(Vintage, on_delete=models.PROTECT, related_name="tasting_notes")
    bottle = models.ForeignKey(
        Bottle, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasting_notes"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tasting_notes"
    )
    tasted_date = models.DateField(default=timezone.localdate)
    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(50), MaxValueValidator(100)],
        help_text="50–100 point scale",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-tasted_date", "-created"]

    def __str__(self):
        return f"{self.vintage} — {self.author.get_username()} {self.tasted_date}"
