from web_scraper.config import MagentoSettings
from web_scraper.magento import parse_position, resolve_media_roles


def test_resolve_media_roles_prefers_exact_mapping_then_prefix_defaults():
    settings = MagentoSettings(role_mapping={"side_7": ["small_image"]})

    assert resolve_media_roles("side_7", settings) == ["small_image"]
    assert resolve_media_roles("base_2", settings) == [
        "image",
        "small_image",
        "thumbnail",
    ]
    assert resolve_media_roles("detail_1", settings) == ["image"]


def test_parse_position_uses_numeric_suffix():
    assert parse_position("Side_12") == 12
    assert parse_position("thumbnail") == 1
