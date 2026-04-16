from __future__ import annotations

from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json


def send_messages(bot_token: str, chat_id: str, messages: list[str]) -> None:
    for message in messages:
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

