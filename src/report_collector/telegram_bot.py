from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import html
import json
import time

from report_collector.normalization import normalize_subject_key


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _trim(value: str, limit: int = 180) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _send_message(bot_token: str, chat_id: str, message: str) -> None:
    payload = urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = Request(
        url=f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {data}")


def send_messages(bot_token: str, chat_id: str, messages: list[str]) -> None:
    for message in messages:
        _send_message(bot_token, chat_id, message)


def _latest_digest(docs_root: Path) -> dict:
    return _load_json(docs_root / "data" / "latest.json") or {}


def _subject_index(docs_root: Path) -> dict:
    return _load_json(docs_root / "data" / "subjects" / "index.json") or {}


def _subject_detail(docs_root: Path, subject_key: str) -> dict:
    return _load_json(docs_root / "data" / "subjects" / f"{subject_key}.json") or {}


def _find_subject_key(docs_root: Path, query: str) -> tuple[str, str] | None:
    cleaned = query.strip()
    if not cleaned:
        return None
    wanted_key = normalize_subject_key(cleaned)
    subjects = _subject_index(docs_root).get("subjects", [])
    if not isinstance(subjects, list):
        return None

    fallback: tuple[str, str] | None = None
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        name = str(subject.get("subject_name") or "")
        key = str(subject.get("subject_key") or "")
        if not key:
            continue
        if key == wanted_key or name == cleaned:
            return key, name
        if cleaned.lower() in name.lower() or (wanted_key and wanted_key in key):
            fallback = fallback or (key, name)
    return fallback


def _format_report_line(report: dict, index: int | None = None) -> str:
    prefix = f"{index}. " if index is not None else "• "
    title = html.escape(str(report.get("display_title") or report.get("title") or "제목 없음"))
    broker = html.escape(str(report.get("broker") or "-"))
    score = report.get("score")
    score_text = f" · 점수 {float(score):.2f}" if isinstance(score, (int, float)) else ""
    url = html.escape(str(report.get("detail_url") or ""))
    if url:
        return f'{prefix}<a href="{url}">{title}</a>\n   {broker}{score_text}'
    return f"{prefix}{title}\n   {broker}{score_text}"


def _format_today(docs_root: Path) -> str:
    digest = _latest_digest(docs_root)
    if not digest:
        return "저장된 최신 digest가 없습니다."
    lines = [
        f"<b>{html.escape(str(digest.get('date') or '-'))} 데일리 리포트</b>",
        html.escape(str(digest.get("editorial_note") or "")),
        "",
        "<b>필독 후보</b>",
    ]
    for index, report in enumerate((digest.get("must_read") or [])[:6], start=1):
        if isinstance(report, dict):
            lines.append(_format_report_line(report, index))
    return "\n".join(line for line in lines if line is not None)


def _format_changes(docs_root: Path) -> str:
    digest = _latest_digest(docs_root)
    changes = [item for item in digest.get("changes", []) if isinstance(item, dict)]
    if not changes:
        return "최근 digest에는 변화 감지 리포트가 없습니다."
    lines = [f"<b>{html.escape(str(digest.get('date') or '-'))} 변화 감지</b>"]
    for index, report in enumerate(changes[:8], start=1):
        reasons = " · ".join(str(item) for item in report.get("change_reasons", [])[:3])
        lines.append(_format_report_line(report, index))
        if reasons:
            lines.append(f"   {html.escape(reasons)}")
    return "\n".join(lines)


def _format_source(docs_root: Path) -> str:
    digest = _latest_digest(docs_root)
    stats = digest.get("stats") if isinstance(digest.get("stats"), dict) else {}
    health = [item for item in stats.get("collector_health", []) if isinstance(item, dict)]
    alerts = [item for item in stats.get("collector_alerts", []) if isinstance(item, dict)]
    if not health:
        return "최신 digest에 소스 상태 정보가 없습니다."
    lines = [f"<b>{html.escape(str(digest.get('date') or '-'))} 소스 상태</b>"]
    if alerts:
        lines.append("<b>운영 알림</b>")
        for alert in alerts[:5]:
            lines.append(f"• {html.escape(str(alert.get('title') or '-'))}: {html.escape(_trim(str(alert.get('message') or ''), 120))}")
    lines.append("<b>수집기</b>")
    for item in health:
        lines.append(
            "• "
            f"{html.escape(str(item.get('label') or item.get('source') or '-'))}: "
            f"{html.escape(str(item.get('status') or '-'))} · "
            f"{html.escape(str(item.get('report_count') or 0))}건"
        )
    return "\n".join(lines)


def _format_watchlist(docs_root: Path) -> str:
    digest = _latest_digest(docs_root)
    priority = digest.get("priority_filters") if isinstance(digest.get("priority_filters"), dict) else {}
    reports = [
        report
        for report in digest.get("reports", [])
        if isinstance(report, dict) and report.get("is_priority_match")
    ]
    lines = [
        f"<b>{html.escape(str(digest.get('date') or '-'))} 관심 필터</b>",
        f"종목: {html.escape(', '.join(priority.get('subjects') or []) or '없음')}",
        f"키워드: {html.escape(', '.join(priority.get('keywords') or []) or '없음')}",
        f"일치 리포트: {len(reports)}건",
        "",
        "<b>상위 일치 리포트</b>",
    ]
    for index, report in enumerate(reports[:6], start=1):
        lines.append(_format_report_line(report, index))
    return "\n".join(lines)


def _format_subject(docs_root: Path, query: str) -> str:
    matched = _find_subject_key(docs_root, query)
    if not matched:
        return f"'{html.escape(query)}' 종목 히스토리를 찾지 못했습니다."
    subject_key, subject_name = matched
    detail = _subject_detail(docs_root, subject_key)
    if not detail:
        return f"'{html.escape(subject_name)}' 종목 JSON을 읽지 못했습니다."

    target = detail.get("target_summary") if isinstance(detail.get("target_summary"), dict) else {}
    timeline = [item for item in detail.get("broker_timeline", []) if isinstance(item, dict)]
    latest = [item for item in detail.get("latest_by_broker", []) if isinstance(item, dict)]
    lines = [
        f"<b>{html.escape(str(detail.get('subject_name') or subject_name))} 히스토리</b>",
        f"최근 업데이트: {html.escape(str(detail.get('latest_report_date') or '-'))}",
        f"누적 {detail.get('report_count') or 0}건 · 활동 증권사 {detail.get('active_broker_count') or 0}곳",
        f"평균 목표가 {target.get('avg') or '-'} · 최고 {target.get('high') or '-'} · 최저 {target.get('low') or '-'}",
        "",
        "<b>최근 2주 브로커 타임라인</b>",
    ]
    for item in timeline[-8:]:
        lines.append(
            "• "
            f"{html.escape(str(item.get('date') or '-'))} "
            f"{html.escape(str(item.get('broker') or '-'))}: "
            f"{html.escape(_trim(str(item.get('title') or '-'), 80))}"
        )
    lines.append("")
    lines.append("<b>증권사별 최신 시각</b>")
    for report in latest[:5]:
        lines.append(_format_report_line(report))
    return "\n".join(lines)


def render_command_response(command_text: str, docs_root: Path | str = "docs") -> str:
    docs_path = Path(docs_root)
    text = command_text.strip()
    command, _, rest = text.partition(" ")
    command = command.lower()
    if command == "/today":
        return _format_today(docs_path)
    if command == "/changes":
        return _format_changes(docs_path)
    if command == "/source":
        return _format_source(docs_path)
    if command == "/watchlist":
        return _format_watchlist(docs_path)
    if command == "/subject":
        if not rest.strip():
            return "사용법: /subject 삼성전자"
        return _format_subject(docs_path, rest)
    return (
        "<b>지원 명령어</b>\n"
        "/today\n/changes\n/subject 삼성전자\n/source\n/watchlist"
    )


def _telegram_api_get(bot_token: str, method: str, params: dict[str, object]) -> dict:
    query = urlencode(params)
    with urlopen(f"https://api.telegram.org/bot{bot_token}/{method}?{query}", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {payload}")
    return payload


def process_command_updates(
    bot_token: str,
    *,
    docs_root: Path | str = "docs",
    allowed_chat_id: str | None = None,
    state_path: Path | str | None = None,
    timeout: int = 0,
) -> int:
    state_file = Path(state_path) if state_path else Path(docs_root) / "data" / "telegram_command_state.json"
    state = _load_json(state_file) or {}
    offset = int(state.get("offset") or 0) or None
    params: dict[str, object] = {
        "timeout": timeout,
        "allowed_updates": json.dumps(["message"]),
    }
    if offset is not None:
        params["offset"] = offset
    payload = _telegram_api_get(bot_token, "getUpdates", params)
    processed = 0
    next_offset = offset or 0
    for update in payload.get("result", []):
        if not isinstance(update, dict):
            continue
        update_id = int(update.get("update_id") or 0)
        next_offset = max(next_offset, update_id + 1)
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        chat_id = str(chat.get("id") or "")
        if allowed_chat_id and chat_id != str(allowed_chat_id):
            continue
        text = str(message.get("text") or "").strip()
        if not text.startswith("/"):
            continue
        response = render_command_response(text, docs_root)
        _send_message(bot_token, chat_id, response)
        processed += 1

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"offset": next_offset, "updated_at": int(time.time())}), encoding="utf-8")
    return processed
