"""User accounts and roles.

GradeVault uses a single User model with a role field rather than three
separate models. Every person who signs in is a User; the role decides
what they may do.

The role is deliberately *not* enforced here. Models describe data;
permission rules live in the views and are proved by tests. Putting
access control in two places is how the two versions drift apart.
"""

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """Ensures a superuser is always given the administrator role.

    `createsuperuser` only prompts for USERNAME_FIELD and REQUIRED_FIELDS,
    so without this a superuser would be created with an empty role and
    fail every is_admin check.
    """

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", self.model.Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """A person who can sign in to GradeVault.

    `username` is inherited from AbstractUser and is the unique identifier
    a student uses to sign in, e.g. "STU-2026-0142".
    """

    class Role(models.TextChoices):
        ADMIN = "admin", _("Administrator")
        TEACHER = "teacher", _("Teacher")
        STUDENT = "student", _("Student")

    role = models.CharField(
        _("role"),
        max_length=20,
        choices=Role.choices,
        help_text=_("Decides what this person may see and do."),
    )

    # Students in primary school may have no email address at all, so this
    # must never be required. It stays optional for every role.
    email = models.EmailField(_("email address"), blank=True)

    objects = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["last_name", "first_name", "username"]

    def __str__(self):
        full_name = self.get_full_name()
        return f"{full_name} ({self.username})" if full_name else self.username

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    @property
    def is_teacher(self) -> bool:
        return self.role == self.Role.TEACHER

    @property
    def is_student(self) -> bool:
        return self.role == self.Role.STUDENT


def generate_student_username(entry_year: int) -> str:
    """Build the next unused student username, e.g. STU-2026-0142.

    Students are identified by this rather than by email, because most
    Somali school students have no email address. The year makes the
    identifier readable and keeps numbering restarting each intake.

    Uniqueness is enforced by the database, not by this function. Callers
    save inside a retry loop, because two admissions created at the same
    moment could otherwise compute the same number.
    """
    prefix = f"STU-{entry_year}-"

    last = (
        User.objects.filter(username__startswith=prefix)
        .order_by("-username")
        .values_list("username", flat=True)
        .first()
    )

    next_number = 1
    if last:
        try:
            next_number = int(last.removeprefix(prefix)) + 1
        except ValueError:
            # A hand-edited username that does not end in digits should
            # not stop the next admission.
            next_number = User.objects.filter(username__startswith=prefix).count() + 1

    return f"{prefix}{next_number:04d}"


class StudentProfile(models.Model):
    """School-specific details for a student.

    Deliberately minimal. These are records about children, so the model
    holds only what producing a result actually requires. Date of birth,
    photographs and addresses are not stored: nothing in GradeVault needs
    them, and data that is never collected cannot leak.
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="student_profile"
    )
    institution = models.ForeignKey(
        "schools.Institution", on_delete=models.CASCADE, related_name="students"
    )
    admission_number = models.CharField(
        _("admission number"),
        max_length=30,
        help_text=_("The school's own reference for this student."),
    )
    guardian_name = models.CharField(_("guardian name"), max_length=150, blank=True)
    guardian_phone = models.CharField(_("guardian phone"), max_length=40, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("student")
        verbose_name_plural = _("students")
        ordering = ["user__last_name", "user__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "admission_number"],
                name="unique_admission_number_per_institution",
            ),
        ]

    def __str__(self):
        return (
            f"{self.user.get_full_name() or self.user.username} ({self.user.username})"
        )

    @property
    def full_name(self) -> str:
        return self.user.get_full_name() or self.user.username

    def current_enrollment(self):
        """The student's active class, or None."""
        return (
            self.enrollments.filter(is_active=True).select_related("classroom").first()
        )


class TeacherProfile(models.Model):
    """School-specific details for a teacher."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="teacher_profile"
    )
    institution = models.ForeignKey(
        "schools.Institution", on_delete=models.CASCADE, related_name="teachers"
    )
    staff_number = models.CharField(_("staff number"), max_length=30, blank=True)
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("teacher")
        verbose_name_plural = _("teachers")
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    @property
    def full_name(self) -> str:
        return self.user.get_full_name() or self.user.username

    def teaches(self, subject, classroom) -> bool:
        """Whether this teacher may record marks for this subject and class.

        This is the single source of truth for the rule that a teacher
        may only mark subjects they actually teach. Views ask this
        question; they never reimplement the answer.
        """
        return self.assignments.filter(
            subject=subject, classroom=classroom, is_active=True
        ).exists()
