"""Entry points: signing in, and sending each role to the right place."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


@login_required
def dashboard(request):
    """Send each role to its own area.

    A single page that renders three different things depending on who is
    looking is how a template ends up leaking one role's data to another.
    Each role gets its own view instead.
    """
    user = request.user

    if user.is_teacher:
        return redirect("teacher_home")
    if user.is_student:
        return redirect("student_results")
    if user.is_admin:
        return redirect("/admin/")

    # A signed-in account with no usable role. Better to say so than to
    # show an empty page that looks broken.
    return render(request, "accounts/no_role.html", status=403)
