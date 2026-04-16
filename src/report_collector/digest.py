from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import html
import math
import re

from report_collector.config import Settings
from report_collector.models import DailyDigest, Report


CATEGORY_WEIGHTS = {
    "company": 3.2,
    "industry": 2.7,
    "invest": 2.5,
    "economy": 2.3,
    "market": 1.8,
    "debenture": 1.7,
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

RANKING_GROUPS = (
    ("company", "종목 랭킹", {"company"}),
    ("industry", "산업 랭킹", {"industry"}),
    ("macro", "매크로 랭킹", {"economy", "market", "debenture"}),
    ("strategy", "전략 랭킹", {"invest"}),
)

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


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _trim_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _split_sentences(text: str) -> list[str]:
    chunks: list[str] = []
    for line in re.split(r"[\r\n]+", text):
        line = _normalize_space(line)
        if not line:
            continue
        parts = SENTENCE_SPLIT_RE.split(line)
        for part in parts:
            sentence = _normalize_space(part)
            if not sentence:
                continue
            if sentence.isupper() and len(sentence) < 40:
                continue
            chunks.append(sentence)
    return chunks


def _build_summary(text: str, sentence_count: int, preview_limit: int) -> tuple[str, str]:
    sentences = _split_sentences(text)
    if not sentences:
        fallback = _trim_text(_normalize_space(text), preview_limit) or "본문 요약을 만들 수 없었습니다."
        return fallback, fallback

    summary = " ".join(sentences[:sentence_count]).strip()
    excerpt = _trim_text(" ".join(sentences[:2]).strip(), preview_limit)
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
    score = CATEGORY_WEIGHTS.get(report.category, 1.4)
    reasons: list[str] = [f"{report.category_label} 카테고리"]

    if report.priority_subject_matches:
        score += 4.0 + max(0.0, (len(report.priority_subject_matches) - 1) * 0.35)
        reasons.append(f"관심 종목({', '.join(report.priority_subject_matches[:3])})")

    if report.priority_keyword_matches:
        score += 2.4 + max(0.0, (len(report.priority_keyword_matches) - 1) * 0.2)
        reasons.append(f"관심 섹터/키워드({', '.join(report.priority_keyword_matches[:3])})")

    score += min(2.3, math.log10(max(report.views, 1)))
    if report.views >= 1000:
        reasons.append("조회수 상위권")

    if report.target_price:
        score += 0.7
        reasons.append("목표가 포함")
    if report.opinion:
        score += 0.6
        reasons.append("투자의견 포함")
    if report.analyst:
        score += 0.2

    broker_index = None
    for index, broker in enumerate(settings.broker_priority):
        if report.broker == broker:
            broker_index = index
            break
    if broker_index is not None:
        score += max(0.25, 1.2 - broker_index * 0.05)
        reasons.append("우선 추적 증권사")

    title_lower = report.title.lower()
    matched_keywords: list[str] = []
    for keyword, boost in TITLE_KEYWORD_BOOSTS.items():
        if keyword in title_lower or keyword in report.title:
            score += boost
            matched_keywords.append(keyword)
    if matched_keywords:
        reasons.append(f"핵심 키워드({', '.join(matched_keywords[:3])})")

    for keyword, penalty in TITLE_KEYWORD_PENALTIES.items():
        if keyword in title_lower or keyword in report.title:
            score += penalty

    text_length = _report_text_length(report)
    if text_length >= 2500:
        score += 0.95
        reasons.append("본문 정보량 풍부")
    elif text_length >= 1000:
        score += 0.55
    elif text_length >= 400:
        score += 0.25

    if report.has_pdf_text:
        score += 0.2

    return round(score, 2), reasons[:4]


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


def _select_must_read(reports: list[Report], limit: int) -> list[Report]:
    if not reports:
        return []

    grouped: dict[str, list[Report]] = defaultdict(list)
    for report in reports:
        grouped[report.category].append(report)

    selected: list[Report] = []
    seen_ids: set[str] = set()

    for category, quota in MUST_READ_QUOTAS:
        for report in grouped.get(category, [])[:quota]:
            if report.report_id in seen_ids or len(selected) >= limit:
                continue
            selected.append(report)
            seen_ids.add(report.report_id)

    if len(selected) < limit:
        for report in reports:
            if report.report_id in seen_ids:
                continue
            selected.append(report)
            seen_ids.add(report.report_id)
            if len(selected) >= limit:
                break

    return selected[:limit]


def _build_stats(reports: list[Report], keywords: list[str]) -> dict[str, object]:
    category_counts = Counter(report.category_label for report in reports)
    broker_counts = Counter(report.broker for report in reports)
    priority_count = sum(1 for report in reports if report.is_priority_match)
    pdf_text_count = sum(1 for report in reports if report.has_pdf_text)

    return {
        "total_reports": len(reports),
        "priority_match_reports": priority_count,
        "pdf_text_reports": pdf_text_count,
        "llm_summary_reports": 0,
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


def _build_editorial_note(reports: list[Report], must_read: list[Report]) -> str:
    if not reports:
        return "해당 일자에 수집된 리포트가 없습니다."

    category_counts = Counter(report.category_label for report in reports)
    broker_counts = Counter(report.broker for report in reports)

    busiest_category, category_count = category_counts.most_common(1)[0]
    active_brokers = ", ".join(broker for broker, _ in broker_counts.most_common(3))
    must_read_titles = ", ".join(report.display_title for report in must_read[:3])

    return (
        f"오늘은 {busiest_category} 리포트가 {category_count}건으로 가장 많았습니다. "
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


def enrich_and_build_digest(
    reports: list[Report],
    *,
    target_date: str,
    requested_date: str,
    generated_at: str,
    collection_note: str,
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
        _annotate_priority_matches(report, settings)
        report.score, report.score_reasons = _score_report(report, settings)

    reports.sort(key=lambda item: (-item.score, item.broker, item.title))
    selection_pool = reports
    if settings.priority_only:
        matched_reports = [report for report in reports if report.is_priority_match]
        if matched_reports:
            selection_pool = matched_reports

    must_read = _select_must_read(selection_pool, settings.must_read_limit)
    keywords = _extract_keywords(must_read or reports)
    stats = _build_stats(reports, keywords)
    priority_filters = _build_priority_filters(reports, must_read, settings)
    editorial_note = _build_editorial_note(reports, must_read)
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
        rankings=rankings,
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
        f"- 키워드: {', '.join(digest.keywords) if digest.keywords else '없음'}",
        "",
    ]

    if digest.collection_note:
        lines.extend(["## 수집 메모", digest.collection_note, ""])

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
                        f"- {index}. {report.display_title} | {report.broker} | 점수 {report.score:.2f}"
                    )
            lines.append("")

    lines.append("## 꼭 읽을 리포트")
    if not digest.must_read:
        lines.extend(["- 꼭 읽을 리포트로 선정된 항목이 없습니다.", ""])

    for index, report in enumerate(digest.must_read, start=1):
        reasons = ", ".join(report.score_reasons) if report.score_reasons else "자동 선정"
        lines.extend(
            [
                f"### {index}. [{report.category_label}] {report.display_title}",
                f"- 증권사: {report.broker}",
                f"- 발행일: {report.published_date}",
                f"- 점수: {report.score:.2f}",
                f"- 선정 이유: {reasons}",
                f"- 요약 엔진: {report.summary_engine}",
                (
                    "- 관심 필터 일치: "
                    f"종목 {', '.join(report.priority_subject_matches) or '없음'} / "
                    f"키워드 {', '.join(report.priority_keyword_matches) or '없음'}"
                )
                if report.is_priority_match
                else "- 관심 필터 일치: 없음",
                f"- 요약: {report.summary}",
                f"- 상세 링크: {report.detail_url}",
                f"- PDF: {report.pdf_url or '없음'}",
                "",
            ]
        )

    lines.extend(["## 전체 수집 결과", ""])
    for report in digest.reports:
        lines.append(
            f"- [{report.category_label}] {report.display_title} | {report.broker} | "
            f"{report.published_date} | 점수 {report.score:.2f} | {report.detail_url}"
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
    if digest.keywords:
        header.append(f"키워드: {html.escape(', '.join(digest.keywords[:6]))}")
    header.append("")
    header.append(html.escape(digest.editorial_note))

    blocks = ["\n".join(header)]

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
            f'<a href="{html.escape(top_report.detail_url)}">'
            f"{html.escape(top_report.display_title)}</a>"
        )
    if len(ranking_lines) > 2:
        blocks.append("\n".join(ranking_lines))

    for index, report in enumerate(digest.must_read[:max_reports], start=1):
        summary = _trim_text(report.summary, 180)
        parts = [
            "",
            f"<b>{index}. [{html.escape(report.category_label)}] "
            f'<a href="{html.escape(report.detail_url)}">'
            f"{html.escape(report.display_title)}</a></b>",
            f"{html.escape(report.broker)} | 점수 {report.score:.2f}",
        ]
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
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(timezone_name)).replace(microsecond=0).isoformat()
