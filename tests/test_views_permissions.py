"""Permission tests for the web pages.

These are the most important tests in the project. Every other test
checks that GradeVault does what it should; these check that it refuses
what it must. A results system that computes perfectly but shows one
student another student's marks has failed completely.
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


@pytest.fixture
def school(db):
    school = Institution.objects.create(name="Hodan Secondary", short_name="HSS")
    scale = GradingScale.objects.create(
        institution=school, name="Standard", is_default=True
    )
    for letter, low, high in [("A", 95, 100), ("D", 50, 94.99), ("F", 0, 49.99)]:
        GradeBand.objects.create(
            scale=scale,
            letter=letter,
            min_percentage=Decimal(str(low)),
            max_percentage=Decimal(str(high)),
        )
    return school


@pytest.fixture
def year(school):
    return AcademicYear.objects.create(
        institution=school,
        name="2026/2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=True,
    )


@pytest.fixture
def term_one(year):
    return Term.objects.create(
        academic_year=year,
        name="Term 1",
        sequence=1,
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 15),
    )


@pytest.fixture
def form_2a(year):
    return ClassRoom.objects.create(academic_year=year, name="Form 2A")


@pytest.fixture
def form_2b(year):
    return ClassRoom.objects.create(academic_year=year, name="Form 2B")


@pytest.fixture
def maths(school):
    return Subject.objects.create(institution=school, name="Mathematics")


@pytest.fixture
def biology(school):
    return Subject.objects.create(institution=school, name="Biology")


def make_teacher(school, username):
    user = User.objects.create_user(
        username=username,
        password=PASSWORD,
        role=User.Role.TEACHER,
        first_name="Fatima",
        last_name="Omar",
    )
    return TeacherProfile.objects.create(user=user, institution=school)


def make_student(school, classroom, first, last):
    user = User.objects.create_user(
        username=generate_student_username(2026),
        password=PASSWORD,
        role=User.Role.STUDENT,
        first_name=first,
        last_name=last,
    )
    student = StudentProfile.objects.create(
        user=user,
        institution=school,
        admission_number=f"ADM-{StudentProfile.objects.count() + 1:03d}",
    )
    return Enrollment.objects.create(student=student, classroom=classroom)


@pytest.fixture
def maths_teacher(school, form_2a, maths):
    teacher = make_teacher(school, "tch-maths")
    TeachingAssignment.objects.create(teacher=teacher, subject=maths, classroom=form_2a)
    return teacher


@pytest.fixture
def assessment(term_one, maths, form_2a):
    return Assessment.objects.create(
        term=term_one,
        subject=maths,
        classroom=form_2a,
        name="Mid-term",
        max_marks=Decimal("40"),
    )


# ---------- anonymous visitors ----------


@pytest.mark.parametrize("url_name", ["dashboard", "teacher_home", "student_results"])
def test_pages_are_closed_to_anonymous_visitors(client, db, url_name):
    response = client.get(reverse(url_name))

    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_a_mark_sheet_is_closed_to_anonymous_visitors(client, form_2a, maths, term_one):
    url = reverse("mark_sheet", args=[form_2a.id, maths.id, term_one.id])

    response = client.get(url)

    assert response.status_code == 302
    assert "/login/" in response["Location"]


# ---------- role separation ----------


@pytest.mark.permissions
def test_a_student_cannot_open_a_teacher_page(client, school, form_2a):
    make_student(school, form_2a, "Amina", "Hassan")
    client.login(username="STU-2026-0001", password=PASSWORD)

    response = client.get(reverse("teacher_home"))

    assert response.status_code == 403


@pytest.mark.permissions
def test_a_teacher_cannot_open_the_student_results_page(client, maths_teacher):
    client.login(username="tch-maths", password=PASSWORD)

    response = client.get(reverse("student_results"))

    assert response.status_code == 403


@pytest.mark.permissions
def test_a_student_cannot_open_a_mark_sheet(client, school, form_2a, maths, term_one):
    """The page that changes grades must be closed to the people graded."""
    make_student(school, form_2a, "Amina", "Hassan")
    client.login(username="STU-2026-0001", password=PASSWORD)

    response = client.get(
        reverse("mark_sheet", args=[form_2a.id, maths.id, term_one.id])
    )

    assert response.status_code == 403


# ---------- a teacher's reach stops at their own subjects ----------


@pytest.mark.permissions
def test_a_teacher_can_open_their_own_mark_sheet(
    client, maths_teacher, form_2a, maths, term_one, assessment
):
    client.login(username="tch-maths", password=PASSWORD)

    response = client.get(
        reverse("mark_sheet", args=[form_2a.id, maths.id, term_one.id])
    )

    assert response.status_code == 200


@pytest.mark.permissions
def test_a_teacher_cannot_open_a_subject_they_do_not_teach(
    client, maths_teacher, form_2a, biology, term_one
):
    """Teaching maths grants nothing over biology."""
    client.login(username="tch-maths", password=PASSWORD)

    response = client.get(
        reverse("mark_sheet", args=[form_2a.id, biology.id, term_one.id])
    )

    assert response.status_code == 403


@pytest.mark.permissions
def test_a_teacher_cannot_open_their_subject_in_another_class(
    client, maths_teacher, form_2b, maths, term_one
):
    """Teaching maths to Form 2A grants nothing over Form 2B."""
    client.login(username="tch-maths", password=PASSWORD)

    response = client.get(
        reverse("mark_sheet", args=[form_2b.id, maths.id, term_one.id])
    )

    assert response.status_code == 403


@pytest.mark.permissions
def test_a_teacher_cannot_post_marks_to_a_class_they_do_not_teach(
    client, maths_teacher, school, form_2b, maths, term_one
):
    """Refusing the GET is not enough if the POST still writes."""
    enrollment = make_student(school, form_2b, "Amina", "Hassan")
    other = Assessment.objects.create(
        term=term_one,
        subject=maths,
        classroom=form_2b,
        name="Mid-term",
        max_marks=Decimal("40"),
    )
    client.login(username="tch-maths", password=PASSWORD)

    response = client.post(
        reverse("mark_sheet", args=[form_2b.id, maths.id, term_one.id]),
        {f"m-{enrollment.id}-{other.id}": "40"},
    )

    assert response.status_code == 403
    assert not Score.objects.filter(enrollment=enrollment).exists()


@pytest.mark.permissions
def test_a_teacher_cannot_mark_a_student_from_another_class(
    client, maths_teacher, school, form_2a, form_2b, maths, term_one, assessment
):
    """A forged field naming an outside student must be ignored, not obeyed.

    The form is rendered with this teacher's own class, so a submission
    naming somebody else's student was constructed by hand.
    """
    outsider = make_student(school, form_2b, "Yusuf", "Ali")
    client.login(username="tch-maths", password=PASSWORD)

    client.post(
        reverse("mark_sheet", args=[form_2a.id, maths.id, term_one.id]),
        {f"m-{outsider.id}-{assessment.id}": "40"},
    )

    assert not Score.objects.filter(enrollment=outsider).exists()


@pytest.mark.permissions
def test_a_teacher_cannot_see_the_ranking_of_a_class_they_do_not_teach(
    client, maths_teacher, form_2b, term_one
):
    client.login(username="tch-maths", password=PASSWORD)

    response = client.get(reverse("class_ranking", args=[form_2b.id, term_one.id]))

    assert response.status_code == 403


# ---------- a student sees their own results and no one else's ----------


@pytest.mark.permissions
def test_a_student_sees_only_their_own_marks(
    client, school, form_2a, maths, term_one, assessment
):
    """The decisive test: one student's page must not contain another's."""
    mine = make_student(school, form_2a, "Amina", "Hassan")
    theirs = make_student(school, form_2a, "Yusuf", "Ali")

    Score.objects.create(enrollment=mine, assessment=assessment, marks=Decimal("21"))
    Score.objects.create(enrollment=theirs, assessment=assessment, marks=Decimal("39"))
    term_one.publish(released_by=None)

    client.login(username=mine.student.user.username, password=PASSWORD)
    body = client.get(reverse("student_results")).content.decode()

    assert "Amina Hassan" in body
    assert "Yusuf Ali" not in body
    assert "39" not in body


@pytest.mark.permissions
def test_there_is_no_way_to_ask_for_another_students_results(client):
    """The URL takes no student id, so there is nothing to tamper with.

    A page that accepts an identifier invites the mistake of trusting it,
    and that single mistake leaks every student at once.
    """
    from django.urls import get_resolver

    pattern = next(
        p
        for p in get_resolver().url_patterns
        if getattr(p, "name", "") == "student_results"
    )

    assert pattern.pattern.regex.groups == 0


# ---------- unpublished results stay hidden ----------


@pytest.mark.permissions
def test_a_student_cannot_see_an_unpublished_term(
    client, school, form_2a, term_one, assessment
):
    """Marks exist, but the term is not released, so nothing is shown."""
    mine = make_student(school, form_2a, "Amina", "Hassan")
    Score.objects.create(enrollment=mine, assessment=assessment, marks=Decimal("38"))

    assert term_one.is_published is False

    client.login(username=mine.student.user.username, password=PASSWORD)
    body = client.get(reverse("student_results")).content.decode()

    assert "38" not in body
    assert "No results yet" in body


def test_results_appear_once_the_term_is_published(
    client, school, form_2a, term_one, assessment
):
    mine = make_student(school, form_2a, "Amina", "Hassan")
    Score.objects.create(enrollment=mine, assessment=assessment, marks=Decimal("38"))

    term_one.publish(released_by=None)

    client.login(username=mine.student.user.username, password=PASSWORD)
    body = client.get(reverse("student_results")).content.decode()

    assert "38" in body
    assert "95.00" in body  # 38 out of 40


# ---------- marks entered through the page are audited ----------


def test_marks_entered_by_a_teacher_are_recorded_against_them(
    client, maths_teacher, school, form_2a, maths, term_one, assessment
):
    from audit.models import AuditLog

    enrollment = make_student(school, form_2a, "Amina", "Hassan")
    client.login(username="tch-maths", password=PASSWORD)

    client.post(
        reverse("mark_sheet", args=[form_2a.id, maths.id, term_one.id]),
        {f"m-{enrollment.id}-{assessment.id}": "32"},
    )

    score = Score.objects.get(enrollment=enrollment, assessment=assessment)
    assert score.marks == Decimal("32")
    assert score.recorded_by == maths_teacher.user

    entry = AuditLog.objects.get()
    assert entry.actor == maths_teacher.user
    assert entry.new_value == "32.00"


def test_a_mark_above_the_maximum_is_refused_by_the_page(
    client, maths_teacher, school, form_2a, maths, term_one, assessment
):
    """45 out of 40 must be rejected with a message, not saved."""
    enrollment = make_student(school, form_2a, "Amina", "Hassan")
    client.login(username="tch-maths", password=PASSWORD)

    response = client.post(
        reverse("mark_sheet", args=[form_2a.id, maths.id, term_one.id]),
        {f"m-{enrollment.id}-{assessment.id}": "45"},
        follow=True,
    )

    assert not Score.objects.filter(enrollment=enrollment, marks__isnull=False).exists()
    assert "outside 0 to 40" in response.content.decode()
