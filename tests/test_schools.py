"""Tests for the school structure models."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from accounts.models import User
from schools.models import (
    AcademicYear,
    ClassRoom,
    GradeBand,
    GradingScale,
    Institution,
    Subject,
    Term,
)


@pytest.fixture
def school(db):
    return Institution.objects.create(name="Hodan Secondary School", short_name="HSS")


@pytest.fixture
def year(school):
    """A year matching the real Somali calendar: September to June."""
    return AcademicYear.objects.create(
        institution=school,
        name="2026/2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=True,
    )


# ---------- Academic year ----------


def test_a_year_cannot_end_before_it_starts(school):
    year = AcademicYear(
        institution=school,
        name="2026/2027",
        start_date=date(2027, 6, 30),
        end_date=date(2026, 9, 1),
    )

    with pytest.raises(ValidationError):
        year.full_clean()


def test_only_one_year_can_be_current(school, year):
    """Marking a new year current must stand the previous one down."""
    newer = AcademicYear.objects.create(
        institution=school,
        name="2027/2028",
        start_date=date(2027, 9, 1),
        end_date=date(2028, 6, 30),
        is_current=True,
    )

    year.refresh_from_db()
    assert newer.is_current
    assert not year.is_current


def test_year_names_are_unique_within_an_institution(school, year):
    with pytest.raises(IntegrityError):
        AcademicYear.objects.create(
            institution=school,
            name="2026/2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
        )


# ---------- Terms ----------


@pytest.fixture
def term_one(year):
    """Term 1 runs September to 15 January (PROPOSAL.md §10.1)."""
    return Term.objects.create(
        academic_year=year,
        name="Term 1",
        sequence=1,
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 15),
    )


def test_a_new_term_is_unpublished(term_one):
    """Results must never be visible the moment a teacher types them."""
    assert term_one.is_published is False
    assert term_one.published_at is None
    assert term_one.published_by is None


def test_publishing_records_who_released_the_results(term_one):
    registrar = User.objects.create_user(username="registrar", role=User.Role.ADMIN)

    term_one.publish(released_by=registrar)
    term_one.refresh_from_db()

    assert term_one.is_published
    assert term_one.published_by == registrar
    assert term_one.published_at is not None


def test_results_can_be_withdrawn_after_publication(term_one):
    """A wrong mark must be correctable without losing who published it."""
    registrar = User.objects.create_user(username="registrar2", role=User.Role.ADMIN)
    term_one.publish(released_by=registrar)

    term_one.unpublish()
    term_one.refresh_from_db()

    assert term_one.is_published is False
    assert term_one.published_by == registrar  # history is not erased


def test_a_year_cannot_hold_two_terms_with_the_same_sequence(year, term_one):
    with pytest.raises(IntegrityError):
        Term.objects.create(
            academic_year=year,
            name="Term 1 again",
            sequence=1,
            start_date=date(2027, 2, 2),
            end_date=date(2027, 6, 30),
        )


# ---------- Classes ----------


def test_class_names_are_free_text(year):
    """Somali schools name levels differently; the system must not care."""
    for name in ["Class 5", "Form 2A", "9", "Fasalka 3"]:
        room = ClassRoom.objects.create(academic_year=year, name=name)
        assert room.name == name


def test_the_same_class_name_may_repeat_in_a_different_year(school, year):
    """'Class 5' in 2026/2027 is a different group from 'Class 5' in 2027/2028."""
    ClassRoom.objects.create(academic_year=year, name="Class 5")

    next_year = AcademicYear.objects.create(
        institution=school,
        name="2027/2028",
        start_date=date(2027, 9, 1),
        end_date=date(2028, 6, 30),
    )
    later = ClassRoom.objects.create(academic_year=next_year, name="Class 5")

    assert later.pk is not None


def test_a_class_name_cannot_repeat_within_one_year(year):
    ClassRoom.objects.create(academic_year=year, name="Form 2A")

    with pytest.raises(IntegrityError):
        ClassRoom.objects.create(academic_year=year, name="Form 2A")


# ---------- Subjects ----------


def test_subject_names_are_unique_within_an_institution(school):
    Subject.objects.create(institution=school, name="Mathematics", code="MATH")

    with pytest.raises(IntegrityError):
        Subject.objects.create(institution=school, name="Mathematics")


# ---------- Grading ----------


@pytest.fixture
def scale(school):
    scale = GradingScale.objects.create(
        institution=school, name="Hodan scale", is_default=True
    )
    bands = [
        ("A", 80, 100, "Excellent"),
        ("B", 70, 79.99, "Very good"),
        ("C", 60, 69.99, "Good"),
        ("D", 50, 59.99, "Pass"),
        ("F", 0, 49.99, "Fail"),
    ]
    for letter, low, high, remark in bands:
        GradeBand.objects.create(
            scale=scale,
            letter=letter,
            min_percentage=Decimal(str(low)),
            max_percentage=Decimal(str(high)),
            remark=remark,
        )
    return scale


@pytest.mark.parametrize(
    ("percentage", "expected"),
    [
        (100, "A"),
        (83, "A"),
        (80, "A"),
        (79, "B"),
        (65, "C"),
        (50, "D"),
        (49, "F"),
        (0, "F"),
    ],
)
def test_percentage_maps_to_the_right_letter(scale, percentage, expected):
    band = scale.grade_for(Decimal(str(percentage)))

    assert band is not None
    assert band.letter == expected


def test_overlapping_grade_bands_are_rejected(scale):
    """Overlapping bands would make a student's grade depend on row order."""
    clashing = GradeBand(
        scale=scale,
        letter="A+",
        min_percentage=Decimal("75"),
        max_percentage=Decimal("100"),
    )

    with pytest.raises(ValidationError):
        clashing.full_clean()


def test_a_band_cannot_end_below_where_it_starts(scale):
    backwards = GradeBand(
        scale=scale,
        letter="X",
        min_percentage=Decimal("90"),
        max_percentage=Decimal("10"),
    )

    with pytest.raises(ValidationError):
        backwards.full_clean()


def test_each_school_may_define_its_own_scale(school):
    """Somali schools set their own boundaries, so scales are per-institution."""
    other = Institution.objects.create(name="Banadir Primary", short_name="BPS")

    strict = GradingScale.objects.create(institution=school, name="Strict")
    GradeBand.objects.create(
        scale=strict,
        letter="A",
        min_percentage=Decimal("90"),
        max_percentage=Decimal("100"),
    )

    lenient = GradingScale.objects.create(institution=other, name="Lenient")
    GradeBand.objects.create(
        scale=lenient,
        letter="A",
        min_percentage=Decimal("70"),
        max_percentage=Decimal("100"),
    )

    assert strict.grade_for(Decimal("75")) is None
    assert lenient.grade_for(Decimal("75")).letter == "A"


def test_only_one_scale_per_institution_is_default(school, scale):
    replacement = GradingScale.objects.create(
        institution=school, name="New scale", is_default=True
    )

    scale.refresh_from_db()
    assert replacement.is_default
    assert not scale.is_default
