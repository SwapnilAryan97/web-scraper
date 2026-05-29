from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
import imagehash
from PIL import Image, UnidentifiedImageError

from .config import Settings
from .models import ImageCandidate, ReviewIssue
from .utils import ensure_dir, maybe_sleep, sanitize_filename_component


class ImageDownloadError(RuntimeError):
    pass


def _guess_extension(url: str, content_type: Optional[str]) -> str:
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
        if guessed:
            return ".jpg" if guessed == ".jpe" else guessed

    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix:
        return suffix
    return ".jpg"


def download_image(
    candidate: ImageCandidate,
    *,
    client: httpx.Client,
    temp_dir: Path,
    settings: Settings,
) -> ImageCandidate:
    ensure_dir(temp_dir)
    maybe_sleep(settings.network.min_delay_seconds, settings.network.max_delay_seconds)
    response = client.get(candidate.image_url)
    response.raise_for_status()

    content_type = (
        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if content_type and not content_type.startswith("image/"):
        raise ImageDownloadError(
            f"Expected image content from {candidate.image_url}, received {content_type or 'unknown'}"
        )

    extension = _guess_extension(candidate.image_url, content_type)
    file_stem = hashlib.sha1(candidate.image_url.encode("utf-8")).hexdigest()[:16]
    local_path = temp_dir / f"{file_stem}{extension}"
    local_path.write_bytes(response.content)

    try:
        with Image.open(local_path) as image:
            width, height = image.size
    except UnidentifiedImageError as exc:
        local_path.unlink(missing_ok=True)
        raise ImageDownloadError(
            f"Downloaded file is not a valid image: {candidate.image_url}"
        ) from exc

    candidate.local_path = local_path
    candidate.content_type = content_type or mimetypes.types_map.get(
        extension, "image/jpeg"
    )
    candidate.width = width
    candidate.height = height
    return candidate


def evaluate_quality(
    candidate: ImageCandidate, settings: Settings
) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    if not candidate.local_path or not candidate.local_path.exists():
        return [
            ReviewIssue(
                severity="error",
                category="download",
                message="Candidate has no local image file to evaluate",
            )
        ]

    file_size = candidate.local_path.stat().st_size
    if (candidate.width or 0) < settings.quality.min_width or (
        candidate.height or 0
    ) < settings.quality.min_height:
        issues.append(
            ReviewIssue(
                severity="error",
                category="resolution",
                message=(
                    f"Image resolution {candidate.width}x{candidate.height} is below the configured "
                    f"minimum of {settings.quality.min_width}x{settings.quality.min_height}"
                ),
            )
        )

    if file_size > settings.quality.max_bytes:
        issues.append(
            ReviewIssue(
                severity="warning",
                category="file_size",
                message=f"Image is larger than the configured limit ({file_size} bytes)",
                metadata={"bytes": file_size},
            )
        )

    extension = candidate.local_path.suffix.lower()
    if extension not in settings.quality.preferred_extensions:
        issues.append(
            ReviewIssue(
                severity="info",
                category="file_extension",
                message=f"Image extension {extension} is not in the preferred list",
            )
        )
    return issues


def compute_image_hash(path: Path) -> imagehash.ImageHash:
    with Image.open(path) as image:
        return imagehash.phash(image)


def is_duplicate(
    path: Path, seen_hashes: list[imagehash.ImageHash], threshold: int
) -> bool:
    image_hash = compute_image_hash(path)
    for seen_hash in seen_hashes:
        if image_hash - seen_hash <= threshold:
            return True
    seen_hashes.append(image_hash)
    return False


def build_final_image_path(
    output_dir: Path, sku: str, attribute_name: str, source_path: Path
) -> Path:
    sku_component = sanitize_filename_component(sku)
    attribute_component = sanitize_filename_component(attribute_name)
    extension = source_path.suffix.lower() or ".jpg"
    return (
        ensure_dir(output_dir / sku_component)
        / f"{sku_component}_{attribute_component}{extension}"
    )


def persist_image(
    candidate: ImageCandidate, *, output_dir: Path, sku: str, attribute_name: str
) -> Path:
    if not candidate.local_path:
        raise ImageDownloadError(
            "Cannot persist an image candidate without a downloaded file"
        )
    final_path = build_final_image_path(
        output_dir, sku, attribute_name, candidate.local_path
    )
    shutil.copy2(candidate.local_path, final_path)
    return final_path
