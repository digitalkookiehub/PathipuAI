"""What gets published: readiness checks and the assembled content of a PDF.

Only approved text is ever published. Source text comes from approved pages; a translation is published only when
every part of the chapter is approved, current (the Tamil did not change after it was translated) and was made by
a real translation service (never test-mode placeholders). Anything else blocks the export with a clear reason.
"""

import re
import sqlite3
from dataclasses import dataclass, field

from app.config import SUPPORTED_LANGUAGES, Settings
from app.services import chapters as chapter_service
from app.services.books import BookError
from app.services.publishing.fonts import missing_glyphs
from app.services.translation import review as translation_review
from app.services.translation import service as translation

KINDS = ("source", "target", "bilingual", "multilingual")
MAX_PROBLEM_LINES = 12
SAMPLE_PAGES = 2
SAMPLE_PARTS = 2
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
# A line that starts a numbered item: "5." or "5)", "10 நீ…" (a number, then a word) or a lettered item such as "அ)".
_NUMBERED_ITEM = re.compile(r"^\s*(?:\d{1,3}\s*[.)]|\d{1,3}\s+(?=[^\W\d_])|[^\W\d_]\))")


class PublishError(BookError):
    """The book cannot be published yet; the message says what to fix."""


@dataclass(frozen=True)
class Block:
    """One piece of text to draw. role: main, source (the original in a bilingual layout), label or pageref."""

    text: str
    language: str
    role: str = "main"


@dataclass
class Section:
    """A chapter: its heading lines (one per language shown) and its body."""

    headings: list[Block]
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Publication:
    """Everything the PDF renderer needs."""

    title: str
    author: str
    details: str
    source_language: str
    kind: str
    languages: list[str]
    sections: list[Section]
    toc: bool = True
    sample: bool = False


@dataclass(frozen=True)
class ReadyInfo:
    """Whether one output can be published, and what is in the way if not."""

    ready: bool
    problems: list[str]


@dataclass(frozen=True)
class PublishStatus:
    """Readiness of the whole book."""

    chapters: int
    unassigned: list[tuple[int, int]]
    targets: list[str]
    source: ReadyInfo
    languages: dict[str, ReadyInfo]


def paragraphs(text: str, numbered: bool = False) -> list[str]:
    """Paragraphs of a text: blocks separated by blank lines, with wrapped lines joined into one flowing paragraph.

    With numbered=True a line that starts a numbered or lettered item ("5.", "10 …", "அ)") also starts a new
    paragraph, so verse lists keep one item per paragraph.
    """
    result: list[str] = []
    for block in _PARAGRAPH_BREAK.split(text.strip()):
        groups: list[list[str]] = []
        for line in (raw.strip() for raw in block.splitlines()):
            if not line:
                continue
            if groups and not (numbered and _NUMBERED_ITEM.match(line)):
                groups[-1].append(line)
            else:
                groups.append([line])
        result += [" ".join(group) for group in groups]
    return result


def _language_name(code: str) -> str:
    return SUPPORTED_LANGUAGES.get(code, (code,))[0]


def _chapter_label(chapter: sqlite3.Row) -> str:
    return f"chapter {chapter['order_index']} “{chapter['title']}”"


def _pages_text(pages: list[int]) -> str:
    shown = ", ".join(str(p) for p in pages[:MAX_PROBLEM_LINES])
    return shown + (" …" if len(pages) > MAX_PROBLEM_LINES else "")


# --- readiness --------------------------------------------------------------------------------------------------


def _source_problems(conn: sqlite3.Connection, book_id: int, chapter: sqlite3.Row) -> list[str]:
    missing = translation._missing_pages(conn, book_id, chapter)
    if not missing:
        return []
    return [f"{_chapter_label(chapter).capitalize()}: pages {_pages_text(missing)} are not approved yet."]


def _translation_problems(
    conn: sqlite3.Connection, settings: Settings, book_id: int, chapter: sqlite3.Row, language: str
) -> list[str]:
    where = f"{_language_name(language)}, {_chapter_label(chapter)}"
    rows = conn.execute(
        "SELECT chunk_index, status, provider FROM translations WHERE chapter_id = ? AND language_code = ?",
        (chapter["id"], language),
    ).fetchall()
    if not rows:
        return [f"{where}: not translated yet."]
    outdated = translation_review.outdated_indexes(conn, settings, book_id, chapter["id"])
    problems = []
    placeholders = sum(1 for r in rows if r["provider"] == translation.TEST_PROVIDER)
    stale = sum(1 for r in rows if r["chunk_index"] in outdated)
    unapproved = sum(1 for r in rows if r["status"] != translation.APPROVED)
    wrong = translation_review.untranslated_indexes(conn, book_id, chapter["id"], language)
    if wrong:
        problems.append(
            f"{where}: {len(wrong)} part(s) are not in {_language_name(language)} (still in the original language)."
        )
    if placeholders:
        problems.append(f"{where}: {placeholders} part(s) are test-mode placeholders, not real translations.")
    if stale:
        problems.append(f"{where}: the Tamil changed after {stale} part(s) were translated. Translate again.")
    if unapproved:
        problems.append(f"{where}: {unapproved} part(s) are not approved yet.")
    return problems


def publication_status(conn: sqlite3.Connection, settings: Settings, book_id: int) -> PublishStatus:
    """Readiness of the Tamil (source) edition and of each chosen translation language."""
    chapters = chapter_service.list_chapters(conn, book_id)
    targets = translation.get_targets(conn, book_id)
    if not chapters:
        none = ReadyInfo(False, ["Create the chapters first (step 3). The book is published chapter by chapter."])
        return PublishStatus(0, [], targets, none, {code: none for code in targets})
    source = [p for chapter in chapters for p in _source_problems(conn, book_id, chapter)]
    languages = {}
    for code in targets:
        problems = [p for chapter in chapters for p in _translation_problems(conn, settings, book_id, chapter, code)]
        languages[code] = ReadyInfo(not problems, problems)
    return PublishStatus(
        chapters=len(chapters),
        unassigned=chapter_service.unassigned_ranges(conn, book_id),
        targets=targets,
        source=ReadyInfo(not source, source),
        languages=languages,
    )


# --- assembling the content -------------------------------------------------------------------------------------


def _source_section(
    conn: sqlite3.Connection,
    book_id: int,
    chapter: sqlite3.Row,
    source: str,
    page_references: bool,
    sample: bool,
    numbered: bool,
) -> Section:
    heading = chapter["heading"] or chapter["title"]
    section = Section(headings=[Block(heading, source)])
    pages = chapter_service.chapter_pages(conn, book_id, chapter["id"], approved_only=True)
    for page in pages[: SAMPLE_PAGES if sample else None]:
        if page_references:
            section.blocks.append(Block(f"Page {page.page_number}", "en", "pageref"))
        section.blocks += [Block(text, source) for text in paragraphs(page.text, numbered)]
    return section


def _chunks(conn: sqlite3.Connection, chapter_id: int, language: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT chunk_index, source_text, translated_text, edited_text FROM translations "
        "WHERE chapter_id = ? AND language_code = ? ORDER BY chunk_index",
        (chapter_id, language),
    ).fetchall()


def build_publication(
    conn: sqlite3.Connection,
    settings: Settings,
    book_id: int,
    kind: str,
    languages: list[str] | None = None,
    *,
    toc: bool = True,
    page_references: bool = False,
    sample: bool = False,
    numbered_paragraphs: bool = True,
) -> Publication:
    """Check that everything needed is approved and assemble the content, or raise PublishError."""
    book = conn.execute(
        "SELECT title, author, publication_details, source_language FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    if book is None:
        raise PublishError("That book no longer exists.")
    if kind not in KINDS:
        raise PublishError("Please choose what to publish.")
    source = book["source_language"]
    targets = translation.get_targets(conn, book_id)
    chosen = [c for c in dict.fromkeys(languages or []) if c]
    if kind == "multilingual" and not chosen:
        chosen = list(targets)
    if kind == "source":
        chosen = []
    elif kind in ("target", "bilingual") and len(chosen) != 1:
        raise PublishError("Please choose exactly one language.")
    elif not chosen:
        raise PublishError("Please choose at least one language.")
    for code in chosen:
        if code not in targets:
            raise PublishError(f"{_language_name(code)} is not one of the languages chosen on the Translate tab.")

    all_chapters = chapter_service.list_chapters(conn, book_id)
    if not all_chapters:
        raise PublishError("Create the chapters first (step 3). The book is published chapter by chapter.")
    used = all_chapters[:1] if sample else all_chapters

    problems: list[str] = []
    for chapter in used:
        if kind != "target":
            problems += _source_problems(conn, book_id, chapter)
        for code in chosen:
            problems += _translation_problems(conn, settings, book_id, chapter, code)
    if problems:
        extra = f"\n… and {len(problems) - MAX_PROBLEM_LINES} more." if len(problems) > MAX_PROBLEM_LINES else ""
        raise PublishError(
            "This is not ready to publish yet. Only approved text is published:\n- "
            + "\n- ".join(problems[:MAX_PROBLEM_LINES])
            + extra
        )

    sections = []
    for chapter in used:
        if kind == "source":
            sections.append(
                _source_section(conn, book_id, chapter, source, page_references, sample, numbered_paragraphs)
            )
            continue
        per_language = {code: _chunks(conn, chapter["id"], code) for code in chosen}
        first = per_language[chosen[0]]
        section = Section(headings=[])
        if kind != "target":
            section.headings.append(Block(first[0]["source_text"], source))
        for code in chosen:
            section.headings.append(Block(translation_review.current_text(per_language[code][0]), code))
        for index in range(1, len(first) if not sample else min(len(first), 1 + SAMPLE_PARTS)):
            if kind in ("bilingual", "multilingual"):
                section.blocks += [
                    Block(t, source, "source") for t in paragraphs(first[index]["source_text"], numbered_paragraphs)
                ]
            for code in chosen:
                if len(chosen) > 1:
                    section.blocks.append(Block(_language_name(code), "en", "label"))
                translated = translation_review.current_text(per_language[code][index])
                section.blocks += [Block(t, code) for t in paragraphs(translated, numbered_paragraphs)]
        sections.append(section)

    publication = Publication(
        title=book["title"],
        author=book["author"],
        details=book["publication_details"],
        source_language=source,
        kind=kind,
        languages=chosen,
        sections=sections,
        toc=toc,
        sample=sample,
    )
    _check_glyphs(publication)
    return publication


def _check_glyphs(publication: Publication) -> None:
    """Refuse to publish characters the bundled fonts cannot draw (they would appear as empty boxes)."""
    texts: dict[str, list[str]] = {
        publication.source_language: [publication.title, publication.author, publication.details]
    }
    for section in publication.sections:
        for block in [*section.headings, *section.blocks]:
            texts.setdefault(block.language, []).append(block.text)
    lines = []
    for language, parts in texts.items():
        missing = missing_glyphs("".join(parts), language, publication.source_language)
        if missing:
            shown = ", ".join(f"“{c}” (U+{ord(c):04X})" for c in sorted(missing)[:10])
            lines.append(f"{_language_name(language)}: {shown}")
    if lines:
        raise PublishError(
            "The text contains characters the fonts cannot draw, so they would show as empty boxes. "
            "Please correct them (often OCR mistakes):\n- " + "\n- ".join(lines)
        )
