from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs
from urllib.parse import urljoin
from urllib.parse import urlparse
import re

from report_collector.config import Settings
from report_collector.models import Report
from report_collector.sources.common import (
    category_label,
    fetch_soup,
    infer_category,
    normalize_space,
    split_text_lines,
)


BASE_URL = "https://securities.koreainvestment.com"
MAIN_URL = BASE_URL + "/main/Main.jsp"
DETAIL_TEMPLATE = BASE_URL + "/main/research/research/StrategyDetail.jsp?jkGubun=6&id={report_id}"
BROKER_NAME = "한국투자증권"
DETAIL_STOP_MARKERS = {
    "관련리포트",
    "관련키워드",
    "원문보기",
    "목록",
    "이전글",
    "다음글",
}


def _parse_detail_id(detail_url: str) -> str | None:
    report_id = parse_qs(urlparse(detail_url).query).get("id", [""])[0]
    return report_id or None


def _clean_subject(subject_line: str) -> tuple[str | None, str | None]:
    subject_line = normalize_space(subject_line)
    if not subject_line:
        return None, None
    if subject_line.endswith("기업분석"):
        return normalize_space(subject_line.removesuffix("기업분석")), "company"
    if subject_line.endswith("산업분석"):
        return normalize_space(subject_line.removesuffix("산업분석")), "industry"
    return subject_line, None


class KoreaInvestmentCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def collect(self, target_date: date) -> list[Report]:
        queue = self._load_seed_ids()
        seen_ids: set[str] = set()
        reports_by_id: dict[str, Report] = {}
        max_items = max(12, self.settings.page_depth * 12)

        while queue and len(seen_ids) < max_items:
            current_id = queue.pop(0)
            if current_id in seen_ids:
                continue
            seen_ids.add(current_id)

            hydrated = self._fetch_detail_report(current_id)
            if hydrated is None:
                continue
            report, related_ids = hydrated

            report_date = date.fromisoformat(report.published_date)
            if report_date == target_date:
                reports_by_id.setdefault(report.report_id, report)

            if report_date >= target_date:
                for related_id in related_ids:
                    if related_id not in seen_ids and related_id not in queue:
                        queue.append(related_id)

        return sorted(
            reports_by_id.values(),
            key=lambda item: (item.category, item.published_date, item.display_title),
        )

    def _load_seed_ids(self) -> list[str]:
        soup = fetch_soup(MAIN_URL, settings=self.settings, encoding="utf-8")
        seed_ids: list[str] = []
        for anchor in soup.select("a[href*='StrategyDetail.jsp']"):
            detail_url = urljoin(BASE_URL, anchor.get("href", ""))
            report_id = _parse_detail_id(detail_url)
            if not report_id or report_id in seed_ids:
                continue
            seed_ids.append(report_id)
        return seed_ids

    def _fetch_detail_report(self, report_id: str) -> tuple[Report, list[str]] | None:
        detail_url = DETAIL_TEMPLATE.format(report_id=report_id)
        try:
            soup = fetch_soup(
                detail_url,
                settings=self.settings,
                encoding="utf-8",
                referer=MAIN_URL,
            )
        except Exception:
            return None

        lines = split_text_lines(soup)
        date_index = next(
            (
                index
                for index, line in enumerate(lines)
                if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", line)
            ),
            -1,
        )
        if date_index < 3:
            return None

        subject_line = lines[date_index - 3]
        title_line = lines[date_index - 2]
        analyst_line = lines[date_index - 1]
        published_date = date.fromisoformat(lines[date_index].replace(".", "-")).isoformat()

        subject, fixed_category = _clean_subject(subject_line)
        body_start = date_index + 1
        if body_start < len(lines) and lines[body_start] in {"오늘의 차트"}:
            body_start += 1

        body_end = len(lines)
        for index in range(body_start, len(lines)):
            if lines[index] in DETAIL_STOP_MARKERS:
                body_end = index
                break

        body = "\n".join(lines[body_start:body_end]).strip()
        category = fixed_category or infer_category(
            title_line,
            subject=subject,
            body=body,
        )

        report = Report(
            source="korea_investment_official",
            category=category,
            category_label=category_label(category),
            report_id=f"kis-{report_id}",
            title=title_line,
            broker=BROKER_NAME,
            published_date=published_date,
            detail_url=detail_url,
            pdf_url=None,
            subject=subject if subject and subject not in title_line else None,
            analyst=analyst_line or None,
            body=body,
        )

        related_ids: list[str] = []
        for anchor in soup.select("#content a[onclick]"):
            onclick = anchor.get("onclick", "")
            match = re.search(r"doDetail\('(\d+)'\)", onclick)
            if not match:
                continue
            related_id = match.group(1)
            if related_id != report_id and related_id not in related_ids:
                related_ids.append(related_id)

        return report, related_ids
