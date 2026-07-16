"""IMAP polling for the dedicated distributor mailbox.

Idempotent: each message is keyed by folder+UID (unique on the model), so
re-running never duplicates. HTML-only marketing emails fall back to a
tag-stripped version of the HTML body.

The management command `assistant_poll_email` is the thin CLI shim over
`poll_mailbox()`.
"""

import logging

from django.conf import settings
from django.utils.html import strip_tags
from imap_tools import AND, MailBox

from . import sommelier
from .models import DistributorEmail

logger = logging.getLogger("winecellar.assistant")


class MailboxNotConfigured(Exception):
    pass


def _message_text(msg) -> str:
    if msg.text and msg.text.strip():
        return msg.text
    return strip_tags(msg.html or "")


def poll_mailbox(progress=None) -> dict:
    """Fetch unseen messages, store them, and digest each with the sommelier.

    Returns stats: fetched / digested / failed / skipped.
    """
    progress = progress or (lambda message: None)
    if not (
        settings.DISTRIBUTOR_IMAP_HOST
        and settings.DISTRIBUTOR_IMAP_USER
        and settings.DISTRIBUTOR_IMAP_PASSWORD
    ):
        raise MailboxNotConfigured(
            "DISTRIBUTOR_IMAP_HOST / _USER / _PASSWORD must be set in .env"
        )

    folder = settings.DISTRIBUTOR_IMAP_FOLDER
    stats = {"fetched": 0, "digested": 0, "failed": 0, "skipped": 0}

    with MailBox(settings.DISTRIBUTOR_IMAP_HOST).login(
        settings.DISTRIBUTOR_IMAP_USER,
        settings.DISTRIBUTOR_IMAP_PASSWORD,
        initial_folder=folder,
    ) as mailbox:
        for msg in mailbox.fetch(AND(seen=False)):
            uid_key = f"{folder}:{msg.uid}"
            if DistributorEmail.objects.filter(message_uid=uid_key).exists():
                stats["skipped"] += 1
                logger.debug("skipping already-stored message %s", uid_key)
                continue

            email = DistributorEmail(
                message_uid=uid_key,
                sender=msg.from_,
                subject=msg.subject[:500],
                received_at=msg.date,
                raw_text=_message_text(msg),
            )
            stats["fetched"] += 1
            progress(f"fetched: {email.subject or email.sender}")

            try:
                digest = sommelier.digest_email(email.raw_text)
            except sommelier.SommelierError as exc:
                email.status = DistributorEmail.Status.FAILED
                email.error = str(exc)
                stats["failed"] += 1
                logger.error("digest failed for %s: %s", uid_key, exc)
            else:
                email.status = DistributorEmail.Status.ANALYZED
                email.result = digest.model_dump()
                stats["digested"] += 1
                actionable = len(email.actionable_offers)
                progress(
                    f"  digested: {len(digest.offers)} offer(s), {actionable} worth a look"
                )
            email.save()

    return stats
