from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import json
from typing import Any

from report_collector.models import DailyDigest
from report_collector.normalization import (
    normalize_opinion_value,
    normalize_subject_key,
    normalize_subject_name,
    parse_target_price_value,
)


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


def _report_sort_key(report: dict[str, Any]) -> tuple[str, float, int, str]:
    return (
        str(report.get("published_date") or ""),
        float(report.get("score") or 0.0),
        int(report.get("views") or 0),
        str(report.get("broker") or ""),
    )


def _normalize_subject_report(report: dict[str, Any]) -> dict[str, Any] | None:
    subject_name = normalize_subject_name(str(report.get("subject") or "") or None)
    if not subject_name:
        return None

    payload = dict(report)
    payload["subject"] = subject_name
    payload["subject_key"] = report.get("subject_key") or normalize_subject_key(subject_name)
    payload["target_price_value"] = report.get("target_price_value")
    if payload["target_price_value"] is None:
        payload["target_price_value"] = parse_target_price_value(
            str(report.get("target_price") or "") or None
        )
    payload["opinion_normalized"] = report.get("opinion_normalized") or normalize_opinion_value(
        str(report.get("opinion") or "") or None
    )
    payload["change_types"] = list(report.get("change_types") or [])
    payload["change_reasons"] = list(report.get("change_reasons") or [])
    payload["has_change_signal"] = bool(
        report.get("has_change_signal")
        or payload["change_types"]
        or payload["change_reasons"]
    )
    return payload


def _build_subject_change_summary(reports: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "changed_reports": sum(1 for report in reports if report.get("has_change_signal")),
        "target_price_up": sum(
            1 for report in reports if str(report.get("target_price_change") or "") == "up"
        ),
        "target_price_down": sum(
            1 for report in reports if str(report.get("target_price_change") or "") == "down"
        ),
        "opinion_changed": sum(1 for report in reports if bool(report.get("opinion_changed"))),
        "opinion_up": sum(
            1 for report in reports if str(report.get("opinion_change_direction") or "") == "up"
        ),
        "opinion_down": sum(
            1 for report in reports if str(report.get("opinion_change_direction") or "") == "down"
        ),
        "analyst_changed": sum(1 for report in reports if bool(report.get("analyst_changed"))),
        "coverage_initiated": sum(
            1 for report in reports if bool(report.get("coverage_initiated"))
        ),
    }


def _build_target_summary(reports: list[dict[str, Any]]) -> dict[str, int | None]:
    values = [
        int(report["target_price_value"])
        for report in reports
        if report.get("target_price_value") is not None
    ]
    if not values:
        return {"count": 0, "high": None, "low": None, "avg": None}

    return {
        "count": len(values),
        "high": max(values),
        "low": min(values),
        "avg": int(round(sum(values) / len(values))),
    }


def _build_subject_payloads(archive_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    if archive_root.exists():
        for day_dir in sorted(
            (path for path in archive_root.iterdir() if path.is_dir()),
            reverse=True,
        ):
            digest_path = day_dir / "digest.json"
            if not digest_path.exists():
                continue

            payload = json.loads(digest_path.read_text(encoding="utf-8"))
            for report in payload.get("reports", []):
                if not isinstance(report, dict):
                    continue
                normalized = _normalize_subject_report(report)
                if not normalized:
                    continue
                subject_key = str(normalized.get("subject_key") or "")
                if not subject_key:
                    continue
                grouped[subject_key].append(normalized)

    subjects: list[dict[str, Any]] = []
    subject_payloads: dict[str, dict[str, Any]] = {}

    for subject_key, reports in grouped.items():
        timeline = sorted(reports, key=_report_sort_key, reverse=True)
        latest_report = timeline[0]

        latest_by_broker: list[dict[str, Any]] = []
        seen_brokers: set[str] = set()
        for report in timeline:
            broker = str(report.get("broker") or "")
            if not broker or broker in seen_brokers:
                continue
            latest_by_broker.append(report)
            seen_brokers.add(broker)

        change_summary = _build_subject_change_summary(timeline)
        target_summary = _build_target_summary(latest_by_broker)
        opinion_counter = Counter(
            str(report.get("opinion_normalized") or "")
            for report in latest_by_broker
            if report.get("opinion_normalized")
        )
        broker_counter = Counter(str(report.get("broker") or "") for report in timeline)
        category_counter = Counter(
            str(report.get("category_label") or report.get("category") or "")
            for report in timeline
        )

        subject_payload = {
            "subject_key": subject_key,
            "subject_name": latest_report.get("subject"),
            "latest_report_date": latest_report.get("published_date"),
            "report_count": len(timeline),
            "active_broker_count": len(seen_brokers),
            "active_brokers": sorted(seen_brokers),
            "change_summary": change_summary,
            "target_summary": target_summary,
            "opinion_summary": [
                {"label": label, "count": count}
                for label, count in opinion_counter.most_common()
            ],
            "broker_summary": [
                {"name": name, "count": count}
                for name, count in broker_counter.most_common(12)
                if name
            ],
            "category_summary": [
                {"label": label, "count": count}
                for label, count in category_counter.most_common(8)
                if label
            ],
            "latest_by_broker": latest_by_broker[:20],
            "recent_changes": [report for report in timeline if report.get("has_change_signal")][:20],
            "timeline": timeline[:120],
        }
        subject_payloads[subject_key] = subject_payload

        subjects.append(
            {
                "subject_key": subject_key,
                "subject_name": latest_report.get("subject"),
                "latest_report_date": latest_report.get("published_date"),
                "report_count": len(timeline),
                "active_broker_count": len(seen_brokers),
                "changed_reports": change_summary["changed_reports"],
                "target_summary": target_summary,
                "top_brokers": [item["name"] for item in subject_payload["broker_summary"][:3]],
                "top_categories": [item["label"] for item in subject_payload["category_summary"][:3]],
                "latest_title": latest_report.get("display_title"),
            }
        )

    subjects.sort(
        key=lambda item: (
            str(item.get("latest_report_date") or ""),
            int(item.get("changed_reports") or 0),
            int(item.get("report_count") or 0),
            str(item.get("subject_name") or ""),
        ),
        reverse=True,
    )

    return {"subjects": subjects}, subject_payloads


def _sync_subject_payloads(
    docs_data_root: Path,
    archive_root: Path,
) -> None:
    subject_index, subject_payloads = _build_subject_payloads(archive_root)
    subjects_root = docs_data_root / "subjects"
    subjects_root.mkdir(parents=True, exist_ok=True)

    existing_keys = {
        path.stem
        for path in subjects_root.glob("*.json")
        if path.is_file() and path.name != "index.json"
    }
    for subject_key, payload in subject_payloads.items():
        _write_json(subjects_root / f"{subject_key}.json", payload)
    for stale_key in existing_keys - set(subject_payloads):
        (subjects_root / f"{stale_key}.json").unlink(missing_ok=True)

    _write_json(subjects_root / "index.json", subject_index)


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
    _sync_subject_payloads(docs_data_root, archive_root)


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
