from __future__ import annotations

from pathlib import Path

from PIL import Image

from .config import Settings
from .models import ReviewIssue

try:
    import cv2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime dependency
    cv2 = None

try:
    import pytesseract  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime dependency
    pytesseract = None


def inspect_watermark(image_path: Path, settings: Settings) -> list[ReviewIssue]:
    if not settings.watermark.enabled:
        return []

    issues: list[ReviewIssue] = []
    issues.extend(_inspect_text(image_path, settings))
    issues.extend(_inspect_overlay_patterns(image_path, settings))
    return issues


def _inspect_text(image_path: Path, settings: Settings) -> list[ReviewIssue]:
    if pytesseract is None:
        return []
    if settings.watermark.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.watermark.tesseract_cmd

    try:
        with Image.open(image_path) as image:
            extracted_text = pytesseract.image_to_string(image).lower()
    except Exception:
        return []

    normalized_text = " ".join(extracted_text.split())
    if len(normalized_text) < settings.watermark.min_text_length:
        return []

    for keyword in settings.watermark.ocr_keywords:
        if keyword.lower() in normalized_text:
            return [
                ReviewIssue(
                    severity="error",
                    category="watermark_text",
                    message=f"OCR detected likely watermark text: {keyword}",
                    metadata={"keyword": keyword},
                )
            ]
    return []


def _inspect_overlay_patterns(
    image_path: Path, settings: Settings
) -> list[ReviewIssue]:
    if cv2 is None:
        return []

    image = cv2.imread(str(image_path))
    if image is None:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, threshold = cv2.threshold(
        gray,
        settings.watermark.bright_region_threshold,
        255,
        cv2.THRESH_BINARY,
    )
    contours, _ = cv2.findContours(threshold, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    suspect_contours = [
        contour for contour in contours if 20 <= cv2.contourArea(contour) <= 4000
    ]
    if len(suspect_contours) >= settings.watermark.max_suspect_regions:
        return [
            ReviewIssue(
                severity="warning",
                category="watermark_pattern",
                message="Image contains many bright repeated regions and may include an overlay watermark",
                metadata={"suspect_regions": len(suspect_contours)},
            )
        ]
    return []
