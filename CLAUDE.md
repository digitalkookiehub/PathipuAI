# CLAUDE.md - PathippuAI Project Rules

> Project-specific rules for Claude Code. This file is read automatically.

---

## Project Overview

**Project Name:** PathippuAI
**Description:** Simple, low-cost web app to digitize scanned Tamil books (local OCR), correct and approve text, translate into Indian languages, review translations, and export publication-ready PDFs.
**Spec:** `project_det/AI_Engineering_Career_Intelligence_All_Departments_Master_Product_Development_Prompt.txt` and `INITIAL.md`

**Tech Stack:**
- Language: Python 3.11+ (backend), TypeScript (frontend)
- Backend API: FastAPI (wraps the service modules; OCR runs in a background thread)
- Frontend: React + TypeScript + Vite + Chakra UI v2, Noto Sans Tamil bundled for readable Tamil
- OCR: Tesseract (`tam`) via pytesseract (fast, default) and the optional `ocr-tamil` careful engine (slow, accurate); local only
- PDF rendering: pypdfium2; preprocessing: Pillow / OpenCV (optional)
- Translation: pluggable provider interface; Claude API provider (`anthropic` SDK) and a mock provider for tests
- Database: SQLite with versioned migrations
- PDF output: ReportLab or HTML-to-PDF with bundled Unicode fonts
- Config: environment variables + python-dotenv
- Auth: app login with hashed passwords
- Deploy: Docker + Nginx (HTTPS) on Ubuntu VPS
- Testing: pytest

**Keep it simple.** One FastAPI process serves the API and the built React app. No microservices, Kubernetes, vector DBs, AI agents, paid OCR, or managed databases.

---

## Project Structure

```
PathippuAI/
├── app/
│   ├── api/                  # FastAPI: main.py, routes.py, schemas.py, deps.py, jobs.py (background OCR)
│   ├── config.py             # env settings
│   ├── db.py                 # SQLite connection + migrations runner
│   ├── migrations/
│   ├── services/
│   │   ├── books.py
│   │   ├── pdf_validation.py
│   │   ├── ocr.py
│   │   ├── careful_engine.py   # optional ocr-tamil engine + word ordering
│   │   ├── accuracy.py         # OCR accuracy from the author's approved pages
│   │   ├── preprocessing.py
│   │   ├── chapters.py
│   │   ├── translation/      # base.py (interface), mock.py, <provider>.py, chunking.py
│   │   ├── glossary.py
│   │   └── publishing.py
│   ├── auth/
│   ├── storage.py            # safe paths, internal IDs
│   └── fonts/                # redistributable Unicode fonts
├── frontend/                 # React app (src/pages, components, hooks, api.ts, types.ts, theme.ts)
├── scripts/ocr_eval.py         # score OCR output against a hand-checked transcript (CER)
├── tests/
│   └── fixtures/             # small samples only
├── deploy/                   # nginx.conf, backup script
├── project_det/              # spec (private content never committed)
├── Dockerfile, docker-compose.yml, requirements.txt, .env.example, .gitignore
├── skills/, agents/, PRPs/, .claude/commands/
└── README.md
```

Runtime data lives outside source in a configurable `DATA_DIR`:
`books/<book_id>/{original.pdf,pages/,ocr/,corrected/,translations/,exports/}`

---

## Code Standards

```python
# Type hints and docstrings on public functions
def save_corrected_text(conn: sqlite3.Connection, book_id: int, page_number: int, text: str) -> None:
    """Save corrected text; reset page to pending approval if it was approved."""

# Translation providers implement a common interface
class TranslationProvider(Protocol):
    def translate(self, text: str, source: str, target: str, glossary: list[GlossaryTerm]) -> str: ...
```

- Keep OCR text, corrected text and translated text in separate columns/files.
- Use SQLite transactions for multi-step writes; parameterized queries only.
- Process pages one at a time; never hold all page images in memory.

---

## Forbidden

- `print()` → use `logging` (never log API keys or manuscript text)
- Plain-text passwords → hash (bcrypt/argon2)
- Hardcoded secrets → env vars; never commit `.env`, private PDFs, passwords or keys
- User-provided filenames as storage paths → use generated internal IDs; validate paths (no traversal)
- Storing page images/binaries in SQLite
- Sending the book to an external OCR service
- Auto-approving pages from OCR confidence
- Translating unapproved source text or exporting unapproved text/translations
- Overwriting approved translations or existing books without confirmation
- Inventing or silently altering religious content; claiming translation/OCR accuracy without testing on representative pages
- Exposing the app directly to the internet (use Nginx + HTTPS); the API has no login until Phase 8
- `any` types, `console.log` and inline styles in the frontend (use Chakra props)
- Unnecessary infrastructure or placeholder files

---

## Domain Rules

- Statuses: Not started, Processing, Needs correction, Awaiting approval, Approved, Failed. Page review status: pending / corrected / approved.
- Editing approved text sets it back to pending approval.
- A failed page never aborts the run; failed pages can be retried individually; processing resumes without redoing successes.
- Translation: per chapter, in ordered chunks, bounded retries, completed chunks persisted, status per chapter+language.
- Glossary terms (keep-unchanged, preferred translations) must be applied; preserve mantras, sacred names, Sanskrit words, scripture references, verse numbers.
- Source and target languages must differ; at least one target; verify Tesseract language data before OCR.
- Fonts must be legally redistributable; test every supported script for missing glyphs.
- Friendly, non-technical user-facing messages.

---

## Environment Variables

```env
DATA_DIR=./data
DATABASE_PATH=./data/pathippuai.db
SECRET_KEY=change-me
TESSERACT_CMD=tesseract
OCR_DPI=300
OCR_PSM=6
TESSDATA_DIR=./tessdata
OCR_PREPROCESS=
OCR_CAREFUL_PREPROCESS=flatten
OCR_EXTRA_CONFIG=
CORS_ORIGINS=http://localhost:5173
MAX_UPLOAD_MB=200
MAX_PAGES=1000
TRANSLATION_PROVIDER=mock
TRANSLATION_API_KEY=
TRANSLATION_MODEL=
TRANSLATION_CHUNK_CHARS=2500
```

---

## Development Commands

```bash
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-ocr-tamil.txt
.venv/Scripts/python -m uvicorn app.api.main:app --port 8010      # API + built React app
cd frontend && npm run dev                 # React dev server on :5173 (proxies /api to :8010)
cd frontend && npm run build               # production build served by FastAPI

pytest -v
ruff check .

docker-compose build
docker-compose up -d
```

---

## Commit Message Format

```
feat(ocr): add page retry
fix(translation): keep chunk order
test(publishing): cover Unicode glyphs
docs: update README
```

---

## Skills Reference

> The skills and agents in this repo were written for FastAPI/React/PostgreSQL. This project uses SQLite instead; adapt the database guidance.

| Task | Skill |
|------|-------|
| Database | skills/DATABASE.md |
| Services | skills/BACKEND.md |
| UI | skills/FRONTEND.md |
| Testing | skills/TESTING.md |
| Deployment | skills/DEPLOYMENT.md |

---

## Workflow

Implement in the 8 phases listed in `INITIAL.md`. Complete and test each phase before proceeding, run available tests, and explain how to start the app after each phase. Before coding: present structure, dependencies and licenses, and risks (Tamil OCR accuracy, Unicode PDF rendering).

## Validation

```bash
ruff check . && pytest
cd frontend && npm run lint && npm run type-check
docker-compose build
```
