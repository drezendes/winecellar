"""Create/refresh the shared read-only guest account.

Idempotent: ensures the ``Guest`` group exists and a **non-staff** user (default
``guest``) belongs to it, then sets the password. Guests get read-only browse
access via core.middleware.GuestPolicyMiddleware. Non-staff keeps /admin/ shut.

    python manage.py create_guest --password '<pw>' [--username guest]
    # (omit --password to be prompted securely; on the box run without -T so
    #  the prompt has a TTY)
"""

import getpass

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError

from core.guest import GUEST_GROUP


class Command(BaseCommand):
    help = "Create/update the shared read-only guest account (Guest group, non-staff)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="guest")
        parser.add_argument("--password", help="If omitted, prompt securely.")

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"] or getpass.getpass("Guest password: ")
        if not password:
            raise CommandError("a password is required")

        group, _ = Group.objects.get_or_create(name=GUEST_GROUP)
        user, created = User.objects.get_or_create(username=username)
        user.is_staff = False
        user.is_superuser = False
        user.is_active = True
        user.set_password(password)
        user.save()
        user.groups.add(group)
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} guest '{username}' "
                f"— group '{GUEST_GROUP}', read-only, non-staff."
            )
        )
