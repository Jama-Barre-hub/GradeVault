"""School setup: years, terms, classes, subjects and grading scales.

The Django admin can already edit every one of these. What it cannot do
is answer the question a head teacher actually has in September, which
is not "what rows exist" but **"is my school ready to record marks?"**

Answering that needs the pieces checked against each other rather than
listed separately. A year with no terms, a class nobody teaches, a
grading scale with a gap in it — each looks fine on its own screen and
each stops results working. So `readiness()` below is the centre of this
module and the list screens hang off it.

The same two rules as everywhere else in the portal:

**Everything is scoped to the signed-in administrator's school**, and
scoped on the way in rather than checked on the way out. An object
fetched by an id from a form is re-filtered by institution first.

**Nothing here can publish results.** Setup and publication are separate
screens on purpose: one is preparation, the other is irreversible in the
eyes of every student in the school.
"""

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from accounts.permissions import admin_required
from schools.models import (
    AcademicYear,
    ClassRoom,
    GradeBand,
    GradingScale,
    Term,
)
from schools.setup_forms import (
    AcademicYearForm,
    ClassRoomForm,
    GradeBandForm,
    GradingScaleForm,
    SubjectForm,
    TermForm,
)


def institution_of(request):
    """The school this administrator belongs to, or 404.

    A superuser operates the deployment rather than belonging to a
    school, so they have no institution and land here too. Setting up
    somebody else's school is not theirs to do, and failing closed is
    the difference between a bug and a breach.
    """
    institution = request.user.institution
    if institution is None:
        raise Http404("This account is not attached to a school.")
    return institution


def current_year(institution):
    """The year the school is working in, or its most recent one."""
    return (
        institution.academic_years.filter(is_current=True).first()
        or institution.academic_years.order_by("-start_date").first()
    )


# ------------------------------------------------------------- readiness


def readiness(institution):
    """What still stands between this school and recording marks.

    Ordered by what has to happen first: there is no point telling
    somebody their classes have no subjects when they have not created a
    year yet. Each entry names the thing to do, not the rule that failed.
    """
    problems = []
    year = current_year(institution)

    if year is None:
        problems.append(
            {
                "what": _("No academic year"),
                "why": _("Everything else belongs to a year, so start here."),
                "where": "setup_years",
            }
        )
        return {"year": None, "problems": problems, "ready": False}

    if not year.terms.exists():
        problems.append(
            {
                "what": _("%(year)s has no terms") % {"year": year.name},
                "why": _("Marks are recorded against a term. Somali schools run two."),
                "where": "setup_years",
            }
        )

    if not year.classrooms.exists():
        problems.append(
            {
                "what": _("No classes in %(year)s") % {"year": year.name},
                "why": _("Students are enrolled into a class, and ranked within it."),
                "where": "setup_classes",
            }
        )

    if not institution.subjects.exists():
        problems.append(
            {
                "what": _("No subjects"),
                "why": _("A mark is a mark in a subject."),
                "where": "setup_subjects",
            }
        )

    scales = list(institution.grading_scales.all())
    if not scales:
        problems.append(
            {
                "what": _("No grading scale"),
                "why": _("Without one, a percentage cannot become a letter grade."),
                "where": "setup_scales",
            }
        )
    else:
        if not any(scale.is_default for scale in scales):
            problems.append(
                {
                    "what": _("No default grading scale"),
                    "why": _(
                        "Mark one scale as the default so results know which to use."
                    ),
                    "where": "setup_scales",
                }
            )

        # A gap is the failure this whole screen exists to catch: a
        # student landing in one receives no grade at all, and nothing
        # else in the system notices. One mistyped digit does it.
        for scale in scales:
            gaps = scale.coverage_gaps()
            if gaps:
                problems.append(
                    {
                        "what": _("%(scale)s has a gap") % {"scale": scale.name},
                        "why": _(
                            "Nothing covers %(low)s–%(high)s%%, so a student scoring "
                            "in that range would receive no grade."
                        )
                        % {"low": gaps[0][0], "high": gaps[0][1]},
                        "where": "setup_scales",
                    }
                )

    # Classes that nobody has been assigned to teach. Marks cannot be
    # entered for these at all, and it is invisible from every other
    # screen.
    unstaffed = (
        year.classrooms.annotate(
            staffed=Count(
                "teaching_assignments", filter=Q(teaching_assignments__is_active=True)
            )
        )
        .filter(staffed=0)
        .values_list("name", flat=True)
    )
    if unstaffed:
        problems.append(
            {
                "what": _("No teacher assigned to %(classes)s")
                % {"classes": ", ".join(unstaffed)},
                "why": _(
                    "Nobody can enter marks for a class with no teaching assignment."
                ),
                "where": None,
            }
        )

    return {"year": year, "problems": problems, "ready": not problems}


@admin_required
def setup_overview(request):
    institution = institution_of(request)
    state = readiness(institution)
    year = state["year"]

    return render(
        request,
        "schools/setup_overview.html",
        {
            "nav_active": "setup",
            "institution": institution,
            "state": state,
            "counts": {
                "years": institution.academic_years.count(),
                "terms": Term.objects.filter(academic_year=year).count() if year else 0,
                "classes": year.classrooms.count() if year else 0,
                "subjects": institution.subjects.count(),
                "scales": institution.grading_scales.count(),
            },
        },
    )


# ----------------------------------------------------------------- years


@admin_required
def setup_years(request):
    """Academic years, and the terms inside each one."""
    institution = institution_of(request)
    years = institution.academic_years.prefetch_related("terms").order_by("-start_date")

    form = AcademicYearForm(institution=institution)

    if request.method == "POST":
        form = AcademicYearForm(request.POST, institution=institution)
        if form.is_valid():
            year = form.save(commit=False)
            year.institution = institution
            year.save()
            messages.success(request, _("%(name)s added.") % {"name": year.name})
            return redirect("setup_years")

    return render(
        request,
        "schools/setup_years.html",
        {
            "nav_active": "setup",
            "institution": institution,
            "years": years,
            "form": form,
        },
    )


@admin_required
def setup_terms(request, year_id):
    """The terms of one academic year."""
    institution = institution_of(request)
    year = get_object_or_404(AcademicYear, pk=year_id, institution=institution)

    form = TermForm(institution=institution, year=year)

    if request.method == "POST":
        form = TermForm(request.POST, institution=institution, year=year)
        if form.is_valid():
            term = form.save(commit=False)
            term.academic_year = year
            term.save()
            messages.success(request, _("%(name)s added.") % {"name": term.name})
            return redirect("setup_terms", year_id=year.id)

    return render(
        request,
        "schools/setup_terms.html",
        {
            "nav_active": "setup",
            "institution": institution,
            "year": year,
            "terms": year.terms.order_by("sequence"),
            "form": form,
        },
    )


# --------------------------------------------------------------- classes


@admin_required
def setup_classes(request):
    """Classes in the year the school is working in."""
    institution = institution_of(request)
    year = current_year(institution)

    form = ClassRoomForm(institution=institution, year=year)

    if request.method == "POST":
        if year is None:
            messages.error(request, _("Create an academic year first."))
            return redirect("setup_years")

        form = ClassRoomForm(request.POST, institution=institution, year=year)
        if form.is_valid():
            classroom = form.save(commit=False)
            classroom.academic_year = year
            classroom.save()
            messages.success(request, _("%(name)s added.") % {"name": classroom.name})
            return redirect("setup_classes")

    classrooms = (
        ClassRoom.objects.filter(academic_year=year)
        .annotate(
            students=Count(
                "enrollments", filter=Q(enrollments__is_active=True), distinct=True
            ),
            staff=Count(
                "teaching_assignments",
                filter=Q(teaching_assignments__is_active=True),
                distinct=True,
            ),
        )
        .order_by("name")
        if year
        else []
    )

    return render(
        request,
        "schools/setup_classes.html",
        {
            "nav_active": "setup",
            "institution": institution,
            "year": year,
            "classrooms": classrooms,
            "form": form,
        },
    )


# -------------------------------------------------------------- subjects


@admin_required
def setup_subjects(request):
    institution = institution_of(request)

    form = SubjectForm(institution=institution)

    if request.method == "POST":
        form = SubjectForm(request.POST, institution=institution)
        if form.is_valid():
            subject = form.save(commit=False)
            subject.institution = institution
            subject.save()
            messages.success(request, _("%(name)s added.") % {"name": subject.name})
            return redirect("setup_subjects")

    subjects = institution.subjects.annotate(
        taught=Count(
            "teaching_assignments", filter=Q(teaching_assignments__is_active=True)
        )
    ).order_by("name")

    return render(
        request,
        "schools/setup_subjects.html",
        {
            "nav_active": "setup",
            "institution": institution,
            "subjects": subjects,
            "form": form,
        },
    )


# -------------------------------------------------------- grading scales


@admin_required
def setup_scales(request):
    institution = institution_of(request)

    form = GradingScaleForm(institution=institution)

    if request.method == "POST":
        form = GradingScaleForm(request.POST, institution=institution)
        if form.is_valid():
            scale = form.save(commit=False)
            scale.institution = institution
            scale.save()
            messages.success(request, _("%(name)s added.") % {"name": scale.name})
            return redirect("setup_scale", scale_id=scale.id)

    scales = [
        {"scale": scale, "gaps": scale.coverage_gaps(), "bands": scale.bands.count()}
        for scale in institution.grading_scales.order_by("name")
    ]

    return render(
        request,
        "schools/setup_scales.html",
        {
            "nav_active": "setup",
            "institution": institution,
            "scales": scales,
            "form": form,
        },
    )


@admin_required
def setup_scale(request, scale_id):
    """The bands of one grading scale, and the gaps between them."""
    institution = institution_of(request)
    scale = get_object_or_404(GradingScale, pk=scale_id, institution=institution)

    form = GradeBandForm(institution=institution, scale=scale)

    if request.method == "POST":
        if request.POST.get("action") == "remove":
            return _remove_band(request, scale)

        form = GradeBandForm(request.POST, institution=institution, scale=scale)
        if form.is_valid():
            band = form.save(commit=False)
            band.scale = scale
            band.save()
            messages.success(request, _("%(letter)s added.") % {"letter": band.letter})
            return redirect("setup_scale", scale_id=scale.id)

    return render(
        request,
        "schools/setup_scale.html",
        {
            "nav_active": "setup",
            "institution": institution,
            "scale": scale,
            "bands": scale.bands.order_by("-min_percentage"),
            "gaps": scale.coverage_gaps(),
            "form": form,
        },
    )


def _remove_band(request, scale):
    """Delete one band, re-checked against its own scale.

    Filtered by scale rather than fetched by id: the id comes from a
    form, and a band id from another school's scale would otherwise be
    deleted on request.
    """
    band = GradeBand.objects.filter(pk=request.POST.get("band"), scale=scale).first()

    if band is None:
        messages.error(request, _("That grade band is not part of this scale."))
    else:
        letter = band.letter
        band.delete()
        messages.success(request, _("%(letter)s removed.") % {"letter": letter})

    return redirect("setup_scale", scale_id=scale.id)
