"""Colored, human-friendly log formatter for the web-scraper CLI."""

from __future__ import annotations

import logging
import os
import sys

# ── ANSI color codes ──────────────────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_COLORS = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}

# Level labels padded to the same width for alignment
_LABELS = {
    logging.DEBUG: "DEBUG   ",
    logging.INFO: "INFO    ",
    logging.WARNING: "WARNING ",
    logging.ERROR: "ERROR   ",
    logging.CRITICAL: "CRITICAL",
}


def _supports_color(stream: object) -> bool:
    """Return True when the stream is a TTY and the OS is not Windows CI."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class ColorFormatter(logging.Formatter):
    """
    Formats log records with:
      - Colored level badges
      - Dimmed timestamps (HH:MM:SS)
      - Shortened logger names (last two dotted segments)
      - Inline exception summaries for non-DEBUG levels
    """

    _datefmt = "%H:%M:%S"

    def __init__(self, use_color: bool = True) -> None:
        super().__init__()
        self._use_color = use_color

    # ------------------------------------------------------------------
    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelno, "")
        label = _LABELS.get(record.levelno, record.levelname.ljust(8))
        ts = self.formatTime(record, self._datefmt)
        module = _short_name(record.name)
        msg = record.getMessage()

        if self._use_color:
            timestamp_str = f"{_DIM}{ts}{_RESET}"
            level_str = f"{color}{_BOLD}{label}{_RESET}"
            module_str = f"{_DIM}{module}{_RESET}"
            message_str = (
                f"{color}{msg}{_RESET}" if record.levelno >= logging.WARNING else msg
            )
        else:
            timestamp_str = ts
            level_str = label
            module_str = module
            message_str = msg

        line = f"{timestamp_str}  {level_str}  {module_str}  {message_str}"

        # Append exception info when present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            if self._use_color:
                exc_text = f"{_DIM}{exc_text}{_RESET}"
            line = f"{line}\n{exc_text}"

        return line


class ProgressLogger:
    """
    Thin wrapper that emits structured, human-readable progress messages to a
    ``logging.Logger`` so they flow through the normal handler/formatter stack.

    Usage::

        log = ProgressLogger(__name__)
        log.start("Downloading image", url=url)
        log.success("Image saved", path=str(path))
        log.warn("Low resolution", width=w, height=h, min=min_res)
        log.fail("Source returned no candidates", source=source_name)
        log.step("Checking watermark …")
    """

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    # ------------------------------------------------------------------
    def start(self, msg: str, **kwargs: object) -> None:
        self._log.info("→ %s%s", msg, _fmt_kwargs(kwargs))

    def step(self, msg: str, **kwargs: object) -> None:
        self._log.debug("  %s%s", msg, _fmt_kwargs(kwargs))

    def success(self, msg: str, **kwargs: object) -> None:
        self._log.info("✓ %s%s", msg, _fmt_kwargs(kwargs))

    def warn(self, msg: str, **kwargs: object) -> None:
        self._log.warning("⚠ %s%s", msg, _fmt_kwargs(kwargs))

    def fail(self, msg: str, **kwargs: object) -> None:
        self._log.error("✗ %s%s", msg, _fmt_kwargs(kwargs))

    def section(self, msg: str) -> None:
        """Emit a visually distinct section header at INFO level."""
        self._log.info("━━━  %s  ━━━", msg)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _short_name(name: str) -> str:
    """Return the last two dotted components of a logger name, padded."""
    parts = name.rsplit(".", 2)
    short = ".".join(parts[-2:]) if len(parts) >= 2 else name
    return short[:28].ljust(28)


def _fmt_kwargs(kwargs: dict) -> str:
    if not kwargs:
        return ""
    pairs = "  ".join(f"{k}={v}" for k, v in kwargs.items())
    return f"  [{pairs}]"


# ── Public setup function ─────────────────────────────────────────────────────


def setup_logging(level: str = "INFO") -> None:
    """
    Configure root logger with a ``ColorFormatter`` on stderr.

    Call once from ``cli.main()``.
    """
    numeric = getattr(logging, level.upper(), logging.INFO)
    use_color = _supports_color(sys.stderr)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(ColorFormatter(use_color=use_color))
    handler.setLevel(numeric)

    root = logging.getLogger()
    root.setLevel(numeric)

    # Remove any existing handlers so basicConfig remnants don't double-print
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers unless the user asked for DEBUG
    if numeric > logging.DEBUG:
        for noisy in ("httpx", "httpcore", "playwright", "PIL", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
