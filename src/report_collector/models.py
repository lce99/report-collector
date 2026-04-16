from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    views: int = 0
    analyst: str | None = None
    target_price: str | None = None
    opinion: str | None = None
    body: str = ""
    pdf_text: str = ""
    excerpt: str = ""
    summary: str = ""
    summary_engine: str = "rule"
    score: float = 0.0
    score_reasons: list[str] = field(default_factory=list)
    priority_subject_matches: list[str] = field(default_factory=list)
    priority_keyword_matches: list[str] = field(default_factory=list)

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
            "subject": self.subject,
            "views": self.views,
            "analyst": self.analyst,
            "target_price": self.target_price,
            "opinion": self.opinion,
            "has_pdf_text": self.has_pdf_text,
            "content_sources": self.content_sources,
            "excerpt": self.excerpt,
            "summary": self.summary,
            "summary_engine": self.summary_engine,
            "score": self.score,
            "score_reasons": self.score_reasons,
            "priority_subject_matches": self.priority_subject_matches,
            "priority_keyword_matches": self.priority_keyword_matches,
            "is_priority_match": self.is_priority_match,
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
    rankings: dict[str, Any]
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
            "rankings": {
                key: {
                    "label": value.get("label"),
                    "reports": [
                        report.to_public_dict() for report in value.get("reports", [])
                    ],
                }
                for key, value in self.rankings.items()
            },
            "must_read": [report.to_public_dict() for report in self.must_read],
            "reports": [report.to_public_dict() for report in self.reports],
        }
