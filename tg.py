"""Минимальный клиент Telegram Bot API. Только стандартная библиотека Python."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.telegram.org/bot"
MAX_LEN = 3900  # лимит Telegram 4096, оставляем запас


def _split(text: str) -> list[str]:
    """Режет длинное сообщение по строкам, чтобы уложиться в лимит Telegram."""
    if len(text) <= MAX_LEN:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.split("\n"):
        if size + len(line) + 1 > MAX_LEN and buf:
            parts.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        parts.append("\n".join(buf))
    return parts


def _plain(text: str) -> str:
    for tag in ("<b>", "</b>", "<i>", "</i>", "<code>", "</code>"):
        text = text.replace(tag, "")
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


class Telegram:
    """dry=True — ничего не отправляет, печатает сообщения в консоль."""

    def __init__(self, token: str = "", chat_id: str = "", dry: bool = False) -> None:
        self.token = (token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = (chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
        self.dry = dry or not (self.token and self.chat_id)
        if dry is False and not (self.token and self.chat_id):
            print(
                "!! Нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — работаю в режиме печати в консоль",
                file=sys.stderr,
            )

    # ------------------------------------------------------------- транспорт
    def call(self, method: str, payload: dict, *, retries: int = 3) -> dict | None:
        data = {k: v for k, v in payload.items() if v is not None}
        url = API_BASE + self.token + "/" + method
        for attempt in range(1, retries + 1):
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
                with urllib.request.urlopen(req, timeout=25) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                low = body.lower()
                if "can't parse entities" in low and "parse_mode" in data:
                    data.pop("parse_mode")
                    data["text"] = _plain(str(data.get("text", "")))
                    continue
                if "query is too old" in low or "message is not modified" in low:
                    return None  # неважные ошибки, молчим
                print(f"!! Telegram {method} HTTP {exc.code}: {body}", file=sys.stderr)
                return None
            except Exception as exc:  # noqa: BLE001
                print(f"!! Telegram {method} ошибка ({attempt}/{retries}): {exc}", file=sys.stderr)
                time.sleep(2 * attempt)
        return None

    # --------------------------------------------------------------- методы
    def send(self, text: str, *, reply_markup: dict | None = None) -> bool:
        chunks = _split(text)
        if self.dry:
            for chunk in chunks:
                print("\n" + "=" * 64)
                print(_plain(chunk))
            if reply_markup:
                print("[кнопки: " + ", ".join(
                    btn["text"] for row in reply_markup.get("inline_keyboard", []) for btn in row
                ) + "]")
            return True

        ok = True
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            res = self.call("sendMessage", {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
                "reply_markup": json.dumps(reply_markup) if (reply_markup and last) else None,
            })
            ok = ok and bool(res)
        return ok

    def edit(self, message_id: int, text: str, *, reply_markup: dict | None = None) -> bool:
        if self.dry:
            print("\n[обновление сообщения]")
            print(_plain(text))
            return True
        res = self.call("editMessageText", {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
            "reply_markup": json.dumps(reply_markup) if reply_markup else None,
        })
        return bool(res)

    def answer(self, callback_id: str, text: str = "") -> None:
        if self.dry:
            return
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text}, retries=1)

    def get_updates(self, offset: int = 0, *, limit: int = 40) -> list[dict]:
        if self.dry:
            return []
        res = self.call("getUpdates", {
            "offset": offset or None,
            "limit": limit,
            "timeout": 0,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }, retries=2)
        if not res or not res.get("ok"):
            return []
        return res.get("result", [])
