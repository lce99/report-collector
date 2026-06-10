from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass(slots=True)
class Report:
    source: str
    category: str
    category_label: str
    report_id: str
    title: str
    broker: str
    published_date: str
    detail_url: str
    pdf_url: str | None = None
    subject: str | None = None
    subject_key: str | None = None
    ticker: str | None = None
    views: int = 0
    analyst: str | None = None
    target_price: str | None = None
    target_price_value: int | None = None
    opinion: str | None = None
    opinion_normalized: str | None = None
    body: str = ""
    pdf_text: str = ""
    excerpt: str = ""
    summary: str = ""
    summary_engine: str = "rule"
    investment_memo: dict[str, Any] = field(default_factory=dict)
    estimate_metrics: list[dict[str, Any]] = field(default_factory=list)
    estimate_signal_types: list[str] = field(default_factory=list)
    estimate_reasons: list[str] = field(default_factory=list)
    estimate_revisions: list[dict[str, Any]] = field(default_factory=list)
    stance: str = "neutral"
    score: float = 0.0
    score_reasons: list[str] = field(default_factory=list)
    score_breakdown: list[dict[str, Any]] = field(default_factory=list)
    priority_subject_matches: list[str] = field(default_factory=list)
    priority_keyword_matches: list[str] = field(default_factory=list)
    previous_report_date: str | None = None
    previous_target_price: str | None = None
    previous_opinion: str | None = None
    previous_analyst: str | None = None
    target_price_change: str | None = None
    target_price_change_pct: float | None = None
    opinion_changed: bool = False
    opinion_change_direction: str | None = None
    analyst_changed: bool = False
    coverage_initiated: bool = False
    change_types: list[str] = field(default_factory=list)
    change_reasons: list[str] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        if self.subject:
            return f"{self.subject} - {self.title}"
        return self.title

    @property
    def is_priority_match(self) -> bool:
        return bool(self.priority_subject_matches or self.priority_keyword_matches)

    @property
    def has_pdf_text(self) -> bool:
        return bool(self.pdf_text)

    @property
    def has_change_signal(self) -> bool:
        return bool(
            self.change_reasons
            or self.change_types
            or self.estimate_reasons
            or self.estimate_signal_types
            or self.estimate_revisions
        )

    @property
    def primary_url(self) -> str:
        return self.pdf_url or self.detail_url

    @property
    def primary_url_label(self) -> str:
        return "PDF" if self.pdf_url else "상세"

    @property
    def link_health(self) -> dict[str, Any]:
        primary_kind = "pdf" if self.pdf_url else "detail"
        detail_host = urlparse(self.detail_url).netloc if self.detail_url else ""
        pdf_host = urlparse(self.pdf_url).netloc if self.pdf_url else ""
        if self.pdf_url:
            status = "pdf_preferred"
            note = "PDF 링크를 대표 링크로 사용합니다."
        elif self.detail_url:
            status = "detail_only"
            note = "상세 페이지 링크만 확보됐습니다."
        else:
            status = "missing"
            note = "사용 가능한 링크가 없습니다."

        return {
            "status": status,
            "primary_kind": primary_kind,
            "has_pdf": bool(self.pdf_url),
            "has_detail": bool(self.detail_url),
            "detail_host": detail_host,
            "pdf_host": pdf_host,
            "note": note,
        }

    @property
    def content_sources(self) -> list[str]:
        sources: list[str] = []
        if self.body:
            sources.append("html")
        if self.pdf_text:
            sources.append("pdf")
        return sources

    @property
    def source_text(self) -> str:
        if self.body and self.pdf_text:
            return f"{self.body}\n{self.pdf_text}"
        return self.body or self.pdf_text

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "category": self.category,
            "category_label": self.category_label,
            "report_id": self.report_id,
            "title": self.title,
            "display_title": self.display_title,
            "broker": self.broker,
            "published_date": self.published_date,
            "detail_url": self.detail_url,
            "pdf_url": self.pdf_url,
            "primary_url": self.primary_url,
            "primary_url_label": self.primary_url_label,
            "subject": self.subject,
            "subject_key": self.subject_key,
            "ticker": self.ticker,
            "views": self.views,
            "analyst": self.analyst,
            "target_price": self.target_price,
            "target_price_value": self.target_price_value,
            "opinion": self.opinion,
            "opinion_normalized": self.opinion_normalized,
            "has_pdf_text": self.has_pdf_text,
            "content_sources": self.content_sources,
            "excerpt": self.excerpt,
            "summary": self.summary,
            "summary_engine": self.summary_engine,
            "investment_memo": self.investment_memo,
            "estimate_metrics": self.estimate_metrics,
            "estimate_signal_types": self.estimate_signal_types,
            "estimate_reasons": self.estimate_reasons,
            "estimate_revisions": self.estimate_revisions,
            "stance": self.stance,
            "score": self.score,
            "score_reasons": self.score_reasons,
            "score_breakdown": self.score_breakdown,
            "link_health": self.link_health,
            "priority_subject_matches": self.priority_subject_matches,
            "priority_keyword_matches": self.priority_keyword_matches,
            "is_priority_match": self.is_priority_match,
            "previous_report_date": self.previous_report_date,
            "previous_target_price": self.previous_target_price,
            "previous_opinion": self.previous_opinion,
            "previous_analyst": self.previous_analyst,
            "target_price_change": self.target_price_change,
            "target_price_change_pct": self.target_price_change_pct,
            "opinion_changed": self.opinion_changed,
            "opinion_change_direction": self.opinion_change_direction,
            "analyst_changed": self.analyst_changed,
            "coverage_initiated": self.coverage_initiated,
            "change_types": self.change_types,
            "change_reasons": self.change_reasons,
            "has_change_signal": self.has_change_signal,
        }


@dataclass(slots=True)
class DailyDigest:
    date: str
    requested_date: str
    generated_at: str
    collection_note: str
    dashboard_url: str | None
    editorial_note: str
    keywords: list[str]
    priority_filters: dict[str, Any]
    stats: dict[str, Any]
    change_summary: dict[str, Any]
    rankings: dict[str, Any]
    changes: list[Report]
    must_read: list[Report]
    reports: list[Report]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "requested_date": self.requested_date,
            "generated_at": self.generated_at,
            "collection_note": self.collection_note,
            "dashboard_url": self.dashboard_url,
            "editorial_note": self.editorial_note,
            "keywords": self.keywords,
            "priority_filters": self.priority_filters,
            "stats": self.stats,
            "change_summary": self.change_summary,
            "rankings": {
                key: {
                    "label": value.get("label"),
                    "reports": [
                        report.to_public_dict() for report in value.get("reports", [])
                    ],
                }
                for key, value in self.rankings.items()
            },
            "changes": [report.to_public_dict() for report in self.changes],
            "must_read": [report.to_public_dict() for report in self.must_read],
            "reports": [report.to_public_dict() for report in self.reports],
        }
