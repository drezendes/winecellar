"""Cellar valuation: the batched run, cost-basis rule, and series. AI mocked."""

import datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from assistant import sommelier, valuation
from assistant.models import ValuationRun, VintageValuation
from assistant.schemas import CellarValuation, VintageValue
from cellar.models import Bottle, Producer, Vintage, Wine


@pytest.fixture
def user(db):
    return User.objects.create_user(username="owner", password="test-pass-123")


@pytest.fixture
def vintage(db):
    producer = Producer.objects.create(name="Ridge")
    wine = Wine.objects.create(producer=producer, name="Monte Bello", wine_type="red")
    return Vintage.objects.create(wine=wine, year=2019)


def fake_response(parsed):
    response = mock.Mock()
    response.parsed_output = parsed
    response.model = "claude-opus-4-8"
    response.usage.input_tokens = 4000
    response.usage.output_tokens = 2000
    response.usage.cache_read_input_tokens = 0
    return response


@pytest.fixture
def mock_parse():
    with mock.patch.object(sommelier, "_get_client") as get_client:
        yield get_client.return_value.messages.parse


def complete_run(vintage, value, created=None, note=""):
    """Test helper: a completed run with one priced valuation row."""
    run = ValuationRun.objects.create(status=ValuationRun.Status.COMPLETE)
    if created:
        ValuationRun.objects.filter(pk=run.pk).update(created=created)
        run.refresh_from_db()
    VintageValuation.objects.create(
        run=run, vintage=vintage,
        per_bottle_value=Decimal(value) if value is not None else None, note=note,
    )
    return run


class TestRunValuation:
    def test_run_saves_rows_and_completes(self, db, vintage, mock_parse):
        Bottle.objects.create(vintage=vintage)
        mock_parse.return_value = fake_response(
            CellarValuation(
                items=[VintageValue(vintage_id=str(vintage.pk), per_bottle_usd=210.0)],
                general_note="Steady market.",
            )
        )
        run = ValuationRun.objects.create()
        valuation.run_valuation(run.pk)
        run.refresh_from_db()
        assert run.status == ValuationRun.Status.COMPLETE
        row = run.valuations.get()
        assert row.per_bottle_value == Decimal("210.00")
        # Prompt used the exact vintage id
        prompt = mock_parse.call_args.kwargs["messages"][0]["content"]
        assert str(vintage.pk) in prompt

    def test_unpriceable_stored_as_null_and_hallucinations_dropped(
        self, db, vintage, mock_parse
    ):
        Bottle.objects.create(vintage=vintage)
        mock_parse.return_value = fake_response(
            CellarValuation(
                items=[
                    VintageValue(vintage_id=str(vintage.pk), per_bottle_usd=None, note="too obscure"),
                    VintageValue(vintage_id="not-a-uuid", per_bottle_usd=99.0),
                ]
            )
        )
        run = ValuationRun.objects.create()
        valuation.run_valuation(run.pk)
        assert run.valuations.count() == 1
        assert run.valuations.get().per_bottle_value is None

    def test_failure_lands_on_run(self, db, vintage, mock_parse):
        Bottle.objects.create(vintage=vintage)
        mock_parse.side_effect = sommelier.anthropic.APIConnectionError(request=mock.Mock())
        run = ValuationRun.objects.create()
        valuation.run_valuation(run.pk)
        run.refresh_from_db()
        assert run.status == ValuationRun.Status.FAILED
        assert run.error


class TestCostBasis:
    def test_actual_price_wins(self, db, vintage):
        bottle = Bottle.objects.create(vintage=vintage, purchase_price="180.00")
        bottle.refresh_from_db()  # purchase_price as the DB-loaded Decimal
        complete_run(vintage, "210.00")
        basis, kind = valuation.bottle_basis(bottle, valuation._history())
        assert basis == Decimal("180.00")
        assert kind == "actual"

    def test_first_mark_when_no_actual(self, db, vintage):
        bottle = Bottle.objects.create(vintage=vintage)
        complete_run(vintage, "200.00")
        complete_run(vintage, "230.00")
        basis, kind = valuation.bottle_basis(bottle, valuation._history())
        assert basis == Decimal("200.00")  # FIRST mark, not latest
        assert kind == "first_mark"

    def test_marks_before_acquisition_ignored(self, db, vintage):
        old = timezone.now() - datetime.timedelta(days=90)
        complete_run(vintage, "150.00", created=old)  # before the bottle existed
        bottle = Bottle.objects.create(vintage=vintage)
        complete_run(vintage, "220.00")
        basis, _ = valuation.bottle_basis(bottle, valuation._history())
        assert basis == Decimal("220.00")

    def test_magnum_scales_first_mark(self, db, vintage):
        bottle = Bottle.objects.create(vintage=vintage, size=Bottle.Size.MAGNUM)
        complete_run(vintage, "100.00")
        basis, _ = valuation.bottle_basis(bottle, valuation._history())
        assert basis == Decimal("200.00")


class TestSummary:
    def test_gain_uses_basis_rule(self, db, vintage):
        Bottle.objects.create(vintage=vintage, purchase_price="180.00")
        Bottle.objects.create(vintage=vintage)  # unknown cost
        complete_run(vintage, "210.00")
        summary = valuation.summarize()
        latest = summary["latest"]
        # est = 2 x 210; basis = 180 (actual) + 210 (first mark, zero gain)
        assert latest["estimated"] == Decimal("420.00")
        assert latest["basis"] == Decimal("390.00")
        assert latest["gain"] == Decimal("30.00")
        assert latest["basis_kinds"] == {"actual": 1, "first_mark": 1, "none": 0}

    def test_series_values_bottles_held_at_run_time(self, db, vintage):
        old = timezone.now() - datetime.timedelta(days=90)
        bottle = Bottle.objects.create(vintage=vintage, purchase_price="100.00")
        Bottle.objects.filter(pk=bottle.pk).update(created=old)
        complete_run(vintage, "120.00", created=old + datetime.timedelta(days=1))
        # Bottle consumed after the first run, before the second
        bottle.refresh_from_db()
        bottle.mark_consumed(on_date=timezone.localdate() - datetime.timedelta(days=30))
        complete_run(vintage, "150.00")
        series = valuation.summarize()["series"]
        assert series[0]["bottles"] == 1  # held at run 1
        assert series[1]["bottles"] == 0  # gone by run 2

    def test_none_before_first_run(self, db):
        assert valuation.summarize() is None


class TestView:
    def test_page_renders_summary(self, client, user, vintage):
        Bottle.objects.create(vintage=vintage, purchase_price="180.00")
        complete_run(vintage, "210.00")
        client.force_login(user)
        response = client.get(reverse("assistant:cellar_value"))
        assert response.status_code == 200
        assert b"estimated value" in response.content
        assert b"cost basis" in response.content

    def test_post_starts_single_run(self, client, user, vintage, mock_parse):
        Bottle.objects.create(vintage=vintage)
        mock_parse.return_value = fake_response(CellarValuation(items=[]))
        client.force_login(user)
        with mock.patch.object(valuation.threading, "Thread") as thread_cls:
            response = client.post(reverse("assistant:cellar_value"))
            assert response.status_code == 302
            assert thread_cls.called
            assert ValuationRun.objects.count() == 1
            # A second POST while pending must not start another run
            client.post(reverse("assistant:cellar_value"))
            assert ValuationRun.objects.count() == 1
