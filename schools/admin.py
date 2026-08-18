from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from schools.admin_scoping import InstitutionScopedAdmin

from .models import (
    AcademicYear,
    Assessment,
    ClassRoom,
    Enrollment,
    GradeBand,
    GradingScale,
    Institution,
    Score,
    Subject,
    TeachingAssignment,
    Term,
)


@admin.register(Enrollment)
class EnrollmentAdmin(InstitutionScopedAdmin):
    institution_lookup = "classroom__academic_year__institution"
    related_scoping = {
        "student": "institution",
        "classroom": "academic_year__institution",
    }
    list_display = ("student", "classroom", "roll_number", "is_active")
    list_filter = ("classroom__academic_year", "classroom", "is_active")
    search_fields = ("student__user__username", "student__user__last_name")
    autocomplete_fields = ("student", "classroom")


@admin.register(TeachingAssignment)
class TeachingAssignmentAdmin(InstitutionScopedAdmin):
    institution_lookup = "classroom__academic_year__institution"
    related_scoping = {
        "teacher": "institution",
        "subject": "institution",
        "classroom": "academic_year__institution",
    }
    list_display = ("teacher", "subject", "classroom", "is_active")
    list_filter = ("classroom__academic_year", "subject", "classroom", "is_active")
    search_fields = ("teacher__user__last_name", "subject__name")
    autocomplete_fields = ("teacher", "subject", "classroom")


@admin.register(Assessment)
class AssessmentAdmin(InstitutionScopedAdmin):
    institution_lookup = "classroom__academic_year__institution"
    related_scoping = {
        "subject": "institution",
        "classroom": "academic_year__institution",
        "term": "academic_year__institution",
    }
    list_display = (
        "name",
        "subject",
        "classroom",
        "term",
        "max_marks",
        "subject_total",
    )
    list_filter = ("term", "classroom", "subject")
    search_fields = ("name", "subject__name")
    autocomplete_fields = ("subject", "classroom")

    @admin.display(description=_("subject total"))
    def subject_total(self, obj):
        """Show the marks available across the whole subject, and flag it
        when they do not add up to 100."""
        total = obj.siblings_total
        if total == 100:
            return _("%(total)s — complete") % {"total": total}
        return format_html(
            '<span style="color:#ba2121;font-weight:bold;">{}</span>',
            _("%(total)s of 100") % {"total": total},
        )


@admin.register(Score)
class ScoreAdmin(InstitutionScopedAdmin):
    institution_lookup = "enrollment__classroom__academic_year__institution"
    related_scoping = {
        "enrollment": "classroom__academic_year__institution",
        "assessment": "classroom__academic_year__institution",
    }
    list_display = ("student_name", "assessment", "marks", "recorded_by")
    list_filter = ("assessment__term", "assessment__classroom", "assessment__subject")
    search_fields = (
        "enrollment__student__user__username",
        "enrollment__student__user__last_name",
    )
    autocomplete_fields = ("enrollment", "assessment")
    readonly_fields = ("recorded_by",)

    @admin.display(description=_("student"))
    def student_name(self, obj):
        return obj.enrollment.student.full_name

    def save_model(self, request, obj, form, change):
        """Record who entered the mark, rather than trusting a form field."""
        obj.recorded_by = request.user
        super().save_model(request, obj, form, change)


class TermInline(admin.TabularInline):
    model = Term
    extra = 0
    fields = ("name", "sequence", "start_date", "end_date", "is_published")


@admin.register(Institution)
class InstitutionAdmin(InstitutionScopedAdmin):
    institution_lookup = "pk"
    list_display = ("name", "short_name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "short_name")


@admin.register(AcademicYear)
class AcademicYearAdmin(InstitutionScopedAdmin):
    institution_lookup = "institution"
    related_scoping = {
        "institution": "pk",
    }
    list_display = ("name", "institution", "start_date", "end_date", "is_current")
    list_filter = ("institution", "is_current")
    search_fields = ("name",)
    inlines = [TermInline]


@admin.register(Term)
class TermAdmin(InstitutionScopedAdmin):
    institution_lookup = "academic_year__institution"
    related_scoping = {
        "academic_year": "institution",
    }
    list_display = (
        "name",
        "academic_year",
        "sequence",
        "start_date",
        "end_date",
        "is_published",
        "published_at",
    )
    list_filter = ("is_published", "academic_year")

    # Publication is recorded automatically by Term.publish(); editing these
    # by hand would let the record disagree with what actually happened.
    readonly_fields = ("published_at", "published_by")

    actions = ["publish_results", "unpublish_results"]

    @admin.action(description=_("Publish results to students"))
    def publish_results(self, request, queryset):
        for term in queryset:
            term.publish(released_by=request.user)
        self.message_user(
            request, _("Results published for %d term(s).") % len(queryset)
        )

    @admin.action(description=_("Withdraw results from students"))
    def unpublish_results(self, request, queryset):
        for term in queryset:
            term.unpublish()
        self.message_user(
            request, _("Results withdrawn for %d term(s).") % len(queryset)
        )


@admin.register(Subject)
class SubjectAdmin(InstitutionScopedAdmin):
    institution_lookup = "institution"
    related_scoping = {
        "institution": "pk",
    }
    list_display = ("name", "code", "institution")
    list_filter = ("institution",)
    search_fields = ("name", "code")


@admin.register(ClassRoom)
class ClassRoomAdmin(InstitutionScopedAdmin):
    institution_lookup = "academic_year__institution"
    related_scoping = {
        "academic_year": "institution",
        "class_teacher": "institution",
    }
    list_display = ("name", "academic_year", "class_teacher")
    list_filter = ("academic_year",)
    search_fields = ("name",)


class GradeBandInline(admin.TabularInline):
    model = GradeBand
    extra = 0
    fields = ("letter", "min_percentage", "max_percentage", "remark", "points")


@admin.register(GradingScale)
class GradingScaleAdmin(InstitutionScopedAdmin):
    institution_lookup = "institution"
    related_scoping = {
        "institution": "pk",
    }
    list_display = ("name", "institution", "is_default", "coverage")
    list_filter = ("institution", "is_default")
    inlines = [GradeBandInline]

    @admin.display(description=_("coverage"))
    def coverage(self, obj):
        """Warn in the list when a scale would leave students ungraded."""
        gaps = obj.coverage_gaps()
        if not gaps:
            return _("Complete")

        ranges = ", ".join(f"{low}–{high}%" for low, high in gaps)
        return format_html(
            '<span style="color:#ba2121;font-weight:bold;">{}</span>',
            _("No grade for %(ranges)s") % {"ranges": ranges},
        )

    def response_change(self, request, obj):
        """Tell the administrator immediately if a saved scale has gaps."""
        self._warn_about_gaps(request, obj)
        return super().response_change(request, obj)

    def response_add(self, request, obj, post_url_continue=None):
        self._warn_about_gaps(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def _warn_about_gaps(self, request, obj):
        gaps = obj.coverage_gaps()
        if not gaps:
            return

        ranges = ", ".join(f"{low}–{high}%" for low, high in gaps)
        messages.warning(
            request,
            _(
                "This scale has no grade for %(ranges)s. Students scoring in "
                "that range will receive a blank grade."
            )
            % {"ranges": ranges},
        )
