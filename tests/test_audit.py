"""Tests for the audit trail.

The project's central claim is that every change to a grade is
attributable. These tests are what make that claim checkable rather than
merely stated.
"""

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import StudentProfile, User, generate_student_username
from audit.models import AuditLog, AuditLogError
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
def teacher(db):
    return User.objects.create_user(
        username="tch-fomar",
        role=User.Role.TEACHER,
        first_name="Fatima",
        last_name="Omar",
    )


@pytest.fixture
def midterm(term_one, school, year):
    subject = Subject.objects.create(institution=school, name="Mathematics")
    classroom = ClassRoom.objects.create(academic_year=year, name="Form 2A")
    return Assessment.objects.create(
        term=term_one,
        subject=subject,
        classroom=classroom,
        name="Mid-term",
        max_marks=Decimal("40"),
    )


@pytest.fixture
def enrollment(school, midterm):
    user = User.objects.create_user(
        username=generate_student_username(2026),
        role=User.Role.STUDENT,
        first_name="Amina",
        last_name="Hassan",
    )
    student = StudentProfile.objects.create(
        user=user, institution=school, admission_number="ADM-001"
    )
    return Enrollment.objects.create(student=student, classroom=midterm.classroom)


# ---------- the log records what happened ----------


def test_recording_a_mark_is_logged(enrollment, midterm, teacher):
    Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )

    entry = AuditLog.objects.get()
    assert entry.action == AuditLog.Action.SCORE_RECORDED
    assert entry.actor == teacher
    assert entry.new_value == "32.00"
    assert entry.old_value == ""


def test_changing_a_mark_records_both_values(enrollment, midterm, teacher):
    """The old value is the point. Without it, tampering is invisible."""
    score = Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )

    score.marks = Decimal("38")
    score.save()

    entry = AuditLog.objects.filter(action=AuditLog.Action.SCORE_CHANGED).get()
    assert entry.old_value == "32.00"
    assert entry.new_value == "38.00"


def test_the_person_who_changed_a_mark_is_named(enrollment, midterm, teacher):
    head = User.objects.create_user(username="head", role=User.Role.ADMIN)
    score = Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )

    score.marks = Decimal("40")
    score.recorded_by = head
    score.save()

    changed = AuditLog.objects.get(action=AuditLog.Action.SCORE_CHANGED)
    assert changed.actor == head
    assert "head" in changed.actor_label


def test_clearing_a_mark_is_logged(enrollment, midterm, teacher):
    score = Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )

    score.marks = None
    score.save()

    entry = AuditLog.objects.get(action=AuditLog.Action.SCORE_CLEARED)
    assert entry.old_value == "32.00"
    assert entry.new_value == ""


def test_saving_without_changing_anything_records_nothing(enrollment, midterm, teacher):
    """An unchanged save is not an event, and noise hides real entries."""
    score = Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )
    before = AuditLog.objects.count()

    score.save()
    score.save()

    assert AuditLog.objects.count() == before


def test_an_empty_placeholder_is_not_a_recorded_mark(enrollment, midterm):
    """Creating an unmarked row is setup, not a grading decision."""
    Score.objects.create(enrollment=enrollment, assessment=midterm, marks=None)

    assert AuditLog.objects.count() == 0


def test_publishing_and_withdrawing_results_are_logged(term_one, teacher):
    head = User.objects.create_user(username="head", role=User.Role.ADMIN)

    term_one.publish(released_by=head)
    term_one.unpublish(withdrawn_by=head)

    actions = list(AuditLog.objects.order_by("id").values_list("action", flat=True))
    assert actions == [
        AuditLog.Action.TERM_PUBLISHED,
        AuditLog.Action.TERM_UNPUBLISHED,
    ]


def test_the_full_history_of_one_mark_is_reconstructable(enrollment, midterm, teacher):
    """Three edits must leave three readable entries, in order."""
    score = Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("20"),
        recorded_by=teacher,
    )
    for value in ("28", "35"):
        score.marks = Decimal(value)
        score.save()

    history = list(
        AuditLog.objects.order_by("id").values_list("old_value", "new_value")
    )

    assert history == [("", "20.00"), ("20.00", "28.00"), ("28.00", "35.00")]


# ---------- the log cannot be rewritten ----------


def test_an_entry_cannot_be_edited(enrollment, midterm, teacher):
    Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )
    entry = AuditLog.objects.get()

    entry.new_value = "40"
    with pytest.raises(AuditLogError):
        entry.save()


def test_an_entry_cannot_be_deleted(enrollment, midterm, teacher):
    Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )
    entry = AuditLog.objects.get()

    with pytest.raises(AuditLogError):
        entry.delete()

    assert AuditLog.objects.count() == 1


def test_the_log_cannot_be_bulk_updated(enrollment, midterm, teacher):
    """queryset.update() bypasses save(), so it is closed separately."""
    Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )

    with pytest.raises(AuditLogError):
        AuditLog.objects.all().update(new_value="99")


def test_the_log_cannot_be_bulk_deleted(enrollment, midterm, teacher):
    Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )

    with pytest.raises(AuditLogError):
        AuditLog.objects.all().delete()

    assert AuditLog.objects.count() == 1


# ---------- the log outlives what it describes ----------


def test_an_entry_survives_the_deletion_of_the_teacher(enrollment, midterm, teacher):
    """Removing a member of staff must not erase what they did."""
    Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )
    teacher.delete()

    entry = AuditLog.objects.get()
    assert entry.actor is None
    assert "Fatima Omar" in entry.actor_label
    assert entry.new_value == "32.00"


def test_an_entry_stays_readable_after_the_student_leaves(enrollment, midterm, teacher):
    """The names are copied, so history does not empty out over time."""
    Score.objects.create(
        enrollment=enrollment,
        assessment=midterm,
        marks=Decimal("32"),
        recorded_by=teacher,
    )
    student_user = enrollment.student.user
    enrollment.student.delete()
    student_user.delete()

    entry = AuditLog.objects.get()
    assert "Amina Hassan" in entry.student_label
    assert entry.subject_label == "Mathematics"
    assert entry.classroom_label == "Form 2A"
