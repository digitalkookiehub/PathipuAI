-- One row per term and language; language_code '*' holds the term-level settings
-- (explanation, author notes, keep_unchanged). Other rows hold per-language preferred translations.
CREATE UNIQUE INDEX idx_glossary_unique ON glossary_terms(book_id, source_term, language_code);
