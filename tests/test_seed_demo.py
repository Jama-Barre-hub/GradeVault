"""Tests for the demo seeder.

The seeder is how the project keeps its promise never to use real student
records, so it has to work and it has to leave other schools alone.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from accounts.models import StudentProfile, TeacherProfile
from schools.management.commands.seed_demo import DEMO_SCHOOL_NAME
from schools.models import (
    Assessment,
    ClassRoom,
    Enrollment,
    Institution,
    Score,
    Term,
)


@pytest.fixture
def seeded(db):
    out = StringIO()
    call_command("seed_demo", "--students", "3", stdout=out, stderr=StringIO())
    return Institution.objects.get(name=DEMO_SCHOOL_NAME)


def test_the_seeder_builds_a_whole_school(seeded):
    assert seeded.academic_years.count() == 1
    assert seeded.subjects.count() == 8
    assert ClassRoom.objects.filter(academic_year__institution=seeded).count() == 6
    assert TeacherProfile.objects.filter(institution=seeded).count() == 12
    assert StudentProfile.objects.filter(institution=seeded).count() == 18


def test_the_calendar_matches_the_somali_school_year(seeded):
    terms = Term.objects.filter(academic_year__institution=seeded).order_by("sequence")

    assert terms.count() == 2
    assert terms[0].start_date.month == 9
    assert terms[0].end_date.month == 1
    assert terms[1].end_date.month == 6


def test_assessments_use_the_forty_sixty_split(seeded):
    classes = ClassRoom.objects.filter(academic_year__institution=seeded)
    marks = set(
        Assessment.objects.filter(classroom__in=classes).values_list(
            "max_marks", flat=True
        )
    )

    assert marks == {Decimal("40.00"), Decimal("60.00")}


def test_every_subject_totals_one_hundred_marks(seeded):
    classes = ClassRoom.objects.filter(academic_year__institution=seeded)
    terms = Term.objects.filter(academic_year__institution=seeded)

    for term in terms:
        for subject in seeded.subjects.all():
            for classroom in classes:
                total = Assessment.total_max_marks(term, subject, classroom)
                assert total == Decimal("100"), (
                    f"{subject} in {classroom} totals {total}, not 100"
                )


def test_results_start_unpublished(seeded):
    """Students must not see marks until an administrator releases them."""
    terms = Term.objects.filter(academic_year__institution=seeded)

    assert not any(term.is_published for term in terms)


def test_some_marks_are_deliberately_missing(seeded):
    """A half-marked term is the normal state of a real system."""
    classes = ClassRoom.objects.filter(academic_year__institution=seeded)
    scores = Score.objects.filter(assessment__classroom__in=classes)

    assert scores.filter(marks__isnull=True).exists()
    assert scores.filter(marks__isnull=False).exists()


def test_no_mark_exceeds_its_assessment_total(seeded):
    """The generator must obey the same rule teachers do."""
    classes = ClassRoom.objects.filter(academic_year__institution=seeded)
    over = [
        s
        for s in Score.objects.filter(
            assessment__classroom__in=classes, marks__isnull=False
        ).select_related("assessment")
        if s.marks > s.assessment.max_marks or s.marks < 0
    ]

    assert over == []


def test_every_student_sits_in_exactly_one_class(seeded):
    for student in StudentProfile.objects.filter(institution=seeded):
        assert student.enrollments.filter(is_active=True).count() == 1


def test_no_teacher_covers_the_entire_school(seeded):
    """Spread matters: it is what makes the permission tests meaningful."""
    classes = ClassRoom.objects.filter(academic_year__institution=seeded)
    total_pairs = classes.count() * seeded.subjects.count()

    for teacher in TeacherProfile.objects.filter(institution=seeded):
        assert teacher.assignments.count() < total_pairs


def test_seeded_accounts_can_actually_sign_in(db):
    """The seeder reuses one password hash for speed. That optimisation is
    worthless if the resulting accounts cannot log in."""
    from django.contrib.auth import authenticate

    call_command(
        "seed_demo", "--students", "2", "--password", "known-demo-pw", stdout=StringIO()
    )

    assert authenticate(username="demo-tch-01", password="known-demo-pw") is not None
    assert authenticate(username="STU-2026-0001", password="known-demo-pw") is not None


def test_a_wrong_password_is_still_refused(db):
    from django.contrib.auth import authenticate

    call_command(
        "seed_demo", "--students", "2", "--password", "known-demo-pw", stdout=StringIO()
    )

    assert authenticate(username="demo-tch-01", password="not-the-password") is None


def test_the_grading_scale_covers_every_percentage(seeded):
    scale = seeded.grading_scales.get(is_default=True)

    assert scale.is_complete
    assert scale.coverage_gaps() == []


def test_the_scale_uses_plus_and_minus_grades(seeded):
    """Ten pass grades plus fail. Adding them required no code change,
    because a grading scale is data owned by the school."""
    scale = seeded.grading_scales.get(is_default=True)
    letters = list(
        scale.bands.order_by("-min_percentage").values_list("letter", flat=True)
    )

    assert letters == [
        "A",
        "A-",
        "B+",
        "B",
        "B-",
        "C+",
        "C",
        "C-",
        "D+",
        "D",
        "F",
    ]


@pytest.mark.parametrize(
    ("percentage", "expected"),
    [
        (100, "A"),
        (95, "A"),
        (90, "A-"),
        (85, "B+"),
        (80, "B"),
        (75, "B-"),
        (70, "C+"),
        (65, "C"),
        (60, "C-"),
        (55, "D+"),
        (50, "D"),
        (49, "F"),
        (0, "F"),
    ],
)
def test_each_band_returns_its_own_letter(seeded, percentage, expected):
    """Every boundary value, since off-by-one at a band edge changes a
    student's reported grade."""
    scale = seeded.grading_scales.get(is_default=True)

    assert scale.grade_for(Decimal(percentage)).letter == expected


def test_fifty_passes_and_forty_nine_fails(seeded):
    """The pass mark is 50. This is the boundary that matters most to a
    student, so it is asserted directly rather than inferred."""
    scale = seeded.grading_scales.get(is_default=True)

    assert scale.grade_for(Decimal("50")).letter == "D"
    assert scale.grade_for(Decimal("49.99")).letter == "F"
    assert scale.grade_for(Decimal("49")).letter == "F"


def test_seeding_does_not_touch_another_school(db):
    """A school entered by hand must survive a demo rebuild."""
    real = Institution.objects.create(name="Hodan Secondary School", short_name="HSS")

    call_command("seed_demo", "--students", "2", stdout=StringIO())
    call_command("seed_demo", "--reset", "--students", "2", stdout=StringIO())

    real.refresh_from_db()
    assert Institution.objects.filter(pk=real.pk).exists()


def test_reset_rebuilds_rather_than_duplicating(db):
    call_command("seed_demo", "--students", "2", stdout=StringIO())
    first = Enrollment.objects.count()

    call_command("seed_demo", "--reset", "--students", "2", stdout=StringIO())

    assert Institution.objects.filter(name=DEMO_SCHOOL_NAME).count() == 1
    assert Enrollment.objects.count() == first


def test_running_twice_without_reset_refuses(db):
    err = StringIO()
    call_command("seed_demo", "--students", "2", stdout=StringIO())
    call_command("seed_demo", "--students", "2", stdout=StringIO(), stderr=err)

    assert "already exists" in err.getvalue()
    assert Institution.objects.filter(name=DEMO_SCHOOL_NAME).count() == 1


def test_the_same_seed_produces_the_same_data(db):
    call_command("seed_demo", "--students", "2", "--seed", "7", stdout=StringIO())
    first = list(
        StudentProfile.objects.order_by("admission_number").values_list(
            "user__first_name", "user__last_name"
        )
    )

    call_command(
        "seed_demo", "--reset", "--students", "2", "--seed", "7", stdout=StringIO()
    )
    second = list(
        StudentProfile.objects.order_by("admission_number").values_list(
            "user__first_name", "user__last_name"
        )
    )

    assert first == second
