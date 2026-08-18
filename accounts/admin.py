from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from schools.admin_scoping import InstitutionScopedAdmin

from .models import StudentProfile, TeacherProfile, User


@admin.register(StudentProfile)
class StudentProfileAdmin(InstitutionScopedAdmin):
    institution_lookup = "institution"
    related_scoping = {"user": "institution", "institution": "pk"}
    list_display = (
        "full_name",
        "student_username",
        "admission_number",
        "current_class",
        "institution",
        "is_active",
    )
    list_filter = ("institution", "is_active")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "admission_number",
    )
    autocomplete_fields = ("user",)

    @admin.display(description=_("username"), ordering="user__username")
    def student_username(self, obj):
        return obj.user.username

    @admin.display(description=_("current class"))
    def current_class(self, obj):
        enrollment = obj.current_enrollment()
        return enrollment.classroom.name if enrollment else "—"


@admin.register(TeacherProfile)
class TeacherProfileAdmin(InstitutionScopedAdmin):
    institution_lookup = "institution"
    related_scoping = {"user": "institution", "institution": "pk"}
    list_display = ("full_name", "staff_number", "institution", "is_active")
    list_filter = ("institution", "is_active")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)


@admin.register(User)
class UserAdmin(InstitutionScopedAdmin, BaseUserAdmin):
    """Extends Django's UserAdmin so `role` is visible and editable.

    Subclassing rather than replacing keeps Django's password handling —
    the admin never shows or accepts a raw password, and changes go
    through the hashing form.
    """

    institution_lookup = "institution"

    list_display = ("username", "get_full_name", "role", "is_active", "is_staff")
    list_filter = ("role", "institution", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "first_name", "last_name", "email")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "email")}),
        (_("Role"), {"fields": ("role", "institution")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "role", "institution", "password1", "password2"),
            },
        ),
    )

    @admin.display(description=_("name"), ordering="last_name")
    def get_full_name(self, obj):
        return obj.get_full_name() or "—"
