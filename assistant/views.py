import uuid
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView
from django.views.generic.edit import FormView

from cellar.models import Vintage

from . import sommelier, tasks
from .images import ensure_browser_displayable
from .models import DistributorEmail, LabelScan, MenuAnalysis, TasteProfile


class LabelScanForm(forms.Form):
    image = forms.ImageField(
        label="Label photo",
        widget=forms.FileInput(attrs={"accept": "image/*", "capture": "environment"}),
    )


class LabelScanView(LoginRequiredMixin, FormView):
    """Photo of a bottle label → AI extraction → prefilled add-bottle form.

    The scan is a proposal: the user reviews and edits everything on the
    intake form before anything is saved to the cellar.
    """

    template_name = "assistant/label_scan.html"
    form_class = LabelScanForm

    def form_valid(self, form):
        image = ensure_browser_displayable(form.cleaned_data["image"])
        try:
            label = sommelier.scan_label(image)
        except sommelier.SommelierError as exc:
            LabelScan.objects.create(
                image=image, status=LabelScan.Status.FAILED, error=str(exc),
                created_by=self.request.user,
            )
            messages.error(self.request, f"Label scan failed: {exc}")
            return self.form_invalid(form)

        scan = LabelScan.objects.create(
            image=image, status=LabelScan.Status.COMPLETE,
            result=label.model_dump(), created_by=self.request.user,
        )

        prefill = {
            "producer_name": label.producer_name,
            "producer_region": label.producer_region,
            "producer_country": label.producer_country,
            "wine_name": label.wine_name,
            "wine_type": label.wine_type,
            "varietals": label.varietals,
            "appellation": label.appellation,
            "year": label.year,
            "abv": label.abv,
            # Rides through the intake form so the confirmed vintage gets
            # linked back to this scan (and its label photo).
            "label_scan": scan.pk,
        }
        query = urlencode({k: v for k, v in prefill.items() if v not in (None, "")})

        messages.success(self.request, f"Label read: {label.producer_name} {label.wine_name}.")
        if label.confidence_notes:
            messages.warning(self.request, f"Check before saving: {label.confidence_notes}")
        return redirect(f"{reverse('cellar:bottle_add')}?{query}")


class SuggestWindowView(LoginRequiredMixin, View):
    """POST-only: AI-suggest a drinking window, prefill the vintage window form.

    Nothing is saved — the suggestion lands in the (editable) form and the
    user decides whether to keep it.
    """

    def post(self, request, pk):
        vintage = get_object_or_404(Vintage, pk=pk)
        window_url = reverse("cellar:vintage_window", kwargs={"pk": vintage.pk})
        try:
            window = sommelier.suggest_window(vintage)
        except sommelier.SommelierError as exc:
            messages.error(request, f"Window suggestion failed: {exc}")
            return redirect(window_url)

        query = urlencode(
            {
                "drink_from": window.drink_from,
                "drink_until": window.drink_until,
                "window_rationale": window.rationale,
            }
        )
        messages.success(
            request,
            f"Suggested {window.drink_from}–{window.drink_until}. Review and save if it looks right.",
        )
        return redirect(f"{window_url}?{query}")


class ResearchWineView(LoginRequiredMixin, View):
    """POST-only: kick off web research for a vintage in a background thread.

    Research takes minutes, and the phone that requested it may lock or lose
    connectivity — so the request returns immediately and the outcome lands
    on the Vintage row (see assistant.tasks). The wine page polls a fragment
    until the state settles.
    """

    def post(self, request, pk):
        vintage = get_object_or_404(Vintage, pk=pk)
        detail_url = reverse("cellar:wine_detail", kwargs={"pk": vintage.wine_id})
        if vintage.dossier_state == "pending":
            messages.info(request, f"Already researching {vintage} — results land here soon.")
            return redirect(detail_url)

        tasks.start_research(vintage)
        messages.info(
            request,
            f"Researching {vintage} — takes a few minutes. Safe to leave; "
            "the dossier appears on this page when it's done.",
        )
        return redirect(detail_url)


class DossierFragmentView(LoginRequiredMixin, View):
    """GET: the dossier section for one vintage, polled by HTMX while pending."""

    def get(self, request, pk):
        vintage = get_object_or_404(Vintage, pk=pk)
        return render(request, "cellar/_dossier.html", {"vintage": vintage})


class PairingForm(forms.Form):
    dish = forms.CharField(
        label="What are you eating?",
        max_length=300,
        widget=forms.TextInput(attrs={"placeholder": "e.g. braised short ribs with polenta"}),
    )


class PairingView(LoginRequiredMixin, FormView):
    """Ask 'what goes with X?' — answers are grounded in the actual cellar."""

    template_name = "assistant/pairing.html"
    form_class = PairingForm

    def form_valid(self, form):
        dish = form.cleaned_data["dish"]
        context = self.get_context_data(form=form, dish=dish)
        try:
            advice = sommelier.pair_food(dish, user=self.request.user)
        except sommelier.SommelierError as exc:
            messages.error(self.request, f"Pairing failed: {exc}")
            return self.render_to_response(context)

        # Resolve the model's vintage ids back to real objects for linking;
        # drop anything that doesn't resolve (hallucination guard). Non-UUID
        # strings would make the pk__in lookup raise, so pre-validate.
        candidate_ids = []
        for pairing in advice.pairings:
            try:
                candidate_ids.append(uuid.UUID(pairing.vintage_id))
            except ValueError:
                continue
        vintage_map = {
            str(v.pk): v
            for v in Vintage.objects.filter(pk__in=candidate_ids).select_related(
                "wine", "wine__producer"
            )
        }
        context["pairings"] = [
            {"vintage": vintage_map[p.vintage_id], "reasoning": p.reasoning}
            for p in advice.pairings
            if p.vintage_id in vintage_map
        ]
        context["general_advice"] = advice.general_advice
        context["answered"] = True
        return self.render_to_response(context)


class MenuScanForm(forms.Form):
    image = forms.ImageField(
        label="Wine list photo",
        widget=forms.FileInput(attrs={"accept": "image/*", "capture": "environment"}),
    )
    food = forms.CharField(
        max_length=300,
        required=False,
        label="What are you eating? (optional)",
        widget=forms.TextInput(attrs={"placeholder": "e.g. ribeye and roasted mushrooms"}),
    )
    notes = forms.CharField(
        max_length=300,
        required=False,
        label="Anything else tonight? (optional)",
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. celebrating — okay to splurge / keep it under $70"}
        ),
    )


class MenuScanView(LoginRequiredMixin, FormView):
    """Restaurant wine-list photo → ranked picks per the diner's chosen categories."""

    template_name = "assistant/menu_scan.html"
    form_class = MenuScanForm

    def form_valid(self, form):
        image = ensure_browser_displayable(form.cleaned_data["image"])
        food = form.cleaned_data["food"]
        notes = form.cleaned_data["notes"]
        context = self.get_context_data(form=form)
        try:
            advice = sommelier.analyze_menu(
                image, food=food, notes=notes, user=self.request.user
            )
        except sommelier.SommelierError as exc:
            MenuAnalysis.objects.create(
                image=image, food=food, notes=notes, status=MenuAnalysis.Status.FAILED,
                error=str(exc), created_by=self.request.user,
            )
            messages.error(self.request, f"Menu analysis failed: {exc}")
            return self.render_to_response(context)

        MenuAnalysis.objects.create(
            image=image, food=food, notes=notes, status=MenuAnalysis.Status.COMPLETE,
            result=advice.model_dump(), created_by=self.request.user,
        )
        context["advice"] = advice
        context["answered"] = True
        return self.render_to_response(context)


# USD per million tokens: (input, output, cache-read). Matched by prefix so
# dated model snapshots roll up to their family.
PRICING_PER_MTOK = {
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-sonnet-5": (3.00, 15.00, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
DEFAULT_PRICING = (5.00, 25.00, 0.50)


def estimate_cost(model, input_tokens, output_tokens, cache_read_tokens=0):
    pricing = DEFAULT_PRICING
    for prefix, rates in PRICING_PER_MTOK.items():
        if model.startswith(prefix):
            pricing = rates
            break
    in_rate, out_rate, cache_rate = pricing
    return (
        input_tokens * in_rate + output_tokens * out_rate + cache_read_tokens * cache_rate
    ) / 1_000_000


class UsageView(LoginRequiredMixin, View):
    """API cost ledger: per-feature token totals and estimated dollars."""

    def get(self, request):
        from datetime import timedelta

        from django.shortcuts import render
        from django.utils import timezone

        from .models import ApiUsage

        def summarize(queryset):
            rows = []
            by_feature = queryset.values("feature", "model").annotate(
                calls=Count("id"),
                input=Sum("input_tokens"),
                output=Sum("output_tokens"),
                cache_read=Sum("cache_read_tokens"),
            )
            for row in by_feature:
                row["cost"] = estimate_cost(
                    row["model"], row["input"] or 0, row["output"] or 0, row["cache_read"] or 0
                )
                rows.append(row)
            rows.sort(key=lambda r: -r["cost"])
            return rows, sum(r["cost"] for r in rows)

        month_start = timezone.localdate().replace(day=1)
        month_rows, month_total = summarize(ApiUsage.objects.filter(created__date__gte=month_start))
        thirty_days = ApiUsage.objects.filter(created__gte=timezone.now() - timedelta(days=30))
        _, thirty_day_total = summarize(thirty_days)

        return render(
            request,
            "assistant/usage.html",
            {
                "month_rows": month_rows,
                "month_total": month_total,
                "thirty_day_total": thirty_day_total,
                "month_start": month_start,
            },
        )


class TasteProfileForm(forms.ModelForm):
    class Meta:
        model = TasteProfile
        fields = [
            "text",
            "menu_taste_match",
            "menu_best_value",
            "menu_most_interesting",
            "menu_notes",
        ]
        labels = {"text": "Your taste profile"}
        widgets = {
            "text": forms.Textarea(attrs={"rows": 12}),
            "menu_notes": forms.Textarea(attrs={"rows": 4}),
        }


class TasteProfileView(LoginRequiredMixin, FormView):
    """Onboarding/editing for the user's taste profile.

    The text goes into every pairing/menu/email prompt, so recommendations
    are tailored per person. An AI draft (from tasting history) can prefill
    it, but the user always edits and saves the final wording.
    """

    template_name = "assistant/profile.html"
    form_class = TasteProfileForm

    def get_profile(self):
        profile, _ = TasteProfile.objects.get_or_create(user=self.request.user)
        return profile

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_profile()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        draft = self.request.session.pop("profile_draft", None)
        if draft:
            initial["text"] = draft
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["has_draft"] = bool(self.request.GET.get("drafted"))
        return context

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Taste profile saved.")
        return redirect("assistant:profile")


class DraftProfileView(LoginRequiredMixin, View):
    """POST-only: AI-draft the profile from tasting history; prefills the form."""

    def post(self, request):
        profile, _ = TasteProfile.objects.get_or_create(user=request.user)
        try:
            draft = sommelier.draft_taste_profile(request.user, current_text=profile.text)
        except sommelier.SommelierError as exc:
            messages.error(request, f"Draft failed: {exc}")
            return redirect("assistant:profile")

        request.session["profile_draft"] = draft.profile_text
        messages.info(
            request, "Draft loaded below — edit as you like, nothing is saved until you save."
        )
        return redirect(f"{reverse('assistant:profile')}?drafted=1")


class SuggestionListView(LoginRequiredMixin, ListView):
    """Digested distributor emails, unreviewed first."""

    template_name = "assistant/suggestions.html"
    context_object_name = "emails"
    paginate_by = 25

    def get_queryset(self):
        qs = DistributorEmail.objects.all()
        if not self.request.GET.get("all"):
            qs = qs.filter(reviewed=False)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["showing_all"] = bool(self.request.GET.get("all"))
        return context


class EmailReviewView(LoginRequiredMixin, View):
    """POST-only: mark a distributor email digest as reviewed/dismissed."""

    def post(self, request, pk):
        email = DistributorEmail.objects.filter(pk=pk).first()
        if email is None:
            messages.error(request, "Email not found.")
        else:
            email.reviewed = True
            email.save(update_fields=["reviewed", "modified"])
            messages.success(request, "Marked reviewed.")
        return redirect(request.POST.get("next") or "assistant:suggestions")
