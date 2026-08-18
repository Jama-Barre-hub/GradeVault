"""The structure of a school: years, terms, classes, subjects and grading.

Everything here hangs off an Institution. GradeVault runs a single school
today, but the key is present on every table from the first migration, so
adding a second school later is an extension rather than a rewrite.

See PROPOSAL.md §10 for why each decision was made.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    """Records when a row was created and last changed."""

    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class Institution(TimeStampedModel):
    """A school. Every other record belongs to one."""

    name = models.CharField(_("name"), max_length=200)
    short_name = models.CharField(
        _("short name"),
        max_length=30,
        help_text=_("Used on report cards where space is limited."),
    )
    address = models.CharField(_("address"), max_length=255, blank=True)
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    email = models.EmailField(_("email"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("institution")
        verbose_name_plural = _("institutions")
        ordering = ["name"]

    def __str__(self):
        return self.name


class AcademicYear(TimeStampedModel):
    """One school year, e.g. 2026/2027."""

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="academic_years"
    )
    name = models.CharField(_("name"), max_length=20, help_text=_("e.g. 2026/2027"))
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    is_current = models.BooleanField(
        _("current year"),
        default=False,
        help_text=_("The year new work defaults to. Only one may be current."),
    )

    class Meta:
        verbose_name = _("academic year")
        verbose_name_plural = _("academic years")
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "name"], name="unique_year_name_per_institution"
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Only one year per institution may be current.
        if self.is_current:
            AcademicYear.objects.filter(institution=self.institution).exclude(
                pk=self.pk
            ).update(is_current=False)

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({"end_date": _("The year must end after it starts.")})


class Term(TimeStampedModel):
    """One of the two terms in a year.

    Somali schools run two terms: September to mid-January, and early
    February to June (PROPOSAL.md §10.1).

    `is_published` is the gate between a teacher entering a mark and a
    student seeing it. Nothing is visible to students until an
    administrator publishes the term (§10.5).
    """

    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="terms"
    )
    name = models.CharField(_("name"), max_length=40, help_text=_("e.g. Term 1"))
    sequence = models.PositiveSmallIntegerField(
        _("sequence"), help_text=_("1 for the first term, 2 for the second.")
    )
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))

    is_published = models.BooleanField(
        _("results published"),
        default=False,
        help_text=_("While unpublished, students cannot see any result for this term."),
    )
    published_at = models.DateTimeField(_("published at"), null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_terms",
    )

    class Meta:
        verbose_name = _("term")
        verbose_name_plural = _("terms")
        ordering = ["academic_year", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "sequence"], name="unique_term_sequence"
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.academic_year}"

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({"end_date": _("The term must end after it starts.")})

    def publish(self, released_by):
        """Release results to students. Recorded, never silent."""
        self.is_published = True
        self.published_at = timezone.now()
        self.published_by = released_by
        self.save(update_fields=["is_published", "published_at", "published_by"])

    def unpublish(self):
        """Withdraw results, e.g. when a mark is found to be wrong."""
        self.is_published = False
        self.save(update_fields=["is_published"])


class Subject(TimeStampedModel):
    """A subject taught at the institution, e.g. Mathematics."""

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="subjects"
    )
    name = models.CharField(_("name"), max_length=100)
    code = models.CharField(_("code"), max_length=20, blank=True)

    class Meta:
        verbose_name = _("subject")
        verbose_name_plural = _("subjects")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "name"], name="unique_subject_per_institution"
            ),
        ]

    def __str__(self):
        return self.name


class ClassRoom(TimeStampedModel):
    """A class group within one academic year.

    The name is free text because Somali schools differ: primary schools
    use "Class 1" to "Class 8", secondary schools use "Form 1" to
    "Form 4" or "9" to "12". There is no national convention to encode,
    so GradeVault stores whatever the school types (§10.6).

    A class belongs to a single academic year. "Class 5" in 2026/2027
    and "Class 5" in 2027/2028 are different groups of students, and
    keeping them separate is what makes class rank meaningful.
    """

    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="classrooms"
    )
    name = models.CharField(
        _("name"), max_length=50, help_text=_('e.g. "Class 5" or "Form 2A"')
    )
    class_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classes_supervised",
    )

    class Meta:
        verbose_name = _("class")
        verbose_name_plural = _("classes")
        ordering = ["academic_year", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "name"], name="unique_class_name_per_year"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.academic_year})"

    @property
    def institution(self):
        return self.academic_year.institution


class GradingScale(TimeStampedModel):
    """How a percentage becomes a letter grade.

    Each Somali school sets its own boundaries, so this is data the
    school configures, never a rule in code (§10.3).
    """

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="grading_scales"
    )
    name = models.CharField(_("name"), max_length=100)
    is_default = models.BooleanField(_("default scale"), default=False)

    class Meta:
        verbose_name = _("grading scale")
        verbose_name_plural = _("grading scales")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "name"], name="unique_scale_name_per_institution"
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            GradingScale.objects.filter(institution=self.institution).exclude(
                pk=self.pk
            ).update(is_default=False)

    def grade_for(self, percentage):
        """Return the GradeBand a percentage falls into, or None."""
        return self.bands.filter(
            min_percentage__lte=percentage, max_percentage__gte=percentage
        ).first()


class GradeBand(models.Model):
    """One row of a grading scale, e.g. A = 80–100."""

    scale = models.ForeignKey(
        GradingScale, on_delete=models.CASCADE, related_name="bands"
    )
    letter = models.CharField(_("letter"), max_length=5)
    min_percentage = models.DecimalField(
        _("minimum percentage"),
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    max_percentage = models.DecimalField(
        _("maximum percentage"),
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    remark = models.CharField(
        _("remark"), max_length=100, blank=True, help_text=_('e.g. "Excellent"')
    )
    points = models.DecimalField(
        _("points"),
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Reserved for GPA calculation. Not used in v1."),
    )

    class Meta:
        verbose_name = _("grade band")
        verbose_name_plural = _("grade bands")
        ordering = ["-min_percentage"]
        constraints = [
            models.UniqueConstraint(
                fields=["scale", "letter"], name="unique_letter_per_scale"
            ),
            models.CheckConstraint(
                condition=models.Q(max_percentage__gte=models.F("min_percentage")),
                name="grade_band_max_not_below_min",
            ),
        ]

    def __str__(self):
        return f"{self.letter} ({self.min_percentage}–{self.max_percentage}%)"

    def clean(self):
        """Reject a band that overlaps another in the same scale.

        Overlapping bands would make a percentage ambiguous, and the
        student's grade would depend on row ordering.
        """
        if self.min_percentage is None or self.max_percentage is None:
            return

        if self.max_percentage < self.min_percentage:
            raise ValidationError(
                {"max_percentage": _("The maximum cannot be below the minimum.")}
            )

        if not self.scale_id:
            return

        overlapping = (
            GradeBand.objects.filter(scale_id=self.scale_id)
            .exclude(pk=self.pk)
            .filter(
                min_percentage__lte=self.max_percentage,
                max_percentage__gte=self.min_percentage,
            )
        )

        if overlapping.exists():
            clash = overlapping.first()
            raise ValidationError(
                _("This range overlaps grade %(letter)s (%(low)s–%(high)s%%).")
                % {
                    "letter": clash.letter,
                    "low": clash.min_percentage,
                    "high": clash.max_percentage,
                }
            )
