"""URL configuration for winecellar."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from assistant import views as assistant_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("assistant/", include("assistant.urls")),
    # Machine-to-machine: the Cloudflare Email Worker POSTs raw MIME here.
    path("api/distributor-inbox/", assistant_views.distributor_inbox_webhook, name="distributor_inbox"),
    path("", include("cellar.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
