from pathlib import Path

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
