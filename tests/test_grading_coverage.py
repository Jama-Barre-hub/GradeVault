"""Tests for grading scale coverage.

Written after a real mistake: a scale was saved with band D running
50.00-50.99 instead of 50.00-59.99. Every student scoring 51% to 59%
would have received a blank grade, and nothing warned anyone.
"""

from decimal import Decimal

import pytest

from schools.models import GradeBand, GradingScale, Institution


@pytest.fixture
def school(db):
    return Institution.objects.create(name="Hodan Secondary School", short_name="HSS")


def build_scale(school, bands, name="Scale"):
    scale = GradingScale.objects.create(institution=school, name=name)
    for letter, low, high in bands:
        GradeBand.objects.create(
            scale=scale,
            letter=letter,
            min_percentage=Decimal(str(low)),
            max_percentage=Decimal(str(high)),
        )
    return scale


COMPLETE = [
    ("A", 80, 100),
    ("B", 70, 79.99),
    ("C", 60, 69.99),
    ("D", 50, 59.99),
    ("F", 0, 49.99),
]


def test_a_complete_scale_reports_no_gaps(school):
    scale = build_scale(school, COMPLETE)

    assert scale.coverage_gaps() == []
    assert scale.is_complete


def test_every_whole_percentage_gets_a_grade_in_a_complete_scale(school):
    scale = build_scale(school, COMPLETE)

    ungraded = [p for p in range(101) if scale.grade_for(Decimal(p)) is None]

    assert ungraded == []


def test_the_real_mistyped_band_is_detected(school):
    """The exact typo that prompted this: 50.99 where 59.99 was meant."""
    scale = build_scale(
        school,
        [
            ("A", 80, 100),
            ("B", 70, 79.99),
            ("C", 60, 69.99),
            ("D", 50, 50.99),  # the typo
            ("F", 0, 49.99),
        ],
    )

    gaps = scale.coverage_gaps()

    assert not scale.is_complete
    assert gaps == [(Decimal("50.99"), Decimal("60.00"))]


def test_a_missing_top_band_is_detected(school):
    scale = build_scale(school, [("F", 0, 49.99), ("D", 50, 79.99)])

    assert scale.coverage_gaps() == [(Decimal("79.99"), Decimal("100"))]


def test_a_missing_bottom_band_is_detected(school):
    scale = build_scale(school, [("A", 80, 100), ("B", 40, 79.99)])

    assert scale.coverage_gaps() == [(Decimal("0"), Decimal("40.00"))]


def test_a_scale_with_no_bands_covers_nothing(school):
    scale = GradingScale.objects.create(institution=school, name="Empty")

    assert scale.coverage_gaps() == [(Decimal("0"), Decimal("100"))]


def test_inclusive_band_edges_are_not_treated_as_gaps(school):
    """ "up to 49.99" then "from 50" is adjacent, not a hole."""
    scale = build_scale(school, [("F", 0, 49.99), ("P", 50, 100)])

    assert scale.coverage_gaps() == []


def test_several_gaps_are_all_reported(school):
    scale = build_scale(school, [("F", 0, 20), ("C", 40, 60), ("A", 80, 100)])

    assert scale.coverage_gaps() == [
        (Decimal("20.00"), Decimal("40.00")),
        (Decimal("60.00"), Decimal("80.00")),
    ]
