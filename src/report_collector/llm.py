from __future__ import annotations

from typing import Any
import json
import re

from report_collector.config import Settings
from report_collector.models import DailyDigest, Report
from report_collector.normalization import normalize_space, trim_text


SYSTEM_PROMPT = """
You are a Korean equity research digest editor and investment memo formatter.
Return JSON only.

Write concise Korean summaries and structured investment memos for sell-side research reports.
Focus on:
- the core thesis
- important numbers, estimates, or target-price changes when present
- what changed or why the report matters today
- catalysts, risks, and practical follow-up actions for an investor

Do not invent facts.
Do not use markdown.
""".strip()

INVESTMENT_MEMO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "string",
            "description": "A concise Korean summary in 2 to 3 sentences.",
        },
        "excerpt": {
            "type": "string",
            "description": "A one-sentence Korean preview under 110 characters.",
        },
        "investment_memo": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "stance": {
                    "type": "string",
                    "enum": ["positive", "neutral", "negative", "watch"],
                    "description": (
                        "Investment tone implied by the report. Use watch when the report "
                        "is informative but not directional."
                    ),
                },
                "thesis": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "One to three Korean bullet points for the core thesis.",
                    "maxItems": 3,
                },
                "catalysts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Zero to three Korean catalysts or events to watch.",
                    "maxItems": 3,
                },
                "risks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Zero to three Korean risk factors or blind spots.",
                    "maxItems": 3,
                },
                "numbers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Important figures exactly grounded in the report.",
                    "maxItems": 4,
                },
                "action": {
                    "type": "string",
                    "description": "A short Korean follow-up action for an investor.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Confidence that the memo captures the report without missing context.",
                },
            },
            "required": [
                "stance",
                "thesis",
                "catalysts",
                "risks",
                "numbers",
                "action",
                "confidence",
            ],
        },
    },
    "required": ["summary", "excerpt", "investment_memo"],
}


def _candidate_reports(digest: DailyDigest, settings: Settings) -> list[Report]:
    selected: list[Report] = []
    seen_ids: set[str] = set()

    for report in list(digest.must_read) + list(digest.reports):
        if report.report_id in seen_ids:
            continue
        if len(normalize_space(report.source_text)) < settings.openai_summary_min_chars:
            continue
        selected.append(report)
        seen_ids.add(report.report_id)
        if len(selected) >= settings.openai_summary_max_reports:
            break

    return selected


def _build_prompt(report: Report, settings: Settings) -> str:
    metadata_lines = [
        f"카테고리: {report.category_label}",
        f"종목/주제: {report.subject or '-'}",
        f"제목: {report.title}",
        f"증권사: {report.broker}",
        f"발행일: {report.published_date}",
        f"애널리스트: {report.analyst or '-'}",
        f"목표가: {report.target_price or '-'}",
        f"의견: {report.opinion or '-'}",
    ]
    if report.previous_target_price or report.previous_opinion or report.previous_analyst:
        metadata_lines.extend(
            [
                f"직전 리포트 날짜: {report.previous_report_date or '-'}",
                f"직전 목표가: {report.previous_target_price or '-'}",
                f"직전 의견: {report.previous_opinion or '-'}",
                f"직전 애널리스트: {report.previous_analyst or '-'}",
                f"감지된 변화: {', '.join(report.change_reasons) or '-'}",
            ]
        )
    content = trim_text(normalize_space(report.source_text), settings.openai_summary_char_limit)

    return "\n".join(
        [
            "아래 증권사 리포트를 읽고 JSON으로 요약과 투자 메모를 작성해 주세요.",
            "투자 메모는 원문에 있는 근거만 사용하고, 추정이 필요한 항목은 비워두거나 watch/low로 낮춰 주세요.",
            "",
            *metadata_lines,
            "",
            "본문:",
            content,
        ]
    )


def _parse_json_payload(raw_text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(parsed, dict):
        return None
    return parsed


def _clean_string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = normalize_space(str(item or ""))
        if not text:
            continue
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _clean_investment_memo(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    stance = normalize_space(str(value.get("stance") or "watch")).lower()
    if stance not in {"positive", "neutral", "negative", "watch"}:
        stance = "watch"

    confidence = normalize_space(str(value.get("confidence") or "low")).lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"

    memo = {
        "stance": stance,
        "thesis": _clean_string_list(value.get("thesis"), 3),
        "catalysts": _clean_string_list(value.get("catalysts"), 3),
        "risks": _clean_string_list(value.get("risks"), 3),
        "numbers": _clean_string_list(value.get("numbers"), 4),
        "action": normalize_space(str(value.get("action") or "")),
        "confidence": confidence,
    }

    if not any(
        memo[key]
        for key in ("thesis", "catalysts", "risks", "numbers", "action")
    ):
        return {}
    return memo


def _apply_summary(report: Report, payload: dict[str, Any]) -> bool:
    summary = normalize_space(str(payload.get("summary", "")))
    excerpt = normalize_space(str(payload.get("excerpt", "")))
    if not summary:
        return False

    report.summary = summary
    report.excerpt = excerpt or trim_text(summary, 110)
    report.summary_engine = "openai"
    report.investment_memo = _clean_investment_memo(payload.get("investment_memo"))
    return True


def enhance_digest_summaries(digest: DailyDigest, settings: Settings) -> int:
    digest.stats["llm_summary_reports"] = 0
    digest.stats["llm_investment_memo_reports"] = 0
    if not settings.openai_summary_enabled:
        return 0

    try:
        from openai import OpenAI
    except ImportError:
        return 0

    candidates = _candidate_reports(digest, settings)
    if not candidates:
        return 0

    client = OpenAI(api_key=settings.openai_api_key)
    enhanced = 0
    memo_enhanced = 0

    for report in candidates:
        request_kwargs: dict[str, Any] = {
            "model": settings.openai_model,
            "instructions": SYSTEM_PROMPT,
            "input": _build_prompt(report, settings),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "broker_report_investment_memo",
                    "strict": True,
                    "schema": INVESTMENT_MEMO_SCHEMA,
                }
            },
        }
        if settings.openai_reasoning_effort:
            request_kwargs["reasoning"] = {
                "effort": settings.openai_reasoning_effort,
            }

        try:
            response = client.responses.create(**request_kwargs)
        except Exception:
            continue

        payload = _parse_json_payload(getattr(response, "output_text", "") or "")
        if not payload:
            continue
        if _apply_summary(report, payload):
            enhanced += 1
            if report.investment_memo:
                memo_enhanced += 1

    digest.stats["llm_summary_reports"] = enhanced
    digest.stats["llm_investment_memo_reports"] = memo_enhanced
    return enhanced
