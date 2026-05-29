# web-scraper

Configurable Python pipeline for scraping product images, validating them, saving them using slot-style names such as `base_1` and `side_1`, and optionally uploading approved images to Magento through the official REST API.

## What this repo does

- Reads an Excel workbook and turns image-slot columns into image jobs.
- Supports scraping a single product URL directly with `scrape-url`.
- Tries multiple sources in priority order, with direct URLs pinned to the supplied domain.
- Downloads and validates images with resolution, duplicate, and watermark checks.
- Saves approved images locally with deterministic filenames.
- Writes JSON and CSV manifests for auditability and manual review.
- Optionally uploads approved images to Magento.

## Default source strategy

1. `gsmarena`
2. `official_media`
3. `browser_fallback`

Direct `scrape-url` runs and any row with an explicit non-GSMArena source URL stay pinned to that provided page/domain. Amazon is **not** the default source. If you need it later, provide an `amazonUrl` column and set `ALLOW_AMAZON_FALLBACK=true`.

## Project layout

- `config/settings.yaml` — default runtime configuration
- `src/web_scraper/` — scraper package and CLI
- `tests/` — regression tests and fixtures
- `output/` — saved images and run reports
- `.env.example` — placeholder env vars for Magento and runtime toggles

## Prerequisites

- Python `3.9+`
- `pip`
- Playwright Chromium browser for the browser fallback
- Optional: Tesseract OCR for text-based watermark detection

On macOS, install the optional OCR dependency with:

```bash
brew install tesseract
```

## Setup

### Option 1: use your existing virtual environment

```bash
source /Users/swapnilsinha/Desktop/Github/Nuroguru/NuroGuruBackend/services/langchain-service/.venv/bin/activate
cd /Users/swapnilsinha/Desktop/Github/web-scraper
python -m pip install -e '.[dev]'
playwright install chromium
```

### Option 2: create a fresh virtual environment

```bash
cd /Users/swapnilsinha/Desktop/Github/web-scraper
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
playwright install chromium
```

## Configuration

### Runtime config

Default settings live in `config/settings.yaml`.

Important defaults:

- output directory: `output/`
- source priority: `gsmarena -> official_media -> browser_fallback`
- minimum image size: `800x800`
- workbook source URL columns:
  - `officialMediaUrl`
  - `sourceUrl`
  - `amazonUrl`

### Environment variables

This project expects runtime configuration from `.env` and/or your shell environment.

Common variables:

- `MAGENTO_BASE_URL`
- `MAGENTO_ACCESS_TOKEN`
- `MAGENTO_ENABLED`
- `MAGENTO_DRY_RUN`
- `ALLOW_AMAZON_FALLBACK`
- `BROWSER_FALLBACK_ENABLED`
- `PLAYWRIGHT_HEADLESS`
- `TESSERACT_CMD`

If you need Magento upload, copy `.env.example` to `.env` and fill in the Magento values before running.

## Expected workbook defaults

The parser is config-driven, but the default assumptions are:

- SKU column: `sku`
- Product name column: `productName`
- Image slot columns such as:
  - `base_1`
  - `side_1`
  - `front_1`
  - `back_1`
  - `top_1`
  - `bottom_1`
- Optional source URL columns such as:
  - `officialMediaUrl`
  - `sourceUrl`
  - `amazonUrl`

If your workbook uses different headers, update `config/settings.yaml`.

## How to run

### 1. Preview workbook parsing

Use this to confirm the sheet is being interpreted correctly before scraping.

```bash
web-scraper parse-sheet /path/to/products.xlsx
```

### 2. Run a sheet-based scrape

Run the pipeline without Magento upload:

```bash
web-scraper run /path/to/products.xlsx --no-upload
```

Run the pipeline and allow Magento upload for this invocation:

```bash
web-scraper run /path/to/products.xlsx --upload
```

Limit the run to a small pilot batch:

```bash
web-scraper run /path/to/products.xlsx --limit 5 --no-upload
```

### 3. Scrape a single product URL

This is the fastest way to test a page without preparing an Excel sheet.

Basic usage:

```bash
web-scraper scrape-url "https://example.com/products/example-phone" \
  --sku EXAMPLE123 \
  --name "Example Phone" \
  --attribute base_1
```

Real example matching the recent direct-URL workflow:

```bash
web-scraper scrape-url "https://www.apple.com/in/iphone-17-pro/" \
  --sku IPHONE17 \
  --name "Apple iPhone 17 Pro"
```

Enable Magento upload for a single URL scrape:

```bash
web-scraper scrape-url "https://example.com/products/example-phone" \
  --sku EXAMPLE123 \
  --name "Example Phone" \
  --attribute base_1 \
  --upload
```

### CLI notes

- `scrape-url` uses `base_1` by default unless you pass `--attribute`
- direct URL runs write the same reports as sheet-based runs
- explicit product URLs are kept on-domain, which helps avoid unrelated image drift

## Outputs

- Approved images are saved under `output/images/<SKU>/`
- Temporary downloads are saved under `output/tmp/<RUN_ID>/`
- Run artifacts are saved under `output/runs/<RUN_ID>/`

Each run produces:

- `results.json`
- `review_queue.json`
- `manifest.csv`
- `summary.json`

## Validation and review

The current implementation uses:

- OCR keyword detection via `pytesseract`
- bright-region heuristics via `OpenCV`
- minimum resolution checks
- perceptual hash duplicate detection
- generic image ranking that prefers same-site product/device imagery over logos, banners, and unrelated marketing assets

Uncertain or rejected candidates are recorded for manual review instead of being uploaded automatically.

## Testing

Run the full suite:

```bash
source /Users/swapnilsinha/Desktop/Github/Nuroguru/NuroGuruBackend/services/langchain-service/.venv/bin/activate
cd /Users/swapnilsinha/Desktop/Github/web-scraper
pytest
```

Run a smaller regression subset while iterating on scraping logic:

```bash
pytest tests/test_gsmarena.py tests/test_official_media.py
```

## Notes

- `browser_fallback` is best-effort and is most useful when a product page requires rendered image sources.
- Magento upload uses the official REST API; this repo does **not** write directly to the Magento database.
- If you add more product categories or source types later, the cleanest extension point is a new source adapter under `src/web_scraper/sources/`.
