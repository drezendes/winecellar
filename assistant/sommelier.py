"""The AI sommelier: every Claude API call in the project goes through here.

Pattern for each feature: build messages (vision inputs as base64 image
blocks), call `_parse()` with a Pydantic schema (structured outputs), log
token usage to ApiUsage, return the validated object. AI output is always a
*proposal* — views feed it into forms the user confirms.
"""

import base64
import io
import logging

import anthropic
from django.conf import settings
from PIL import Image, ImageOps

from .models import ApiUsage
from .schemas import DrinkingWindow, EmailDigest, LabelData, MenuAdvice, PairingAdvice

logger = logging.getLogger("winecellar.assistant")

# Downscale photos before sending: full-resolution phone photos cost ~3x the
# image tokens and label/menu text survives 1600px fine.
MAX_IMAGE_EDGE = 1600
JPEG_QUALITY = 85
MAX_TOKENS = 16000


class SommelierError(Exception):
    """Raised when an AI call fails or the API key is missing."""


def _get_client():
    if not settings.ANTHROPIC_API_KEY:
        raise SommelierError("ANTHROPIC_API_KEY is not set — add it to .env")
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def prepare_image(file_obj) -> dict:
    """Downscale + re-encode an uploaded photo, return an API image content block."""
    image = Image.open(file_obj)
    image = ImageOps.exif_transpose(image)  # phone photos carry rotation in EXIF
    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    data = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": data},
    }


def _parse(feature: str, *, messages: list, schema, system: str | None = None):
    """One structured-output call: parse, log usage, return the validated object."""
    client = _get_client()
    kwargs = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "messages": messages,
        "output_format": schema,
    }
    if system:
        kwargs["system"] = system
    try:
        response = client.messages.parse(**kwargs)
    except anthropic.APIError as exc:
        logger.error("%s call failed: %s", feature, exc)
        raise SommelierError(f"Claude API call failed: {exc}") from exc

    usage = response.usage
    ApiUsage.objects.create(
        feature=feature,
        model=response.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
    )
    logger.debug(
        "%s: %s in / %s out tokens", feature, usage.input_tokens, usage.output_tokens
    )

    if response.parsed_output is None:
        raise SommelierError(f"{feature}: model response did not match the expected schema")
    return response.parsed_output


SYSTEM = (
    "You are the sommelier assistant for a personal wine cellar app. "
    "Be accurate and honest about uncertainty; never invent producers, "
    "vintages, or prices that are not supported by the input."
)


def scan_label(file_obj) -> LabelData:
    """Extract structured wine data from a bottle label photo."""
    return _parse(
        "scan_label",
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    prepare_image(file_obj),
                    {
                        "type": "text",
                        "text": (
                            "Extract the wine details from this bottle label photo. "
                            "If the vintage year is not visible, leave it null. "
                            "Flag anything you had to guess in confidence_notes."
                        ),
                    },
                ],
            }
        ],
        schema=LabelData,
    )


def inventory_summary() -> str:
    """Compact one-line-per-vintage summary of everything drinkable in the cellar."""
    from django.db.models import Avg

    from cellar.models import Vintage

    lines = []
    vintages = (
        Vintage.objects.with_stock()
        .select_related("wine", "wine__producer")
        .annotate(avg_rating=Avg("tasting_notes__rating"))
    )
    for v in vintages:
        window = (
            f"window {v.drink_from or '?'}-{v.drink_until or '?'}"
            if (v.drink_from or v.drink_until)
            else "window unknown"
        )
        rating = f", our avg rating {v.avg_rating:.0f}/100" if v.avg_rating else ""
        lines.append(
            f"{v.pk} | {v} | {v.wine.get_wine_type_display()}"
            f" | {v.wine.varietals or 'varietals unknown'} | {window}"
            f" | {v.in_cellar} bottle(s){rating}"
        )
    return "\n".join(lines)


def taste_profile() -> str:
    """Short summary of household taste, from the highest-rated tasting notes."""
    from cellar.models import TastingNote

    notes = (
        TastingNote.objects.filter(rating__isnull=False)
        .select_related("vintage__wine__producer")
        .order_by("-rating")[:10]
    )
    if not notes:
        return ""
    lines = [
        f"{note.rating}/100 — {note.vintage} ({note.vintage.wine.get_wine_type_display()})"
        for note in notes
    ]
    return "Our highest-rated recent wines:\n" + "\n".join(lines)


def pair_food(dish: str) -> PairingAdvice:
    """Suggest bottles from the cellar for a dish. Grounded in actual inventory."""
    inventory = inventory_summary()
    if not inventory:
        inventory = "(the cellar is currently empty)"
    return _parse(
        "pair_food",
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"We're having: {dish}\n\n"
                    "Recommend up to 3 bottles from our cellar (listed below), best first. "
                    "Only recommend wines from this list, using the exact id in the first "
                    "column. Prefer bottles inside their drinking window. If nothing fits "
                    "well, say so in general_advice and suggest what style to look for.\n\n"
                    f"CELLAR INVENTORY (id | wine | type | varietals | window | stock):\n"
                    f"{inventory}"
                ),
            }
        ],
        schema=PairingAdvice,
    )


def analyze_menu(file_obj, occasion: str = "") -> MenuAdvice:
    """Read a restaurant wine list photo and recommend, informed by our taste history."""
    profile = taste_profile()
    context = f"\n\nContext for tonight: {occasion}" if occasion else ""
    tastes = f"\n\n{profile}" if profile else ""
    return _parse(
        "analyze_menu",
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    prepare_image(file_obj),
                    {
                        "type": "text",
                        "text": (
                            "This is a restaurant wine list. Parse every legible wine, "
                            "then recommend up to 3 (best first) with brief reasoning. "
                            "Favor interesting value over trophy bottles unless asked "
                            f"otherwise.{context}{tastes}"
                        ),
                    },
                ],
            }
        ],
        schema=MenuAdvice,
    )


EMAIL_TEXT_LIMIT = 50_000


def digest_email(raw_text: str) -> EmailDigest:
    """Digest a distributor marketing email into offers + buy/skip suggestions."""
    if len(raw_text) > EMAIL_TEXT_LIMIT:
        logger.warning(
            "digest_email: clipping email text from %s to %s chars",
            len(raw_text), EMAIL_TEXT_LIMIT,
        )
        raw_text = raw_text[:EMAIL_TEXT_LIMIT]

    inventory = inventory_summary() or "(the cellar is currently empty)"
    tastes = taste_profile()
    tastes_block = f"\n\nOUR TASTE HISTORY:\n{tastes}" if tastes else ""
    return _parse(
        "digest_email",
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    "Below is a marketing email from our local wine distributor. "
                    "Extract every distinct wine offer, then judge each one for us: "
                    "'buy' if it clearly fits our cellar and tastes (fills a gap, great "
                    "value, styles we rate highly), 'consider' if it's interesting but "
                    "a judgment call, 'skip' otherwise. Be candid — most marketing "
                    "offers deserve 'skip'.\n\n"
                    f"OUR CELLAR (id | wine | type | varietals | window | stock):\n{inventory}"
                    f"{tastes_block}\n\n"
                    f"THE EMAIL:\n{raw_text}"
                ),
            }
        ],
        schema=EmailDigest,
    )


def suggest_window(vintage) -> DrinkingWindow:
    """Suggest a drinking window for a cellar.Vintage."""
    wine = vintage.wine
    description = (
        f"Producer: {wine.producer.name} ({wine.producer.region or 'region unknown'}, "
        f"{wine.producer.country or 'country unknown'})\n"
        f"Wine: {wine.name}\n"
        f"Type: {wine.get_wine_type_display()}\n"
        f"Varietals: {wine.varietals or 'unknown'}\n"
        f"Appellation: {wine.appellation or 'unknown'}\n"
        f"Vintage: {vintage.year or 'non-vintage'}\n"
        f"ABV: {vintage.abv or 'unknown'}"
    )
    return _parse(
        "suggest_window",
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    "Suggest a realistic drinking window (calendar years) for this wine, "
                    "based on its style, structure, appellation norms, and vintage "
                    f"reputation:\n\n{description}"
                ),
            }
        ],
        schema=DrinkingWindow,
    )
