"""An append-only record of every change to a grade.

A results system's real duty is not storing marks; it is being able to
prove that a mark is the one the teacher actually entered. Without this,
grade tampering is undetectable and, just as importantly, unprovable —
an honest school cannot demonstrate that nothing was altered.

Two design decisions follow from that:

**Nothing may amend or delete a row.** Saving over an existing entry
raises, as does deleting, as do queryset-level update() and delete().

**Entries carry copies of the facts, not only foreign keys.** A student
who leaves and is deleted must not take the history of their marks with
them. Each row stores the names as text alongside the keys, so the log
stays readable after the rows it refers to are gone.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditLogError(Exception):
    """Raised on any attempt to change or remove an audit entry."""


class AuditLogQuerySet(models.QuerySet):
    """Refuses the bulk operations that would rewrite history."""

    def update(self, **kwargs):
        raise AuditLogError("Audit entries cannot be updated. The log is append-only.")

    def delete(self):
        raise AuditLogError("Audit entries cannot be deleted. The log is append-only.")


class AuditLog(models.Model):
    """One recorded change. Written once, never altered."""

    class Action(models.TextChoices):
        SCORE_RECORDED = "score_recorded", _("Mark recorded")
        SCORE_CHANGED = "score_changed", _("Mark changed")
        SCORE_CLEARED = "score_cleared", _("Mark removed")
        TERM_PUBLISHED = "term_published", _("Results published")
        TERM_UNPUBLISHED = "term_unpublished", _("Results withdrawn")

    action = models.CharField(_("action"), max_length=32, choices=Action.choices)

    # Without this an administrator would read every school's history.
    # Recorded on the entry rather than reached through the score, so the
    # scoping still works after the score is gone.
    institution = models.ForeignKey(
        "schools.Institution",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_entries",
    )

    # SET_NULL rather than CASCADE: deleting a member of staff must not
    # erase the record of what they did.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    actor_label = models.CharField(
        _("who"),
        max_length=200,
        help_text=_("Copied at the time, so the entry survives account deletion."),
    )

    # Copies of the surrounding facts, so an entry still reads correctly
    # after the student, class or subject it refers to has been removed.
    student_label = models.CharField(_("student"), max_length=200, blank=True)
    classroom_label = models.CharField(_("class"), max_length=100, blank=True)
    subject_label = models.CharField(_("subject"), max_length=120, blank=True)
    assessment_label = models.CharField(_("assessment"), max_length=120, blank=True)
    term_label = models.CharField(_("term"), max_length=120, blank=True)

    old_value = models.CharField(_("from"), max_length=40, blank=True)
    new_value = models.CharField(_("to"), max_length=40, blank=True)

    created_at = models.DateTimeField(_("when"), auto_now_add=True, db_index=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        verbose_name = _("audit entry")
        verbose_name_plural = _("audit trail")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["student_label"]),
        ]

    def __str__(self):
        who = self.actor_label or _("unknown")
        if self.action.startswith("score"):
            return (
                f"{who}: {self.student_label} {self.assessment_label} "
                f"{self.old_value or '—'} to {self.new_value or '—'}"
            )
        return f"{who}: {self.get_action_display()} ({self.term_label})"

    def save(self, *args, **kwargs):
        """Allow the first write, refuse every one after it."""
        if self.pk is not None:
            raise AuditLogError(
                "An audit entry cannot be modified once written. "
                "Record a new entry instead."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditLogError("Audit entries cannot be deleted. The log is append-only.")

    # ---------- recording ----------

    @classmethod
    def record_score(cls, score, action, actor, old_value, new_value):
        """Write an entry for a mark that was created, changed or removed."""
        assessment = score.assessment
        student = score.enrollment.student

        return cls.objects.create(
            action=action,
            institution=score.enrollment.classroom.academic_year.institution,
            actor=actor,
            actor_label=cls._describe(actor),
            student_label=f"{student.full_name} ({student.user.username})",
            classroom_label=score.enrollment.classroom.name,
            subject_label=assessment.subject.name,
            assessment_label=f"{assessment.name} (out of {assessment.max_marks})",
            term_label=str(assessment.term),
            old_value=cls.format_marks(old_value),
            new_value=cls.format_marks(new_value),
        )

    @staticmethod
    def format_marks(value) -> str:
        """Render a mark identically wherever it came from.

        A value read back from the database arrives as Decimal("20.00")
        while the same mark held in memory is Decimal("20"). Recorded
        as-is, one history read "20.00 to 28", which is the same number
        written two ways. In a log whose purpose is evidence, a value
        that renders differently depending on its origin cannot be
        compared or trusted, so every mark is stored to two decimal
        places.
        """
        if value is None:
            return ""
        return f"{Decimal(value):.2f}"

    @classmethod
    def record_publication(cls, term, action, actor):
        """Write an entry for a term being released or withdrawn."""
        return cls.objects.create(
            action=action,
            institution=term.academic_year.institution,
            actor=actor,
            actor_label=cls._describe(actor),
            term_label=str(term),
            classroom_label="",
        )

    @staticmethod
    def _describe(actor) -> str:
        if actor is None:
            return "system"
        full_name = actor.get_full_name()
        return f"{full_name} ({actor.username})" if full_name else actor.username
