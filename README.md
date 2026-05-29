# web-scraper

A configurable Python pipeline that scrapes product images from official manufacturer pages and
third-party sources, validates them against resolution, duplicate, and watermark criteria, and
optionally uploads approved images to Magento via its REST API.

---

## Table of contents

- [Overview](#overview)
- [Source strategy](#source-strategy)
- [Project layout](#project-layout)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Configuration](#configuration)
  - [Runtime settings](#runtime-settings)
  - [Environment variables](#environment-variables)
- [Workbook format](#workbook-format)
- [How to run](#how-to-run)
  - [1. Preview workbook parsing](#1-preview-workbook-parsing)
  - [2. Sheet-based scrape](#2-sheet-based-scrape)
  - [3. Single URL scrape](#3-single-url-scrape)
- [CLI reference](#cli-reference)
- [Outputs](#outputs)
- [Image validation](#image-validation)
- [Risks and known limitations](#risks-and-known-limitations)
- [Testing](#testing)
- [Notes](#notes)

---

## Overview

The pipeline accepts either an Excel workbook or a single product URL, then works through a
prioritised list of image sources to find the best available product image for each slot. Each
candidate is evaluated for resolution, watermarks, and visual uniqueness before being saved. A
full audit trail is written to JSON and CSV for every run.

Key capabilities:

- Reads an Excel workbook and turns image-slot columns into individual image jobs.
- Supports scraping a single product URL directly with the `scrape-url` command.
- Evaluates multiple sources in priority order; direct URLs stay pinned to the supplied domain.
- Ranks candidates using generic, site-agnostic signals: same-site affinity, product-name token
  overlap, image dimensions, srcset width hints, and device-view context cues.
- Saves approved images locally under deterministic, slot-style filenames (`base_1`, `side_1`, …).
- Writes `results.json`, `review_queue.json`, `manifest.csv`, and `summary.json` for every run.
- Optionally uploads approved images to Magento through the official REST API.

---

## Source strategy

Sources are attempted in the order defined in `config/settings.yaml`. The default order is:

| Priority | Source             | Description                                                                                                                                                         |
| -------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1        | `gsmarena`         | Queries [GSMArena][gsmarena] for device specifications and product images. Skipped automatically when an explicit non-GSMArena URL is already provided for the job. |
| 2        | `official_media`   | Fetches the provided product page and ranks all image candidates using a generic scoring model.                                                                     |
| 3        | `browser_fallback` | Launches a headless Chromium browser via [Playwright][playwright] to resolve JavaScript-rendered image sources.                                                     |

Amazon is not a default source. To enable it, add an `amazonUrl` column to the workbook and set
`ALLOW_AMAZON_FALLBACK=true`.

---

## Project layout

```
.
├── config/
│   └── settings.yaml            # Default runtime configuration
├── src/
│   └── web_scraper/
│       ├── cli.py               # CLI entrypoint (web-scraper command)
│       ├── pipeline.py          # Main orchestration loop
│       ├── images.py            # Download, quality, and persistence helpers
│       ├── watermark.py         # OCR and heuristic watermark detection
│       ├── sheets.py            # Excel workbook parser
│       ├── magento.py           # Magento REST API client
│       ├── models.py            # Shared dataclasses
│       └── sources/
│           ├── gsmarena.py      # GSMArena adapter
│           ├── official_media.py # Official page adapter with candidate scoring
│           └── browser_fallback.py # Playwright-based fallback
├── tests/                       # Regression tests and HTML fixtures
├── output/                      # Saved images and run reports (git-ignored)
├── .env.example                 # Placeholder environment variable file
└── pyproject.toml
```

---

## Prerequisites

| Requirement                       | Notes                                                 |
| --------------------------------- | ----------------------------------------------------- |
| Python 3.9 or later               | 3.11+ recommended                                     |
| pip                               | Bundled with Python                                   |
| [Playwright][playwright] Chromium | Required for the `browser_fallback` source            |
| [Tesseract OCR][tesseract]        | Optional. Required for text-based watermark detection |

**macOS** — install Tesseract with [Homebrew][homebrew]:

```bash
brew install tesseract
```

**Linux (Debian / Ubuntu)**:

```bash
sudo apt-get install tesseract-ocr
```

---

## Setup

Choose whichever setup flow matches your machine best.

### Option 1: use an existing virtual environment

This is handy when you already have a shared or parent-project virtual environment and want to
reuse it instead of creating another one for this repo.

```bash
source /path/to/existing/project/.venv/bin/activate
cd /path/to/web-scraper
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
playwright install chromium
```

Replace `/path/to/existing/project/.venv` and `/path/to/web-scraper` with paths that exist on
your machine.

### Option 2: create a repo-local virtual environment

```bash
cd /path/to/web-scraper
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
playwright install chromium
```

The `[dev]` extra installs `pytest`. Omit it for a production-only installation.

If you do not need Magento upload yet, you can leave the placeholder values in `.env` as-is.

---

## Configuration

### Runtime settings

All defaults live in [`config/settings.yaml`](config/settings.yaml). The most commonly adjusted
settings are:

| Setting                          | Default                                        | Description                                  |
| -------------------------------- | ---------------------------------------------- | -------------------------------------------- |
| `sources.priority`               | `[gsmarena, official_media, browser_fallback]` | Order in which sources are attempted per job |
| `sources.max_candidates_per_job` | `8`                                            | Maximum candidates evaluated per image slot  |
| `quality.min_width`              | `800`                                          | Minimum accepted image width in pixels       |
| `quality.min_height`             | `800`                                          | Minimum accepted image height in pixels      |
| `watermark.enabled`              | `true`                                         | Toggle OCR and heuristic watermark checks    |
| `magento.enabled`                | `false`                                        | Toggle Magento upload                        |
| `magento.dry_run`                | `true`                                         | Simulate upload without writing to Magento   |

### Environment variables

Copy `.env.example` to `.env` and populate the values relevant to your environment. Variables can
also be set directly in the shell.

| Variable                   | Required   | Description                                              |
| -------------------------- | ---------- | -------------------------------------------------------- |
| `MAGENTO_BASE_URL`         | For upload | Base URL of your Magento store                           |
| `MAGENTO_ACCESS_TOKEN`     | For upload | Admin API access token                                   |
| `MAGENTO_ENABLED`          | No         | Set to `true` to enable upload                           |
| `MAGENTO_DRY_RUN`          | No         | Set to `false` to write to Magento                       |
| `ALLOW_AMAZON_FALLBACK`    | No         | Set to `true` to allow Amazon source URLs                |
| `BROWSER_FALLBACK_ENABLED` | No         | Set to `false` to disable Playwright                     |
| `PLAYWRIGHT_HEADLESS`      | No         | Set to `false` to show the browser window                |
| `TESSERACT_CMD`            | No         | Absolute path to the `tesseract` binary if not on `PATH` |

---

## Workbook format

The workbook parser is config-driven. Default column name expectations are:

| Column purpose     | Default header                                               | Common aliases                                              |
| ------------------ | ------------------------------------------------------------ | ----------------------------------------------------------- |
| SKU                | `sku`                                                        | `product_sku`, `sku_code`                                   |
| Product name       | `productName`                                                | `product_name`, `title`, `name`, `model_name`               |
| Image slots        | `base_1`, `side_1`, `front_1`, `back_1`, `top_1`, `bottom_1` | Any column matching `sheet.image_slot_patterns` in settings |
| Official media URL | `officialMediaUrl`                                           | —                                                           |
| Source URL         | `sourceUrl`                                                  | —                                                           |
| Amazon URL         | `amazonUrl`                                                  | —                                                           |

To use different headers, update the relevant keys under `sheet:` in `config/settings.yaml`.

---

## How to run

### 1. Preview workbook parsing

Inspect how the workbook will be interpreted before committing to a full run.

```bash
web-scraper parse-sheet /path/to/products.xlsx
web-scraper parse-sheet /path/to/products.xlsx --limit 20
```

### 2. Sheet-based scrape

Run the full pipeline against an Excel workbook:

```bash
# Dry run, no upload
web-scraper run /path/to/products.xlsx --no-upload

# Enable Magento upload for this invocation
web-scraper run /path/to/products.xlsx --upload

# Pilot batch limited to the first 5 rows
web-scraper run /path/to/products.xlsx --limit 5 --no-upload
```

### 3. Single URL scrape

Scrape one product page without preparing a workbook. Useful for testing or one-off jobs.

```bash
# Minimal usage — image slot defaults to base_1
web-scraper scrape-url "https://example.com/products/example-phone" \
  --sku EXAMPLE123 \
  --name "Example Phone"

# Specify a different image slot
web-scraper scrape-url "https://example.com/products/example-phone" \
  --sku EXAMPLE123 \
  --name "Example Phone" \
  --attribute side_1

# With Magento upload
web-scraper scrape-url "https://example.com/products/example-phone" \
  --sku EXAMPLE123 \
  --name "Example Phone" \
  --upload
```

---

## CLI reference

```
web-scraper <command> [options]

Commands:
  parse-sheet   Inspect how a workbook will be parsed. No images are downloaded.
  run           Run the full scraping pipeline against a workbook.
  scrape-url    Scrape a single product URL without a workbook.

Common options:
  --config PATH        Path to a settings YAML file  (default: config/settings.yaml)
  --env-file PATH      Path to a .env file           (default: .env)
  --log-level LEVEL    Logging verbosity              (default: INFO)

run / parse-sheet options:
  WORKBOOK             Path to the Excel file (required, positional)
  --limit N            Process only the first N product rows

scrape-url options:
  URL                  Product page URL               (required, positional)
  --sku TEXT           SKU used for saved filenames   (default: unknown)
  --name TEXT          Product name used for ranking  (default: derived from URL)
  --attribute TEXT     Image slot name                (default: base_1)
  --upload / --no-upload
```

---

## Outputs

| Path                                     | Description                                |
| ---------------------------------------- | ------------------------------------------ |
| `output/images/<SKU>/`                   | Approved images saved as `<attribute>.jpg` |
| `output/tmp/<RUN_ID>/`                   | Temporary candidate downloads for the run  |
| `output/runs/<RUN_ID>/results.json`      | Full result detail for every job           |
| `output/runs/<RUN_ID>/review_queue.json` | Jobs that were flagged or failed           |
| `output/runs/<RUN_ID>/manifest.csv`      | Flat CSV summary of every job              |
| `output/runs/<RUN_ID>/summary.json`      | Aggregate counts for the run               |

---

## Image validation

Each candidate passes through the following checks before being approved:

| Check                             | Implementation                                                                                                 | Configurable |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------------ |
| Minimum resolution                | `quality.min_width` / `quality.min_height` in settings                                                         | Yes          |
| Maximum file size                 | `quality.max_bytes` in settings                                                                                | Yes          |
| Perceptual duplicate detection    | [ImageHash][imagehash] pHash with a configurable Hamming distance threshold                                    | Yes          |
| Watermark keyword detection       | [pytesseract][pytesseract] OCR over the image                                                                  | Yes          |
| Bright-region watermark heuristic | [OpenCV][opencv] region analysis                                                                               | Yes          |
| Candidate ranking                 | Generic scoring on same-site affinity, product-name overlap, dimensions, srcset hints, and device-view context | No           |

Jobs that produce no approved candidate are written to `review_queue.json` for manual inspection.

---

## Risks and known limitations

Automated scraping carries inherent technical, operational, and legal risks. The table below
documents the blockers most commonly encountered and the current pipeline behaviour in each case.

| Risk                                                 | Likelihood               | Current behaviour                                                                             | Mitigation                                                                                                                            |
| ---------------------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Anti-bot protection** (Cloudflare, Akamai, Distil) | High for large retailers | HTTP request returns a JS challenge page; `official_media` finds no usable images             | Enable `browser_fallback`; advanced WAF fingerprinting may still block headless Chromium                                              |
| **Rate limiting** (HTTP 429)                         | Medium                   | Request fails with an exception; the source is skipped for that job                           | Increase `network.min_delay_seconds` in settings; no automatic retry or back-off is implemented                                       |
| **IP blocking** after repeated bulk requests         | Medium                   | Requests begin returning 403 or connection resets                                             | Use polite delays between jobs; distribute bulk runs across sessions or rotate via a proxy                                            |
| **JavaScript-rendered image sources**                | High for modern SPAs     | Static HTML contains `data:image/gif` placeholder `src` values instead of real URLs           | Enable `browser_fallback`; Playwright resolves `currentSrc` after the page renders                                                    |
| **Lazy-loaded images** below the viewport            | Medium                   | Playwright loads to `domcontentloaded` and collects whatever is resolved at that point        | Scroll the page before collecting `img` elements (not currently implemented)                                                          |
| **CAPTCHA**                                          | Low–Medium               | Browser session stalls on the challenge page, then times out                                  | No automatic solving; the job is skipped and written to `review_queue.json`                                                           |
| **Session or cookie requirement**                    | Low–Medium               | Request returns a login wall or an empty product page                                         | No session management is implemented; provide pre-authenticated URLs where possible                                                   |
| **CDN hotlink protection**                           | Medium                   | Image CDN returns 403 when `Referer` is absent or unexpected                                  | The pipeline sends a realistic `User-Agent`; `Referer` injection is not implemented                                                   |
| **Terms of service / `robots.txt`**                  | Variable by site         | The pipeline does not check [`robots.txt`][robots] or ToS before fetching                     | Review the target site's ToS before bulk scraping; scraping for internal data enrichment may be permitted where redistribution is not |
| **Geo-restricted product pages**                     | Low–Medium               | Page redirects to a regional storefront with different URLs or content                        | Use the correct regional URL in the workbook; no automatic cross-region redirect following                                            |
| **HTML structure changes** (selector drift)          | Low, ongoing             | GSMArena-specific selectors stop matching; source returns zero candidates                     | Monitor `review_queue.json` for clusters of failures and update selectors when needed                                                 |
| **Image quality ceiling on responsive pages**        | Medium                   | Static HTML may only expose small-breakpoint `src` values; larger sizes are behind JavaScript | `browser_fallback` resolves the browser-selected `currentSrc`, which reflects the rendered breakpoint                                 |
| **Product URL instability**                          | Low                      | URLs hardcoded in the workbook go stale when a site restructures                              | Re-validate source URLs periodically; prefer canonical URLs where available                                                           |

---

## Testing

Run the full test suite:

```bash
pytest
```

Run with verbose output to see individual test names:

```bash
pytest -v
```

Run only the scraping-logic regression tests:

```bash
pytest tests/test_gsmarena.py tests/test_official_media.py
```

Tests are also run automatically on every push and pull request via
[GitHub Actions][actions-workflow] (see `.github/workflows/tests.yml`).

---

## Notes

- `browser_fallback` is best-effort. Advanced bot-detection systems can identify headless
  Chromium even with a realistic user agent.
- Magento upload uses the official REST API. This project does not interact with the Magento
  database directly.
- The candidate scoring weights in `src/web_scraper/sources/official_media.py` are currently
  hardcoded constants. They can be promoted to a `scoring:` block in `config/settings.yaml` if
  per-site tuning is needed.
- Adding support for a new product page type requires only a new class that extends `ImageSource`
  in `src/web_scraper/sources/`, implementing `fetch_candidates`, and registering the source name
  in `sources.priority`.

[gsmarena]: https://www.gsmarena.com
[playwright]: https://playwright.dev/python/
[tesseract]: https://github.com/tesseract-ocr/tesseract
[homebrew]: https://brew.sh
[imagehash]: https://github.com/JohannesBuchner/imagehash
[pytesseract]: https://github.com/madmaze/pytesseract
[opencv]: https://opencv.org
[robots]: https://www.robotstxt.org
[actions-workflow]: .github/workflows/tests.yml
