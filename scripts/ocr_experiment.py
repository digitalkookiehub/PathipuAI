"""Compare OCR variants on one page against a hand-checked transcript.

Usage: python scripts/ocr_experiment.py <book_id> <page_number> <ground_truth_file>
"""

import dataclasses
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.config import load_settings
from app.services import ocr
from app.services.preprocessing import preprocess
from scripts.ocr_eval import cer


def levels(a: np.ndarray, lo: int, hi: int) -> np.ndarray:
    return np.clip((a.astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)


def sharpen(a: np.ndarray) -> np.ndarray:
    return cv2.addWeighted(a, 1.8, cv2.GaussianBlur(a, (0, 0), 3), -0.8, 0)


def main() -> None:
    book_id, page_number, gt_path = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    settings = load_settings()
    conn = sqlite3.connect(settings.database_path)
    pdf = Path(conn.execute("SELECT original_pdf_path FROM books WHERE id = ?", (book_id,)).fetchone()[0])
    truth = Path(gt_path).read_text(encoding="utf-8")
    image = ocr.render_page(pdf, page_number - 1, settings.ocr_dpi)
    gray = np.array(image.convert("L"))
    flat = np.array(preprocess(image, ("flatten",)))
    variants = {
        "gray (current)": gray,
        "flatten": flat,
        "flatten+levels": levels(flat, 40, 180),
        "flatten+sharpen": sharpen(flat),
        "gray x0.7": cv2.resize(gray, None, fx=0.7, fy=0.7, interpolation=cv2.INTER_AREA),
        "gray x1.5": cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC),
    }
    for name, array in variants.items():
        scores = []
        for psm in (3, 4, 6):
            cfg = dataclasses.replace(settings, ocr_psm=psm)
            text, _ = ocr.tesseract_recognize(Image.fromarray(array), cfg, "tam")
            scores.append(f"psm{psm}={cer(text, truth):.0%}")
        print(f"{name:18s}", *scores, flush=True)


if __name__ == "__main__":
    main()
