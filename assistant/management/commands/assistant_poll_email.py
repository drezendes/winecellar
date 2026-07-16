"""Poll the distributor mailbox and digest new emails.

Thin shim over assistant.email_pipeline.poll_mailbox(); safe to re-run
(messages are keyed by folder+UID). Run manually or via Task Scheduler.
"""

from django.core.management.base import BaseCommand, CommandError

from assistant.email_pipeline import MailboxNotConfigured, poll_mailbox


class Command(BaseCommand):
    help = "Fetch unseen distributor emails via IMAP and digest them with the sommelier."

    def add_arguments(self, parser):
        parser.add_argument("--quiet", action="store_true", help="Summary line only")

    def handle(self, *args, **options):
        progress = (lambda message: None) if options["quiet"] else (
            lambda message: self.stdout.write(message)
        )
        try:
            stats = poll_mailbox(progress=progress)
        except MailboxNotConfigured as exc:
            raise CommandError(str(exc)) from exc

        self.stats = stats  # structured stats for programmatic callers
        self.stdout.write(
            f"Done: {stats['fetched']} fetched, {stats['digested']} digested, "
            f"{stats['failed']} failed, {stats['skipped']} skipped."
        )
