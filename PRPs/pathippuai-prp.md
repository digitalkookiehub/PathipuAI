# PRP: PathippuAI

> Implementation blueprint for phased agent execution (FastAPI + React + SQLite; UI changed from Streamlit to React on 2026-10-22)

---

## METADATA

| Field | Value |
|-------|-------|
| **Product** | PathippuAI |
| **Type** | Low-cost self-hosted web app (single application) |
| **Version** | 1.0 |
| **Created** | 2026-10-22 |
| **Complexity** | Medium-High (Tamil OCR quality, multi-script PDF rendering, resumable jobs) |

---

## PRODUCT OVERVIEW

**Description:** Authors upload a scanned PDF (e.g. Adobe Scan). The app runs local Tesseract OCR page by page, the author corrects and approves text, organizes chapters, translates approved text into Telugu, Kannada, Malayalam, Hindi or English, reviews translations, and exports Tamil, per-language, bilingual and multilingual PDFs.

**Initial user:** A temple guru with a 300+ page Tamil spiritual book. Content is religious, so terminology must be preserved per the author's glossary.

**Value Proposition:** Digitize and publish a book in several languages at very low cost, with the author in control of every approval.

**Non-goals:** Microservices, Kubernetes, distributed processing, vector DBs, AI agents, paid OCR, managed databases, payments, admin panel.

**MVP Scope:**
- [ ] Login (hashed passwords, session protection)
- [ ] Create book, upload and validate scanned PDF
- [ ] Local Tamil OCR page by page with progress, resume, per-page retry
- [ ] OCR review, correction, approval, search, text export
- [ ] Manual chapters and glossary
- [ ] Translation: provider interface, chunking, bounded retries, resume
- [ ] Translation review and approval
- [ ] Tamil / translated / bilingual / multilingual PDF export with correct glyphs
- [ ] Docker + Nginx HTTPS deployment, backups, README

---

## TECH STACK

| Layer | Technology | Skill Reference |
|-------|------------|-----------------|
| Language | Python 3.11+ | - |
| Frontend | React + TypeScript + Vite + Chakra UI v2 | skills/FRONTEND.md |
| API | FastAPI over the Python service modules | skills/BACKEND.md |
| OCR | Tesseract + `tam` data via pytesseract | - |
| PDF rendering | pypdfium2 | - |
| Preprocessing | Pillow, OpenCV (optional) | - |
| Translation | Provider interface + mock + one low-cost API | skills/BACKEND.md (adapt) |
| Database | SQLite, versioned migrations | skills/DATABASE.md (adapt) |
| PDF output | ReportLab (or HTML-to-PDF) + bundled Unicode fonts | - |
| Auth | bcrypt hashes + session/token auth in FastAPI | skills/BACKEND.md (adapt) |
| Testing | pytest | skills/TESTING.md |
| Deployment | Docker, docker-compose, Nginx, HTTPS | skills/DEPLOYMENT.md |

> Existing skills/agents are FastAPI/React/PostgreSQL oriented. Use them for principles; implement with this stack.

---

## PROJECT STRUCTURE

```
app/
  main.py  config.py  db.py  storage.py
  migrations/            # 001_initial.sql ...
  auth/                  # hashing, login, session guard
  api/                   # FastAPI routes; frontend/ holds the React pages
  services/
    books.py  pdf_validation.py  ocr.py  preprocessing.py
    chapters.py  glossary.py  publishing.py
    translation/         # base.py, mock.py, <provider>.py, chunking.py
  fonts/                 # redistributable fonts + LICENSES
tests/ (fixtures/ small samples only)
deploy/ (nginx.conf, backup.sh, restore notes)
Dockerfile  docker-compose.yml  requirements.txt  .env.example  .gitignore  README.md
```

---

## DATABASE MODELS (SQLite)

All tables: integer PK, `created_at`, `updated_at`; foreign keys enabled; schema versioned in `schema_migrations`.

| Table | Key fields / relationships |
|-------|----------------------------|
| users | id, username, password_hash, is_active |
| books | id, owner_id FK, uuid (storage id), title, author, description, source_language, publication_details, original_pdf_path, page_count, status |
| book_pages | id, book_id FK, page_number, image_path, ocr_text (original, immutable), corrected_text, ocr_confidence, ocr_status, review_status (pending/corrected/approved), duration_ms, error, approved_at. Unique (book_id, page_number) |
| chapters | id, book_id FK, title, heading, order_index, start_page, end_page |
| target_languages | id, book_id FK, language_code, selected. Unique (book_id, language_code) |
| translations | id, chapter_id FK, language_code, chunk_index, source_text, translated_text, edited_text, status (not started/processing/awaiting approval/approved/failed), attempts, error, approved_at. Unique (chapter_id, language_code, chunk_index) |
| glossary_terms | id, book_id FK, source_term, language_code, preferred_translation, explanation, keep_unchanged, author_notes |
| processing_jobs | id, book_id FK, job_type (ocr/translation), status, total, completed, failed, started_at, finished_at, error |
| export_jobs | id, book_id FK, export_type (source/target/bilingual/multilingual/sample), languages, status, output_path, error |
| text_history (optional) | id, entity_type, entity_id, old_text, new_text, action, created_at |

Rules: original OCR, corrected text and translations stay separate; no binaries in SQLite; images and PDFs live on disk under `DATA_DIR/books/<uuid>/...`.

---

## MODULES

> Services are plain Python modules exposed through a thin FastAPI layer (`app/api`) and consumed by the React frontend.

### Module H: Auth, Settings, Security
**Agents:** DATABASE + BACKEND + FRONTEND

| Service | Description |
|---------|-------------|
| auth.hash_password / verify_password | bcrypt/argon2 |
| auth.login / logout / require_login | session guard on every page; rate-limit failed logins |
| storage.safe_path | internal IDs, traversal checks, 0700/0600 permissions |
| config | env-driven settings (DPI, PSM, limits, provider) |

| Page | Purpose |
|------|---------|
| Login | username/password |
| Application settings | OCR DPI/PSM, preprocessing toggles, limits, provider status |

### Module A: Book Management
**Agents:** DATABASE + BACKEND + FRONTEND

| Service | Description |
|---------|-------------|
| books.create/list/get/delete | delete requires confirmation; never overwrite silently |
| pdf_validation.validate | type, size, page count, readability, disk space |
| books.save_original | store as `original.pdf` under generated ID |

| Page | Purpose |
|------|---------|
| Dashboard | book list, statuses, resume, delete |
| Create / upload book | metadata + upload + validation result |

### Module B: PDF Processing and OCR
**Agents:** BACKEND + FRONTEND

| Service | Description |
|---------|-------------|
| ocr.check_languages | verify Tesseract data before run; friendly error |
| ocr.process_book | render page via pypdfium2 at configured DPI, optional preprocess, OCR, persist, free memory; continue on failure |
| ocr.retry_failed | only failed pages |
| processing_jobs | persistent progress and resume |

| Page | Purpose |
|------|---------|
| OCR processing | start/resume, progress bar, failed pages, retry |

Confidence is informational only.

### Module C: OCR Review and Correction
**Agents:** BACKEND + FRONTEND

| Service | Description |
|---------|-------------|
| save_corrected_text | store correction, status corrected; approved → pending on edit |
| approve_page | explicit author action only |
| search_text | search in extracted/corrected text |
| export_source_text | corrected Tamil text export |

| Page | Purpose |
|------|---------|
| OCR correction and approval | page image + editable text, prev/next, Save, Approve, search |

### Module D: Chapters
**Agents:** BACKEND + FRONTEND

Services: create, rename, reorder, set range, assign pages, preview, export chapter text. Page: Chapter management. Manual first; auto-detect optional.

### Module E: Translation
**Agents:** BACKEND + FRONTEND

| Service | Description |
|---------|-------------|
| translation.base.TranslationProvider | interface (translate(text, source, target, glossary)) |
| mock provider | deterministic, for tests/local |
| real provider | affordable API, key from env, timeouts, rate limits |
| chunking.split | per chapter, ordered, preserves paragraphs/headings |
| translate_chapter | approved source only; bounded retries; persist each chunk; skip done chunks on resume; confirm before overwriting approved |

| Page | Purpose |
|------|---------|
| Target language selection | multi-select, validate source ≠ target, ≥1 target |
| Translation progress | per chapter × language status, errors, start/resume |

### Module F: Glossary and Translation Review
**Agents:** BACKEND + FRONTEND

Services: glossary CRUD, apply glossary to provider instructions (keep-unchanged terms, preferred translations), save/approve translation. Pages: Glossary management; Translation review (approved Tamil beside editable translation, Save, Approve, status).
Prompt priorities: semantic fidelity, respectful religious terminology, natural target-language writing; never invent content.

### Module G: PDF Publishing
**Agents:** BACKEND + FRONTEND

| Service | Description |
|---------|-------------|
| publishing.export_source / target / bilingual / multilingual | approved content only; refuse otherwise |
| publishing.sample_preview | few pages before full export |
| fonts | register per-script fonts (Tamil, Telugu, Kannada, Malayalam, Devanagari, Latin) |

Includes title, author, chapter headings, page numbers, margins, optional TOC, original page references. Page: PDF preview and export.

---

## PHASE EXECUTION PLAN

Complete and validate each phase before the next. Before coding, present structure, dependency licenses, and risks (Tamil OCR accuracy, Unicode PDF rendering).

**Phase 1: Foundation / Books**
- DATABASE-AGENT: `db.py`, migration runner, `001_initial.sql` (all tables)
- BACKEND-AGENT: `config.py`, `storage.py`, `pdf_validation.py`, `books.py`
- FRONTEND-AGENT: React skeleton, Dashboard, Create/upload book
- DEVOPS-AGENT (parallel): Dockerfile draft with tesseract-ocr + `tesseract-ocr-tam`, `.env.example`, `.gitignore`, requirements.txt
- Gate 1: tests for validation, page counting, path safety; `uvicorn app.api.main:app` starts

**Phase 2: OCR**
- BACKEND-AGENT: `ocr.py`, `preprocessing.py`, jobs/resume/retry
- FRONTEND-AGENT: OCR processing page
- TEST-AGENT: OCR on a small sample page, missing language data, save/retrieve
- Gate 2: tests pass; sample page OCR works

**Phase 3: Review and correction**
- BACKEND + FRONTEND: correction, approval, search, text export
- Gate 3: approve/edit/reset behavior tests

**Phase 4: Chapters and glossary**
- BACKEND + FRONTEND: Chapter management, Glossary management
- Gate 4: chapter ordering and glossary tests

**Phase 5: Translation engine**
- BACKEND: provider interface, mock, real provider, chunking, retries, resume
- FRONTEND: language selection, translation progress
- Gate 5: chunk order, retry/resume, language validation, unapproved-text block tests

**Phase 6: Translation review**
- BACKEND + FRONTEND: review/edit/approve, overwrite confirmation
- Gate 6: approval and overwrite-protection tests

**Phase 7: PDF publishing**
- BACKEND: fonts, ReportLab layouts for all four export types, sample preview
- FRONTEND: export page
- TEST-AGENT: Unicode glyph tests for all 6 languages, unapproved-export block
- Gate 7: PDFs render without missing glyphs

**Phase 8: Auth, deployment, docs**
- BACKEND/FRONTEND: login, session guard, settings page
- DEVOPS-AGENT: final Dockerfile, docker-compose (persistent volumes), Nginx HTTPS config, health check, backup script, restore instructions, README
- REVIEW-AGENT: security and quality audit (auth, uploads, traversal, logging, secrets)
- Final: manual quality-validation procedure with representative pages from the real book (not committed)

---

## VALIDATION GATES

| Gate | Commands |
|------|----------|
| 1 | `pip install -r requirements.txt`, `pytest tests -k "validation or storage"`, `uvicorn app.api.main:app` (smoke), `cd frontend && npm run build` |
| 2 | `ruff check .`, `pytest -k ocr` |
| 3-6 | `ruff check .`, `pytest` for the phase |
| 7 | `pytest -k pdf` (glyph checks for ta, te, kn, ml, hi, en) |
| Final | `ruff check . && pytest`, `docker-compose build`, `docker-compose up -d`, health check |

---

## TEST COVERAGE (from spec)

PDF validation; page counting; OCR on sample page; missing Tesseract language data; save/retrieve OCR results; edit/approve source text; translation chunk ordering; retry and resume; language validation; block translating unapproved text; block exporting unapproved translations; Unicode PDF generation for all languages; file access restrictions. Fixtures are small and contain none of the guru's book.

---

## ENVIRONMENT VARIABLES

```env
DATA_DIR=./data
DATABASE_PATH=./data/pathippuai.db
SECRET_KEY=change-me
TESSERACT_CMD=tesseract
OCR_DPI=300
OCR_PSM=6
MAX_UPLOAD_MB=200
MAX_PAGES=1000
TRANSLATION_PROVIDER=mock
TRANSLATION_API_KEY=
```

---

## RISKS

- Tamil OCR accuracy varies; always require human review, never claim accuracy untested.
- Rendering Indic scripts in PDFs requires complex-text shaping and fonts that cover all scripts; verify ReportLab shaping (may need HarfBuzz/HTML-to-PDF).
- Machine translation of religious text can distort meaning; glossary and human approval are mandatory.
- The API has no login until Phase 8; keep it on localhost or behind Nginx + HTTPS until then.
- Long OCR jobs run in a background thread; progress is persisted so restarts resume safely.

---

## NEXT STEP

/execute-prp PRPs/pathippuai-prp.md
