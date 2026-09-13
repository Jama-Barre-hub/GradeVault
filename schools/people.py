"""Creating and enrolling the people a school is made of.

Until now a school could describe itself — years, classes, subjects,
grading — but could not add a single person to it. Teachers and pupils
were created in the Django admin, which meant a head teacher could not
onboard their own staff without the person who runs the deployment. That
is the last thing standing between GradeVault and a real school.

Everything here follows the rules already established in
`schools/setup.py`, with one addition that matters more than the rest:

**Role is decided by the view, never by the request.** A screen that
adds teachers adds teachers. There is no path through this module that
creates an administrator or a superuser, because a head teacher creating
a colleague must not be able to create their own replacement, and an
account's powers must never be a field somebody can post.
"""

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from accounts.models import (
    StudentProfile,
    TeacherProfile,
    User,
    generate_student_username,
)
from accounts.permissions import admin_required
from schools.models import Enrollment, TeachingAssignment
from schools.people_forms import (
    MoveStudentForm,
    StudentForm,
    TeacherForm,
    TeachingAssignmentForm,
    make_password_for_new_account,
)
from schools.setup import current_year, institution_of


def announce_new_account(request, who, username, password):
    """Show the credentials once, for the administrator to hand over.

    The password is displayed rather than emailed because a Somali
    primary school has no email address for a nine-year-old, and a
    credential that cannot be delivered is an account that cannot be
    used. It is shown once and not stored anywhere readable: what the
    database keeps is a hash, which this value cannot be recovered from.
    """
    messages.success(
        request,
        _(
            "%(who)s added. Sign-in name: %(username)s — temporary password: "
            "%(password)s. Write this down now; it cannot be shown again."
        )
        % {"who": who, "username": username, "password": password},
    )


# ------------------------------------------------------------- overview


@admin_required
def people_overview(request):
    institution = institution_of(request)
    year = current_year(institution)

    return render(
        request,
        "schools/people_overview.html",
        {
            "nav_active": "people",
            "institution": institution,
            "year": year,
            "counts": {
                "teachers": TeacherProfile.objects.filter(
                    institution=institution, is_active=True
                ).count(),
                "students": StudentProfile.objects.filter(
                    institution=institution, is_active=True
                ).count(),
                "enrolled": Enrollment.objects.filter(
                    classroom__academic_year=year, is_active=True
                ).count()
                if year
                else 0,
                "assignments": TeachingAssignment.objects.filter(
                    classroom__academic_year=year, is_active=True
                ).count()
                if year
                else 0,
            },
        },
    )


# -------------------------------------------------------------- teachers


@admin_required
def people_teachers(request):
    institution = institution_of(request)
    form = TeacherForm(institution=institution)

    if request.method == "POST":
        form = TeacherForm(request.POST, institution=institution)
        if form.is_valid():
            password = _create_teacher(form, institution)
            announce_new_account(
                request,
                _("Teacher"),
                form.cleaned_data["username"],
                password,
            )
            return redirect("people_teachers")

    teachers = (
        TeacherProfile.objects.filter(institution=institution)
        .select_related("user")
        .annotate(teaches=Count("assignments", filter=Q(assignments__is_active=True)))
        .order_by("user__last_name", "user__first_name")
    )

    return render(
        request,
        "schools/people_teachers.html",
        {
            "nav_active": "people",
            "institution": institution,
            "teachers": teachers,
            "form": form,
        },
    )


@transaction.atomic
def _create_teacher(form, institution):
    """Create the account and its profile together, or neither.

    Atomic because a User without a TeacherProfile is an account that can
    sign in and then be refused by every page — the confusing half-state
    `accounts/permissions.py` raises 403 for.
    """
    first, last = form.full_name()
    password = make_password_for_new_account()

    user = User.objects.create_user(
        username=form.cleaned_data["username"],
        password=password,
        # Set here, not taken from the form. This is the line that stops
        # a head teacher from creating an administrator.
        role=User.Role.TEACHER,
        institution=institution,
        first_name=first,
        last_name=last,
    )
    TeacherProfile.objects.create(
        user=user,
        institution=institution,
        staff_number=form.cleaned_data["staff_number"],
        phone=form.cleaned_data["phone"],
    )
    return password


# -------------------------------------------------------------- students


@admin_required
def people_students(request):
    institution = institution_of(request)
    year = current_year(institution)

    form = StudentForm(institution=institution, year=year)

    if request.method == "POST":
        if year is None:
            messages.error(request, _("Create an academic year first."))
            return redirect("setup_years")

        form = StudentForm(request.POST, institution=institution, year=year)
        if form.is_valid():
            username, password = _create_student(form, institution, year)
            announce_new_account(request, _("Pupil"), username, password)
            return redirect("people_students")

    students = (
        StudentProfile.objects.filter(institution=institution)
        .select_related("user")
        .prefetch_related("enrollments__classroom")
        .order_by("user__last_name", "user__first_name")
    )

    return render(
        request,
        "schools/people_students.html",
        {
            "nav_active": "people",
            "institution": institution,
            "year": year,
            "students": students,
            "form": form,
        },
    )


@transaction.atomic
def _create_student(form, institution, year):
    """Create the pupil, their profile and their enrolment as one act."""
    first, last = form.full_name()
    password = make_password_for_new_account()
    username = generate_student_username(year.start_date.year)

    user = User.objects.create_user(
        username=username,
        password=password,
        role=User.Role.STUDENT,
        institution=institution,
        first_name=first,
        last_name=last,
    )
    student = StudentProfile.objects.create(
        user=user,
        institution=institution,
        admission_number=form.cleaned_data["admission_number"],
        guardian_name=form.cleaned_data["guardian_name"],
        guardian_phone=form.cleaned_data["guardian_phone"],
    )
    Enrollment.objects.create(student=student, classroom=form.cleaned_data["classroom"])
    return username, password


@admin_required
def move_student(request, student_id):
    """Move a pupil to another class in the same year."""
    institution = institution_of(request)
    year = current_year(institution)

    # Re-filtered by institution: the id arrives in a URL.
    student = get_object_or_404(StudentProfile, pk=student_id, institution=institution)
    enrollment = student.current_enrollment()

    if request.method == "POST" and enrollment is not None:
        form = MoveStudentForm(request.POST, year=year, exclude=enrollment.classroom)
        if form.is_valid():
            _move(student, enrollment, form.cleaned_data["classroom"])
            messages.success(
                request,
                _("%(name)s moved to %(classroom)s.")
                % {
                    "name": student.full_name,
                    "classroom": form.cleaned_data["classroom"].name,
                },
            )
            return redirect("people_students")
    else:
        form = MoveStudentForm(
            year=year, exclude=enrollment.classroom if enrollment else None
        )

    return render(
        request,
        "schools/move_student.html",
        {
            "nav_active": "people",
            "institution": institution,
            "student": student,
            "enrollment": enrollment,
            "form": form,
        },
    )


@transaction.atomic
def _move(student, enrollment, classroom):
    """Close the old enrolment and open a new one.

    The old row is deactivated rather than deleted. A child who changed
    class in February still sat Term 1 in the class they were in, and
    deleting that enrolment would detach a term of real marks from the
    class they were earned in — rewriting history to tidy the present.
    """
    enrollment.is_active = False
    enrollment.save(update_fields=["is_active"])
    Enrollment.objects.create(student=student, classroom=classroom)


# ---------------------------------------------------------- who teaches


@admin_required
def people_teaching(request):
    """Which teacher takes which subject in which class."""
    institution = institution_of(request)
    year = current_year(institution)

    form = TeachingAssignmentForm(institution=institution, year=year)

    if request.method == "POST":
        if request.POST.get("action") == "remove":
            return _remove_assignment(request, year)

        form = TeachingAssignmentForm(request.POST, institution=institution, year=year)
        if form.is_valid():
            TeachingAssignment.objects.create(
                teacher=form.cleaned_data["teacher"],
                subject=form.cleaned_data["subject"],
                classroom=form.cleaned_data["classroom"],
            )
            messages.success(request, _("Teaching assignment added."))
            return redirect("people_teaching")

    assignments = (
        TeachingAssignment.objects.filter(classroom__academic_year=year, is_active=True)
        .select_related("teacher__user", "subject", "classroom")
        .order_by("classroom__name", "subject__name")
        if year
        else []
    )

    return render(
        request,
        "schools/people_teaching.html",
        {
            "nav_active": "people",
            "institution": institution,
            "year": year,
            "assignments": assignments,
            "form": form,
        },
    )


def _remove_assignment(request, year):
    """Withdraw one assignment, re-checked against this school's year.

    Filtered by the year rather than fetched by id, for the same reason
    every other id in this project is: it arrives in a form, and a form
    contains whatever the person sending it decided to put in it.
    """
    assignment = TeachingAssignment.objects.filter(
        pk=request.POST.get("assignment"), classroom__academic_year=year
    ).first()

    if assignment is None:
        messages.error(request, _("That assignment is not one of your school's."))
    else:
        assignment.delete()
        messages.success(request, _("Teaching assignment removed."))

    return redirect("people_teaching")
