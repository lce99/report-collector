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

