"""Tests for the role dashboards.

A dashboard summarises data, which means it queries widely — counts,
recent activity, other people's marks to work out a position. That makes
it the most likely place for one school's figures to appear on another
school's screen.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    StudentProfile,
    TeacherProfile,
    User,
    generate_student_username,
)
from schools.dashboards import current_term
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
    """A school whose term contains today, so it is the current one."""

    def __init__(self, name, short):
        today = timezone.localdate()
        self.institution = Institution.objects.create(name=name, short_name=short)
        self.year = AcademicYear.objects.create(
            institution=self.institution,
            name="2026/2027",
            start_date=today - timedelta(days=60),
            end_date=today + timedelta(days=120),
            is_current=True,
        )
        self.term = Term.objects.create(
            academic_year=self.year,
            name="Term 1",
            sequence=1,
            start_date=today - timedelta(days=60),
            end_date=today + timedelta(days=30),
        )
        self.later = Term.objects.create(
            academic_year=self.year,
            name="Term 2",
            sequence=2,
            start_date=today + timedelta(days=31),
            end_date=today + timedelta(days=120),
        )
        self.classroom = ClassRoom.objects.create(
            academic_year=self.year, name="Form 2A"
        )
        self.subject = Subject.objects.create(
            institution=self.institution, name="Mathematics"
        )
        self.scale = GradingScale.objects.create(
            institution=self.institution, name="Scale", is_default=True
        )
        for letter, low, high in [("A", 80, 100), ("D", 50, 79.99), ("F", 0, 49.99)]:
            GradeBand.objects.create(
                scale=self.scale,
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

    def admin(self, username):
        return User.objects.create_user(
            username=username,
            password=PASSWORD,
            role=User.Role.ADMIN,
            institution=self.institution,
            is_staff=True,
        )

    def teacher(self, username):
        user = User.objects.create_user(
            username=username,
            password=PASSWORD,
            role=User.Role.TEACHER,
            institution=self.institution,
            first_name="Fatima",
        )
        profile = TeacherProfile.objects.create(user=user, institution=self.institution)
        TeachingAssignment.objects.create(
            teacher=profile, subject=self.subject, classroom=self.classroom
        )
        return profile

    def student(self, first, last, marks=None):
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
            student=profile, classroom=self.classroom
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


# ---------- which term is "now" ----------


def test_the_current_term_is_the_one_today_falls_inside(hodan):
    """A dashboard fixed to the first term would be wrong most of the year."""
    assert current_term(hodan.year) == hodan.term


def test_the_last_started_term_is_used_between_terms(hodan):
    """Between terms, the one just finished is more useful than the next."""
    today = timezone.localdate()
    hodan.term.start_date = today - timedelta(days=200)
    hodan.term.end_date = today - timedelta(days=100)
    hodan.term.save()
    hodan.later.start_date = today + timedelta(days=30)
    hodan.later.end_date = today + timedelta(days=90)
    hodan.later.save()

    assert current_term(hodan.year) == hodan.term


def test_a_year_with_no_terms_has_no_current_term(db):
    school = Institution.objects.create(name="Empty", short_name="E")
    year = AcademicYear.objects.create(
        institution=school,
        name="2026/2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
    )

    assert current_term(year) is None


# ---------- student ----------


def test_a_student_sees_their_own_summary(client, hodan):
    mine = hodan.student("Amina", "Hassan", marks="34")
    hodan.term.publish(released_by=None)

    client.login(username=mine.student.user.username, password=PASSWORD)
    body = client.get(reverse("dashboard")).content.decode()

    assert "Amina" in body
    assert "85.00%" in body  # 34 out of 40


@pytest.mark.permissions
def test_a_students_dashboard_never_names_a_classmate(client, hodan):
    """Working out a position requires reading the whole class. None of
    that may reach the page."""
    mine = hodan.student("Amina", "Hassan", marks="20")
    hodan.student("Yusuf", "Ali", marks="39")
    hodan.term.publish(released_by=None)

    client.login(username=mine.student.user.username, password=PASSWORD)
    body = client.get(reverse("dashboard")).content.decode()

    assert "Yusuf" not in body
    assert "39" not in body
    assert "of 2 in class" in body  # the position is shown, the rival is not


@pytest.mark.permissions
def test_an_unpublished_term_shows_no_figures(client, hodan):
    mine = hodan.student("Amina", "Hassan", marks="34")

    client.login(username=mine.student.user.username, password=PASSWORD)
    body = client.get(reverse("dashboard")).content.decode()

    assert "85.00%" not in body
    assert "No results published yet" in body


def test_a_student_with_no_class_is_told_so(client, hodan):
    user = User.objects.create_user(
        username="STU-2026-9999",
        password=PASSWORD,
        role=User.Role.STUDENT,
        institution=hodan.institution,
    )
    StudentProfile.objects.create(
        user=user, institution=hodan.institution, admission_number="ADM-X"
    )

    client.login(username="STU-2026-9999", password=PASSWORD)
    body = client.get(reverse("dashboard")).content.decode()

    assert "not enrolled in a class" in body


# ---------- teacher ----------


def test_a_teacher_sees_what_is_left_to_mark(client, hodan):
    hodan.teacher("tch-one")
    hodan.student("Amina", "Hassan", marks="30")
    hodan.student("Yusuf", "Ali")  # unmarked
    hodan.student("Sagal", "Omar")  # unmarked

    client.login(username="tch-one", password=PASSWORD)
    response = client.get(reverse("dashboard"))
    rows = response.context["rows"]

    assert response.context["outstanding"] == 2
    assert rows[0]["expected"] == 3
    assert rows[0]["marked"] == 1
    assert rows[0]["missing"] == 2


@pytest.mark.permissions
def test_a_teachers_progress_covers_only_their_own_subjects(client, hodan):
    """A second subject they do not teach must not appear."""
    hodan.teacher("tch-one")
    biology = Subject.objects.create(institution=hodan.institution, name="Biology")
    Assessment.objects.create(
        term=hodan.term,
        subject=biology,
        classroom=hodan.classroom,
        name="Mid-term",
        max_marks=Decimal("40"),
    )
    hodan.student("Amina", "Hassan")

    client.login(username="tch-one", password=PASSWORD)
    body = client.get(reverse("dashboard")).content.decode()

    assert "Mathematics" in body
    assert "Biology" not in body


# ---------- administrator ----------


@pytest.mark.permissions
def test_an_administrator_counts_only_their_own_school(client, hodan, banadir):
    hodan.student("Amina", "Hassan")
    banadir.student("Yusuf", "Ali")
    banadir.student("Sagal", "Omar")
    banadir.teacher("banadir-teacher")
    hodan.admin("hodan-admin")

    client.login(username="hodan-admin", password=PASSWORD)
    context = client.get(reverse("dashboard")).context

    assert context["students"] == 1
    assert context["teachers"] == 0
    assert context["classes"] == 1
    assert context["subjects"] == 1


@pytest.mark.permissions
def test_an_administrator_sees_only_their_own_recent_changes(client, hodan, banadir):
    hodan.student("Amina", "Hassan", marks="30")
    banadir.student("Yusuf", "Ali", marks="35")
    hodan.admin("hodan-admin")

    client.login(username="hodan-admin", password=PASSWORD)
    body = client.get(reverse("dashboard")).content.decode()

    assert "Amina Hassan" in body
    assert "Yusuf Ali" not in body


def test_an_administrator_is_warned_about_a_grading_gap(client, hodan):
    """The typo that started this: a scale that leaves students ungraded."""
    hodan.scale.bands.filter(letter="D").update(max_percentage=Decimal("60"))
    hodan.admin("hodan-admin")

    client.login(username="hodan-admin", password=PASSWORD)
    body = client.get(reverse("dashboard")).content.decode()

    assert "receive no grade" in body


@pytest.mark.permissions
def test_an_administrator_without_a_school_sees_nothing(client, hodan):
    User.objects.create_user(
        username="unassigned",
        password=PASSWORD,
        role=User.Role.ADMIN,
        is_staff=True,
    )

    client.login(username="unassigned", password=PASSWORD)
    body = client.get(reverse("dashboard")).content.decode()

    assert "No school assigned" in body
    assert hodan.institution.name not in body


def test_the_operator_sees_every_school(client, hodan, banadir):
    hodan.student("Amina", "Hassan")
    banadir.student("Yusuf", "Ali")
    User.objects.create_superuser(username="operator", password=PASSWORD)

    client.login(username="operator", password=PASSWORD)
    context = client.get(reverse("dashboard")).context

    assert context["operator"] is True
    assert context["students"] == 2
