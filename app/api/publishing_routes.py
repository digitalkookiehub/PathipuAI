"""HTTP routes for publishing: what is ready, creating PDFs, and downloading them. All paths are under /api."""

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.deps import get_conn, get_settings, require_book, require_user
from app.config import Settings
from app.services.publishing import exports
from app.services.publishing.model import publication_status

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


class ReadyOut(BaseModel):
    ready: bool
    problems: list[str]


class PublishStatusOut(BaseModel):
    chapters: int
    unassigned: list[tuple[int, int]]
    targets: list[str]
    source: ReadyOut
    languages: dict[str, ReadyOut]
    running: bool


class ExportRequest(BaseModel):
    kind: Literal["source", "target", "bilingual", "multilingual"]
    languages: list[str] = []
    toc: bool = True
    page_references: bool = False
    sample: bool = False
    numbered_paragraphs: bool = True


class ExportOut(BaseModel):
    id: int
    kind: str
    languages: list[str]
    status: str
    file_name: str | None
    size_bytes: int | None
    page_count: int | None
    toc: bool
    page_references: bool
    sample: bool
    numbered_paragraphs: bool
    error: str | None
    created_at: str


def _export_out(row: sqlite3.Row) -> ExportOut:
    options = json.loads(row["options"] or "{}")
    return ExportOut(
        id=row["id"],
        kind=row["export_type"],
        languages=[c for c in (row["languages"] or "").split(",") if c],
        status=row["status"],
        file_name=row["file_name"],
        size_bytes=row["size_bytes"],
        page_count=row["page_count"],
        toc=bool(options.get("toc", True)),
        page_references=bool(options.get("page_references", False)),
        sample=bool(options.get("sample", False)),
        numbered_paragraphs=bool(options.get("numbered_paragraphs", True)),
        error=row["error"],
        created_at=row["created_at"],
    )


@router.get("/books/{book_id}/publishing", response_model=PublishStatusOut)
def status(
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> PublishStatusOut:
    """What can be published now, and what is still in the way."""
    info = publication_status(conn, settings, book["id"])
    return PublishStatusOut(
        chapters=info.chapters,
        unassigned=info.unassigned,
        targets=info.targets,
        source=ReadyOut(ready=info.source.ready, problems=info.source.problems),
        languages={c: ReadyOut(ready=v.ready, problems=v.problems) for c, v in info.languages.items()},
        running=exports.is_running(book["id"]),
    )


@router.post("/books/{book_id}/exports", status_code=202)
def create(
    body: ExportRequest,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    """Create a PDF in the background. Refused, with the reasons, unless everything needed is approved."""
    export_id = exports.start_export(
        conn,
        settings,
        book["id"],
        body.kind,
        body.languages,
        toc=body.toc,
        page_references=body.page_references,
        sample=body.sample,
        numbered_paragraphs=body.numbered_paragraphs,
    )
    return {"id": export_id}


@router.get("/books/{book_id}/exports", response_model=list[ExportOut])
def list_all(
    book: sqlite3.Row = Depends(require_book), conn: sqlite3.Connection = Depends(get_conn)
) -> list[ExportOut]:
    """The PDFs made for this book, newest first. Poll while one is being created."""
    return [_export_out(row) for row in exports.list_exports(conn, book["id"])]


@router.get("/books/{book_id}/exports/{export_id}/file")
def download(
    export_id: int,
    download: bool = False,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """The PDF itself: shown in the browser, or saved when download=true."""
    path = exports.export_file(conn, settings, book["id"], export_id)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"book_{book['id']}_{path.name}",
        content_disposition_type="attachment" if download else "inline",
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/books/{book_id}/exports/{export_id}", status_code=204)
def remove(
    export_id: int,
    book: sqlite3.Row = Depends(require_book),
    conn: sqlite3.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> None:
    """Delete a finished or failed PDF."""
    exports.delete_export(conn, settings, book["id"], export_id)
