from __future__ import annotations

from pathlib import Path
import json

from report_collector.models import DailyDigest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    if path.is_file():
        path.unlink()
        return
    for child in path.iterdir():
        _remove_tree(child)
    path.rmdir()


def _cleanup_stale_requested_day(
    digest: DailyDigest,
    *,
    archive_root: Path,
    docs_root: Path,
) -> None:
    if digest.requested_date == digest.date:
        return

    requested_archive_dir = archive_root / digest.requested_date
    requested_archive_payload = _load_json(requested_archive_dir / "digest.json")
    if requested_archive_payload and requested_archive_payload.get("stats", {}).get(
        "total_reports",
        0,
    ) == 0:
        _remove_tree(requested_archive_dir)

    requested_day_path = docs_root / "data" / "days" / f"{digest.requested_date}.json"
    requested_day_payload = _load_json(requested_day_path)
    if requested_day_payload and requested_day_payload.get("stats", {}).get(
        "total_reports",
        0,
    ) == 0:
        requested_day_path.unlink()


def publish_digest(
    digest: DailyDigest,
    *,
    archive_root: Path,
    docs_root: Path,
    markdown_content: str,
) -> None:
    archive_day_dir = archive_root / digest.date
    digest_payload = digest.to_public_dict()

    _write_json(archive_day_dir / "digest.json", digest_payload)
    _write_text(archive_day_dir / "summary.md", markdown_content)

    docs_data_root = docs_root / "data"
    _write_json(docs_data_root / "days" / f"{digest.date}.json", digest_payload)
    _write_json(docs_data_root / "latest.json", digest_payload)
    _cleanup_stale_requested_day(
        digest,
        archive_root=archive_root,
        docs_root=docs_root,
    )
    _write_json(docs_data_root / "index.json", _build_index(archive_root))


def _build_index(archive_root: Path) -> dict:
    days: list[dict] = []
    if not archive_root.exists():
        return {"days": days}

    for day_dir in sorted(
        (path for path in archive_root.iterdir() if path.is_dir()),
        reverse=True,
    ):
        digest_path = day_dir / "digest.json"
        if not digest_path.exists():
            continue
        payload = json.loads(digest_path.read_text(encoding="utf-8"))
        days.append(
            {
                "date": payload["date"],
                "generated_at": payload["generated_at"],
                "total_reports": payload["stats"]["total_reports"],
                "keywords": payload.get("keywords", []),
                "top_titles": [
                    item["display_title"] for item in payload.get("must_read", [])[:3]
                ],
            }
        )

    return {"days": days}
