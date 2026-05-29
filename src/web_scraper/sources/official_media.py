from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from ..config import Settings
from ..models import ImageCandidate, ImageJob
from ..utils import normalize_header
from .base import ImageSource

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_META_IMAGE_SELECTORS = (
    ('meta[property="og:image"]', "og:image"),
    ('meta[property="og:image:url"]', "og:image"),
    ('meta[name="twitter:image"]', "twitter:image"),
    ('meta[name="twitter:image:src"]', "twitter:image"),
)
_POSITIVE_CONTEXT_HINTS = (
    "product",
    "hero",
    "gallery",
    "overview",
    "packshot",
    "detail",
    "zoom",
    "main",
)
_DEVICE_VIEW_HINTS = (
    "front",
    "back",
    "rear",
    "side",
    "top",
    "bottom",
    "angle",
    "device",
    "finish",
    "color",
    "colour",
    "exterior",
    "interior",
)
_STRONG_NEGATIVE_HINTS = (
    "logo",
    "icon",
    "sprite",
    "badge",
    "favicon",
    "avatar",
    "thumbnail",
    "thumb",
    "share",
    "social",
    "banner",
    "button",
    "placeholder",
)
_WEAK_NEGATIVE_HINTS = (
    "promo",
    "promotion",
    "support",
    "help",
    "buy",
    "shop",
    "compare",
    "video",
    "feature",
    "lifestyle",
)
_MULTIWORD_NEGATIVE_HINTS = (
    "in use",
    "feature in use",
    "app showing",
    "scene from",
    "how to",
)
_DIRECT_IMAGE_ATTRIBUTES = (
    "src",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-image",
    "data-zoom-image",
    "data-full",
    "data-large-image",
    "data-full-image",
    "href",
)
_SRCSET_ATTRIBUTES = ("srcset", "data-srcset", "imagesrcset")


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _looks_like_image_url(url: str) -> bool:
    if not url or url.startswith("data:"):
        return False
    path = urlparse(url).path.lower()
    return PurePosixPath(path).suffix in _IMAGE_EXTENSIONS


def _is_amazon_url(url: str) -> bool:
    hostname = urlparse(url).netloc.lower()
    return "amazon." in hostname


def _root_domain(hostname: str) -> str:
    labels = [label for label in hostname.lower().split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    if len(labels[-1]) == 2 and labels[-2] in {"co", "com", "org", "net", "gov", "ac"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _same_site_score(image_url: str, page_url: str) -> tuple[float, bool]:
    image_host = urlparse(image_url).hostname or ""
    page_host = urlparse(page_url).hostname or ""
    if not image_host or not page_host:
        return 0.0, False
    if image_host == page_host:
        return 2.0, True
    if _root_domain(image_host) == _root_domain(page_host):
        return 1.5, True
    return -0.75, False


def _normalized_text(value: str) -> str:
    return normalize_header(value)


def _token_set(value: str) -> set[str]:
    return {token for token in _normalized_text(value).split("_") if token}


def _count_matches(text: str, terms: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


def _parse_dimension(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_srcset_descriptor(value: str) -> tuple[Optional[int], Optional[float]]:
    if value.endswith("w"):
        try:
            return int(value[:-1]), None
        except ValueError:
            return None, None
    if value.endswith("x"):
        try:
            return None, float(value[:-1])
        except ValueError:
            return None, None
    return None, None


def _best_srcset_candidate(
    srcset: str, page_url: str
) -> Optional[tuple[str, Optional[int], Optional[float]]]:
    variants: list[tuple[int, float, str]] = []
    for entry in srcset.split(","):
        parts = entry.strip().split()
        if not parts:
            continue
        url = urljoin(page_url, parts[0])
        if not _looks_like_image_url(url):
            continue
        width_hint: Optional[int] = None
        density_hint: Optional[float] = None
        if len(parts) > 1:
            width_hint, density_hint = _parse_srcset_descriptor(parts[1])
        variants.append((width_hint or 0, density_hint or 0.0, url))

    if not variants:
        return None

    best_width, best_density, best_url = max(
        variants, key=lambda item: (item[0], item[1])
    )
    return best_url, (best_width or None), (best_density or None)


def _build_context_text(element: Tag, associated_text: str = "") -> str:
    parts: list[str] = [associated_text] if associated_text else []

    def extend_from_tag(tag: Optional[Tag]) -> None:
        if tag is None:
            return
        for attribute in (
            "alt",
            "title",
            "aria-label",
            "data-testid",
            "data-role",
            "name",
        ):
            value = tag.get(attribute)
            if value:
                parts.append(str(value))
        for attribute in ("class", "id"):
            value = tag.get(attribute)
            if not value:
                continue
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            else:
                parts.append(str(value))

    extend_from_tag(element)

    current = element.parent
    depth = 0
    while isinstance(current, Tag) and depth < 2:
        extend_from_tag(current)
        current = current.parent
        depth += 1

    return " ".join(part for part in parts if part)


def _score_candidate(
    image_url: str,
    *,
    page_url: str,
    product_name: str,
    source_type: str,
    context_text: str,
    width_hint: Optional[int] = None,
    density_hint: Optional[float] = None,
    attribute_width: Optional[int] = None,
    attribute_height: Optional[int] = None,
) -> tuple[float, dict[str, Any]]:
    combined_text = " ".join((context_text, urlparse(image_url).path)).strip()
    normalized_product = _normalized_text(product_name)
    normalized_combined = _normalized_text(combined_text)
    product_tokens = _token_set(product_name)
    candidate_tokens = _token_set(combined_text)

    same_site_points, same_site = _same_site_score(image_url, page_url)
    score = same_site_points
    score += {
        "direct_image_url": 4.0,
        "og:image": 1.75,
        "twitter:image": 1.5,
        "preload_image": 1.5,
        "picture_srcset": 1.25,
        "img_srcset": 1.0,
        "img": 0.5,
    }.get(source_type, 0.0)

    overlap = len(product_tokens & candidate_tokens)
    if product_tokens:
        overlap_ratio = overlap / len(product_tokens)
        score += overlap_ratio * 4.5
        if overlap == 0:
            score -= 1.0
    if normalized_product and normalized_product in normalized_combined:
        score += 1.75

    score += min(_count_matches(combined_text, _POSITIVE_CONTEXT_HINTS) * 0.45, 1.8)
    score += min(_count_matches(combined_text, _DEVICE_VIEW_HINTS) * 0.65, 2.6)
    score -= min(_count_matches(combined_text, _STRONG_NEGATIVE_HINTS) * 2.0, 6.0)
    score -= min(_count_matches(combined_text, _WEAK_NEGATIVE_HINTS) * 0.65, 2.6)
    score -= min(_count_matches(combined_text, _MULTIWORD_NEGATIVE_HINTS) * 1.25, 3.75)

    if width_hint:
        score += min(width_hint / 1500.0, 2.0)
    if density_hint:
        score += min(density_hint, 3.0) * 0.25

    if attribute_width and attribute_height:
        area = attribute_width * attribute_height
        smallest_side = min(attribute_width, attribute_height)
        if smallest_side < 120 or area < 50_000:
            score -= 4.0
        elif smallest_side < 300 or area < 200_000:
            score -= 1.25
        else:
            score += min(area / 1_500_000, 1.5)
    elif attribute_width or attribute_height:
        smallest_known = min(
            value for value in (attribute_width, attribute_height) if value
        )
        if smallest_known < 120:
            score -= 2.0

    if not context_text.strip() and source_type not in {
        "og:image",
        "twitter:image",
        "preload_image",
        "direct_image_url",
    }:
        score -= 0.5

    metadata: dict[str, Any] = {
        "source_type": source_type,
        "same_site": same_site,
    }
    if width_hint is not None:
        metadata["width_hint"] = width_hint
    if density_hint is not None:
        metadata["density_hint"] = density_hint
    if attribute_width is not None:
        metadata["attribute_width"] = attribute_width
    if attribute_height is not None:
        metadata["attribute_height"] = attribute_height
    return score, metadata


def _build_candidate(
    image_url: str,
    *,
    page_url: str,
    product_name: str,
    source_type: str,
    context_text: str,
    width_hint: Optional[int] = None,
    density_hint: Optional[float] = None,
    attribute_width: Optional[int] = None,
    attribute_height: Optional[int] = None,
) -> Optional[ImageCandidate]:
    if not _looks_like_image_url(image_url):
        return None

    score, metadata = _score_candidate(
        image_url,
        page_url=page_url,
        product_name=product_name,
        source_type=source_type,
        context_text=context_text,
        width_hint=width_hint,
        density_hint=density_hint,
        attribute_width=attribute_width,
        attribute_height=attribute_height,
    )
    return ImageCandidate(
        source_name="official_media",
        image_url=image_url,
        page_url=page_url,
        label=product_name,
        score=score,
        metadata=metadata,
    )


def _collect_tag_candidates(
    element: Tag,
    *,
    page_url: str,
    product_name: str,
    source_type: str,
    associated_text: str = "",
) -> list[ImageCandidate]:
    candidates: list[ImageCandidate] = []
    context_text = _build_context_text(element, associated_text)
    attribute_width = _parse_dimension(element.get("width"))
    attribute_height = _parse_dimension(element.get("height"))

    for attribute in _DIRECT_IMAGE_ATTRIBUTES:
        value = element.get(attribute)
        if not value:
            continue
        image_url = urljoin(page_url, value)
        candidate = _build_candidate(
            image_url,
            page_url=page_url,
            product_name=product_name,
            source_type=source_type,
            context_text=context_text,
            attribute_width=attribute_width,
            attribute_height=attribute_height,
        )
        if candidate is not None:
            candidates.append(candidate)

    for attribute in _SRCSET_ATTRIBUTES:
        value = element.get(attribute)
        if not value:
            continue
        best_variant = _best_srcset_candidate(value, page_url)
        if best_variant is None:
            continue
        image_url, width_hint, density_hint = best_variant
        candidate = _build_candidate(
            image_url,
            page_url=page_url,
            product_name=product_name,
            source_type=f"{source_type}_srcset",
            context_text=context_text,
            width_hint=width_hint,
            density_hint=density_hint,
            attribute_width=attribute_width,
            attribute_height=attribute_height,
        )
        if candidate is not None:
            candidates.append(candidate)

    return candidates


def _token_score(product_name: str, candidate_text: str) -> float:
    product_tokens = {
        token for token in normalize_header(product_name).split("_") if token
    }
    candidate_tokens = {
        token for token in normalize_header(candidate_text).split("_") if token
    }
    if not product_tokens:
        return 0.0
    overlap = len(product_tokens & candidate_tokens)
    return overlap / len(product_tokens)


def extract_image_candidates(
    html: str, page_url: str, product_name: str
) -> list[ImageCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    collected: list[ImageCandidate] = []

    for selector, source_type in _META_IMAGE_SELECTORS:
        for element in soup.select(selector):
            content = element.get("content")
            if not content:
                continue
            candidate = _build_candidate(
                urljoin(page_url, content),
                page_url=page_url,
                product_name=product_name,
                source_type=source_type,
                context_text=_build_context_text(element),
            )
            if candidate is not None:
                collected.append(candidate)

    for preload in soup.select('link[as="image"]'):
        collected.extend(
            _collect_tag_candidates(
                preload,
                page_url=page_url,
                product_name=product_name,
                source_type="preload_image",
            )
        )

    for picture in soup.select("picture"):
        image = picture.find("img")
        shared_context = (
            _build_context_text(image)
            if isinstance(image, Tag)
            else _build_context_text(picture)
        )
        for source in picture.find_all("source"):
            collected.extend(
                _collect_tag_candidates(
                    source,
                    page_url=page_url,
                    product_name=product_name,
                    source_type="picture",
                    associated_text=shared_context,
                )
            )
        if isinstance(image, Tag):
            collected.extend(
                _collect_tag_candidates(
                    image,
                    page_url=page_url,
                    product_name=product_name,
                    source_type="img",
                    associated_text=shared_context,
                )
            )

    for image in soup.select("img"):
        if image.parent and image.parent.name == "picture":
            continue
        collected.extend(
            _collect_tag_candidates(
                image,
                page_url=page_url,
                product_name=product_name,
                source_type="img",
            )
        )

    by_url: dict[str, ImageCandidate] = {}
    for candidate in collected:
        existing = by_url.get(candidate.image_url)
        if existing is None or candidate.score > existing.score:
            by_url[candidate.image_url] = candidate

    ranked = sorted(
        by_url.values(),
        key=lambda candidate: (
            candidate.score,
            candidate.metadata.get("width_hint", 0),
            int(candidate.metadata.get("same_site", False)),
        ),
        reverse=True,
    )
    if ranked:
        return ranked

    # Fallback: preserve the old behavior when we have image URLs but no useful context to score.
    fallback_urls: list[str] = []
    for image in soup.select("img[src], img[data-src]"):
        source = image.get("data-src") or image.get("src")
        if not source:
            continue
        absolute = urljoin(page_url, source)
        if _looks_like_image_url(absolute):
            fallback_urls.append(absolute)

    return [
        ImageCandidate(
            source_name="official_media",
            image_url=image_url,
            page_url=page_url,
            label=product_name,
            score=0.0,
        )
        for image_url in _unique(fallback_urls)
    ]


def extract_image_urls(html: str, page_url: str, product_name: str) -> list[str]:
    return [
        candidate.image_url
        for candidate in extract_image_candidates(html, page_url, product_name)
    ]


class OfficialMediaSource(ImageSource):
    name = "official_media"

    def fetch_candidates(
        self,
        job: ImageJob,
        *,
        client: httpx.Client,
        settings: Settings,
    ) -> list[ImageCandidate]:
        if not settings.sources.official_media.enabled:
            return []

        source_urls = self._discover_source_urls(job, settings)
        if not source_urls:
            return []

        candidates: list[ImageCandidate] = []
        for source_url in source_urls:
            if _looks_like_image_url(source_url):
                candidates.append(
                    ImageCandidate(
                        source_name=self.name,
                        image_url=source_url,
                        page_url=source_url,
                        label=job.product_name,
                        score=10.0,
                        metadata={"source_type": "direct_image_url", "same_site": True},
                    )
                )
                continue

            response = client.get(source_url)
            response.raise_for_status()
            for candidate in extract_image_candidates(
                response.text, source_url, job.product_name
            ):
                candidates.append(candidate)

        deduped_candidates: dict[str, ImageCandidate] = {}
        for candidate in candidates:
            existing = deduped_candidates.get(candidate.image_url)
            if existing is None or candidate.score > existing.score:
                deduped_candidates[candidate.image_url] = candidate

        ranked_candidates = sorted(
            deduped_candidates.values(),
            key=lambda candidate: candidate.score,
            reverse=True,
        )
        return ranked_candidates[: settings.sources.max_candidates_per_job]

    def _discover_source_urls(self, job: ImageJob, settings: Settings) -> list[str]:
        urls: list[str] = []
        for column_name in settings.sheet.source_url_columns:
            value = job.metadata.get(normalize_header(column_name))
            if not value:
                continue
            if (
                _is_amazon_url(value)
                and not settings.sources.browser_fallback.allow_amazon_fallback
            ):
                continue
            urls.append(value)
        return _unique(urls)
