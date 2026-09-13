"""Drawing a report card as a PDF.

A browser's Print-to-PDF already produces a usable card, so this exists
for the thing printing cannot do: hand a school a file. A head teacher
emailing a term's reports to parents, or keeping them for the year, needs
an object they can attach and store — and "press Ctrl+P and choose Save
as PDF" is not an instruction that survives contact with forty parents.

**Why not render the HTML.** WeasyPrint would turn the existing template
into a PDF and the two could never drift apart, which is the better
design on paper. It needs Pango and Cairo installed on the server, and
this project's deployment has already failed three times for
configuration reasons. A pure-Python library cannot fail that way: it is
a wheel, it installs anywhere Python does, and it cannot take the site
down. The cost is that this module draws the layout itself, and the
guard against drift is `_build` — the PDF and the HTML are built from
the same dictionary, so a figure cannot differ between them even if the
arrangement does.

**Why no logo or photograph.** Nothing here loads an image. A school's
crest would have to be uploaded, stored and served, and the only thing
it adds is decoration on a document whose value is its numbers.
"""

import unicodedata

from django.http import HttpResponse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from fpdf import FPDF

# A4 in millimetres, and the margin a school's hole-punch needs.
PAGE_WIDTH = 210
MARGIN = 15
CONTENT_WIDTH = PAGE_WIDTH - (MARGIN * 2)

# Helvetica is one of the fourteen fonts every PDF reader is required to
# have. Embedding a nicer one would add roughly a third of a megabyte to
# each card, which matters when a school sends forty of them over a
# mobile connection.
FONT = "Helvetica"

# The built-in fonts carry a single-byte encoding, so they cannot draw
# every character a name might contain. cp1252 rather than fpdf2's
# latin-1 default because it covers the typographic punctuation that
# ends up in this project's own labels — the em dash above all.
ENCODING = "cp1252"

INK = (22, 48, 44)
MUTED = (90, 112, 107)
RULE = (200, 216, 212)
WASH = (233, 246, 242)


def drawable(text) -> str:
    """Return text the built-in font can actually draw.

    fpdf2 raises when a character falls outside the font's encoding, and
    a raised exception here is not a mangled letter — it is an error page
    where a child's report card should be, for every pupil in the class.
    That trade is never worth taking, so anything unencodable is reduced
    rather than refused.

    Accents come off by decomposition, which is lossy but readable: a
    name that cannot be drawn with its diacritic is still the right name
    without it. Only a character with no Latin form at all falls through
    to "?", and at that point the school has a font problem this module
    cannot solve on its own.
    """
    text = str(text)
    if _encodable(text):
        return text

    out = []
    for character in text:
        if _encodable(character):
            out.append(character)
            continue

        stripped = "".join(
            part
            for part in unicodedata.normalize("NFKD", character)
            if not unicodedata.combining(part)
        )
        out.append(stripped if stripped and _encodable(stripped) else "?")

    return "".join(out)


def _encodable(text: str) -> bool:
    try:
        text.encode(ENCODING)
    except UnicodeEncodeError:
        return False
    return True


class ReportCard(FPDF):
    """One student's term, on one page."""

    def __init__(self, card):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.card = card
        self.core_fonts_encoding = ENCODING
        self.set_auto_page_break(auto=True, margin=MARGIN)
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_title(self._title())

    def normalize_text(self, text: str) -> str:
        """Every piece of text fpdf2 draws passes through here.

        Sanitising at this single point rather than at each `cell` call
        is deliberate: a call site added later cannot forget to do it.
        """
        return super().normalize_text(drawable(text))

    def _title(self):
        return (
            f"{self.card['student'].full_name} — "
            f"{self.card['term'].name} {self.card['term'].academic_year}"
        )

    # ---------------------------------------------------------- header

    def header(self):
        institution = self.card["institution"]

        self.set_font(FONT, "B", 16)
        self.set_text_color(*INK)
        self.cell(0, 8, institution.name, new_x="LMARGIN", new_y="NEXT")

        if institution.address:
            self.set_font(FONT, "", 9)
            self.set_text_color(*MUTED)
            self.cell(0, 5, institution.address, new_x="LMARGIN", new_y="NEXT")

        self.set_font(FONT, "B", 11)
        self.set_text_color(*INK)
        self.cell(0, 7, _("Report card"), new_x="LMARGIN", new_y="NEXT")

        self.set_draw_color(*RULE)
        self.line(MARGIN, self.get_y() + 1, PAGE_WIDTH - MARGIN, self.get_y() + 1)
        self.ln(5)

    def footer(self):
        self.set_y(-14)
        self.set_font(FONT, "", 7.5)
        self.set_text_color(*MUTED)

        if not self.card["released"]:
            # A card a school is still checking must say so on the page,
            # not only on the screen it was downloaded from. A file
            # outlives its context: it gets forwarded, printed and filed,
            # and by then nobody remembers it was provisional.
            self.set_text_color(163, 45, 45)
            self.cell(
                0,
                4,
                _("PROVISIONAL — these results have not been published."),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            self.set_text_color(*MUTED)

        self.cell(
            0,
            4,
            _("Generated by GradeVault. Page %(page)s") % {"page": self.page_no()},
        )

    # ------------------------------------------------------ who it is for

    def identity(self):
        card = self.card
        rows = [
            (_("Pupil"), card["student"].full_name),
            (_("Sign-in number"), card["student"].user.username),
            (_("Admission number"), card["student"].admission_number),
            (_("Class"), card["classroom"].name),
            (_("Term"), f"{card['term'].name} · {card['term'].academic_year}"),
        ]

        self.set_font(FONT, "", 10)
        for label, value in rows:
            self.set_text_color(*MUTED)
            self.cell(45, 6, str(label))
            self.set_text_color(*INK)
            self.set_font(FONT, "B", 10)
            self.cell(0, 6, str(value), new_x="LMARGIN", new_y="NEXT")
            self.set_font(FONT, "", 10)
        self.ln(3)

    # ----------------------------------------------------------- marks

    def subjects(self):
        widths = [70, 30, 30, 20, CONTENT_WIDTH - 150]
        headers = [
            _("Subject"),
            _("Marks"),
            _("Percentage"),
            _("Grade"),
            _("Remark"),
        ]

        self.set_font(FONT, "B", 9)
        self.set_fill_color(*WASH)
        self.set_text_color(*INK)
        for width, header in zip(widths, headers, strict=True):
            self.cell(width, 7, str(header), fill=True)
        self.ln()

        self.set_font(FONT, "", 9.5)
        for row in self.card["rows"]:
            subject = row["subject"]
            grade = row["grade"]

            if subject.has_any_mark:
                marks = f"{subject.marks_obtained:.2f} / {subject.marks_available:.2f}"
                percentage = f"{subject.percentage}%"
            else:
                marks = _("not marked")
                percentage = "—"

            self.set_text_color(*INK)
            self.cell(widths[0], 6.5, subject.subject_name)
            self.cell(widths[1], 6.5, marks, align="R")
            self.cell(widths[2], 6.5, percentage, align="R")
            self.cell(widths[3], 6.5, grade.letter if grade else "—", align="R")
            self.set_text_color(*MUTED)
            self.cell(widths[4], 6.5, grade.remark if grade else "")
            self.ln()

        self._totals(widths)

    def _totals(self, widths):
        result = self.card["result"]
        grade = self.card["grade"]

        self.set_draw_color(*RULE)
        self.line(MARGIN, self.get_y(), PAGE_WIDTH - MARGIN, self.get_y())
        self.ln(1)

        self.set_font(FONT, "B", 10)
        self.set_text_color(*INK)
        self.cell(widths[0], 7, str(_("Total")))
        self.cell(
            widths[1],
            7,
            f"{result.marks_obtained:.2f} / {result.marks_available:.2f}",
            align="R",
        )
        average = result.average_percentage
        self.cell(
            widths[2], 7, f"{average}%" if average is not None else "—", align="R"
        )
        self.cell(widths[3], 7, grade.letter if grade else "—", align="R")
        self.cell(widths[4], 7, "")
        self.ln(10)

    # --------------------------------------------------------- verdict

    def verdict(self):
        card = self.card
        result = card["result"]
        grade = card["grade"]

        place = card["place"]
        position = f"{place} {_('of')} {card['out_of']}" if place else "—"

        pairs = [
            (
                _("Average"),
                f"{result.average_percentage}%"
                if result.average_percentage is not None
                else "—",
            ),
            (_("Grade"), grade.letter if grade else "—"),
            (_("Position in class"), position),
            (
                _("Subjects passed"),
                f"{card['passed']} {_('of')} {len(card['rows'])}",
            ),
        ]

        self.set_font(FONT, "", 10)
        for label, value in pairs:
            self.set_text_color(*MUTED)
            self.cell(45, 6.5, str(label))
            self.set_font(FONT, "B", 11)
            self.set_text_color(*INK)
            self.cell(0, 6.5, str(value), new_x="LMARGIN", new_y="NEXT")
            self.set_font(FONT, "", 10)

        if grade and grade.remark:
            self.ln(1)
            self.set_text_color(*MUTED)
            self.cell(45, 6.5, str(_("Remarks")))
            self.set_text_color(*INK)
            self.cell(0, 6.5, grade.remark, new_x="LMARGIN", new_y="NEXT")

        self.ln(8)

    # ------------------------------------------------------ signatures

    def signatures(self):
        """Lines for the people who have to stand behind the figures.

        A report card is a claim a school makes to a family, and in
        practice that claim is signed. Leaving the lines off would make
        the file unusable for the purpose schools actually print them
        for.
        """
        self.set_font(FONT, "", 9)
        self.set_text_color(*MUTED)

        width = CONTENT_WIDTH / 2 - 5

        # Anchored near the foot of the page, which is where a report
        # card is signed — but never above the marks, so a class with a
        # long subject list pushes the lines down instead of printing
        # them through its own table.
        rule = max(self.get_y() + 10, self.h - 45)

        for index, label in enumerate((_("Class teacher"), _("Head teacher"))):
            left = MARGIN + index * (width + 10)
            self.set_draw_color(*RULE)
            self.line(left, rule, left + width, rule)
            self.set_xy(left, rule)
            self.cell(width, 5, str(label))

    def build(self):
        self.add_page()
        self.identity()
        self.subjects()
        self.verdict()
        self.signatures()
        return self


def filename_for(card) -> str:
    """A name a school can file without renaming it.

    Slugified because these end up in folders and email attachments, and
    a Somali name with an apostrophe in it should not produce a file that
    one operating system accepts and another refuses.
    """
    return (
        f"{slugify(card['student'].full_name)}"
        f"-{slugify(card['term'].name)}"
        f"-{slugify(str(card['term'].academic_year))}.pdf"
    )


def render_pdf(card) -> HttpResponse:
    """Turn one built card into a downloadable PDF response."""
    document = ReportCard(card).build()

    response = HttpResponse(bytes(document.output()), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename_for(card)}"'
    return response
