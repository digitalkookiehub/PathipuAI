"""Application settings loaded from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Language code -> (display name, Tesseract language code)
SUPPORTED_LANGUAGES: dict[str, tuple[str, str]] = {
    "ta": ("Tamil", "tam"),
    "te": ("Telugu", "tel"),
    "kn": ("Kannada", "kan"),
    "ml": ("Malayalam", "mal"),
    "hi": ("Hindi", "hin"),
    "en": ("English", "eng"),
}


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. Secrets come from the environment only."""

    data_dir: Path
    database_path: Path
    secret_key: str
    tesseract_cmd: str
    ocr_dpi: int
    ocr_psm: int
    max_upload_mb: int
    max_pages: int
    min_free_disk_mb: int
    translation_provider: str
    translation_api_key: str
    tessdata_dir: Path | None = None
    ocr_preprocess: tuple[str, ...] = ()
    ocr_extra_config: str = ""
    careful_preprocess: tuple[str, ...] = ("flatten",)
    translation_model: str = ""
    translation_chunk_chars: int = 2500
    translation_max_attempts: int = 4
    translation_backoff_seconds: float = 2.0
    auth_required: bool = True
    cookie_secure: bool = False
    session_hours: int = 12
    trust_proxy: bool = False


def load_settings() -> Settings:
    """Build Settings from the environment (and a local .env if present)."""
    load_dotenv()
    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    return Settings(
        data_dir=data_dir,
        database_path=Path(os.getenv("DATABASE_PATH", str(data_dir / "pathippuai.db"))).resolve(),
        secret_key=os.getenv("SECRET_KEY", ""),
        tesseract_cmd=os.getenv("TESSERACT_CMD", "tesseract"),
        ocr_dpi=int(os.getenv("OCR_DPI", "300")),
        ocr_psm=int(os.getenv("OCR_PSM", "6")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "200")),
        max_pages=int(os.getenv("MAX_PAGES", "1000")),
        min_free_disk_mb=int(os.getenv("MIN_FREE_DISK_MB", "1024")),
        translation_provider=os.getenv("TRANSLATION_PROVIDER", "mock"),
        translation_api_key=os.getenv("TRANSLATION_API_KEY", ""),
        tessdata_dir=Path(tessdata).resolve() if (tessdata := os.getenv("TESSDATA_DIR")) else None,
        ocr_preprocess=tuple(p.strip() for p in os.getenv("OCR_PREPROCESS", "").split(",") if p.strip()),
        ocr_extra_config=os.getenv("OCR_EXTRA_CONFIG", "").strip(),
        translation_model=os.getenv("TRANSLATION_MODEL", "").strip(),
        translation_chunk_chars=int(os.getenv("TRANSLATION_CHUNK_CHARS", "2500")),
        translation_max_attempts=int(os.getenv("TRANSLATION_MAX_ATTEMPTS", "4")),
        translation_backoff_seconds=float(os.getenv("TRANSLATION_BACKOFF_SECONDS", "2")),
        auth_required=os.getenv("AUTH_REQUIRED", "true").strip().lower() not in ("0", "false", "no"),
        cookie_secure=os.getenv("COOKIE_SECURE", "false").strip().lower() in ("1", "true", "yes"),
        session_hours=int(os.getenv("SESSION_HOURS", "12")),
        trust_proxy=os.getenv("TRUST_PROXY", "false").strip().lower() in ("1", "true", "yes"),
        careful_preprocess=tuple(
            p.strip() for p in os.getenv("OCR_CAREFUL_PREPROCESS", "flatten").split(",") if p.strip()
        ),
    )
