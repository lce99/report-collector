from __future__ import annotations

from argparse import ArgumentParser
import json
import os
from urllib.request import urlopen


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(
        description="Print Telegram chat IDs visible from a bot's recent updates.",
    )
    parser.add_argument(
        "--bot-token",
        default=os.getenv("TELEGRAM_BOT_TOKEN"),
        help="Telegram bot token. Defaults to TELEGRAM_BOT_TOKEN env var.",
    )
    return parser


def fetch_updates(bot_token: str) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    with urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def iter_chat_objects(update: dict) -> list[dict]:
    chats: list[dict] = []
    for field in ("message", "edited_message", "channel_post", "my_chat_member", "chat_member"):
        payload = update.get(field)
        if not isinstance(payload, dict):
            continue
        chat = payload.get("chat")
        if isinstance(chat, dict):
            chats.append(chat)
    return chats


def display_name(chat: dict) -> str:
    title = chat.get("title")
    if title:
        return str(title)

    parts = [
        chat.get("first_name", ""),
        chat.get("last_name", ""),
    ]
    full_name = " ".join(part for part in parts if part).strip()
    if full_name:
        return full_name

    username = chat.get("username")
    if username:
        return f"@{username}"

    return "(이름 없음)"


def main() -> int:
    parser = parse_args()
    args = parser.parse_args()

    if not args.bot_token:
        parser.error("--bot-token 또는 TELEGRAM_BOT_TOKEN 환경 변수가 필요합니다.")

    payload = fetch_updates(args.bot_token)
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram getUpdates failed: {payload}")

    unique_chats: dict[int, dict] = {}
    for update in payload.get("result", []):
        for chat in iter_chat_objects(update):
            chat_id = chat.get("id")
            if isinstance(chat_id, int):
                unique_chats[chat_id] = chat

    if not unique_chats:
        print("최근 업데이트에서 chat_id를 찾지 못했습니다.")
        print("1. 봇과 개인 채팅을 시작하거나")
        print("2. 받을 그룹에 봇을 초대한 뒤")
        print("3. 아무 메시지나 한 번 보낸 다음 다시 실행해 보세요.")
        return 0

    print("발견된 chat_id 목록")
    for chat_id, chat in sorted(unique_chats.items(), key=lambda item: item[0]):
        print(
            f"- chat_id={chat_id} | type={chat.get('type', 'unknown')} | "
            f"name={display_name(chat)}"
        )

    print("")
    print("원하는 chat_id를 GitHub Secret TELEGRAM_CHAT_ID에 넣으면 됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
