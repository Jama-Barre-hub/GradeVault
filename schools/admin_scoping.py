"""Restricting the admin to one school's data.

GradeVault is meant for many Somali schools in one deployment, so an
administrator at one school must never read, edit or even see the
existence of another school's records.

Every model reaches its Institution by a different path — a Score
through its enrolment, class and year; a Subject directly — so each
admin declares its own lookup and the filtering itself is written once.
Writing the filter out in each admin is how one gets forgotten, and the
forgotten one is the leak.

Two deliberate rules:

**Missing means nothing, not everything.** An account with no
institution sees an empty list rather than the whole database, so an
administrator created without a school fails closed.

**Dropdowns are filtered too.** Restricting the list while leaving the
foreign-key pickers unfiltered would still let one school attach its
records to another's classes, and leak their names in the process.
"""

from django.contrib import admin


class InstitutionScopedAdmin(admin.ModelAdmin):
    """Shows only rows belonging to the signed-in user's school.

    Subclasses set `institution_lookup` to the query path from their
    model to Institution, and `related_scoping` to the same for any
    foreign key whose dropdown must also be filtered.
    """

    institution_lookup = "institution"
    related_scoping: dict[str, str] = {}

    def _institution_id(self, request):
        return getattr(request.user, "institution_id", None)

    def _is_operator(self, request) -> bool:
        """Superusers run the service and legitimately see every school."""
        return request.user.is_superuser

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if self._is_operator(request):
            return queryset

        institution_id = self._institution_id(request)
        if institution_id is None:
            return queryset.none()

        return queryset.filter(**{self.institution_lookup: institution_id})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Keep other schools out of the dropdowns as well as the lists."""
        lookup = self.related_scoping.get(db_field.name)

        if lookup and not self._is_operator(request):
            institution_id = self._institution_id(request)
            queryset = db_field.remote_field.model._default_manager.all()
            kwargs["queryset"] = (
                queryset.filter(**{lookup: institution_id})
                if institution_id is not None
                else queryset.none()
            )

        return super().formfield_for_foreignkey(db_field, request, **kwargs)
