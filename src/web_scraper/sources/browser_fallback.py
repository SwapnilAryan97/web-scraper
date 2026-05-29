from __future__ import annotations

from collections.abc import Iterable
from typing import Optional
from urllib.parse import urljoin

import httpx

from ..config import Settings
from ..models import ImageCandidate, ImageJob
from ..utils import maybe_sleep, normalize_header
from .base import ImageSource


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


class BrowserFallbackSource(ImageSource):
    name = "browser_fallback"

    def fetch_candidates(
        self,
        job: ImageJob,
        *,
        client: httpx.Client,
        settings: Settings,
    ) -> list[ImageCandidate]:
        del client  # Browser-based fallback uses Playwright instead of the shared HTTP client.
        if not settings.sources.browser_fallback.enabled:
            return []

        target_url = self._resolve_target_url(job, settings)
        if not target_url:
            return []

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=settings.sources.browser_fallback.headless
                )
                context = browser.new_context(
                    user_agent=settings.network.user_agent,
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()
                page.set_default_timeout(
                    settings.sources.browser_fallback.page_timeout_seconds * 1000
                )
                page.goto(target_url, wait_until="domcontentloaded")
                maybe_sleep(
                    settings.network.min_delay_seconds,
                    settings.network.max_delay_seconds,
                )

                raw_urls: list[str] = page.eval_on_selector_all(
                    "img",
                    """
                    (elements) => elements.flatMap((element) => {
                      const values = [
                        element.getAttribute('data-old-hires'),
                        element.getAttribute('data-src'),
                        element.getAttribute('src'),
                        element.currentSrc,
                      ].filter(Boolean);

                      const srcset = element.getAttribute('srcset');
                      if (srcset) {
                        for (const entry of srcset.split(',')) {
                          const [url] = entry.trim().split(/\\s+/);
                          if (url) values.push(url);
                        }
                      }
                      return values;
                    })
                    """,
                )
                browser.close()
        except PlaywrightError:
            return []

        candidates = [
            ImageCandidate(
                source_name=self.name,
                image_url=urljoin(target_url, image_url),
                page_url=target_url,
                label=job.product_name,
            )
            for image_url in _unique(raw_urls)
            if image_url.startswith("http")
            or image_url.startswith("//")
            or image_url.startswith("/")
        ]
        return candidates[: settings.sources.max_candidates_per_job]

    def _resolve_target_url(self, job: ImageJob, settings: Settings) -> Optional[str]:
        amazon_key = normalize_header(
            settings.sources.browser_fallback.amazon_url_column
        )
        if settings.sources.browser_fallback.allow_amazon_fallback:
            amazon_url = job.metadata.get(amazon_key)
            if amazon_url:
                return amazon_url

        for column_name in settings.sheet.source_url_columns:
            value = job.metadata.get(normalize_header(column_name))
            if not value:
                continue
            return value
        return None
