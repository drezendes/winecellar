"""Pydantic schemas for structured outputs from the sommelier service.

Field values that feed cellar models use the same choice values as those
models (e.g. wine_type matches cellar.Wine.WineType).
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

WineType = Literal["red", "white", "rose", "sparkling", "dessert", "fortified"]


class LabelData(BaseModel):
    """Extracted from a wine bottle label photo."""

    producer_name: str = Field(description="Winery/producer name as shown on the label")
    producer_region: str = Field(default="", description="Region if identifiable, else empty")
    producer_country: str = Field(default="", description="Country if identifiable, else empty")
    wine_name: str = Field(
        description="Cuvée/bottling name; if the label shows only producer + appellation, use the appellation"
    )
    wine_type: WineType
    varietals: str = Field(default="", description="Comma-separated grape varieties, if known")
    appellation: str = Field(default="", description="Appellation/AVA/DOCG etc., if shown")
    year: Optional[int] = Field(default=None, description="Vintage year; null for NV")
    abv: Optional[float] = Field(default=None, description="Alcohol % if printed on the label")
    confidence_notes: str = Field(
        default="",
        description="One short sentence flagging anything uncertain or guessed, else empty",
    )


class DrinkingWindow(BaseModel):
    """Suggested drinking window for a vintage."""

    drink_from: int = Field(description="First year the wine is likely drinking well")
    drink_until: int = Field(description="Last year before likely decline")
    rationale: str = Field(description="2-3 sentences on why, mentioning structure/style")


class WineDossier(BaseModel):
    """Background research on a wine, gathered from the web (producer site first)."""

    producer_background: str = Field(
        description="2-3 sentences on the producer: who, where, house style"
    )
    style_and_tasting: str = Field(
        description="What this wine is like per the producer/critics: structure, flavors, oak, style"
    )
    vintage_notes: str = Field(
        default="", description="Anything specific to this vintage year, if found"
    )
    drinking_advice: str = Field(
        default="", description="Aging/serving guidance from the producer or critics, if found"
    )
    typical_price: str = Field(
        default="", description="Typical retail price if seen, e.g. '$45-55'"
    )
    # Catalog facts often missing from the label (e.g. unlabeled field blends);
    # used to backfill blank inventory fields — never overwriting user data.
    varietals: str = Field(
        default="",
        description="Comma-separated grape varieties only, no commentary, "
        "if the notes state them (e.g. 'Touriga Nacional, Tinta Roriz')",
    )
    appellation: str = Field(
        default="", description="Appellation/DO/AVA/DOCG if the notes state it"
    )
    abv: Optional[float] = Field(default=None, description="Alcohol % if the notes state it")
    keeps_open_days: Optional[int] = Field(
        default=None,
        description="Honest estimate of how many days an OPENED bottle of this wine "
        "stays good (e.g. tawny port ~30-60, ruby ~3-5, crisp white ~3-4, "
        "structured red ~2-3). Null if the style makes it genuinely unclear.",
    )
    producer_region: str = Field(
        default="", description="Producer's home region if the notes state it"
    )
    producer_country: str = Field(
        default="", description="Producer's country if the notes state it"
    )
    sources: list[str] = Field(
        default_factory=list, description="URLs actually used, producer site first"
    )


class Pairing(BaseModel):
    """One recommended bottle from the cellar for a dish."""

    vintage_id: str = Field(description="The exact id shown in the inventory list")
    wine_label: str = Field(description="Producer + wine + vintage, as shown in the inventory")
    reasoning: str = Field(description="1-2 sentences on why this pairing works")


class PairingAdvice(BaseModel):
    """Cellar-grounded pairing suggestions for a dish."""

    pairings: list[Pairing] = Field(
        description="Up to 3 picks from the inventory list, best first. Empty if nothing fits."
    )
    general_advice: str = Field(
        default="",
        description="Brief style guidance, especially when the cellar has no good match",
    )


class MenuOffering(BaseModel):
    """One wine parsed off a restaurant list."""

    name: str = Field(description="Producer/wine/vintage as printed on the menu")
    style: str = Field(default="", description="e.g. 'red — Nebbiolo', 'sparkling'")
    price: str = Field(default="", description="Price as printed, e.g. '$68' — empty if absent")


class MenuRecommendation(BaseModel):
    name: str = Field(description="Menu wine being recommended, matching an offering name")
    price: str = Field(default="")
    reasoning: str = Field(description="1-2 sentences: why, given the diner's tastes and meal")


class ProfileDraft(BaseModel):
    """AI-drafted taste profile text for the user to review and edit."""

    profile_text: str = Field(
        description="First-person taste profile, ~100-200 words: loves, avoids, "
        "favorite regions/grapes, adventurousness, budget habits"
    )


class EmailOffer(BaseModel):
    """One wine offer parsed from a distributor email, with a verdict."""

    wine: str = Field(description="Producer + wine + vintage as described in the email")
    vintage: Optional[int] = Field(default=None)
    price: str = Field(default="", description="Offer price/terms as stated, e.g. '$42/btl'")
    deal_terms: str = Field(default="", description="Case discounts, deadlines, allocations")
    action: Literal["buy", "consider", "skip"] = Field(
        description="buy = clear fit for this cellar; consider = interesting, judgment call; skip = pass"
    )
    reasoning: str = Field(description="1-2 sentences grounded in the cellar and taste history")


class EmailDigest(BaseModel):
    """Structured digest of a distributor marketing email."""

    distributor: str = Field(default="", description="Sender/distributor name if identifiable")
    summary: str = Field(description="1-2 sentence summary of what the email is offering")
    offers: list[EmailOffer] = Field(description="Every distinct wine offer in the email")


class MenuAdvice(BaseModel):
    """Parsed restaurant wine list + ranked picks per requested category.

    Categories are ranked lists (best first, prices included) so the diner
    can see the ordering and choose their own price point.
    """

    offerings: list[MenuOffering] = Field(description="Every wine legible on the menu photo")
    taste_match: list[MenuRecommendation] = Field(
        default_factory=list,
        description="Up to 3 bottles most aligned with the diner's taste profile and "
        "rating history, ranked best-fit first, with prices",
    )
    best_value: list[MenuRecommendation] = Field(
        default_factory=list,
        description="Up to 3 ranked by quality-for-price (not merely cheapest); span "
        "price tiers where the list allows so the diner can pick their spend",
    )
    most_interesting: list[MenuRecommendation] = Field(
        default_factory=list,
        description="Up to 3 distinctive/adventurous bottles ranked — rare grape, "
        "unusual region, standout producer",
    )
    general_note: str = Field(default="", description="One short overall note, if useful")
