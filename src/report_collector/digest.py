from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import html
import math
import re

from report_collector.archive import iter_digest_payloads, iter_payload_reports
from report_collector.config import Settings
from report_collector.estimates import annotate_report_estimates
from report_collector.models import DailyDigest, Report
from report_collector.normalization import (
    annotate_report_normalized_fields,
    normalize_opinion_value,
    normalize_space,
    normalize_subject_key,
    opinion_change_direction,
    parse_target_price_value,
    trim_text,
)
from report_collector.sources.common import normalize_report_key


CATEGORY_WEIGHTS = {
    "company": 3.2,
    "industry": 2.7,
    "invest": 2.5,
    "economy": 2.3,
    "market": 1.8,
    "debenture": 1.7,
}

SOURCE_WEIGHTS = {
    "mirae_asset_official": 0.45,
    "shinhan_investment_official": 0.45,
    "korea_investment_official": 0.4,
    "naver_research": 0.1,
}

TITLE_KEYWORD_BOOSTS = {
    "preview": 1.4,
    "프리뷰": 1.4,
    "전망": 1.1,
    "top picks": 1.6,
    "탑픽": 1.5,
    "실적": 0.9,
    "cpi": 0.7,
    "금리": 0.6,
    "방산": 0.6,
    "반도체": 0.5,
    "투자전략": 0.5,
    "etf": 0.4,
    "weekly": 0.4,
}

TITLE_KEYWORD_PENALTIES = {
    "daily": -0.45,
    "morning": -0.4,
    "snapshot": -0.3,
    "장마감": -0.25,
    "마감": -0.2,
}

MUST_READ_QUOTAS = (
    ("company", 4),
    ("industry", 2),
    ("invest", 2),
    ("economy", 2),
    ("market", 1),
    ("debenture", 1),
)

MUST_READ_BROKER_SOFT_LIMIT = 3
MUST_READ_BROKER_HARD_LIMIT = 5
MUST_READ_IDENTITY_HARD_LIMIT = 2
MUST_READ_SIGNAL_LIMIT = 3

RANKING_GROUPS = (
    ("company", "종목 랭킹", {"company"}),
    ("industry", "산업 랭킹", {"industry"}),
    ("macro", "매크로 랭킹", {"economy", "market", "debenture"}),
    ("strategy", "전략 랭킹", {"invest"}),
)

COLLECTOR_HISTORY_LIMIT = 5
MIN_SOURCE_BASELINE_COUNT = 3.0
MIN_TOTAL_BASELINE_COUNT = 20.0
SOURCE_DROP_RATIO_THRESHOLD = 0.45
TOTAL_DROP_RATIO_THRESHOLD = 0.55

STOPWORDS = {
    "리포트",
    "증권",
    "분석",
    "정보",
    "시황",
    "보고서",
    "update",
    "daily",
    "weekly",
    "report",
    "market",
    "today",
    "morning",
    "brief",
    "comment",
    "letter",
    "review",
    "check",
    "focus",
    "watchlist",
    "preview",
    "기타",
}

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    chunks: list[str] = []
    for line in re.split(r"[\r\n]+", text):
        line = normalize_space(line)
        if not line:
            continue
        parts = SENTENCE_SPLIT_RE.split(line)
        for part in parts:
            sentence = normalize_space(part)
            if not sentence:
                continue
            if sentence.isupper() and len(sentence) < 40:
                continue
            chunks.append(sentence)
    return chunks


def _build_summary(text: str, sentence_count: int, preview_limit: int) -> tuple[str, str]:
    sentences = _split_sentences(text)
    if not sentences:
        fallback = trim_text(normalize_space(text), preview_limit) or "본문 요약을 만들 수 없었습니다."
        return fallback, fallback

    summary = " ".join(sentences[:sentence_count]).strip()
    excerpt = trim_text(" ".join(sentences[:2]).strip(), preview_limit)
    return summary or excerpt, excerpt or summary


def _contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    return term.lower() in text.lower()


def _report_text(report: Report) -> str:
    return report.source_text or report.title


def _report_text_length(report: Report) -> int:
    return max(len(report.body), len(report.pdf_text), len(report.source_text))


def _annotate_priority_matches(report: Report, settings: Settings) -> None:
    source_text = " ".join(
        part
        for part in (report.subject, report.title, _report_text(report))
        if part
    )

    report.priority_subject_matches = [
        item
        for item in settings.priority_subjects
        if _contains_term(source_text, item)
    ]
    report.priority_keyword_matches = [
        item
        for item in settings.priority_keywords
        if _contains_term(source_text, item)
    ]


def _score_report(report: Report, settings: Settings) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    breakdown: list[dict[str, object]] = []

    def add_score(label: str, value: float, *, reason: str | None = None) -> None:
        nonlocal score
        if value == 0:
            return
        score += value
        breakdown.append(
            {
                "label": label,
                "value": round(value, 2),
                "kind": "penalty" if value < 0 else "boost",
            }
        )
        if reason:
            reasons.append(reason)

    add_score(
        f"{report.category_label} 카테고리",
        CATEGORY_WEIGHTS.get(report.category, 1.4),
        reason=f"{report.category_label} 카테고리",
    )

    source_boost = SOURCE_WEIGHTS.get(report.source, 0.0)
    if source_boost:
        reason = None
        if report.source != "naver_research":
            reason = "공식 소스"
        add_score("소스 가중치", source_boost, reason=reason)

    if report.priority_subject_matches:
        add_score(
            "관심 종목",
            4.0 + max(0.0, (len(report.priority_subject_matches) - 1) * 0.35),
            reason=f"관심 종목({', '.join(report.priority_subject_matches[:3])})",
        )

    if report.priority_keyword_matches:
        add_score(
            "관심 섹터/키워드",
            2.4 + max(0.0, (len(report.priority_keyword_matches) - 1) * 0.2),
            reason=f"관심 섹터/키워드({', '.join(report.priority_keyword_matches[:3])})",
        )

    add_score("조회수", min(2.3, math.log10(max(report.views, 1))))
    if report.views >= 1000:
        reasons.append("조회수 상위권")

    if report.target_price:
        add_score("목표가", 0.7, reason="목표가 포함")
    if report.opinion:
        add_score("투자의견", 0.6, reason="투자의견 포함")
    if report.analyst:
        add_score("애널리스트", 0.2)

    if report.estimate_metrics:
        add_score(
            "실적/마진 추정치",
            min(1.2, 0.35 + len(report.estimate_metrics) * 0.12),
            reason="실적/마진 추정치 포함",
        )
    if "earnings_estimate_up" in report.estimate_signal_types:
        add_score("이익 추정 상향", 1.8, reason="이익 추정 상향/증가")
    if "margin_estimate_up" in report.estimate_signal_types:
        add_score("마진율 개선", 1.5, reason="마진율 추정 상승/개선")
    if "earnings_estimate_down" in report.estimate_signal_types:
        add_score("이익 추정 하향", 1.1, reason="이익 추정 하향/감소")
    if "margin_estimate_down" in report.estimate_signal_types:
        add_score("마진율 악화", 0.9, reason="마진율 추정 하락/악화")

    if report.target_price_change == "up":
        add_score("목표가 상향", 2.2, reason="목표가 상향")
    elif report.target_price_change == "down":
        add_score("목표가 하향", 1.25, reason="목표가 하향")
    if report.target_price_change_pct is not None:
        add_score("목표가 변화폭", min(1.2, abs(report.target_price_change_pct) / 12))
    if report.opinion_changed:
        if report.opinion_change_direction == "up":
            add_score("의견 상향", 1.6, reason="의견 상향")
        elif report.opinion_change_direction == "down":
            add_score("의견 하향", 1.6, reason="의견 하향")
        else:
            add_score("의견 변경", 1.6, reason="의견 변경")
    if report.coverage_initiated:
        add_score("신규 커버리지", 1.2, reason="신규 커버리지")
    if report.analyst_changed:
        add_score("애널리스트 변경", 0.45)

    broker_index = None
    for index, broker in enumerate(settings.broker_priority):
        if report.broker == broker:
            broker_index = index
            break
    if broker_index is not None:
        add_score(
            "우선 추적 증권사",
            max(0.25, 1.2 - broker_index * 0.05),
            reason="우선 추적 증권사",
        )

    title_lower = report.title.lower()
    matched_keywords: list[str] = []
    for keyword, boost in TITLE_KEYWORD_BOOSTS.items():
        if keyword in title_lower or keyword in report.title:
            add_score(f"제목 키워드: {keyword}", boost)
            matched_keywords.append(keyword)
    if matched_keywords:
        reasons.append(f"핵심 키워드({', '.join(matched_keywords[:3])})")

    for keyword, penalty in TITLE_KEYWORD_PENALTIES.items():
        if keyword in title_lower or keyword in report.title:
            add_score(f"제목 패널티: {keyword}", penalty)

    text_length = _report_text_length(report)
    if text_length >= 2500:
        add_score("본문 정보량", 0.95, reason="본문 정보량 풍부")
    elif text_length >= 1000:
        add_score("본문 정보량", 0.55)
    elif text_length >= 400:
        add_score("본문 정보량", 0.25)

    if report.has_pdf_text:
        add_score("PDF 본문", 0.35, reason="PDF 본문 확보")

    report.score_breakdown = sorted(
        breakdown,
        key=lambda item: abs(float(item.get("value") or 0.0)),
        reverse=True,
    )
    return round(score, 2), list(dict.fromkeys(reasons))[:5]


def _extract_keywords(reports: list[Report], limit: int = 8) -> list[str]:
    counter: Counter[str] = Counter()
    display_tokens: dict[str, str] = {}

    for report in reports:
        source_text = f"{report.subject or ''} {report.title}"
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+#-]{1,}|[가-힣]{2,}", source_text):
            lowered = token.lower()
            if re.fullmatch(r"q\d{2}", lowered):
                continue
            if lowered in STOPWORDS or token in STOPWORDS:
                continue
            canonical = token.upper() if token.isascii() else token
            key = canonical.lower() if canonical.isascii() else canonical
            counter[key] += 1
            display_tokens.setdefault(key, canonical)

    return [display_tokens[key] for key, _ in counter.most_common(limit)]


def _report_history_key(
    broker: str | None,
    subject: str | None,
) -> str | None:
    normalized_broker = normalize_report_key(broker or "")
    normalized_subject = normalize_subject_key(subject)
    if not normalized_broker or not normalized_subject:
        return None
    return f"{normalized_broker}:{normalized_subject}"


def _iter_previous_digests(
    archive_root,
    current_date: str,
    limit: int = COLLECTOR_HISTORY_LIMIT,
) -> list[dict[str, object]]:
    previous_digests: list[dict[str, object]] = []
    for _, payload in iter_digest_payloads(archive_root):
        payload_date = str(payload.get("date", ""))
        if not payload_date or payload_date >= current_date:
            continue

        previous_digests.append(payload)
        if len(previous_digests) >= limit:
            break

    return previous_digests


def _iter_previous_reports(
    archive_root,
    current_date: str,
) -> list[dict[str, object]]:
    previous_reports: list[dict[str, object]] = []
    for _, payload in iter_digest_payloads(archive_root):
        payload_date = str(payload.get("date", ""))
        if not payload_date or payload_date >= current_date:
            continue
        previous_reports.extend(iter_payload_reports(payload))

    return previous_reports


def _build_previous_report_lookup(
    archive_root,
    current_date: str,
) -> dict[str, dict[str, object]]:
    lookup: dict[str, dict[str, object]] = {}
    for report in _iter_previous_reports(archive_root, current_date):
        key = _report_history_key(
            str(report.get("broker") or ""),
            str(report.get("subject") or ""),
        )
        if not key or key in lookup:
            continue
        lookup[key] = report
    return lookup


def _change_sort_key(report: Report) -> tuple[object, ...]:
    return (
        1 if "earnings_estimate_up" in report.estimate_signal_types else 0,
        1 if "margin_estimate_up" in report.estimate_signal_types else 0,
        1 if report.coverage_initiated else 0,
        1 if report.opinion_changed else 0,
        1 if report.target_price_change else 0,
        abs(report.target_price_change_pct or 0.0),
        report.score,
        report.display_title,
    )


def _append_unique(target: list[str], values: list[str]) -> None:
    seen = set(target)
    for value in values:
        if value and value not in seen:
            target.append(value)
            seen.add(value)


def _bump(summary: dict[str, object], key: str) -> None:
    summary[key] = int(summary.get(key) or 0) + 1


def _append_estimate_change_signals(
    report: Report,
    summary: dict[str, object],
) -> None:
    if not report.estimate_signal_types:
        return

    _bump(summary, "estimate_signal_reports")
    for signal_type in report.estimate_signal_types:
        if signal_type in summary:
            _bump(summary, signal_type)

    _append_unique(report.change_types, report.estimate_signal_types)
    _append_unique(report.change_reasons, report.estimate_reasons)


def _reset_change_state(report: Report) -> None:
    report.previous_report_date = None
    report.previous_target_price = None
    report.previous_opinion = None
    report.previous_analyst = None
    report.target_price_change = None
    report.target_price_change_pct = None
    report.opinion_changed = False
    report.opinion_change_direction = None
    report.analyst_changed = False
    report.coverage_initiated = False
    report.change_types = []
    report.change_reasons = []


def _mark_coverage_initiated(report: Report, summary: dict[str, object]) -> None:
    if (
        report.category == "company"
        and report.subject_key
        and (report.target_price_value is not None or report.opinion_normalized)
    ):
        report.coverage_initiated = True
        report.change_types.append("coverage_initiated")
        report.change_reasons.append("신규 커버리지")
        _bump(summary, "coverage_initiated")


def _detect_target_price_change(
    report: Report,
    previous: dict[str, object],
    summary: dict[str, object],
) -> None:
    current_target = report.target_price_value
    previous_target_raw = previous.get("target_price_value")
    previous_target = (
        previous_target_raw
        if isinstance(previous_target_raw, int)
        else parse_target_price_value(
            str(previous_target_raw)
            if previous_target_raw is not None
            else report.previous_target_price
        )
    )
    if (
        current_target is None
        or previous_target is None
        or current_target == previous_target
    ):
        return

    report.target_price_change = "up" if current_target > previous_target else "down"
    if previous_target > 0:
        report.target_price_change_pct = round(
            ((current_target - previous_target) / previous_target) * 100,
            1,
        )
    if report.target_price_change == "up":
        report.change_reasons.append("목표가 상향")
        report.change_types.append("target_up")
        _bump(summary, "target_price_up")
    else:
        report.change_reasons.append("목표가 하향")
        report.change_types.append("target_down")
        _bump(summary, "target_price_down")


def _detect_opinion_change(
    report: Report,
    previous: dict[str, object],
    summary: dict[str, object],
) -> None:
    current_opinion = report.opinion_normalized or normalize_opinion_value(report.opinion)
    previous_opinion_raw = previous.get("opinion_normalized")
    previous_opinion = str(previous_opinion_raw) if previous_opinion_raw else None
    if previous_opinion is None:
        previous_opinion = normalize_opinion_value(report.previous_opinion)
    if not current_opinion or not previous_opinion or current_opinion == previous_opinion:
        return

    report.opinion_changed = True
    report.opinion_change_direction = opinion_change_direction(
        current_opinion,
        previous_opinion,
    )
    if report.opinion_change_direction == "up":
        report.change_types.append("opinion_up")
        _bump(summary, "opinion_up")
    elif report.opinion_change_direction == "down":
        report.change_types.append("opinion_down")
        _bump(summary, "opinion_down")
    else:
        report.change_types.append("opinion_changed")
    report.change_reasons.append("의견 변경")
    _bump(summary, "opinion_changed")


def _detect_analyst_change(report: Report, summary: dict[str, object]) -> None:
    current_analyst = normalize_space(report.analyst or "")
    previous_analyst = normalize_space(report.previous_analyst or "")
    if current_analyst and previous_analyst and current_analyst != previous_analyst:
        report.analyst_changed = True
        report.change_types.append("analyst_changed")
        report.change_reasons.append("애널리스트 변경")
        _bump(summary, "analyst_changed")


def _annotate_changes(
    reports: list[Report],
    *,
    current_date: str,
    settings: Settings,
) -> tuple[dict[str, object], list[Report]]:
    summary = {
        "available": False,
        "changed_reports": 0,
        "target_price_up": 0,
        "target_price_down": 0,
        "opinion_changed": 0,
        "opinion_up": 0,
        "opinion_down": 0,
        "analyst_changed": 0,
        "coverage_initiated": 0,
        "estimate_signal_reports": 0,
        "earnings_estimate_up": 0,
        "earnings_estimate_down": 0,
        "margin_estimate_up": 0,
        "margin_estimate_down": 0,
    }

    history_lookup = _build_previous_report_lookup(settings.archive_root, current_date)
    summary["available"] = bool(history_lookup)
    changed_reports: list[Report] = []

    for report in reports:
        _reset_change_state(report)
        _append_estimate_change_signals(report, summary)

        key = _report_history_key(report.broker, report.subject)
        previous = history_lookup.get(key) if key else None
        if previous:
            report.previous_report_date = str(previous.get("published_date") or "") or None
            report.previous_target_price = str(previous.get("target_price") or "") or None
            report.previous_opinion = str(previous.get("opinion") or "") or None
            report.previous_analyst = str(previous.get("analyst") or "") or None

            _detect_target_price_change(report, previous, summary)
            _detect_opinion_change(report, previous, summary)
            _detect_analyst_change(report, summary)
        elif key and history_lookup:
            _mark_coverage_initiated(report, summary)

        if report.has_change_signal:
            changed_reports.append(report)

    changed_reports.sort(key=_change_sort_key, reverse=True)
    summary["changed_reports"] = len(changed_reports)
    summary["available"] = bool(summary["available"] or changed_reports)
    return summary, changed_reports


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _build_link_health_summary(reports: list[Report]) -> dict[str, object]:
    status_counts = Counter(report.link_health["status"] for report in reports)
    return {
        "pdf_preferred": status_counts.get("pdf_preferred", 0),
        "detail_only": status_counts.get("detail_only", 0),
        "missing": status_counts.get("missing", 0),
        "total": len(reports),
    }


def _build_must_read_diversity(
    must_read: list[Report],
    settings: Settings,
) -> dict[str, object]:
    broker_counts = Counter(report.broker for report in must_read if report.broker)
    identity_counts = Counter(_must_read_identity_key(report) for report in must_read)
    return {
        "selected": len(must_read),
        "unique_subject_or_title": len(identity_counts),
        "unique_brokers": len(broker_counts),
        "max_broker_count": max(broker_counts.values(), default=0),
        "max_subject_or_title_count": max(identity_counts.values(), default=0),
        "broker_soft_limit": settings.must_read_broker_soft_limit,
        "broker_hard_limit": settings.must_read_broker_hard_limit,
        "subject_hard_limit": settings.must_read_subject_hard_limit,
    }


def _must_read_identity_key(report: Report) -> str:
    if report.subject_key:
        return f"subject:{report.subject_key}"
    return f"title:{normalize_report_key(report.display_title or report.title)}"


def _select_must_read(
    reports: list[Report],
    limit: int,
    *,
    changed_reports: list[Report] | None = None,
    broker_soft_limit: int = MUST_READ_BROKER_SOFT_LIMIT,
    broker_hard_limit: int = MUST_READ_BROKER_HARD_LIMIT,
    identity_hard_limit: int = MUST_READ_IDENTITY_HARD_LIMIT,
) -> list[Report]:
    if not reports:
        return []

    grouped: dict[str, list[Report]] = defaultdict(list)
    for report in reports:
        grouped[report.category].append(report)

    selected: list[Report] = []
    seen_ids: set[str] = set()
    seen_identity_keys: set[str] = set()
    identity_counts: Counter[str] = Counter()
    broker_counts: Counter[str] = Counter()

    def add_candidate(report: Report, *, diversity: str) -> bool:
        if report.report_id in seen_ids or len(selected) >= limit:
            return False

        identity_key = _must_read_identity_key(report)
        if diversity == "strict":
            if identity_key in seen_identity_keys:
                return False
            if broker_counts[report.broker] >= broker_soft_limit:
                return False
        elif diversity == "relaxed":
            if identity_counts[identity_key] >= identity_hard_limit:
                return False
            if broker_counts[report.broker] >= broker_hard_limit:
                return False

        selected.append(report)
        seen_ids.add(report.report_id)
        seen_identity_keys.add(identity_key)
        identity_counts[identity_key] += 1
        broker_counts[report.broker] += 1
        return True

    signal_candidates = changed_reports or []
    signal_target = min(MUST_READ_SIGNAL_LIMIT, limit)
    for report in signal_candidates:
        if len(selected) >= signal_target:
            break
        add_candidate(report, diversity="strict")

    for category, quota in MUST_READ_QUOTAS:
        category_count = sum(1 for report in selected if report.category == category)
        for report in grouped.get(category, []):
            if category_count >= quota or len(selected) >= limit:
                break
            if add_candidate(report, diversity="strict"):
                category_count += 1

    if len(selected) < limit:
        for report in reports:
            add_candidate(report, diversity="relaxed")

    if len(selected) < limit:
        for report in reports:
            add_candidate(report, diversity="none")

    return selected[:limit]


def _build_stats(
    reports: list[Report],
    keywords: list[str],
    change_summary: dict[str, object],
    collection_attempts: list[dict[str, object]] | None = None,
    *,
    archive_root=None,
    current_date: str = "",
    must_read: list[Report] | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    category_counts = Counter(report.category_label for report in reports)
    broker_counts = Counter(report.broker for report in reports)
    priority_count = sum(1 for report in reports if report.is_priority_match)
    pdf_text_count = sum(1 for report in reports if report.has_pdf_text)
    active_attempt = _active_collection_attempt(collection_attempts)
    collector_health = _collector_health_items(active_attempt)
    collector_summary = _build_collector_health_summary(
        collection_attempts or [],
        collector_health,
    )
    collector_alerts = _build_collector_alerts(
        collection_attempts or [],
        collector_health,
        archive_root=archive_root,
        current_date=current_date,
    )
    collector_alert_summary = _build_collector_alert_summary(collector_alerts)

    return {
        "total_reports": len(reports),
        "priority_match_reports": priority_count,
        "pdf_text_reports": pdf_text_count,
        "estimate_metric_reports": sum(1 for report in reports if report.estimate_metrics),
        "estimate_signal_reports": change_summary.get("estimate_signal_reports", 0),
        "earnings_estimate_up": change_summary.get("earnings_estimate_up", 0),
        "earnings_estimate_down": change_summary.get("earnings_estimate_down", 0),
        "margin_estimate_up": change_summary.get("margin_estimate_up", 0),
        "margin_estimate_down": change_summary.get("margin_estimate_down", 0),
        "llm_summary_reports": 0,
        "llm_investment_memo_reports": 0,
        "changed_reports": change_summary.get("changed_reports", 0),
        "collector_health": collector_health,
        "collector_health_summary": collector_summary,
        "collector_health_attempts": collection_attempts or [],
        "collector_alerts": collector_alerts,
        "collector_alert_summary": collector_alert_summary,
        "link_health": _build_link_health_summary(reports),
        "must_read_diversity": _build_must_read_diversity(must_read or [], settings)
        if settings
        else {},
        "categories": [
            {"label": label, "count": count}
            for label, count in category_counts.most_common()
        ],
        "brokers": [
            {"name": broker, "count": count}
            for broker, count in broker_counts.most_common(10)
        ],
        "keywords": keywords,
    }


def _active_collection_attempt(
    collection_attempts: list[dict[str, object]] | None,
) -> dict[str, object] | None:
    if not collection_attempts:
        return None
    for attempt in reversed(collection_attempts):
        if _safe_int(attempt.get("deduped_report_count")) > 0:
            return attempt
    return collection_attempts[-1]


def _collector_health_items(
    active_attempt: dict[str, object] | None,
) -> list[dict[str, object]]:
    if not active_attempt:
        return []
    collectors = active_attempt.get("collectors")
    if not isinstance(collectors, list):
        return []
    return [item for item in collectors if isinstance(item, dict)]


def _build_collector_health_summary(
    collection_attempts: list[dict[str, object]],
    collector_health: list[dict[str, object]],
) -> dict[str, object]:
    status_counts = Counter(str(item.get("status") or "unknown") for item in collector_health)
    active_attempt = _active_collection_attempt(collection_attempts)
    return {
        "available": bool(collector_health),
        "active_date": str(active_attempt.get("date") or "") if active_attempt else "",
        "attempt_count": len(collection_attempts),
        "ok_sources": status_counts.get("ok", 0),
        "empty_sources": status_counts.get("empty", 0),
        "failed_sources": status_counts.get("failed", 0),
        "raw_report_count": _safe_int(active_attempt.get("raw_report_count"))
        if active_attempt
        else 0,
        "deduped_report_count": _safe_int(active_attempt.get("deduped_report_count"))
        if active_attempt
        else 0,
    }


def _source_counts_from_digest(payload: dict[str, object]) -> dict[str, int]:
    stats = payload.get("stats")
    if isinstance(stats, dict):
        collector_health = stats.get("collector_health")
        if isinstance(collector_health, list):
            counts: dict[str, int] = {}
            for item in collector_health:
                if not isinstance(item, dict):
                    continue
                source = str(item.get("source") or "")
                if not source:
                    continue
                counts[source] = _safe_int(item.get("report_count"))
            if counts:
                return counts

    counts = Counter()
    reports_payload = payload.get("reports")
    if isinstance(reports_payload, list):
        for report in reports_payload:
            if isinstance(report, dict):
                source = str(report.get("source") or "")
                if source:
                    counts[source] += 1
    return dict(counts)


def _total_count_from_digest(payload: dict[str, object]) -> int:
    stats = payload.get("stats")
    if isinstance(stats, dict):
        collector_summary = stats.get("collector_health_summary")
        if isinstance(collector_summary, dict):
            total = _safe_int(collector_summary.get("deduped_report_count"))
            if total:
                return total
        total = _safe_int(stats.get("total_reports"))
        if total:
            return total

    reports_payload = payload.get("reports")
    if isinstance(reports_payload, list):
        return len(reports_payload)
    return 0


def _collector_history_baselines(
    archive_root,
    current_date: str,
) -> dict[str, object]:
    previous_digests = _iter_previous_digests(archive_root, current_date)
    source_counts: dict[str, list[int]] = defaultdict(list)
    total_counts: list[int] = []

    for payload in previous_digests:
        total_count = _total_count_from_digest(payload)
        if total_count:
            total_counts.append(total_count)
        for source, count in _source_counts_from_digest(payload).items():
            source_counts[source].append(count)

    source_baselines = {
        source: {
            "average_report_count": round(sum(counts) / len(counts), 1),
            "sample_days": len(counts),
            "max_report_count": max(counts),
        }
        for source, counts in source_counts.items()
        if counts
    }

    total_average = round(sum(total_counts) / len(total_counts), 1) if total_counts else 0.0
    return {
        "source": source_baselines,
        "total": {
            "average_report_count": total_average,
            "sample_days": len(total_counts),
            "max_report_count": max(total_counts) if total_counts else 0,
        },
    }


def _build_collector_alerts(
    collection_attempts: list[dict[str, object]],
    collector_health: list[dict[str, object]],
    *,
    archive_root=None,
    current_date: str = "",
) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    active_attempt = _active_collection_attempt(collection_attempts)
    baselines = (
        _collector_history_baselines(archive_root, current_date)
        if archive_root and current_date
        else {"source": {}, "total": {}}
    )

    total_baseline = baselines.get("total", {})
    total_average = _safe_float(
        total_baseline.get("average_report_count") if isinstance(total_baseline, dict) else 0
    )
    current_total = (
        _safe_int(active_attempt.get("deduped_report_count")) if active_attempt else 0
    )
    if (
        total_average >= MIN_TOTAL_BASELINE_COUNT
        and current_total <= total_average * TOTAL_DROP_RATIO_THRESHOLD
    ):
        alerts.append(
            {
                "type": "total_volume_drop",
                "severity": "warning",
                "source": "__total__",
                "label": "전체 수집량",
                "title": "전체 수집량 급감",
                "message": (
                    f"오늘 {current_total}건으로 최근 평균 {total_average:.1f}건 대비 낮습니다."
                ),
                "current_count": current_total,
                "average_count": total_average,
                "sample_days": _safe_int(
                    total_baseline.get("sample_days") if isinstance(total_baseline, dict) else 0
                ),
            }
        )

    source_baselines = baselines.get("source", {})
    if not isinstance(source_baselines, dict):
        source_baselines = {}

    for item in collector_health:
        source = str(item.get("source") or "")
        label = str(item.get("label") or source or "-")
        status = str(item.get("status") or "unknown")
        current_count = _safe_int(item.get("report_count"))
        baseline = source_baselines.get(source)
        average_count = (
            _safe_float(baseline.get("average_report_count"))
            if isinstance(baseline, dict)
            else 0.0
        )
        sample_days = (
            _safe_int(baseline.get("sample_days"))
            if isinstance(baseline, dict)
            else 0
        )

        if status == "failed":
            alerts.append(
                {
                    "type": "collector_failed",
                    "severity": "critical",
                    "source": source,
                    "label": label,
                    "title": f"{label} 수집 실패",
                    "message": str(item.get("message") or "수집기가 실패했습니다."),
                    "current_count": current_count,
                    "average_count": average_count,
                    "sample_days": sample_days,
                }
            )
            continue

        if average_count < MIN_SOURCE_BASELINE_COUNT:
            continue

        if status == "empty":
            alerts.append(
                {
                    "type": "collector_empty",
                    "severity": "warning",
                    "source": source,
                    "label": label,
                    "title": f"{label} 무출력",
                    "message": (
                        f"오늘 0건입니다. 최근 평균은 {average_count:.1f}건입니다."
                    ),
                    "current_count": current_count,
                    "average_count": average_count,
                    "sample_days": sample_days,
                }
            )
            continue

        if current_count <= average_count * SOURCE_DROP_RATIO_THRESHOLD:
            alerts.append(
                {
                    "type": "collector_volume_drop",
                    "severity": "warning",
                    "source": source,
                    "label": label,
                    "title": f"{label} 수집량 급감",
                    "message": (
                        f"오늘 {current_count}건으로 최근 평균 {average_count:.1f}건 대비 낮습니다."
                    ),
                    "current_count": current_count,
                    "average_count": average_count,
                    "sample_days": sample_days,
                }
            )

    return alerts


def _build_collector_alert_summary(
    collector_alerts: list[dict[str, object]],
) -> dict[str, object]:
    severity_counts = Counter(str(item.get("severity") or "unknown") for item in collector_alerts)
    type_counts = Counter(str(item.get("type") or "unknown") for item in collector_alerts)
    return {
        "available": bool(collector_alerts),
        "total_alerts": len(collector_alerts),
        "critical_alerts": severity_counts.get("critical", 0),
        "warning_alerts": severity_counts.get("warning", 0),
        "failed_sources": type_counts.get("collector_failed", 0),
        "empty_sources": type_counts.get("collector_empty", 0),
        "volume_drop_alerts": (
            type_counts.get("collector_volume_drop", 0)
            + type_counts.get("total_volume_drop", 0)
        ),
    }


def _build_priority_filters(
    reports: list[Report],
    must_read: list[Report],
    settings: Settings,
) -> dict[str, object]:
    return {
        "enabled": settings.priority_filter_enabled,
        "subjects": list(settings.priority_subjects),
        "keywords": list(settings.priority_keywords),
        "priority_only": settings.priority_only,
        "matched_reports": sum(1 for report in reports if report.is_priority_match),
        "matched_must_read": sum(1 for report in must_read if report.is_priority_match),
    }


def _build_editorial_note(
    reports: list[Report],
    must_read: list[Report],
    change_summary: dict[str, object],
) -> str:
    if not reports:
        return "해당 일자에 수집된 리포트가 없습니다."

    category_counts = Counter(report.category_label for report in reports)
    broker_counts = Counter(report.broker for report in reports)

    busiest_category, category_count = category_counts.most_common(1)[0]
    active_brokers = ", ".join(broker for broker, _ in broker_counts.most_common(3))
    must_read_titles = ", ".join(report.display_title for report in must_read[:3])

    change_labels = (
        ("earnings_estimate_up", "이익 추정 상향"),
        ("margin_estimate_up", "마진 개선"),
        ("target_price_up", "목표가 상향"),
        ("target_price_down", "목표가 하향"),
        ("opinion_changed", "의견 변경"),
    )
    change_bits = [
        f"{label} {change_summary[key]}건"
        for key, label in change_labels
        if change_summary.get(key)
    ]
    prefix = f"{', '.join(change_bits)}이 감지됐습니다. " if change_bits else ""

    return (
        prefix
        + f"오늘은 {busiest_category} 리포트가 {category_count}건으로 가장 많았습니다. "
        f"{active_brokers} 발간 비중이 높았고, "
        f"우선 확인할 만한 핵심 리포트는 {must_read_titles}입니다."
    )


def _build_rankings(reports: list[Report], limit: int) -> dict[str, dict[str, object]]:
    rankings: dict[str, dict[str, object]] = {}
    for key, label, categories in RANKING_GROUPS:
        matched = [report for report in reports if report.category in categories]
        if not matched:
            continue
        rankings[key] = {
            "label": label,
            "reports": matched[:limit],
        }
    return rankings


def _build_dashboard_url(site_url: str | None, date_text: str) -> str | None:
    if not site_url:
        return None
    separator = "&" if "?" in site_url else "?"
    return f"{site_url}{separator}date={date_text}"


def _format_collector_status(status: object) -> str:
    return {
        "ok": "정상",
        "empty": "무출력",
        "failed": "실패",
    }.get(str(status or ""), "확인 필요")


def _format_alert_severity(severity: object) -> str:
    return {
        "critical": "긴급",
        "warning": "주의",
    }.get(str(severity or ""), "확인")


def _format_memo_stance(stance: object) -> str:
    return {
        "positive": "긍정",
        "neutral": "중립",
        "negative": "부정",
        "watch": "관찰",
    }.get(str(stance or ""), "관찰")


def _format_memo_confidence(confidence: object) -> str:
    return {
        "high": "높음",
        "medium": "보통",
        "low": "낮음",
    }.get(str(confidence or ""), "낮음")


def _memo_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [normalize_space(str(item or "")) for item in value if normalize_space(str(item or ""))]


def _has_investment_memo(report: Report) -> bool:
    memo = report.investment_memo
    if not isinstance(memo, dict) or not memo:
        return False
    return bool(
        _memo_list(memo.get("thesis"))
        or _memo_list(memo.get("catalysts"))
        or _memo_list(memo.get("risks"))
        or _memo_list(memo.get("numbers"))
        or normalize_space(str(memo.get("action") or ""))
    )


def _format_duration(seconds: object) -> str:
    try:
        numeric = float(seconds or 0)
    except (TypeError, ValueError):
        numeric = 0.0
    return f"{numeric:.2f}초"


def _format_target_change(report: Report) -> str | None:
    if not report.target_price_change:
        return None

    direction = "상향" if report.target_price_change == "up" else "하향"
    percent = ""
    if report.target_price_change_pct is not None:
        percent = f" ({report.target_price_change_pct:+.1f}%)"
    return (
        f"목표가 {direction}: "
        f"{report.previous_target_price or '-'} → {report.target_price or '-'}{percent}"
    )


def _collector_problem_items(digest: DailyDigest) -> list[dict[str, object]]:
    collector_health = digest.stats.get("collector_health", [])
    if not isinstance(collector_health, list):
        return []

    collector_alerts = digest.stats.get("collector_alerts", [])
    alert_sources = {
        str(item.get("source") or "")
        for item in collector_alerts
        if isinstance(item, dict)
    }

    problem_items: list[dict[str, object]] = []
    for item in collector_health:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        source = str(item.get("source") or "")
        if status != "ok" or source in alert_sources:
            problem_items.append(item)
    return problem_items


def enrich_and_build_digest(
    reports: list[Report],
    *,
    target_date: str,
    requested_date: str,
    generated_at: str,
    collection_note: str,
    collection_attempts: list[dict[str, object]] | None = None,
    settings: Settings,
) -> DailyDigest:
    for report in reports:
        summary_source = _report_text(report)
        report.summary, report.excerpt = _build_summary(
            summary_source,
            settings.summary_sentence_count,
            settings.preview_char_limit,
        )
        report.summary_engine = "rule"
        annotate_report_normalized_fields(report)
        annotate_report_estimates(report)
        _annotate_priority_matches(report, settings)
        report.score, report.score_reasons = _score_report(report, settings)

    reports.sort(key=lambda item: (-item.score, item.broker, item.title))
    change_summary, changed_reports = _annotate_changes(
        reports,
        current_date=target_date,
        settings=settings,
    )
    selection_pool = reports
    if settings.priority_only:
        matched_reports = [report for report in reports if report.is_priority_match]
        if matched_reports:
            selection_pool = matched_reports

    selection_ids = {report.report_id for report in selection_pool}
    selection_changes = [
        report for report in changed_reports if report.report_id in selection_ids
    ]
    must_read = _select_must_read(
        selection_pool,
        settings.must_read_limit,
        changed_reports=selection_changes,
        broker_soft_limit=settings.must_read_broker_soft_limit,
        broker_hard_limit=settings.must_read_broker_hard_limit,
        identity_hard_limit=settings.must_read_subject_hard_limit,
    )
    keywords = _extract_keywords(must_read or reports)
    stats = _build_stats(
        reports,
        keywords,
        change_summary,
        collection_attempts,
        archive_root=settings.archive_root,
        current_date=target_date,
        must_read=must_read,
        settings=settings,
    )
    priority_filters = _build_priority_filters(reports, must_read, settings)
    editorial_note = _build_editorial_note(reports, must_read, change_summary)
    rankings = _build_rankings(reports, settings.ranking_limit)
    dashboard_url = _build_dashboard_url(settings.site_url, target_date)

    return DailyDigest(
        date=target_date,
        requested_date=requested_date,
        generated_at=generated_at,
        collection_note=collection_note,
        dashboard_url=dashboard_url,
        editorial_note=editorial_note,
        keywords=keywords,
        priority_filters=priority_filters,
        stats=stats,
        change_summary=change_summary,
        rankings=rankings,
        changes=changed_reports,
        must_read=must_read,
        reports=reports,
    )


def render_markdown(digest: DailyDigest) -> str:
    lines = [
        f"# {digest.date} 증권사 리포트 데일리",
        "",
        f"- 요청 기준일: {digest.requested_date}",
        f"- 생성 시각: {digest.generated_at}",
        f"- 대시보드: {digest.dashboard_url or '미설정'}",
        f"- 수집 건수: {digest.stats['total_reports']}건",
        f"- PDF 텍스트 보강: {digest.stats.get('pdf_text_reports', 0)}건",
        f"- OpenAI 요약 적용: {digest.stats.get('llm_summary_reports', 0)}건",
        f"- LLM 투자 메모: {digest.stats.get('llm_investment_memo_reports', 0)}건",
        f"- 키워드: {', '.join(digest.keywords) if digest.keywords else '없음'}",
        "",
    ]

    if digest.collection_note:
        lines.extend(["## 수집 메모", digest.collection_note, ""])

    collector_alerts = digest.stats.get("collector_alerts", [])
    if isinstance(collector_alerts, list) and collector_alerts:
        lines.extend(["## 운영 알림", ""])
        for item in collector_alerts:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- "
                f"[{_format_alert_severity(item.get('severity'))}] "
                f"{item.get('title') or item.get('label')}: "
                f"{item.get('message') or ''}"
            )
        lines.append("")

    collector_health = digest.stats.get("collector_health", [])
    if isinstance(collector_health, list) and collector_health:
        lines.extend(["## 수집 소스 상태", ""])
        for item in collector_health:
            if not isinstance(item, dict):
                continue
            status = _format_collector_status(item.get("status"))
            message = str(item.get("message") or "")
            line = (
                f"- {item.get('label') or item.get('source')}: {status}, "
                f"{item.get('report_count', 0)}건, "
                f"{_format_duration(item.get('duration_seconds'))}"
            )
            if message:
                line += f" - {message}"
            lines.append(line)
        lines.append("")

    if digest.priority_filters["enabled"]:
        lines.extend(
            [
                "## 관심 필터",
                f"- 관심 종목: {', '.join(digest.priority_filters['subjects']) or '없음'}",
                f"- 관심 섹터/키워드: {', '.join(digest.priority_filters['keywords']) or '없음'}",
                f"- 일치 리포트: {digest.priority_filters['matched_reports']}건",
                (
                    "- 엄격 필터 모드: "
                    f"{'켜짐' if digest.priority_filters['priority_only'] else '꺼짐'}"
                ),
                "",
            ]
        )

    lines.extend(["## 오늘의 한줄", digest.editorial_note, ""])

    if digest.change_summary.get("available"):
        lines.extend(
            [
                "## 이익·마진 추정 변화",
                f"- 변화 감지 리포트: {digest.change_summary.get('changed_reports', 0)}건",
                (
                    f"- 이익 추정 상향/하향: "
                    f"{digest.change_summary.get('earnings_estimate_up', 0)}건 / "
                    f"{digest.change_summary.get('earnings_estimate_down', 0)}건"
                ),
                (
                    f"- 마진 개선/악화: "
                    f"{digest.change_summary.get('margin_estimate_up', 0)}건 / "
                    f"{digest.change_summary.get('margin_estimate_down', 0)}건"
                ),
                (
                    f"- 목표가 상향/하향: "
                    f"{digest.change_summary.get('target_price_up', 0)}건 / "
                    f"{digest.change_summary.get('target_price_down', 0)}건"
                ),
                (
                    f"- 의견 변경/애널리스트 변경: "
                    f"{digest.change_summary.get('opinion_changed', 0)}건 / "
                    f"{digest.change_summary.get('analyst_changed', 0)}건"
                ),
                "",
            ]
        )

        if digest.changes:
            for index, report in enumerate(digest.changes[:12], start=1):
                lines.extend(
                    [
                        f"### {index}. {report.display_title}",
                        f"- 증권사: {report.broker}",
                        f"- 변화 유형: {', '.join(report.change_reasons)}",
                    ]
                )
                target_line = _format_target_change(report)
                if target_line:
                    lines.append(f"- {target_line}")
                if report.opinion_changed:
                    lines.append(
                        f"- 의견 변경: {report.previous_opinion or '-'} → {report.opinion or '-'}"
                    )
                if report.analyst_changed:
                    lines.append(
                        f"- 애널리스트 변경: {report.previous_analyst or '-'} → {report.analyst or '-'}"
                    )
                if report.previous_report_date:
                    lines.append(f"- 비교 기준일: {report.previous_report_date}")
                lines.append(f"- 대표 링크: {report.primary_url}")
                lines.append("")

    if digest.rankings:
        lines.extend(["## 카테고리 랭킹", ""])
        for ranking in digest.rankings.values():
            lines.append(f"### {ranking['label']}")
            reports = ranking.get("reports", [])
            if not reports:
                lines.append("- 결과 없음")
            else:
                for index, report in enumerate(reports, start=1):
                    lines.append(
                        f"- {index}. {report.display_title} | {report.broker} | 우선순위 {report.score:.2f}"
                    )
            lines.append("")

    lines.append("## 우선 검토 후보")
    if not digest.must_read:
        lines.extend(["- 우선 검토 후보로 선정된 항목이 없습니다.", ""])

    for index, report in enumerate(digest.must_read, start=1):
        reasons = ", ".join(report.score_reasons) if report.score_reasons else "자동 선정"
        lines.extend(
            [
                f"### {index}. [{report.category_label}] {report.display_title}",
                f"- 증권사: {report.broker}",
                f"- 발행일: {report.published_date}",
                f"- 우선순위 점수: {report.score:.2f}",
                f"- 선정 근거: {reasons}",
                f"- 요약 엔진: {report.summary_engine}",
                (
                    "- 관심 필터 일치: "
                    f"종목 {', '.join(report.priority_subject_matches) or '없음'} / "
                    f"키워드 {', '.join(report.priority_keyword_matches) or '없음'}"
                )
                if report.is_priority_match
                else "- 관심 필터 일치: 없음",
                f"- 요약: {report.summary}",
                f"- 대표 링크: {report.primary_url}",
            ]
        )
        if report.pdf_url:
            lines.append(f"- 상세 페이지: {report.detail_url}")
        if _has_investment_memo(report):
            memo = report.investment_memo
            lines.extend(
                [
                    "- 투자 메모:",
                    f"  - 톤: {_format_memo_stance(memo.get('stance'))} / 신뢰도 {_format_memo_confidence(memo.get('confidence'))}",
                ]
            )
            action = normalize_space(str(memo.get("action") or ""))
            if action:
                lines.append(f"  - 액션: {action}")
            for label, key in (
                ("핵심 논지", "thesis"),
                ("촉매", "catalysts"),
                ("리스크", "risks"),
                ("숫자", "numbers"),
            ):
                values = _memo_list(memo.get(key))
                if values:
                    lines.append(f"  - {label}: {' / '.join(values)}")
        lines.append("")

    lines.extend(["## 전체 수집 결과", ""])
    for report in digest.reports:
        lines.append(
            f"- [{report.category_label}] {report.display_title} | {report.broker} | "
            f"{report.published_date} | 우선순위 {report.score:.2f} | {report.primary_url}"
        )

    return "\n".join(lines).strip() + "\n"


def render_telegram_messages(digest: DailyDigest, max_reports: int = 8) -> list[str]:
    header = [
        f"<b>{html.escape(digest.date)} 증권사 리포트 데일리</b>",
        f"총 {digest.stats['total_reports']}건 수집",
    ]
    if digest.dashboard_url:
        header.append(
            f'<a href="{html.escape(digest.dashboard_url)}">대시보드 열기</a>'
        )
    if digest.collection_note:
        header.append(html.escape(digest.collection_note))
    if digest.priority_filters["enabled"]:
        header.append(
            f"관심 필터 일치 {digest.priority_filters['matched_reports']}건"
        )
    if digest.stats.get("pdf_text_reports"):
        header.append(f"PDF 보강 {digest.stats['pdf_text_reports']}건")
    if digest.stats.get("llm_summary_reports"):
        header.append(f"OpenAI 요약 {digest.stats['llm_summary_reports']}건")
    if digest.stats.get("llm_investment_memo_reports"):
        header.append(f"LLM 투자 메모 {digest.stats['llm_investment_memo_reports']}건")
    collector_summary = digest.stats.get("collector_health_summary", {})
    if isinstance(collector_summary, dict) and collector_summary.get("available"):
        header.append(
            "소스 상태 "
            f"정상 {collector_summary.get('ok_sources', 0)} / "
            f"무출력 {collector_summary.get('empty_sources', 0)} / "
            f"실패 {collector_summary.get('failed_sources', 0)}"
        )
    collector_alert_summary = digest.stats.get("collector_alert_summary", {})
    if isinstance(collector_alert_summary, dict) and collector_alert_summary.get("available"):
        header.append(
            "운영 알림 "
            f"{collector_alert_summary.get('total_alerts', 0)}건"
            f" (긴급 {collector_alert_summary.get('critical_alerts', 0)} / "
            f"주의 {collector_alert_summary.get('warning_alerts', 0)})"
        )
    if digest.keywords:
        header.append(f"키워드: {html.escape(', '.join(digest.keywords[:6]))}")
    if digest.change_summary.get("changed_reports"):
        header.append(
            "변화 감지 "
            f"{digest.change_summary.get('changed_reports', 0)}건"
            f" (이익↑ {digest.change_summary.get('earnings_estimate_up', 0)} / "
            f"마진↑ {digest.change_summary.get('margin_estimate_up', 0)} / "
            f"목표가↑ {digest.change_summary.get('target_price_up', 0)} / "
            f"의견 {digest.change_summary.get('opinion_changed', 0)})"
        )
    header.append("")
    header.append(html.escape(digest.editorial_note))

    blocks = ["\n".join(header)]

    collector_alerts = digest.stats.get("collector_alerts", [])
    if isinstance(collector_alerts, list) and collector_alerts:
        alert_lines = ["", "<b>운영 알림</b>"]
        for item in collector_alerts[:6]:
            if not isinstance(item, dict):
                continue
            alert_lines.append(
                f"{html.escape(_format_alert_severity(item.get('severity')))} · "
                f"{html.escape(str(item.get('title') or item.get('label') or '-'))}\n"
                f"{html.escape(trim_text(str(item.get('message') or ''), 140))}"
            )
        blocks.append("\n".join(alert_lines))

    problem_health = _collector_problem_items(digest)
    if problem_health:
        health_lines = ["", "<b>점검 필요한 소스</b>"]
        for item in problem_health[:6]:
            status = _format_collector_status(item.get("status"))
            message = str(item.get("message") or "")
            line = (
                f"{html.escape(str(item.get('label') or item.get('source') or '-'))}: "
                f"{html.escape(status)} · "
                f"{html.escape(str(item.get('report_count', 0)))}건 · "
                f"{html.escape(_format_duration(item.get('duration_seconds')))}"
            )
            if message and item.get("status") != "ok":
                line += f"\n{html.escape(trim_text(message, 120))}"
            health_lines.append(line)
        blocks.append("\n".join(health_lines))

    ranking_lines = ["", "<b>카테고리 랭킹</b>"]
    for key in ("company", "industry", "macro", "strategy"):
        ranking = digest.rankings.get(key)
        if not ranking:
            continue
        reports = ranking.get("reports", [])
        if not reports:
            continue
        top_report = reports[0]
        ranking_lines.append(
            f"{html.escape(str(ranking['label']))}: "
            f'<a href="{html.escape(top_report.primary_url)}">'
            f"{html.escape(top_report.display_title)}</a>"
        )
    if len(ranking_lines) > 2:
        blocks.append("\n".join(ranking_lines))

    if digest.changes:
        change_lines = ["", "<b>이익·마진 추정 변화</b>"]
        for report in digest.changes[:5]:
            detail_bits = []
            target_line = _format_target_change(report)
            if target_line:
                detail_bits.append(target_line)
            if report.opinion_changed:
                detail_bits.append(
                    f"의견 {report.previous_opinion or '-'} → {report.opinion or '-'}"
                )
            if report.analyst_changed:
                detail_bits.append(
                    f"애널리스트 {report.previous_analyst or '-'} → {report.analyst or '-'}"
                )
            change_lines.append(
                f'• <a href="{html.escape(report.primary_url)}">'
                f"{html.escape(report.display_title)}</a>"
            )
            if detail_bits:
                change_lines.append(html.escape(" / ".join(detail_bits)))
        blocks.append("\n".join(change_lines))

    for index, report in enumerate(digest.must_read[:max_reports], start=1):
        summary = trim_text(report.summary, 160)
        meta_bits = [report.broker, f"우선순위 {report.score:.2f}"]
        if report.target_price:
            meta_bits.append(f"목표가 {report.target_price}")
        if report.opinion:
            meta_bits.append(f"의견 {report.opinion}")
        parts = [
            "",
            f"<b>{index}. [{html.escape(report.category_label)}] "
            f'<a href="{html.escape(report.primary_url)}">'
            f"{html.escape(report.display_title)}</a></b>",
            html.escape(" · ".join(meta_bits)),
        ]
        if report.change_reasons:
            parts.append(html.escape("변화: " + ", ".join(report.change_reasons[:2])))
        if _has_investment_memo(report):
            memo = report.investment_memo
            action = normalize_space(str(memo.get("action") or ""))
            thesis = _memo_list(memo.get("thesis"))
            memo_bits = [
                f"톤 {_format_memo_stance(memo.get('stance'))}",
                f"신뢰 {_format_memo_confidence(memo.get('confidence'))}",
            ]
            if action:
                memo_bits.append(action)
            elif thesis:
                memo_bits.append(thesis[0])
            parts.append("투자 메모: " + html.escape(" · ".join(memo_bits)))
        if report.is_priority_match:
            parts.append(
                "관심 일치: "
                + html.escape(
                    ", ".join(
                        report.priority_subject_matches
                        + report.priority_keyword_matches[:2]
                    )
                )
            )
        if report.summary_engine != "rule":
            parts.append(f"요약 엔진: {html.escape(report.summary_engine)}")
        parts.append(html.escape(summary))
        blocks.append("\n".join(parts))

    messages: list[str] = []
    current = ""
    for block in blocks:
        candidate = (current + "\n" + block).strip() if current else block
        if len(candidate) > 3500 and current:
            messages.append(current.strip())
            current = block.strip()
        else:
            current = candidate
    if current:
        messages.append(current.strip())

    return messages


def now_iso_string(timezone_name: str) -> str:
    return datetime.now(ZoneInfo(timezone_name)).replace(microsecond=0).isoformat()
