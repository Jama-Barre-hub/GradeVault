"""User accounts and roles.

GradeVault uses a single User model with a role field rather than three
separate models. Every person who signs in is a User; the role decides
what they may do.

The role is deliberately *not* enforced here. Models describe data;
permission rules live in the views and are proved by tests. Putting
access control in two places is how the two versions drift apart.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


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
