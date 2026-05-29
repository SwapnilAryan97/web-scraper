from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from ._logging import ProgressLogger, _supports_color, setup_logging
from .config import load_settings
from .models import ImageJob
from .pipeline import ScraperPipeline
from .sheets import load_image_jobs

LOGGER = logging.getLogger(__name__)
_progress = ProgressLogger(__name__)

# ANSI helpers used only for the final summary table printed to stdout
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _c(text: str, code: str) -> str:
    """Wrap *text* in an ANSI code when stdout supports color."""
    if _supports_color(sys.stdout):
        return f"{code}{text}{_RESET}"
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web-scraper",
        description="Scrape product images, validate them, and optionally upload to Magento.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/settings.yaml"),
        help="Path to the YAML settings file.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to the environment file.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_sheet = subparsers.add_parser(
        "parse-sheet", help="Parse the workbook into image jobs."
    )
    parse_sheet.add_argument("sheet", type=Path, help="Path to the Excel workbook.")
    parse_sheet.add_argument(
        "--limit", type=int, default=10, help="Preview at most this many jobs."
    )

    run = subparsers.add_parser(
        "run", help="Run scraping, validation, and optional upload."
    )
    run.add_argument("sheet", type=Path, help="Path to the Excel workbook.")
    run.add_argument("--limit", type=int, help="Limit the number of jobs processed.")
    upload_group = run.add_mutually_exclusive_group()
    upload_group.add_argument(
        "--upload",
        dest="upload",
        action="store_true",
        help="Enable Magento upload for this run.",
    )
    upload_group.add_argument(
        "--no-upload",
        dest="upload",
        action="store_false",
        help="Disable Magento upload for this run.",
    )
    run.set_defaults(upload=None)

    scrape_url = subparsers.add_parser(
        "scrape-url",
        help="Scrape images from a single URL without an Excel sheet.",
    )
    scrape_url.add_argument("url", help="Product page URL to scrape images from.")
    scrape_url.add_argument(
        "--sku",
        default="unknown",
        help="SKU to use when saving images (default: unknown).",
    )
    scrape_url.add_argument(
        "--name",
        default="",
        help="Product name to use for source search (default: derived from URL).",
    )
    scrape_url.add_argument(
        "--attribute",
        default="base_1",
        help="Image attribute/slot name (default: base_1).",
    )
    scrape_url_upload = scrape_url.add_mutually_exclusive_group()
    scrape_url_upload.add_argument(
        "--upload",
        dest="upload",
        action="store_true",
        help="Enable Magento upload after scraping.",
    )
    scrape_url_upload.add_argument(
        "--no-upload",
        dest="upload",
        action="store_false",
        help="Disable Magento upload (default).",
    )
    scrape_url.set_defaults(upload=None)

    return parser


def configure_logging(level: str) -> None:
    setup_logging(level)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    settings = load_settings(args.config, env_path=args.env_file, root_dir=Path.cwd())

    if args.command == "parse-sheet":
        _progress.start("Parsing workbook", path=str(args.sheet))
        jobs = load_image_jobs(args.sheet, settings)
        _progress.success(
            f"Found {len(jobs)} image job(s)", showing=min(args.limit, len(jobs))
        )
        print()
        header = f"  {'ROW':>4}  {'SKU':<20}  {'ATTRIBUTE':<18}  PRODUCT"
        print(_c(header, _DIM))
        print(_c("  " + "─" * (len(header) - 2), _DIM))
        for job in jobs[: args.limit]:
            row_str = _c(f"{job.row_number:>4}", _DIM)
            sku_str = _c(f"{job.sku:<20}", _CYAN)
            attr_str = _c(f"{job.attribute_name:<18}", _YELLOW)
            print(f"  {row_str}  {sku_str}  {attr_str}  {job.product_name}")
        if len(jobs) > args.limit:
            print(
                _c(
                    f"\n  … {len(jobs) - args.limit} more job(s) not shown (increase --limit)",
                    _DIM,
                )
            )
        return 0

    if args.command == "run":
        _progress.section("Starting scrape run")
        _progress.start("Loading workbook", path=str(args.sheet))
        pipeline = ScraperPipeline(settings)
        try:
            results, report_paths = pipeline.run(
                args.sheet, limit=args.limit, allow_upload=args.upload
            )
        finally:
            pipeline.close()

        approved = sum(result.status == "approved" for result in results)
        flagged = sum(result.status == "flagged" for result in results)
        failed = sum(result.status == "failed" for result in results)

        print()
        print(_c("━━━  Run Summary  ━━━", _BOLD))
        print(f"  Total jobs : {_c(str(len(results)), _BOLD)}")
        print(f"  {_c('✓ Approved', _GREEN)} : {_c(str(approved), _GREEN)}")
        print(f"  {_c('⚠ Flagged ', _YELLOW)} : {_c(str(flagged), _YELLOW)}")
        print(f"  {_c('✗ Failed  ', _RED)} : {_c(str(failed), _RED)}")
        print()
        print(_c("Reports written:", _DIM))
        for label, path in report_paths.items():
            print(f"  {_c(label + ':', _DIM)} {path}")
        return 0

    if args.command == "scrape-url":
        from urllib.parse import urlparse

        product_name = (
            args.name
            or urlparse(args.url)
            .path.rsplit("/", 1)[-1]
            .replace("-", " ")
            .split(".")[0]
        )
        _progress.section(f"Scraping URL for {args.sku!r}")
        _progress.start(
            "Building image job",
            sku=args.sku,
            product=product_name,
            attribute=args.attribute,
        )
        job = ImageJob(
            row_number=1,
            sku=args.sku,
            product_name=product_name,
            attribute_name=args.attribute,
            metadata={"officialmediaurl": args.url, "sourceurl": args.url},
        )
        pipeline = ScraperPipeline(settings)
        try:
            result = pipeline.process_job(job, allow_upload=args.upload)
            report_paths = pipeline.write_reports([result])
        finally:
            pipeline.close()

        print()
        _status_colors = {
            "approved": (_GREEN, "✓ APPROVED"),
            "flagged": (_YELLOW, "⚠ FLAGGED"),
            "failed": (_RED, "✗ FAILED"),
        }
        color, label = _status_colors.get(result.status, ("", result.status.upper()))
        print(
            _c(f"  {label}", color)
            + f"  sku={_c(args.sku, _CYAN)}  attribute={_c(args.attribute, _YELLOW)}"
        )
        if result.final_path:
            print(f"  {_c('saved  :', _DIM)} {result.final_path}")
        if result.selected_candidate:
            print(f"  {_c('source :', _DIM)} {result.selected_candidate.source_name}")
            print(f"  {_c('url    :', _DIM)} {result.selected_candidate.image_url}")
        if result.issues:
            print()
            for issue in result.issues:
                issue_color = {
                    "error": _RED,
                    "warning": _YELLOW,
                    "info": _DIM,
                }.get(issue.severity, "")
                print(
                    f"  {_c(f'[{issue.severity}]', issue_color)} {issue.category}: {issue.message}"
                )
        print()
        print(_c("Reports:", _DIM))
        for label_key, path in report_paths.items():
            print(f"  {_c(label_key + ':', _DIM)} {path}")
        return 0 if result.status == "approved" else 1

    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
