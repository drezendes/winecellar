"""Distributor-inbox webhook + service tests. Sommelier mocked, email sent to
Django's locmem backend (mailoutbox) — no network, no Anthropic key."""

from email.message import EmailMessage as PyEmailMessage
from unittest import mock

import pytest

from assistant import inbox, sommelier
from assistant.models import DistributorEmail
from assistant.schemas import EmailDigest, EmailOffer, EmailPick

URL = "/api/distributor-inbox/"
SECRET = "top-secret-worker-token"


def raw_email(subject="Spring Burgundy offer", sender="offers@dist.example",
              text="Volnay 1er Cru, $65/btl, 10% off 6+.", message_id="<a1@dist.example>",
              html=None):
    msg = PyEmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "cellar@example.com"
    if message_id:
        msg["Message-ID"] = message_id
    msg["Date"] = "Mon, 14 Jul 2026 09:00:00 +0000"
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


WINE = EmailDigest(
    forward=False,
    distributor="Dist",
    summary="A Burgundy allocation.",
    offers=[EmailOffer(wine="Domaine Test Volnay 1er Cru", vintage=2022, price="$65/btl")],
    taste_match=[EmailPick(wine="Domaine Test Volnay 1er Cru", price="$65/btl",
                           reasoning="You rate red Burgundy highly and hold none.")],
)
MULTI = EmailDigest(
    forward=False,
    distributor="Dist",
    summary="A mixed Loire offer.",
    offers=[
        EmailOffer(wine="Clos Test Vouvray Sec", vintage=2023, price="$28/btl"),
        EmailOffer(wine="Domaine Test Chinon", vintage=2022, price="$24/btl"),
    ],
    taste_match=[EmailPick(wine="Clos Test Vouvray Sec", price="$28/btl", reasoning="Fits.")],
    best_value=[EmailPick(wine="Domaine Test Chinon", price="$24/btl", reasoning="Well priced.")],
)
NONWINE = EmailDigest(forward=True, forward_reason="whiskey presale", summary="Bourbon barrel picks.")


@pytest.fixture
def configured(settings):
    settings.DISTRIBUTOR_WEBHOOK_SECRET = SECRET
    settings.DISTRIBUTOR_RECIPIENT = "owner@example.com"
    settings.DISTRIBUTOR_OWNER_USERNAME = ""
    return settings


def post(client, body=None, token=SECRET):
    return client.post(
        URL, data=body if body is not None else raw_email(),
        content_type="message/rfc822", headers={"Authorization": f"Bearer {token}"},
    )


class TestParseMime:
    def test_prefers_plain_over_html(self):
        parsed = inbox.parse_mime(raw_email(text="plain body", html="<p>html body</p>"))
        assert parsed["text"] == "plain body\n"
        assert parsed["subject"] == "Spring Burgundy offer"
        assert parsed["message_id"] == "<a1@dist.example>"
        assert parsed["received_at"] is not None

    def test_html_only_stripped(self):
        msg = PyEmailMessage()
        msg["Subject"] = "s"; msg["From"] = "f@x"; msg["Message-ID"] = "<h@x>"
        msg.set_content("<p>Big <b>Barolo</b> sale</p>", subtype="html")
        parsed = inbox.parse_mime(msg.as_bytes())
        assert "Barolo" in parsed["text"] and "<b>" not in parsed["text"]

    def test_missing_message_id_hashes_body(self):
        parsed = inbox.parse_mime(raw_email(message_id=None))
        assert parsed["message_id"].startswith("sha256:")


class TestWebhookAuth:
    def test_disabled_when_secret_unset(self, client, settings):
        settings.DISTRIBUTOR_WEBHOOK_SECRET = ""
        assert post(client).status_code == 503

    def test_wrong_token_unauthorized(self, client, configured):
        assert post(client, token="nope").status_code == 401

    def test_empty_body_rejected(self, client, configured):
        assert post(client, body=b"").status_code == 400

    def test_get_not_allowed(self, client, configured):
        assert client.get(URL).status_code == 405


class TestWebhookFlow:
    def test_wine_offer_handled_and_sent(self, db, client, configured, mailoutbox):
        with mock.patch.object(sommelier, "digest_email", return_value=WINE):
            resp = post(client)
        assert resp.status_code == 200 and resp.json()["action"] == "handled"
        assert len(mailoutbox) == 1
        sent = mailoutbox[0]
        assert sent.to == ["owner@example.com"]
        # single-offer → compact: wine named once, question headings collapsed
        assert "Fit:" in sent.body and "Is it a fit?" not in sent.body
        assert sent.body.count("Domaine Test Volnay 1er Cru") == 1
        # no inline quote — the original is the attachment, not duplicated text
        assert "Volnay 1er Cru, $65/btl, 10% off 6+." not in sent.body
        assert "attached (original.eml)" in sent.body
        # reply goes to the distributor (never back into cellar@ → the Worker)
        assert sent.reply_to == ["offers@dist.example"]
        # the raw original rides along so order links/images survive stripping
        assert [a[0] for a in sent.attachments] == ["original.eml"]
        email = DistributorEmail.objects.get()
        assert email.status == DistributorEmail.Status.ANALYZED

    def test_multi_offer_uses_lens_headings(self, db, client, configured, mailoutbox):
        with mock.patch.object(sommelier, "digest_email", return_value=MULTI):
            resp = post(client)
        assert resp.status_code == 200
        body = mailoutbox[0].body
        assert "Is it a fit?" in body and "Good value?" in body
        assert "Clos Test Vouvray Sec" in body and "Domaine Test Chinon" in body

    def test_non_wine_forwarded_not_sent(self, db, client, configured, mailoutbox):
        with mock.patch.object(sommelier, "digest_email", return_value=NONWINE):
            resp = post(client)
        assert resp.status_code == 200 and resp.json()["action"] == "forward"
        assert len(mailoutbox) == 0
        assert DistributorEmail.objects.get().status == DistributorEmail.Status.FORWARDED

    def test_idempotent_on_message_id(self, db, client, configured, mailoutbox):
        with mock.patch.object(sommelier, "digest_email", return_value=WINE):
            post(client)
            resp = post(client)  # same Message-ID
        assert resp.json().get("duplicate") is True
        assert DistributorEmail.objects.count() == 1
        assert len(mailoutbox) == 1  # not re-sent

    def test_analysis_failure_returns_502(self, db, client, configured, mailoutbox):
        with mock.patch.object(sommelier, "digest_email",
                               side_effect=sommelier.SommelierError("boom")):
            resp = post(client)
        assert resp.status_code == 502  # -> Worker forwards the original untouched
        assert len(mailoutbox) == 0
        assert DistributorEmail.objects.get().status == DistributorEmail.Status.FAILED
