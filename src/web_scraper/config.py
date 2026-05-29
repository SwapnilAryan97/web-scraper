from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from .utils import deep_merge, env_or_default, parse_bool, read_env_file


@dataclass
class ProjectSettings:
    output_dir: Path = Path("output")
    run_reports_dir: Path = Path("output/runs")
    temp_dir: Path = Path("output/tmp")


@dataclass
class SheetSettings:
    sheet_name: Optional[str] = None
    header_row: int = 1
    sku_column: str = "sku"
    sku_aliases: list[str] = field(default_factory=list)
    product_name_column: str = "productName"
    product_name_aliases: list[str] = field(default_factory=list)
    source_url_columns: list[str] = field(default_factory=list)
    process_filled_slots: bool = True
    image_slot_patterns: list[str] = field(default_factory=list)


@dataclass
class NetworkSettings:
    user_agent: str = "Mozilla/5.0"
    request_timeout_seconds: int = 20
    min_delay_seconds: float = 1.0
    max_delay_seconds: float = 3.0


@dataclass
class OfficialMediaSettings:
    enabled: bool = True
    extract_from_row_urls: bool = True


@dataclass
class BrowserFallbackSettings:
    enabled: bool = True
    headless: bool = True
    page_timeout_seconds: int = 30
    amazon_url_column: str = "amazonUrl"
    allow_amazon_fallback: bool = False


@dataclass
class SourceSettings:
    priority: list[str] = field(
        default_factory=lambda: ["gsmarena", "official_media", "browser_fallback"]
    )
    max_candidates_per_job: int = 8
    official_media: OfficialMediaSettings = field(default_factory=OfficialMediaSettings)
    browser_fallback: BrowserFallbackSettings = field(
        default_factory=BrowserFallbackSettings
    )


@dataclass
class QualitySettings:
    min_width: int = 800
    min_height: int = 800
    max_bytes: int = 15_000_000
    perceptual_hash_distance: int = 6
    preferred_extensions: list[str] = field(
        default_factory=lambda: [".jpg", ".jpeg", ".png", ".webp"]
    )


@dataclass
class WatermarkSettings:
    enabled: bool = True
    min_text_length: int = 4
    bright_region_threshold: int = 240
    max_suspect_regions: int = 35
    ocr_keywords: list[str] = field(default_factory=list)
    tesseract_cmd: Optional[str] = None


@dataclass
class MagentoSettings:
    enabled: bool = False
    dry_run: bool = True
    timeout_seconds: int = 30
    base_url: Optional[str] = None
    access_token: Optional[str] = None
    role_mapping: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Settings:
    root_dir: Path
    project: ProjectSettings = field(default_factory=ProjectSettings)
    sheet: SheetSettings = field(default_factory=SheetSettings)
    network: NetworkSettings = field(default_factory=NetworkSettings)
    sources: SourceSettings = field(default_factory=SourceSettings)
    quality: QualitySettings = field(default_factory=QualitySettings)
    watermark: WatermarkSettings = field(default_factory=WatermarkSettings)
    magento: MagentoSettings = field(default_factory=MagentoSettings)

    def validate(self) -> None:
        if self.network.min_delay_seconds > self.network.max_delay_seconds:
            raise ValueError(
                "network.min_delay_seconds cannot exceed network.max_delay_seconds"
            )
        if self.magento.enabled and (
            not self.magento.base_url or not self.magento.access_token
        ):
            raise ValueError(
                "Magento upload is enabled but MAGENTO_BASE_URL or MAGENTO_ACCESS_TOKEN is missing"
            )


def _resolve_path(root_dir: Path, value: Union[str, Path]) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return root_dir / path


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded or {}


def load_settings(
    config_path: Optional[Path] = None,
    *,
    env_path: Optional[Path] = None,
    root_dir: Optional[Path] = None,
) -> Settings:
    root = (root_dir or Path.cwd()).resolve()
    config_file = (config_path or root / "config" / "settings.yaml").resolve()
    env_file = (env_path or root / ".env").resolve()

    yaml_data = _load_yaml(config_file)
    env_values = read_env_file(env_file)

    if env_override := env_or_default("MAGENTO_BASE_URL", env_values):
        yaml_data = deep_merge(yaml_data, {"magento": {"base_url": env_override}})
    if env_override := env_or_default("MAGENTO_ACCESS_TOKEN", env_values):
        yaml_data = deep_merge(yaml_data, {"magento": {"access_token": env_override}})

    yaml_data = deep_merge(
        yaml_data,
        {
            "magento": {
                "enabled": parse_bool(
                    env_or_default("MAGENTO_ENABLED", env_values),
                    yaml_data.get("magento", {}).get("enabled", False),
                ),
                "dry_run": parse_bool(
                    env_or_default("MAGENTO_DRY_RUN", env_values),
                    yaml_data.get("magento", {}).get("dry_run", True),
                ),
            },
            "sources": {
                "browser_fallback": {
                    "enabled": parse_bool(
                        env_or_default("BROWSER_FALLBACK_ENABLED", env_values),
                        yaml_data.get("sources", {})
                        .get("browser_fallback", {})
                        .get("enabled", True),
                    ),
                    "headless": parse_bool(
                        env_or_default("PLAYWRIGHT_HEADLESS", env_values),
                        yaml_data.get("sources", {})
                        .get("browser_fallback", {})
                        .get("headless", True),
                    ),
                    "allow_amazon_fallback": parse_bool(
                        env_or_default("ALLOW_AMAZON_FALLBACK", env_values),
                        yaml_data.get("sources", {})
                        .get("browser_fallback", {})
                        .get("allow_amazon_fallback", False),
                    ),
                }
            },
            "watermark": {
                "tesseract_cmd": env_or_default(
                    "TESSERACT_CMD",
                    env_values,
                    yaml_data.get("watermark", {}).get("tesseract_cmd"),
                ),
            },
        },
    )

    project_data = yaml_data.get("project", {})
    sheet_data = yaml_data.get("sheet", {})
    network_data = yaml_data.get("network", {})
    sources_data = yaml_data.get("sources", {})
    official_media_data = sources_data.get("official_media", {})
    browser_fallback_data = sources_data.get("browser_fallback", {})
    quality_data = yaml_data.get("quality", {})
    watermark_data = yaml_data.get("watermark", {})
    magento_data = yaml_data.get("magento", {})

    settings = Settings(
        root_dir=root,
        project=ProjectSettings(
            output_dir=_resolve_path(root, project_data.get("output_dir", "output")),
            run_reports_dir=_resolve_path(
                root, project_data.get("run_reports_dir", "output/runs")
            ),
            temp_dir=_resolve_path(root, project_data.get("temp_dir", "output/tmp")),
        ),
        sheet=SheetSettings(
            sheet_name=sheet_data.get("sheet_name"),
            header_row=int(sheet_data.get("header_row", 1)),
            sku_column=sheet_data.get("sku_column", "sku"),
            sku_aliases=list(sheet_data.get("sku_aliases", [])),
            product_name_column=sheet_data.get("product_name_column", "productName"),
            product_name_aliases=list(sheet_data.get("product_name_aliases", [])),
            source_url_columns=list(sheet_data.get("source_url_columns", [])),
            process_filled_slots=bool(sheet_data.get("process_filled_slots", True)),
            image_slot_patterns=list(sheet_data.get("image_slot_patterns", [])),
        ),
        network=NetworkSettings(
            user_agent=network_data.get("user_agent", "Mozilla/5.0"),
            request_timeout_seconds=int(
                network_data.get("request_timeout_seconds", 20)
            ),
            min_delay_seconds=float(network_data.get("min_delay_seconds", 1.0)),
            max_delay_seconds=float(network_data.get("max_delay_seconds", 3.0)),
        ),
        sources=SourceSettings(
            priority=list(
                sources_data.get(
                    "priority", ["gsmarena", "official_media", "browser_fallback"]
                )
            ),
            max_candidates_per_job=int(sources_data.get("max_candidates_per_job", 8)),
            official_media=OfficialMediaSettings(
                enabled=bool(official_media_data.get("enabled", True)),
                extract_from_row_urls=bool(
                    official_media_data.get("extract_from_row_urls", True)
                ),
            ),
            browser_fallback=BrowserFallbackSettings(
                enabled=bool(browser_fallback_data.get("enabled", True)),
                headless=bool(browser_fallback_data.get("headless", True)),
                page_timeout_seconds=int(
                    browser_fallback_data.get("page_timeout_seconds", 30)
                ),
                amazon_url_column=browser_fallback_data.get(
                    "amazon_url_column", "amazonUrl"
                ),
                allow_amazon_fallback=bool(
                    browser_fallback_data.get("allow_amazon_fallback", False)
                ),
            ),
        ),
        quality=QualitySettings(
            min_width=int(quality_data.get("min_width", 800)),
            min_height=int(quality_data.get("min_height", 800)),
            max_bytes=int(quality_data.get("max_bytes", 15_000_000)),
            perceptual_hash_distance=int(
                quality_data.get("perceptual_hash_distance", 6)
            ),
            preferred_extensions=list(
                quality_data.get(
                    "preferred_extensions", [".jpg", ".jpeg", ".png", ".webp"]
                )
            ),
        ),
        watermark=WatermarkSettings(
            enabled=bool(watermark_data.get("enabled", True)),
            min_text_length=int(watermark_data.get("min_text_length", 4)),
            bright_region_threshold=int(
                watermark_data.get("bright_region_threshold", 240)
            ),
            max_suspect_regions=int(watermark_data.get("max_suspect_regions", 35)),
            ocr_keywords=list(watermark_data.get("ocr_keywords", [])),
            tesseract_cmd=watermark_data.get("tesseract_cmd"),
        ),
        magento=MagentoSettings(
            enabled=bool(magento_data.get("enabled", False)),
            dry_run=bool(magento_data.get("dry_run", True)),
            timeout_seconds=int(magento_data.get("timeout_seconds", 30)),
            base_url=magento_data.get("base_url"),
            access_token=magento_data.get("access_token"),
            role_mapping={
                key: list(value)
                for key, value in magento_data.get("role_mapping", {}).items()
            },
        ),
    )

    settings.validate()
    return settings
