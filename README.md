# PathippuAI

Digitize scanned Tamil books with local OCR, correct and approve the text, translate it, and export PDFs.
See `INITIAL.md` for the product definition and `PRPs/pathippuai-prp.md` for the build plan.

## Run it (Windows, development)

1. Install Tesseract: `winget install --id UB-Mannheim.TesseractOCR -e`
2. Put Tamil data in `tessdata/` (`tam.traineddata` from the `tessdata_best` project) and set `TESSDATA_DIR=./tessdata` in `.env`.
3. Backend (use a virtual environment): `python -m venv .venv`, then
   `.venv\Scripts\python -m pip install -r requirements.txt -r requirements-ocr-tamil.txt`
   (leave out the second file if you only want the fast Tesseract reading), then
   `.venv\Scripts\python -m uvicorn app.api.main:app --port 8010`
4. Frontend: `cd frontend && npm install && npm run build`

Open http://localhost:8010 (the API serves the built React app).
For live frontend development, run `npm run dev` in `frontend/` and open http://localhost:5173.

## Checks

```
ruff check . && pytest
cd frontend && npm run lint && npm run type-check
```

## Measuring OCR quality

Type out the correct text of a few representative pages into `project_det/ground_truth/pageNNN.txt` (git-ignored),
then score OCR output with `python -m scripts.ocr_eval <ocr_text_file> <ground_truth_file>` (lower error rate is better).

## OCR quality notes (measured, not guessed)

Tested on page 1 of the real book (a phone photo with shadows and faint bleed-through) against a hand-typed
transcript; error rate is the character error rate, lower is better.

| Approach | Error rate |
|----------|-----------|
| **`ocr-tamil` (careful engine), words put back in reading order, ~52 s/page on CPU** | **2%** |
| `ocr-tamil` with the library's own word order | 20% |
| Plain grayscale, Tesseract `tam` (tessdata_best), psm 4 / 6 | 13% / 17% |
| Border added, psm 6 | 12% |
| Shadow flattening, contrast, brightness windows, sharpen, resize | 15-40% (worse or noise) |
| Tesseract noise/layout options | within +-1 point (noise) |
| PaddleOCR Tamil | 38% |
| Own line detection + Tesseract per line | 41-49% |
| Voting across 3-8 runs | 18-26% |

Most lines read perfectly. Errors are mostly dropped words at line starts and the curved, blurry bottom of the page.
Confidence scores are not a reliable guide (one setting scored 91% while losing half the text).
The most effective improvement is a cleaner scan: flat lighting, no shadows, book held flat.
Use the "OCR accuracy" figure on the Check and correct page: it is measured from your approved pages.

## Reading methods

- **Fast** (default): Tesseract, about 3 seconds a page. Good for clean scans.
- **Careful**: the `ocr-tamil` library (Tamil and English books only), about a minute a page on a CPU, far more accurate
  on difficult phone photos. It needs `requirements-ocr-tamil.txt` (pulls in torch) and downloads about 270 MB of
  models the first time. The library returns words in a scrambled order; `app/services/careful_engine.py` puts them
  back into reading order using their positions, which is what made it accurate (20% error became 2% on page 1).
  This was measured on a single page, so confirm it on your own pages with the "OCR accuracy" figure, which is shown
  per method on the Check and correct page.

## Translation

Translation runs chapter by chapter on **approved text only**, in ordered chunks (a chapter heading is chunk 0). Finished
chunks are saved immediately, so an interrupted run resumes without translating anything twice. Transient errors
(rate limits, timeouts, server errors) are retried a limited number of times with growing waits; a rejected key stops
the run with a clear message. Approved or hand-edited translations are never replaced without your confirmation.
Glossary terms are applied: "keep unchanged" terms stay as written and preferred wordings are used; if a translation
drops one, the part is flagged for review.

- **Test mode (default):** `TRANSLATION_PROVIDER=mock` marks the text with `[Telugu test translation]` so you can try
  the whole workflow without a key. It does not translate.
- **Real translation with OpenAI:** in `.env` set `TRANSLATION_PROVIDER=openai` and `TRANSLATION_API_KEY=sk-...`
  (never commit `.env`; `OPENAI_API_KEY` in the environment also works), then restart. `TRANSLATION_MODEL` defaults to
  `gpt-5.4-mini`; older mini models such as `gpt-4o-mini` and `gpt-4.1-mini` are listed as deprecated, so check which
  model your account offers. Very rough cost for a 300-page Tamil book per target language: about US$2 at the listed
  GPT-5.4 Mini prices (check current pricing). A larger model costs more and may translate religious text better, so
  try one chapter first and judge quality against cost.
- **Real translation with Claude:** `TRANSLATION_PROVIDER=claude`, with a Claude key as `TRANSLATION_API_KEY`.
  `TRANSLATION_MODEL` defaults to `claude-opus-5-5` (best quality, very roughly US$9 per language for 300 pages);
  `claude-sonnet-5-5` and `claude-haiku-5-5` are cheaper.
- Your book text is sent to the chosen provider to be translated. The OCR itself never leaves your computer.
- Other settings: `TRANSLATION_CHUNK_CHARS` (default 2500), `TRANSLATION_MAX_ATTEMPTS` (4), `TRANSLATION_BACKOFF_SECONDS` (2).
- The provider interface is in `app/services/translation/base.py`; another service can be added without touching the rest.
- Machine translation does not guarantee doctrinal accuracy. Every translation must be reviewed and approved by the author.

## Reviewing translations

On the **6. Review translations** tab you read each part of a chapter's translation next to the approved Tamil (both on
A4-style pages), correct the wording, and approve it. The machine translation is never overwritten: your edits are
stored separately and "Back to the machine translation" undoes them. Any change sends a part back to "awaiting
approval". A part cannot be approved if it is test-mode placeholder text, if the Tamil changed after it was translated,
or if it is empty or not translated yet. Glossary warnings are shown beside the text and refresh when you edit. Edits
and approvals are recorded in the history table. "Approve all parts of this chapter" is an explicit action; it skips
whatever cannot be approved.

## Publishing PDFs

The **7. Publish** tab makes A4 PDFs: the Tamil book, one translation, Tamil and one translation together (Tamil
first, translation below, part by part), or Tamil and all chosen languages. Each has a cover, an optional contents
page, chapter headings, paragraph formatting, page numbers and, for the Tamil book, optional small original-page
markers. "Preview a sample first" makes a short PDF (cover, the first chapter's start) to check the look and fonts.

- **Only approved text is published.** The Tamil book needs every page of every chapter approved. A translation
  needs every part approved, translated by a real service (never test-mode placeholders) and still matching the
  approved Tamil. Otherwise the export is refused and the reasons are listed. Pages that are not in any chapter are
  not published (a warning is shown).
- **Fonts:** Noto Sans for Tamil, Telugu, Kannada, Malayalam, Devanagari (Hindi) and Latin are bundled in `app/fonts`
  (SIL Open Font License, see `app/fonts/README.md`). Text is shaped with HarfBuzz so conjuncts and vowel signs are
  correct. The Latin and the book's own script act as fallbacks, so Tamil glossary terms kept unchanged inside a
  Telugu translation still print. If text contains a character no bundled font can draw (often an OCR mistake), the
  export is refused and the character is named, instead of printing an empty box.
- **Paragraphs:** blank lines separate paragraphs and wrapped lines are joined. "Start a new paragraph at each numbered
  item" (on by default) also splits at lines that begin with 1. / 2) / 10 / அ) so verse lists stay one item per
  paragraph. Fix wrong line breaks or numbers on the Check and correct page.
- PDFs are stored in `data/books/<id>/exports/` under generated names and are only served through the app.
- Copying Indic text out of a PDF can show small oddities (the text is stored in shaped glyph order); the printed
  appearance is correct.

## Translations that come back in the wrong language

Language models sometimes return the source text unchanged (especially for noisy OCR text). Every answer is checked by
script: if a part is mostly in the book's own language (or not in the target language at all) it is asked for again
with a firmer instruction (bounded retries), and if it still fails it is marked failed with a clear message instead
of being saved. Parts already saved that way (including earlier ones) are flagged on the Translate and Review tabs,
cannot be approved or published, and "Translate again" replaces only those parts without asking, because they were
never real translations. Hand-edited parts are never replaced automatically. Glossary "keep unchanged" terms are
ignored by the check, and very short texts (headings) are not judged.

## Typing Tamil with English letters (Tanglish)

On **2. Check and correct** (Tamil books), type Tamil with English letters and press space, comma or Enter: the word
you just typed becomes Tamil (`naan` -> நான், `nandri` -> நன்றி, `thangam` -> தங்கம்). Tanglish is ambiguous, so the
converter prefers the spelling your book already uses (from approved or corrected pages): `vanakkam` -> வணக்கம்
if the book contains it. A capital letter inside a word means that exact letter (`vaNakkam`; N = ண, L = ள, R = ற).
Ctrl+Z undoes a conversion. The switch above the text box turns it off (for typing real English words), and
"Convert the English words on this page now" converts pasted Tanglish. The rules are in `frontend/src/tanglish.ts`
and are tested with `npm test` in `frontend/`.

## Login, deployment and backups (Phase 8)

- **Login:** every page and API call needs a signed-in account (bcrypt password hashes, server-side sessions,
  CSRF token + same-site check on changes, lockout after 5 wrong passwords). The first account is created on the
  sign-in screen when you open the app on the same computer; on a server use
  `python -m scripts.create_user NAME` (add `--reset` to change a password). Set `AUTH_REQUIRED=false` only for
  private local use.
- **Deploy:** Docker + Nginx + free HTTPS on a Ubuntu VPS: see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
  (install, environment, start, domain/HTTPS, updates, backup/restore, logs, and the manual quality checklist).
- **Backups:** `python -m scripts.backup create|list|restore` (database + original PDFs), or `deploy/backup.sh`
  on a server. Copy backups off the machine.
- Not verified here: a real `docker build`, the Let's Encrypt step and Nginx (need a real server and domain).
