"""Pages for teachers and students."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
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

    if request.method == "POST":
        saved, errors = _save_marks(request, enrollments, assessments)
        if errors:
            for message in errors:
                messages.error(request, message)
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
    """Write submitted marks, reporting anything that could not be stored.

    A single bad value must not discard the rest of a teacher's typing,
    so each cell is handled on its own and problems are collected rather
    than raised.
    """
    saved = 0
    errors: list[str] = []

    valid_pairs = {(e.id, a.id): (e, a) for e in enrollments for a in assessments}

    with transaction.atomic():
        for key, raw in request.POST.items():
            if not key.startswith("m-"):
                continue

            try:
                # Not `_, ...`: this module imports gettext as _, and
                # unpacking into it would replace the translation
                # function with a string.
                prefix, enrollment_id, assessment_id = key.split("-")
                del prefix
                pair = valid_pairs[(int(enrollment_id), int(assessment_id))]
            except (ValueError, KeyError):
                # A field naming a student or assessment outside this
                # sheet is ignored rather than trusted.
                continue

            enrollment, assessment = pair
            raw = raw.strip()

            if raw == "":
                marks = None
            else:
                try:
                    marks = Decimal(raw)
                except InvalidOperation:
                    errors.append(
                        _("%(student)s: '%(value)s' is not a number.")
                        % {"student": enrollment.student.full_name, "value": raw}
                    )
                    continue

                if marks < 0 or marks > assessment.max_marks:
                    errors.append(
                        _(
                            "%(student)s: %(value)s is outside 0 to %(max)s "
                            "for %(assessment)s."
                        )
                        % {
                            "student": enrollment.student.full_name,
                            "value": marks,
                            "max": assessment.max_marks,
                            "assessment": assessment.name,
                        }
                    )
                    continue

            score, was_created = Score.objects.get_or_create(
                enrollment=enrollment, assessment=assessment
            )
            del was_created
            if score.marks != marks:
                score.marks = marks
                score.recorded_by = request.user
                score.save()
                saved += 1

        if errors:
            transaction.set_rollback(True)
            return 0, errors

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
