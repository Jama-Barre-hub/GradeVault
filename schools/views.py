"""Pages for teachers and students."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from accounts.permissions import (
    require_teaches,
    student_required,
    teacher_profile,
    teacher_required,
)
from accounts.permissions import (
    student_profile as get_student_profile,
)
from schools.models import (
    Assessment,
    ClassRoom,
    Enrollment,
    Score,
    Subject,
    Term,
)
from schools.results import class_results, default_scale_for, term_result

# ---------------------------------------------------------------- teacher


@teacher_required
def teacher_home(request):
    """The classes and subjects this teacher is assigned to — no others."""
    teacher = teacher_profile(request)

    assignments = (
        teacher.assignments.filter(is_active=True)
        .select_related("subject", "classroom", "classroom__academic_year")
        .order_by("classroom__name", "subject__name")
    )

    terms = (
        Term.objects.filter(
            academic_year__classrooms__in=[a.classroom for a in assignments]
        )
        .distinct()
        .order_by("academic_year", "sequence")
    )

    return render(
        request,
        "schools/teacher_home.html",
        {
            "teacher": teacher,
            "assignments": assignments,
            "terms": terms,
            "nav_active": "classes",
        },
    )


@teacher_required
def mark_sheet(request, classroom_id, subject_id, term_id):
    """Enter marks for one subject, one class, one term.

    Access is checked before anything is read from the database, so a
    teacher cannot learn even the size of a class they do not teach by
    guessing an id.
    """
    teacher = teacher_profile(request)
    classroom = get_object_or_404(ClassRoom, pk=classroom_id)
    subject = get_object_or_404(Subject, pk=subject_id)
    term = get_object_or_404(Term, pk=term_id)

    require_teaches(teacher, subject, classroom)

    assessments = list(
        Assessment.objects.filter(
            term=term, subject=subject, classroom=classroom
        ).order_by("sequence", "name")
    )
    enrollments = list(
        Enrollment.objects.filter(classroom=classroom, is_active=True)
        .select_related("student__user")
        .order_by("roll_number", "student__user__last_name")
    )

    errors = {}
    if request.method == "POST":
        saved, errors = _save_marks(request, enrollments, assessments)
        if errors:
            messages.error(
                request,
                _(
                    "No marks were saved. "
                    "Correct the highlighted entries and save again."
                ),
            )
        if saved:
            messages.success(request, _("Saved %(count)d mark(s).") % {"count": saved})
        if not errors:
            return redirect(
                "mark_sheet",
                classroom_id=classroom.id,
                subject_id=subject.id,
                term_id=term.id,
            )

    existing = {
        (score.enrollment_id, score.assessment_id): score
        for score in Score.objects.filter(
            enrollment__in=enrollments, assessment__in=assessments
        )
    }

    rows = [
        {
            "enrollment": enrollment,
            "cells": [
                {
                    "assessment": assessment,
                    "field": f"m-{enrollment.id}-{assessment.id}",
                    "value": (
                        score.marks
                        if (score := existing.get((enrollment.id, assessment.id)))
                        and score.marks is not None
                        else ""
                    ),
                }
                for assessment in assessments
            ],
        }
        for enrollment in enrollments
    ]

    if errors:
        for row in rows:
            for cell in row["cells"]:
                field = cell["field"]
                cell["value"] = request.POST.get(field, cell["value"])
                cell["error"] = errors.get(field, "")

    return render(
        request,
        "schools/mark_sheet.html",
        {
            "classroom": classroom,
            "subject": subject,
            "term": term,
            "assessments": assessments,
            "rows": rows,
            "nav_active": "classes",
            "total_available": sum(a.max_marks for a in assessments) or 0,
        },
    )


def _save_marks(request, enrollments, assessments):
    """Validate the whole sheet before saving marks and their audit entries.

    An invalid sheet writes nothing. The caller keeps the submitted values
    visible so the teacher can correct errors without retyping valid marks.
    """
    saved = 0
    errors: dict[str, str] = {}
    cleaned = []

    valid_fields = {
        f"m-{e.id}-{a.id}": (e, a) for e in enrollments for a in assessments
    }

    marks_field = Score._meta.get_field("marks")
    for key, raw in request.POST.items():
        if key not in valid_fields:
            # Forged fields outside this teacher's sheet are never trusted.
            continue

        enrollment, assessment = valid_fields[key]

        range_error = _("This mark is outside 0 to %(max)s for %(assessment)s.") % {
            "max": assessment.max_marks,
            "assessment": assessment.name,
        }
        field = forms.DecimalField(
            required=False,
            min_value=0,
            max_value=assessment.max_marks,
            max_digits=marks_field.max_digits,
            decimal_places=marks_field.decimal_places,
            error_messages={"min_value": range_error, "max_value": range_error},
        )
        try:
            marks = field.clean(raw.strip())
        except ValidationError as error:
            errors[key] = " ".join(error.messages)
            continue
        cleaned.append((enrollment, assessment, marks))

    if errors:
        return 0, errors

    with transaction.atomic():
        for enrollment, assessment, marks in cleaned:
            score, was_created = Score.objects.get_or_create(
                enrollment=enrollment, assessment=assessment
            )
            del was_created
            if score.marks != marks:
                score.marks = marks
                score.recorded_by = request.user
                score.save()
                saved += 1

    return saved, errors


@teacher_required
def class_ranking(request, classroom_id, term_id):
    """Results for a class the teacher actually teaches."""
    teacher = teacher_profile(request)
    classroom = get_object_or_404(ClassRoom, pk=classroom_id)
    term = get_object_or_404(Term, pk=term_id)

    if not teacher.assignments.filter(classroom=classroom, is_active=True).exists():
        raise PermissionDenied(f"You do not teach {classroom.name}.")

    scale = default_scale_for(classroom)
    results = class_results(classroom, term)

    return render(
        request,
        "schools/class_ranking.html",
        {
            "classroom": classroom,
            "term": term,
            "scale": scale,
            "nav_active": "classes",
            "rows": [
                {
                    "result": r,
                    "grade": r.grade(scale),
                    "passed": r.subjects_passed(scale),
                }
                for r in results
            ],
        },
    )


# ---------------------------------------------------------------- student


@student_required
def student_results(request):
    """The signed-in student's own results. Never anyone else's.

    There is deliberately no student id in the URL. A page that accepts
    one invites the mistake of trusting it, and that single mistake is
    how a results system leaks every student's marks at once.
    """
    student = get_student_profile(request)
    enrollment = student.current_enrollment()

    if enrollment is None:
        return render(request, "schools/student_no_class.html", {"student": student})

    classroom = enrollment.classroom
    scale = default_scale_for(classroom)

    published_terms = Term.objects.filter(
        academic_year=classroom.academic_year, is_published=True
    ).order_by("sequence")

    reports = []
    for term in published_terms:
        result = term_result(enrollment, term)
        reports.append(
            {
                "term": term,
                "result": result,
                "grade": result.grade(scale),
                "passed": result.subjects_passed(scale),
                "subjects": [
                    {"subject": subject, "grade": subject.grade(scale)}
                    for subject in result.subjects
                ],
                "position": _position_of(classroom, term, enrollment),
            }
        )

    unpublished = Term.objects.filter(
        academic_year=classroom.academic_year, is_published=False
    ).order_by("sequence")

    return render(
        request,
        "schools/student_results.html",
        {
            "student": student,
            "enrollment": enrollment,
            "classroom": classroom,
            "reports": reports,
            "unpublished": unpublished,
            "nav_active": "results",
        },
    )


def _position_of(classroom, term, enrollment):
    """This student's place in their class, computed with everyone else's.

    Only the position is returned. Working it out requires reading the
    whole class, but nothing about a classmate leaves this function.
    """
    for result in class_results(classroom, term):
        if result.enrollment_id == enrollment.id:
            return {"place": result.position, "out_of": result.class_size}
    return {"place": None, "out_of": None}
