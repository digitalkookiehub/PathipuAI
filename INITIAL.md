# INITIAL.md - PathippuAI Product Definition

> A simple, low-cost web app that digitizes scanned Tamil books, helps the author correct OCR errors, translates approved text into other Indian languages, and exports publication-ready PDFs.

Full specification: `project_det/AI_Engineering_Career_Intelligence_All_Departments_Master_Product_Development_Prompt.txt`

---

## PRODUCT

### Name
PathippuAI

### Description
A single-user-friendly web application for authors. The author uploads a scanned PDF (e.g. from Adobe Scan), the app runs local Tesseract OCR page by page, the author corrects and approves the text, organizes it into chapters, translates approved chapters into other languages, reviews the translations, and exports Tamil, target-language, bilingual or multilingual PDFs.

The initial user is a temple guru with a 300+ page spiritual book written in Tamil. Content is spiritual and religious, so terminology (mantras, sacred names, Sanskrit words, scripture references) must be preserved per the author's preferences.

### Target User
Non-technical authors digitizing and translating their own printed books.

### Type
- [x] Low-cost self-hosted web app (single Python application, not an enterprise system)

### Non-goals
Microservices, Kubernetes, distributed processing, vector databases, AI agents, paid OCR services (Azure Document Intelligence etc.), managed databases.

---

## TECH STACK

> Changed from Streamlit to a React frontend with a small FastAPI backend. PostgreSQL is still NOT used (SQLite, per the product spec).

| Layer | Choice |
|-------|--------|
| Language | Python 3.11+ |
| Frontend | React + TypeScript + Vite + Chakra UI v2 (Noto Sans Tamil font bundled) |
| API | FastAPI (services stay plain Python modules; OCR runs as a background job) |
| OCR | Tesseract (`tam` and other language data) via pytesseract, local only |
| PDF rendering | pypdfium2 |
| Image preprocessing | Pillow, OpenCV (optional, configurable) |
| Translation | Pluggable provider interface; low-cost API first; mock provider for tests |
| Database | SQLite with versioned migrations |
| PDF generation | ReportLab or an HTML-to-PDF library, with bundled Unicode fonts |
| Config | Environment variables + python-dotenv |
| Auth | Application login with hashed passwords (bcrypt/argon2) and session protection |
| Payments | None |
| Deployment | Docker + docker-compose on an Ubuntu Hostinger VPS, Nginx reverse proxy with HTTPS |
| Testing | pytest |

### Supported Languages
Tamil (ta, initial source), Telugu (te), Kannada (kn), Malayalam (ml), Hindi (hi), English (en). Source language is configurable; OCR and translation language config are kept separate. Source and target must differ; at least one target is required; Tesseract language data is verified before processing.

---

## MODULES

### Module A: Book Management
**Description:** Create books, upload scanned PDFs, track status, resume, delete with confirmation.

**Tables:** `books` (id, title, author, description, source_language, publication_details, original_pdf_path, page_count, status, created_at, updated_at)

**Capabilities:**
- Create book with title, author, description, source language, publication details
- Upload scanned PDF; validate type, size, page count, readability
- Never silently overwrite an existing book; delete only after confirmation
- Dashboard listing with processing status and resume

**Pages:** Dashboard; Create / upload book

---

### Module B: PDF Processing and OCR
**Description:** Page-by-page local OCR with persistent progress.

**Tables:** `book_pages` (book_id, page_number, image_path, ocr_text, ocr_confidence, ocr_status, duration_ms, error, ...), `processing_jobs`

**Capabilities:**
- Save original PDF; render one page at a time at configurable DPI (default 300) with pypdfium2
- Tesseract `tam` with configurable PSM; optional preprocessing (deskew, contrast, denoise, threshold)
- Store per-page text, status, duration, errors; continue on page failure; retry failed pages only
- Release page images after processing; disk-space check before large jobs
- Progress shown live in the React UI (background OCR job polled by the frontend)
- OCR confidence is informational, never a basis for auto-approval

**Pages:** OCR processing

---

### Module C: OCR Review and Correction
**Description:** Side-by-side page image and editable text.

**Capabilities:**
- Show scanned page image, editable text, page number, status, Save / Approve, Previous / Next
- Keep original OCR text separate from corrected text; page status pending / corrected / approved
- Editing approved text resets it to pending approval
- Search within extracted text; export corrected source text

**Pages:** OCR correction and approval

---

### Module D: Chapter Management
**Description:** Manual organization of pages into chapters.

**Tables:** `chapters` (book_id, title, order_index, start_page, end_page, heading, ...)

**Capabilities:**
- Create, rename, reorder chapters; set start/end pages; edit headings
- Preview and export chapter text; preserve original page numbers and order
- Automatic chapter detection optional, must not block workflow

**Pages:** Chapter management

---

### Module E: Translation
**Description:** Provider-agnostic, chunked, resumable translation of approved text.

**Tables:** `target_languages`, `translations` (chapter_id, language, chunk_index, source_text, translated_text, status, history...)

**Capabilities:**
- Translation provider interface; initial low-cost API; mock provider for local tests; keys only via env vars
- Translate only approved source text, chapter by chapter, in ordered chunks that keep paragraph and heading boundaries
- Bounded retries, timeout and rate-limit handling; completed chunks are saved and not re-translated after restart
- Independent target-language selection; per chapter+language status; progress and error messages
- Never overwrite approved translations without confirmation

**Pages:** Target language selection; Translation progress

---

### Module F: Spiritual Terminology and Translation Review
**Description:** Glossary plus review/approval of translations.

**Tables:** `glossary_terms` (source_term, language, preferred_translation, explanation, keep_unchanged, author_notes)

**Capabilities:**
- Glossary applied to translation instructions; preserve mantras, sacred names, Sanskrit words, scripture references, verse numbers
- Review UI: approved source text, translated text, editable translation, Save, Approve, status
- Prompt priorities: semantic fidelity, respectful religious terminology, natural target-language writing
- Never invent religious content; never claim doctrinal accuracy from machine translation

**Pages:** Glossary management; Translation review

---

### Module G: PDF Publishing
**Description:** Export approved content only.

**Tables:** `export_jobs`

**Capabilities:**
- Tamil PDF, per-language PDFs, bilingual (Tamil + one language), multilingual (Tamil + all selected)
- Title, author, chapter headings, page numbers, margins, paragraph formatting, optional table of contents, original page references
- Bundled Unicode fonts for Tamil, Telugu, Kannada, Malayalam, Hindi, English (licenses verified as redistributable)
- Sample-PDF preview before full export; glyph-rendering tests
- Refuse to publish unapproved text or translations

**Pages:** PDF preview and export

---

### Module H: Authentication, Settings and Security
**Description:** Protect unpublished manuscripts.

**Capabilities:**
- Application login with password hashing and session protection
- Settings page (OCR DPI/PSM, preprocessing toggles, provider, limits)
- Upload restrictions, private file storage, path-traversal protection, internal IDs instead of user filenames
- Logging without secrets or document contents

**Pages:** Login; Application settings

---

## DATA & STORAGE

- SQLite with a simple versioned migration mechanism and transactions; original OCR text, corrected text and translations stored separately; approval history where practical
- Files on disk under a configurable data dir outside source: `data/books/<book_id>/{original.pdf, pages/, ocr/, corrected/, translations/, exports/}`
- No large binaries in SQLite; no arbitrary URL access to private files

---

## STATUS LABELS

Not started, Processing, Needs correction, Awaiting approval, Approved, Failed. Messages must be friendly to non-technical users.

---

## MVP SCOPE

### Must Have (MVP)
- [x] Login
- [x] Create book and upload/validate scanned PDF (Phase 1)
- [x] Local Tamil OCR, page by page, with progress, resume and retry (Phase 2)
- [x] OCR review, correction, approval, search, text export (Phase 3)
- [x] Manual chapters and glossary (Phase 4)
- [x] Translation with provider interface, chunking, retries, resume (Phase 5)
- [x] Translation review and approval (Phase 6)
- [ ] Tamil / translated / bilingual / multilingual PDF export with correct glyphs (Phase 7)
- [ ] Docker deployment, Nginx + HTTPS, backups, docs (Phase 8)

### Nice to Have (Post-MVP)
- Automatic chapter detection
- Additional source/target languages
- Alternative translation providers

---

## IMPLEMENTATION PHASES

Complete and test each phase before the next.

1. Project skeleton, React dashboard, book upload, PDF validation
2. Tesseract OCR, page-by-page processing, progress, persistent results
3. OCR review, correction, approval, text export
4. Chapter management and glossary
5. Translation provider, language selection, chunking, retries, resume
6. Translation review and approval
7. Bilingual and multilingual PDF generation
8. Authentication, Docker deployment, HTTPS, backups, documentation

Before coding: present project structure, explain dependencies and licenses, and identify risks (Tamil OCR accuracy, Unicode PDF rendering).

---

## ACCEPTANCE CRITERIA

### Books and OCR
- [ ] Invalid, unreadable, oversized or over-page-limit PDFs are rejected with clear messages
- [ ] A 300+ page scan is OCR'd page by page without loading all pages into memory
- [ ] A failed page does not stop the run and can be retried alone
- [ ] Interrupted processing resumes without redoing successful pages
- [ ] Missing Tesseract language data is detected and reported before processing

### Review and Chapters
- [ ] Original OCR text is preserved separately from corrected text
- [ ] Editing approved text returns the page to pending approval
- [ ] Chapters can be created, renamed, reordered and exported

### Translation
- [ ] Unapproved source text cannot be translated
- [ ] Chunks keep order; completed chunks are not re-translated after restart
- [ ] Approved translations are not overwritten without confirmation
- [ ] Glossary terms and keep-unchanged terms are respected

### Publishing
- [ ] Unapproved text or translations cannot be exported
- [ ] PDFs render all six scripts with no missing-glyph boxes
- [ ] Sample preview works before full export

### Security and Quality
- [ ] Login required; passwords hashed; no secrets in Git or logs
- [ ] Path traversal and unauthorized file access are prevented
- [ ] pytest suite covers the areas in the spec; fixtures contain no private book content
- [ ] Docker build succeeds; data survives container restarts and upgrades
- [ ] Backup script and restore instructions work

---

## SPECIAL REQUIREMENTS

### Security
- [x] Password hashing and session protection
- [x] File upload restrictions and validation
- [x] Private file storage with restricted permissions
- [x] Secrets via environment variables only
- [x] Nginx + HTTPS in front of the app (never expose it directly)

### Integrations
- [x] Translation API (configurable, low cost) with mock provider
- [ ] Email service
- [ ] Payments (none)
- [ ] Admin panel / analytics dashboard (not requested)

### Deliverables (Phase 8)
Dockerfile, docker-compose.yml, requirements.txt, .env.example, .gitignore, Nginx config, health check, backup script, restore instructions, README.md

---

## AGENTS

> The template agents under `agents/` target FastAPI/React. Adapt them to SQLite or work through the ORCHESTRATOR.

| Agent | Role | Works On |
|-------|------|----------|
| DATABASE-AGENT | SQLite schema and migrations | All tables |
| BACKEND-AGENT | OCR, translation, PDF services (Python modules) | Services layer |
| FRONTEND-AGENT | React pages | All 11 pages |
| DEVOPS-AGENT | Docker, Nginx, backups | Infrastructure |
| TEST-AGENT | pytest suite | All code |
| REVIEW-AGENT | Security and code quality audit | All code |

---

# READY?

```bash
/generate-prp INITIAL.md
/execute-prp PRPs/pathippuai-prp.md
```
