"""Server-side read-only enforcement for guest accounts.

Mirrors the app's single-global-gate pattern (sits right after
``LoginRequiredMiddleware``). Templates only *hide* buttons — this is the wall:
a guest that hand-crafts a URL or POST is still stopped here.

Policy for a guest (``core.guest.is_guest``):
- No unsafe methods (POST/PUT/PATCH/DELETE) — covers every mutation AND every
  Claude call (all are POST-only in this app).
- No private GET surfaces — the whole ``/assistant/*`` namespace (prospects,
  suggestions, usage, valuation, taste profile, and the AI forms) plus the
  cellar mutation forms (add bottle, add note, edit window).
- Everything else (browse pages, static/media, auth) passes through.
Blocked navigations redirect to the dashboard with a note; blocked HTMX/XHR
get a bare 403 (no message spam from background polls).
"""

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from .guest import is_guest

SAFE_METHODS = frozenset(("GET", "HEAD", "OPTIONS"))

# GET paths a guest may not reach (private/AI + mutation forms).
_DENIED_PREFIXES = ("/assistant/", "/bottles/add", "/notes/add")


def _static_media_prefixes():
    out = []
    for url in (settings.STATIC_URL, settings.MEDIA_URL):
        if url:
            out.append(url if url.startswith("/") else "/" + url)
    return tuple(out)


class GuestPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._asset_prefixes = _static_media_prefixes()

    def __call__(self, request):
        request.is_guest = is_guest(request.user)
        if request.is_guest and not self._allowed(request):
            if request.headers.get("HX-Request"):
                return HttpResponseForbidden("Guest access is read-only.")
            messages.info(request, "Guest access is read-only — sign in as yourself to change things.")
            return redirect("cellar:dashboard")
        return self.get_response(request)

    def _allowed(self, request) -> bool:
        path = request.path
        # Assets and auth (incl. the logout POST) always pass.
        if path.startswith(self._asset_prefixes) or path.startswith("/accounts/"):
            return True
        # Read-only: no writes, no AI (all are POST-only here).
        if request.method not in SAFE_METHODS:
            return False
        # Private/AI GET surfaces + cellar mutation forms.
        if path.startswith(_DENIED_PREFIXES):
            return False
        # The edit-drinking-window form GET (/vintages/<pk>/window/).
        if path.startswith("/vintages/") and path.endswith("/window/"):
            return False
        return True
