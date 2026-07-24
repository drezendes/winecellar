"""Distributor inbox: turn an inbound distributor email (raw MIME pushed by the
Cloudflare Email Worker) into either a composed recommendation emailed to the
owner, or a "forward" verdict telling the bridge to pass the original through.

The intelligence lives here — winecellar has the cellar, the tastes, and the
Anthropic key — so the Worker stays a dumb bridge. Never lose mail: any failure
raises, the webhook view maps that to 5xx, and the Worker forwards the untouched
original to the owner.
"""

import hashlib
import logging
from email import message_from_bytes
from email.policy import default as email_policy
from email.utils import parsedate_to_datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.utils.html import strip_tags

from . import sommelier
from .models import DistributorEmail

logger = logging.getLogger("winecellar.assistant")


def _body_text(msg) -> str:
    """Best-effort plain text: prefer text/plain, fall back to tag-stripped
    text/html — the same rule the IMAP path uses."""
    plain = html = ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_maintype() != "text":
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):  # unknown charset / undecodable — skip
            continue
        if part.get_content_type() == "text/plain" and not plain:
            plain = content
        elif part.get_content_type() == "text/html" and not html:
            html = content
    if plain and plain.strip():
        return plain
    return strip_tags(html)


def parse_mime(raw: bytes) -> dict:
    """Parse raw MIME into the fields the pipeline needs. Message-ID keys
    idempotency; a body hash stands in when a message lacks one."""
    msg = message_from_bytes(raw, policy=email_policy)
    try:
        received_at = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
    except (TypeError, ValueError):
        received_at = None
    message_id = (msg["Message-ID"] or "").strip() if msg["Message-ID"] else ""
    if not message_id:
        message_id = "sha256:" + hashlib.sha256(raw).hexdigest()[:32]
    return {
        "message_id": message_id,
        "sender": str(msg["From"] or "")[:300],
        "subject": str(msg["Subject"] or "")[:500],
        "received_at": received_at,
        "text": _body_text(msg),
    }


def _owner_user():
    """The user whose TasteProfile configures the analysis (buying notes + lens
    toggles). Blank setting → None → household-wide tastes, all lenses on."""
    username = settings.DISTRIBUTOR_OWNER_USERNAME
    if not username:
        return None
    return get_user_model().objects.filter(username=username).first()


def render_recommendation(digest, parsed: dict) -> str:
    """Plain-text recommendation: the picks on top, the original quoted below.
    First cut — Fable reviews copy/format before the routing rule goes live."""
    lines = [digest.summary.strip(), ""]
    lenses = [
        ("Is it a fit?", digest.taste_match),
        ("Good value?", digest.best_value),
        ("Worth grabbing?", digest.most_interesting),
    ]
    shown = False
    for label, picks in lenses:
        if not picks:
            continue
        shown = True
        lines.append(label)
        for p in picks:
            price = f" · {p.price}" if p.price else ""
            lines.append(f"  - {p.wine}{price} — {p.reasoning}")
        lines.append("")
    if not shown:
        lines += ["Nothing here stands out for the cellar.", ""]
    lines += [
        "— analyzed against your cellar by winecellar",
        "",
        "--- original message ---",
        f"From: {parsed['sender']}",
        f"Subject: {parsed['subject']}",
        "",
        parsed["text"],
    ]
    return "\n".join(lines)


def send_recommendation(digest, parsed: dict) -> None:
    """Compose and send the recommendation via the configured email backend."""
    recipient = settings.DISTRIBUTOR_RECIPIENT
    if not recipient:
        raise RuntimeError("DISTRIBUTOR_RECIPIENT is not set — cannot send the recommendation")
    subject = f"Cellar picks: {parsed['subject']}" if parsed["subject"] else "Cellar picks"
    EmailMessage(
        subject=subject[:200],
        body=render_recommendation(digest, parsed),
        to=[recipient],
    ).send(fail_silently=False)


def handle_inbound(raw: bytes) -> dict:
    """Parse → analyze → send a recommendation or return a forward verdict.
    Idempotent on Message-ID. Raises on analysis/send failure so the webhook
    returns 5xx and the Worker forwards the untouched original (never lose mail).
    """
    parsed = parse_mime(raw)
    uid = f"webhook:{parsed['message_id']}"[:200]

    existing = DistributorEmail.objects.filter(message_uid=uid).first()
    if existing is not None:
        logger.info("distributor inbox: duplicate %s (%s)", uid, existing.status)
        action = "handled" if existing.status == DistributorEmail.Status.ANALYZED else "forward"
        return {"action": action, "duplicate": True}

    email = DistributorEmail(
        message_uid=uid,
        sender=parsed["sender"],
        subject=parsed["subject"],
        received_at=parsed["received_at"],
        raw_text=parsed["text"],
    )
    try:
        digest = sommelier.digest_email(parsed["text"], user=_owner_user())
    except sommelier.SommelierError as exc:
        email.status = DistributorEmail.Status.FAILED
        email.error = str(exc)
        email.save()
        logger.error("distributor inbox: analysis failed for %s: %s", uid, exc)
        raise

    email.result = digest.model_dump()
    if digest.forward:
        email.status = DistributorEmail.Status.FORWARDED
        email.save()
        logger.info("distributor inbox: forwarding %s (%s)", uid, digest.forward_reason)
        return {"action": "forward", "reason": digest.forward_reason}

    try:
        send_recommendation(digest, parsed)
    except Exception as exc:
        email.status = DistributorEmail.Status.FAILED
        email.error = f"send failed: {exc}"
        email.save()
        logger.exception("distributor inbox: send failed for %s", uid)
        raise

    email.status = DistributorEmail.Status.ANALYZED
    email.save()
    return {"action": "handled", "picks": len(email.actionable_offers)}
