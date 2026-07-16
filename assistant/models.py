"""AI feature models: every Claude interaction is persisted for auditability,
and token usage is logged per call so cost stays visible.
"""

from django.conf import settings
from django.db import models

from core.models import BaseModel


class ApiUsage(BaseModel):
    """One row per Claude API call; the cost ledger."""

    feature = models.CharField(max_length=50)  # e.g. "scan_label", "pair_food"
    model = models.CharField(max_length=100)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created"]
        verbose_name_plural = "API usage"

    def __str__(self):
        return f"{self.feature} ({self.input_tokens}→{self.output_tokens} tok)"


class TasteProfile(BaseModel):
    """A user's palate in their own words — included in every recommendation
    prompt so answers are tailored per person. Edited freely over time; the
    AI can draft an update from tasting history, but the user owns the text.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="taste_profile"
    )
    text = models.TextField(
        blank=True,
        help_text=(
            "What you love and avoid, favorite regions/grapes, adventurousness, "
            "typical budget at restaurants vs retail."
        ),
    )

    # Restaurant-menu preferences: which pick categories this user wants,
    # plus standing instructions that ride along with every menu scan.
    menu_taste_match = models.BooleanField(
        default=True, verbose_name="Your taste match (bottles most like what you love)"
    )
    menu_best_value = models.BooleanField(
        default=True, verbose_name="Best value (quality-for-price, ranked across price tiers)"
    )
    menu_most_interesting = models.BooleanField(
        default=True, verbose_name="Most interesting (rare grapes, unusual regions)"
    )
    menu_notes = models.TextField(
        blank=True,
        verbose_name="Standing menu instructions",
        help_text=(
            "Always applied to restaurant lists, e.g. 'I usually want the "
            "cost-effective option unless it's a special occasion' or "
            "'bottles only, never glasses'."
        ),
    )

    def __str__(self):
        return f"Taste profile: {self.user.get_username()}"


class Prospect(BaseModel):
    """An UNVETTED capture — a wine on the radar that the owner hasn't decided on.

    Sources: research byproducts, explicit "suggest 5" asks, and store scans
    he didn't buy. Deliberately separate from the catalog so AI suggestions
    and raw captures never masquerade as inventory. Promotion goes through
    the intake form, whose cellar/wishlist/tried modes ARE the vetting gate.
    """

    class Source(models.TextChoices):
        RESEARCH = "research", "Came up in research"
        REQUESTED = "requested", "Asked the sommelier"
        SCANNED = "scanned", "Scanned, didn't buy"

    class Status(models.TextChoices):
        WATCHING = "watching", "Watching"
        PROMOTED = "promoted", "Promoted"
        DISMISSED = "dismissed", "Dismissed"

    producer_name = models.CharField(max_length=200)
    wine_name = models.CharField(max_length=200)
    wine_type = models.CharField(max_length=20, blank=True)
    varietals = models.CharField(max_length=200, blank=True)
    region = models.CharField(max_length=200, blank=True)
    why = models.TextField(blank=True, help_text="The AI's reasoning, or scan context")
    source = models.CharField(max_length=20, choices=Source.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.WATCHING)
    style_vector = models.JSONField(
        null=True, blank=True, help_text="Optional taste fingerprint (map dashed dot)"
    )
    label_scan = models.ForeignKey(
        "LabelScan", on_delete=models.SET_NULL, null=True, blank=True, related_name="prospects"
    )
    promoted_wine = models.ForeignKey(
        "cellar.Wine", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="prospects",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="prospects",
    )

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.producer_name} {self.wine_name} ({self.get_status_display()})"


class DistributorEmail(BaseModel):
    """A distributor marketing email pulled from the dedicated mailbox,
    plus the AI digest (offers + buy/skip suggestions) generated from it.
    """

    class Status(models.TextChoices):
        ANALYZED = "analyzed", "Analyzed"
        FAILED = "failed", "Failed"

    message_uid = models.CharField(max_length=200, unique=True)  # idempotency key
    sender = models.CharField(max_length=300, blank=True)
    subject = models.CharField(max_length=500, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    raw_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    reviewed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-received_at", "-created"]

    def __str__(self):
        return f"{self.subject or self.sender or self.message_uid} ({self.status})"

    @property
    def actionable_offers(self):
        """Offers the digest marked buy/consider (what the dashboard surfaces)."""
        if not self.result:
            return []
        return [o for o in self.result.get("offers", []) if o.get("action") in ("buy", "consider")]


class MenuAnalysis(BaseModel):
    """A restaurant wine-list photo and the advice generated from it."""

    class Status(models.TextChoices):
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    image = models.ImageField(upload_to="menu_scans/%Y/%m/")
    food = models.CharField(max_length=300, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="menu_analyses"
    )

    class Meta:
        ordering = ["-created"]
        verbose_name_plural = "menu analyses"

    def __str__(self):
        return f"Menu analysis {self.created:%Y-%m-%d %H:%M} ({self.status})"


class LabelScan(BaseModel):
    """A wine-label photo and what the model extracted from it."""

    class Status(models.TextChoices):
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    image = models.ImageField(upload_to="label_scans/%Y/%m/")
    status = models.CharField(max_length=20, choices=Status.choices)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="label_scans"
    )
    vintage = models.ForeignKey(
        "cellar.Vintage", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="label_scans",
        help_text="The vintage this scan became once confirmed through intake",
    )

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"Label scan {self.created:%Y-%m-%d %H:%M} ({self.status})"
