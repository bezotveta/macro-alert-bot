"""Источники данных экономического календаря. Без внешних зависимостей (только stdlib)."""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Бесплатный публичный фид Forex Factory. Ключ API не нужен.
# Неделя у Forex Factory начинается в воскресенье, поэтому одного фида
# thisweek хватает и для воскресного обзора недели вперёд.
# Адрес ff_calendar_nextweek.json источник отключил (отдаёт 404) — не запрашиваем.
FF_FEEDS = ("https://nfs.faireconomy.media/ff_calendar_thisweek.json",)
UA = "Mozilla/5.0 (compatible; macro-alert-bot/1.0)"

# С серверов GitHub фид часто отвечает 429 ("слишком много запросов":
# IP общий на всех пользователей). Лечится паузой и повтором.
RETRY_WAITS = (4, 12, 30)


@dataclass(frozen=True)
class Event:
    title: str
    currency: str
    dt: datetime  # всегда aware, в UTC
    impact: str = "High"
    forecast: str | None = None
    previous: str | None = None
    actual: str | None = None
    all_day: bool = False
    note: str = ""

    @property
    def uid(self) -> str:
        return f"{self.currency}|{self.title}|{self.dt.strftime('%Y-%m-%dT%H:%M')}"


def _http_json(url: str, timeout: int = 25, *, waits=RETRY_WAITS):
    """GET c повторами: 429 и ошибки сервера — не повод сдаваться сразу."""
    last = "неизвестная ошибка"
    for attempt in range(len(waits) + 1):
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            retriable = exc.code == 429 or 500 <= exc.code < 600
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            retriable = True
        if not retriable or attempt >= len(waits):
            break
        print(f"   {url}: {last}, повтор через {waits[attempt]} с", file=sys.stderr)
        time.sleep(waits[attempt])
    raise RuntimeError(last)


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_ff_rows(rows) -> list[Event]:
    out: list[Event] = []
    for row in rows or []:
        raw = _clean(row.get("date"))
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append(
            Event(
                title=_clean(row.get("title")) or "",
                currency=(_clean(row.get("country")) or "").upper(),
                dt=dt.astimezone(timezone.utc),
                impact=(_clean(row.get("impact")) or "Unknown").title(),
                forecast=_clean(row.get("forecast")),
                previous=_clean(row.get("previous")),
                actual=_clean(row.get("actual")),
                all_day=bool(row.get("allDay")),
            )
        )
    return out


def fetch_ff_rows(feeds=FF_FEEDS) -> list[dict]:
    """Сырые строки календаря — их удобно класть в кэш как есть."""
    rows: list[dict] = []
    errors: list[str] = []
    for url in feeds:
        try:
            data = _http_json(url)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            continue
        if isinstance(data, list):
            rows.extend(item for item in data if isinstance(item, dict))
    if not rows:
        raise RuntimeError(
            "Не удалось загрузить календарь -> " + "; ".join(errors or ["пустой ответ"])
        )
    return rows


def fetch_forexfactory(feeds=FF_FEEDS) -> list[Event]:
    return parse_ff_rows(fetch_ff_rows(feeds))


def load_static_calendar(path) -> list[Event]:
    """Свои события из JSON-файла (например, заседания ЦБ РФ)."""
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text("utf-8"))
    out: list[Event] = []
    for item in data.get("dates", []):
        try:
            dt = datetime.fromisoformat(item["date"])
        except (KeyError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append(
            Event(
                title=item.get("title") or data.get("title") or "Событие",
                currency=(item.get("currency") or data.get("currency") or "").upper(),
                dt=dt.astimezone(timezone.utc),
                impact=item.get("impact") or data.get("impact") or "High",
                forecast=_clean(item.get("forecast")),
                previous=_clean(item.get("previous")),
                note=item.get("note", ""),
            )
        )
    return out


def load_fixture(path) -> list[Event]:
    """Локальный JSON в формате Forex Factory — для офлайн-тестов."""
    return parse_ff_rows(json.loads(Path(path).read_text("utf-8")))


_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?")


def to_number(value):
    """'0.3%' -> 0.3 | '162K' -> 162000.0 | '-1.2%' -> -1.2 | None -> None"""
    if value is None:
        return None
    text = str(value).strip().replace(" ", "").replace(",", ".")
    m = _NUM_RE.match(text)
    if not m:
        return None
    num = float(m.group(0))
    tail = text[m.end():].upper()
    if tail.startswith("K"):
        num *= 1_000
    elif tail.startswith("M"):
        num *= 1_000_000
    elif tail.startswith("B"):
        num *= 1_000_000_000
    return num
