"""Tests that one school cannot reach another school's data.

GradeVault is meant to serve many Somali schools from one deployment.
That makes isolation a correctness requirement, not a feature: a single
unscoped query would expose one school's students to another, and it
would do so quietly.

Every test here plays the attacker. They pass only when GradeVault
refuses.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.admin.sites import site
from django.test import RequestFactory
from django.urls import reverse

from accounts.models import (
    StudentProfile,
    TeacherProfile,
    User,
    generate_student_username,
)
from audit.models import AuditLog
from schools.models import (
    AcademicYear,
    Assessment,
    ClassRoom,
    Enrollment,
    GradingScale,
    Institution,
    Score,
    Subject,
    TeachingAssignment,
    Term,
)

PASSWORD = "test-password-123"


class SchoolFixture:
    """One complete, self-contained school."""

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
        self.subject = Subject.objects.create(
            institution=self.institution, name="Mathematics"
        )
        self.scale = GradingScale.objects.create(
            institution=self.institution, name="Scale", is_default=True
        )
        self.assessment = Assessment.objects.create(
            term=self.term,
            subject=self.subject,
            classroom=self.classroom,
            name="Mid-term",
            max_marks=Decimal("40"),
        )

    def add_admin(self, username):
        user = User.objects.create_user(
            username=username,
            password=PASSWORD,
            role=User.Role.ADMIN,
            institution=self.institution,
            is_staff=True,
        )
        user.user_permissions.set([])
        return user

    def add_teacher(self, username):
        user = User.objects.create_user(
            username=username,
            password=PASSWORD,
            role=User.Role.TEACHER,
            institution=self.institution,
        )
        teacher = TeacherProfile.objects.create(user=user, institution=self.institution)
        TeachingAssignment.objects.create(
            teacher=teacher, subject=self.subject, classroom=self.classroom
        )
        return teacher

    def add_student(self, first, last, marks=None):
        user = User.objects.create_user(
            username=generate_student_username(2026),
            password=PASSWORD,
            role=User.Role.STUDENT,
            institution=self.institution,
            first_name=first,
            last_name=last,
        )
        student = StudentProfile.objects.create(
            user=user,
            institution=self.institution,
            admission_number=f"ADM-{StudentProfile.objects.count() + 1:03d}",
        )
        enrollment = Enrollment.objects.create(
            student=student, classroom=self.classroom
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
    return SchoolFixture("Hodan Secondary School", "HSS")


@pytest.fixture
def banadir(db):
    return SchoolFixture("Banadir Secondary School", "BSS")


def admin_queryset(model, user):
    """What this user would see in the admin list for a model."""
    request = RequestFactory().get("/admin/")
    request.user = user
    return site._registry[model].get_queryset(request)


# ---------- the admin shows one school only ----------


@pytest.mark.permissions
@pytest.mark.parametrize(
    "model",
    [Institution, AcademicYear, Term, ClassRoom, Subject, GradingScale],
)
def test_an_administrator_sees_only_their_own_school(hodan, banadir, model):
    theirs = hodan.add_admin("hodan-admin")

    visible = admin_queryset(model, theirs)

    assert visible.count() == 1, f"{model.__name__} leaked another school"


@pytest.mark.permissions
def test_an_administrator_sees_only_their_own_students(hodan, banadir):
    hodan.add_student("Amina", "Hassan")
    banadir.add_student("Yusuf", "Ali")
    theirs = hodan.add_admin("hodan-admin")

    names = [s.full_name for s in admin_queryset(StudentProfile, theirs)]

    assert names == ["Amina Hassan"]


@pytest.mark.permissions
def test_an_administrator_sees_only_their_own_scores(hodan, banadir):
    hodan.add_student("Amina", "Hassan", marks="31")
    banadir.add_student("Yusuf", "Ali", marks="39")
    theirs = hodan.add_admin("hodan-admin")

    marks = [s.marks for s in admin_queryset(Score, theirs)]

    assert marks == [Decimal("31.00")]


@pytest.mark.permissions
def test_an_administrator_sees_only_their_own_audit_trail(hodan, banadir):
    hodan.add_student("Amina", "Hassan", marks="31")
    banadir.add_student("Yusuf", "Ali", marks="39")
    theirs = hodan.add_admin("hodan-admin")

    entries = admin_queryset(AuditLog, theirs)

    assert entries.count() == 1
    assert "Amina Hassan" in entries.first().student_label


@pytest.mark.permissions
def test_an_administrator_sees_only_their_own_user_accounts(hodan, banadir):
    banadir.add_teacher("banadir-teacher")
    theirs = hodan.add_admin("hodan-admin")

    usernames = set(admin_queryset(User, theirs).values_list("username", flat=True))

    assert "banadir-teacher" not in usernames
    assert "hodan-admin" in usernames


# ---------- failing closed ----------


@pytest.mark.permissions
def test_an_account_with_no_school_sees_nothing(hodan, banadir):
    """A missing institution must mean nothing, never everything."""
    stray = User.objects.create_user(
        username="unassigned",
        password=PASSWORD,
        role=User.Role.ADMIN,
        is_staff=True,
    )

    assert admin_queryset(StudentProfile, stray).count() == 0
    assert admin_queryset(Institution, stray).count() == 0
    assert admin_queryset(Score, stray).count() == 0


@pytest.mark.permissions
def test_the_service_operator_still_sees_every_school(hodan, banadir):
    """A superuser runs the deployment and legitimately sees all of it."""
    operator = User.objects.create_superuser(username="operator", password=PASSWORD)

    assert admin_queryset(Institution, operator).count() == 2


# ---------- dropdowns are filtered too ----------


@pytest.mark.permissions
def test_dropdowns_do_not_offer_another_schools_records(hodan, banadir):
    """Filtering the list but not the pickers would still leak names, and
    let one school attach its records to another's classes."""
    from schools.admin import AssessmentAdmin

    theirs = hodan.add_admin("hodan-admin")
    request = RequestFactory().get("/admin/")
    request.user = theirs

    model_admin = AssessmentAdmin(Assessment, site)
    field = Assessment._meta.get_field("classroom")
    formfield = model_admin.formfield_for_foreignkey(field, request)

    assert list(formfield.queryset) == [hodan.classroom]


# ---------- teachers and students cannot cross schools ----------


@pytest.mark.permissions
def test_a_teacher_cannot_mark_another_schools_class(client, hodan, banadir):
    """The mark sheet is reached by id, so ids from another school must
    be refused rather than merely absent from the menu."""
    hodan.add_teacher("hodan-teacher")
    client.login(username="hodan-teacher", password=PASSWORD)

    response = client.get(
        reverse(
            "mark_sheet",
            args=[banadir.classroom.id, banadir.subject.id, banadir.term.id],
        )
    )

    assert response.status_code == 403


@pytest.mark.permissions
def test_a_teacher_cannot_see_another_schools_ranking(client, hodan, banadir):
    hodan.add_teacher("hodan-teacher")
    client.login(username="hodan-teacher", password=PASSWORD)

    response = client.get(
        reverse("class_ranking", args=[banadir.classroom.id, banadir.term.id])
    )

    assert response.status_code == 403


@pytest.mark.permissions
def test_a_teacher_cannot_post_marks_into_another_school(client, hodan, banadir):
    """Blocking the page is not enough if the submission still writes."""
    hodan.add_teacher("hodan-teacher")
    victim = banadir.add_student("Yusuf", "Ali")
    client.login(username="hodan-teacher", password=PASSWORD)

    client.post(
        reverse(
            "mark_sheet",
            args=[banadir.classroom.id, banadir.subject.id, banadir.term.id],
        ),
        {f"m-{victim.id}-{banadir.assessment.id}": "40"},
    )

    assert not Score.objects.filter(enrollment=victim).exists()


@pytest.mark.permissions
def test_a_student_never_sees_another_schools_results(client, hodan, banadir):
    mine = hodan.add_student("Amina", "Hassan", marks="21")
    banadir.add_student("Yusuf", "Ali", marks="39")
    hodan.term.publish(released_by=None)
    banadir.term.publish(released_by=None)

    client.login(username=mine.student.user.username, password=PASSWORD)
    body = client.get(reverse("student_results")).content.decode()

    assert "Amina Hassan" in body
    assert "Yusuf Ali" not in body
    assert "Banadir" not in body


@pytest.mark.permissions
def test_a_class_ranking_never_counts_another_schools_students(hodan, banadir):
    """Both schools name their class Form 2A. Ranking must not merge them."""
    from schools.results import class_results

    hodan.add_student("Amina", "Hassan", marks="21")
    banadir.add_student("Yusuf", "Ali", marks="39")
    banadir.add_student("Sagal", "Omar", marks="35")

    results = class_results(hodan.classroom, hodan.term)

    assert [r.student_name for r in results] == ["Amina Hassan"]
    assert results[0].class_size == 1
