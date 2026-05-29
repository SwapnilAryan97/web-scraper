from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import quote

import httpx

from .config import MagentoSettings
from .models import UploadResult
from .utils import normalize_header

_DEFAULT_ROLE_MAP = {
    "base_": ["image", "small_image", "thumbnail"],
    "front_": ["image"],
    "side_": ["image"],
    "back_": ["image"],
}


def resolve_media_roles(attribute_name: str, settings: MagentoSettings) -> list[str]:
    normalized = normalize_header(attribute_name)
    if normalized in settings.role_mapping:
        return settings.role_mapping[normalized]
    for prefix, roles in _DEFAULT_ROLE_MAP.items():
        if normalized.startswith(prefix):
            return roles
    return ["image"]


def parse_position(attribute_name: str) -> int:
    normalized = normalize_header(attribute_name)
    suffix = normalized.rsplit("_", 1)[-1]
    return int(suffix) if suffix.isdigit() else 1


class MagentoClient:
    def __init__(self, settings: MagentoSettings) -> None:
        self.settings = settings

    def upload_image(
        self,
        *,
        sku: str,
        attribute_name: str,
        image_path: Path,
    ) -> UploadResult:
        if not self.settings.enabled:
            return UploadResult(
                success=False,
                sku=sku,
                attribute_name=attribute_name,
                image_path=image_path,
                message="Magento upload is disabled",
            )

        if self.settings.dry_run:
            return UploadResult(
                success=True,
                sku=sku,
                attribute_name=attribute_name,
                image_path=image_path,
                message="Dry-run enabled; upload skipped",
            )

        if not self.settings.base_url or not self.settings.access_token:
            raise ValueError("Magento client is missing base_url or access_token")

        encoded_bytes = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        mime_type = _guess_mime_type(image_path)
        payload = {
            "entry": {
                "media_type": "image",
                "label": attribute_name,
                "position": parse_position(attribute_name),
                "disabled": False,
                "types": resolve_media_roles(attribute_name, self.settings),
                "content": {
                    "base64_encoded_data": encoded_bytes,
                    "type": mime_type,
                    "name": image_path.name,
                },
            }
        }

        endpoint = f"{self.settings.base_url.rstrip('/')}/rest/V1/products/{quote(sku, safe='')}/media"
        headers = {
            "Authorization": f"Bearer {self.settings.access_token}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.settings.timeout_seconds) as client:
            response = client.post(endpoint, json=payload, headers=headers)

        success = response.status_code in {200, 201}
        return UploadResult(
            success=success,
            sku=sku,
            attribute_name=attribute_name,
            image_path=image_path,
            message="Upload succeeded" if success else "Upload failed",
            remote_id=str(response.json()) if success else None,
            status_code=response.status_code,
            response_body=response.text,
        )


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"
