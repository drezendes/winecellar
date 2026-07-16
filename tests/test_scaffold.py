"""Scaffold smoke tests: auth gating and the dashboard render."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse


@pytest.fixture
def user(db):
    return User.objects.create_user(username="owner", password="test-pass-123")


def test_dashboard_requires_login(client):
    response = client.get(reverse("cellar:dashboard"))
    assert response.status_code == 302
    assert reverse("login") in response.url


def test_dashboard_renders_for_authenticated_user(client, user):
    client.force_login(user)
    response = client.get(reverse("cellar:dashboard"))
    assert response.status_code == 200
    assert b"Dashboard" in response.content


def test_login_page_is_public(client):
    response = client.get(reverse("login"))
    assert response.status_code == 200
