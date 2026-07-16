from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("scan/", views.LabelScanView.as_view(), name="label_scan"),
    path("pairing/", views.PairingView.as_view(), name="pairing"),
    path("menu/", views.MenuScanView.as_view(), name="menu_scan"),
    path(
        "vintages/<uuid:pk>/suggest-window/",
        views.SuggestWindowView.as_view(),
        name="suggest_window",
    ),
    path(
        "vintages/<uuid:pk>/research/",
        views.ResearchWineView.as_view(),
        name="research_wine",
    ),
    path("suggestions/", views.SuggestionListView.as_view(), name="suggestions"),
    path("usage/", views.UsageView.as_view(), name="usage"),
    path("profile/", views.TasteProfileView.as_view(), name="profile"),
    path("profile/draft/", views.DraftProfileView.as_view(), name="profile_draft"),
    path("emails/<uuid:pk>/review/", views.EmailReviewView.as_view(), name="email_review"),
]
