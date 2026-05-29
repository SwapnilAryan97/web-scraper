from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import Settings
from ..models import ImageCandidate, ImageJob
from ..utils import normalize_header
from .base import ImageSource

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


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
    lowered = url.lower()
    return lowered.endswith(_IMAGE_EXTENSIONS)


def _is_amazon_url(url: str) -> bool:
    hostname = urlparse(url).netloc.lower()
    return "amazon." in hostname


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


def extract_image_urls(html: str, page_url: str, product_name: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    scored_urls: list[tuple[float, str]] = []

    meta_image = soup.select_one('meta[property="og:image"]')
    if meta_image and meta_image.get("content"):
        scored_urls.append((1.0, urljoin(page_url, meta_image["content"])))

    for image in soup.select("img[src], img[data-src]"):
        source = image.get("data-src") or image.get("src")
        if not source:
            continue
        absolute = urljoin(page_url, source)
        score = _token_score(product_name, image.get("alt", ""))
        scored_urls.append((score, absolute))

    ranked = sorted(scored_urls, key=lambda entry: entry[0], reverse=True)
    relevant = [
        url for score, url in ranked if score > 0 and _looks_like_image_url(url)
    ]
    if relevant:
        return _unique(relevant)
    # Fallback: page has no useful alt text (e.g. a plain product page), keep all image-extension URLs
    return _unique([url for _, url in ranked if _looks_like_image_url(url)])


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
                    )
                )
                continue

            response = client.get(source_url)
            response.raise_for_status()
            for image_url in extract_image_urls(
                response.text, source_url, job.product_name
            ):
                candidates.append(
                    ImageCandidate(
                        source_name=self.name,
                        image_url=image_url,
                        page_url=source_url,
                        label=job.product_name,
                    )
                )

        unique_candidates: list[ImageCandidate] = []
        seen_urls: set[str] = set()
        for candidate in candidates:
            if candidate.image_url in seen_urls:
                continue
            seen_urls.add(candidate.image_url)
            unique_candidates.append(candidate)
        return unique_candidates[: settings.sources.max_candidates_per_job]

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
