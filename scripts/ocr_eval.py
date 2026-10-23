"""Score OCR output against a hand-checked transcript (character error rate, lower is better).

Usage: python -m scripts.ocr_eval <ocr_text_file> <ground_truth_file>
"""

import sys
from pathlib import Path

from app.services.accuracy import cer, normalize

__all__ = ["cer", "normalize"]

if __name__ == "__main__":
    hyp, ref = (Path(p).read_text(encoding="utf-8") for p in sys.argv[1:3])
    print(f"CER: {cer(hyp, ref):.1%}")
