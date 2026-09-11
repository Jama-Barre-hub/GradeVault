"""Tests for the public demo's read-only guarantee.

The demo hands working credentials to anyone who asks. Two things must
therefore both be true, and each is worthless without the other:

  - with DEMO_MODE on, nothing a visitor does can change stored data
  - with DEMO_MODE off, everything still saves exactly as before

The second is the one that is easy to forget. A guard that quietly
blocked writes in a real school would destroy the system's actual job —
recording marks — so it is tested first and in as much detail as the
blocking itself.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from accounts.demo import (
    DEMO_ADMIN_USERNAME,
    DEMO_STUDENT_USERNAME,
    DEMO_TEACHER_USERNAME,
)
from accounts.models import User
from audit.models import AuditLog
from schools.management.commands.seed_demo import DEMO_SCHOOL_NAME
from schools.models import Assessment, Enrollment, Institution, Score

DEMO_PASSWORD = "known-demo-pw"


@pytest.fixture
def demo_school(db):
    """A small seeded demo school with its first term published."""
    call_command(
        "seed_demo",
        "--students",
        "2",
        "--publish",
        "--password",
        DEMO_PASSWORD,
        stdout=StringIO(),
    )
    return Institution.objects.get(name=DEMO_SCHOOL_NAME)


@pytest.fixture
def mark_sheet_post(demo_school):
    """A URL and payload that genuinely saves a mark when allowed.

    Built from a real teaching assignment rather than invented ids, so
    the request exercises the same path a teacher's browser takes. If
    this stopped being a valid write, the blocking tests below would
    pass for the wrong reason.
    """
    teacher = User.objects.get(username=DEMO_TEACHER_USERNAME).teacher_profile
    assignment = teacher.assignments.select_related("subject", "classroom").first()
    assert assignment is not None, "the demo teacher must teach something"

    classroom = assignment.classroom
    term = classroom.academic_year.terms.order_by("sequence").first()
    assessment = Assessment.objects.filter(
        term=term, subject=assignment.subject, classroom=classroom
    ).first()
    enrollment = Enrollment.objects.filter(classroom=classroom, is_active=True).first()

    url = reverse(
        "mark_sheet",
        kwargs={
            "classroom_id": classroom.id,
            "subject_id": assignment.subject.id,
            "term_id": term.id,
        },
    )
    return url, {f"m-{enrollment.id}-{assessment.id}": "37"}, enrollment, assessment


def _marks_now(enrollment, assessment):
    score = Score.objects.filter(enrollment=enrollment, assessment=assessment).first()
    return score.marks if score else None


# ---------------------------------------------------------- demo mode off


def test_marks_still_save_when_demo_mode_is_off(settings, client, mark_sheet_post):
    """The guard must be genuinely inert in a real school deployment.

    This is the most important test in the file. A middleware that
    blocked writes for an actual school would break the one thing
    GradeVault exists to do.
    """
    settings.DEMO_MODE = False
    url, payload, enrollment, assessment = mark_sheet_post

    client.login(username=DEMO_TEACHER_USERNAME, password=DEMO_PASSWORD)
    response = client.post(url, payload)

    assert response.status_code == 302
    assert _marks_now(enrollment, assessment) == Decimal("37.00")


# ----------------------------------------------------------- demo mode on


def test_a_mark_cannot_be_changed_when_demo_mode_is_on(
    settings, client, mark_sheet_post
):
    settings.DEMO_MODE = True
    url, payload, enrollment, assessment = mark_sheet_post
    before = _marks_now(enrollment, assessment)

    client.login(username=DEMO_TEACHER_USERNAME, password=DEMO_PASSWORD)
    response = client.post(url, payload)

    assert response.status_code == 302
    assert _marks_now(enrollment, assessment) == before


def test_a_refused_write_leaves_no_audit_entry(settings, client, mark_sheet_post):
    """A demo that forged audit rows would undermine the project's
    central claim: that the log records what really happened."""
    settings.DEMO_MODE = True
    url, payload, _enrollment, _assessment = mark_sheet_post
    before = AuditLog.objects.count()

    client.login(username=DEMO_TEACHER_USERNAME, password=DEMO_PASSWORD)
    client.post(url, payload)

    assert AuditLog.objects.count() == before


def test_the_visitor_is_told_why_nothing_was_saved(settings, client, mark_sheet_post):
    """Silence would read as a broken site. Opening a mark sheet, typing
    and pressing Save is the first thing a visitor tries."""
    settings.DEMO_MODE = True
    url, payload, _enrollment, _assessment = mark_sheet_post

    client.login(username=DEMO_TEACHER_USERNAME, password=DEMO_PASSWORD)
    response = client.post(url, payload, follow=True)

    assert response.status_code == 200
    assert "public demo" in response.content.decode().lower()


def test_reading_is_untouched_by_demo_mode(settings, client, mark_sheet_post):
    """Refusing writes must not refuse the demo itself."""
    settings.DEMO_MODE = True
    url, _payload, _enrollment, _assessment = mark_sheet_post

    client.login(username=DEMO_TEACHER_USERNAME, password=DEMO_PASSWORD)

    assert client.get(url).status_code == 200


def test_a_student_still_sees_published_results(settings, client, demo_school):
    """The demo's whole promise: sign in as a student, see a real grade."""
    settings.DEMO_MODE = True

    client.login(username=DEMO_STUDENT_USERNAME, password=DEMO_PASSWORD)
    response = client.get(reverse("student_results"))

    assert response.status_code == 200


def test_the_django_admin_refuses_deletions_even_for_a_superuser(
    settings, client, demo_school
):
    """The admin is a write surface too, and a far more dangerous one:
    one visitor deleting the demo school ends the demo for everyone.

    Deliberately tested as a *superuser*. `demo-admin` holds view
    permissions only, so it would be refused by the permission system
    whether or not this middleware existed — the test would pass while
    proving nothing. A superuser has every permission, so the only thing
    that can refuse it is the demo guard, which is what makes this the
    real assertion that DEMO_MODE binds every account without exception.
    """
    settings.DEMO_MODE = True
    User.objects.create_superuser(username="operator", password=DEMO_PASSWORD)
    subject = demo_school.subjects.first()

    client.login(username="operator", password=DEMO_PASSWORD)
    client.post(
        reverse("admin:schools_subject_delete", args=[subject.id]), {"post": "yes"}
    )

    assert demo_school.subjects.filter(pk=subject.pk).exists()


# --------------------------------------------------- nothing leaks when off


def test_a_real_school_is_never_told_about_demo_accounts(settings, client, db):
    """The public page is the same template for every deployment.

    A real school's front page must not advertise sign-in details for
    accounts that do not exist on it.
    """
    settings.DEMO_MODE = False

    body = client.get(reverse("home")).content.decode()

    assert "demo-teacher" not in body
    assert "demo-password" not in body
    assert "public demo" not in body.lower()


def test_the_demo_page_advertises_exactly_the_accounts_that_exist(
    settings, client, demo_school
):
    """The published credentials and the seeded accounts come from one
    module, so this proves they have not drifted apart."""
    settings.DEMO_MODE = True
    settings.DEMO_PASSWORD = DEMO_PASSWORD

    body = client.get(reverse("home")).content.decode()

    for username in (
        DEMO_ADMIN_USERNAME,
        DEMO_TEACHER_USERNAME,
        DEMO_STUDENT_USERNAME,
    ):
        assert username in body
        assert User.objects.filter(username=username).exists()

    assert DEMO_PASSWORD in body


# ------------------------------------------------------- signing in and out


def test_signing_in_still_works_in_demo_mode(settings, client, demo_school):
    """Login is a POST. A demo nobody can sign in to is not a demo."""
    settings.DEMO_MODE = True

    response = client.post(
        reverse("login"),
        {"username": DEMO_TEACHER_USERNAME, "password": DEMO_PASSWORD},
    )

    assert response.status_code == 302
    assert response.wsgi_request.user.is_authenticated


def test_signing_out_still_works_in_demo_mode(settings, client, demo_school):
    """Logout is a POST in Django 5+, and a visitor must be able to
    leave one demo role to try another."""
    settings.DEMO_MODE = True
    client.login(username=DEMO_TEACHER_USERNAME, password=DEMO_PASSWORD)

    response = client.post(reverse("logout"))

    assert response.status_code == 302
    assert not response.wsgi_request.user.is_authenticated


# ------------------------------------------------------------- health check


def test_healthz_reports_ok(client, db):
    response = client.get(reverse("healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_is_not_cached(client, db):
    """A cached health check reports the state of a past request."""
    response = client.get(reverse("healthz"))

    assert "no-cache" in response.headers.get("Cache-Control", "")
