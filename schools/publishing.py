"""Releasing a term's results to students.

This is the action a school performs most often and understands least
comfortably. Publishing makes every mark in a term visible to every
student in it at once, and withdrawing takes them all back. Until now it
lived in the Django admin, behind a list filter and a bulk action, which
is a reasonable back office for a developer and the wrong place to ask a
head teacher to press the most consequential button in the system.

Three rules shape what follows.

**Publication is never silent.** Both directions go through
`Term.publish()` / `Term.unpublish()`, which write the audit entry. This
module never touches `is_published` itself.

**A school sees only its own terms.** Every query is filtered by the
signed-in administrator's institution, and the POST re-checks it rather
than trusting the id in the form.

**Incomplete marking warns, it does not block.** A term is often
published with marks missing — a student sits an exam late, or was
absent. Refusing to publish would make the software wrong about how
schools actually work, so the count is shown plainly and the decision is
left to the person who is accountable for it.
"""

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from accounts.permissions import admin_required
from schools.models import Enrollment, Score, Term

PUBLISH = "publish"
WITHDRAW = "withdraw"


def terms_for(user):
    """Every term belonging to this administrator's school.

    A superuser runs the deployment rather than belonging to a school,
    and publishing another school's results is not theirs to do, so they
    get nothing here rather than everything. Failing closed is the
    difference between a bug and a breach.
    """
    institution = user.institution
    if institution is None:
        return Term.objects.none()

    return (
        Term.objects.filter(academic_year__institution=institution)
        .select_related("academic_year", "published_by")
        .order_by("-academic_year__start_date", "sequence")
    )


def marking_progress(term):
    """How much of this term has actually been marked.

    Answers the question an administrator is really asking before they
    publish: is this finished? Counting scores alone would not — a
    missing Score row and a Score with no marks both mean "not marked",
    and only one of them exists as a row.
    """
    expected = Enrollment.objects.filter(
        classroom__assessments__term=term, is_active=True
    ).count()

    counts = Score.objects.filter(assessment__term=term).aggregate(
        marked=Count("id", filter=Q(marks__isnull=False)),
    )
    marked = counts["marked"] or 0

    return {
        "expected": expected,
        "marked": marked,
        "missing": max(expected - marked, 0),
        "percent": round(marked / expected * 100) if expected else 0,
    }


@admin_required
def term_publication(request):
    """List this school's terms, and release or withdraw their results."""
    if request.method == "POST":
        return _apply(request)

    rows = [
        {"term": term, "progress": marking_progress(term)}
        for term in terms_for(request.user)
    ]

    return render(
        request,
        "schools/term_publication.html",
        {
            "nav_active": "publishing",
            "rows": rows,
            "institution": request.user.institution,
        },
    )


def _apply(request):
    """Carry out a publish or withdraw, or refuse and say why."""
    action = request.POST.get("action")
    term_id = request.POST.get("term")

    # Re-filtered by institution rather than fetched by id alone. The id
    # arrives from a form, and a form is whatever the person sending it
    # decided to put in it.
    term = terms_for(request.user).filter(pk=term_id).first()

    if term is None:
        messages.error(request, _("That term is not one of your school's."))
        return redirect("term_publication")

    if action == PUBLISH:
        term.publish(released_by=request.user)
        messages.success(
            request,
            _("%(term)s is published. Students can now see their results.")
            % {"term": term.name},
        )
    elif action == WITHDRAW:
        term.unpublish(withdrawn_by=request.user)
        messages.success(
            request,
            _("%(term)s is withdrawn. Students can no longer see these results.")
            % {"term": term.name},
        )
    else:
        messages.error(request, _("Unrecognised action."))

    return redirect("term_publication")
