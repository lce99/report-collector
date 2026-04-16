from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen
import re

from bs4 import BeautifulSoup

from report_collector.config import Settings
from report_collector.models import Report


@dataclass(frozen=True, slots=True)
class CategoryConfig:
    key: str
    label: str
    list_path: str
    detail_prefix: str
    subject_index: int | None
    title_index: int
    broker_index: int
    file_index: int
    date_index: int
    views_index: int
    minimum_cells: int


CATEGORY_CONFIGS: dict[str, CategoryConfig] = {
    "company": CategoryConfig(
        key="company",
        label="종목분석",
        list_path="company_list.naver",
        detail_prefix="company_read.naver",
        subject_index=0,
        title_index=1,
        broker_index=2,
        file_index=3,
        date_index=4,
        views_index=5,
        minimum_cells=6,
    ),
    "industry": CategoryConfig(
        key="industry",
        label="산업분석",
        list_path="industry_list.naver",
        detail_prefix="industry_read.naver",
        subject_index=0,
        title_index=1,
        broker_index=2,
        file_index=3,
        date_index=4,
        views_index=5,
        minimum_cells=6,
    ),
    "economy": CategoryConfig(
        key="economy",
        label="경제분석",
        list_path="economy_list.naver",
        detail_prefix="economy_read.naver",
        subject_index=None,
        title_index=0,
        broker_index=1,
        file_index=2,
        date_index=3,
        views_index=4,
        minimum_cells=5,
    ),
    "invest": CategoryConfig(
        key="invest",
        label="투자정보",
        list_path="invest_list.naver",
        detail_prefix="invest_read.naver",
        subject_index=None,
        title_index=0,
        broker_index=1,
        file_index=2,
        date_index=3,
        views_index=4,
        minimum_cells=5,
    ),
    "market": CategoryConfig(
        key="market",
        label="시황정보",
        list_path="market_info_list.naver",
        detail_prefix="market_info_read.naver",
        subject_index=None,
        title_index=0,
        broker_index=1,
        file_index=2,
        date_index=3,
        views_index=4,
        minimum_cells=5,
    ),
    "debenture": CategoryConfig(
        key="debenture",
        label="채권분석",
        list_path="debenture_list.naver",
        detail_prefix="debenture_read.naver",
        subject_index=None,
        title_index=0,
        broker_index=1,
        file_index=2,
        date_index=3,
        views_index=4,
        minimum_cells=5,
    ),
}


META_LABELS = {"목표가", "투자의견", "애널리스트"}
BODY_END_MARKERS = (
    "리서치 탐색기",
    "보고서의 내용은 투자판단",
    "증권홈",
)


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_short_date(value: str) -> date:
    cleaned = _normalize_space(value).replace(" ", "")
    parts = cleaned.split(".")
    if len(parts) != 3:
        raise ValueError(f"Unexpected date format: {value}")
    year = int(parts[0])
    if year < 100:
        year += 2000
    month = int(parts[1])
    day_value = int(parts[2])
    return date(year, month, day_value)


def _parse_int(value: str) -> int:
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else 0


def _clean_optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _normalize_space(value)
    if cleaned.lower() in {"없음", "-", "n/a", "na"}:
        return None
    return cleaned


class NaverResearchCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def collect(self, target_date: date) -> list[Report]:
        reports_by_id: dict[str, Report] = {}

        for category in self.settings.categories:
            config = CATEGORY_CONFIGS.get(category)
            if not config:
                continue

            for page in range(1, self.settings.page_depth + 1):
                list_url = urljoin(
                    self.settings.base_url,
                    f"{config.list_path}?page={page}",
                )
                rows = self._parse_list_page(list_url, config)
                if not rows:
                    break

                page_has_target_date = False
                page_all_older = True

                for report, row_date in rows:
                    if row_date == target_date:
                        page_has_target_date = True
                        page_all_older = False
                        reports_by_id.setdefault(report.report_id, report)
                    elif row_date > target_date:
                        page_all_older = False

                if not page_has_target_date and page_all_older:
                    break

        for report in reports_by_id.values():
            self._hydrate_detail(report)

        return sorted(
            reports_by_id.values(),
            key=lambda item: (item.category, item.broker, item.title),
        )

    def _fetch_html(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": self.settings.user_agent,
                "Referer": self.settings.base_url,
            },
        )
        with urlopen(
            request,
            timeout=self.settings.request_timeout_seconds,
        ) as response:
            return response.read().decode("euc-kr", errors="ignore")

    def _parse_list_page(
        self,
        url: str,
        config: CategoryConfig,
    ) -> list[tuple[Report, date]]:
        html = self._fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="type_1")
        if table is None:
            return []

        parsed: list[tuple[Report, date]] = []
        for row in table.find_all("tr"):
            columns = row.find_all("td")
            if len(columns) < config.minimum_cells:
                continue

            report = self._parse_list_row(columns, config)
            if report is None:
                continue

            row_date = date.fromisoformat(report.published_date)
            parsed.append((report, row_date))

        return parsed

    def _parse_list_row(
        self,
        columns: list,
        config: CategoryConfig,
    ) -> Report | None:
        title_cell = columns[config.title_index]
        detail_anchor = None
        for anchor in title_cell.find_all("a", href=True):
            href = anchor["href"]
            if config.detail_prefix in href:
                detail_anchor = anchor
                break
        if detail_anchor is None:
            return None

        detail_url = urljoin(self.settings.base_url, detail_anchor["href"])
        report_id = parse_qs(urlparse(detail_url).query).get("nid", [""])[0]
        if not report_id:
            return None

        subject = None
        if config.subject_index is not None:
            subject = _normalize_space(columns[config.subject_index].get_text(" ", strip=True))

        pdf_anchor = columns[config.file_index].find("a", href=True)
        pdf_url = urljoin(self.settings.base_url, pdf_anchor["href"]) if pdf_anchor else None

        published_date = _parse_short_date(
            columns[config.date_index].get_text(" ", strip=True)
        ).isoformat()

        return Report(
            source="naver_research",
            category=config.key,
            category_label=config.label,
            report_id=report_id,
            title=_normalize_space(detail_anchor.get_text(" ", strip=True)),
            broker=_normalize_space(columns[config.broker_index].get_text(" ", strip=True)),
            published_date=published_date,
            detail_url=detail_url,
            pdf_url=pdf_url,
            subject=subject or None,
            views=_parse_int(columns[config.views_index].get_text(" ", strip=True)),
        )

    def _hydrate_detail(self, report: Report) -> None:
        try:
            html = self._fetch_html(report.detail_url)
        except Exception:
            return

        soup = BeautifulSoup(html, "html.parser")
        main_table = self._find_main_table(soup.find_all("table"))
        if main_table is None:
            return

        lines = [
            _normalize_space(line)
            for line in main_table.get_text("\n", strip=True).splitlines()
        ]
        lines = [line for line in lines if line and line != "|"]

        report.target_price = self._value_after(lines, "목표가")
        report.opinion = self._value_after(lines, "투자의견")
        report.analyst = self._value_after(lines, "애널리스트")

        detail_views = next(
            (line for line in lines if line.startswith("조회")),
            None,
        )
        if detail_views:
            report.views = max(report.views, _parse_int(detail_views))

        report.body = self._extract_body(lines)

    def _find_main_table(self, tables: Iterable) -> BeautifulSoup | None:
        for table in tables:
            table_text = table.get_text(" ", strip=True)
            if "리포트 본문" in table_text:
                return table
        return None

    def _value_after(self, lines: list[str], label: str) -> str | None:
        for index, value in enumerate(lines):
            if value == label and index + 1 < len(lines):
                return _clean_optional_value(lines[index + 1])
        return None

    def _extract_body(self, lines: list[str]) -> str:
        body_start = 0
        for index, value in enumerate(lines):
            if value.startswith("조회"):
                body_start = index + 1
                break

        while body_start < len(lines):
            current = lines[body_start]
            if current in META_LABELS:
                body_start += 2
                continue
            if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", current):
                body_start += 1
                continue
            break

        body_lines: list[str] = []
        for line in lines[body_start:]:
            lowered = line.lower()
            if lowered.endswith(".pdf"):
                break
            if any(marker in line for marker in BODY_END_MARKERS):
                break
            body_lines.append(line)

        return "\n".join(body_lines).strip()
