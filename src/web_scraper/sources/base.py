from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from ..config import Settings
from ..models import ImageCandidate, ImageJob


class ImageSource(ABC):
    name = "base"

    @abstractmethod
    def fetch_candidates(
        self,
        job: ImageJob,
        *,
        client: httpx.Client,
        settings: Settings,
    ) -> list[ImageCandidate]:
        raise NotImplementedError
