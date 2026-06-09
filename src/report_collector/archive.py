from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator
import json


def load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def iter_digest_payloads(
    archive_root: Path,
    *,
    newest_first: bool = True,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (day_dir_name, digest payload) for each archived day."""
    if not archive_root or not archive_root.exists():
        return

    for day_dir in sorted(
        (path for path in archive_root.iterdir() if path.is_dir()),
        reverse=newest_first,
    ):
        payload = load_json_dict(day_dir / "digest.json")
        if payload:
            yield day_dir.name, payload


def iter_payload_reports(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    reports = payload.get("reports")
    if not isinstance(reports, list):
        return
    for report in reports:
        if isinstance(report, dict):
            yield report
