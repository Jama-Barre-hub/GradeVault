from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from schools.admin_scoping import InstitutionScopedAdmin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(InstitutionScopedAdmin):
    institution_lookup = "institution"
    """A reader for the audit trail. Deliberately read-only.

    Django's admin is the most likely place an administrator would try to
    tidy up an inconvenient entry, so every write path is closed here as
    well as on the model. An audit log an administrator can edit proves
    nothing.
    """

    list_display = (
        "created_at",
        "action",
        "actor_label",
        "student_label",
        "subject_label",
        "change",
    )
    list_filter = ("action", "created_at", "classroom_label", "subject_label")
    search_fields = ("actor_label", "student_label", "subject_label", "term_label")
    date_hierarchy = "created_at"

    readonly_fields = tuple(field.name for field in AuditLog._meta.fields)

    @admin.display(description=_("change"))
    def change(self, obj):
        if not obj.old_value and not obj.new_value:
            return "—"
        return f"{obj.old_value or '—'} → {obj.new_value or '—'}"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
