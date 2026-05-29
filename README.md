# web-scraper

Configurable Python pipeline for scraping product images, validating them, saving them using sheet-driven nomenclature such as `base_1` and `Side_1`, and optionally uploading approved images to Magento through the official REST API.

## What this repo does

- Reads an Excel workbook and turns image-slot columns into image jobs.
- Tries safer image sources first: `GSM Arena` and row-provided official media URLs.
- Supports a browser-based fallback for harder pages, with Amazon kept behind an explicit opt-in switch.
- Downloads and validates images with resolution, duplicate, and watermark checks.
- Saves approved images locally with deterministic filenames.
- Writes JSON and CSV manifests for auditability and manual review.
- Optionally uploads approved images to Magento.

## Default source strategy

1. `gsmarena`
2. `official_media`
3. `browser_fallback`

Amazon is **not** the default source. If you need it later, provide an `amazonUrl` column and set `ALLOW_AMAZON_FALLBACK=true`.

## Project layout

- `config/settings.yaml` — default runtime configuration
- `src/web_scraper/` — scraper package
- `tests/` — regression tests and GSM Arena fixtures
- `.env.example` — placeholder env vars for Magento and runtime toggles

## Setup

Use your existing Python environment, then install the project in editable mode.

```bash
source /Users/swapnilsinha/Desktop/Github/Nuroguru/NuroGuruBackend/services/langchain-service/.venv/bin/activate
cd /Users/swapnilsinha/Desktop/Github/web-scraper
python -m pip install -e '.[dev]'
playwright install chromium
```

For OCR-based watermark detection, install the Tesseract binary on macOS:

```bash
brew install tesseract
```

## Environment variables

This repo includes both `.env.example` and a placeholder `.env` because Magento credentials and runtime toggles are expected at runtime.

Relevant variables:

- `MAGENTO_BASE_URL`
- `MAGENTO_ACCESS_TOKEN`
- `MAGENTO_ENABLED`
- `MAGENTO_DRY_RUN`
- `ALLOW_AMAZON_FALLBACK`
- `BROWSER_FALLBACK_ENABLED`
- `PLAYWRIGHT_HEADLESS`
- `TESSERACT_CMD`

## Expected workbook defaults

The parser is config-driven, but the default assumptions are:

- SKU column: `sku`
- Product name column: `productName`
- Image slot columns like `base_1`, `side_1`, `front_1`, `back_1`
- Optional source URL columns like `officialMediaUrl`, `sourceUrl`, and `amazonUrl`

If your sheet uses different names, update `config/settings.yaml`.

## Usage

Preview how the workbook will be parsed:

```bash
web-scraper parse-sheet /path/to/products.xlsx
```

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

## Outputs

- Approved images are saved under `output/images/<SKU>/`
- Run artifacts are saved under `output/runs/<RUN_ID>/`
- Each run produces:
  - `results.json`
  - `review_queue.json`
  - `manifest.csv`
  - `summary.json`

## Watermark and quality review

The current implementation uses:

- OCR keyword detection via `pytesseract`
- bright-region heuristics via `OpenCV`
- minimum resolution checks
- perceptual hash duplicate detection

Uncertain or rejected candidates are recorded for manual review instead of being uploaded automatically.

## Testing

```bash
source /Users/swapnilsinha/Desktop/Github/Nuroguru/NuroGuruBackend/services/langchain-service/.venv/bin/activate
cd /Users/swapnilsinha/Desktop/Github/web-scraper
pytest
```

## Notes

- `browser_fallback` is best-effort and designed for explicit product URLs already present in the sheet.
- Magento upload uses the official REST API; this repo does **not** write directly to the Magento database.
- If you later add more product categories, the easiest extension point is a new source adapter under `src/web_scraper/sources/`.
