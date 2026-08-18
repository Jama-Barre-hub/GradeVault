"""Tests for assessments and scores.

Marks are recorded out of the assessment's own total, exactly as a
teacher writes them in a mark book: 32 out of 40 (PROPOSAL.md §10.2).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from accounts.models import (
    StudentProfile,
    User,
    generate_student_username,
)
from schools.models import (
    AcademicYear,
    Assessment,
    ClassRoom,
    Enrollment,
    Institution,
    Score,
    Subject,
    Term,
)


@pytest.fixture
def school(db):
    return Institution.objects.create(name="Hodan Secondary School", short_name="HSS")


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
def maths(school):
    return Subject.objects.create(institution=school, name="Mathematics", code="MATH")


@pytest.fixture
def midterm(term_one, maths, form_2a):
    """The Somali default: mid-term marked out of 40."""
    return Assessment.objects.create(
        term=term_one,
        subject=maths,
        classroom=form_2a,
        name="Mid-term",
        max_marks=Decimal("40"),
        sequence=1,
    )


@pytest.fixture
def final(term_one, maths, form_2a):
    """The Somali default: final marked out of 60."""
    return Assessment.objects.create(
        term=term_one,
        subject=maths,
        classroom=form_2a,
        name="Final",
        max_marks=Decimal("60"),
        sequence=2,
    )


@pytest.fixture
def enrollment(school, form_2a):
    user = User.objects.create_user(
        username=generate_student_username(2026),
        role=User.Role.STUDENT,
        first_name="Amina",
        last_name="Hassan",
    )
    student = StudentProfile.objects.create(
        user=user, institution=school, admission_number="ADM-001"
    )
    return Enrollment.objects.create(student=student, classroom=form_2a, roll_number=1)


# ---------- Assessments ----------


def test_the_default_structure_sums_to_one_hundred(
    term_one, maths, form_2a, midterm, final
):
    """Mid-term 40 plus final 60, as Somali schools mark them."""
    total = Assessment.total_max_marks(term_one, maths, form_2a)

    assert total == Decimal("100")


def test_an_incomplete_subject_reports_less_than_one_hundred(
    term_one, maths, form_2a, midterm
):
    """Only the mid-term exists so far, so the subject is not yet whole."""
    assert Assessment.total_max_marks(term_one, maths, form_2a) == Decimal("40")


def test_a_school_may_use_a_different_weighting(term_one, maths, form_2a):
    """Some schools weight the mid-term at 30 instead of 40."""
    Assessment.objects.create(
        term=term_one,
        subject=maths,
        classroom=form_2a,
        name="Mid-term",
        max_marks=Decimal("30"),
    )
    Assessment.objects.create(
        term=term_one,
        subject=maths,
        classroom=form_2a,
        name="Final",
        max_marks=Decimal("70"),
    )

    assert Assessment.total_max_marks(term_one, maths, form_2a) == Decimal("100")


def test_a_school_may_add_a_third_assessment(term_one, maths, form_2a):
    """Homework 10 + mid-term 30 + final 60 must work without code changes."""
    for name, marks in [("Homework", 10), ("Mid-term", 30), ("Final", 60)]:
        Assessment.objects.create(
            term=term_one,
            subject=maths,
            classroom=form_2a,
            name=name,
            max_marks=Decimal(marks),
        )

    assert Assessment.total_max_marks(term_one, maths, form_2a) == Decimal("100")


def test_an_assessment_name_cannot_repeat_for_one_subject(
    term_one, maths, form_2a, midterm
):
    with pytest.raises(IntegrityError):
        Assessment.objects.create(
            term=term_one,
            subject=maths,
            classroom=form_2a,
            name="Mid-term",
            max_marks=Decimal("40"),
        )


# ---------- Scores ----------


def test_a_mark_is_recorded_out_of_the_assessment_total(enrollment, midterm):
    score = Score.objects.create(
        enrollment=enrollment, assessment=midterm, marks=Decimal("32")
    )

    assert score.marks == Decimal("32")
    assert score.assessment.max_marks == Decimal("40")
    assert score.is_marked


def test_the_worked_example_from_the_proposal(enrollment, midterm, final):
    """32/40 and 51/60 gives a term total of 83 (PROPOSAL.md §10.2)."""
    Score.objects.create(enrollment=enrollment, assessment=midterm, marks=Decimal("32"))
    Score.objects.create(enrollment=enrollment, assessment=final, marks=Decimal("51"))

    total = sum(s.marks for s in enrollment.scores.all())

    assert total == Decimal("83")


def test_a_mark_above_the_maximum_is_refused(enrollment, midterm):
    """45 out of 40 is not a mark; it is a typing mistake."""
    with pytest.raises(ValidationError):
        Score.objects.create(
            enrollment=enrollment, assessment=midterm, marks=Decimal("45")
        )


def test_the_maximum_itself_is_allowed(enrollment, midterm):
    score = Score.objects.create(
        enrollment=enrollment, assessment=midterm, marks=Decimal("40")
    )

    assert score.marks == Decimal("40")


def test_a_negative_mark_is_refused(enrollment, midterm):
    with pytest.raises(ValidationError):
        Score.objects.create(
            enrollment=enrollment, assessment=midterm, marks=Decimal("-1")
        )


def test_an_over_maximum_mark_is_refused_even_when_saved_directly(enrollment, midterm):
    """save() validates too, so code paths that skip forms cannot slip past."""
    score = Score(enrollment=enrollment, assessment=midterm, marks=Decimal("41"))

    with pytest.raises(ValidationError):
        score.save()

    assert not Score.objects.filter(enrollment=enrollment).exists()


def test_an_unmarked_score_is_not_the_same_as_zero(enrollment, midterm):
    """A student not yet marked must not be recorded as having failed."""
    score = Score.objects.create(enrollment=enrollment, assessment=midterm, marks=None)

    assert score.marks is None
    assert not score.is_marked
    assert score.marks != Decimal("0")


def test_zero_is_a_valid_mark(enrollment, midterm):
    """Scoring nothing is different from not being marked, and both are legal."""
    score = Score.objects.create(
        enrollment=enrollment, assessment=midterm, marks=Decimal("0")
    )

    assert score.is_marked
    assert score.marks == Decimal("0")


def test_a_student_cannot_be_marked_twice_for_one_assessment(enrollment, midterm):
    Score.objects.create(enrollment=enrollment, assessment=midterm, marks=Decimal("32"))

    with pytest.raises(IntegrityError):
        Score.objects.create(
            enrollment=enrollment, assessment=midterm, marks=Decimal("35")
        )


def test_a_correction_updates_the_existing_mark(enrollment, midterm):
    score = Score.objects.create(
        enrollment=enrollment, assessment=midterm, marks=Decimal("32")
    )

    score.marks = Decimal("35")
    score.save()
    score.refresh_from_db()

    assert score.marks == Decimal("35")
