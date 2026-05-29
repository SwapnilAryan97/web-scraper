from web_scraper.config import load_settings


def test_load_settings_applies_environment_overrides(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.yaml").write_text(
        """
magento:
  enabled: false
  dry_run: false
sources:
  browser_fallback:
    allow_amazon_fallback: false
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "MAGENTO_BASE_URL=https://store.example.com",
                "MAGENTO_ACCESS_TOKEN=token-123",
                "MAGENTO_ENABLED=true",
                "MAGENTO_DRY_RUN=true",
                "ALLOW_AMAZON_FALLBACK=true",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(root_dir=tmp_path)

    assert settings.magento.base_url == "https://store.example.com"
    assert settings.magento.access_token == "token-123"
    assert settings.magento.enabled is True
    assert settings.magento.dry_run is True
    assert settings.sources.browser_fallback.allow_amazon_fallback is True
