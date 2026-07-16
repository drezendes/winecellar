"""Generate taste-map style vectors for wines that lack one.

Thin shim over assistant.styles.backfill_styles(); idempotent (skips wines
that already have a vector unless --refresh). ~1-2 cents per wine.
"""

from django.core.management.base import BaseCommand

from assistant.styles import backfill_styles


class Command(BaseCommand):
    help = "Generate AI style vectors for the taste map (blank wines only by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--refresh", action="store_true", help="Regenerate for ALL wines, not just blanks"
        )
        parser.add_argument("--quiet", action="store_true", help="Summary line only")

    def handle(self, *args, **options):
        progress = (lambda message: None) if options["quiet"] else (
            lambda message: self.stdout.write(message)
        )
        stats = backfill_styles(progress=progress, refresh=options["refresh"])
        self.stats = stats  # structured stats for programmatic callers
        self.stdout.write(f"Done: {stats['done']} vectored, {stats['failed']} failed.")
