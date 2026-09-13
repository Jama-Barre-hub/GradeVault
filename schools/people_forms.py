"""Forms for creating the people a school is made of.

This is the most dangerous module in GradeVault, because everything else
is a rule *about* accounts and this is the thing that makes them. A
mistake in `setup_forms.py` produces a badly named subject. A mistake
here produces an account with powers nobody granted it.

Three rules therefore hold without exception.

**Role is never a form field.** It is set by the view, from which screen
the request came through. A form that accepted a role would let anyone
who can add a teacher add an administrator instead, by adding one field
to the request — and a head teacher creating a colleague must not be
able to create their own replacement.

**Institution is never a form field.** It comes from the signed-in
administrator, so a posted form cannot enrol a child into another
school.

**Passwords are generated, never chosen.** A head teacher setting up
forty accounts in an afternoon picks forty weak passwords, usually the
same one. The system generates each and shows it once, for the
administrator to hand over.
"""

import secrets
import string

from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.models import StudentProfile, TeacherProfile, User
from schools.models import ClassRoom, Subject, TeachingAssignment

# Unambiguous characters only.
#
# A password read off a screen and typed by a ten-year-old must not turn
# on telling O from 0 or l from 1. Dropping the confusable characters
# costs a little entropy and removes the commonest reason a new account
# cannot sign in on its first day.
SAFE_CHARACTERS = "".join(
    c for c in string.ascii_letters + string.digits if c not in "O0oIl1"
)


def make_password_for_new_account(length: int = 10) -> str:
    """A temporary password, generated with the system's own randomness.

    `secrets` rather than `random`: this value guards a child's records
    from the moment it is created until it is changed, and `random` is
    seeded predictably enough to be reproduced.
    """
    return "".join(secrets.choice(SAFE_CHARACTERS) for _ in range(length))


class PersonForm(forms.Form):
    """Fields every new account needs, whatever it will become."""

    first_name = forms.CharField(label=_("First name"), max_length=150)
    last_name = forms.CharField(label=_("Last name"), max_length=150)

    def __init__(self, *args, institution=None, **kwargs):
        self.institution = institution
        super().__init__(*args, **kwargs)

    def full_name(self) -> tuple[str, str]:
        return (
            self.cleaned_data["first_name"].strip(),
            self.cleaned_data["last_name"].strip(),
        )


class TeacherForm(PersonForm):
    """A member of teaching staff.

    The username is chosen rather than generated. Teachers are adults who
    sign in daily and will remember `f.hassan`; a generated string would
    be written on a sticky note beside the keyboard, which is worse for
    security than letting them pick something memorable.
    """

    username = forms.CharField(
        label=_("Username"),
        max_length=150,
        help_text=_("What they will type to sign in, e.g. f.hassan"),
    )
    staff_number = forms.CharField(
        label=_("Staff number"), max_length=30, required=False
    )
    phone = forms.CharField(label=_("Phone"), max_length=40, required=False)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()

        # Checked against every account on the deployment, not just this
        # school's. Usernames are how a person signs in, so they are
        # global whether or not a school thinks of them that way, and a
        # per-school check would produce a clash the database refuses
        # after the form has already said yes.
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(_("That username is already taken."))
        return username


class StudentForm(PersonForm):
    """A pupil, and the class they are joining.

    Creating a student and enrolling them are one action here rather than
    two screens. A student who exists but sits in no class has no
    results, appears in no register and is invisible to every other page
    — a state worth making hard to reach.
    """

    admission_number = forms.CharField(
        label=_("Admission number"),
        max_length=30,
        help_text=_("Your school's own reference for this pupil."),
    )
    classroom = forms.ModelChoiceField(
        label=_("Class"), queryset=ClassRoom.objects.none()
    )
    guardian_name = forms.CharField(
        label=_("Guardian name"), max_length=150, required=False
    )
    guardian_phone = forms.CharField(
        label=_("Guardian phone"), max_length=40, required=False
    )

    def __init__(self, *args, year=None, **kwargs):
        self.year = year
        super().__init__(*args, **kwargs)
        # The dropdown is filtered, not merely the list behind it. An
        # unfiltered picker would let one school enrol a child into
        # another school's class, and leak the class names doing it.
        self.fields["classroom"].queryset = (
            ClassRoom.objects.filter(academic_year=year).order_by("name")
            if year
            else ClassRoom.objects.none()
        )

    def clean_admission_number(self):
        number = self.cleaned_data["admission_number"].strip()
        clash = StudentProfile.objects.filter(
            institution=self.institution, admission_number__iexact=number
        )
        if clash.exists():
            raise forms.ValidationError(
                _("Another pupil at your school already has this admission number.")
            )
        return number


class TeachingAssignmentForm(forms.Form):
    """Records that a teacher teaches one subject to one class.

    This is what makes "a teacher may only mark subjects they teach"
    enforceable, so all three dropdowns are filtered to the signed-in
    administrator's school. An unfiltered one here would hand a teacher
    at one school the right to enter marks at another.
    """

    teacher = forms.ModelChoiceField(
        label=_("Teacher"), queryset=TeacherProfile.objects.none()
    )
    subject = forms.ModelChoiceField(
        label=_("Subject"), queryset=Subject.objects.none()
    )
    classroom = forms.ModelChoiceField(
        label=_("Class"), queryset=ClassRoom.objects.none()
    )

    def __init__(self, *args, institution=None, year=None, **kwargs):
        self.institution = institution
        self.year = year
        super().__init__(*args, **kwargs)

        self.fields["teacher"].queryset = TeacherProfile.objects.filter(
            institution=institution, is_active=True
        ).order_by("user__last_name")
        self.fields["subject"].queryset = Subject.objects.filter(
            institution=institution
        ).order_by("name")
        self.fields["classroom"].queryset = (
            ClassRoom.objects.filter(academic_year=year).order_by("name")
            if year
            else ClassRoom.objects.none()
        )

    def clean(self):
        cleaned = super().clean()
        teacher = cleaned.get("teacher")
        subject = cleaned.get("subject")
        classroom = cleaned.get("classroom")

        if teacher and subject and classroom:
            existing = TeachingAssignment.objects.filter(
                teacher=teacher, subject=subject, classroom=classroom
            )
            if existing.exists():
                raise forms.ValidationError(
                    _("%(teacher)s already teaches %(subject)s to %(classroom)s.")
                    % {
                        "teacher": teacher.full_name,
                        "subject": subject.name,
                        "classroom": classroom.name,
                    }
                )
        return cleaned


class MoveStudentForm(forms.Form):
    """Move a pupil from one class to another within the same year.

    Deactivates rather than deletes the old enrolment: a child who moved
    class in February still sat Term 1 in the class they were in, and
    deleting that would rewrite a term of results that actually happened.
    """

    classroom = forms.ModelChoiceField(
        label=_("Move to"), queryset=ClassRoom.objects.none()
    )

    def __init__(self, *args, year=None, exclude=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = (
            ClassRoom.objects.filter(academic_year=year)
            if year
            else ClassRoom.objects.none()
        )
        if exclude is not None:
            queryset = queryset.exclude(pk=exclude.pk)
        self.fields["classroom"].queryset = queryset.order_by("name")
