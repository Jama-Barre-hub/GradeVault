"""Tests for the limit on failed sign-in attempts.

Student usernames are predictable by design — STU-2026-0001 upwards — so
an attacker never has to guess *which* accounts exist, only the password.
Without a limit, that is an unlimited number of free attempts against a
known account holding a child's records.

The tests that matter most here are the ones proving the limit does not
become a weapon: locking the wrong thing would let an attacker shut a
whole school out, or lock a named student out on purpose.
"""

import pytest
from axes.helpers import get_client_str
from axes.models import AccessAttempt
from django.urls import reverse

from accounts.models import User

PASSWORD = "correct-horse-battery"
WRONG = "not-the-password"
LIMIT = 10


@pytest.fixture(autouse=True)
def _sign_in_limits_on(settings):
    """These tests are about the limiter, so it must be active."""
    settings.AXES_ENABLED = True


@pytest.fixture(autouse=True)
def clear_attempts(db):
    """Axes stores attempts in the database; start each test clean."""
    AccessAttempt.objects.all().delete()
    yield
    AccessAttempt.objects.all().delete()


@pytest.fixture
def student(db):
    return User.objects.create_user(
        username="STU-2026-0001", password=PASSWORD, role=User.Role.STUDENT
    )


def attempt(client, username, password, ip="10.0.0.1"):
    return client.post(
        reverse("login"),
        {"username": username, "password": password},
        REMOTE_ADDR=ip,
    )


# ---------- the limit exists ----------


@pytest.mark.permissions
def test_a_correct_password_still_works(client, student):
    response = attempt(client, student.username, PASSWORD)

    assert response.status_code == 302


@pytest.mark.permissions
def test_repeated_wrong_passwords_are_eventually_refused(client, student):
    """The sixth attempt must not even be checked.

    429 rather than 403: the request is not forbidden, it is rate
    limited, and the distinction tells an honest user their password may
    well be right and they should simply wait.
    """
    for _ in range(LIMIT):
        attempt(client, student.username, WRONG)

    response = attempt(client, student.username, WRONG)

    assert response.status_code == 429


@pytest.mark.permissions
def test_the_right_password_is_refused_once_locked(client, student):
    """Locking only wrong guesses would let an attacker keep trying: the
    lock has to hold even when the guess finally lands."""
    for _ in range(LIMIT):
        attempt(client, student.username, WRONG)

    response = attempt(client, student.username, PASSWORD)

    assert response.status_code == 429


@pytest.mark.permissions
def test_a_locked_out_visitor_is_told_why(client, student):
    for _ in range(LIMIT):
        attempt(client, student.username, WRONG)

    body = attempt(client, student.username, WRONG).content.decode()

    assert "Too many attempts" in body


# ---------- the limit must not become a weapon ----------


@pytest.mark.permissions
def test_one_locked_student_does_not_lock_the_whole_school(client, db):
    """Somali schools and internet cafes commonly share one public
    address. Locking by address alone would take every student behind it
    offline whenever one person mistyped."""
    victim = User.objects.create_user(
        username="STU-2026-0001", password=PASSWORD, role=User.Role.STUDENT
    )
    classmate = User.objects.create_user(
        username="STU-2026-0002", password=PASSWORD, role=User.Role.STUDENT
    )

    shared_ip = "41.78.0.9"
    for _ in range(LIMIT + 1):
        attempt(client, victim.username, WRONG, ip=shared_ip)

    response = attempt(client, classmate.username, PASSWORD, ip=shared_ip)

    assert response.status_code == 302, (
        "A classmate on the same address was locked out by someone else's "
        "failed attempts."
    )


@pytest.mark.permissions
def test_a_student_can_still_sign_in_from_elsewhere(client, student):
    """Locking by username alone would let anyone lock a named student
    out deliberately, simply by guessing wrong five times."""
    for _ in range(LIMIT + 1):
        attempt(client, student.username, WRONG, ip="203.0.113.5")

    response = attempt(client, student.username, PASSWORD, ip="41.78.0.9")

    assert response.status_code == 302, (
        "The real student could not sign in from their own device after "
        "an attacker elsewhere triggered a lockout."
    )


# ---------- what gets recorded ----------


@pytest.mark.permissions
def test_the_attempted_password_is_never_stored(client, student):
    """A record of failed attempts must not become a list of passwords
    people nearly use."""
    attempt(client, student.username, "my-real-password-elsewhere")

    stored = AccessAttempt.objects.get()
    haystack = " ".join(
        str(value) for value in stored.__dict__.values() if value is not None
    )

    assert "my-real-password-elsewhere" not in haystack


@pytest.mark.permissions
def test_the_attempted_username_is_recorded(client, student):
    """An administrator should be able to see which accounts are probed."""
    attempt(client, student.username, WRONG)

    stored = AccessAttempt.objects.get()

    assert stored.username == student.username
    assert get_client_str(
        stored.username, stored.ip_address, stored.user_agent, stored.path_info, None
    )


@pytest.mark.permissions
def test_signing_in_successfully_clears_the_count(client, student):
    """Yesterday's typos must not accumulate into tomorrow's lockout."""
    for _ in range(LIMIT - 1):
        attempt(client, student.username, WRONG)

    attempt(client, student.username, PASSWORD)
    client.logout()

    response = attempt(client, student.username, WRONG)

    assert response.status_code != 429
