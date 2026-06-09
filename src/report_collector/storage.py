from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
import json
from typing import Any

from report_collector.archive import (
    iter_digest_payloads,
    iter_payload_reports,
    load_json_dict as _load_json,
)
from report_collector.estimates import (
    estimate_reasons_for_types,
    extract_estimate_metrics,
    extract_estimate_signal_types,
)
from report_collector.market_data import normalize_ticker
from report_collector.models import DailyDigest
from report_collector.normalization import (
    normalize_opinion_value,
    normalize_subject_key,
    normalize_subject_name,
    parse_target_price_value,
)

PERFORMANCE_HORIZONS = (1, 7, 30)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
    payload["ticker"] = _resolve_report_ticker(payload)
    payload["target_price_value"] = report.get("target_price_value")
    if payload["target_price_value"] is None:
        payload["target_price_value"] = parse_target_price_value(
            str(report.get("target_price") or "") or None
        )
    payload["opinion_normalized"] = report.get("opinion_normalized") or normalize_opinion_value(
        str(report.get("opinion") or "") or None
    )
    estimate_text = _report_estimate_text(payload)
    estimate_metrics = list(report.get("estimate_metrics") or [])
    if not estimate_metrics:
        estimate_metrics = extract_estimate_metrics(estimate_text)
    estimate_signal_types = list(report.get("estimate_signal_types") or [])
    if not estimate_signal_types:
        estimate_signal_types = extract_estimate_signal_types(estimate_text)
    estimate_reasons = list(report.get("estimate_reasons") or [])
    if not estimate_reasons:
        estimate_reasons = estimate_reasons_for_types(estimate_signal_types)

    payload["estimate_metrics"] = estimate_metrics
    payload["estimate_signal_types"] = estimate_signal_types
    payload["estimate_reasons"] = estimate_reasons
    payload["change_types"] = _unique_strings(
        list(report.get("change_types") or []) + estimate_signal_types
    )
    payload["change_reasons"] = _unique_strings(
        list(report.get("change_reasons") or []) + estimate_reasons
    )
    payload["has_change_signal"] = bool(
        report.get("has_change_signal")
        or payload["change_types"]
        or payload["change_reasons"]
        or payload["estimate_signal_types"]
        or payload["estimate_reasons"]
    )
    return payload


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _report_estimate_text(report: dict[str, Any]) -> str:
    memo = report.get("investment_memo")
    memo_parts: list[str] = []
    if isinstance(memo, dict):
        for key in ("thesis", "catalysts", "risks", "numbers"):
            values = memo.get(key)
            if isinstance(values, list):
                memo_parts.extend(str(item or "") for item in values)
        memo_parts.append(str(memo.get("action") or ""))

    return " ".join(
        str(report.get(key) or "")
        for key in ("display_title", "title", "subject", "summary", "excerpt")
    ) + " " + " ".join(memo_parts)


ESTIMATE_SIGNAL_KEYS = (
    "earnings_estimate_up",
    "earnings_estimate_down",
    "margin_estimate_up",
    "margin_estimate_down",
)


def _build_subject_change_summary(reports: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "changed_reports": 0,
        "target_price_up": 0,
        "target_price_down": 0,
        "opinion_changed": 0,
        "opinion_up": 0,
        "opinion_down": 0,
        "analyst_changed": 0,
        "coverage_initiated": 0,
        "estimate_signal_reports": 0,
        **{key: 0 for key in ESTIMATE_SIGNAL_KEYS},
    }

    for report in reports:
        if report.get("has_change_signal"):
            summary["changed_reports"] += 1

        target_change = str(report.get("target_price_change") or "")
        if target_change in ("up", "down"):
            summary[f"target_price_{target_change}"] += 1

        if report.get("opinion_changed"):
            summary["opinion_changed"] += 1
        opinion_direction = str(report.get("opinion_change_direction") or "")
        if opinion_direction in ("up", "down"):
            summary[f"opinion_{opinion_direction}"] += 1

        if report.get("analyst_changed"):
            summary["analyst_changed"] += 1
        if report.get("coverage_initiated"):
            summary["coverage_initiated"] += 1

        signal_types = set(report.get("estimate_signal_types") or [])
        if signal_types:
            summary["estimate_signal_reports"] += 1
        for key in ESTIMATE_SIGNAL_KEYS:
            if key in signal_types:
                summary[key] += 1

    return summary


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


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return None


def _chart_report_point(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": report.get("published_date"),
        "broker": report.get("broker"),
        "title": report.get("display_title") or report.get("title"),
        "ticker": report.get("ticker"),
        "detail_url": report.get("detail_url"),
        "pdf_url": report.get("pdf_url"),
        "primary_url": report.get("primary_url") or report.get("pdf_url") or report.get("detail_url"),
        "target_price": report.get("target_price"),
        "target_price_value": report.get("target_price_value"),
        "opinion": report.get("opinion"),
        "opinion_normalized": report.get("opinion_normalized"),
        "score": report.get("score"),
        "has_change_signal": bool(report.get("has_change_signal")),
        "estimate_signal_types": list(report.get("estimate_signal_types") or []),
        "estimate_reasons": list(report.get("estimate_reasons") or []),
    }


def _chart_estimate_point(report: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any]:
    point = _chart_report_point(report)
    point.update(
        {
            "metric": metric.get("metric"),
            "metric_group": metric.get("metric_group"),
            "label": metric.get("label"),
            "period": metric.get("period"),
            "value": metric.get("value"),
            "unit": metric.get("unit"),
            "value_krw_100m": metric.get("value_krw_100m"),
            "value_pct": metric.get("value_pct"),
            "value_won": metric.get("value_won"),
            "change_pctp": metric.get("change_pctp"),
            "source_excerpt": metric.get("source_excerpt"),
        }
    )
    return point


def _build_subject_chart_payload(
    timeline: list[dict[str, Any]],
    latest_by_broker: list[dict[str, Any]],
    latest_report_date: object,
) -> dict[str, Any]:
    target_price_history = [
        _chart_report_point(report)
        for report in timeline
        if report.get("target_price_value") is not None
    ]
    target_price_history.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("broker") or "")))

    estimate_metric_history = [
        _chart_estimate_point(report, metric)
        for report in timeline
        for metric in (report.get("estimate_metrics") or [])
        if isinstance(metric, dict)
    ]
    estimate_metric_history.sort(
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("metric") or ""),
            str(item.get("broker") or ""),
        )
    )

    opinion_counter = Counter(
        str(report.get("opinion_normalized") or report.get("opinion") or "")
        for report in latest_by_broker
        if report.get("opinion_normalized") or report.get("opinion")
    )
    opinion_distribution = [
        {"label": label, "count": count}
        for label, count in opinion_counter.most_common()
        if label
    ]

    latest_date = _parse_date(latest_report_date)
    if latest_date:
        window_start = latest_date - timedelta(days=14)
        recent_reports = [
            report
            for report in timeline
            if (report_date := _parse_date(report.get("published_date")))
            and report_date >= window_start
        ]
    else:
        recent_reports = timeline[:40]

    broker_timeline = [_chart_report_point(report) for report in sorted(
        recent_reports,
        key=_report_sort_key,
    )]

    return {
        "target_price_history": target_price_history[-80:],
        "estimate_metric_history": estimate_metric_history[-120:],
        "opinion_distribution": opinion_distribution,
        "broker_timeline": broker_timeline[-80:],
        "window_days": 14,
    }


def _build_subject_payloads(archive_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for _, payload in iter_digest_payloads(archive_root):
        for report in iter_payload_reports(payload):
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
        chart_payload = _build_subject_chart_payload(
            timeline,
            latest_by_broker,
            latest_report.get("published_date"),
        )
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
            "charts": chart_payload,
            "target_price_history": chart_payload["target_price_history"],
            "estimate_metric_history": chart_payload["estimate_metric_history"],
            "opinion_distribution": chart_payload["opinion_distribution"],
            "broker_timeline": chart_payload["broker_timeline"],
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


def _selection_key(digest_date: str, report: dict[str, Any]) -> str:
    return f"{digest_date}:{report.get('report_id') or report.get('detail_url') or report.get('display_title')}"


def _due_date(digest_date: str, days: int) -> str:
    parsed = _parse_date(digest_date)
    if not parsed:
        return ""
    return (parsed + timedelta(days=days)).isoformat()


def _build_selection_record(
    digest_payload: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    digest_date = str(digest_payload.get("date") or "")
    ticker = _resolve_report_ticker(report)
    return {
        "key": _selection_key(digest_date, report),
        "selected_date": digest_date,
        "report_id": report.get("report_id"),
        "display_title": report.get("display_title") or report.get("title"),
        "subject": report.get("subject"),
        "subject_key": report.get("subject_key"),
        "ticker": ticker,
        "broker": report.get("broker"),
        "category": report.get("category"),
        "category_label": report.get("category_label"),
        "score": report.get("score"),
        "score_reasons": list(report.get("score_reasons") or []),
        "detail_url": report.get("detail_url"),
        "pdf_url": report.get("pdf_url"),
        "primary_url": report.get("primary_url") or report.get("pdf_url") or report.get("detail_url"),
        "target_price": report.get("target_price"),
        "target_price_value": report.get("target_price_value"),
        "opinion": report.get("opinion"),
        "horizons": {
            f"{days}d": {
                "days": days,
                "due_date": _due_date(digest_date, days),
                "status": "pending",
                "price_return_pct": None,
                "volume_change_pct": None,
                "news_count": None,
            }
            for days in PERFORMANCE_HORIZONS
        },
    }


def _resolve_report_ticker(report: dict[str, Any]) -> str | None:
    for key in ("ticker", "stock_code", "code"):
        ticker = normalize_ticker(report.get(key))
        if ticker:
            return ticker
    return normalize_ticker(
        " ".join(
            str(report.get(key) or "")
            for key in ("display_title", "title", "subject", "subject_key")
        )
    )


def _build_ticker_lookup(subject_ticker_map: dict[str, str] | None) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for key, value in (subject_ticker_map or {}).items():
        ticker = normalize_ticker(value)
        if not ticker:
            continue
        raw_key = str(key or "").strip()
        normalized_key = normalize_subject_key(raw_key)
        if raw_key:
            lookup[raw_key] = ticker
        if normalized_key:
            lookup[normalized_key] = ticker
    return lookup


def _resolve_record_ticker(
    record: dict[str, Any],
    ticker_lookup: dict[str, str],
) -> str | None:
    ticker = normalize_ticker(record.get("ticker"))
    if ticker:
        return ticker
    for key in ("subject_key", "subject", "display_title"):
        value = str(record.get(key) or "").strip()
        if not value:
            continue
        mapped = ticker_lookup.get(value)
        if mapped:
            return mapped
        normalized = normalize_subject_key(value)
        if normalized and ticker_lookup.get(normalized):
            return ticker_lookup[normalized]
    return _resolve_report_ticker(record)


def _report_matches_selection(report: dict[str, Any], record: dict[str, Any]) -> bool:
    subject_key = str(record.get("subject_key") or "")
    if subject_key and str(report.get("subject_key") or "") == subject_key:
        return True

    selected_title = str(record.get("display_title") or "")
    report_title = str(report.get("display_title") or report.get("title") or "")
    if selected_title and report_title and selected_title == report_title:
        return True

    return False


def _load_archive_reports_by_day(archive_root: Path) -> list[tuple[date, list[dict[str, Any]]]]:
    days: list[tuple[date, list[dict[str, Any]]]] = []
    for day_name, payload in iter_digest_payloads(archive_root, newest_first=False):
        day = _parse_date(day_name)
        if not day:
            continue
        days.append((day, list(iter_payload_reports(payload))))
    return days


def _follow_up_reports_for_record(
    archive_days: list[tuple[date, list[dict[str, Any]]]],
    record: dict[str, Any],
    due_date: date,
) -> list[dict[str, Any]]:
    selected_date = _parse_date(record.get("selected_date"))
    if not selected_date:
        return []

    matches = [
        report
        for day, reports in archive_days
        if selected_date < day <= due_date
        for report in reports
        if _report_matches_selection(report, record)
    ]

    matches.sort(
        key=lambda item: (
            str(item.get("published_date") or ""),
            float(item.get("score") or 0.0),
        ),
        reverse=True,
    )
    return matches


def _target_price_delta_pct(
    selected_value: object,
    latest_value: object,
) -> float | None:
    try:
        selected = float(selected_value)
        latest = float(latest_value)
    except (TypeError, ValueError):
        return None
    if selected <= 0:
        return None
    return round(((latest - selected) / selected) * 100, 2)


def _complete_due_horizons(
    records: list[dict[str, Any]],
    *,
    archive_root: Path,
    as_of_date: date | None,
    market_data_provider: Any | None = None,
    subject_ticker_map: dict[str, str] | None = None,
) -> None:
    if not as_of_date:
        return

    ticker_lookup = _build_ticker_lookup(subject_ticker_map)
    archive_days: list[tuple[date, list[dict[str, Any]]]] | None = None
    for record in records:
        record_ticker = _resolve_record_ticker(record, ticker_lookup)
        if record_ticker and not record.get("ticker"):
            record["ticker"] = record_ticker
        horizons = record.get("horizons")
        if not isinstance(horizons, dict):
            continue
        for horizon in horizons.values():
            if not isinstance(horizon, dict):
                continue
            due_date = _parse_date(horizon.get("due_date"))
            if not due_date or due_date > as_of_date:
                continue
            if str(horizon.get("status") or "") == "completed":
                continue

            if archive_days is None:
                archive_days = _load_archive_reports_by_day(archive_root)
            follow_ups = _follow_up_reports_for_record(archive_days, record, due_date)
            latest = follow_ups[0] if follow_ups else {}
            horizon["status"] = "completed"
            horizon["completed_at"] = as_of_date.isoformat()
            horizon["follow_up_report_count"] = len(follow_ups)
            horizon["follow_up_change_count"] = sum(
                1 for report in follow_ups if bool(report.get("has_change_signal"))
            )
            horizon["latest_report_date"] = latest.get("published_date")
            horizon["latest_report_title"] = latest.get("display_title") or latest.get("title")
            horizon["latest_broker"] = latest.get("broker")
            horizon["latest_score"] = latest.get("score")
            horizon["latest_target_price"] = latest.get("target_price")
            horizon["latest_target_price_value"] = latest.get("target_price_value")
            horizon["latest_opinion"] = latest.get("opinion")
            horizon["target_price_delta_pct"] = _target_price_delta_pct(
                record.get("target_price_value"),
                latest.get("target_price_value"),
            )
            horizon["outcome_source"] = "archived_follow_up_reports"
            _attach_market_return(
                horizon,
                record,
                record_ticker,
                market_data_provider,
            )


def _attach_market_return(
    horizon: dict[str, Any],
    record: dict[str, Any],
    ticker: str | None,
    market_data_provider: Any | None,
) -> None:
    if market_data_provider is None:
        return

    selected_date = _parse_date(record.get("selected_date"))
    due_date = _parse_date(horizon.get("due_date"))
    if not selected_date or not due_date:
        return

    if not ticker:
        horizon["price_return_status"] = "missing_ticker"
        return

    try:
        result = market_data_provider.calculate_return(ticker, selected_date, due_date)
    except Exception as exc:
        horizon["ticker"] = ticker
        horizon["price_source"] = getattr(market_data_provider, "source_name", "market_data")
        horizon["price_return_status"] = f"failed:{exc.__class__.__name__}"
        return

    horizon["ticker"] = ticker
    if not result:
        horizon["price_source"] = getattr(market_data_provider, "source_name", "market_data")
        horizon["price_return_status"] = "price_unavailable"
        return

    horizon.update(result)
    horizon["price_return_status"] = "ok"


def _build_performance_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    pending_by_horizon: dict[str, int] = Counter()
    completed_by_horizon: dict[str, int] = Counter()
    priced_by_horizon: dict[str, int] = Counter()
    price_source_counts: dict[str, int] = Counter()
    returns_by_horizon: dict[str, list[float]] = defaultdict(list)
    for record in records:
        horizons = record.get("horizons")
        if not isinstance(horizons, dict):
            continue
        for horizon, payload in horizons.items():
            if not isinstance(payload, dict):
                continue
            status = str(payload.get("status") or "pending")
            if status == "completed":
                completed_by_horizon[horizon] += 1
                price_return = payload.get("price_return_pct")
                if price_return is not None:
                    priced_by_horizon[horizon] += 1
                    try:
                        returns_by_horizon[horizon].append(float(price_return))
                    except (TypeError, ValueError):
                        pass
                price_source = str(payload.get("price_source") or "")
                if price_source:
                    price_source_counts[price_source] += 1
            else:
                pending_by_horizon[horizon] += 1

    average_return_by_horizon = {
        horizon: round(sum(values) / len(values), 2)
        for horizon, values in returns_by_horizon.items()
        if values
    }

    return {
        "tracked_selections": len(records),
        "pending_by_horizon": dict(pending_by_horizon),
        "completed_by_horizon": dict(completed_by_horizon),
        "priced_by_horizon": dict(priced_by_horizon),
        "average_price_return_by_horizon": average_return_by_horizon,
        "price_source_counts": dict(price_source_counts),
        "horizons": [f"{days}d" for days in PERFORMANCE_HORIZONS],
    }


def _sync_selection_performance(
    docs_data_root: Path,
    digest_payload: dict[str, Any],
    *,
    archive_root: Path,
    market_data_provider: Any | None = None,
    subject_ticker_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    performance_root = docs_data_root / "performance"
    ledger_path = performance_root / "selection_outcomes.json"
    existing_payload = _load_json(ledger_path) or {}
    existing_records = existing_payload.get("selections", [])
    if not isinstance(existing_records, list):
        existing_records = []

    records_by_key = {
        str(record.get("key")): record
        for record in existing_records
        if isinstance(record, dict) and record.get("key")
    }

    for report in digest_payload.get("must_read", []):
        if not isinstance(report, dict):
            continue
        key = _selection_key(str(digest_payload.get("date") or ""), report)
        if key not in records_by_key:
            records_by_key[key] = _build_selection_record(digest_payload, report)

    _complete_due_horizons(
        list(records_by_key.values()),
        archive_root=archive_root,
        as_of_date=_parse_date(digest_payload.get("date")),
        market_data_provider=market_data_provider,
        subject_ticker_map=subject_ticker_map,
    )

    records = sorted(
        records_by_key.values(),
        key=lambda item: (
            str(item.get("selected_date") or ""),
            float(item.get("score") or 0.0),
            str(item.get("display_title") or ""),
        ),
        reverse=True,
    )
    summary = _build_performance_summary(records)
    payload = {
        "updated_at": digest_payload.get("generated_at"),
        "summary": summary,
        "selections": records[:500],
    }
    _write_json(ledger_path, payload)
    _write_json(performance_root / "latest.json", payload)
    return payload


def publish_digest(
    digest: DailyDigest,
    *,
    archive_root: Path,
    docs_root: Path,
    markdown_content: str,
    market_data_provider: Any | None = None,
    subject_ticker_map: dict[str, str] | None = None,
) -> None:
    archive_day_dir = archive_root / digest.date
    digest_payload = digest.to_public_dict()
    docs_data_root = docs_root / "data"
    performance_payload = _sync_selection_performance(
        docs_data_root,
        digest_payload,
        archive_root=archive_root,
        market_data_provider=market_data_provider,
        subject_ticker_map=subject_ticker_map,
    )
    if isinstance(digest_payload.get("stats"), dict):
        digest_payload["stats"]["selection_performance"] = performance_payload.get("summary", {})

    _write_json(archive_day_dir / "digest.json", digest_payload)
    _write_text(archive_day_dir / "summary.md", markdown_content)

    _write_json(docs_data_root / "days" / f"{digest.date}.json", digest_payload)
    _write_json(docs_data_root / "latest.json", digest_payload)
    _cleanup_stale_requested_day(
        digest,
        archive_root=archive_root,
        docs_root=docs_root,
    )
    _write_json(docs_data_root / "index.json", _build_index(archive_root))
    _sync_subject_payloads(docs_data_root, archive_root)


def _build_index(archive_root: Path) -> dict[str, list[dict[str, Any]]]:
    days: list[dict[str, Any]] = []

    for day_name, payload in iter_digest_payloads(archive_root):
        stats = payload.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}
        must_read = payload.get("must_read", [])
        if not isinstance(must_read, list):
            must_read = []
        days.append(
            {
                "date": str(payload.get("date") or day_name),
                "generated_at": str(payload.get("generated_at") or ""),
                "total_reports": int(stats.get("total_reports") or 0),
                "keywords": payload.get("keywords", []),
                "top_titles": [
                    str(item.get("display_title") or "")
                    for item in must_read[:3]
                    if isinstance(item, dict)
                ],
            }
        )

    return {"days": days}
