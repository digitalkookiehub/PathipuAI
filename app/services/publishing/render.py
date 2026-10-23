"""Draw a Publication as a PDF: A4, shaped Indic text, cover, optional contents page, headings, page numbers."""

from types import SimpleNamespace
from typing import Any

from fpdf import FPDF
from fpdf.errors import FPDFException
from fpdf.fonts import FontFace

from app.config import SUPPORTED_LANGUAGES
from app.services.publishing.fonts import LATIN, fallback_families, family_for, register_fonts
from app.services.publishing.model import Block, Publication, Section

MARGIN_X = 20
MARGIN_TOP = 22
MARGIN_BOTTOM = 22
BODY_SIZE = 11.5
BODY_LINE = 7.2
SOURCE_SIZE = 10.5
HEADING_SIZE = 20
SECOND_HEADING_SIZE = 16
GRAY = (95, 95, 95)
LIGHT_GRAY = (140, 140, 140)


def _name(code: str) -> str:
    return SUPPORTED_LANGUAGES.get(code, (code,))[0]


class _BookPDF(FPDF):
    """An A4 book with a page number at the bottom of every page except the cover."""

    def __init__(self, sample: bool) -> None:
        super().__init__(format="A4")
        self.sample = sample

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_font(LATIN, "", 9)
        self.set_text_color(*LIGHT_GRAY)
        label = f"SAMPLE PREVIEW  ·  {self.page_no()}" if self.sample else str(self.page_no())
        self.cell(0, 8, label, align="C")


def _edition_label(publication: Publication) -> str:
    source = _name(publication.source_language)
    languages = [_name(code) for code in publication.languages]
    if publication.kind == "source":
        return f"{source} edition"
    if publication.kind == "target":
        return f"{languages[0]} translation"
    return f"{source} and {', '.join(languages)}"


def _cover(pdf: _BookPDF, publication: Publication) -> None:
    pdf.add_page()
    pdf.set_y(75)
    pdf.set_text_color(0, 0, 0)
    family = family_for(publication.source_language)
    pdf.set_font(family, "B", 28)
    pdf.multi_cell(0, 14, publication.title, align="C", new_x="LMARGIN", new_y="NEXT")
    if publication.author:
        pdf.ln(12)
        pdf.set_font(family, "", 16)
        pdf.multi_cell(0, 9, publication.author, align="C", new_x="LMARGIN", new_y="NEXT")
    if publication.details:
        pdf.ln(14)
        pdf.set_font(family, "", 10)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(0, 6, publication.details, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(-60)
    pdf.set_font(LATIN, "", 12)
    pdf.set_text_color(*GRAY)
    label = _edition_label(publication) + ("  ·  Sample preview" if publication.sample else "")
    pdf.multi_cell(0, 7, label, align="C", new_x="LMARGIN", new_y="NEXT")


def _toc_renderer(families: list[str]) -> Any:
    def render(pdf: FPDF, outline: list[Any]) -> None:
        pdf.set_xy(pdf.l_margin, pdf.t_margin)  # the callback runs at the end of the document: start at the page top
        pdf.set_text_color(0, 0, 0)
        pdf.set_font(LATIN, "B", HEADING_SIZE)
        pdf.cell(0, 12, "Contents", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)
        with pdf.table(
            col_widths=(150, 20),
            borders_layout="NONE",
            text_align=("LEFT", "RIGHT"),
            line_height=8,
            first_row_as_headings=False,
        ) as table:
            for index, entry in enumerate(outline):
                row = table.row()
                row.cell(entry.name, style=FontFace(family=families[index], size_pt=12))
                row.cell(str(entry.page_number), style=FontFace(family=LATIN, size_pt=12))

    return render


def _block(pdf: _BookPDF, block: Block) -> None:
    family = family_for(block.language)
    if block.role == "label":
        pdf.ln(1)
        pdf.set_font(LATIN, "B", 9)
        pdf.set_text_color(*LIGHT_GRAY)
        pdf.multi_cell(0, 5, block.text.upper(), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.5)
        return
    if block.role == "pageref":
        pdf.set_font(LATIN, "", 8.5)
        pdf.set_text_color(*LIGHT_GRAY)
        pdf.multi_cell(0, 5, f"[ {block.text} ]", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        return
    if block.role == "source":
        pdf.set_font(family, "", SOURCE_SIZE)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(0, BODY_LINE - 0.8, block.text, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)
        return
    pdf.set_font(family, "", BODY_SIZE)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, BODY_LINE, block.text, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2.5)


def _section(pdf: _BookPDF, section: Section, new_page: bool = True) -> None:
    if new_page:
        pdf.add_page()
    pdf.start_section(section.headings[0].text, level=0)
    for index, heading in enumerate(section.headings):
        pdf.set_font(family_for(heading.language), "B", HEADING_SIZE if index == 0 else SECOND_HEADING_SIZE)
        pdf.set_text_color(0, 0, 0)
        pdf.multi_cell(0, 10, heading.text, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.ln(6)
    for block in section.blocks:
        _block(pdf, block)


def _new_pdf(publication: Publication) -> _BookPDF:
    pdf = _BookPDF(publication.sample)
    pdf.set_margins(MARGIN_X, MARGIN_TOP, MARGIN_X)
    pdf.set_auto_page_break(True, margin=MARGIN_BOTTOM)
    pdf.set_text_shaping(True)  # needed for correct Indic conjuncts and vowel signs
    register_fonts(pdf)
    # Latin letters/digits and the book's own script (kept-unchanged glossary terms) inside other scripts.
    pdf.set_fallback_fonts(fallback_families(publication.source_language))
    pdf.set_title(publication.title)
    pdf.set_author(publication.author)
    pdf.set_creator("PathippuAI")
    return pdf


def _contents_pages(publication: Publication, families: list[str]) -> int:
    """How many pages the contents need: draw them once on a scratch document with the same layout."""
    probe = _new_pdf(publication)
    probe.add_page()
    entries = [SimpleNamespace(name=s.headings[0].text, page_number=999) for s in publication.sections]
    _toc_renderer(families)(probe, entries)
    return len(probe.pages)


def _build(publication: Publication, contents_pages: int) -> _BookPDF:
    pdf = _new_pdf(publication)
    _cover(pdf, publication)
    has_contents = publication.toc and bool(publication.sections)
    if has_contents:
        families = [family_for(section.headings[0].language) for section in publication.sections]
        pdf.add_page()  # the contents get their own page(s) right after the cover
        pdf.insert_toc_placeholder(_toc_renderer(families), pages=contents_pages)
    for index, section in enumerate(publication.sections):
        # After the contents placeholder the library has already started the page for the first chapter.
        _section(pdf, section, new_page=not (has_contents and index == 0))
    return pdf


def render_pdf(publication: Publication) -> tuple[bytes, int]:
    """Create the PDF; returns its bytes and its page count."""
    contents_pages = 1
    if publication.toc and publication.sections:
        families = [family_for(section.headings[0].language) for section in publication.sections]
        contents_pages = _contents_pages(publication, families)
    for _attempt in range(4):
        try:
            pdf = _build(publication, contents_pages)
            return bytes(pdf.output()), len(pdf.pages)
        except FPDFException as exc:  # the library wants the exact number of contents pages
            message = str(exc)
            if "too many page breaks" in message:
                contents_pages += 1
            elif "too few page breaks" in message and contents_pages > 1:
                contents_pages -= 1
            else:
                raise
    raise FPDFException("Could not lay out the contents pages.")
