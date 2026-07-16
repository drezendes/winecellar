from django.urls import path

from . import views

app_name = "cellar"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("wines/", views.WineListView.as_view(), name="wine_list"),
    path("wines/<uuid:pk>/", views.WineDetailView.as_view(), name="wine_detail"),
    path("bottles/add/", views.BottleIntakeView.as_view(), name="bottle_add"),
    path(
        "bottles/<uuid:pk>/<str:action>/", views.BottleActionView.as_view(), name="bottle_action"
    ),
    path(
        "vintages/<uuid:pk>/window/",
        views.VintageWindowUpdateView.as_view(),
        name="vintage_window",
    ),
    path("notes/add/", views.TastingNoteCreateView.as_view(), name="note_add"),
]
