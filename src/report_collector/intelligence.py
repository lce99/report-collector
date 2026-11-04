"""Compact public reading feed. Rules describe evidence, never investment advice.

Accept only the existing public digest, never private notes, settings or raw bodies.
No network calls or model/API calls are made by this module.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from hashlib import sha256
import math
import re
from typing import Any
from urllib.parse import quote, urlparse

RULE_VERSION = "daily-intelligence-v1"
SOURCE_HOSTS = {
    "naver_research": ("finance.naver.com", "stock.pstatic.net"),
    "mirae_asset_official": ("securities.miraeasset.com",),
    "korea_investment_official": ("securities.koreainvestment.com",),
    "shinhan_investment_official": ("bbs2.shinhansec.com", "www.shinhansec.com"),
}
CATEGORY_LABELS = {
    "company": "기업", "industry": "산업", "strategy": "시장·전략",
    "macro": "경제", "fixed_income": "채권", "other": "기타·미확인",
}
SECTOR_RULES = {
    "semiconductors": ("반도체", "HBM", "DRAM", "메모리", "SK하이닉스", "삼성전자"),
    "software": ("소프트웨어", "클라우드", "SNOW", "ADBE", "MDB"),
    "healthcare": ("바이오", "임상", "테라퓨틱", "치료제"),
    "energy": ("에너지", "정유", "유가", "원유"),
    "industrials": ("조선", "건설", "삼성E&A", "기계", "물류"),
    "defense_aerospace": ("방산", "항공우주", "디펜스"),
    "consumer": ("유통", "식품", "삼립", "소비"),
    "financials": ("은행", "보험", "증권업"),
    "batteries": ("배터리", "이차전지", "ESS"),
}
THEME_RULES = {
    "hbm": ("HBM",), "ai": ("AI", "인공지능", "에이전틱", "OpenAI"),
    "earnings": ("실적", "Preview", "Review", "컨센서스"),
    "rates": ("금리", "FOMC", "연준"), "china": ("중국", "China"),
    "clinical_data": ("임상", "초기 데이터"), "commodities": ("유가", "원유", "원자재"),
    "valuation": ("밸류에이션", "Valuation", "PBR", "PER"),
}
KEYWORD_SIGNALS = {
    "earnings_estimate_up", "earnings_estimate_down",
    "margin_estimate_up", "margin_estimate_down",
}


def _text(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def _canonical(report: dict[str, Any]) -> str:
    return ":".join(quote(_text(report.get(k), 160), safe="-_.") for k in ("source", "report_id"))


def _normalized(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.casefold())


def _link(value: Any, source: str) -> str | None:
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        parsed = urlparse(value)
        if (parsed.scheme not in ("http", "https") or parsed.username or parsed.password
                or parsed.hostname not in SOURCE_HOSTS.get(source, ())):
            return None
        if re.search(r"(?:^|[&?])(?:token|api_key|secret|password)=", parsed.query, re.I):
            return None
        return value
    except ValueError:
        return None


def _match(fields: dict[str, str], terms: tuple[str, ...]) -> dict[str, str] | None:
    for field, text in fields.items():
        for term in terms:
            pattern = re.escape(term)
            if term.isascii() and term.isalnum():
                pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
            found = re.search(pattern, text, re.I)
            if found:
                return {"field": field, "matched": found.group()}
    return None


def _classification(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = _text(report.get("title"))
    fields = {"title": title}
    upstream = _text(report.get("category"))
    category, confidence, reason = "other", "low", None
    ticker_match = re.search(r"\((?:\d{6}|[A-Z]{1,6}\s+(?:USA|US|HK))[^)]*\)", title)
    company_prefix = re.match(r"^([^;]{1,50});", title)
    if ticker_match:
        category, confidence = "company", "medium"
        reason = {"field": "title", "matched": ticker_match.group()}
    else:
        for candidate, terms in (
            ("fixed_income", ("Fixed Income", "채권", "크레딧", "Bond")),
            ("strategy", ("전략", "마켓", "Market", "브리핑", "한눈에 투데이", "시황")),
            ("macro", ("경제", "매크로", "Macro", "CPI", "FOMC")),
        ):
            reason = _match(fields, terms)
            if reason:
                category, confidence = candidate, "medium"
                break
        else:
            if company_prefix and upstream == "company":
                category, confidence = "company", "medium"
                reason = {"field": "title", "matched": company_prefix.group()}
            elif _match(fields, ("산업", "업종", "소프트웨어", "반도체", "배터리", "방산", "항공우주", "음식료")):
                category, confidence = "industry", "medium"
                reason = _match(fields, ("산업", "업종", "소프트웨어", "반도체", "배터리", "방산", "항공우주", "음식료"))
            else:
                category = {"company": "company", "industry": "industry", "economy": "macro",
                            "market": "strategy", "debenture": "fixed_income"}.get(upstream, "other")
                reason = {"field": "upstream_category", "matched": upstream or "unknown"}
    company_name = None
    if category == "company":
        if ticker_match:
            company_name = re.sub(r"^\[[^]]+\]\s*", "", title[:ticker_match.start()]).strip()
        elif company_prefix:
            company_name = company_prefix.group(1).strip()
    company = {
        "name": company_name or None,
        "ticker": _text(report.get("ticker"), 32) or None,
        "status": "title_candidate" if company_name else "unresolved",
    }
    return {
        "category": category, "label": CATEGORY_LABELS[category],
        "method": "deterministic_rules", "confidence": confidence,
        "reasons": [reason] if reason else [],
    }, company


def _tags(fields: dict[str, str], rules: dict[str, tuple[str, ...]]) -> list[dict[str, str]]:
    result = []
    for name, terms in rules.items():
        evidence = _match(fields, terms)
        if evidence:
            result.append({"name": name, **evidence})
    return result


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _revisions(report: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in report.get("estimate_revisions") or []:
        if not isinstance(item, dict):
            continue
        previous, current = item.get("previous_value"), item.get("current_value")
        if not (_numeric(previous) and _numeric(current)) or previous == current:
            continue
        result.append({
            "metric": _text(item.get("metric"), 40), "period": _text(item.get("period"), 40),
            "unit": _text(item.get("unit"), 20), "previous_value": previous,
            "current_value": current, "direction": "up" if current > previous else "down",
            "evidence_status": "collector_numeric_comparison_unverified",
        })
    return result[:8]


def _source_records(report: dict[str, Any]) -> list[dict[str, Any]]:
    result, seen = [], set()
    for item in [report, *(report.get("source_records") or [])]:
        if not isinstance(item, dict) or item.get("source") not in SOURCE_HOSTS or not item.get("report_id"):
            continue
        key = _canonical(item)
        if key in seen:
            continue
        seen.add(key)
        source = str(item["source"])
        result.append({
            "canonical_id": key, "source": source, "report_id": _text(item.get("report_id"), 160),
            "detail_url": _link(item.get("detail_url"), source),
            "pdf_url": _link(item.get("pdf_url"), source),
        })
    return result


def _report_link(report: dict[str, Any], key: str) -> str | None:
    # A preferred official report can inherit a public PDF from a duplicate source.
    # Validate against the recorded original source rather than rejecting that PDF.
    source = str(report["source"])
    value = report.get(key)
    safe = _link(value, source)
    if safe:
        return safe
    for record in report.get("source_records") or []:
        if isinstance(record, dict) and record.get(key) == value:
            safe = _link(value, str(record.get("source") or ""))
            if safe:
                return safe
    return None


def _row(report: dict[str, Any], requested_date: str) -> dict[str, Any]:
    source = str(report["source"])
    detail_url, pdf_url = (_report_link(report, k) for k in ("detail_url", "pdf_url"))
    content_sources = report.get("content_sources") or []
    pdf_text = bool(report.get("has_pdf_text") or "pdf" in content_sources)
    html_text = "html" in content_sources
    level = "pdf_excerpt" if pdf_text else "html_excerpt" if html_text else "title_only"
    classification, company = _classification(report)
    # An LLM can overwrite excerpt in the legacy pipeline: do not call it a source claim.
    excerpt = _text(report.get("excerpt"), 360) if (html_text or pdf_text) and report.get("summary_engine", "rule") == "rule" else ""
    fields = {"title": _text(report.get("title")), "excerpt": excerpt}
    revisions = _revisions(report)
    keywords = sorted(set(str(x) for x in report.get("estimate_signal_types") or [] if x in KEYWORD_SIGNALS))
    conflicts = any(f"{prefix}_up" in keywords and f"{prefix}_down" in keywords
                    for prefix in ("earnings_estimate", "margin_estimate"))
    errors = []
    for key, safe in (("detail_url", detail_url), ("pdf_url", pdf_url)):
        if report.get(key) and not safe:
            errors.append(f"{key}_rejected")
    if not (detail_url or pdf_url):
        errors.append("no_public_source_link")
    fresh = _text(report.get("published_date"), 10) == requested_date
    reasons = []
    def points(code: str, score: int) -> None:
        reasons.append({"code": code, "points": score})
    if fresh:
        points("published_on_requested_date", 2)
    if report.get("is_priority_match") or report.get("priority_subject_matches") or report.get("priority_keyword_matches"):
        points("configured_priority_match", 8)
    if revisions:
        points("numeric_comparison_available_for_review", 3)
    if pdf_url:
        points("pdf_link_available_for_selective_reading", 2)
    if html_text or pdf_text:
        points("collector_excerpt_available", 1)
    if level == "title_only":
        points("title_only_requires_source_reading", -2)
    if not (detail_url or pdf_url):
        points("missing_public_link", -10)
    duplicate_material = "|".join((_text(report.get("published_date"), 10),
                                   _normalized(_text(report.get("broker"))),
                                   _normalized(_text(report.get("title")))))
    return {
        "canonical_id": _canonical(report), "source": source,
        "report_id": _text(report.get("report_id"), 160), "broker": _text(report.get("broker"), 80),
        "title": fields["title"], "published_date": _text(report.get("published_date"), 10),
        "upstream_category": _text(report.get("category"), 40),
        "upstream_category_label": _text(report.get("category_label"), 80),
        "upstream_subject": _text(report.get("subject"), 100) or None,
        "company": company, "classification": classification,
        "sectors": _tags(fields, SECTOR_RULES), "themes": _tags(fields, THEME_RULES),
        "content_status": {
            "level": level, "pdf_link_available": bool(pdf_url), "pdf_text_extracted": pdf_text,
            "html_text_available": html_text, "fulltext_read": False,
            "extraction_error": "not_recorded",
        },
        "detail_url": detail_url, "pdf_url": pdf_url,
        "provenance": {
            "origin": "collector_public_metadata", "link_verification": "not_checked",
            "duplicate_group_id": "dg-" + sha256(duplicate_material.encode()).hexdigest()[:20],
            "source_records": _source_records(report),
            "source_records_complete": bool(report.get("source_records")),
        },
        "report_claims": {"excerpt": excerpt, "status": "author_claims_unverified" if excerpt else "unavailable"},
        "author_opinion": {"rating": _text(report.get("opinion"), 60) or None,
                           "target_price": _text(report.get("target_price"), 60) or None,
                           "status": "collector_attributed_author_opinion"},
        "signals": {"keyword_signals": keywords, "numeric_revisions": revisions,
                    "numeric_revision_status": "collector_numeric_comparison" if revisions else "none",
                    "conflicting_keyword_directions": conflicts},
        "read_priority": {
            "rank": 0, "score": sum(x["points"] for x in reasons), "reasons": reasons,
            "action": "selective_pdf_read" if pdf_url else "selective_detail_read" if detail_url else "metadata_review",
        },
        "errors": errors,
    }


def build_daily_intelligence(payload: dict[str, Any], *, shortlist_limit: int = 5) -> dict[str, Any]:
    """Derive sidecar from public payload; preserve legacy archive and upstream fields."""
    effective = _text(payload.get("date"), 10)
    requested = _text(payload.get("requested_date"), 10) or effective
    rows, excluded = {}, 0
    for report in payload.get("reports") or []:
        if not isinstance(report, dict) or report.get("source") not in SOURCE_HOSTS or not report.get("report_id"):
            excluded += 1
            continue
        key = _canonical(report)
        row = _row(report, requested)
        # Repeated canonical IDs contribute no extra rank/reading slots.
        if key not in rows or row["read_priority"]["score"] > rows[key]["read_priority"]["score"]:
            rows[key] = row
    reports = sorted(rows.values(), key=lambda x: (-x["read_priority"]["score"], x["canonical_id"]))
    shortlist, seen_groups, broker_counts = [], set(), Counter()
    for rank, report in enumerate(reports, 1):
        report["read_priority"]["rank"] = rank
        group = report["provenance"]["duplicate_group_id"]
        if (group not in seen_groups and (report["pdf_url"] or report["detail_url"])
                and len(shortlist) < max(0, shortlist_limit) and broker_counts[report["broker"]] < 2):
            shortlist.append(report["canonical_id"])
            seen_groups.add(group)
            broker_counts[report["broker"]] += 1
    # Fill remaining slots only when fewer issuers are available.
    for report in reports:
        group = report["provenance"]["duplicate_group_id"]
        if group not in seen_groups and (report["pdf_url"] or report["detail_url"]) and len(shortlist) < max(0, shortlist_limit):
            shortlist.append(report["canonical_id"])
            seen_groups.add(group)
    try:
        age = (date.fromisoformat(requested) - date.fromisoformat(effective)).days
        status = "current" if age == 0 else "fallback" if age > 0 else "future_date"
    except ValueError:
        age, status = None, "unknown"
    if not reports:
        status = "no_reports"
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    collector_health = []
    for item in stats.get("collector_health") or []:
        if not isinstance(item, dict) or item.get("source") not in SOURCE_HOSTS:
            continue
        health = item.get("status") if item.get("status") in ("ok", "empty", "failed") else "unknown"
        count = item.get("report_count")
        collector_health.append({"source": item["source"], "status": health,
                                 "report_count": count if isinstance(count, int) and count >= 0 else 0,
                                 "error_code": "collector_failed" if health == "failed" else None})
    levels = Counter(r["content_status"]["level"] for r in reports)
    return {
        "schema_version": 1, "rule_version": RULE_VERSION, "date": effective,
        "requested_date": requested, "generated_at": _text(payload.get("generated_at"), 80),
        "freshness": {"status": status, "effective_age_days": age},
        "counts": {
            "reports": len(reports), "excluded_reports": excluded,
            "pdf_links": sum(bool(r["pdf_url"]) for r in reports),
            "pdf_text_extracted": sum(r["content_status"]["pdf_text_extracted"] for r in reports),
            "html_text_available": sum(r["content_status"]["html_text_available"] for r in reports),
            "title_only": levels["title_only"], "duplicate_groups": len({r["provenance"]["duplicate_group_id"] for r in reports}),
            "numeric_revision_reports": sum(bool(r["signals"]["numeric_revisions"]) for r in reports),
        },
        "collector_health": collector_health, "shortlist": shortlist,
        "shortlist_policy": {"limit": max(0, shortlist_limit), "broker_soft_limit": 2,
                             "duplicate_group_limit": 1, "purpose": "reading_candidates"},
        "reports": reports,
    }
