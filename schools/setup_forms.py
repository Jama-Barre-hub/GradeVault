"""Forms for a school setting itself up.

Until now this was all done in the Django admin, which validates against
the database constraints and reports what it finds in the language of the
schema. "Duplicate key value violates unique constraint
unique_subject_per_institution" is a true statement and a useless one to
a head teacher.

So these forms check the same rules a little earlier and say what they
mean: which field is wrong, and what to do about it.

Two rules run through all of them.

**The institution is never a form field.** It comes from the signed-in
user, so a posted form cannot attach one school's class to another
school's year. Every uniqueness check is scoped to that institution for
the same reason: two schools may both have a "Form 2A", and only a check
that knows whose school it is can tell that apart from a duplicate.

**Names are compared case-insensitively.** The database constraints are
case-sensitive, so "Mathematics" and "mathematics" would both be
accepted and would then appear as two subjects on every report card.
Being stricter than the constraint is deliberate.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from schools.models import (
    AcademicYear,
    ClassRoom,
    GradeBand,
    GradingScale,
    Subject,
    Term,
)

DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ScopedForm(forms.ModelForm):
    """A form that knows which school it is editing for."""

    def __init__(self, *args, institution=None, **kwargs):
        self.institution = institution
        super().__init__(*args, **kwargs)

    def reject_duplicate(self, siblings, field, message):
        """Refuse a name already used by a sibling row.

        Compared with `iexact` rather than `exact`: the database
        constraint is case-sensitive, so without this a school could hold
        both "Mathematics" and "mathematics" and see them as two separate
        subjects for the rest of the year.
        """
        value = self.cleaned_data.get(field)
        if not value:
            return

        clash = siblings.filter(**{f"{field}__iexact": value})
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)

        if clash.exists():
            self.add_error(field, message)


class AcademicYearForm(ScopedForm):
    class Meta:
        model = AcademicYear
        fields = ["name", "start_date", "end_date", "is_current"]
        widgets = {"start_date": DATE_INPUT, "end_date": DATE_INPUT}
        labels = {"is_current": _("This is the year we are working in")}

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")

        if start and end and end <= start:
            self.add_error("end_date", _("The year must end after it starts."))

        self.reject_duplicate(
            AcademicYear.objects.filter(institution=self.institution),
            "name",
            _("Your school already has a year with this name."),
        )
        return cleaned


class TermForm(ScopedForm):
    """A term inside one academic year."""

    def __init__(self, *args, year=None, **kwargs):
        self.year = year
        super().__init__(*args, **kwargs)

    class Meta:
        model = Term
        fields = ["name", "sequence", "start_date", "end_date"]
        widgets = {"start_date": DATE_INPUT, "end_date": DATE_INPUT}
        help_texts = {"sequence": _("1 for the first term, 2 for the second.")}

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")

        if start and end and end <= start:
            self.add_error("end_date", _("The term must end after it starts."))

        # A term outside its own year is not a typo the database would
        # catch, and it puts marks in a term that the year they belong to
        # does not contain. The second term legitimately ends in the same
        # month the year does, so the comparison is inclusive.
        if self.year:
            if start and start < self.year.start_date:
                self.add_error(
                    "start_date",
                    _("The term cannot start before %(year)s does, on %(date)s.")
                    % {"year": self.year.name, "date": self.year.start_date},
                )
            if end and end > self.year.end_date:
                self.add_error(
                    "end_date",
                    _("The term cannot end after %(year)s does, on %(date)s.")
                    % {"year": self.year.name, "date": self.year.end_date},
                )

            siblings = Term.objects.filter(academic_year=self.year)
            self.reject_duplicate(
                siblings, "name", _("This year already has a term with this name.")
            )

            sequence = cleaned.get("sequence")
            if sequence is not None:
                clash = siblings.filter(sequence=sequence)
                if self.instance.pk:
                    clash = clash.exclude(pk=self.instance.pk)
                if clash.exists():
                    self.add_error(
                        "sequence",
                        _("Term %(n)s already exists in this year.") % {"n": sequence},
                    )

        return cleaned


class ClassRoomForm(ScopedForm):
    """A class group, which always belongs to one academic year."""

    def __init__(self, *args, year=None, **kwargs):
        self.year = year
        super().__init__(*args, **kwargs)

    class Meta:
        model = ClassRoom
        fields = ["name"]
        help_texts = {
            "name": _('Whatever your school calls it — "Class 5", "Form 2A".')
        }

    def clean(self):
        cleaned = super().clean()
        if self.year:
            self.reject_duplicate(
                ClassRoom.objects.filter(academic_year=self.year),
                "name",
                _("This year already has a class with this name."),
            )
        return cleaned


class SubjectForm(ScopedForm):
    class Meta:
        model = Subject
        fields = ["name", "code"]
        help_texts = {"code": _("Optional. A short form used where space is tight.")}

    def clean(self):
        cleaned = super().clean()
        self.reject_duplicate(
            Subject.objects.filter(institution=self.institution),
            "name",
            _("Your school already teaches a subject with this name."),
        )
        return cleaned


class GradingScaleForm(ScopedForm):
    class Meta:
        model = GradingScale
        fields = ["name", "is_default"]
        labels = {"is_default": _("Use this scale by default")}

    def clean(self):
        cleaned = super().clean()
        self.reject_duplicate(
            GradingScale.objects.filter(institution=self.institution),
            "name",
            _("Your school already has a scale with this name."),
        )
        return cleaned


class GradeBandForm(ScopedForm):
    """One row of a grading scale: a letter and the range it covers."""

    def __init__(self, *args, scale=None, **kwargs):
        self.scale = scale
        super().__init__(*args, **kwargs)

    class Meta:
        model = GradeBand
        fields = ["letter", "min_percentage", "max_percentage", "remark"]
        labels = {
            "min_percentage": _("From (%)"),
            "max_percentage": _("To (%)"),
        }

    def clean(self):
        cleaned = super().clean()
        low = cleaned.get("min_percentage")
        high = cleaned.get("max_percentage")

        if low is not None and high is not None and high < low:
            self.add_error(
                "max_percentage", _("The top of the band cannot be below the bottom.")
            )

        if self.scale:
            self.reject_duplicate(
                GradeBand.objects.filter(scale=self.scale),
                "letter",
                _("This scale already has a band with this letter."),
            )

            # An overlap is worse than a gap. A gap leaves a student with
            # no grade, which is visibly wrong; an overlap silently gives
            # two answers, and which one a student receives depends on
            # row order rather than on the school's intention.
            if low is not None and high is not None:
                overlapping = GradeBand.objects.filter(
                    scale=self.scale, min_percentage__lte=high, max_percentage__gte=low
                )
                if self.instance.pk:
                    overlapping = overlapping.exclude(pk=self.instance.pk)

                clash = overlapping.first()
                if clash:
                    self.add_error(
                        None,
                        _("This overlaps %(letter)s, which covers %(low)s–%(high)s.")
                        % {
                            "letter": clash.letter,
                            "low": clash.min_percentage,
                            "high": clash.max_percentage,
                        },
                    )

        return cleaned
