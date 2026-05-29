from pathlib import Path

from web_scraper.config import Settings
from web_scraper.models import ImageJob
from web_scraper.sources.gsmarena import GsmArenaSource
from web_scraper.sources.gsmarena import (
    parse_gallery_page,
    parse_product_page,
    parse_search_results,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_search_results_extracts_titles_and_urls():
    html = (FIXTURES / "gsmarena_search.html").read_text(encoding="utf-8")

    results = parse_search_results(html)

    assert results[0]["title"] == "Apple iPhone 15"
    assert results[0]["url"].endswith("apple_iphone_15-12559.php")


def test_parse_product_page_and_gallery_extract_images():
    product_html = (FIXTURES / "gsmarena_product.html").read_text(encoding="utf-8")
    gallery_html = (FIXTURES / "gsmarena_gallery.html").read_text(encoding="utf-8")

    product_images, gallery_url = parse_product_page(
        product_html,
        "https://www.gsmarena.com/apple_iphone_15-12559.php",
    )
    gallery_images = parse_gallery_page(
        gallery_html,
        "https://www.gsmarena.com/apple_iphone_15-pictures-12559.php",
    )

    assert gallery_url and gallery_url.endswith("apple_iphone_15-pictures-12559.php")
    assert (
        "https://fdn2.gsmarena.com/vv/pics/apple/apple-iphone-15-1.jpg"
        in product_images
    )
    assert gallery_images == [
        "https://fdn2.gsmarena.com/vv/pics/apple/apple-iphone-15-3.jpg",
        "https://fdn2.gsmarena.com/vv/pics/apple/apple-iphone-15-4.jpg",
    ]


def test_parse_product_page_ignores_unrelated_page_images():
    html = """
        <html>
            <head>
                <meta property="og:image" content="https://fdn2.gsmarena.com/vv/pics/apple/apple-iphone-15-1.jpg" />
            </head>
            <body>
                <div class="specs-photo-main">
                    <img src="https://fdn2.gsmarena.com/vv/pics/apple/apple-iphone-15-2.jpg" />
                </div>
                <div class="related-devices">
                    <img src="https://fdn2.gsmarena.com/vv/pics/vivo/vivo-x200-fe-1.jpg" />
                    <img src="https://fdn.gsmarena.com/imgroot/static/logo.png" />
                </div>
            </body>
        </html>
        """

    product_images, _ = parse_product_page(
        html,
        "https://www.gsmarena.com/apple_iphone_15-12559.php",
    )

    assert product_images == [
        "https://fdn2.gsmarena.com/vv/pics/apple/apple-iphone-15-1.jpg",
        "https://fdn2.gsmarena.com/vv/pics/apple/apple-iphone-15-2.jpg",
    ]


def test_gsmarena_source_skips_search_when_job_has_explicit_non_gsmarena_url(tmp_path):
    job = ImageJob(
        row_number=1,
        sku="SKU-1",
        product_name="Example Phone",
        attribute_name="base_1",
        metadata={"officialmediaurl": "https://example.com/products/example-phone"},
    )
    settings = Settings(root_dir=tmp_path)

    class UnexpectedCallClient:
        def get(self, url: str):  # pragma: no cover - assertion path only
            raise AssertionError(f"Unexpected GSMArena lookup for {url}")

    candidates = GsmArenaSource().fetch_candidates(
        job,
        client=UnexpectedCallClient(),
        settings=settings,
    )

    assert candidates == []
