"""Build a complete demo school with entirely fictional data.

    python manage.py seed_demo --reset

Every name, admission number and mark this command produces is invented.
No real student record is ever used, in development, in tests, or in the
public demo. Providing a good generator is what makes reaching for real
data unnecessary.

The command only ever touches the institution named by DEMO_SCHOOL_NAME,
so a school entered by hand is never affected.
"""

import random
from datetime import date
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction

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
    GradeBand,
    GradingScale,
    Institution,
    Score,
    Subject,
    TeachingAssignment,
    Term,
)

DEMO_SCHOOL_NAME = "Daryeel Secondary School (Demo)"

# Common Somali given and family names, combined at random. The people
# produced are fictional; any resemblance to a real person is accidental.
GIVEN_NAMES_F = [
    "Amina",
    "Fatima",
    "Hodan",
    "Ayaan",
    "Sagal",
    "Ubah",
    "Deqa",
    "Halima",
    "Ifrah",
    "Khadija",
    "Nasra",
    "Sahra",
    "Warsan",
    "Zamzam",
    "Ilhan",
    "Muna",
    "Rahma",
    "Samira",
    "Asha",
    "Faduma",
    "Hafsa",
    "Layla",
]
GIVEN_NAMES_M = [
    "Abdi",
    "Ahmed",
    "Ali",
    "Bashir",
    "Farah",
    "Guled",
    "Hassan",
    "Hussein",
    "Ibrahim",
    "Ismail",
    "Jama",
    "Khalid",
    "Liban",
    "Mohamed",
    "Nur",
    "Omar",
    "Said",
    "Yusuf",
    "Abdullahi",
    "Mahad",
    "Siyad",
    "Warsame",
]
FAMILY_NAMES = [
    "Abdi",
    "Adan",
    "Ahmed",
    "Ali",
    "Aweys",
    "Barre",
    "Diriye",
    "Dahir",
    "Egal",
    "Farah",
    "Gedi",
    "Hassan",
    "Hersi",
    "Hussein",
    "Ismail",
    "Jama",
    "Kahin",
    "Mohamud",
    "Noor",
    "Omar",
    "Osman",
    "Samatar",
    "Shire",
    "Warsame",
    "Yusuf",
]

SUBJECTS = [
    ("Mathematics", "MATH"),
    ("English", "ENG"),
    ("Somali", "SOM"),
    ("Biology", "BIO"),
    ("Chemistry", "CHEM"),
    ("Physics", "PHY"),
    ("Geography", "GEO"),
    ("Islamic Studies", "ISL"),
]

CLASS_NAMES = ["Form 1A", "Form 1B", "Form 2A", "Form 2B", "Form 3A", "Form 4A"]

# Ten pass grades in five-point steps from 100 down to 50, then fail.
#
# The pass mark is 50: anything below 49.99 fails. Fifty points divided
# into five-point bands gives exactly ten grades, which is why the ladder
# stops at D rather than continuing to D-. Adding D- would mean uneven
# bands or a lower pass mark.
#
# These boundaries are the seeded default, not a standard. Every school
# sets its own (§10.3), and changing them means editing rows, never code.
GRADE_BANDS = [
    ("A", 95, 100, "Excellent"),
    ("A-", 90, 94.99, "Excellent"),
    ("B+", 85, 89.99, "Very good"),
    ("B", 80, 84.99, "Very good"),
    ("B-", 75, 79.99, "Good"),
    ("C+", 70, 74.99, "Good"),
    ("C", 65, 69.99, "Satisfactory"),
    ("C-", 60, 64.99, "Satisfactory"),
    ("D+", 55, 59.99, "Pass"),
    ("D", 50, 54.99, "Pass"),
    ("F", 0, 49.99, "Fail"),
]

# Marks out of these totals, matching how Somali schools record them.
ASSESSMENTS = [("Mid-term", Decimal("40"), 1), ("Final", Decimal("60"), 2)]


class Command(BaseCommand):
    help = "Create a demo school populated with fictional students and marks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the existing demo school first. Only the demo school.",
        )
        parser.add_argument(
            "--students",
            type=int,
            default=20,
            help="Students per class (default 20).",
        )
        parser.add_argument(
            "--password",
            default="demo-password",
            help="Password for every demo account. Local use only.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=2026,
            help="Random seed, so the same data is produced each run.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(options["seed"])
        password = options["password"]
        per_class = options["students"]

        # Hash the shared demo password once instead of 130-odd times.
        #
        # PBKDF2 at 1.5 million iterations takes roughly a second per
        # call, which is exactly what makes a stolen hash expensive to
        # crack, and why the setting must never be lowered. But every
        # demo account deliberately uses the same password, so hashing it
        # repeatedly buys nothing and turned a two-second command into a
        # two-minute one.
        #
        # Reusing one hash means identical stored values, which would
        # reveal that these accounts share a password. That is acceptable
        # here and nowhere else: these are fictional accounts whose
        # password is printed on screen and published in the README.
        # Real accounts go through set_password() individually.
        self._shared_hash = make_password(password)

        if options["reset"]:
            self._reset()

        if Institution.objects.filter(name=DEMO_SCHOOL_NAME).exists():
            self.stderr.write(
                self.style.ERROR(
                    f"'{DEMO_SCHOOL_NAME}' already exists. "
                    "Re-run with --reset to rebuild it."
                )
            )
            return

        school = self._create_school()
        year, terms = self._create_calendar(school)
        self._create_grading_scale(school)
        subjects = self._create_subjects(school)
        classrooms = self._create_classes(year)
        teachers = self._create_teachers(school, rng)
        self._assign_teaching(teachers, subjects, classrooms, rng)
        enrollments = self._enrol_students(school, classrooms, per_class, rng)
        assessments = self._create_assessments(terms, subjects, classrooms)
        marked = self._record_marks(enrollments, assessments, terms, rng)

        self._report(school, teachers, enrollments, marked, password)

    # ---------- steps ----------

    def _reset(self):
        deleted, _ = Institution.objects.filter(name=DEMO_SCHOOL_NAME).delete()
        # Demo accounts are not reached by the cascade, since users own
        # their profiles rather than the other way round.
        User.objects.filter(username__startswith="STU-").delete()
        User.objects.filter(username__startswith="demo-tch-").delete()
        if deleted:
            self.stdout.write(f"Removed previous demo school ({deleted} rows).")

    def _create_school(self):
        return Institution.objects.create(
            name=DEMO_SCHOOL_NAME,
            short_name="DSS",
            address="Hodan District, Mogadishu, Somalia",
            phone="+252 61 000 0000",
            email="demo@example.invalid",
        )

    def _create_calendar(self, school):
        """Two terms, matching the real Somali calendar (PROPOSAL.md §10.1)."""
        year = AcademicYear.objects.create(
            institution=school,
            name="2026/2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            is_current=True,
        )
        terms = [
            Term.objects.create(
                academic_year=year,
                name="Term 1",
                sequence=1,
                start_date=date(2026, 9, 1),
                end_date=date(2027, 1, 15),
            ),
            Term.objects.create(
                academic_year=year,
                name="Term 2",
                sequence=2,
                start_date=date(2027, 2, 2),
                end_date=date(2027, 6, 30),
            ),
        ]
        return year, terms

    def _create_grading_scale(self, school):
        scale = GradingScale.objects.create(
            institution=school, name="DSS Standard Scale", is_default=True
        )
        GradeBand.objects.bulk_create(
            GradeBand(
                scale=scale,
                letter=letter,
                min_percentage=Decimal(str(low)),
                max_percentage=Decimal(str(high)),
                remark=remark,
            )
            for letter, low, high, remark in GRADE_BANDS
        )
        return scale

    def _create_subjects(self, school):
        return [
            Subject.objects.create(institution=school, name=name, code=code)
            for name, code in SUBJECTS
        ]

    def _create_classes(self, year):
        return [
            ClassRoom.objects.create(academic_year=year, name=name)
            for name in CLASS_NAMES
        ]

    def _create_teachers(self, school, rng):
        teachers = []
        for index in range(12):
            first, last = self._invent_name(rng)
            user = User.objects.create(
                username=f"demo-tch-{index + 1:02d}",
                role=User.Role.TEACHER,
                first_name=first,
                last_name=last,
                password=self._shared_hash,
            )

            teachers.append(
                TeacherProfile.objects.create(
                    user=user,
                    institution=school,
                    staff_number=f"STF-{index + 1:03d}",
                )
            )
        return teachers

    def _assign_teaching(self, teachers, subjects, classrooms, rng):
        """Give every subject in every class exactly one teacher.

        Teachers are spread across subjects so that no teacher covers the
        whole school, which is what makes the permission tests meaningful.
        """
        for subject_index, subject in enumerate(subjects):
            for class_index, classroom in enumerate(classrooms):
                teacher = teachers[(subject_index + class_index) % len(teachers)]
                TeachingAssignment.objects.create(
                    teacher=teacher, subject=subject, classroom=classroom
                )

    def _enrol_students(self, school, classrooms, per_class, rng):
        enrollments = []
        admission = 1

        for classroom in classrooms:
            for roll in range(1, per_class + 1):
                first, last = self._invent_name(rng)
                user = User.objects.create(
                    username=generate_student_username(2026),
                    role=User.Role.STUDENT,
                    first_name=first,
                    last_name=last,
                    password=self._shared_hash,
                )

                student = StudentProfile.objects.create(
                    user=user,
                    institution=school,
                    admission_number=f"DEMO-{admission:04d}",
                    guardian_name=f"{self._invent_name(rng)[0]} {last}",
                    guardian_phone=f"+252 61 {rng.randint(100000, 999999)}",
                )
                admission += 1

                enrollments.append(
                    Enrollment.objects.create(
                        student=student, classroom=classroom, roll_number=roll
                    )
                )
        return enrollments

    def _create_assessments(self, terms, subjects, classrooms):
        created = []
        for term in terms:
            for subject in subjects:
                for classroom in classrooms:
                    for name, max_marks, sequence in ASSESSMENTS:
                        created.append(
                            Assessment(
                                term=term,
                                subject=subject,
                                classroom=classroom,
                                name=name,
                                max_marks=max_marks,
                                sequence=sequence,
                            )
                        )
        Assessment.objects.bulk_create(created)
        return Assessment.objects.all()

    def _record_marks(self, enrollments, assessments, terms, rng):
        """Mark term 1 fully; leave term 2 partly unmarked.

        A half-finished term is the normal state of a real system, and it
        exercises the distinction between "not yet marked" and "zero".
        """
        first_term, second_term = terms[0], terms[1]
        by_class = {}
        for assessment in assessments:
            by_class.setdefault(assessment.classroom_id, []).append(assessment)

        scores = []
        marked = 0

        for enrollment in enrollments:
            # A student's ability is stable across subjects, so class
            # rankings are coherent rather than random noise.
            ability = min(96, max(28, rng.gauss(66, 14)))

            for assessment in by_class.get(enrollment.classroom_id, []):
                if assessment.term_id == second_term.id and rng.random() < 0.4:
                    marks = None  # not yet marked
                else:
                    percentage = min(100, max(0, rng.gauss(ability, 8)))
                    marks = (assessment.max_marks * Decimal(percentage) / 100).quantize(
                        Decimal("0.01")
                    )
                    marked += 1

                scores.append(
                    Score(enrollment=enrollment, assessment=assessment, marks=marks)
                )

        Score.objects.bulk_create(scores, batch_size=2000)

        first_term.refresh_from_db()
        return marked

    # ---------- helpers ----------

    def _invent_name(self, rng):
        pool = GIVEN_NAMES_F if rng.random() < 0.5 else GIVEN_NAMES_M
        return rng.choice(pool), rng.choice(FAMILY_NAMES)

    def _report(self, school, teachers, enrollments, marked, password):
        # Every count is scoped to the demo school. An unscoped count
        # reports another institution's records as if they were the
        # demo's, which is both wrong here and the exact shape of query
        # that leaks data once several schools share one database.
        classes = ClassRoom.objects.filter(academic_year__institution=school)
        assessments = Assessment.objects.filter(classroom__in=classes)
        unmarked = Score.objects.filter(
            assessment__in=assessments, marks__isnull=True
        ).count()

        write = self.stdout.write
        write("")
        write(self.style.SUCCESS(f"Created {school.name}"))
        write("")
        write(f"  Teachers          {len(teachers)}")
        write(f"  Students          {len(enrollments)}")
        write(f"  Classes           {classes.count()}")
        write(f"  Subjects          {school.subjects.count()}")
        write(f"  Assessments       {assessments.count()}")
        write(f"  Marks recorded    {marked}")
        write(f"  Awaiting marking  {unmarked}")
        write("")

        sample_teacher = teachers[0].user.username
        sample_student = (
            enrollments[0].student.user.username if enrollments else "STU-2026-0001"
        )
        write("  Sign in with:")
        write(f"    teacher   {sample_teacher}")
        write(f"    student   {sample_student}")
        write(f"    password  {password}")
        write("")
        write(
            self.style.WARNING(
                "  All names and marks are fictional. Both terms are unpublished, "
                "so students cannot see results until an administrator publishes."
            )
        )
