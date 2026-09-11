"""Builders for test data.

`SchoolFixture` assembles one complete, self-contained school — year,
term, class, subject, grading scale and assessment — so a test that
needs two schools to prove they cannot see each other can say so in two
lines.

It lives here rather than in one test module because isolation,
publication and permission tests all need the same shape of school, and
a second hand-rolled copy would drift from this one.
"""

from datetime import date
from decimal import Decimal

from accounts.models import (
    StudentProfile,
    TeacherProfile,
    User,
    generate_student_username,
)
from schools.models import (
    AcademicYear,
    Assessment,
    ClassRoom,
    Enrollment,
    GradingScale,
    Institution,
    Score,
    Subject,
    TeachingAssignment,
    Term,
)

PASSWORD = "test-password-123"


class SchoolFixture:
    """One complete, self-contained school."""

    def __init__(self, name, short):
        self.institution = Institution.objects.create(name=name, short_name=short)
        self.year = AcademicYear.objects.create(
            institution=self.institution,
            name="2026/2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            is_current=True,
        )
        self.term = Term.objects.create(
            academic_year=self.year,
            name="Term 1",
            sequence=1,
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 15),
        )
        self.classroom = ClassRoom.objects.create(
            academic_year=self.year, name="Form 2A"
        )
        self.subject = Subject.objects.create(
            institution=self.institution, name="Mathematics"
        )
        self.scale = GradingScale.objects.create(
            institution=self.institution, name="Scale", is_default=True
        )
        self.assessment = Assessment.objects.create(
            term=self.term,
            subject=self.subject,
            classroom=self.classroom,
            name="Mid-term",
            max_marks=Decimal("40"),
        )

    def add_admin(self, username):
        user = User.objects.create_user(
            username=username,
            password=PASSWORD,
            role=User.Role.ADMIN,
            institution=self.institution,
            is_staff=True,
        )
        user.user_permissions.set([])
        return user

    def add_teacher(self, username):
        user = User.objects.create_user(
            username=username,
            password=PASSWORD,
            role=User.Role.TEACHER,
            institution=self.institution,
        )
        teacher = TeacherProfile.objects.create(user=user, institution=self.institution)
        TeachingAssignment.objects.create(
            teacher=teacher, subject=self.subject, classroom=self.classroom
        )
        return teacher

    def add_student(self, first, last, marks=None):
        user = User.objects.create_user(
            username=generate_student_username(2026),
            password=PASSWORD,
            role=User.Role.STUDENT,
            institution=self.institution,
            first_name=first,
            last_name=last,
        )
        student = StudentProfile.objects.create(
            user=user,
            institution=self.institution,
            admission_number=f"ADM-{StudentProfile.objects.count() + 1:03d}",
        )
        enrollment = Enrollment.objects.create(
            student=student, classroom=self.classroom
        )
        if marks is not None:
            Score.objects.create(
                enrollment=enrollment,
                assessment=self.assessment,
                marks=Decimal(marks),
            )
        return enrollment
