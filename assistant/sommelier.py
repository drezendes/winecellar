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
from .schemas import (
    DrinkingWindow,
    EmailDigest,
    LabelData,
    MenuAdvice,
    PairingAdvice,
    ProfileDraft,
    WineDossier,
)

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


def _log_usage(feature: str, response):
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

    _log_usage(feature, response)

    if response.parsed_output is None:
        raise SommelierError(f"{feature}: model response did not match the expected schema")
    return response.parsed_output


def _web_research(feature: str, prompt: str, max_searches: int = 4) -> str:
    """A free-text call with server-side web search enabled.

    Kept separate from _parse: web-search responses carry citations, which are
    incompatible with constrained output — so research is a text step, and the
    caller structures the result with a follow-up _parse call.
    """
    client = _get_client()
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}]
    messages = [{"role": "user", "content": prompt}]

    for _ in range(4):  # bounded pause_turn continuations
        try:
            response = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=SYSTEM,
                tools=tools,
                messages=messages,
            )
        except anthropic.APIError as exc:
            logger.error("%s research call failed: %s", feature, exc)
            raise SommelierError(f"Claude API call failed: {exc}") from exc
        _log_usage(feature, response)
        if response.stop_reason != "pause_turn":
            break
        # Server-side tool loop paused; append the assistant turn and resume.
        messages = messages + [{"role": "assistant", "content": response.content}]
    else:
        raise SommelierError(f"{feature}: research did not finish (kept pausing)")

    text = "\n".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        raise SommelierError(f"{feature}: research returned no text")
    return text


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


def rating_history(user=None) -> str:
    """Highest-rated tasting notes — the household's (or one user's) revealed taste."""
    from cellar.models import TastingNote

    notes = TastingNote.objects.filter(rating__isnull=False)
    if user is not None:
        notes = notes.filter(author=user)
    notes = notes.select_related("vintage__wine__producer").order_by("-rating")[:10]
    if not notes:
        return ""
    lines = [
        f"{note.rating}/100 — {note.vintage} ({note.vintage.wine.get_wine_type_display()})"
        for note in notes
    ]
    return "Highest-rated recent wines:\n" + "\n".join(lines)


def taste_context(user=None) -> str:
    """Stated taste profile(s) + rating history, for inclusion in prompts.

    With a user: that user's profile and their ratings (falling back to
    household ratings). Without: every stated profile, labeled by name.
    """
    from .models import TasteProfile

    parts = []
    if user is not None:
        profile = TasteProfile.objects.filter(user=user).exclude(text="").first()
        if profile:
            parts.append(f"THE DINER'S STATED TASTE PROFILE:\n{profile.text}")
        history = rating_history(user) or rating_history()
    else:
        profiles = TasteProfile.objects.exclude(text="").select_related("user")
        for profile in profiles:
            parts.append(
                f"TASTE PROFILE ({profile.user.get_username()}):\n{profile.text}"
            )
        history = rating_history()
    if history:
        parts.append(history)
    return "\n\n".join(parts)


def pair_food(dish: str, user=None) -> PairingAdvice:
    """Suggest bottles from the cellar for a dish. Grounded in actual inventory."""
    inventory = inventory_summary()
    if not inventory:
        inventory = "(the cellar is currently empty)"
    tastes = taste_context(user)
    tastes_block = f"\n\n{tastes}" if tastes else ""
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
                    f"{inventory}{tastes_block}"
                ),
            }
        ],
        schema=PairingAdvice,
    )


MENU_CATEGORY_SPECS = {
    "taste_match": (
        "taste_match — up to 3 bottles most aligned with the diner's stated profile "
        "and rating history, ranked best-fit first. Always include prices so the "
        "diner can choose their price point within the ranking."
    ),
    "best_value": (
        "best_value — up to 3 ranked by quality-for-price (never merely the cheapest). "
        "Span price tiers where the list allows, so both a budget pick and a "
        "worth-the-money pick appear."
    ),
    "most_interesting": (
        "most_interesting — up to 3 distinctive bottles worth the adventure (rare "
        "grape, unusual region, standout producer), ranked."
    ),
}


def analyze_menu(file_obj, food: str = "", notes: str = "", user=None) -> MenuAdvice:
    """Read a restaurant wine list photo; ranked picks per the diner's chosen categories."""
    from .models import TasteProfile

    profile = (
        TasteProfile.objects.filter(user=user).first() if user is not None else None
    )
    enabled = {
        "taste_match": profile.menu_taste_match if profile else True,
        "best_value": profile.menu_best_value if profile else True,
        "most_interesting": profile.menu_most_interesting if profile else True,
    }
    categories = "\n".join(
        f"- {MENU_CATEGORY_SPECS[key]}" for key, on in enabled.items() if on
    )
    skipped = [key for key, on in enabled.items() if not on]
    skip_line = (
        f"\nLeave these categories as empty lists (the diner opted out): {', '.join(skipped)}."
        if skipped
        else ""
    )

    blocks = []
    if profile and profile.menu_notes.strip():
        blocks.append(f"THE DINER'S STANDING MENU INSTRUCTIONS:\n{profile.menu_notes}")
    if food:
        blocks.append(f"Tonight's food: {food}")
    if notes:
        blocks.append(f"Tonight's extra wishes: {notes}")
    tastes = taste_context(user)
    if tastes:
        blocks.append(tastes)
    context_block = ("\n\n" + "\n\n".join(blocks)) if blocks else ""

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
                            "then fill these ranked categories:\n"
                            f"{categories}{skip_line}\n"
                            "A bottle may appear in more than one category when it "
                            f"genuinely earns it.{context_block}"
                        ),
                    },
                ],
            }
        ],
        schema=MenuAdvice,
    )


def draft_taste_profile(user, current_text: str = "") -> ProfileDraft:
    """Draft/refresh a user's taste profile from their tasting history.

    The draft prefills the profile form — the user edits and saves it themselves.
    """
    history = rating_history(user) or "(no rated tasting notes yet)"
    current = (
        f"Their current profile (preserve stated facts, refine wording):\n{current_text}"
        if current_text.strip()
        else "They have no profile yet — draft a starting point."
    )
    return _parse(
        "draft_taste_profile",
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Draft a first-person wine taste profile for {user.get_username()}, "
                    "suitable for handing to a sommelier. Base it on the evidence below; "
                    "where evidence is thin, keep it general rather than inventing "
                    "specifics.\n\n"
                    f"{current}\n\nTHEIR RATING HISTORY:\n{history}"
                ),
            }
        ],
        schema=ProfileDraft,
    )


def research_wine(vintage) -> WineDossier:
    """Web-research a wine (producer site first) and return a structured dossier.

    Two API calls by design: a web-search research pass (text), then a cheap
    structuring pass — see the note on _web_research.
    """
    wine = vintage.wine
    identity = f"{wine.producer.name} {wine.name} {vintage.year or 'NV'}"
    detail = (
        f"({wine.get_wine_type_display()}"
        f"{', ' + wine.varietals if wine.varietals else ''}"
        f"{', ' + wine.appellation if wine.appellation else ''})"
    )
    research = _web_research(
        "research_wine",
        (
            f"Research this wine: {identity} {detail}\n\n"
            "Prioritize the producer's own website, then reputable wine sources. "
            "Report: producer background and house style; what this wine is like "
            "(structure, flavors, winemaking); anything specific to this vintage; "
            "aging/serving guidance; typical retail price. List the URLs you used. "
            "If you can't find the exact wine, say so plainly rather than "
            "substituting a similar one."
        ),
    )
    return _parse(
        "research_wine",
        messages=[
            {
                "role": "user",
                "content": (
                    "Convert these research notes into the dossier structure. Keep only "
                    "what the notes support — leave fields empty rather than inventing.\n\n"
                    f"{research}"
                ),
            }
        ],
        schema=WineDossier,
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
    tastes = taste_context()  # household-wide: all profiles + ratings
    tastes_block = f"\n\n{tastes}" if tastes else ""
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
