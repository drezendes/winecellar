"""Shared read-only "guest" role.

A guest is a user in the ``GUEST_GROUP`` group. Enforcement lives in
``core.middleware.GuestPolicyMiddleware`` (server-side wall) and the ``is_guest``
template flag (``core.context_processors``). Guests are created non-staff by
``manage.py create_guest`` so ``/admin/`` stays closed.
"""

GUEST_GROUP = "Guest"


def is_guest(user) -> bool:
    """True for an authenticated user in the Guest group."""
    return bool(
        getattr(user, "is_authenticated", False)
        and user.groups.filter(name=GUEST_GROUP).exists()
    )
