-- Which OCR engine read each page ('tesseract' or 'careful'), so accuracy can be compared per engine.
ALTER TABLE book_pages ADD COLUMN ocr_engine TEXT;
