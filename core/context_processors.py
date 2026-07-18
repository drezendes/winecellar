"""Template context: the ``is_guest`` flag set by GuestPolicyMiddleware, so
templates can hide owner-only UI with ``{% if not is_guest %}``."""


def guest(request):
    return {"is_guest": getattr(request, "is_guest", False)}
