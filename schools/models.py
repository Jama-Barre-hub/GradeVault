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

    def coverage_gaps(self):
        """Return the percentage ranges this scale fails to cover.

        A gap means a student landing there receives no grade at all, and
        nothing else in the system would notice. A single mistyped digit
        — 50.99 where 59.99 was meant — silently strips a grade from
        every student in that range, so the scale reports its own gaps
        rather than waiting for a school to discover blank report cards.

        Bands are written inclusively, so "D up to 59.99" and "C from 60"
        are adjacent rather than separated. Only a shortfall wider than
        one hundredth counts as a real gap.
        """
        step = Decimal("0.01")
        floor, ceiling = Decimal("0"), Decimal("100")

        bands = list(self.bands.order_by("min_percentage"))
        if not bands:
            return [(floor, ceiling)]

        gaps = []
        covered_to = floor

        for band in bands:
            if band.min_percentage - covered_to > step:
                gaps.append((covered_to, band.min_percentage))
            covered_to = max(covered_to, band.max_percentage)

        if ceiling - covered_to > step:
            gaps.append((covered_to, ceiling))

        return gaps

    @property
    def is_complete(self) -> bool:
        """True when every percentage from 0 to 100 maps to a grade."""
        return not self.coverage_gaps()


class Enrollment(TimeStampedModel):
    """Places a student in a class for an academic year.

    A student sits in exactly one class per year. Allowing two would make
    class rank meaningless, because the same student would compete in two
    rankings at once.
    """

    student = models.ForeignKey(
        "accounts.StudentProfile", on_delete=models.CASCADE, related_name="enrollments"
    )
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name="enrollments"
    )
    roll_number = models.PositiveSmallIntegerField(
        _("roll number"),
        null=True,
        blank=True,
        help_text=_("The student's number within the class register."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("enrolment")
        verbose_name_plural = _("enrolments")
        ordering = ["classroom", "roll_number", "student"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "classroom"], name="unique_student_per_class"
            ),
        ]

    def __str__(self):
        return f"{self.student} in {self.classroom}"

    def clean(self):
        """Reject a second active class in the same academic year."""
        if not self.student_id or not self.classroom_id:
            return

        clash = (
            Enrollment.objects.filter(
                student_id=self.student_id,
                classroom__academic_year=self.classroom.academic_year,
                is_active=True,
            )
            .exclude(pk=self.pk)
            .select_related("classroom")
            .first()
        )

        if clash and self.is_active:
            raise ValidationError(
                _("This student is already enrolled in %(other)s for %(year)s.")
                % {
                    "other": clash.classroom.name,
                    "year": self.classroom.academic_year,
                }
            )


class TeachingAssignment(TimeStampedModel):
    """Records that a teacher teaches one subject to one class.

    This is what makes "a teacher may only enter marks for subjects they
    actually teach" enforceable. Without it, any teacher could mark any
    subject, which is the central permission failure this project sets
    out to avoid.

    The class already belongs to an academic year, so the assignment does
    not repeat it. Several teachers may share a subject in one class,
    which happens in practice.
    """

    teacher = models.ForeignKey(
        "accounts.TeacherProfile", on_delete=models.CASCADE, related_name="assignments"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="teaching_assignments"
    )
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name="teaching_assignments"
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("teaching assignment")
        verbose_name_plural = _("teaching assignments")
        ordering = ["classroom", "subject"]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "subject", "classroom"],
                name="unique_teaching_assignment",
            ),
        ]

    def __str__(self):
        return f"{self.teacher} teaches {self.subject} to {self.classroom.name}"


class Assessment(TimeStampedModel):
    """A gradeable item within a term, such as the mid-term or the final.

    Marks are recorded out of the assessment's own total, exactly as a
    teacher writes them in a mark book: 32 out of 40, not "80% weighted
    at 40" (PROPOSAL.md §10.2). Nothing is rounded at entry time.

    The default Somali structure is mid-term out of 40 and final out of
    60, summing to 100. That is a default, not a rule. A school weighting
    the mid-term at 30, or adding homework out of 10, defines its own
    assessments and nothing else changes.
    """

    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="assessments")
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="assessments"
    )
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name="assessments"
    )
    name = models.CharField(
        _("name"), max_length=60, help_text=_('e.g. "Mid-term" or "Final"')
    )
    max_marks = models.DecimalField(
        _("out of"),
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text=_("The total this assessment is marked out of, e.g. 40."),
    )
    sequence = models.PositiveSmallIntegerField(
        _("order"), default=1, help_text=_("Controls the order shown on a report card.")
    )

    class Meta:
        verbose_name = _("assessment")
        verbose_name_plural = _("assessments")
        ordering = ["term", "classroom", "subject", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["term", "subject", "classroom", "name"],
                name="unique_assessment_per_subject_class_term",
            ),
            models.CheckConstraint(
                condition=models.Q(max_marks__gt=0),
                name="assessment_max_marks_positive",
            ),
        ]

    def __str__(self):
        return (
            f"{self.name} ({self.subject}, {self.classroom.name}) "
            f"out of {self.max_marks}"
        )

    @staticmethod
    def total_max_marks(term, subject, classroom) -> Decimal:
        """The marks available across every assessment for one subject."""
        result = Assessment.objects.filter(
            term=term, subject=subject, classroom=classroom
        ).aggregate(total=models.Sum("max_marks"))
        return result["total"] or Decimal("0")

    @property
    def siblings_total(self) -> Decimal:
        """Total marks available for this subject, class and term."""
        return self.total_max_marks(self.term, self.subject, self.classroom)


class Score(TimeStampedModel):
    """One student's mark for one assessment. The central record.

    Tied to an Enrollment rather than a student, because a mark only
    makes sense for a student who is actually in that class. This makes
    it impossible to record a mark for a student who was never enrolled.

    `marks` may be null: an assessment exists for the whole class before
    anyone has been marked, and "not yet marked" is a different state
    from "scored zero". Conflating them would fail a student who was
    simply absent from the teacher's data entry.
    """

    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="scores"
    )
    assessment = models.ForeignKey(
        Assessment, on_delete=models.CASCADE, related_name="scores"
    )
    marks = models.DecimalField(
        _("marks"),
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text=_("Leave empty if the student has not been marked yet."),
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scores_recorded",
    )

    class Meta:
        verbose_name = _("score")
        verbose_name_plural = _("scores")
        ordering = ["assessment", "enrollment"]
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "assessment"], name="unique_score_per_assessment"
            ),
            models.CheckConstraint(
                condition=models.Q(marks__gte=0) | models.Q(marks__isnull=True),
                name="score_not_negative",
            ),
        ]

    def __str__(self):
        shown = self.marks if self.marks is not None else "—"
        return f"{self.enrollment.student} — {self.assessment.name}: {shown}"

    def save(self, *args, **kwargs):
        """Validate the mark before it reaches the database.

        clean() is not called by save(), so relying on it alone would let
        code paths that skip forms store 45 out of 40. For a grade this
        is checked on every write, not only when a form is used.
        """
        self._assert_marks_within_range()
        super().save(*args, **kwargs)

    def clean(self):
        self._assert_marks_within_range()

    def _assert_marks_within_range(self):
        if self.marks is None:
            return

        if self.marks < 0:
            raise ValidationError({"marks": _("A mark cannot be negative.")})

        limit = self.assessment.max_marks
        if self.marks > limit:
            raise ValidationError(
                {
                    "marks": _("%(marks)s is more than the %(limit)s available.")
                    % {"marks": self.marks, "limit": limit}
                }
            )

    @property
    def is_marked(self) -> bool:
        return self.marks is not None


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
