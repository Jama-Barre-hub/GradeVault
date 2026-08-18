"""Turning marks into results.

Everything here is **computed, never stored**. A stored total is a copy
of the truth that can drift away from it: correct a mark and a cached
percentage silently disagrees with the marks it came from. In a system
whose purpose is trustworthy grades, a figure that might be stale is
worse than one that takes a moment to work out.

The numbers are small — a class of forty across eight subjects — so
correctness costs nothing here. If it ever does, the fix is a cache with
explicit invalidation, not a stored column.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from schools.models import Assessment, ClassRoom, Enrollment, GradingScale, Score

TWO_PLACES = Decimal("0.01")


def round_percentage(value: Decimal) -> Decimal:
    """Round half up, the way a person expects.

    Python's default for Decimal is banker's rounding, which sends 82.5
    to 82 and 83.5 to 84. A school reading 82.5 expects 83, and a rule
    that rounds one student up and another down for the same fraction is
    impossible to defend to a parent.
    """
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SubjectResult:
    """One student's standing in one subject for one term."""

    subject_name: str
    marks_obtained: Decimal
    marks_available: Decimal
    marks_possible: Decimal
    assessments_marked: int
    assessments_total: int

    @property
    def is_complete(self) -> bool:
        """Whether every assessment in this subject has been marked."""
        return self.assessments_marked == self.assessments_total

    @property
    def has_any_mark(self) -> bool:
        return self.assessments_marked > 0

    @property
    def percentage(self) -> Decimal | None:
        """Marks obtained as a percentage of what has been marked so far.

        The denominator is the marks *available*, not the full 100. A
        student marked only on the mid-term scoring 32 out of 40 stands
        at 80%, which is comparable with a classmate on 80 out of 100.
        Dividing by 100 instead would report them at 32% and rank them
        below someone who has simply been marked sooner.
        """
        if not self.has_any_mark or self.marks_available == 0:
            return None
        return round_percentage(self.marks_obtained / self.marks_available * 100)

    def grade(self, scale: GradingScale | None):
        """The letter grade, or None if unmarked or no scale is set."""
        percentage = self.percentage
        if percentage is None or scale is None:
            return None
        return scale.grade_for(percentage)


@dataclass(frozen=True)
class TermResult:
    """One student's whole term: every subject, the average, the position."""

    enrollment: Enrollment
    subjects: list[SubjectResult]
    position: int | None = None
    class_size: int | None = None

    @property
    def student_name(self) -> str:
        return self.enrollment.student.full_name

    @property
    def marks_obtained(self) -> Decimal:
        return sum((s.marks_obtained for s in self.subjects), Decimal("0"))

    @property
    def marks_available(self) -> Decimal:
        return sum((s.marks_available for s in self.subjects), Decimal("0"))

    @property
    def has_any_mark(self) -> bool:
        return any(s.has_any_mark for s in self.subjects)

    @property
    def is_complete(self) -> bool:
        return bool(self.subjects) and all(s.is_complete for s in self.subjects)

    @property
    def average_percentage(self) -> Decimal | None:
        """Total obtained over total available, across every subject."""
        if not self.has_any_mark or self.marks_available == 0:
            return None
        return round_percentage(self.marks_obtained / self.marks_available * 100)

    def grade(self, scale: GradingScale | None):
        average = self.average_percentage
        if average is None or scale is None:
            return None
        return scale.grade_for(average)

    def subjects_passed(self, scale: GradingScale | None) -> int:
        if scale is None:
            return 0
        return sum(
            1
            for subject in self.subjects
            if (band := subject.grade(scale)) is not None and band.letter != "F"
        )


def default_scale_for(classroom: ClassRoom) -> GradingScale | None:
    """The grading scale the school has marked as default."""
    return GradingScale.objects.filter(
        institution=classroom.academic_year.institution, is_default=True
    ).first()


def term_result(enrollment: Enrollment, term) -> TermResult:
    """Work out one student's results for a term."""
    assessments = list(
        Assessment.objects.filter(term=term, classroom=enrollment.classroom)
        .select_related("subject")
        .order_by("subject__name", "sequence")
    )

    marks = {
        score.assessment_id: score.marks
        for score in Score.objects.filter(
            enrollment=enrollment, assessment__in=assessments
        )
    }

    by_subject: dict[str, list[Assessment]] = {}
    for assessment in assessments:
        by_subject.setdefault(assessment.subject.name, []).append(assessment)

    subjects = []
    for subject_name, subject_assessments in by_subject.items():
        obtained = Decimal("0")
        available = Decimal("0")
        possible = Decimal("0")
        marked = 0

        for assessment in subject_assessments:
            possible += assessment.max_marks
            mark = marks.get(assessment.id)
            if mark is not None:
                obtained += mark
                available += assessment.max_marks
                marked += 1

        subjects.append(
            SubjectResult(
                subject_name=subject_name,
                marks_obtained=obtained,
                marks_available=available,
                marks_possible=possible,
                assessments_marked=marked,
                assessments_total=len(subject_assessments),
            )
        )

    return TermResult(enrollment=enrollment, subjects=subjects)


def class_results(classroom: ClassRoom, term) -> list[TermResult]:
    """Every student in a class, ranked.

    Position is competition ranking: two students tied for second are
    both second, and the next is fourth. Awarding different positions to
    identical averages would be arbitrary, and inventing a tie-break the
    school did not ask for would be worse.

    Students with no marks at all are returned unranked rather than
    placed last, because "not yet marked" is not "scored nothing"
    (PROPOSAL.md §10.2).
    """
    enrollments = list(
        Enrollment.objects.filter(classroom=classroom, is_active=True)
        .select_related("student__user", "classroom")
        .order_by("roll_number", "student__user__last_name")
    )

    results = [term_result(enrollment, term) for enrollment in enrollments]

    ranked = [r for r in results if r.has_any_mark]
    unranked = [r for r in results if not r.has_any_mark]

    ranked.sort(key=lambda r: r.average_percentage, reverse=True)

    positioned: list[TermResult] = []
    previous_average = None
    previous_position = 0

    for index, result in enumerate(ranked, start=1):
        average = result.average_percentage
        position = previous_position if average == previous_average else index
        previous_average, previous_position = average, position

        positioned.append(
            TermResult(
                enrollment=result.enrollment,
                subjects=result.subjects,
                position=position,
                class_size=len(ranked),
            )
        )

    positioned.extend(
        TermResult(
            enrollment=r.enrollment,
            subjects=r.subjects,
            position=None,
            class_size=len(ranked),
        )
        for r in unranked
    )

    return positioned
