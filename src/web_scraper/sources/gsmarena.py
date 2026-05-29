from __future__ import annotations

from collections.abc import Iterable
from typing import Optional, Tuple
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

from ..config import Settings
from ..models import ImageCandidate, ImageJob
from ..utils import maybe_sleep, normalize_header
from .base import ImageSource

GSM_ARENA_BASE_URL = "https://www.gsmarena.com/"
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


def parse_search_results(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, str]] = []

    for anchor in soup.select(".makers li a, .makers a"):
        href = anchor.get("href")
        if not href:
            continue
        title = " ".join(anchor.stripped_strings)
        if not title:
            continue
        results.append(
            {
                "title": title,
                "url": urljoin(GSM_ARENA_BASE_URL, href),
            }
        )
    return results


def _token_score(query: str, candidate_title: str) -> float:
    query_tokens = {token for token in normalize_header(query).split("_") if token}
    title_tokens = {
        token for token in normalize_header(candidate_title).split("_") if token
    }
    if not query_tokens:
        return 0.0
    overlap = len(query_tokens & title_tokens)
    return overlap / len(query_tokens)


def parse_product_page(html: str, page_url: str) -> Tuple[list[str], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    image_urls: list[str] = []

    meta_image = soup.select_one('meta[property="og:image"]')
    if meta_image and meta_image.get("content"):
        image_urls.append(urljoin(page_url, meta_image["content"]))

    for image in soup.select(".specs-photo-main img, img[src], img[data-src]"):
        source = image.get("data-src") or image.get("src")
        if not source:
            continue
        absolute = urljoin(page_url, source)
        lowered = absolute.lower()
        if "gsmarena.com" not in lowered:
            continue
        if "/pics/" not in lowered and not lowered.endswith(_IMAGE_EXTENSIONS):
            continue
        image_urls.append(absolute)

    gallery_link = soup.select_one('a[href*="-pictures-"]')
    gallery_url = (
        urljoin(page_url, gallery_link["href"])
        if gallery_link and gallery_link.get("href")
        else None
    )
    return _unique(image_urls), gallery_url


def parse_gallery_page(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for image in soup.select("img[src], img[data-src]"):
        source = image.get("data-src") or image.get("src")
        if not source:
            continue
        absolute = urljoin(page_url, source)
        lowered = absolute.lower()
        if "gsmarena.com" not in lowered:
            continue
        if "/pics/" not in lowered and not lowered.endswith(_IMAGE_EXTENSIONS):
            continue
        urls.append(absolute)
    return _unique(urls)


class GsmArenaSource(ImageSource):
    name = "gsmarena"

    def fetch_candidates(
        self,
        job: ImageJob,
        *,
        client: httpx.Client,
        settings: Settings,
    ) -> list[ImageCandidate]:
        if known_url := self._resolve_known_product_url(job):
            return self._extract_candidates_from_product_page(
                job,
                page_url=known_url,
                client=client,
                settings=settings,
            )

        search_url = f"{GSM_ARENA_BASE_URL}results.php3?sQuickSearch=yes&sName={quote_plus(job.product_name)}"
        response = client.get(search_url)
        response.raise_for_status()

        results = parse_search_results(response.text)
        if not results:
            return []

        ranked = sorted(
            results,
            key=lambda result: _token_score(job.product_name, result["title"]),
            reverse=True,
        )
        best_result = ranked[0]
        return self._extract_candidates_from_product_page(
            job,
            page_url=best_result["url"],
            client=client,
            settings=settings,
        )

    def _resolve_known_product_url(self, job: ImageJob) -> Optional[str]:
        for key in ("gsmarenaurl", "sourceurl", "officialmediaurl"):
            value = job.metadata.get(key)
            if value and "gsmarena.com" in value:
                return value
        return None

    def _extract_candidates_from_product_page(
        self,
        job: ImageJob,
        *,
        page_url: str,
        client: httpx.Client,
        settings: Settings,
    ) -> list[ImageCandidate]:
        maybe_sleep(
            settings.network.min_delay_seconds, settings.network.max_delay_seconds
        )
        response = client.get(page_url)
        response.raise_for_status()

        product_images, gallery_url = parse_product_page(response.text, page_url)
        gallery_images: list[str] = []
        if gallery_url:
            maybe_sleep(
                settings.network.min_delay_seconds, settings.network.max_delay_seconds
            )
            gallery_response = client.get(gallery_url)
            gallery_response.raise_for_status()
            gallery_images = parse_gallery_page(gallery_response.text, gallery_url)

        candidates = [
            ImageCandidate(
                source_name=self.name,
                image_url=image_url,
                page_url=page_url,
                label=job.product_name,
            )
            for image_url in _unique([*product_images, *gallery_images])[
                : settings.sources.max_candidates_per_job
            ]
        ]
        return candidates
