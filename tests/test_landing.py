"""Tests for the public page.

Two things matter here. It must be reachable without an account, since
that is its entire purpose. And it must not claim anything untrue: a
school results system that overstates itself on its own front page has
already lost the argument it is trying to win.
"""

import pytest
from django.urls import reverse

from accounts.models import User

PASSWORD = "test-password-123"


@pytest.mark.django_db
def test_a_visitor_who_is_not_signed_in_sees_the_public_page(client):
    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert "Results your school can prove" in response.content.decode()


@pytest.mark.django_db
def test_a_signed_in_person_is_sent_to_their_own_area(client):
    """A marketing page is no use to a teacher with marks to enter."""
    User.objects.create_user(
        username="tch-one", password=PASSWORD, role=User.Role.TEACHER
    )
    client.login(username="tch-one", password=PASSWORD)

    response = client.get(reverse("home"))

    assert response.status_code == 302
    assert response["Location"] == reverse("dashboard")


@pytest.mark.django_db
def test_the_public_page_needs_no_database_records(client):
    """It must work on a brand new installation, before any school
    exists, or nobody could ever read about the software."""
    response = client.get(reverse("home"))

    assert response.status_code == 200


@pytest.mark.django_db
def test_the_sample_report_is_labelled_as_an_example(client):
    """The page shows a specimen result card. Anyone glancing at it must
    be able to tell it is not a real child's marks."""
    body = client.get(reverse("home")).content.decode()

    assert "Example only" in body
    assert "Not a real student" in body


@pytest.mark.django_db
def test_the_page_claims_no_users_it_does_not_have(client):
    """GradeVault has no schools using it. Invented adoption figures and
    testimonials would cost exactly the trust this page exists to earn,
    and a head teacher who discovered the fiction would be right to walk
    away."""
    body = client.get(reverse("home")).content.decode().lower()

    for claim in [
        "happy customer",
        "trusted by",
        "students trust us",
        "schools trust",
        "testimonial",
        "monthly visitors",
    ]:
        assert claim not in body, f"the public page claims '{claim}'"


@pytest.mark.django_db
def test_the_page_admits_it_has_not_been_security_reviewed(client):
    """Stated plainly rather than buried, because a school deciding
    whether to trust it with children's records deserves to know."""
    body = client.get(reverse("home")).content.decode()

    assert "not yet been examined" in body


@pytest.mark.django_db
def test_the_public_page_offers_a_way_to_sign_in(client):
    body = client.get(reverse("home")).content.decode()

    assert reverse("login") in body


@pytest.mark.django_db
def test_the_public_page_states_who_it_is_for(client):
    """The audience is Somali schools, and the page should say so rather
    than leaving a visitor to guess whether it applies to them."""
    body = client.get(reverse("home")).content.decode()

    assert "Somalia" in body
