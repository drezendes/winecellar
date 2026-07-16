"""Email pipeline tests: IMAP mocked, sommelier mocked — no network."""

import datetime
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from assistant import email_pipeline, sommelier
from assistant.models import DistributorEmail
from assistant.schemas import EmailDigest, EmailOffer


@pytest.fixture
def user(db):
    return User.objects.create_user(username="owner", password="test-pass-123")


def fake_message(uid="101", subject="March Burgundy offer", text="Great deals on Volnay..."):
    msg = mock.Mock()
    msg.uid = uid
    msg.subject = subject
    msg.from_ = "offers@localdistributor.com"
    msg.date = datetime.datetime(2026, 7, 14, 9, 0, tzinfo=datetime.timezone.utc)
    msg.text = text
    msg.html = "<p>html body</p>"
    return msg


DIGEST = EmailDigest(
    distributor="Local Distributor",
    summary="Spring Burgundy allocation offer.",
    offers=[
        EmailOffer(
            wine="Domaine Test Volnay 1er Cru",
            vintage=2022,
            price="$65/btl",
            deal_terms="10% off 6+",
            action="buy",
            reasoning="You rate red Burgundy highly and hold none.",
        ),
        EmailOffer(
            wine="Bulk Chardonnay", vintage=2024, price="$12/btl",
            action="skip", reasoning="Below the quality bar of the cellar.",
        ),
    ],
)


@pytest.fixture
def mock_mailbox(settings):
    settings.DISTRIBUTOR_IMAP_HOST = "imap.example.com"
    settings.DISTRIBUTOR_IMAP_USER = "cellar@example.com"
    settings.DISTRIBUTOR_IMAP_PASSWORD = "secret"
    with mock.patch.object(email_pipeline, "MailBox") as mailbox_cls:
        mailbox = mailbox_cls.return_value.login.return_value.__enter__.return_value
        yield mailbox


class TestPollMailbox:
    def test_fetches_and_digests(self, db, mock_mailbox):
        mock_mailbox.fetch.return_value = [fake_message()]
        with mock.patch.object(sommelier, "digest_email", return_value=DIGEST):
            stats = email_pipeline.poll_mailbox()
        assert stats == {"fetched": 1, "digested": 1, "failed": 0, "skipped": 0}
        email = DistributorEmail.objects.get()
        assert email.status == DistributorEmail.Status.ANALYZED
        assert email.result["summary"].startswith("Spring Burgundy")
        assert len(email.actionable_offers) == 1  # skip verdicts filtered out

    def test_idempotent_on_rerun(self, db, mock_mailbox):
        mock_mailbox.fetch.return_value = [fake_message(uid="42")]
        with mock.patch.object(sommelier, "digest_email", return_value=DIGEST):
            email_pipeline.poll_mailbox()
            stats = email_pipeline.poll_mailbox()
        assert stats["skipped"] == 1
        assert DistributorEmail.objects.count() == 1

    def test_digest_failure_recorded(self, db, mock_mailbox):
        mock_mailbox.fetch.return_value = [fake_message()]
        with mock.patch.object(
            sommelier, "digest_email", side_effect=sommelier.SommelierError("boom")
        ):
            stats = email_pipeline.poll_mailbox()
        assert stats["failed"] == 1
        email = DistributorEmail.objects.get()
        assert email.status == DistributorEmail.Status.FAILED
        assert email.error == "boom"

    def test_html_only_email_falls_back_to_stripped_html(self, db, mock_mailbox):
        msg = fake_message(text="")
        msg.html = "<p>Big <b>Barolo</b> sale</p>"
        mock_mailbox.fetch.return_value = [msg]
        with mock.patch.object(sommelier, "digest_email", return_value=DIGEST) as digest:
            email_pipeline.poll_mailbox()
        assert "Barolo" in digest.call_args.args[0]
        assert "<b>" not in digest.call_args.args[0]

    def test_unconfigured_mailbox_raises(self, db, settings):
        settings.DISTRIBUTOR_IMAP_HOST = ""
        with pytest.raises(email_pipeline.MailboxNotConfigured):
            email_pipeline.poll_mailbox()


class TestSuggestionViews:
    @pytest.fixture
    def email(self, db):
        return DistributorEmail.objects.create(
            message_uid="INBOX:7",
            sender="offers@localdistributor.com",
            subject="March offer",
            status=DistributorEmail.Status.ANALYZED,
            result=DIGEST.model_dump(),
        )

    def test_suggestions_lists_unreviewed(self, client, user, email):
        client.force_login(user)
        response = client.get(reverse("assistant:suggestions"))
        assert email in response.context["emails"]

    def test_reviewed_hidden_unless_all(self, client, user, email):
        email.reviewed = True
        email.save()
        client.force_login(user)
        response = client.get(reverse("assistant:suggestions"))
        assert email not in response.context["emails"]
        response = client.get(reverse("assistant:suggestions"), {"all": "1"})
        assert email in response.context["emails"]

    def test_review_action(self, client, user, email):
        client.force_login(user)
        response = client.post(reverse("assistant:email_review", kwargs={"pk": email.pk}))
        assert response.status_code == 302
        email.refresh_from_db()
        assert email.reviewed is True

    def test_dashboard_shows_unreviewed(self, client, user, email):
        client.force_login(user)
        response = client.get(reverse("cellar:dashboard"))
        assert email in response.context["unreviewed_emails"]
        assert b"New buying suggestions" in response.content
