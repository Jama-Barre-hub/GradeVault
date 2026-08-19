"""Report cards: one student, one term, laid out to be printed.

Two ways in, deliberately separate rather than one view that decides
what a caller is allowed to see:

  - a student opens their own card, and the URL carries no student
    identifier, so there is nothing to tamper with
  - a teacher opens a card for a student in a class they teach, and the
    identifier is checked against that class

A term that has not been published shows nothing to the student. Staff
may view an unpublished card, because someone has to check a report
before the school releases it.
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from accounts.permissions import (
    student_profile as get_student_profile,
)
from accounts.permissions import (
    student_required,
    teacher_profile,
    teacher_required,
)
from schools.models import ClassRoom, Enrollment, Term
from schools.results import class_results, default_scale_for, term_result


def _build(enrollment, term, *, released):
    """Everything one card shows, gathered in one place.

    Both entry points render the same template from this, so a student
    and a teacher never see two different versions of the same report.
    """
    classroom = enrollment.classroom
    scale = default_scale_for(classroom)
    result = term_result(enrollment, term)

    place, out_of = None, None
    for other in class_results(classroom, term):
        if other.enrollment_id == enrollment.id:
            place, out_of = other.position, other.class_size
            break

    return {
        "institution": classroom.academic_year.institution,
        "student": enrollment.student,
        "enrollment": enrollment,
        "classroom": classroom,
        "term": term,
        "result": result,
        "grade": result.grade(scale),
        "passed": result.subjects_passed(scale),
        "place": place,
        "out_of": out_of,
        "rows": [
            {"subject": subject, "grade": subject.grade(scale)}
            for subject in result.subjects
        ],
        "released": released,
    }


@student_required
def my_report_card(request, term_id):
    """A student's own card. No student identifier in the URL."""
    student = get_student_profile(request)
    enrollment = student.current_enrollment()

    if enrollment is None:
        raise PermissionDenied("You are not enrolled in a class.")

    term = get_object_or_404(
        Term, pk=term_id, academic_year=enrollment.classroom.academic_year
    )

    if not term.is_published:
        # Not 404: the term plainly exists. Saying so is honest and
        # reveals nothing, because no figure from it is shown.
        return render(
            request,
            "schools/report_card_unavailable.html",
            {"term": term, "nav_active": "results"},
            status=403,
        )

    return render(
        request,
        "schools/report_card.html",
        {**_build(enrollment, term, released=True), "nav_active": "results"},
    )


@teacher_required
def class_report_card(request, classroom_id, term_id, enrollment_id):
    """A card for one student in a class this teacher actually teaches."""
    teacher = teacher_profile(request)
    classroom = get_object_or_404(ClassRoom, pk=classroom_id)
    term = get_object_or_404(Term, pk=term_id, academic_year=classroom.academic_year)

    if not teacher.assignments.filter(classroom=classroom, is_active=True).exists():
        raise PermissionDenied(f"You do not teach {classroom.name}.")

    # Matching on the class as well as the id is what stops an
    # identifier from another class being accepted.
    enrollment = get_object_or_404(
        Enrollment, pk=enrollment_id, classroom=classroom, is_active=True
    )

    return render(
        request,
        "schools/report_card.html",
        {
            **_build(enrollment, term, released=term.is_published),
            "nav_active": "classes",
            "staff_view": True,
        },
    )
