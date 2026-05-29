from web_scraper.sources.official_media import extract_image_candidates


def test_extract_image_candidates_prefers_product_hero_srcset_over_lifestyle_assets():
    html = """
    <html>
      <head>
        <meta property="og:image" content="https://cdn.example.com/share/examplephone-share.jpg" />
        <link rel="preload" as="image" imagesrcset="/images/examplephone-front-900.jpg 900w, /images/examplephone-front-1800.jpg 1800w" />
      </head>
      <body>
        <img src="/assets/logo.png" alt="ExamplePhone brand logo" width="120" height="40" />

        <picture class="product-hero overview-gallery">
          <source srcset="/images/examplephone-front-900.jpg 900w, /images/examplephone-front-1800.jpg 1800w" />
          <img
            src="/images/examplephone-front-900.jpg"
            alt="ExamplePhone 12 Pro front exterior in black finish"
            width="900"
            height="1200"
          />
        </picture>

        <img
          src="/images/lifestyle-battery.jpg"
          alt="A scene from the launch film showing ExamplePhone 12 Pro battery feature in use"
          width="2400"
          height="1600"
        />

        <img
          src="https://ads.example-cdn.com/banner.jpg"
          alt="Buy ExamplePhone 12 Pro now"
          width="2200"
          height="1200"
        />
      </body>
    </html>
    """

    candidates = extract_image_candidates(
        html,
        "https://shop.example.com/products/examplephone-12-pro",
        "ExamplePhone 12 Pro",
    )

    assert candidates
    assert (
        candidates[0].image_url
        == "https://shop.example.com/images/examplephone-front-1800.jpg"
    )
    assert candidates[0].score > candidates[1].score

    logo_candidate = next(
        candidate
        for candidate in candidates
        if candidate.image_url.endswith("logo.png")
    )
    assert logo_candidate.score < candidates[0].score
