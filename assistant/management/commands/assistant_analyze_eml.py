"""Analyze a raw .eml through the distributor-inbox pipeline, without the
Worker or webhook — for validating the analysis on real fixtures.

    python manage.py assistant_analyze_eml tests/fixtures/distributor/offer.eml
    python manage.py assistant_analyze_eml offer.eml --send   # also send the email

Reads no mailbox and writes no DistributorEmail row — it just parses, analyzes,
and prints, so it's safe to re-run on the same file. Needs ANTHROPIC_API_KEY
(and, with --send, the email settings).
"""

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from assistant import inbox, sommelier


class Command(BaseCommand):
    help = "Analyze a raw .eml file through the distributor-inbox pipeline (no DB write)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="path to a raw .eml file")
        parser.add_argument(
            "--send", action="store_true", help="also compose and send the recommendation email"
        )

    def handle(self, *args, **opts):
        # Distributor emails carry emoji, smart quotes, zero-width spaces —
        # force UTF-8 so printing doesn't die on the Windows console (cp1252).
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

        path = Path(opts["path"])
        if not path.is_file():
            raise CommandError(f"no such file: {path}")

        raw = path.read_bytes()
        parsed = inbox.parse_mime(raw)
        self.stdout.write(f"From:    {parsed['sender']}")
        self.stdout.write(f"Subject: {parsed['subject']}")
        self.stdout.write("-" * 60)

        try:
            digest = sommelier.digest_email(parsed["text"], user=inbox._owner_user())
        except sommelier.SommelierError as exc:
            raise CommandError(f"analysis failed: {exc}")

        if digest.forward:
            self.stdout.write(self.style.WARNING(f"FORWARD (not a wine offer): {digest.forward_reason}"))
            return

        # Just the picks here (the original is noisy in a console); the emailed
        # version — inbox.render_recommendation — also quotes the original below.
        self.stdout.write(inbox.render_picks(digest))
        if opts["send"]:
            inbox.send_recommendation(digest, parsed, raw)
            self.stdout.write(self.style.SUCCESS("\nsent."))
