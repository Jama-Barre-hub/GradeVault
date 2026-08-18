"""Access rules for views.

Every rule lives here rather than being written out in each view. A
permission check copied into ten places is a permission check that will
be wrong in one of them, and the one that is wrong is the one nobody
notices until a student sees another student's marks.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from accounts.models import User


def role_required(*roles):
    """Allow only the listed roles through.

    Anonymous visitors are sent to the login page. A signed-in user with
    the wrong role gets 403 rather than a redirect: they are not
    unauthenticated, they are simply not allowed, and bouncing them to a
    login form they have already passed would be misleading.
    """

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied("This page is not available for your role.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


admin_required = role_required(User.Role.ADMIN)
teacher_required = role_required(User.Role.TEACHER)
student_required = role_required(User.Role.STUDENT)


def teacher_profile(request):
    """The signed-in teacher's profile, or 403 if they have none."""
    profile = getattr(request.user, "teacher_profile", None)
    if profile is None or not profile.is_active:
        raise PermissionDenied("No active teacher record for this account.")
    return profile


def student_profile(request):
    """The signed-in student's profile, or 403 if they have none."""
    profile = getattr(request.user, "student_profile", None)
    if profile is None or not profile.is_active:
        raise PermissionDenied("No active student record for this account.")
    return profile


def require_teaches(teacher, subject, classroom):
    """Refuse a teacher marking a subject they do not teach.

    This is the rule the whole project exists to enforce, so it is asked
    of TeacherProfile.teaches() rather than reimplemented here. One
    source of truth cannot disagree with itself.
    """
    if not teacher.teaches(subject, classroom):
        raise PermissionDenied(f"You do not teach {subject} to {classroom.name}.")
