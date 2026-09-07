"""Источники данных экономического календаря. Без внешних зависимостей (только stdlib)."""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Бесплатный публичный фид Forex Factory. Ключ API не нужен.
FF_FEEDS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
)
UA = "Mozilla/5.0 (compatible; macro-alert-bot/1.0)"


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


def _http_json(url: str, timeout: int = 25):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


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


def fetch_forexfactory(feeds=FF_FEEDS) -> list[Event]:
    events: list[Event] = []
    errors: list[str] = []
    for url in feeds:
        try:
            events.extend(parse_ff_rows(_http_json(url)))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    if not events and errors:
        raise RuntimeError("Не удалось загрузить календарь -> " + "; ".join(errors))
    return events


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
