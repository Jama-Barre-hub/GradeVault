"""Tests for changing and resetting passwords.

Resetting somebody's password is taking control of their account, so the
tests that matter are the ones about who may do it to whom.

**It may only ever point downwards.** An administrator may reset a
teacher or a pupil at their own school. Not another administrator, not a
superuser, and not anybody at another school. Without that rule, an
administrator could take over an account that outranks their own, and
every permission in the project would rest on a door left open.
"""

import pytest
from django.urls import reverse

from accounts.models import User
from audit.models import AuditLog
from factories import PASSWORD

NEW = "a-much-better-passphrase-42"


@pytest.fixture
def head(client, hodan):
    user = hodan.add_admin("hodan-head")
    client.login(username=user.username, password=PASSWORD)
    return user


# ------------------------------------------------- changing your own


def test_anyone_signed_in_can_change_their_own_password(client, hodan):
    teacher = hodan.add_teacher("hodan-tch").user
    client.login(username=teacher.username, password=PASSWORD)

    client.post(
        reverse("change_my_password"),
        {"old_password": PASSWORD, "new_password1": NEW, "new_password2": NEW},
    )

    teacher.refresh_from_db()
    assert teacher.check_password(NEW)


def test_the_current_password_must_be_right(client, hodan):
    """Otherwise anyone who finds an unattended signed-in browser owns
    the account permanently rather than until it logs out."""
    teacher = hodan.add_teacher("hodan-tch").user
    client.login(username=teacher.username, password=PASSWORD)

    client.post(
        reverse("change_my_password"),
        {"old_password": "wrong", "new_password1": NEW, "new_password2": NEW},
    )

    teacher.refresh_from_db()
    assert teacher.check_password(PASSWORD)


def test_a_weak_password_is_refused(client, hodan):
    """Django's configured validators do the judging, including the list
    of common passwords."""
    teacher = hodan.add_teacher("hodan-tch").user
    client.login(username=teacher.username, password=PASSWORD)

    client.post(
        reverse("change_my_password"),
        {
            "old_password": PASSWORD,
            "new_password1": "password",
            "new_password2": "password",
        },
    )

    teacher.refresh_from_db()
    assert teacher.check_password(PASSWORD)


def test_changing_your_password_does_not_sign_you_out(client, hodan):
    """A successful action that ends with a login screen reads as a
    failure."""
    teacher = hodan.add_teacher("hodan-tch").user
    client.login(username=teacher.username, password=PASSWORD)

    client.post(
        reverse("change_my_password"),
        {"old_password": PASSWORD, "new_password1": NEW, "new_password2": NEW},
    )

    assert client.get(reverse("dashboard")).status_code == 200


@pytest.mark.permissions
def test_a_visitor_who_is_not_signed_in_is_sent_to_sign_in(client, hodan):
    response = client.get(reverse("change_my_password"))

    assert response.status_code == 302
    assert reverse("login") in response.url


# ------------------------------------------------ resetting somebody else's


def test_an_administrator_can_reset_a_pupils_password(client, head, hodan):
    pupil = hodan.add_student("Amina", "Yusuf").student.user
    old_hash = pupil.password

    client.post(reverse("reset_password", args=[pupil.id]))

    pupil.refresh_from_db()
    assert pupil.password != old_hash
    assert pupil.has_usable_password()


def test_an_administrator_can_reset_a_teachers_password(client, head, hodan):
    teacher = hodan.add_teacher("hodan-tch").user
    old_hash = teacher.password

    client.post(reverse("reset_password", args=[teacher.id]))

    teacher.refresh_from_db()
    assert teacher.password != old_hash


def test_the_new_password_is_shown_once(client, head, hodan):
    pupil = hodan.add_student("Amina", "Yusuf").student.user

    response = client.post(reverse("reset_password", args=[pupil.id]), follow=True)

    assert "write this down now" in response.content.decode()


def test_a_reset_is_written_to_the_audit_trail(client, head, hodan):
    """Taking control of an account is exactly what a school may later
    need to account for."""
    pupil = hodan.add_student("Amina", "Yusuf").student.user

    client.post(reverse("reset_password", args=[pupil.id]))

    entry = AuditLog.objects.get(action=AuditLog.Action.PASSWORD_RESET)
    assert entry.actor == head
    assert pupil.username in entry.student_label
    assert entry.institution == hodan.institution


def test_the_audit_entry_does_not_record_the_new_password(client, head, hodan):
    """A log that stored the password would be a list of live credentials
    that nothing in the system is allowed to delete — the append-only
    rule would make it impossible to clean up afterwards."""
    import re

    pupil = hodan.add_student("Amina", "Yusuf").student.user

    response = client.post(reverse("reset_password", args=[pupil.id]), follow=True)

    # Recover the password the screen actually displayed, so the check
    # below is against the real value rather than a guess at its shape.
    shown = re.search(r"\): ([A-Za-z0-9]{10}) —", response.content.decode())
    assert shown, "the reset page should display a password"
    password = shown.group(1)

    entry = AuditLog.objects.get(action=AuditLog.Action.PASSWORD_RESET)
    row = " ".join(
        [
            entry.actor_label,
            entry.student_label,
            entry.old_value,
            entry.new_value,
            entry.term_label,
            entry.subject_label,
            entry.assessment_label,
            entry.classroom_label,
        ]
    )

    assert password not in row


# ------------------------------------------------------ pointing downwards


@pytest.mark.permissions
def test_an_administrator_cannot_reset_another_administrator(client, head, hodan):
    """The attack this view exists to refuse. An administrator who could
    reset a colleague administrator could take over an account equal to
    their own, and then the school has two of whoever got there first."""
    colleague = hodan.add_admin("hodan-deputy")
    old_hash = colleague.password

    response = client.post(reverse("reset_password", args=[colleague.id]))

    colleague.refresh_from_db()
    assert response.status_code == 404
    assert colleague.password == old_hash


@pytest.mark.permissions
def test_an_administrator_cannot_reset_a_superuser(client, head, hodan):
    """A superuser operates the whole deployment. Resetting one would
    hand a single school control of every school."""
    operator = User.objects.create_superuser(username="operator", password=PASSWORD)
    old_hash = operator.password

    response = client.post(reverse("reset_password", args=[operator.id]))

    operator.refresh_from_db()
    assert response.status_code == 404
    assert operator.password == old_hash


@pytest.mark.permissions
def test_an_administrator_cannot_reset_someone_at_another_school(
    client, head, hodan, banadir
):
    victim = banadir.add_teacher("banadir-tch").user
    old_hash = victim.password

    response = client.post(reverse("reset_password", args=[victim.id]))

    victim.refresh_from_db()
    assert response.status_code == 404
    assert victim.password == old_hash


@pytest.mark.permissions
def test_a_teacher_cannot_reset_anybody(client, hodan):
    teacher = hodan.add_teacher("hodan-tch").user
    pupil = hodan.add_student("Amina", "Yusuf").student.user
    old_hash = pupil.password
    client.login(username=teacher.username, password=PASSWORD)

    response = client.post(reverse("reset_password", args=[pupil.id]))

    pupil.refresh_from_db()
    assert response.status_code == 403
    assert pupil.password == old_hash


@pytest.mark.permissions
def test_a_student_cannot_reset_anybody(client, hodan):
    first = hodan.add_student("Amina", "Yusuf").student.user
    second = hodan.add_student("Liban", "Adan").student.user
    old_hash = second.password
    client.login(username=first.username, password=PASSWORD)

    response = client.post(reverse("reset_password", args=[second.id]))

    second.refresh_from_db()
    assert response.status_code == 403
    assert second.password == old_hash


# ---------------------------------------------------------------- shape


def test_a_reset_needs_a_post_not_a_get(client, head, hodan):
    """A GET shows the confirmation page and changes nothing, so a link
    followed by accident cannot lock a child out of their results."""
    pupil = hodan.add_student("Amina", "Yusuf").student.user
    old_hash = pupil.password

    response = client.get(reverse("reset_password", args=[pupil.id]))

    pupil.refresh_from_db()
    assert response.status_code == 200
    assert pupil.password == old_hash


def test_the_public_demo_cannot_reset_a_password(settings, client, head, hodan):
    settings.DEMO_MODE = True
    pupil = hodan.add_student("Amina", "Yusuf").student.user
    old_hash = pupil.password

    client.post(reverse("reset_password", args=[pupil.id]))

    pupil.refresh_from_db()
    assert pupil.password == old_hash
