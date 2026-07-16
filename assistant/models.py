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
    occasion = models.CharField(max_length=300, blank=True)
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

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"Label scan {self.created:%Y-%m-%d %H:%M} ({self.status})"
