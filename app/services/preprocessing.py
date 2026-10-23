"""Optional image preprocessing for OCR. Only applied when enabled in settings."""

from PIL import Image

VALID_STEPS = ("flatten", "deskew", "contrast", "denoise", "threshold")
MAX_DESKEW_DEGREES = 15.0


def preprocess(image: Image.Image, steps: tuple[str, ...]) -> Image.Image:
    """Apply the enabled steps (in a fixed order) and return a grayscale image."""
    gray = image.convert("L")
    if not steps:
        return gray
    import cv2  # imported lazily: only needed when preprocessing is enabled
    import numpy as np

    array = np.array(gray)
    if "flatten" in steps:
        array = _flatten_background(array, cv2, np)
    if "denoise" in steps:
        array = cv2.fastNlMeansDenoising(array, None, 10, 7, 21)
    if "contrast" in steps:
        array = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(array)
    if "deskew" in steps:
        array = _deskew(array, cv2, np)
    if "threshold" in steps:
        array = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return Image.fromarray(array)


def _flatten_background(array, cv2, np):  # noqa: ANN001
    """Even out shadows and gray paper (typical of phone photos) by dividing out the background."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    background = cv2.medianBlur(cv2.dilate(array, kernel), 51)
    return cv2.divide(array, background, scale=255)


def _deskew(array, cv2, np):  # noqa: ANN001
    """Rotate to correct small skew, estimated from the dark-pixel bounding rectangle."""
    inverted = cv2.bitwise_not(array)
    binary = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(binary > 0))
    if len(coords) < 100:
        return array
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle if angle < 45 else 90 - angle
    if abs(angle) < 0.1 or abs(angle) > MAX_DESKEW_DEGREES:
        return array
    height, width = array.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(array, matrix, (width, height), flags=cv2.INTER_CUBIC, borderValue=255)
