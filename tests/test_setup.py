"""Tests for a school setting itself up.

These screens create the structure everything else hangs off, so two
kinds of thing are tested here.

**That the validation actually refuses.** A form that reports a problem
but saves the row anyway is worse than no validation, because the school
now believes it was checked. Every rejection test therefore asserts the
database is unchanged, not merely that a message appeared.

**That one school cannot set up another.** The ids in these URLs and
forms come from outside, so each is re-filtered by institution. The
tenancy tests play the attacker and pass only when GradeVault refuses.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from factories import PASSWORD
from schools.models import (
    AcademicYear,
    ClassRoom,
    GradeBand,
    GradingScale,
    Subject,
    Term,
)
from schools.setup import readiness


@pytest.fixture
def head(client, hodan):
    """Signed in as an administrator at Hodan."""
    user = hodan.add_admin("hodan-head")
    client.login(username=user.username, password=PASSWORD)
    return user


# ------------------------------------------------------------ who may look


@pytest.mark.permissions
@pytest.mark.parametrize(
    "name",
    [
        "setup_overview",
        "setup_years",
        "setup_classes",
        "setup_subjects",
        "setup_scales",
    ],
)
def test_a_teacher_cannot_reach_the_setup_screens(client, hodan, name):
    teacher = hodan.add_teacher("hodan-tch").user
    client.login(username=teacher.username, password=PASSWORD)

    assert client.get(reverse(name)).status_code == 403


@pytest.mark.permissions
def test_a_student_cannot_reach_setup(client, hodan):
    student = hodan.add_student("Sagal", "Omar").student.user
    client.login(username=student.username, password=PASSWORD)

    assert client.get(reverse("setup_overview")).status_code == 403


@pytest.mark.permissions
def test_an_administrator_with_no_school_sets_up_nothing(client, hodan):
    """Missing means nothing, not everything."""
    from accounts.models import User

    stray = User.objects.create_user(
        username="no-school", password=PASSWORD, role=User.Role.ADMIN
    )
    client.login(username=stray.username, password=PASSWORD)

    assert client.get(reverse("setup_overview")).status_code == 404


# ---------------------------------------------------------------- tenancy


@pytest.mark.permissions
def test_another_schools_year_cannot_be_opened(client, head, banadir):
    response = client.get(reverse("setup_terms", args=[banadir.year.id]))

    assert response.status_code == 404


@pytest.mark.permissions
def test_a_term_cannot_be_added_to_another_schools_year(client, head, banadir):
    before = banadir.year.terms.count()

    client.post(
        reverse("setup_terms", args=[banadir.year.id]),
        {
            "name": "Injected",
            "sequence": 9,
            "start_date": "2026-09-01",
            "end_date": "2026-12-01",
        },
    )

    assert banadir.year.terms.count() == before


@pytest.mark.permissions
def test_another_schools_grading_scale_cannot_be_opened(client, head, banadir):
    response = client.get(reverse("setup_scale", args=[banadir.scale.id]))

    assert response.status_code == 404


@pytest.mark.permissions
def test_a_band_from_another_schools_scale_cannot_be_deleted(
    client, head, hodan, banadir
):
    """The band id arrives in a form, so it is re-filtered by scale."""
    victim = GradeBand.objects.create(
        scale=banadir.scale,
        letter="A",
        min_percentage=Decimal("80"),
        max_percentage=Decimal("100"),
    )

    client.post(
        reverse("setup_scale", args=[hodan.scale.id]),
        {"action": "remove", "band": victim.id},
    )

    assert GradeBand.objects.filter(pk=victim.pk).exists()


@pytest.mark.permissions
def test_only_this_schools_subjects_are_listed(client, head, hodan, banadir):
    Subject.objects.create(institution=banadir.institution, name="Astronomy")

    body = client.get(reverse("setup_subjects")).content.decode()

    assert "Astronomy" not in body


# ------------------------------------------------------------ adding rows


def test_a_year_can_be_added(client, head, hodan):
    client.post(
        reverse("setup_years"),
        {
            "name": "2027/2028",
            "start_date": "2027-09-01",
            "end_date": "2028-06-30",
            "is_current": "on",
        },
    )

    year = AcademicYear.objects.get(institution=hodan.institution, name="2027/2028")
    assert year.is_current


def test_a_class_lands_in_the_current_year(client, head, hodan):
    client.post(reverse("setup_classes"), {"name": "Form 3B"})

    classroom = ClassRoom.objects.get(name="Form 3B")
    assert classroom.academic_year == hodan.year


def test_a_subject_belongs_to_the_signed_in_school(client, head, hodan):
    client.post(reverse("setup_subjects"), {"name": "Chemistry", "code": "CHEM"})

    assert Subject.objects.get(name="Chemistry").institution == hodan.institution


def test_a_grading_scale_can_be_added(client, head, hodan):
    client.post(reverse("setup_scales"), {"name": "Senior scale", "is_default": "on"})

    scale = GradingScale.objects.get(institution=hodan.institution, name="Senior scale")
    assert scale.is_default


def test_a_band_can_be_added_and_removed(client, head, hodan):
    client.post(
        reverse("setup_scale", args=[hodan.scale.id]),
        {
            "letter": "A",
            "min_percentage": "80",
            "max_percentage": "100",
            "remark": "Top",
        },
    )
    band = GradeBand.objects.get(scale=hodan.scale, letter="A")

    client.post(
        reverse("setup_scale", args=[hodan.scale.id]),
        {"action": "remove", "band": band.id},
    )

    assert not GradeBand.objects.filter(pk=band.pk).exists()


# ------------------------------------------------------------- validation


def test_a_year_ending_before_it_starts_is_refused(client, head, hodan):
    before = AcademicYear.objects.count()

    response = client.post(
        reverse("setup_years"),
        {"name": "Backwards", "start_date": "2027-09-01", "end_date": "2027-01-01"},
    )

    assert AcademicYear.objects.count() == before
    assert "must end after it starts" in response.content.decode()


def test_a_duplicate_year_name_is_refused(client, head, hodan):
    before = AcademicYear.objects.count()

    client.post(
        reverse("setup_years"),
        {
            "name": hodan.year.name,
            "start_date": "2030-09-01",
            "end_date": "2031-06-30",
        },
    )

    assert AcademicYear.objects.count() == before


def test_a_name_differing_only_in_case_is_refused(client, head, hodan):
    """The database constraint is case-sensitive, so without the form's
    own check a school ends up with two subjects on every report card."""
    Subject.objects.create(institution=hodan.institution, name="Biology")
    before = Subject.objects.count()

    client.post(reverse("setup_subjects"), {"name": "biology", "code": ""})

    assert Subject.objects.count() == before


def test_the_same_name_at_another_school_is_allowed(client, head, hodan, banadir):
    """Two schools may both teach Biology. A uniqueness check that did
    not know whose school it was would call this a duplicate."""
    Subject.objects.create(institution=banadir.institution, name="Biology")

    client.post(reverse("setup_subjects"), {"name": "Biology", "code": ""})

    assert Subject.objects.filter(
        institution=hodan.institution, name="Biology"
    ).exists()


def test_a_term_running_past_the_end_of_its_year_is_refused(client, head, hodan):
    """Not something the database would catch, and it puts marks in a
    term the year they belong to does not contain."""
    before = Term.objects.count()

    response = client.post(
        reverse("setup_terms", args=[hodan.year.id]),
        {
            "name": "Stray",
            "sequence": 2,
            "start_date": "2029-01-01",
            "end_date": "2029-06-01",
        },
    )

    assert Term.objects.count() == before
    assert "cannot end after" in response.content.decode()


def test_a_term_starting_before_its_year_is_refused(client, head, hodan):
    """The other end of the same rule. Tested separately because a check
    written for one boundary and copied for the other is exactly where a
    comparison ends up pointing the wrong way."""
    before = Term.objects.count()

    response = client.post(
        reverse("setup_terms", args=[hodan.year.id]),
        {
            "name": "Too early",
            "sequence": 2,
            "start_date": "2025-01-01",
            "end_date": "2026-12-01",
        },
    )

    assert Term.objects.count() == before
    assert "cannot start before" in response.content.decode()


def test_a_repeated_term_sequence_is_refused(client, head, hodan):
    before = Term.objects.count()

    client.post(
        reverse("setup_terms", args=[hodan.year.id]),
        {
            "name": "Another first term",
            "sequence": hodan.term.sequence,
            "start_date": "2026-09-02",
            "end_date": "2026-12-01",
        },
    )

    assert Term.objects.count() == before


def test_a_duplicate_class_name_in_the_same_year_is_refused(client, head, hodan):
    before = ClassRoom.objects.count()

    client.post(reverse("setup_classes"), {"name": hodan.classroom.name})

    assert ClassRoom.objects.count() == before


def test_a_band_whose_top_is_below_its_bottom_is_refused(client, head, hodan):
    before = GradeBand.objects.count()

    client.post(
        reverse("setup_scale", args=[hodan.scale.id]),
        {"letter": "X", "min_percentage": "80", "max_percentage": "20", "remark": ""},
    )

    assert GradeBand.objects.count() == before


def test_an_overlapping_band_is_refused(client, head, hodan):
    """An overlap is worse than a gap: it silently gives two answers, and
    which one a student gets depends on row order."""
    GradeBand.objects.create(
        scale=hodan.scale,
        letter="B",
        min_percentage=Decimal("60"),
        max_percentage=Decimal("79.99"),
    )
    before = GradeBand.objects.count()

    response = client.post(
        reverse("setup_scale", args=[hodan.scale.id]),
        {"letter": "C", "min_percentage": "70", "max_percentage": "85", "remark": ""},
    )

    assert GradeBand.objects.count() == before
    assert "overlaps" in response.content.decode()


# ------------------------------------------------------------- readiness


def test_a_bare_school_is_told_to_start_with_a_year(db):
    from schools.models import Institution

    empty = Institution.objects.create(name="Brand New School", short_name="BNS")

    state = readiness(empty)

    assert not state["ready"]
    assert "No academic year" in str(state["problems"][0]["what"])


def test_a_gap_in_the_grading_scale_is_reported(head, hodan):
    """The failure this screen exists to catch: one mistyped digit and a
    whole band of students silently receives no grade."""
    GradeBand.objects.create(
        scale=hodan.scale,
        letter="A",
        min_percentage=Decimal("80"),
        max_percentage=Decimal("100"),
    )
    # Nothing covers 0–80.

    problems = [str(p["what"]) for p in readiness(hodan.institution)["problems"]]

    assert any("has a gap" in problem for problem in problems)


def test_a_class_nobody_teaches_is_reported(head, hodan):
    """Invisible from every other screen, and marks cannot be entered."""
    ClassRoom.objects.create(academic_year=hodan.year, name="Form 4Z")

    problems = [str(p["what"]) for p in readiness(hodan.institution)["problems"]]

    assert any("Form 4Z" in problem for problem in problems)


def test_a_complete_school_reports_ready(head, hodan):
    """The positive case. Without it these checks could all be stuck on
    'not ready' and every test above would still pass."""
    hodan.add_teacher("hodan-tch")
    GradeBand.objects.create(
        scale=hodan.scale,
        letter="P",
        min_percentage=Decimal("0"),
        max_percentage=Decimal("100"),
    )
    hodan.scale.is_default = True
    hodan.scale.save()

    state = readiness(hodan.institution)

    assert state["ready"], [str(p["what"]) for p in state["problems"]]


def test_the_overview_lists_what_is_missing(client, head, hodan):
    response = client.get(reverse("setup_overview"))

    assert response.status_code == 200
    assert "Before marks can be recorded" in response.content.decode()


# --------------------------------------------------------------- demo mode


def test_the_public_demo_cannot_add_a_subject(settings, client, head, hodan):
    settings.DEMO_MODE = True
    before = Subject.objects.count()

    client.post(reverse("setup_subjects"), {"name": "Smuggled", "code": ""})

    assert Subject.objects.count() == before


# ------------------------------------------------------------- date input


def test_dates_render_as_date_pickers(client, head, hodan):
    """A school typing a date by hand into a text box is a school typing
    it in a format the parser rejects."""
    body = client.get(reverse("setup_years")).content.decode()

    assert 'type="date"' in body


def test_an_existing_year_prefills_its_dates_correctly(hodan):
    """A date widget only shows a value it receives as YYYY-MM-DD."""
    from schools.setup_forms import AcademicYearForm

    form = AcademicYearForm(institution=hodan.institution, instance=hodan.year)

    assert str(hodan.year.start_date) in form["start_date"].as_widget()


def test_the_year_fixture_dates_are_what_the_tests_assume(hodan):
    """Guards the term-boundary tests above: they assert a term starting
    in 2029 is outside the year, which is only meaningful while the year
    itself does not reach that far."""
    assert hodan.year.start_date == date(2026, 9, 1)
    assert hodan.year.end_date == date(2027, 6, 30)
