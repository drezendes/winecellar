from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView, UpdateView
from django.views.generic.edit import FormView

from .forms import BottleIntakeForm, TastingNoteForm, VintageWindowForm
from .models import Bottle, TastingNote, Vintage, Wine


class DashboardView(LoginRequiredMixin, TemplateView):
    """Cellar landing page: summary counts, drink-soon and ready-to-drink lists."""

    template_name = "cellar/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        in_cellar = Bottle.objects.filter(status=Bottle.Status.IN_CELLAR)
        context["bottle_count"] = in_cellar.count()
        context["wine_count"] = Wine.objects.filter(
            vintages__bottles__status=Bottle.Status.IN_CELLAR
        ).distinct().count()
        context["cellar_value"] = in_cellar.aggregate(total=Sum("purchase_price"))["total"]
        context["drink_soon"] = Vintage.objects.drink_soon().select_related(
            "wine", "wine__producer"
        )[:10]
        context["ready"] = Vintage.objects.ready().select_related("wine", "wine__producer")[:10]

        from assistant.models import DistributorEmail

        context["unreviewed_emails"] = DistributorEmail.objects.filter(
            reviewed=False, status=DistributorEmail.Status.ANALYZED
        )[:5]
        return context


class WineListView(LoginRequiredMixin, ListView):
    """Browsable cellar: wines with in-cellar counts, filterable by search/type."""

    template_name = "cellar/wine_list.html"
    context_object_name = "wines"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            Wine.objects.select_related("producer")
            .annotate(
                in_cellar=Count(
                    "vintages__bottles",
                    filter=Q(vintages__bottles__status=Bottle.Status.IN_CELLAR),
                )
            )
            .order_by("producer__name", "name")
        )
        search = self.request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(producer__name__icontains=search)
                | Q(varietals__icontains=search)
                | Q(appellation__icontains=search)
            )
        wine_type = self.request.GET.get("type", "").strip()
        if wine_type:
            qs = qs.filter(wine_type=wine_type)
        if self.request.GET.get("in_stock"):
            qs = qs.filter(in_cellar__gt=0)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["wine_types"] = Wine.WineType.choices
        context["current_search"] = self.request.GET.get("q", "")
        context["current_type"] = self.request.GET.get("type", "")
        context["in_stock_only"] = bool(self.request.GET.get("in_stock"))
        return context


class WineDetailView(LoginRequiredMixin, DetailView):
    """One wine: its vintages, bottles, windows, and tasting notes."""

    model = Wine
    template_name = "cellar/wine_detail.html"
    context_object_name = "wine"

    def get_queryset(self):
        return Wine.objects.select_related("producer").prefetch_related(
            "vintages__bottles", "vintages__tasting_notes__author"
        )


class BottleIntakeView(LoginRequiredMixin, FormView):
    """Add bottles: get-or-creates producer/wine/vintage and creates N bottles.

    The label scanner prefills this form via GET parameters (phase 3).
    """

    template_name = "cellar/bottle_intake.html"
    form_class = BottleIntakeForm

    def get_initial(self):
        # Any known form field may arrive as a GET param (label-scan prefill).
        initial = super().get_initial()
        for field in self.form_class.base_fields:
            value = self.request.GET.get(field)
            if value:
                initial[field] = value
        return initial

    def form_valid(self, form):
        vintage, bottles = form.save()
        messages.success(
            self.request,
            f"Added {len(bottles)} bottle{'s' if len(bottles) != 1 else ''} of {vintage}.",
        )
        return redirect("cellar:wine_detail", pk=vintage.wine_id)


class VintageWindowUpdateView(LoginRequiredMixin, UpdateView):
    """Edit a vintage's drinking window / ABV."""

    model = Vintage
    form_class = VintageWindowForm
    template_name = "cellar/vintage_form.html"
    context_object_name = "vintage"

    def get_initial(self):
        # The AI suggest-window flow redirects here with prefill GET params;
        # the user reviews/edits before saving.
        initial = super().get_initial()
        for field in ("drink_from", "drink_until", "window_rationale"):
            value = self.request.GET.get(field)
            if value:
                initial[field] = value
        return initial

    def get_success_url(self):
        messages.success(self.request, f"Updated {self.object}.")
        return reverse("cellar:wine_detail", kwargs={"pk": self.object.wine_id})


class BottleActionView(LoginRequiredMixin, View):
    """POST-only: mark a bottle consumed or gifted."""

    def post(self, request, pk, action):
        bottle = get_object_or_404(Bottle, pk=pk, status=Bottle.Status.IN_CELLAR)
        if action == "drink":
            bottle.mark_consumed()
            messages.success(request, f"Enjoy! {bottle.vintage} marked consumed.")
            return redirect(
                f"{reverse('cellar:note_add')}?vintage={bottle.vintage_id}&bottle={bottle.pk}"
            )
        if action == "gift":
            bottle.mark_gifted()
            messages.success(request, f"{bottle.vintage} marked gifted.")
            return redirect("cellar:wine_detail", pk=bottle.vintage.wine_id)
        messages.error(request, "Unknown bottle action.")
        return redirect("cellar:dashboard")


class TastingNoteCreateView(LoginRequiredMixin, FormView):
    """Record a tasting note; vintage (and optionally bottle) come via GET params."""

    template_name = "cellar/tastingnote_form.html"
    form_class = TastingNoteForm

    def get_vintage(self):
        return get_object_or_404(Vintage, pk=self.request.GET.get("vintage"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["vintage"] = self.get_vintage()
        return context

    def form_valid(self, form):
        vintage = self.get_vintage()
        note = form.save(commit=False)
        note.vintage = vintage
        note.author = self.request.user
        bottle_id = self.request.GET.get("bottle")
        if bottle_id:
            note.bottle = Bottle.objects.filter(pk=bottle_id, vintage=vintage).first()
        note.save()
        messages.success(self.request, f"Tasting note saved for {vintage}.")
        return redirect("cellar:wine_detail", pk=vintage.wine_id)
