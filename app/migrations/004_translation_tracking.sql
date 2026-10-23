-- source_hash: fingerprint of the approved source text a chunk was made from, to detect later changes.
-- notes: warnings about a translation (for example a protected term that did not stay unchanged).
-- provider: which translation service produced the text ('mock' marks placeholder test output).
ALTER TABLE translations ADD COLUMN source_hash TEXT;
ALTER TABLE translations ADD COLUMN notes TEXT;
ALTER TABLE translations ADD COLUMN provider TEXT;
