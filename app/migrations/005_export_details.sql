-- Details of each exported PDF, so the list of exports can show what was made.
ALTER TABLE export_jobs ADD COLUMN options TEXT;
ALTER TABLE export_jobs ADD COLUMN file_name TEXT;
ALTER TABLE export_jobs ADD COLUMN size_bytes INTEGER;
ALTER TABLE export_jobs ADD COLUMN page_count INTEGER;
