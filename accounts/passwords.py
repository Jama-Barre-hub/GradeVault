"""Changing and resetting passwords.

Django ships a password reset flow and GradeVault does not use it,
because that flow sends an email and this system has no email address to
send to. A Somali primary school does not hold an inbox for a nine-year-
old, and a good proportion of the staff will not have one either. A
reset link that cannot be delivered is a reset that cannot happen, and an
account nobody can recover is an account that gets shared instead — which
is how a teacher ends up marking under a colleague's name.

So there are two routes, and neither involves email.

**Anyone can change their own password**, by proving they know the
current one. This is the route a person who simply wants a better
password takes, and it is the only route that does not require somebody
else's involvement.

**An administrator can reset a password they do not know**, for someone
at their own school, and is handed a new temporary one to pass on. This
is the route for a child who has forgotten theirs, which in a primary
school is the common case rather than the exception.

An administrator resetting a password cannot read the old one — nothing
can, because only a hash is stored. What they can do is replace it, and
that is worth recording, so every reset writes an audit entry naming
who did it and whose account it was.
"""

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from accounts.models import User
from accounts.permissions import admin_required
from audit.models import AuditLog
from schools.people_forms import make_password_for_new_account
from schools.setup import institution_of


@login_required
def change_my_password(request):
    """Change your own password, having proved you know the current one.

    Django's own form is used rather than a hand-written one. It checks
    the old password, confirms the new one twice and runs every validator
    configured in settings — including the list of common passwords,
    which is the check most likely to catch a real mistake here.
    """
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()

            # Changing a password rotates the session hash, which would
            # otherwise sign the person out of the browser they are
            # standing at — a confusing end to a successful action.
            update_session_auth_hash(request, form.user)

            messages.success(request, _("Your password has been changed."))
            return redirect("dashboard")
    else:
        form = PasswordChangeForm(user=request.user)

    return render(
        request,
        "accounts/change_password.html",
        {"form": form, "nav_active": "password"},
    )


@admin_required
def reset_password(request, user_id):
    """Give someone at your school a new temporary password.

    Scoped to the administrator's own institution, and refusing any
    account that is not a teacher or a pupil. Without the second check an
    administrator could reset a colleague administrator's password — or,
    worse, a superuser's — and take over an account that outranks their
    own. Resetting a password is taking control of an account, so it may
    only ever point downwards.
    """
    institution = institution_of(request)

    person = get_object_or_404(
        User,
        pk=user_id,
        institution=institution,
        role__in=[User.Role.TEACHER, User.Role.STUDENT],
    )

    if request.method != "POST":
        return render(
            request,
            "accounts/confirm_reset.html",
            {"person": person, "nav_active": "people"},
        )

    password = make_password_for_new_account()
    person.set_password(password)
    person.save(update_fields=["password"])

    AuditLog.record_password_reset(
        person=person, actor=request.user, institution=institution
    )

    messages.success(
        request,
        _(
            "New password for %(name)s (%(username)s): %(password)s — "
            "write this down now; it cannot be shown again."
        )
        % {
            "name": person.get_full_name() or person.username,
            "username": person.username,
            "password": password,
        },
    )
    return redirect("people_students" if person.is_student else "people_teachers")
