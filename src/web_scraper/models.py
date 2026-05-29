from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

IssueSeverity = Literal["info", "warning", "error"]
JobStatus = Literal["approved", "flagged", "failed", "skipped"]


@dataclass
class ImageJob:
    row_number: int
    sku: str
    product_name: str
    attribute_name: str
    current_value: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageCandidate:
    source_name: str
    image_url: str
    page_url: Optional[str] = None
    label: Optional[str] = None
    score: float = 0.0
    local_path: Optional[Path] = None
    width: Optional[int] = None
    height: Optional[int] = None
    content_type: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewIssue:
    severity: IssueSeverity
    category: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UploadResult:
    success: bool
    sku: str
    attribute_name: str
    image_path: Path
    message: str
    remote_id: Optional[str] = None
    status_code: Optional[int] = None
    response_body: Optional[str] = None


@dataclass
class JobResult:
    job: ImageJob
    status: JobStatus
    final_path: Optional[Path] = None
    selected_candidate: Optional[ImageCandidate] = None
    upload_result: Optional[UploadResult] = None
    issues: list[ReviewIssue] = field(default_factory=list)

    def add_issue(
        self, severity: IssueSeverity, category: str, message: str, **metadata: Any
    ) -> None:
        self.issues.append(
            ReviewIssue(
                severity=severity,
                category=category,
                message=message,
                metadata=metadata,
            )
        )
