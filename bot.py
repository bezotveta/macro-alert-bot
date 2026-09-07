#!/usr/bin/env python3
"""Macro Alert Bot — Telegram-уведомления ТОЛЬКО по крупным макрособытиям.

Что умеет:
  1. Утренний дайджест: что сегодня выходит, с расшифровкой каждого показателя.
  2. Напоминание за 30 и за 5 минут до события.
  3. Факт после выхода данных: цифра, сравнение с прогнозом и трактовка.
  4. Воскресный обзор недели.
  5. Команды в Telegram: /menu, /off, /on, /power, /glossary и другие (см. commands.py).

Запуск:
  python bot.py --once            # один проход (для cron / GitHub Actions)
  python bot.py --loop            # бесконечный цикл, проверка раз в минуту
  python bot.py --test            # офлайн-прогон на тестовых данных, без отправки
  python bot.py --demo            # показать меню, список событий и словарь
  python bot.py --once --dry-run  # реальные данные, печать в консоль вместо Telegram

Зависимости: только стандартная библиотека Python 3.11+.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import commands
import filters
import formatter
import providers
from tg import Telegram

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = Path(os.environ.get("STATE_PATH", ROOT / "state.json"))


# ---------------------------------------------------------------- config/state
def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text("utf-8")) if CONFIG_PATH.exists() else {}
    cfg.setdefault("timezone", "Europe/Kyiv")
    cfg.setdefault("min_power", 2)
    cfg.setdefault("lead_minutes", [30, 5])
    cfg.setdefault("tolerance_minutes", 8)
    cfg.setdefault("send_results", True)
    cfg.setdefault("daily_digest_at", "09:00")
    cfg.setdefault("weekly_preview", {"weekday": 6, "at": "18:00"})
    cfg.setdefault("enable_commands", True)
    cfg.setdefault("include_adp", False)
    cfg.setdefault("disabled_rules", [])
    cfg.setdefault("static_calendars", ["cbr_dates.json"])
    cfg.setdefault("calendar_cache_minutes", 10)
    return cfg


def load_state(path: Path = STATE_PATH) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            pass
    return {"sent": {}, "digest": "", "weekly": "", "tg_offset": 0}


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    state["sent"] = {
        uid: stages
        for uid, stages in state.get("sent", {}).items()
        if uid.rsplit("|", 1)[-1][:10] >= cutoff
    }
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")


# ------------------------------------------------------------------------ данные
def _cache_ttl(cfg: dict, rows, now: datetime) -> int:
    """Обычно календарь можно не трогать 10 минут, но рядом с релизом нужна свежесть."""
    for event in providers.parse_ff_rows(rows):
        if abs((event.dt - now).total_seconds()) <= 25 * 60:
            return 1
    return max(1, int(cfg.get("calendar_cache_minutes", 10)))


def fetch_calendar_rows(cfg: dict, state: dict, now: datetime) -> list[dict]:
    """Календарь из сети или из кэша в state.json. Никогда не бросает исключение.

    Фид Forex Factory отвечает 429, если его дёргать часто с одного IP (а у
    серверов GitHub он общий на всех). Поэтому свежую копию держим в
    состоянии и переспрашиваем источник не чаще, чем нужно.
    """
    cache = state.setdefault("calendar", {})
    rows = cache.get("rows") or []
    fetched_at = cache.get("fetched_at")
    age_min = None
    if fetched_at:
        try:
            age_min = (now - datetime.fromisoformat(fetched_at)).total_seconds() / 60
        except ValueError:
            age_min = None

    if rows and age_min is not None and age_min < _cache_ttl(cfg, rows, now):
        return rows

    try:
        fresh = providers.fetch_ff_rows()
    except Exception as exc:  # noqa: BLE001
        print(f"!! Календарь недоступен: {exc}", file=sys.stderr)
        cache.setdefault("failed_since", now.isoformat(timespec="seconds"))
        if rows:
            print(f"   работаю по копии от {fetched_at}", file=sys.stderr)
        return rows

    cache["rows"] = fresh
    cache["fetched_at"] = now.isoformat(timespec="seconds")
    cache.pop("failed_since", None)
    cache.pop("warned", None)
    return fresh


def collect_events(
    cfg: dict,
    fixture: str | None,
    state: dict | None = None,
    now: datetime | None = None,
) -> list[providers.Event]:
    if fixture:
        events = providers.load_fixture(fixture)
    elif state is None:
        events = providers.fetch_forexfactory()
    else:
        events = providers.parse_ff_rows(
            fetch_calendar_rows(cfg, state, now or datetime.now(timezone.utc))
        )
    for name in cfg["static_calendars"]:
        events.extend(providers.load_static_calendar(ROOT / name))

    # свежая запись побеждает (в ней уже может быть actual)
    dedup: dict[str, providers.Event] = {}
    for event in events:
        old = dedup.get(event.uid)
        if old is None or (event.actual and not old.actual):
            dedup[event.uid] = event
    return sorted(dedup.values(), key=lambda e: e.dt)


def whitelisted(events, cfg: dict, state: dict):
    """Оставляет только события из белого списка с учётом настроек пользователя."""
    off = commands.disabled_set(state, cfg)
    power = commands.min_power(state, cfg)
    out = []
    for event in events:
        rule = filters.match(
            event,
            disabled=off,
            min_power=power,
            include_adp=cfg["include_adp"],
        )
        if rule:
            out.append((event, rule))
    return out


def _items(cfg, state, fixture, now=None):
    try:
        events = collect_events(cfg, fixture, state, now)
    except Exception as exc:  # noqa: BLE001
        print(f"!! Не смог собрать события: {exc}", file=sys.stderr)
        return []
    return whitelisted(events, cfg, state)


def _warn_if_stale(tg, state: dict, now: datetime, day_key: str) -> None:
    """Если календарь не грузится больше трёх часов — предупреждаем раз в сутки."""
    cache = state.get("calendar") or {}
    since = cache.get("failed_since")
    if not since or cache.get("warned") == day_key:
        return
    try:
        hours = (now - datetime.fromisoformat(since)).total_seconds() / 3600
    except ValueError:
        return
    if hours < 3:
        return
    ok = tg.send(
        "⚠️ <b>Не могу загрузить экономический календарь</b>\n"
        f"Источник не отвечает уже {int(hours)} ч — напоминания могут не прийти.\n"
        "Обычно это временная блокировка, пробую снова каждые несколько минут."
    )
    if ok:
        cache["warned"] = day_key


def today_text(cfg: dict, state: dict, fixture=None, now=None) -> str:
    tz = ZoneInfo(cfg["timezone"])
    local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
    items = [
        (e, r, e.dt.astimezone(tz))
        for e, r in _items(cfg, state, fixture)
        if e.dt.astimezone(tz).date() == local_now.date()
    ]
    return formatter.digest(items, local_now)


def week_text(cfg: dict, state: dict, fixture=None, now=None, days: int = 8) -> str:
    tz = ZoneInfo(cfg["timezone"])
    local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
    horizon = local_now + timedelta(days=days)
    items = [
        (e, r, e.dt.astimezone(tz))
        for e, r in _items(cfg, state, fixture)
        if local_now <= e.dt.astimezone(tz) <= horizon
    ]
    return formatter.weekly(items, local_now)


# ------------------------------------------------------------------------ логика
def _hhmm(value: str) -> tuple[int, int]:
    hour, _, minute = value.partition(":")
    return int(hour), int(minute or 0)


def _mark(state, uid, stage) -> None:
    state.setdefault("sent", {}).setdefault(uid, [])
    if stage not in state["sent"][uid]:
        state["sent"][uid].append(stage)


def _already(state, uid, stage) -> bool:
    return stage in state.get("sent", {}).get(uid, [])


def run_once(now: datetime, cfg: dict, state: dict, *, fixture=None, dry=False, tg=None) -> int:
    tg = tg or Telegram(dry=dry)
    tz = ZoneInfo(cfg["timezone"])
    local_now = now.astimezone(tz)
    tol = timedelta(minutes=cfg["tolerance_minutes"])
    sent_count = 0

    # 0) сначала обрабатываем команды пользователя (/off, /menu и так далее)
    if cfg["enable_commands"] and not tg.dry:
        handlers = {
            "today": lambda: today_text(cfg, state, fixture),
            "week": lambda: week_text(cfg, state, fixture),
        }
        if commands.process(tg, cfg, state, handlers):
            # сохраняем сразу: если дальше что-то отвалится, ответы не повторятся
            save_state(state)

    items = _items(cfg, state, fixture, now)
    _warn_if_stale(tg, state, now, local_now.strftime("%Y-%m-%d"))

    # если календарь не загрузился — молчим про "спокойный день". Лучше
    # прислать дайджест позже, когда данные появятся, чем соврать, что релизов нет
    cal_ok = bool(fixture) or bool((state.get("calendar") or {}).get("rows"))

    # 1) утренний дайджест
    d_h, d_m = _hhmm(cfg["daily_digest_at"])
    digest_at = local_now.replace(hour=d_h, minute=d_m, second=0, microsecond=0)
    today_key = local_now.strftime("%Y-%m-%d")
    if cal_ok and state.get("digest") != today_key and digest_at <= local_now < digest_at + timedelta(hours=4):
        today = [
            (e, r, e.dt.astimezone(tz))
            for e, r in items
            if e.dt.astimezone(tz).date() == local_now.date()
        ]
        if tg.send(formatter.digest(today, local_now)):
            state["digest"] = today_key
            sent_count += 1

    # 2) обзор недели
    weekly_cfg = cfg["weekly_preview"]
    if weekly_cfg:
        w_h, w_m = _hhmm(weekly_cfg["at"])
        week_key = f"{local_now.isocalendar().year}-W{local_now.isocalendar().week}"
        weekly_at = local_now.replace(hour=w_h, minute=w_m, second=0, microsecond=0)
        if (
            cal_ok
            and local_now.weekday() == weekly_cfg["weekday"]
            and state.get("weekly") != week_key
            and weekly_at <= local_now < weekly_at + timedelta(hours=4)
        ):
            horizon = local_now + timedelta(days=8)
            upcoming = [
                (e, r, e.dt.astimezone(tz))
                for e, r in items
                if local_now <= e.dt.astimezone(tz) <= horizon
            ]
            if tg.send(formatter.weekly(upcoming, local_now)):
                state["weekly"] = week_key
                sent_count += 1

    # 3) напоминания до события и 4) факт после выхода
    for event, rule in items:
        local_dt = event.dt.astimezone(tz)

        if not event.all_day:
            for lead in cfg["lead_minutes"]:
                stage = f"pre{lead}"
                target = event.dt - timedelta(minutes=lead)
                if _already(state, event.uid, stage):
                    continue
                if target <= now <= target + tol and now < event.dt:
                    left = max(1, round((event.dt - now).total_seconds() / 60))
                    if tg.send(formatter.pre_alert(event, rule, local_dt, left)):
                        _mark(state, event.uid, stage)
                        sent_count += 1

        if cfg["send_results"] and event.actual and not _already(state, event.uid, "result"):
            if event.dt <= now <= event.dt + timedelta(hours=6):
                if tg.send(formatter.result_alert(event, rule, local_dt)):
                    _mark(state, event.uid, "result")
                    sent_count += 1

    return sent_count


# ------------------------------------------------------------------- тесты
TEST_MOMENTS = (
    ("Утренний дайджест (пятница 11 сентября, 09:00 Киев)", "2026-09-11T06:00:00+00:00"),
    ("Напоминания за 30 минут (15:00 Киев)", "2026-09-11T12:00:00+00:00"),
    ("Напоминания за 5 минут (15:25 Киев)", "2026-09-11T12:25:00+00:00"),
    ("Факты после выхода данных (15:33 Киев)", "2026-09-11T12:33:00+00:00"),
    ("Обзор недели (воскресенье 13 сентября, 18:00 Киев)", "2026-09-13T15:00:00+00:00"),
)


def run_test(cfg: dict, fixture: str) -> None:
    state_path = ROOT / "tests" / "_state_test.json"
    state_path.unlink(missing_ok=True)
    state = load_state(state_path)
    tg = Telegram(dry=True)

    for label, iso in TEST_MOMENTS:
        print("\n\n" + "#" * 70)
        print(f"### {label}")
        print("#" * 70)
        count = run_once(datetime.fromisoformat(iso), cfg, state, fixture=fixture, dry=True, tg=tg)
        if not count:
            print("(нет сообщений в этот момент)")
        save_state(state, state_path)

    print("\n\n✔ Тест завершён. Отправлено бы сообщений: "
          f"{sum(len(v) for v in state.get('sent', {}).values()) + 2}")
    state_path.unlink(missing_ok=True)


def run_demo(cfg: dict) -> None:
    """Показывает, как выглядят меню и справочные команды."""
    state = {"sent": {}, "digest": "", "weekly": ""}
    tg = Telegram(dry=True)
    print("\n### /menu")
    tg.send(commands.menu_text(state, cfg), reply_markup=commands.menu_keyboard(state, cfg))
    print("\n### нажатие на группу «Центробанки мира»")
    tg.send(commands.group_text(state, cfg, "central_banks"),
            reply_markup=commands.group_keyboard(state, cfg, "central_banks"))
    print("\n### /status")
    tg.send(commands.status_text(state, cfg))
    print("\n### /what nfp")
    tg.send(formatter.rule_card(filters.get("nfp")))
    print("\n### /list (фрагмент)")
    print("\n".join(commands.list_text(state, cfg).splitlines()[:24]))
    print("\n### /glossary (фрагмент)")
    print("\n".join(formatter.glossary().splitlines()[:12]))


# -------------------------------------------------------------------------- CLI
def main() -> None:
    parser = argparse.ArgumentParser(description="Macro Alert Bot")
    parser.add_argument("--once", action="store_true", help="один проход и выход")
    parser.add_argument("--loop", action="store_true", help="бесконечный цикл")
    parser.add_argument("--test", action="store_true", help="офлайн-прогон на тестовых данных")
    parser.add_argument("--demo", action="store_true", help="показать меню и сп��авку")
    parser.add_argument("--dry-run", action="store_true", help="печатать в консоль, не шлать в Telegram")
    parser.add_argument("--now", help="подменить текущее время, например 2026-09-11T12:00:00+00:00")
    parser.add_argument("--fixture", help="JSON-файл с событиями вместо загрузки из сети")
    parser.add_argument("--interval", type=int, default=1, help="минут между проверками в --loop")
    args = parser.parse_args()

    cfg = load_config()

    if args.demo:
        run_demo(cfg)
        return

    if args.test:
        run_test(cfg, args.fixture or str(ROOT / "tests" / "sample_ff.json"))
        return

    if args.loop:
        print(f"Запущен цикл, проверка каждые {args.interval} мин. Остановить: Ctrl+C")
        while True:
            state = load_state()
            try:
                run_once(datetime.now(timezone.utc), cfg, state,
                         fixture=args.fixture, dry=args.dry_run)
            except Exception as exc:  # noqa: BLE001
                print(f"!! Ошибка прохода: {exc}")
            save_state(state)
            time.sleep(max(1, args.interval) * 60)

    # по умолчанию — один проход
    state = load_state()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    count = 0
    try:
        count = run_once(now, cfg, state, fixture=args.fixture, dry=args.dry_run)
    except Exception:  # noqa: BLE001
        # Падать нельзя: иначе GitHub не сохранит state.json и бот повторит
        # уже отправленные сообщения. Печатаем причину и выходим спокойно.
        traceback.print_exc()
        print("!! Проход завершён с ошибкой, состояние сохранено", file=sys.stderr)
    finally:
        save_state(state)
    print(f"Готово. Сообщений отправлено: {count}")


if __name__ == "__main__":
    main()
