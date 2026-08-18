"""Tests for the computation engine.

These check arithmetic that decides whether a student passes, repeats a
year, or is told they came first. Every boundary is asserted explicitly.
"""

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import StudentProfile, User, generate_student_username
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
    Term,
)
from schools.results import class_results, round_percentage, term_result

BANDS = [
    ("A", 95, 100),
    ("A-", 90, 94.99),
    ("B+", 85, 89.99),
    ("B", 80, 84.99),
    ("B-", 75, 79.99),
    ("C+", 70, 74.99),
    ("C", 65, 69.99),
    ("C-", 60, 64.99),
    ("D+", 55, 59.99),
    ("D", 50, 54.99),
    ("F", 0, 49.99),
]


@pytest.fixture
def school(db):
    return Institution.objects.create(name="Hodan Secondary School", short_name="HSS")


@pytest.fixture
def scale(school):
    scale = GradingScale.objects.create(
        institution=school, name="HSS Standard", is_default=True
    )
    for letter, low, high in BANDS:
        GradeBand.objects.create(
            scale=scale,
            letter=letter,
            min_percentage=Decimal(str(low)),
            max_percentage=Decimal(str(high)),
        )
    return scale


@pytest.fixture
def year(school):
    return AcademicYear.objects.create(
        institution=school,
        name="2026/2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
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


def make_subject(school, term, classroom, name):
    subject = Subject.objects.create(institution=school, name=name)
    midterm = Assessment.objects.create(
        term=term,
        subject=subject,
        classroom=classroom,
        name="Mid-term",
        max_marks=Decimal("40"),
        sequence=1,
    )
    final = Assessment.objects.create(
        term=term,
        subject=subject,
        classroom=classroom,
        name="Final",
        max_marks=Decimal("60"),
        sequence=2,
    )
    return subject, midterm, final


def enrol(school, classroom, first, last, roll):
    """Enrol a student.

    The admission number counts every student in the school, not the roll
    within a class. Two students in different classes may share roll
    number 1, but an admission number is unique school-wide.
    """
    user = User.objects.create_user(
        username=generate_student_username(2026),
        role=User.Role.STUDENT,
        first_name=first,
        last_name=last,
    )
    student = StudentProfile.objects.create(
        user=user,
        institution=school,
        admission_number=f"ADM-{StudentProfile.objects.count() + 1:03d}",
    )
    return Enrollment.objects.create(
        student=student, classroom=classroom, roll_number=roll
    )


# ---------- rounding ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("82.500", "82.50"), ("82.505", "82.51"), ("82.504", "82.50"), ("0.005", "0.01")],
)
def test_percentages_round_half_up(raw, expected):
    """Banker's rounding would send 82.505 to 82.50, rounding one student
    down and another up for the same fraction."""
    assert round_percentage(Decimal(raw)) == Decimal(expected)


# ---------- one subject ----------


def test_the_worked_example_from_the_proposal(school, term_one, form_2a, scale):
    """32/40 plus 51/60 is 83%, a B+ on this scale."""
    _, midterm, final = make_subject(school, term_one, form_2a, "Mathematics")
    enrollment = enrol(school, form_2a, "Amina", "Hassan", 1)

    Score.objects.create(enrollment=enrollment, assessment=midterm, marks=Decimal("32"))
    Score.objects.create(enrollment=enrollment, assessment=final, marks=Decimal("51"))

    result = term_result(enrollment, term_one)
    maths = result.subjects[0]

    assert maths.marks_obtained == Decimal("83")
    assert maths.percentage == Decimal("83.00")
    assert maths.grade(scale).letter == "B"
    assert maths.is_complete


def test_a_partly_marked_subject_is_scored_on_what_exists(
    school, term_one, form_2a, scale
):
    """32/40 with the final still unmarked is 80%, not 32%.

    Dividing by the full 100 would report a well-performing student at
    32% and rank them below a classmate who was simply marked earlier.
    """
    _, midterm, _final = make_subject(school, term_one, form_2a, "Mathematics")
    enrollment = enrol(school, form_2a, "Amina", "Hassan", 1)

    Score.objects.create(enrollment=enrollment, assessment=midterm, marks=Decimal("32"))

    maths = term_result(enrollment, term_one).subjects[0]

    assert maths.percentage == Decimal("80.00")
    assert maths.grade(scale).letter == "B"
    assert not maths.is_complete
    assert maths.marks_possible == Decimal("100")


def test_an_unmarked_subject_has_no_percentage_and_no_grade(
    school, term_one, form_2a, scale
):
    make_subject(school, term_one, form_2a, "Mathematics")
    enrollment = enrol(school, form_2a, "Amina", "Hassan", 1)

    maths = term_result(enrollment, term_one).subjects[0]

    assert maths.percentage is None
    assert maths.grade(scale) is None
    assert not maths.has_any_mark


def test_zero_marks_scores_zero_rather_than_nothing(school, term_one, form_2a, scale):
    """Scoring nothing is a fail. Not being marked is not."""
    _, midterm, final = make_subject(school, term_one, form_2a, "Mathematics")
    enrollment = enrol(school, form_2a, "Amina", "Hassan", 1)

    Score.objects.create(enrollment=enrollment, assessment=midterm, marks=Decimal("0"))
    Score.objects.create(enrollment=enrollment, assessment=final, marks=Decimal("0"))

    maths = term_result(enrollment, term_one).subjects[0]

    assert maths.percentage == Decimal("0.00")
    assert maths.grade(scale).letter == "F"
    assert maths.has_any_mark


# ---------- the whole term ----------


def test_the_term_average_spans_every_subject(school, term_one, form_2a, scale):
    enrollment = enrol(school, form_2a, "Amina", "Hassan", 1)
    for name, mid, fin in [
        ("Mathematics", "36", "54"),  # 90
        ("English", "30", "45"),  # 75
        ("Biology", "24", "36"),  # 60
    ]:
        _, midterm, final = make_subject(school, term_one, form_2a, name)
        Score.objects.create(
            enrollment=enrollment, assessment=midterm, marks=Decimal(mid)
        )
        Score.objects.create(
            enrollment=enrollment, assessment=final, marks=Decimal(fin)
        )

    result = term_result(enrollment, term_one)

    assert result.marks_obtained == Decimal("225")
    assert result.marks_available == Decimal("300")
    assert result.average_percentage == Decimal("75.00")
    assert result.grade(scale).letter == "B-"
    assert result.is_complete


def test_subjects_passed_counts_everything_but_a_fail(school, term_one, form_2a, scale):
    enrollment = enrol(school, form_2a, "Amina", "Hassan", 1)
    for name, mid, fin in [
        ("Mathematics", "36", "54"),  # 90  A-
        ("English", "20", "30"),  # 50  D
        ("Biology", "10", "15"),  # 25  F
    ]:
        _, midterm, final = make_subject(school, term_one, form_2a, name)
        Score.objects.create(
            enrollment=enrollment, assessment=midterm, marks=Decimal(mid)
        )
        Score.objects.create(
            enrollment=enrollment, assessment=final, marks=Decimal(fin)
        )

    result = term_result(enrollment, term_one)

    assert result.subjects_passed(scale) == 2


# ---------- class position ----------


def test_students_are_ranked_by_average(school, term_one, form_2a, scale):
    _, midterm, final = make_subject(school, term_one, form_2a, "Mathematics")
    people = [
        ("Amina", "Hassan", "20", "30"),  # 50
        ("Yusuf", "Ali", "36", "54"),  # 90
        ("Sagal", "Omar", "28", "42"),  # 70
    ]
    for roll, (first, last, mid, fin) in enumerate(people, start=1):
        enrollment = enrol(school, form_2a, first, last, roll)
        Score.objects.create(
            enrollment=enrollment, assessment=midterm, marks=Decimal(mid)
        )
        Score.objects.create(
            enrollment=enrollment, assessment=final, marks=Decimal(fin)
        )

    results = class_results(form_2a, term_one)

    assert [(r.student_name, r.position) for r in results] == [
        ("Yusuf Ali", 1),
        ("Sagal Omar", 2),
        ("Amina Hassan", 3),
    ]


def test_tied_students_share_a_position(school, term_one, form_2a, scale):
    """Two students on the same average are both second, and the next is
    fourth. Splitting a tie arbitrarily would be indefensible."""
    _, midterm, final = make_subject(school, term_one, form_2a, "Mathematics")
    people = [
        ("Yusuf", "Ali", "36", "54"),  # 90
        ("Sagal", "Omar", "28", "42"),  # 70
        ("Amina", "Hassan", "28", "42"),  # 70
        ("Liban", "Nur", "20", "30"),  # 50
    ]
    for roll, (first, last, mid, fin) in enumerate(people, start=1):
        enrollment = enrol(school, form_2a, first, last, roll)
        Score.objects.create(
            enrollment=enrollment, assessment=midterm, marks=Decimal(mid)
        )
        Score.objects.create(
            enrollment=enrollment, assessment=final, marks=Decimal(fin)
        )

    positions = {r.student_name: r.position for r in class_results(form_2a, term_one)}

    assert positions["Yusuf Ali"] == 1
    assert positions["Sagal Omar"] == 2
    assert positions["Amina Hassan"] == 2
    assert positions["Liban Nur"] == 4


def test_an_unmarked_student_is_unranked_rather_than_last(
    school, term_one, form_2a, scale
):
    """Being unmarked is not the same as scoring nothing, so it must not
    put a student at the bottom of the class."""
    _, midterm, final = make_subject(school, term_one, form_2a, "Mathematics")

    marked = enrol(school, form_2a, "Yusuf", "Ali", 1)
    Score.objects.create(enrollment=marked, assessment=midterm, marks=Decimal("36"))
    Score.objects.create(enrollment=marked, assessment=final, marks=Decimal("54"))

    enrol(school, form_2a, "Amina", "Hassan", 2)  # no marks at all

    results = {r.student_name: r for r in class_results(form_2a, term_one)}

    assert results["Yusuf Ali"].position == 1
    assert results["Amina Hassan"].position is None
    assert results["Yusuf Ali"].class_size == 1


def test_class_size_counts_only_ranked_students(school, term_one, form_2a, scale):
    _, midterm, final = make_subject(school, term_one, form_2a, "Mathematics")
    for roll in range(1, 4):
        enrollment = enrol(school, form_2a, f"Student{roll}", "Test", roll)
        Score.objects.create(
            enrollment=enrollment, assessment=midterm, marks=Decimal("30")
        )
        Score.objects.create(
            enrollment=enrollment, assessment=final, marks=Decimal("45")
        )

    results = class_results(form_2a, term_one)

    assert all(r.class_size == 3 for r in results)


def test_ranking_ignores_students_from_another_class(school, year, term_one, scale):
    """A position is a position within a class, not the whole school."""
    form_2a = ClassRoom.objects.create(academic_year=year, name="Form 2A")
    form_2b = ClassRoom.objects.create(academic_year=year, name="Form 2B")

    subject = Subject.objects.create(institution=school, name="Mathematics")
    for classroom in (form_2a, form_2b):
        Assessment.objects.create(
            term=term_one,
            subject=subject,
            classroom=classroom,
            name="Final",
            max_marks=Decimal("100"),
        )

    top_of_2b = enrol(school, form_2b, "Yusuf", "Ali", 1)
    Score.objects.create(
        enrollment=top_of_2b,
        assessment=Assessment.objects.get(classroom=form_2b),
        marks=Decimal("99"),
    )

    only_in_2a = enrol(school, form_2a, "Amina", "Hassan", 1)
    Score.objects.create(
        enrollment=only_in_2a,
        assessment=Assessment.objects.get(classroom=form_2a),
        marks=Decimal("55"),
    )

    results = class_results(form_2a, term_one)

    assert len(results) == 1
    assert results[0].student_name == "Amina Hassan"
    assert results[0].position == 1  # first in 2A despite a lower mark than 2B
