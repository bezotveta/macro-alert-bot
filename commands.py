"""Управление ботом прямо из Telegram: включение и выключение новостей.

Настройки живут в state.json → "prefs":
    disabled  — список выключенных ключей событий
    min_power — минимальная сила события (3 = только большие палки)

Команды:
    /menu      — меню с кнопками, включать и выключать по группам
    /list      — весь список событий текстом со статусами
    /off cpi   — выключить конкретную новость
    /on cpi    — включить обратно
    /power 3   — оставить только самые сильные события
    /all       — включить всё
    /status    — текущие настройки
    /today     — что сегодня
    /week      — что на неделе
    /glossary  — словарь терминов
    /what cpi  — подробная расшифровка одного показателя
"""
from __future__ import annotations

from html import escape

import filters
import formatter


# ------------------------------------------------------------------ настройки
def prefs(state: dict, cfg: dict) -> dict:
    """Настройки пользователя. При первом запуске берутся из config.json."""
    saved = state.get("prefs")
    if not isinstance(saved, dict):
        saved = {
            "disabled": list(cfg.get("disabled_rules", [])),
            "min_power": int(cfg.get("min_power", 2)),
        }
        state["prefs"] = saved
    saved.setdefault("disabled", list(cfg.get("disabled_rules", [])))
    saved.setdefault("min_power", int(cfg.get("min_power", 2)))
    return saved


def disabled_set(state: dict, cfg: dict) -> set[str]:
    return {key.strip().lower() for key in prefs(state, cfg)["disabled"]}


def min_power(state: dict, cfg: dict) -> int:
    value = int(prefs(state, cfg)["min_power"])
    return value if value in (1, 2, 3) else 2


def _set_disabled(state: dict, cfg: dict, keys: set[str]) -> None:
    prefs(state, cfg)["disabled"] = sorted(keys)


def is_on(state: dict, cfg: dict, rule: filters.Rule) -> bool:
    return rule.key not in disabled_set(state, cfg) and rule.power >= min_power(state, cfg)


# -------------------------------------------------------------------- тексты
HELP = """🤖 <b>Что я умею</b>

Я слежу только за крупными макроэкономическими новостями и присылаю:
1. Утром — план на день.
2. За 30 и за 5 минут до события — напоминание с расшифровкой.
3. Сразу после выхода — цифру, сравнение с прогнозом и разбор для рынка.
4. В воскресенье — обзор недели.

<b>Управление</b>
/menu — меню с кнопками: включить или выключить новости
/list — весь список событий и их статус
/off <code>ключ</code> — выключить новость, например: <code>/off claims</code>
/on <code>ключ</code> — включить обратно
/power <code>3</code> — оставить только 🔴🔴🔴 большие палки
/power <code>2</code> — 🔴🔴🔴 и 🟠🟠 (по умолчанию)
/power <code>1</code> — вообще всё, включая мелочи
/all — включить все новости разом
/status — что сейчас включено

<b>Справка</b>
/today — что выходит сегодня
/week — что выходит на этой неделе
/glossary — словарь: CPI, PPI, NFP, ястребиный и прочее
/what <code>ключ</code> — подробно про один показатель, например: <code>/what nfp</code>"""


def status_text(state: dict, cfg: dict) -> str:
    off = disabled_set(state, cfg)
    power = min_power(state, cfg)
    active = [r for r in filters.RULES if r.key not in off and r.power >= power]
    strong = [r for r in active if r.power == 3]
    lines = [
        "⚙️ <b>Текущие настройки</b>",
        "",
        f"Порог силы: <b>{filters.POWER_LABEL[power]}</b> и выше",
        f"Активно событий: <b>{len(active)}</b> из {len(filters.RULES)} "
        f"(из них 🔴🔴🔴 больших: {len(strong)})",
    ]
    if off:
        names = ", ".join(sorted(off))
        lines += ["", f"Выключено вручную: <code>{escape(names)}</code>"]
    lines += ["", "Изменить: /menu или /power"]
    return "\n".join(lines)


def list_text(state: dict, cfg: dict) -> str:
    lines = ["📋 <b>Все события бота</b>", "", "✅ включено · ❌ выключено", ""]
    for group, rules in filters.by_group().items():
        lines.append(f"<b>{filters.GROUPS[group]}</b>")
        for rule in rules:
            mark = "✅" if is_on(state, cfg, rule) else "❌"
            lines.append(f"{mark} {rule.badge} {escape(rule.name_ru)}")
            lines.append(f"      ключ: <code>{rule.key}</code>")
        lines.append("")
    lines.append("Выключить: <code>/off ключ</code>   Включить: <code>/on ключ</code>")
    lines.append("Или удобнее кнопками: /menu")
    return "\n".join(lines)


# ------------------------------------------------------------------ клавиатуры
def menu_keyboard(state: dict, cfg: dict) -> dict:
    rows = []
    for group, rules in filters.by_group().items():
        on_count = sum(1 for r in rules if is_on(state, cfg, r))
        rows.append([{
            "text": f"{filters.GROUPS[group]}  ({on_count}/{len(rules)})",
            "callback_data": f"g:{group}",
        }])
    power = min_power(state, cfg)
    rows.append([
        {"text": ("• " if power == 3 else "") + "только 🔴🔴🔴", "callback_data": "p:3"},
        {"text": ("• " if power == 2 else "") + "🔴+🟠", "callback_data": "p:2"},
        {"text": ("• " if power == 1 else "") + "всё", "callback_data": "p:1"},
    ])
    return {"inline_keyboard": rows}


def group_keyboard(state: dict, cfg: dict, group: str) -> dict:
    rows = []
    for rule in filters.by_group().get(group, []):
        mark = "✅" if is_on(state, cfg, rule) else "❌"
        name = rule.name_ru.split(" — ")[0].split(" (")[0]
        rows.append([{
            "text": f"{mark} {rule.badge} {name}"[:60],
            "callback_data": f"t:{rule.key}",
        }])
    rows.append([
        {"text": "✅ включить всю группу", "callback_data": f"gon:{group}"},
        {"text": "❌ выключить всю", "callback_data": f"goff:{group}"},
    ])
    rows.append([{"text": "⬅️ назад в меню", "callback_data": "menu"}])
    return {"inline_keyboard": rows}


def menu_text(state: dict, cfg: dict) -> str:
    return (
        "⚙️ <b>Настройка новостей</b>\n\n"
        "Выбери группу, чтобы включать и выключать события по одному.\n"
        "Нижний ряд — быстрый фильтр по силе события:\n"
        "🔴🔴🔴 большая палка · 🟠🟠 крупное · 🟡 второстепенное\n\n"
        f"Сейчас порог: <b>{filters.POWER_LABEL[min_power(state, cfg)]}</b> и выше"
    )


def group_text(state: dict, cfg: dict, group: str) -> str:
    lines = [f"<b>{filters.GROUPS.get(group, group)}</b>", ""]
    for rule in filters.by_group().get(group, []):
        mark = "✅" if is_on(state, cfg, rule) else "❌"
        lines.append(f"{mark} {rule.badge} <b>{escape(rule.name_ru)}</b>")
        lines.append(f"      <i>{escape(formatter._short_what(rule, 150))}</i>")
    lines += ["", "<i>Нажми на событие, чтобы включить или выключить его.</i>"]
    return "\n".join(lines)


# -------------------------------------------------------------- обработка
def _toggle(state: dict, cfg: dict, key: str) -> bool:
    """Переключает событие. Возвращает True, если теперь включено."""
    off = disabled_set(state, cfg)
    rule = filters.get(key)
    if key in off:
        off.discard(key)
        _set_disabled(state, cfg, off)
        # если событие слабее текущего порога — опускаем порог, иначе кнопка «врёт»
        if rule and rule.power < min_power(state, cfg):
            prefs(state, cfg)["min_power"] = rule.power
        return True
    off.add(key)
    _set_disabled(state, cfg, off)
    return False


def process(tg, cfg: dict, state: dict, handlers: dict) -> int:
    """Читает новые сообщения и нажатия кнопок. Возвращает число обработанных."""
    updates = tg.get_updates(state.get("tg_offset", 0))
    handled = 0

    for update in updates:
        state["tg_offset"] = int(update["update_id"]) + 1
        try:
            if "message" in update:
                handled += _on_message(tg, cfg, state, handlers, update["message"])
            elif "callback_query" in update:
                handled += _on_callback(tg, cfg, state, update["callback_query"])
        except Exception as exc:  # noqa: BLE001
            print(f"!! Ошибка обработки команды: {exc}")
    return handled


def _authorized(tg, chat_id) -> bool:
    return str(chat_id) == str(tg.chat_id)


def _on_message(tg, cfg, state, handlers, message) -> int:
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return 0
    if not _authorized(tg, message.get("chat", {}).get("id")):
        return 0

    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1].strip().lower() if len(parts) > 1 else ""

    if cmd in ("/start", "/help"):
        tg.send(HELP)
    elif cmd in ("/menu", "/settings"):
        tg.send(menu_text(state, cfg), reply_markup=menu_keyboard(state, cfg))
    elif cmd == "/list":
        tg.send(list_text(state, cfg))
    elif cmd == "/status":
        tg.send(status_text(state, cfg))
    elif cmd == "/glossary":
        tg.send(formatter.glossary())
    elif cmd == "/what":
        rule = filters.get(arg) if arg else None
        tg.send(formatter.rule_card(rule) if rule else
                "Не знаю такого ключа. Посмотри список: /list")
    elif cmd == "/off":
        rule = filters.get(arg) if arg else None
        if not rule:
            tg.send("Укажи ключ события, например: <code>/off claims</code>\nСписок: /list")
        else:
            off = disabled_set(state, cfg)
            off.add(rule.key)
            _set_disabled(state, cfg, off)
            tg.send(f"❌ Выключено: <b>{escape(rule.name_ru)}</b>\nВключить обратно: <code>/on {rule.key}</code>")
    elif cmd == "/on":
        rule = filters.get(arg) if arg else None
        if not rule:
            tg.send("Укажи ключ события, например: <code>/on claims</code>\nСписок: /list")
        else:
            _toggle(state, cfg, rule.key) if rule.key in disabled_set(state, cfg) else None
            off = disabled_set(state, cfg)
            off.discard(rule.key)
            _set_disabled(state, cfg, off)
            if rule.power < min_power(state, cfg):
                prefs(state, cfg)["min_power"] = rule.power
            tg.send(f"✅ Включено: <b>{escape(rule.name_ru)}</b>")
    elif cmd == "/all":
        _set_disabled(state, cfg, set())
        prefs(state, cfg)["min_power"] = 1
        tg.send("✅ Включены все события, включая второстепенные.\nВернуть только крупные: <code>/power 2</code>")
    elif cmd == "/power":
        if arg in ("1", "2", "3"):
            prefs(state, cfg)["min_power"] = int(arg)
            tg.send(f"Готово. Порог: <b>{filters.POWER_LABEL[int(arg)]}</b> и выше.\n\n"
                    + status_text(state, cfg))
        else:
            tg.send("Укажи 1, 2 или 3:\n<code>/power 3</code> — только большие палки\n"
                    "<code>/power 2</code> — крупные и большие\n<code>/power 1</code> — всё")
    elif cmd == "/today":
        tg.send(handlers["today"]())
    elif cmd == "/week":
        tg.send(handlers["week"]())
    else:
        tg.send("Не знаю такую команду. Список: /help")
    return 1


def _on_callback(tg, cfg, state, query) -> int:
    data = query.get("data") or ""
    message = query.get("message") or {}
    message_id = message.get("message_id")
    if not _authorized(tg, message.get("chat", {}).get("id")):
        return 0

    note = ""
    if data == "menu":
        tg.answer(query["id"])
        tg.edit(message_id, menu_text(state, cfg), reply_markup=menu_keyboard(state, cfg))
        return 1

    if data.startswith("g:"):
        group = data[2:]
        tg.answer(query["id"])
        tg.edit(message_id, group_text(state, cfg, group),
                reply_markup=group_keyboard(state, cfg, group))
        return 1

    if data.startswith("t:"):
        key = data[2:]
        rule = filters.get(key)
        if not rule:
            tg.answer(query["id"], "Неизвестное событие")
            return 0
        now_on = _toggle(state, cfg, rule.key)
        note = ("включено ✅" if now_on else "выключено ❌")
        tg.answer(query["id"], f"{rule.name_ru[:40]} — {note}")
        tg.edit(message_id, group_text(state, cfg, rule.group),
                reply_markup=group_keyboard(state, cfg, rule.group))
        return 1

    if data.startswith("gon:") or data.startswith("goff:"):
        turn_on = data.startswith("gon:")
        group = data.split(":", 1)[1]
        off = disabled_set(state, cfg)
        keys = [r.key for r in filters.by_group().get(group, [])]
        powers = [r.power for r in filters.by_group().get(group, [])]
        if turn_on:
            off -= set(keys)
            if powers and min(powers) < min_power(state, cfg):
                prefs(state, cfg)["min_power"] = min(powers)
        else:
            off |= set(keys)
        _set_disabled(state, cfg, off)
        tg.answer(query["id"], "Готово")
        tg.edit(message_id, group_text(state, cfg, group),
                reply_markup=group_keyboard(state, cfg, group))
        return 1

    if data.startswith("p:"):
        value = data[2:]
        if value in ("1", "2", "3"):
            prefs(state, cfg)["min_power"] = int(value)
        tg.answer(query["id"], f"Порог: {filters.POWER_SHORT[int(value)]}")
        tg.edit(message_id, menu_text(state, cfg), reply_markup=menu_keyboard(state, cfg))
        return 1

    tg.answer(query["id"])
    return 0
