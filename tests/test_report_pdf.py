"""Tests for the downloadable report card.

The PDF hangs off the same two views as the HTML card, behind the same
checks. That is the design worth protecting: a second entry point would
be a second place for the permission rules to be got right, and the one
that gets forgotten is the one that leaks.

So most of these tests are the permission tests again, aimed at
`?format=pdf`. A guard that protects the page but not the download is
not a guard.
"""

import re
import zlib
from decimal import Decimal

import pytest
from django.urls import reverse

from factories import PASSWORD
from schools.models import GradeBand
from schools.report_pdf import drawable, filename_for


def text_of(pdf: bytes) -> str:
    """The words actually drawn on the page.

    fpdf2 compresses its content streams, so searching the raw bytes for
    a word finds nothing whether or not the word is there — an assertion
    that can only fail is no better than one that can only pass.
    """
    parts = []
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            parts.append(zlib.decompress(stream))
        except zlib.error:
            parts.append(stream)  # uncompressed, e.g. font data
    return b"\n".join(parts).decode("latin-1")


@pytest.fixture
def graded(hodan):
    GradeBand.objects.create(
        scale=hodan.scale,
        letter="A",
        min_percentage=Decimal("50"),
        max_percentage=Decimal("100"),
        remark="Very good",
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
def pupil(hodan):
    """A pupil with a mark, in a published term."""
    enrolment = hodan.add_student("Amina", "Yusuf", marks=32)
    hodan.term.is_published = True
    hodan.term.save(update_fields=["is_published"])
    return enrolment


def pdf_url(term):
    return f"{reverse('my_report_card', args=[term.id])}?format=pdf"


# ------------------------------------------------------------ it works


def test_a_student_can_download_their_own_card(client, hodan, pupil, graded):
    client.login(username=pupil.student.user.username, password=PASSWORD)

    response = client.get(pdf_url(hodan.term))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")

    # A file that opens but says nothing about the child is no use, so
    # check the figures reached the page rather than only the header.
    drawn = text_of(response.content)
    assert "Amina" in drawn
    assert hodan.institution.name in drawn
    assert "80.00%" in drawn  # 32 of the 40 marks the fixture's paper carries
    assert "A" in drawn


def test_the_file_is_offered_as_a_download(client, hodan, pupil, graded):
    """Inline would open it in the browser, which is the print view the
    school already has. The point of this is a file they can keep."""
    client.login(username=pupil.student.user.username, password=PASSWORD)

    response = client.get(pdf_url(hodan.term))

    assert "attachment" in response["Content-Disposition"]
    assert ".pdf" in response["Content-Disposition"]


def test_the_filename_can_be_filed_without_renaming(hodan, pupil, graded):
    """These end up in folders and email attachments, so a name with an
    apostrophe in it must not produce a file one system refuses."""
    from schools.report_cards import _build

    card = _build(pupil, hodan.term, released=True)
    name = filename_for(card)

    assert name.endswith(".pdf")
    assert " " not in name
    assert "amina" in name.lower()


def test_the_pdf_is_not_empty(client, hodan, pupil, graded):
    """A zero-byte or header-only PDF opens as a blank page, which looks
    like the school's fault rather than the software's."""
    client.login(username=pupil.student.user.username, password=PASSWORD)

    response = client.get(pdf_url(hodan.term))

    assert len(response.content) > 1000


def test_a_full_timetable_of_subjects_fits(client, hodan, pupil, graded):
    """Twelve subjects is an ordinary secondary timetable, not an edge
    case, and the signature lines are anchored near the foot of the
    page — so the one thing to prove is that a long table pushes them
    down rather than printing through them."""
    from decimal import Decimal as D

    from schools.models import Assessment, Score, Subject

    for name in (
        "Arabic",
        "Biology",
        "Chemistry",
        "English",
        "Geography",
        "History",
        "Islamic Studies",
        "Physics",
        "Somali",
        "Business Studies",
        "Agriculture",
    ):
        subject = Subject.objects.create(institution=hodan.institution, name=name)
        assessment = Assessment.objects.create(
            term=hodan.term,
            subject=subject,
            classroom=hodan.classroom,
            name="Mid-term",
            max_marks=D("40"),
        )
        Score.objects.create(enrollment=pupil, assessment=assessment, marks=D("30"))

    client.login(username=pupil.student.user.username, password=PASSWORD)

    response = client.get(pdf_url(hodan.term))

    assert response.status_code == 200
    drawn = text_of(response.content)
    for name in ("Arabic", "Agriculture", "Mathematics"):
        assert name in drawn
    assert "Class teacher" in drawn
    assert "Head teacher" in drawn


def test_a_card_with_no_grading_scale_still_renders(client, hodan, pupil):
    """No bands configured means no letter grades. The card must still
    produce a file rather than raising — a school mid-setup should get a
    sparse report, not an error page."""
    client.login(username=pupil.student.user.username, password=PASSWORD)

    response = client.get(pdf_url(hodan.term))

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_an_unmarked_pupil_still_renders(client, hodan, graded):
    enrolment = hodan.add_student("Sagal", "Omar")  # no marks at all
    hodan.term.is_published = True
    hodan.term.save(update_fields=["is_published"])
    client.login(username=enrolment.student.user.username, password=PASSWORD)

    response = client.get(pdf_url(hodan.term))

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


# ------------------------------------------------------- who may download


@pytest.mark.permissions
def test_an_unpublished_term_cannot_be_downloaded_by_a_student(client, hodan, graded):
    """The guard that protects the page must protect the download. A
    student downloading a term their school has not released would be the
    published flag defeated by a query parameter."""
    enrolment = hodan.add_student("Amina", "Yusuf", marks=32)
    assert not hodan.term.is_published
    client.login(username=enrolment.student.user.username, password=PASSWORD)

    response = client.get(pdf_url(hodan.term))

    assert response.status_code == 403
    assert not response.content.startswith(b"%PDF-")


@pytest.mark.permissions
def test_a_visitor_who_is_not_signed_in_gets_nothing(client, hodan, pupil, graded):
    response = client.get(pdf_url(hodan.term))

    assert response.status_code == 302
    assert not response.content.startswith(b"%PDF-")


@pytest.mark.permissions
def test_a_teacher_cannot_download_a_card_for_a_class_they_do_not_teach(
    client, hodan, pupil, graded
):
    """The teacher route checks the class against the assignment. The
    PDF must be checked the same way."""
    from schools.models import TeachingAssignment

    teacher = hodan.add_teacher("hodan-tch")
    TeachingAssignment.objects.filter(teacher=teacher).delete()
    client.login(username=teacher.user.username, password=PASSWORD)

    url = reverse(
        "class_report_card",
        args=[hodan.classroom.id, hodan.term.id, pupil.id],
    )
    response = client.get(f"{url}?format=pdf")

    assert response.status_code == 403
    assert not response.content.startswith(b"%PDF-")


@pytest.mark.permissions
def test_a_teacher_who_does_teach_the_class_can_download(client, hodan, pupil, graded):
    teacher = hodan.add_teacher("hodan-tch")  # assigned to this class
    client.login(username=teacher.user.username, password=PASSWORD)

    url = reverse(
        "class_report_card",
        args=[hodan.classroom.id, hodan.term.id, pupil.id],
    )
    response = client.get(f"{url}?format=pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


@pytest.mark.permissions
def test_an_enrolment_from_another_class_is_refused(client, hodan, graded, banadir):
    """The enrolment id arrives in the URL, so it is matched against the
    class as well as by id."""
    teacher = hodan.add_teacher("hodan-tch")
    victim = banadir.add_student("Hodan", "Ali", marks=30)
    client.login(username=teacher.user.username, password=PASSWORD)

    url = reverse(
        "class_report_card",
        args=[hodan.classroom.id, hodan.term.id, victim.id],
    )
    response = client.get(f"{url}?format=pdf")

    assert response.status_code == 404


# ------------------------------------------------------------ honesty


def test_a_staff_preview_of_an_unpublished_term_is_marked_provisional(
    client, hodan, graded
):
    """A file outlives the screen it came from: it gets forwarded,
    printed and filed, and by then nobody remembers it was a draft."""
    enrolment = hodan.add_student("Amina", "Yusuf", marks=32)
    teacher = hodan.add_teacher("hodan-tch")
    assert not hodan.term.is_published
    client.login(username=teacher.user.username, password=PASSWORD)

    url = reverse(
        "class_report_card",
        args=[hodan.classroom.id, hodan.term.id, enrolment.id],
    )
    response = client.get(f"{url}?format=pdf")

    assert response.status_code == 200
    assert "PROVISIONAL" in text_of(response.content)


def test_a_published_card_is_not_marked_provisional(client, hodan, pupil, graded):
    client.login(username=pupil.student.user.username, password=PASSWORD)

    response = client.get(pdf_url(hodan.term))

    assert "PROVISIONAL" not in text_of(response.content)


# ------------------------------------------------------- awkward names


def test_a_name_the_font_cannot_draw_still_produces_a_card(client, hodan, graded):
    """The built-in PDF fonts carry a single-byte encoding, and fpdf2
    raises on anything outside it. Raising here would not be a mangled
    letter — it would be an error page where a child's report card
    should be, and for a whole class at once if the school's roll
    happens to hold one such name."""
    enrolment = hodan.add_student("Ayşe", "Müller", marks=32)
    hodan.term.is_published = True
    hodan.term.save(update_fields=["is_published"])
    client.login(username=enrolment.student.user.username, password=PASSWORD)

    response = client.get(pdf_url(hodan.term))

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_an_accent_is_kept_where_the_font_has_it(client, hodan, graded):
    """Reducing a name that could have been drawn correctly would be
    damage the encoding did not require."""
    enrolment = hodan.add_student("Zoë", "Müller", marks=32)
    hodan.term.is_published = True
    hodan.term.save(update_fields=["is_published"])
    client.login(username=enrolment.student.user.username, password=PASSWORD)

    drawn = text_of(client.get(pdf_url(hodan.term)).content)

    assert "Zo\xeb" in drawn  # ë survives; cp1252 has it


def test_a_letter_with_no_latin_form_is_reduced_not_refused():
    """Arabic has no Latin decomposition, so it falls through to the
    placeholder. That is a real loss, and still better than refusing the
    document: the marks, the class and the term are all still readable."""
    assert drawable("Cumar") == "Cumar"
    assert drawable("—") == "—"  # cp1252 has the em dash
    assert drawable("Zoë") == "Zoë"
    assert drawable("Ayşe") == "Ayse"  # ş decomposes to s
    assert drawable("عمر") == "???"


# ---------------------------------------------------------- unchanged


def test_the_html_card_still_works(client, hodan, pupil, graded):
    """Adding a download must not have changed the page it hangs off."""
    client.login(username=pupil.student.user.username, password=PASSWORD)

    response = client.get(reverse("my_report_card", args=[hodan.term.id]))

    assert response.status_code == 200
    assert "text/html" in response["Content-Type"]
