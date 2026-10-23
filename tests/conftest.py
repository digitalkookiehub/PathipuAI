import io
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.db import connect  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "test.db",
        secret_key="test",
        tesseract_cmd="tesseract",
        ocr_dpi=300,
        ocr_psm=6,
        max_upload_mb=5,
        max_pages=10,
        min_free_disk_mb=1,
        translation_provider="mock",
        translation_api_key="",
        auth_required=False,
    )


@pytest.fixture
def conn(settings: Settings) -> sqlite3.Connection:
    connection = connect(settings.database_path)
    yield connection
    connection.close()


@pytest.fixture
def make_pdf() -> Callable[[int], bytes]:
    def _make(pages: int) -> bytes:
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        for number in range(1, pages + 1):
            pdf.drawString(100, 750, f"Sample page {number}")
            pdf.showPage()
        pdf.save()
        return buffer.getvalue()

    return _make
