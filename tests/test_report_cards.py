"""Tests for report cards.

A report card is the most sensitive page in GradeVault: it names one
student and shows their whole term. These tests are mostly about who
cannot open one.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import (
    StudentProfile,
    TeacherProfile,
    User,
    generate_student_username,
)
from schools.models import (
    AcademicYear,
    Assessment,
    ClassRoom,
    Enrollment,
    GradeBand,
    GradingScale,
    Institution,
    Score,
    Subject,
    TeachingAssignment,
    Term,
)

PASSWORD = "test-password-123"


class School:
    def __init__(self, name, short):
        self.institution = Institution.objects.create(name=name, short_name=short)
        self.year = AcademicYear.objects.create(
            institution=self.institution,
            name="2026/2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            is_current=True,
        )
        self.term = Term.objects.create(
            academic_year=self.year,
            name="Term 1",
            sequence=1,
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 15),
        )
        self.classroom = ClassRoom.objects.create(
            academic_year=self.year, name="Form 2A"
        )
        self.other_class = ClassRoom.objects.create(
            academic_year=self.year, name="Form 2B"
        )
        self.subject = Subject.objects.create(
            institution=self.institution, name="Mathematics"
        )
        scale = GradingScale.objects.create(
            institution=self.institution, name="Scale", is_default=True
        )
        for letter, low, high in [("A", 80, 100), ("D", 50, 79.99), ("F", 0, 49.99)]:
            GradeBand.objects.create(
                scale=scale,
                letter=letter,
                min_percentage=Decimal(str(low)),
                max_percentage=Decimal(str(high)),
            )
        self.assessment = Assessment.objects.create(
            term=self.term,
            subject=self.subject,
            classroom=self.classroom,
            name="Mid-term",
            max_marks=Decimal("40"),
        )

    def teacher(self, username, classroom=None):
        user = User.objects.create_user(
            username=username,
            password=PASSWORD,
            role=User.Role.TEACHER,
            institution=self.institution,
        )
        profile = TeacherProfile.objects.create(user=user, institution=self.institution)
        TeachingAssignment.objects.create(
            teacher=profile,
            subject=self.subject,
            classroom=classroom or self.classroom,
        )
        return profile

    def student(self, first, last, marks=None, classroom=None):
        user = User.objects.create_user(
            username=generate_student_username(2026),
            password=PASSWORD,
            role=User.Role.STUDENT,
            institution=self.institution,
            first_name=first,
            last_name=last,
        )
        profile = StudentProfile.objects.create(
            user=user,
            institution=self.institution,
            admission_number=f"ADM-{StudentProfile.objects.count() + 1:03d}",
        )
        enrollment = Enrollment.objects.create(
            student=profile, classroom=classroom or self.classroom
        )
        if marks is not None:
            Score.objects.create(
                enrollment=enrollment,
                assessment=self.assessment,
                marks=Decimal(marks),
            )
        return enrollment


@pytest.fixture
def hodan(db):
    return School("Hodan Secondary School", "HSS")


@pytest.fixture
def banadir(db):
    return School("Banadir Secondary School", "BSS")


# ---------- a student's own card ----------


def test_a_student_can_open_their_own_card(client, hodan):
    mine = hodan.student("Amina", "Hassan", marks="34")
    hodan.term.publish(released_by=None)

    client.login(username=mine.student.user.username, password=PASSWORD)
    response = client.get(reverse("my_report_card", args=[hodan.term.id]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Amina Hassan" in body
    assert "Hodan Secondary School" in body
    assert "85.00" in body  # 34 of 40


@pytest.mark.permissions
def test_the_card_url_carries_no_student_identifier():
    """Only the term is in the path. There is nothing to tamper with."""
    from django.urls import get_resolver

    pattern = next(
        p
        for p in get_resolver().url_patterns
        if getattr(p, "name", "") == "my_report_card"
    )

    assert list(pattern.pattern.regex.groupindex) == ["term_id"]


@pytest.mark.permissions
def test_a_student_cannot_open_an_unpublished_card(client, hodan):
    mine = hodan.student("Amina", "Hassan", marks="34")

    client.login(username=mine.student.user.username, password=PASSWORD)
    response = client.get(reverse("my_report_card", args=[hodan.term.id]))

    assert response.status_code == 403
    assert "85.00" not in response.content.decode()


@pytest.mark.permissions
def test_a_student_cannot_open_another_schools_term(client, hodan, banadir):
    """A term id from elsewhere must not resolve into a card."""
    mine = hodan.student("Amina", "Hassan", marks="34")
    banadir.term.publish(released_by=None)

    client.login(username=mine.student.user.username, password=PASSWORD)
    response = client.get(reverse("my_report_card", args=[banadir.term.id]))

    assert response.status_code == 404


@pytest.mark.permissions
def test_a_students_card_names_nobody_else(client, hodan):
    mine = hodan.student("Amina", "Hassan", marks="20")
    hodan.student("Yusuf", "Ali", marks="39")
    hodan.term.publish(released_by=None)

    client.login(username=mine.student.user.username, password=PASSWORD)
    body = client.get(reverse("my_report_card", args=[hodan.term.id])).content.decode()

    assert "Yusuf" not in body
    assert "97.50" not in body  # the classmate's percentage


# ---------- a teacher opening a card ----------


def test_a_teacher_can_open_a_card_for_their_own_class(client, hodan):
    hodan.teacher("tch-one")
    pupil = hodan.student("Amina", "Hassan", marks="34")

    client.login(username="tch-one", password=PASSWORD)
    response = client.get(
        reverse("class_report_card", args=[hodan.classroom.id, hodan.term.id, pupil.id])
    )

    assert response.status_code == 200
    assert "Amina Hassan" in response.content.decode()


def test_staff_may_check_a_card_before_it_is_published(client, hodan):
    """Someone has to read a report before the school releases it."""
    hodan.teacher("tch-one")
    pupil = hodan.student("Amina", "Hassan", marks="34")

    assert hodan.term.is_published is False

    client.login(username="tch-one", password=PASSWORD)
    response = client.get(
        reverse("class_report_card", args=[hodan.classroom.id, hodan.term.id, pupil.id])
    )

    assert response.status_code == 200
    assert "has not been published" in response.content.decode()


@pytest.mark.permissions
def test_a_teacher_cannot_open_a_card_for_a_class_they_do_not_teach(client, hodan):
    hodan.teacher("tch-one")  # teaches Form 2A
    outsider = hodan.student("Yusuf", "Ali", classroom=hodan.other_class, marks="30")

    client.login(username="tch-one", password=PASSWORD)
    response = client.get(
        reverse(
            "class_report_card",
            args=[hodan.other_class.id, hodan.term.id, outsider.id],
        )
    )

    assert response.status_code == 403


@pytest.mark.permissions
def test_an_enrolment_id_from_another_class_is_refused(client, hodan):
    """Naming a class the teacher does teach, but a student from another,
    must not slip through."""
    hodan.teacher("tch-one")
    outsider = hodan.student("Yusuf", "Ali", classroom=hodan.other_class, marks="30")

    client.login(username="tch-one", password=PASSWORD)
    response = client.get(
        reverse(
            "class_report_card",
            args=[hodan.classroom.id, hodan.term.id, outsider.id],
        )
    )

    assert response.status_code == 404


@pytest.mark.permissions
def test_a_teacher_cannot_open_another_schools_card(client, hodan, banadir):
    hodan.teacher("tch-one")
    theirs = banadir.student("Yusuf", "Ali", marks="30")

    client.login(username="tch-one", password=PASSWORD)
    response = client.get(
        reverse(
            "class_report_card",
            args=[banadir.classroom.id, banadir.term.id, theirs.id],
        )
    )

    assert response.status_code == 403


@pytest.mark.permissions
def test_a_student_cannot_use_the_staff_card_url(client, hodan):
    mine = hodan.student("Amina", "Hassan", marks="34")

    client.login(username=mine.student.user.username, password=PASSWORD)
    response = client.get(
        reverse("class_report_card", args=[hodan.classroom.id, hodan.term.id, mine.id])
    )

    assert response.status_code == 403


# ---------- what the card contains ----------


def test_the_card_carries_the_school_and_signature_lines(client, hodan):
    mine = hodan.student("Amina", "Hassan", marks="34")
    hodan.term.publish(released_by=None)

    client.login(username=mine.student.user.username, password=PASSWORD)
    body = client.get(reverse("my_report_card", args=[hodan.term.id])).content.decode()

    for expected in [
        "Hodan Secondary School",
        "Admission number",
        "Position in class",
        "Class teacher",
        "Head teacher",
        "Parent or guardian",
    ]:
        assert expected in body, f"report card is missing {expected}"
