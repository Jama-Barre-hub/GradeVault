"""Tests for students, teachers, enrolment and teaching assignments."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from accounts.models import (
    StudentProfile,
    TeacherProfile,
    User,
    generate_student_username,
)
from schools.models import (
    AcademicYear,
    ClassRoom,
    Enrollment,
    Institution,
    Subject,
    TeachingAssignment,
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
def form_2a(year):
    return ClassRoom.objects.create(academic_year=year, name="Form 2A")


@pytest.fixture
def form_2b(year):
    return ClassRoom.objects.create(academic_year=year, name="Form 2B")


@pytest.fixture
def maths(school):
    return Subject.objects.create(institution=school, name="Mathematics", code="MATH")


@pytest.fixture
def biology(school):
    return Subject.objects.create(institution=school, name="Biology", code="BIO")


def make_student(school, first, last, number):
    user = User.objects.create_user(
        username=generate_student_username(2026),
        role=User.Role.STUDENT,
        first_name=first,
        last_name=last,
    )
    return StudentProfile.objects.create(
        user=user, institution=school, admission_number=number
    )


def make_teacher(school, first, last, username):
    user = User.objects.create_user(
        username=username, role=User.Role.TEACHER, first_name=first, last_name=last
    )
    return TeacherProfile.objects.create(user=user, institution=school)


# ---------- Student usernames ----------


@pytest.mark.django_db
def test_the_first_student_of_an_intake_is_numbered_one():
    assert generate_student_username(2026) == "STU-2026-0001"


@pytest.mark.django_db
def test_usernames_increment_within_an_intake(school):
    make_student(school, "Amina", "Hassan", "ADM-001")
    make_student(school, "Yusuf", "Ali", "ADM-002")

    assert generate_student_username(2026) == "STU-2026-0003"


@pytest.mark.django_db
def test_numbering_restarts_for_a_new_intake(school):
    make_student(school, "Amina", "Hassan", "ADM-001")

    assert generate_student_username(2027) == "STU-2027-0001"


@pytest.mark.django_db
def test_a_hand_edited_username_does_not_block_the_next_admission(school):
    """An administrator may rename an account; admissions must continue."""
    User.objects.create_user(username="STU-2026-transferred", role=User.Role.STUDENT)

    generated = generate_student_username(2026)

    assert generated.startswith("STU-2026-")
    assert not User.objects.filter(username=generated).exists()


@pytest.mark.django_db
def test_admission_numbers_are_unique_within_a_school(school):
    make_student(school, "Amina", "Hassan", "ADM-001")

    with pytest.raises(IntegrityError):
        make_student(school, "Different", "Person", "ADM-001")


# ---------- Enrolment ----------


@pytest.mark.django_db
def test_a_student_is_placed_in_a_class(school, form_2a):
    student = make_student(school, "Amina", "Hassan", "ADM-001")

    Enrollment.objects.create(student=student, classroom=form_2a, roll_number=1)

    assert student.current_enrollment().classroom == form_2a


@pytest.mark.django_db
def test_a_student_cannot_sit_in_two_classes_in_the_same_year(school, form_2a, form_2b):
    """Two classes would place the same student in two rankings at once."""
    student = make_student(school, "Amina", "Hassan", "ADM-001")
    Enrollment.objects.create(student=student, classroom=form_2a)

    second = Enrollment(student=student, classroom=form_2b)

    with pytest.raises(ValidationError):
        second.full_clean()


@pytest.mark.django_db
def test_a_student_progresses_to_a_class_in_the_next_year(school, year, form_2a):
    """Moving up a year is normal and must be allowed."""
    student = make_student(school, "Amina", "Hassan", "ADM-001")
    old = Enrollment.objects.create(student=student, classroom=form_2a)
    old.is_active = False
    old.save()

    next_year = AcademicYear.objects.create(
        institution=school,
        name="2027/2028",
        start_date=date(2027, 9, 1),
        end_date=date(2028, 6, 30),
    )
    form_3a = ClassRoom.objects.create(academic_year=next_year, name="Form 3A")

    progression = Enrollment(student=student, classroom=form_3a)
    progression.full_clean()
    progression.save()

    assert student.current_enrollment().classroom == form_3a


@pytest.mark.django_db
def test_a_student_cannot_be_enrolled_twice_in_one_class(school, form_2a):
    student = make_student(school, "Amina", "Hassan", "ADM-001")
    Enrollment.objects.create(student=student, classroom=form_2a)

    with pytest.raises(IntegrityError):
        Enrollment.objects.create(student=student, classroom=form_2a)


# ---------- Teaching assignments: the permission primitive ----------


@pytest.mark.django_db
def test_a_teacher_teaches_the_subject_they_are_assigned(school, form_2a, maths):
    teacher = make_teacher(school, "Fatima", "Omar", "tch-fomar")
    TeachingAssignment.objects.create(teacher=teacher, subject=maths, classroom=form_2a)

    assert teacher.teaches(maths, form_2a)


@pytest.mark.django_db
def test_a_teacher_does_not_teach_a_subject_they_were_never_given(
    school, form_2a, maths, biology
):
    """The rule this whole project exists to enforce."""
    teacher = make_teacher(school, "Fatima", "Omar", "tch-fomar")
    TeachingAssignment.objects.create(teacher=teacher, subject=maths, classroom=form_2a)

    assert not teacher.teaches(biology, form_2a)


@pytest.mark.django_db
def test_a_teacher_does_not_teach_their_subject_in_another_class(
    school, form_2a, form_2b, maths
):
    """Teaching maths to Form 2A grants nothing over Form 2B."""
    teacher = make_teacher(school, "Fatima", "Omar", "tch-fomar")
    TeachingAssignment.objects.create(teacher=teacher, subject=maths, classroom=form_2a)

    assert not teacher.teaches(maths, form_2b)


@pytest.mark.django_db
def test_a_withdrawn_assignment_removes_the_permission(school, form_2a, maths):
    """A teacher who leaves a class must lose access without losing history."""
    teacher = make_teacher(school, "Fatima", "Omar", "tch-fomar")
    assignment = TeachingAssignment.objects.create(
        teacher=teacher, subject=maths, classroom=form_2a
    )

    assignment.is_active = False
    assignment.save()

    assert not teacher.teaches(maths, form_2a)


@pytest.mark.django_db
def test_two_teachers_may_share_a_subject_in_one_class(school, form_2a, maths):
    """Co-teaching happens; the model must not forbid it."""
    first = make_teacher(school, "Fatima", "Omar", "tch-fomar")
    second = make_teacher(school, "Ahmed", "Nur", "tch-anur")

    TeachingAssignment.objects.create(teacher=first, subject=maths, classroom=form_2a)
    TeachingAssignment.objects.create(teacher=second, subject=maths, classroom=form_2a)

    assert first.teaches(maths, form_2a)
    assert second.teaches(maths, form_2a)


@pytest.mark.django_db
def test_the_same_assignment_cannot_be_recorded_twice(school, form_2a, maths):
    teacher = make_teacher(school, "Fatima", "Omar", "tch-fomar")
    TeachingAssignment.objects.create(teacher=teacher, subject=maths, classroom=form_2a)

    with pytest.raises(IntegrityError):
        TeachingAssignment.objects.create(
            teacher=teacher, subject=maths, classroom=form_2a
        )
