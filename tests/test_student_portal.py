"""Tests for the student's results page.

The page now shows one term at a time, chosen from a list, and reports a
pass or fail and a running average alongside it. Two of those are worth
testing carefully.

**The term comes from the address bar.** A selector that fetches whatever
id it is handed would let a student read a term their school has not
published — the exact failure the published flag exists to prevent,
reintroduced by a convenience feature.

**Averaging across terms is not averaging the averages.** Terms carry
different numbers of marks, and averaging the averages weights a short
term equally with a long one, which quietly misreports the year.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from factories import PASSWORD
from schools.models import Assessment, GradeBand, Score, Term
from schools.results import term_result


@pytest.fixture
def graded(hodan):
    """Give the school's scale real bands.

    The shared fixture creates a scale with no bands at all, which grades
    nothing. Without this every verdict below would read "not yet
    graded" and the pass and fail tests would agree with each other.
    """
    GradeBand.objects.create(
        scale=hodan.scale,
        letter="A",
        min_percentage=Decimal("50"),
        max_percentage=Decimal("100"),
        remark="Pass",
    )
    GradeBand.objects.create(
        scale=hodan.scale,
        letter="F",
        min_percentage=Decimal("0"),
        max_percentage=Decimal("49.99"),
        remark="Fail",
    )
    return hodan.scale


@pytest.fixture
def student(hodan):
    """A student at Hodan with a published, marked first term."""
    enrollment = hodan.add_student("Amina", "Yusuf", marks=32)
    hodan.term.is_published = True
    hodan.term.save(update_fields=["is_published"])
    return enrollment


@pytest.fixture
def second_term(hodan, student):
    """A second, published term with its own assessment and mark."""
    term = Term.objects.create(
        academic_year=hodan.year,
        name="Term 2",
        sequence=2,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 6, 1),
        is_published=True,
    )
    assessment = Assessment.objects.create(
        term=term,
        subject=hodan.subject,
        classroom=hodan.classroom,
        name="Final",
        max_marks=Decimal("60"),
    )
    Score.objects.create(enrollment=student, assessment=assessment, marks=Decimal("30"))
    return term


def sign_in(client, enrollment):
    client.login(username=enrollment.student.user.username, password=PASSWORD)


# ------------------------------------------------------- choosing a term


def test_the_latest_published_term_is_shown_by_default(
    client, hodan, student, second_term
):
    """A student opening this wants the term they have just sat."""
    sign_in(client, student)

    body = client.get(reverse("student_results")).content.decode()

    assert "Term 2" in body


def test_an_earlier_term_can_be_chosen(client, hodan, student, second_term):
    sign_in(client, student)

    response = client.get(reverse("student_results"), {"term": hodan.term.id})

    assert response.status_code == 200
    assert response.context["selected"] == hodan.term


@pytest.mark.permissions
def test_an_unpublished_term_cannot_be_read_from_the_address_bar(
    client, hodan, student
):
    """The security case this feature introduces.

    Putting an unpublished term's id in the URL must not reveal it. The
    requested id is looked up inside the published set rather than
    fetched on its own, so there is nothing to find.
    """
    hidden = Term.objects.create(
        academic_year=hodan.year,
        name="Secret Term",
        sequence=3,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 6, 1),
        is_published=False,
    )
    sign_in(client, student)

    response = client.get(reverse("student_results"), {"term": hidden.id})
    body = response.content.decode()

    assert response.context["selected"] != hidden
    assert "Secret Term" not in body


@pytest.mark.permissions
def test_another_classs_term_id_is_refused(client, hodan, student, banadir):
    """A term id from another school entirely."""
    sign_in(client, student)

    response = client.get(reverse("student_results"), {"term": banadir.term.id})

    assert response.context["selected"] != banadir.term


def test_a_nonsense_term_id_falls_back_rather_than_erroring(client, hodan, student):
    response_client = client
    sign_in(response_client, student)

    response = response_client.get(reverse("student_results"), {"term": "not-a-number"})

    assert response.status_code == 200
    assert response.context["selected"] == hodan.term


# ------------------------------------------------------------ pass or fail


def test_a_passing_term_reports_pass(client, hodan, student, graded):
    """32 out of 40 is 80%, comfortably above the fail band."""
    sign_in(client, student)

    body = client.get(reverse("student_results")).content.decode()

    assert "PASS" in body
    assert "FAIL" not in body


def test_a_failing_term_reports_fail(client, hodan, graded):
    enrollment = hodan.add_student("Liban", "Adan", marks=8)  # 8/40 = 20%
    hodan.term.is_published = True
    hodan.term.save(update_fields=["is_published"])
    sign_in(client, enrollment)

    body = client.get(reverse("student_results")).content.decode()

    assert "FAIL" in body


def test_an_unmarked_term_reports_neither(client, hodan, graded):
    """Not knowing is not the same as failing, and a student shown FAIL
    because nobody has marked them yet would be wronged by the system."""
    enrollment = hodan.add_student("Sagal", "Omar")  # no marks at all
    hodan.term.is_published = True
    hodan.term.save(update_fields=["is_published"])
    sign_in(client, enrollment)

    body = client.get(reverse("student_results")).content.decode()

    assert "Not yet graded" in body
    assert ">PASS<" not in body
    assert ">FAIL<" not in body


def test_is_pass_is_none_without_a_grading_scale(hodan, student):
    """A school that has not configured a scale gets 'not known', not a
    verdict invented from nothing."""
    result = term_result(student, hodan.term)

    assert result.is_pass(None) is None


# -------------------------------------------------------------- cumulative


def test_the_running_average_is_weighted_by_marks_not_by_term(
    client, hodan, student, second_term
):
    """Term 1 is 32/40, Term 2 is 30/60. Weighted: 62/100 = 62%.
    Averaging the two term averages would give (80 + 50) / 2 = 65%,
    overstating the year by three points because the shorter term was
    counted as heavily as the longer one.
    """
    sign_in(client, student)

    cumulative = client.get(reverse("student_results")).context["cumulative"]

    assert cumulative["terms"] == 2
    assert cumulative["average"] == Decimal("62.00")


def test_the_running_average_covers_only_published_terms(
    client, hodan, student, second_term
):
    """An unpublished term must not leak through the cumulative figure,
    which would otherwise disclose marks the school is still holding."""
    second_term.is_published = False
    second_term.save(update_fields=["is_published"])
    sign_in(client, student)

    cumulative = client.get(reverse("student_results")).context["cumulative"]

    assert cumulative["terms"] == 1
    assert cumulative["average"] == Decimal("80.00")


def test_a_student_with_no_marks_has_no_running_average(client, hodan):
    enrollment = hodan.add_student("Nasra", "Farah")
    hodan.term.is_published = True
    hodan.term.save(update_fields=["is_published"])
    sign_in(client, enrollment)

    cumulative = client.get(reverse("student_results")).context["cumulative"]

    assert cumulative["average"] is None


# ------------------------------------------------------------- the shell


def test_the_page_offers_a_result_slip(client, hodan, student):
    sign_in(client, student)

    body = client.get(reverse("student_results")).content.decode()

    assert reverse("my_report_card", args=[hodan.term.id]) in body


def test_top_of_class_is_marked(client, hodan, graded):
    """One student in the class, so they are first in it."""
    enrollment = hodan.add_student("Hodan", "Ali", marks=38)
    hodan.term.is_published = True
    hodan.term.save(update_fields=["is_published"])
    sign_in(client, enrollment)

    body = client.get(reverse("student_results")).content.decode()

    assert "Top of class" in body
