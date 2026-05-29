from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
import imagehash

from ._logging import ProgressLogger
from .config import Settings
from .images import (
    ImageDownloadError,
    download_image,
    evaluate_quality,
    is_duplicate,
    persist_image,
)
from .magento import MagentoClient
from .models import ImageCandidate, ImageJob, JobResult, ReviewIssue, UploadResult
from .sheets import load_image_jobs
from .sources.browser_fallback import BrowserFallbackSource
from .sources.gsmarena import GsmArenaSource
from .sources.official_media import OfficialMediaSource
from .utils import ensure_dir
from .watermark import inspect_watermark

LOGGER = logging.getLogger(__name__)
_progress = ProgressLogger(__name__)


class ScraperPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_dir = ensure_dir(self.settings.project.run_reports_dir / self.run_id)
        self.temp_dir = ensure_dir(self.settings.project.temp_dir / self.run_id)
        self.images_dir = ensure_dir(self.settings.project.output_dir / "images")
        self.review_dir = ensure_dir(self.run_dir / "review")
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=self.settings.network.request_timeout_seconds,
            headers={
                "User-Agent": self.settings.network.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        self.magento = MagentoClient(self.settings.magento)
        self.sources = self._build_sources()

    def close(self) -> None:
        self.client.close()

    def load_jobs(self, sheet_path: Path) -> list[ImageJob]:
        return load_image_jobs(sheet_path, self.settings)

    def run(
        self,
        sheet_path: Path,
        *,
        limit: Optional[int] = None,
        allow_upload: Optional[bool] = None,
    ) -> Tuple[list[JobResult], Dict[str, Path]]:
        jobs = self.load_jobs(sheet_path)
        total = len(jobs)
        if limit is not None:
            jobs = jobs[:limit]
        _progress.start(
            "Starting pipeline",
            jobs=len(jobs),
            total_in_sheet=total,
            upload=allow_upload,
            run_id=self.run_id,
        )

        results = []
        for idx, job in enumerate(jobs, 1):
            _progress.section(
                f"Job {idx}/{len(jobs)}  sku={job.sku}  attr={job.attribute_name}"
            )
            results.append(self.process_job(job, allow_upload=allow_upload))

        report_paths = self.write_reports(results)
        approved = sum(r.status == "approved" for r in results)
        flagged = sum(r.status == "flagged" for r in results)
        failed = sum(r.status == "failed" for r in results)
        _progress.success(
            "Pipeline complete",
            approved=approved,
            flagged=flagged,
            failed=failed,
            run_dir=str(self.run_dir),
        )
        return results, report_paths

    def process_job(
        self, job: ImageJob, *, allow_upload: Optional[bool] = None
    ) -> JobResult:
        result = JobResult(job=job, status="failed")
        seen_hashes: list[imagehash.ImageHash] = []

        for source in self.sources:
            _progress.step("Trying source", source=source.name, sku=job.sku)
            try:
                candidates = source.fetch_candidates(
                    job, client=self.client, settings=self.settings
                )
            except Exception as exc:  # pragma: no cover
                _progress.fail(
                    "Source raised an exception",
                    source=source.name,
                    sku=job.sku,
                    error=type(exc).__name__,
                )
                LOGGER.debug(
                    "Full traceback for source %s:", source.name, exc_info=True
                )
                result.add_issue(
                    "warning",
                    "source_error",
                    f"Source {source.name} failed: {exc}",
                    source=source.name,
                )
                continue

            if not candidates:
                _progress.step(
                    "No candidates returned", source=source.name, sku=job.sku
                )
                result.add_issue(
                    "info",
                    "no_candidates",
                    f"Source {source.name} returned no candidates",
                    source=source.name,
                )
                continue

            _progress.step(
                "Evaluating candidates",
                source=source.name,
                count=len(candidates),
                sku=job.sku,
            )
            for candidate in candidates[: self.settings.sources.max_candidates_per_job]:
                evaluated_candidate = self._evaluate_candidate(
                    candidate,
                    job=job,
                    result=result,
                    seen_hashes=seen_hashes,
                )
                if evaluated_candidate is None:
                    continue

                final_path = persist_image(
                    evaluated_candidate,
                    output_dir=self.images_dir,
                    sku=job.sku,
                    attribute_name=job.attribute_name,
                )
                result.final_path = final_path
                result.selected_candidate = evaluated_candidate
                result.status = "approved"
                _progress.success(
                    "Image approved",
                    sku=job.sku,
                    source=source.name,
                    path=str(final_path),
                    size=f"{evaluated_candidate.width}×{evaluated_candidate.height}",
                )

                should_upload = (
                    allow_upload
                    if allow_upload is not None
                    else self.settings.magento.enabled
                )
                if should_upload:
                    _progress.step(
                        "Uploading to Magento",
                        sku=job.sku,
                        attribute=job.attribute_name,
                    )
                    upload_result = self.magento.upload_image(
                        sku=job.sku,
                        attribute_name=job.attribute_name,
                        image_path=final_path,
                    )
                    result.upload_result = upload_result
                    if upload_result.success:
                        _progress.success(
                            "Magento upload OK",
                            sku=job.sku,
                            remote_id=upload_result.remote_id,
                        )
                    else:
                        _progress.warn(
                            "Magento upload failed",
                            sku=job.sku,
                            message=upload_result.message,
                            status_code=upload_result.status_code,
                        )
                        result.add_issue(
                            "warning",
                            "upload_failed",
                            upload_result.message,
                            status_code=upload_result.status_code,
                        )
                return result

        if result.issues:
            result.status = "flagged"
            _progress.warn(
                "Job flagged — no approved image found",
                sku=job.sku,
                issues=len(result.issues),
            )
        else:
            _progress.fail("Job failed — no candidates from any source", sku=job.sku)
        return result

    def write_reports(self, results: list[JobResult]) -> dict[str, Path]:
        results_path = self.run_dir / "results.json"
        review_path = self.run_dir / "review_queue.json"
        csv_path = self.run_dir / "manifest.csv"
        summary_path = self.run_dir / "summary.json"

        serialized = [serialize_result(result) for result in results]
        results_path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")

        flagged = [entry for entry in serialized if entry["status"] != "approved"]
        review_path.write_text(json.dumps(flagged, indent=2), encoding="utf-8")

        self._write_manifest_csv(csv_path, results)
        summary = {
            "run_id": self.run_id,
            "total_jobs": len(results),
            "approved": sum(result.status == "approved" for result in results),
            "flagged": sum(result.status == "flagged" for result in results),
            "failed": sum(result.status == "failed" for result in results),
            "results_path": str(results_path),
            "review_queue_path": str(review_path),
            "manifest_path": str(csv_path),
        }
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return {
            "results": results_path,
            "review_queue": review_path,
            "manifest": csv_path,
            "summary": summary_path,
        }

    def _write_manifest_csv(self, path: Path, results: list[JobResult]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "sku",
                    "product_name",
                    "attribute_name",
                    "status",
                    "final_path",
                    "source_name",
                    "image_url",
                    "upload_success",
                    "upload_message",
                    "issue_count",
                ],
            )
            writer.writeheader()
            for result in results:
                writer.writerow(
                    {
                        "sku": result.job.sku,
                        "product_name": result.job.product_name,
                        "attribute_name": result.job.attribute_name,
                        "status": result.status,
                        "final_path": (
                            str(result.final_path) if result.final_path else ""
                        ),
                        "source_name": (
                            result.selected_candidate.source_name
                            if result.selected_candidate
                            else ""
                        ),
                        "image_url": (
                            result.selected_candidate.image_url
                            if result.selected_candidate
                            else ""
                        ),
                        "upload_success": (
                            result.upload_result.success if result.upload_result else ""
                        ),
                        "upload_message": (
                            result.upload_result.message if result.upload_result else ""
                        ),
                        "issue_count": len(result.issues),
                    }
                )

    def _evaluate_candidate(
        self,
        candidate: ImageCandidate,
        *,
        job: ImageJob,
        result: JobResult,
        seen_hashes: list[imagehash.ImageHash],
    ) -> Optional[ImageCandidate]:
        try:
            downloaded = download_image(
                candidate,
                client=self.client,
                temp_dir=self.temp_dir,
                settings=self.settings,
            )
        except (httpx.HTTPError, ImageDownloadError) as exc:
            result.add_issue(
                "warning",
                "download_failed",
                f"Failed to download {candidate.image_url}: {exc}",
                source=candidate.source_name,
                image_url=candidate.image_url,
            )
            return None

        issues = evaluate_quality(downloaded, self.settings)
        if downloaded.local_path:
            issues.extend(inspect_watermark(downloaded.local_path, self.settings))
            if is_duplicate(
                downloaded.local_path,
                seen_hashes,
                threshold=self.settings.quality.perceptual_hash_distance,
            ):
                issues.append(
                    ReviewIssue(
                        severity="error",
                        category="duplicate",
                        message="Image is visually similar to an already-seen candidate",
                    )
                )

        result.issues.extend(issues)
        if _has_blocking_issue(issues):
            return None
        return downloaded

    def _build_sources(self) -> list[object]:
        registry = {
            "gsmarena": GsmArenaSource(),
            "official_media": OfficialMediaSource(),
            "browser_fallback": BrowserFallbackSource(),
        }
        sources: list[object] = []
        for source_name in self.settings.sources.priority:
            if source_name in registry:
                sources.append(registry[source_name])
        return sources


def _has_blocking_issue(issues: list[ReviewIssue]) -> bool:
    return any(
        issue.severity == "error" or issue.category.startswith("watermark")
        for issue in issues
    )


def serialize_result(result: JobResult) -> dict[str, Any]:
    return {
        "job": {
            "row_number": result.job.row_number,
            "sku": result.job.sku,
            "product_name": result.job.product_name,
            "attribute_name": result.job.attribute_name,
            "current_value": result.job.current_value,
            "metadata": result.job.metadata,
        },
        "status": result.status,
        "final_path": str(result.final_path) if result.final_path else None,
        "selected_candidate": serialize_candidate(result.selected_candidate),
        "upload_result": serialize_upload_result(result.upload_result),
        "issues": [serialize_issue(issue) for issue in result.issues],
    }


def serialize_candidate(
    candidate: Optional[ImageCandidate],
) -> Optional[dict[str, Any]]:
    if candidate is None:
        return None
    return {
        "source_name": candidate.source_name,
        "image_url": candidate.image_url,
        "page_url": candidate.page_url,
        "label": candidate.label,
        "score": candidate.score,
        "local_path": str(candidate.local_path) if candidate.local_path else None,
        "width": candidate.width,
        "height": candidate.height,
        "content_type": candidate.content_type,
        "metadata": candidate.metadata,
    }


def serialize_issue(issue: ReviewIssue) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "category": issue.category,
        "message": issue.message,
        "metadata": issue.metadata,
    }


def serialize_upload_result(result: Optional[UploadResult]) -> Optional[dict[str, Any]]:
    if result is None:
        return None
    return {
        "success": result.success,
        "sku": result.sku,
        "attribute_name": result.attribute_name,
        "image_path": str(result.image_path),
        "message": result.message,
        "remote_id": result.remote_id,
        "status_code": result.status_code,
        "response_body": result.response_body,
    }
