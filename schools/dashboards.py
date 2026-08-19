"""The landing page each role sees after signing in.

One entry point, three separate builders and three separate templates.
A single template that renders different things depending on who is
looking is how one role's data ends up on another role's screen, so the
branching happens here, in Python, where it can be tested.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from accounts.models import StudentProfile, TeacherProfile
from audit.models import AuditLog
from schools.models import (
    Assessment,
    ClassRoom,
    Enrollment,
    GradingScale,
    Score,
    Subject,
    Term,
)
from schools.results import class_results, default_scale_for, term_result


def current_term(academic_year):
    """The term today falls inside, or the most recent one to have begun.

    Schools work in the term they are in, so a dashboard that always
    showed the first term of the year would be wrong for most of it.
    """
    if academic_year is None:
        return None

    today = timezone.localdate()
    terms = list(academic_year.terms.order_by("sequence"))
    if not terms:
        return None

    for term in terms:
        if term.start_date <= today <= term.end_date:
            return term

    started = [t for t in terms if t.start_date <= today]
    return started[-1] if started else terms[0]


@login_required
def dashboard(request):
    user = request.user

    if user.is_student:
        return _student(request)
    if user.is_teacher:
        return _teacher(request)
    if user.is_admin:
        return _administrator(request)

    return render(request, "accounts/no_role.html", status=403)


# ---------------------------------------------------------------- student


def _student(request):
    profile = getattr(request.user, "student_profile", None)
    enrollment = profile.current_enrollment() if profile else None

    if enrollment is None:
        return render(
            request,
            "schools/dash_student.html",
            {"nav_active": "home", "student": profile, "latest": None},
        )

    classroom = enrollment.classroom
    scale = default_scale_for(classroom)

    published = list(
        Term.objects.filter(
            academic_year=classroom.academic_year, is_published=True
        ).order_by("-sequence")
    )

    latest = None
    if published:
        term = published[0]
        result = term_result(enrollment, term)
        latest = {
            "term": term,
            "result": result,
            "grade": result.grade(scale),
            "passed": result.subjects_passed(scale),
            "position": _place_in_class(classroom, term, enrollment),
        }

    waiting = Term.objects.filter(
        academic_year=classroom.academic_year, is_published=False
    ).count()

    return render(
        request,
        "schools/dash_student.html",
        {
            "nav_active": "home",
            "student": profile,
            "enrollment": enrollment,
            "classroom": classroom,
            "latest": latest,
            "waiting": waiting,
            "published_count": len(published),
        },
    )


def _place_in_class(classroom, term, enrollment):
    for result in class_results(classroom, term):
        if result.enrollment_id == enrollment.id:
            return {"place": result.position, "out_of": result.class_size}
    return {"place": None, "out_of": None}


# ---------------------------------------------------------------- teacher


def _teacher(request):
    """Show what still needs marking, rather than a list of everything.

    A teacher's question on signing in is "what have I not finished?",
    so the dashboard answers that first.
    """
    profile = getattr(request.user, "teacher_profile", None)
    assignments = (
        profile.assignments.filter(is_active=True)
        .select_related("subject", "classroom", "classroom__academic_year")
        .order_by("classroom__name", "subject__name")
        if profile
        else []
    )

    year = assignments[0].classroom.academic_year if assignments else None
    term = current_term(year)

    class_sizes = dict(
        Enrollment.objects.filter(
            classroom__in=[a.classroom_id for a in assignments], is_active=True
        )
        .values_list("classroom_id")
        .annotate(n=Count("id"))
    )

    rows, outstanding = [], 0

    for assignment in assignments:
        if term is None:
            continue

        assessments = Assessment.objects.filter(
            term=term, subject=assignment.subject, classroom=assignment.classroom
        )
        assessment_count = assessments.count()
        students = class_sizes.get(assignment.classroom_id, 0)
        expected = assessment_count * students

        marked = Score.objects.filter(
            assessment__in=assessments, marks__isnull=False
        ).count()

        missing = max(expected - marked, 0)
        outstanding += missing

        rows.append(
            {
                "assignment": assignment,
                "expected": expected,
                "marked": marked,
                "missing": missing,
                "percent": round(marked / expected * 100) if expected else 0,
            }
        )

    rows.sort(key=lambda row: (-row["missing"], row["assignment"].classroom.name))

    return render(
        request,
        "schools/dash_teacher.html",
        {
            "nav_active": "home",
            "teacher": profile,
            "term": term,
            "rows": rows,
            "outstanding": outstanding,
            "class_count": len({a.classroom_id for a in assignments}),
            "subject_count": len({a.subject_id for a in assignments}),
        },
    )


# ---------------------------------------------------------------- admin


def _administrator(request):
    """A school's own numbers, and anything that needs attention.

    Scoped to the administrator's institution. A superuser has none,
    because they operate the deployment rather than belonging to one
    school, and sees every school instead.
    """
    institution = request.user.institution
    operator = institution is None and request.user.is_superuser

    if institution is None and not operator:
        return render(
            request,
            "schools/dash_admin.html",
            {"nav_active": "home", "institution": None, "operator": False},
        )

    if operator:
        profile_filter = {}
        class_filter = {}
        score_filter = {}
        audit_filter = {}
    else:
        # Each model reaches Institution by its own path.
        profile_filter = {"institution": institution}
        class_filter = {"academic_year__institution": institution}
        score_filter = {
            "assessment__classroom__academic_year__institution": institution
        }
        audit_filter = {"institution": institution}

    year = None
    if not operator:
        year = institution.academic_years.filter(is_current=True).first()
    term = current_term(year)

    terms = Term.objects.filter(academic_year=year).order_by("sequence") if year else []

    incomplete_scales = [
        scale
        for scale in GradingScale.objects.filter(**profile_filter)
        if not scale.is_complete
    ]

    unmarked = Score.objects.filter(marks__isnull=True, **score_filter).count()

    return render(
        request,
        "schools/dash_admin.html",
        {
            "nav_active": "home",
            "institution": institution,
            "operator": operator,
            "year": year,
            "term": term,
            "terms": terms,
            "students": StudentProfile.objects.filter(
                is_active=True, **profile_filter
            ).count(),
            "teachers": TeacherProfile.objects.filter(
                is_active=True, **profile_filter
            ).count(),
            "classes": ClassRoom.objects.filter(**class_filter).count(),
            "subjects": Subject.objects.filter(**profile_filter).count(),
            "unmarked": unmarked,
            "incomplete_scales": incomplete_scales,
            "recent": AuditLog.objects.filter(**audit_filter)[:8],
            "published_terms": [t for t in terms if t.is_published],
        },
    )
