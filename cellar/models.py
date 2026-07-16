"""Inventory core: producers, wines, vintages, physical bottles, tasting notes.

Hierarchy: Producer → Wine (a bottling/cuvée) → Vintage (a year, or NV) →
Bottle (a physical bottle). Drinking windows live on Vintage; tasting notes
attach to a Vintage (optionally a specific Bottle).
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import BaseModel


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
        """Vintages that still have bottles in the cellar, annotated with the count."""
        return self.annotate(
            in_cellar=models.Count(
                "bottles", filter=models.Q(bottles__status=Bottle.Status.IN_CELLAR)
            )
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
    """One year (or NV) of a wine; the drinking window lives here."""

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
        return self.bottles.filter(status=Bottle.Status.IN_CELLAR)

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
        CONSUMED = "consumed", "Consumed"
        GIFTED = "gifted", "Gifted"

    vintage = models.ForeignKey(Vintage, on_delete=models.PROTECT, related_name="bottles")
    size = models.CharField(max_length=10, choices=Size.choices, default=Size.STANDARD)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_CELLAR)
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    purchase_source = models.CharField(max_length=200, blank=True)
    location = models.CharField(
        max_length=200, blank=True, help_text="Free text, e.g. 'rack B, row 3'"
    )
    consumed_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.vintage} ({self.get_size_display()}, {self.get_status_display()})"

    def mark_consumed(self, on_date=None):
        self.status = self.Status.CONSUMED
        self.consumed_date = on_date or timezone.localdate()
        self.save(update_fields=["status", "consumed_date", "modified"])

    def mark_gifted(self, on_date=None):
        self.status = self.Status.GIFTED
        self.consumed_date = on_date or timezone.localdate()
        self.save(update_fields=["status", "consumed_date", "modified"])


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
