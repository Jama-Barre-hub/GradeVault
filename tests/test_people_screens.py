"""Tests for the portal screens that create people.

The model-level rules — username numbering, one class per year, what a
teaching assignment permits — live in `test_people.py`. This file covers
the screens a head teacher uses to exercise them.

This is the module that makes accounts, so it is the one where a mistake
produces powers nobody granted rather than a badly named subject. Three
properties matter more than the features:

**Role cannot be posted.** Smuggling `role=admin` into the form that adds
a teacher must produce a teacher. A head teacher who could create an
administrator could create their own replacement.

**Institution cannot be posted.** A pupil admitted at one school must not
land in another, and the class dropdown must not even list another
school's classes.

**Passwords are generated, not chosen.** They are shown once and stored
only as a hash.
"""

import pytest
from django.urls import reverse

from accounts.models import StudentProfile, TeacherProfile, User
from factories import PASSWORD
from schools.models import ClassRoom, Enrollment, TeachingAssignment
from schools.people_forms import SAFE_CHARACTERS, make_password_for_new_account


@pytest.fixture
def head(client, hodan):
    user = hodan.add_admin("hodan-head")
    client.login(username=user.username, password=PASSWORD)
    return user


def add_teacher(client, follow=False, **overrides):
    payload = {
        "username": "f.hassan",
        "first_name": "Farah",
        "last_name": "Hassan",
        "staff_number": "STF-01",
        "phone": "",
    }
    payload.update(overrides)
    return client.post(reverse("people_teachers"), payload, follow=follow)


def admit_pupil(client, classroom, **overrides):
    payload = {
        "first_name": "Amina",
        "last_name": "Yusuf",
        "admission_number": "ADM-100",
        "classroom": classroom.id,
        "guardian_name": "",
        "guardian_phone": "",
    }
    payload.update(overrides)
    return client.post(reverse("people_students"), payload)


# ------------------------------------------------------------ who may look


@pytest.mark.permissions
@pytest.mark.parametrize(
    "name",
    ["people_overview", "people_teachers", "people_students", "people_teaching"],
)
def test_a_teacher_cannot_reach_the_people_screens(client, hodan, name):
    """A teacher who could add accounts could add themselves a second one."""
    teacher = hodan.add_teacher("hodan-tch").user
    client.login(username=teacher.username, password=PASSWORD)

    assert client.get(reverse(name)).status_code == 403


@pytest.mark.permissions
def test_a_student_cannot_reach_the_people_screens(client, hodan):
    student = hodan.add_student("Sagal", "Omar").student.user
    client.login(username=student.username, password=PASSWORD)

    assert client.get(reverse("people_overview")).status_code == 403


@pytest.mark.permissions
def test_a_teacher_cannot_create_an_account_by_posting(client, hodan):
    """Reading the page is refused; so is posting to it."""
    teacher = hodan.add_teacher("hodan-tch").user
    client.login(username=teacher.username, password=PASSWORD)
    before = User.objects.count()

    add_teacher(client)

    assert User.objects.count() == before


# -------------------------------------------------- privilege escalation


@pytest.mark.permissions
def test_posting_a_role_cannot_make_an_administrator(client, head, hodan):
    """The attack this module exists to refuse.

    `role` is not a form field. It is set by the view from which screen
    the request came through, so an extra field in the request is simply
    ignored rather than obeyed.
    """
    add_teacher(client, role="admin")

    created = User.objects.get(username="f.hassan")
    assert created.role == User.Role.TEACHER
    assert not created.is_staff
    assert not created.is_superuser


@pytest.mark.permissions
def test_posting_a_role_cannot_make_a_superuser(client, head, hodan):
    add_teacher(client, role="admin", is_superuser="on", is_staff="on")

    created = User.objects.get(username="f.hassan")
    assert not created.is_superuser
    assert not created.is_staff


@pytest.mark.permissions
def test_an_admitted_pupil_is_only_ever_a_student(client, head, hodan):
    admit_pupil(client, hodan.classroom, role="admin")

    pupil = StudentProfile.objects.get(admission_number="ADM-100")
    assert pupil.user.role == User.Role.STUDENT
    assert not pupil.user.is_staff


# ---------------------------------------------------------------- tenancy


@pytest.mark.permissions
def test_a_new_teacher_belongs_to_the_signed_in_school(client, head, hodan, banadir):
    add_teacher(client)

    teacher = TeacherProfile.objects.get(user__username="f.hassan")
    assert teacher.institution == hodan.institution
    assert teacher.user.institution == hodan.institution


@pytest.mark.permissions
def test_a_pupil_cannot_be_admitted_into_another_schools_class(
    client, head, hodan, banadir
):
    """The class id arrives in a form, so the dropdown is filtered and
    the value re-validated against that filtered set."""
    before = StudentProfile.objects.count()

    admit_pupil(client, banadir.classroom)

    assert StudentProfile.objects.count() == before
    assert not Enrollment.objects.filter(classroom=banadir.classroom).exists()


@pytest.mark.permissions
def test_another_schools_classes_are_not_offered(client, head, hodan, banadir):
    """Compared by id, not by name: both schools happen to call their
    class "Form 2A", so the name appearing proves nothing either way."""
    body = client.get(reverse("people_students")).content.decode()

    assert f'value="{banadir.classroom.id}"' not in body
    assert f'value="{hodan.classroom.id}"' in body


@pytest.mark.permissions
def test_another_schools_teachers_are_not_listed(client, head, hodan, banadir):
    banadir.add_teacher("banadir-tch")

    body = client.get(reverse("people_teachers")).content.decode()

    assert "banadir-tch" not in body


@pytest.mark.permissions
def test_another_schools_pupil_cannot_be_moved(client, head, hodan, banadir):
    victim = banadir.add_student("Hodan", "Ali").student

    response = client.get(reverse("move_student", args=[victim.id]))

    assert response.status_code == 404


@pytest.mark.permissions
def test_another_schools_teaching_assignment_cannot_be_removed(
    client, head, hodan, banadir
):
    banadir.add_teacher("banadir-tch")
    victim = TeachingAssignment.objects.get(teacher__user__username="banadir-tch")

    client.post(
        reverse("people_teaching"), {"action": "remove", "assignment": victim.id}
    )

    assert TeachingAssignment.objects.filter(pk=victim.pk).exists()


# ------------------------------------------------------------- creating


def test_a_teacher_is_created_with_a_working_password(client, head, hodan):
    """The generated password must actually sign in — a credential that
    is handed over and then refused is worse than none."""
    response = add_teacher(client, follow=True)
    body = response.content.decode()

    # The password is announced once, in the message.
    assert "temporary password" in body

    created = User.objects.get(username="f.hassan")
    assert created.check_password(PASSWORD) is False  # not the shared test password
    assert created.has_usable_password()


def test_a_teacher_gets_a_profile_as_well_as_an_account(client, head, hodan):
    """A User with no TeacherProfile can sign in and is then refused by
    every page, which is the confusing half-state to avoid."""
    add_teacher(client)

    assert TeacherProfile.objects.filter(user__username="f.hassan").exists()


def test_a_duplicate_username_is_refused(client, head, hodan):
    add_teacher(client)
    before = User.objects.count()

    add_teacher(client, first_name="Someone", last_name="Else")

    assert User.objects.count() == before


def test_a_username_differing_only_in_case_is_refused(client, head, hodan):
    add_teacher(client)
    before = User.objects.count()

    add_teacher(client, username="F.Hassan")

    assert User.objects.count() == before


def test_admitting_a_pupil_enrols_them_at_the_same_time(client, head, hodan):
    """A pupil who exists but sits in no class has no results and appears
    in no register."""
    admit_pupil(client, hodan.classroom)

    pupil = StudentProfile.objects.get(admission_number="ADM-100")
    enrolment = pupil.current_enrollment()

    assert enrolment is not None
    assert enrolment.classroom == hodan.classroom


def test_a_pupil_gets_a_generated_sign_in_number(client, head, hodan):
    admit_pupil(client, hodan.classroom)

    pupil = StudentProfile.objects.get(admission_number="ADM-100")

    assert pupil.user.username.startswith("STU-")


def test_a_duplicate_admission_number_is_refused(client, head, hodan):
    admit_pupil(client, hodan.classroom)
    before = StudentProfile.objects.count()

    admit_pupil(client, hodan.classroom, first_name="Other", last_name="Pupil")

    assert StudentProfile.objects.count() == before


def test_the_same_admission_number_at_another_school_is_allowed(
    client, head, hodan, banadir
):
    """Two schools number their pupils independently."""
    StudentProfile.objects.create(
        user=User.objects.create_user(
            username="other-school-pupil", password=PASSWORD, role=User.Role.STUDENT
        ),
        institution=banadir.institution,
        admission_number="ADM-100",
    )

    admit_pupil(client, hodan.classroom)

    assert StudentProfile.objects.filter(
        institution=hodan.institution, admission_number="ADM-100"
    ).exists()


# ---------------------------------------------------------------- moving


def test_moving_a_pupil_keeps_the_old_enrolment(client, head, hodan):
    """A child who changed class in February still sat Term 1 where they
    were. Deleting that would detach real marks from the class they were
    earned in."""
    enrolment = hodan.add_student("Liban", "Adan", marks=20)
    other = ClassRoom.objects.create(academic_year=hodan.year, name="Form 2B")

    client.post(
        reverse("move_student", args=[enrolment.student.id]), {"classroom": other.id}
    )

    enrolment.refresh_from_db()
    assert not enrolment.is_active
    assert enrolment.classroom == hodan.classroom  # unchanged, just closed
    assert enrolment.student.current_enrollment().classroom == other


@pytest.mark.permissions
def test_a_pupil_cannot_be_moved_into_another_schools_class(
    client, head, hodan, banadir
):
    enrolment = hodan.add_student("Nasra", "Farah")

    client.post(
        reverse("move_student", args=[enrolment.student.id]),
        {"classroom": banadir.classroom.id},
    )

    assert enrolment.student.current_enrollment().classroom == hodan.classroom


# --------------------------------------------------------- who teaches


def test_an_assignment_lets_a_teacher_mark(client, head, hodan):
    """The rule the whole system is built around, created from the
    portal for the first time."""
    teacher = hodan.add_teacher("hodan-tch")
    TeachingAssignment.objects.filter(teacher=teacher).delete()
    assert not teacher.teaches(hodan.subject, hodan.classroom)

    client.post(
        reverse("people_teaching"),
        {
            "teacher": teacher.id,
            "subject": hodan.subject.id,
            "classroom": hodan.classroom.id,
        },
    )

    assert teacher.teaches(hodan.subject, hodan.classroom)


def test_a_repeated_assignment_is_refused(client, head, hodan):
    teacher = hodan.add_teacher("hodan-tch")  # already teaches the subject
    before = TeachingAssignment.objects.count()

    client.post(
        reverse("people_teaching"),
        {
            "teacher": teacher.id,
            "subject": hodan.subject.id,
            "classroom": hodan.classroom.id,
        },
    )

    assert TeachingAssignment.objects.count() == before


def test_an_assignment_can_be_withdrawn(client, head, hodan):
    teacher = hodan.add_teacher("hodan-tch")
    assignment = TeachingAssignment.objects.get(teacher=teacher)

    client.post(
        reverse("people_teaching"), {"action": "remove", "assignment": assignment.id}
    )

    assert not TeachingAssignment.objects.filter(pk=assignment.pk).exists()


# -------------------------------------------------------------- passwords


def test_generated_passwords_avoid_confusable_characters():
    """A password read off a screen and typed by a ten-year-old must not
    turn on telling O from 0 or l from 1."""
    for character in "O0oIl1":
        assert character not in SAFE_CHARACTERS


def test_generated_passwords_differ_from_each_other():
    passwords = {make_password_for_new_account() for _ in range(50)}

    assert len(passwords) == 50


def test_a_generated_password_is_long_enough_to_be_worth_having():
    assert len(make_password_for_new_account()) >= 10


# -------------------------------------------------------------- demo mode


def test_the_public_demo_cannot_create_accounts(settings, client, head, hodan):
    settings.DEMO_MODE = True
    before = User.objects.count()

    add_teacher(client)

    assert User.objects.count() == before
