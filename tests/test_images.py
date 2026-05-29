from PIL import Image

from web_scraper.config import Settings
from web_scraper.images import build_final_image_path, evaluate_quality
from web_scraper.models import ImageCandidate


def test_build_final_image_path_uses_sheet_attribute_name(tmp_path):
    source_path = tmp_path / "source.JPG"
    source_path.write_bytes(b"placeholder")

    final_path = build_final_image_path(
        tmp_path / "output", "SKU 123", "Side_1", source_path
    )

    assert final_path.name == "SKU_123_Side_1.jpg"
    assert final_path.parent.name == "SKU_123"


def test_evaluate_quality_flags_small_images(tmp_path):
    image_path = tmp_path / "tiny.jpg"
    Image.new("RGB", (100, 100), color="white").save(image_path)

    candidate = ImageCandidate(
        source_name="test",
        image_url="https://example.com/tiny.jpg",
        local_path=image_path,
        width=100,
        height=100,
    )
    settings = Settings(root_dir=tmp_path)

    issues = evaluate_quality(candidate, settings)

    assert any(
        issue.category == "resolution" and issue.severity == "error" for issue in issues
    )
