from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    AcademicYear,
    ClassRoom,
    GradeBand,
    GradingScale,
    Institution,
    Subject,
    Term,
)


class TermInline(admin.TabularInline):
    model = Term
    extra = 0
    fields = ("name", "sequence", "start_date", "end_date", "is_published")


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "short_name")


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("name", "institution", "start_date", "end_date", "is_current")
    list_filter = ("institution", "is_current")
    search_fields = ("name",)
    inlines = [TermInline]


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
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
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "institution")
    list_filter = ("institution",)
    search_fields = ("name", "code")


@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ("name", "academic_year", "class_teacher")
    list_filter = ("academic_year",)
    search_fields = ("name",)


class GradeBandInline(admin.TabularInline):
    model = GradeBand
    extra = 0
    fields = ("letter", "min_percentage", "max_percentage", "remark", "points")


@admin.register(GradingScale)
class GradingScaleAdmin(admin.ModelAdmin):
    list_display = ("name", "institution", "is_default")
    list_filter = ("institution", "is_default")
    inlines = [GradeBandInline]
