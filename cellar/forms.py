"""Forms for the intake and update flows.

BottleIntakeForm is the single entry point for getting wine into the cellar:
it get-or-creates the Producer → Wine → Vintage chain and creates N bottles.
The AI label scanner (phase 3) prefills this same form — AI proposes, the
human confirms here before anything is saved.
"""

from django import forms
from django.db import transaction
from django.utils import timezone

from .models import Bottle, Producer, TastingNote, Vintage, Wine

CURRENT_YEAR = timezone.localdate().year


class BottleIntakeForm(forms.Form):
    MODE_CHOICES = [
        ("cellar", "Add bottles to the cellar"),
        ("wishlist", "Wishlist — want to buy"),
        ("tried", "Just a record — tasted it, don't own it"),
    ]
    # Fields only relevant when bottles are physically entering the cellar;
    # the template hides them for wishlist/tried modes.
    BOTTLE_FIELDS = (
        "quantity", "size", "purchase_date", "purchase_price", "purchase_source", "location"
    )

    mode = forms.ChoiceField(
        choices=MODE_CHOICES, initial="cellar", required=False,
        widget=forms.RadioSelect, label="What is this?",
    )
    # Set by the label-scan redirect; links the confirmed vintage back to the
    # scan so the label photo shows on the wine page.
    label_scan = forms.UUIDField(required=False, widget=forms.HiddenInput)

    producer_name = forms.CharField(max_length=200, label="Producer")
    producer_region = forms.CharField(max_length=200, required=False, label="Region")
    producer_country = forms.CharField(max_length=100, required=False, label="Country")

    wine_name = forms.CharField(max_length=200, label="Wine name")
    wine_type = forms.ChoiceField(choices=Wine.WineType.choices)
    varietals = forms.CharField(max_length=200, required=False)
    appellation = forms.CharField(max_length=200, required=False)

    year = forms.IntegerField(
        required=False, min_value=1900, max_value=CURRENT_YEAR + 1,
        help_text="Blank for non-vintage",
    )
    abv = forms.DecimalField(required=False, max_digits=4, decimal_places=1, label="ABV %")
    drink_from = forms.IntegerField(required=False, min_value=1900, max_value=2200)
    drink_until = forms.IntegerField(required=False, min_value=1900, max_value=2200)

    quantity = forms.IntegerField(min_value=1, max_value=200, initial=1, required=False)
    size = forms.ChoiceField(choices=Bottle.Size.choices, initial=Bottle.Size.STANDARD)
    purchase_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    purchase_price = forms.DecimalField(
        required=False, max_digits=8, decimal_places=2, label="Price per bottle"
    )
    purchase_source = forms.CharField(max_length=200, required=False)
    location = forms.CharField(max_length=200, required=False)

    def wine_fields(self):
        """Bound fields describing the wine itself (always shown)."""
        return [
            self[name] for name in self.fields
            if name not in self.BOTTLE_FIELDS and name != "mode" and not self[name].is_hidden
        ]

    def bottle_fields(self):
        """Bound fields for physical bottles (cellar mode only)."""
        return [self[name] for name in self.BOTTLE_FIELDS]

    def clean(self):
        cleaned = super().clean()
        cleaned["mode"] = cleaned.get("mode") or "cellar"
        drink_from, drink_until = cleaned.get("drink_from"), cleaned.get("drink_until")
        if drink_from and drink_until and drink_from > drink_until:
            raise forms.ValidationError("Drink-from year is after drink-until year.")
        if cleaned["mode"] == "cellar" and not cleaned.get("quantity"):
            self.add_error("quantity", "How many bottles are going into the cellar?")
        return cleaned

    @transaction.atomic
    def save(self):
        """Get-or-create the Producer → Wine → Vintage chain; bottles only in cellar mode."""
        data = self.cleaned_data

        producer, _ = Producer.objects.get_or_create(
            name=data["producer_name"].strip(),
            defaults={
                "region": data.get("producer_region", ""),
                "country": data.get("producer_country", ""),
            },
        )
        wine, _ = Wine.objects.get_or_create(
            producer=producer,
            name=data["wine_name"].strip(),
            defaults={
                "wine_type": data["wine_type"],
                "varietals": data.get("varietals", ""),
                "appellation": data.get("appellation", ""),
            },
        )
        vintage, created = Vintage.objects.get_or_create(
            wine=wine,
            year=data.get("year"),
            defaults={
                "abv": data.get("abv"),
                "drink_from": data.get("drink_from"),
                "drink_until": data.get("drink_until"),
            },
        )
        if not created:
            # Fill window/abv only where the existing vintage has no value —
            # the intake form never overwrites curated data.
            updates = []
            for field in ("abv", "drink_from", "drink_until"):
                if getattr(vintage, field) is None and data.get(field) is not None:
                    setattr(vintage, field, data[field])
                    updates.append(field)
            if updates:
                vintage.save(update_fields=updates + ["modified"])

        if data["mode"] == "wishlist":
            if not vintage.wishlist:
                vintage.wishlist = True
                vintage.save(update_fields=["wishlist", "modified"])
            return vintage, []
        if data["mode"] == "tried":
            return vintage, []

        # Cellar mode: buying a wishlisted wine resolves the wishlist entry.
        if vintage.wishlist:
            vintage.wishlist = False
            vintage.save(update_fields=["wishlist", "modified"])

        bottles = [
            Bottle(
                vintage=vintage,
                size=data["size"],
                purchase_date=data.get("purchase_date"),
                purchase_price=data.get("purchase_price"),
                purchase_source=data.get("purchase_source", ""),
                location=data.get("location", ""),
            )
            for _ in range(data["quantity"])
        ]
        Bottle.objects.bulk_create(bottles)
        return vintage, bottles


class VintageWindowForm(forms.ModelForm):
    class Meta:
        model = Vintage
        fields = ["abv", "drink_from", "drink_until", "window_rationale"]

    def clean(self):
        cleaned = super().clean()
        drink_from, drink_until = cleaned.get("drink_from"), cleaned.get("drink_until")
        if drink_from and drink_until and drink_from > drink_until:
            raise forms.ValidationError("Drink-from year is after drink-until year.")
        return cleaned


class TastingNoteForm(forms.ModelForm):
    class Meta:
        model = TastingNote
        fields = ["tasted_date", "rating", "notes"]
        widgets = {
            "tasted_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 5}),
        }
