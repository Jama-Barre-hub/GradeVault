"""Tests for releasing and withdrawing a term's results.

Publishing is the single most consequential action in GradeVault: it
makes every mark in a term visible to every student in it at once, and
withdrawing takes them all back. Three things therefore have to hold.

  - Only an administrator can do it, and only for their own school.
  - It is never silent. Both directions write an audit entry naming the
    person who did it.
  - There is no route that changes `is_published` without recording it.

The last one is the reason two of these tests exist. Both directions
were reachable through the Django admin's ordinary edit form, which
writes the field directly and never calls `Term.publish()` — so the one
action the audit log exists to record was the one action that could be
taken without it.
"""

import pytest
from django.contrib.admin.sites import site
from django.urls import reverse

from audit.models import AuditLog
from factories import PASSWORD
from schools.models import Term

PAGE = "term_publication"


@pytest.fixture
def head_teacher(hodan):
    """An administrator at Hodan, with a student who has a mark."""
    hodan.add_student("Amina", "Yusuf", marks=32)
    return hodan.add_admin("hodan-head")


# ---------------------------------------------------------- who may look


@pytest.mark.permissions
def test_a_visitor_who_is_not_signed_in_is_sent_to_sign_in(client, hodan):
    response = client.get(reverse(PAGE))

    assert response.status_code == 302
    assert reverse("login") in response.url


@pytest.mark.permissions
@pytest.mark.parametrize("role", ["teacher", "student"])
def test_only_an_administrator_may_publish(client, hodan, role):
    """A teacher entering marks does not decide when a school releases
    them, and a student certainly does not."""
    if role == "teacher":
        user = hodan.add_teacher("hodan-tch").user
    else:
        user = hodan.add_student("Sagal", "Omar").student.user

    client.login(username=user.username, password=PASSWORD)

    assert client.get(reverse(PAGE)).status_code == 403
    assert client.post(reverse(PAGE), {"action": "publish"}).status_code == 403


def test_an_administrator_sees_their_own_terms(client, head_teacher, hodan):
    client.login(username=head_teacher.username, password=PASSWORD)

    response = client.get(reverse(PAGE))

    assert response.status_code == 200
    assert hodan.term.name in response.content.decode()


# --------------------------------------------------------------- tenancy


@pytest.mark.permissions
def test_another_schools_terms_are_not_listed(client, head_teacher, banadir):
    """Banadir's term must not appear on Hodan's publishing page."""
    client.login(username=head_teacher.username, password=PASSWORD)

    body = client.get(reverse(PAGE)).content.decode()

    assert str(banadir.year.name) not in body or banadir.institution.name not in body


@pytest.mark.permissions
def test_another_schools_term_cannot_be_published(client, head_teacher, banadir):
    """The term id arrives in a form, and a form contains whatever the
    person sending it decided to put in it. This is the attack."""
    client.login(username=head_teacher.username, password=PASSWORD)

    client.post(reverse(PAGE), {"action": "publish", "term": banadir.term.id})

    banadir.term.refresh_from_db()
    assert not banadir.term.is_published
    assert not AuditLog.objects.filter(action=AuditLog.Action.TERM_PUBLISHED).exists()


@pytest.mark.permissions
def test_an_administrator_with_no_school_can_publish_nothing(client, hodan):
    """Missing means nothing, not everything: failing closed is the
    difference between a bug and a breach."""
    from accounts.models import User

    stray = User.objects.create_user(
        username="no-school", password=PASSWORD, role=User.Role.ADMIN
    )
    client.login(username=stray.username, password=PASSWORD)

    client.post(reverse(PAGE), {"action": "publish", "term": hodan.term.id})

    hodan.term.refresh_from_db()
    assert not hodan.term.is_published


# ------------------------------------------------------ publishing works


def test_publishing_releases_the_term(client, head_teacher, hodan):
    client.login(username=head_teacher.username, password=PASSWORD)

    response = client.post(
        reverse(PAGE), {"action": "publish", "term": hodan.term.id}, follow=True
    )

    hodan.term.refresh_from_db()
    assert hodan.term.is_published
    assert hodan.term.published_by == head_teacher
    assert hodan.term.published_at is not None
    assert response.status_code == 200


def test_publishing_is_recorded_against_the_person_who_did_it(
    client, head_teacher, hodan
):
    client.login(username=head_teacher.username, password=PASSWORD)

    client.post(reverse(PAGE), {"action": "publish", "term": hodan.term.id})

    entry = AuditLog.objects.get(action=AuditLog.Action.TERM_PUBLISHED)
    assert entry.actor == head_teacher
    assert head_teacher.username in entry.actor_label
    assert entry.institution == hodan.institution


def test_withdrawing_hides_the_term_again(client, head_teacher, hodan):
    hodan.term.publish(released_by=head_teacher)
    client.login(username=head_teacher.username, password=PASSWORD)

    client.post(reverse(PAGE), {"action": "withdraw", "term": hodan.term.id})

    hodan.term.refresh_from_db()
    assert not hodan.term.is_published


def test_withdrawing_is_recorded_against_the_person_who_did_it(
    client, head_teacher, hodan
):
    """Withdrawing hides results from every student at once. It must not
    be the one action in the log with nobody's name against it."""
    hodan.term.publish(released_by=head_teacher)
    client.login(username=head_teacher.username, password=PASSWORD)

    client.post(reverse(PAGE), {"action": "withdraw", "term": hodan.term.id})

    entry = AuditLog.objects.get(action=AuditLog.Action.TERM_UNPUBLISHED)
    assert entry.actor == head_teacher
    assert entry.actor_label != "system"


def test_an_unrecognised_action_changes_nothing(client, head_teacher, hodan):
    client.login(username=head_teacher.username, password=PASSWORD)

    client.post(reverse(PAGE), {"action": "delete-everything", "term": hodan.term.id})

    hodan.term.refresh_from_db()
    assert not hodan.term.is_published
    # Scoped to publication entries: recording the fixture's mark already
    # wrote a score entry, and asserting an empty log would only prove
    # that the fixture is quiet.
    assert not AuditLog.objects.filter(
        action__in=[
            AuditLog.Action.TERM_PUBLISHED,
            AuditLog.Action.TERM_UNPUBLISHED,
        ]
    ).exists()


# ------------------------------------------------- the student's view of it


def test_a_student_sees_results_only_after_the_term_is_published(
    client, head_teacher, hodan
):
    """The end-to-end promise, driven through the real screen."""
    enrollment = hodan.add_student("Hodan", "Ali", marks=36)
    student = enrollment.student.user

    client.login(username=student.username, password=PASSWORD)
    before = client.get(reverse("student_results")).content.decode()

    client.logout()
    client.login(username=head_teacher.username, password=PASSWORD)
    client.post(reverse(PAGE), {"action": "publish", "term": hodan.term.id})

    client.logout()
    client.login(username=student.username, password=PASSWORD)
    after = client.get(reverse("student_results")).content.decode()

    assert hodan.subject.name not in before
    assert hodan.subject.name in after


# ------------------------------------------- no unrecorded route remains


@pytest.mark.permissions
def test_the_admin_form_cannot_flip_publication_directly(client, head_teacher, hodan):
    """Regression. `is_published` was an editable checkbox on the Django
    admin's Term form, so a whole term could be released to every student
    by ticking it — bypassing Term.publish(), and therefore writing no
    audit entry, no published_at and no published_by.
    """
    assert "is_published" in site._registry[Term].readonly_fields


@pytest.mark.permissions
def test_the_term_inline_cannot_flip_publication_either(client):
    """The same field was editable on the academic year's inline, which
    is a second door into the same room."""
    from schools.admin import AcademicYearAdmin

    inline = AcademicYearAdmin.inlines[0]

    assert "is_published" in inline.readonly_fields


def test_the_admin_bulk_withdraw_names_the_actor(client, head_teacher, hodan):
    """Regression: the bulk action called unpublish() with no actor, so
    every withdrawal made through the admin was logged as 'system'."""
    from django.test import RequestFactory

    from schools.admin import TermAdmin

    hodan.term.publish(released_by=head_teacher)

    request = RequestFactory().post("/admin/")
    request.user = head_teacher
    request.session = client.session
    request._messages = _SilentMessages()

    TermAdmin(Term, site).unpublish_results(
        request, Term.objects.filter(pk=hodan.term.pk)
    )

    entry = AuditLog.objects.get(action=AuditLog.Action.TERM_UNPUBLISHED)
    assert entry.actor == head_teacher


class _SilentMessages:
    """Swallows messages, which need a full request cycle to store."""

    def add(self, level, message, extra_tags=""):
        pass


# ------------------------------------------------------ marking progress


def test_marking_progress_counts_what_is_still_missing(head_teacher, hodan):
    """An administrator's real question before publishing is whether the
    term is finished. A missing Score row and a Score with no marks both
    mean 'not marked', and only one of them exists as a row."""
    from schools.publishing import marking_progress

    hodan.add_student("Nasra", "Farah", marks=20)
    hodan.add_student("Liban", "Adan")  # no mark recorded at all

    progress = marking_progress(hodan.term)

    assert progress["expected"] == 3
    assert progress["marked"] == 2
    assert progress["missing"] == 1


# ---------------------------------------------------------- demo mode


def test_the_public_demo_cannot_publish(settings, client, head_teacher, hodan):
    """Publishing is a write like any other, so the demo guard covers it
    without needing to know this screen exists."""
    settings.DEMO_MODE = True
    client.login(username=head_teacher.username, password=PASSWORD)

    client.post(reverse(PAGE), {"action": "publish", "term": hodan.term.id})

    hodan.term.refresh_from_db()
    assert not hodan.term.is_published
