"""Формирование сообщений для Telegram (HTML parse_mode), русский язык.

Во всех сообщениях к каждому событию добавляется расшифровка:
что это за показатель, почему он двигает рынок и по каким инструментам бьёт.
"""
from __future__ import annotations

from html import escape

import filters
from providers import to_number

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

FLAGS = {
    "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵", "CHF": "🇨🇭",
    "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿", "CNY": "🇨🇳", "RUB": "🇷🇺",
}


def human_date(dt_local) -> str:
    return f"{WEEKDAYS[dt_local.weekday()]}, {dt_local.day} {MONTHS[dt_local.month - 1]}"


def _flag(event) -> str:
    return FLAGS.get((event.currency or "").upper(), "🌍")


def _emoji(event, rule) -> str:
    """Эмодзи правила, но без дублирования флага страны."""
    return "" if rule.emoji == _flag(event) else rule.emoji + " "


def _numbers(event) -> str:
    bits = []
    if event.forecast:
        bits.append(f"прогноз <b>{escape(event.forecast)}</b>")
    if event.previous:
        bits.append(f"было {escape(event.previous)}")
    return " · ".join(bits)


def _short_what(rule, limit: int = 130) -> str:
    text = rule.what.split(". ")[0].rstrip(".")
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


# ------------------------------------------------------------ до события
def pre_alert(event, rule, dt_local, minutes_left: int) -> str:
    lines = [
        f"⏰ <b>Через {minutes_left} мин</b> {_flag(event)} <b>{escape(event.title)}</b>",
        f"{_emoji(event, rule)}{escape(rule.name_ru)}",
        f"Сила: {rule.power_label}",
        "",
        f"📌 <b>Что это:</b> {escape(rule.what)}",
        f"📈 <b>Почему двигает рынок:</b> {escape(rule.why)}",
        f"🎯 <b>Обычно бьёт по:</b> {escape(rule.assets)}",
        "",
        f"🕒 {dt_local.strftime('%H:%M')} по Киеву",
    ]
    numbers = _numbers(event)
    if numbers:
        lines.append(numbers)
    if event.note:
        lines.append(escape(event.note))
    return "\n".join(lines)


# ---------------------------------------------------------- после события
def verdict(rule, event) -> tuple[str, str]:
    """(эмодзи-заголовок, трактовка) по факту против прогноза."""
    actual = to_number(event.actual)
    forecast = to_number(event.forecast)

    if rule.kind == "event" or actual is None or forecast is None:
        return "📣", "Смотри текст заявления и реакцию рынка в первые минуты."

    if abs(actual - forecast) < 1e-9:
        return "⚪️", "Ровно по прогнозу — рынок обычно реагирует слабо."
    above = actual > forecast

    if rule.kind == "inflation":
        if above:
            return "🔴", ("Инфляция <b>горячее</b> прогноза → ястребиный сигнал (ставку держат высоко).\n"
                          "Типичная реакция: S&amp;P 500 и Nasdaq ↓, доллар ↑, доходности ↑, золото ↓")
        return "🟢", ("Инфляция <b>ниже</b> прогноза → голубиный сигнал (ставку могут снизить).\n"
                      "Типичная реакция: акции ↑ (особенно техи), доллар ↓, золото ↑")

    if rule.kind == "labor_hot":
        if above:
            return "🟠", ("Рынок труда <b>сильнее</b> ожиданий → ставку могут держать высокой дольше.\n"
                          "Типичная реакция: доллар ↑, доходности ↑, золото ↓, акции чаще ↓")
        return "🟡", ("Рынок труда <b>слабее</b> ожиданий → шансы на снижение ставки ↑, но растут страхи замедления.\n"
                      "Умеренно слабые данные акции любят, резко слабые — нет. Золото обычно ↑")

    if rule.kind == "labor_weak":
        if above:
            return "🟡", ("Безработица/заявки <b>выше</b> прогноза → рынок труда остывает → регулятор мягче.\n"
                          "Умеренный рост акции обычно любят, резкий скачок = сигнал рецессии")
        return "🟠", ("Рынок труда <b>крепче</b> прогноза → ястребиный сигнал.\n"
                      "Типичная реакция: доллар ↑, доходности ↑, золото ↓")

    if rule.kind == "growth":
        if above:
            return "🟢", ("Экономика <b>сильнее</b> прогноза → хорошо для прибылей компаний и сырья, "
                          "но подогревает ожидания по ставке.")
        return "🔴", "Активность <b>слабее</b> прогноза → давление на циклические акции, медь и нефть."

    if rule.kind == "rate":
        if above:
            return "🔴", ("Ставка <b>выше</b> ожиданий → жёстче, чем думал рынок.\n"
                          "Типичная реакция: местная валюта ↑, местные акции ↓")
        return "🟢", ("Ставка <b>ниже</b> ожиданий → мягче, чем думал рынок.\n"
                      "Типичная реакция: местная валюта ↓, местные акции ↑")

    return "📣", ""


def result_alert(event, rule, dt_local) -> str:
    icon, text = verdict(rule, event)
    lines = [
        f"{icon} {_flag(event)} <b>{escape(event.title)}</b>",
        f"{_emoji(event, rule)}{escape(rule.name_ru)}",
        "",
        f"Факт: <b>{escape(event.actual or '—')}</b>"
        + (f"  |  прогноз: {escape(event.forecast)}" if event.forecast else "")
        + (f"  |  было: {escape(event.previous)}" if event.previous else ""),
        f"🕒 вышло в {dt_local.strftime('%H:%M')} по Киеву",
    ]
    if text:
        lines += ["", text]
    lines += ["", f"🎯 <i>Смотри: {escape(rule.assets)}</i>"]
    return "\n".join(lines)


# --------------------------------------------------------------- дайджесты
def digest(items, dt_local, title: str = "План на сегодня") -> str:
    header = f"☀️ <b>{title}</b> — {human_date(dt_local)}"
    if not items:
        return header + "\n\nВажных релизов из твоего списка нет. Спокойный день 🙂"

    lines = [header, ""]
    explained: set[str] = set()
    for event, rule, local in items:
        when = "весь день" if event.all_day else local.strftime("%H:%M")
        lines.append(f"<b>{when}</b> {rule.badge} {_flag(event)} <b>{escape(event.title)}</b>")
        lines.append(f"      {_emoji(event, rule)}{escape(rule.name_ru)}")
        if rule.key not in explained:
            lines.append(f"      <i>{escape(_short_what(rule))}</i>")
            explained.add(rule.key)
        numbers = _numbers(event)
        if numbers:
            lines.append(f"      {numbers}")
        lines.append("")
    lines.append("<i>Время киевское. Напомню отдельно за 30 и за 5 минут до каждого события, "
                 "а после выхода пришлю цифру с разбором.</i>")
    return "\n".join(lines)


def weekly(items, dt_local) -> str:
    if not items:
        return "🗓 <b>Неделя впереди</b>\n\nКрупных релизов из твоего списка не запланировано."

    lines = ["🗓 <b>Что важного на неделе</b>", ""]
    current_day = None
    for event, rule, local in items:
        day = local.date()
        if day != current_day:
            current_day = day
            lines += ["", f"<b>{human_date(local)}</b>"]
        when = "весь день" if event.all_day else local.strftime("%H:%M")
        lines.append(f"  {when} {rule.badge} {_flag(event)} <b>{escape(event.title)}</b>")
        lines.append(f"        <i>{escape(rule.name_ru)}</i>")
    lines += ["", "<i>Время киевское. 🔴🔴🔴 — самые сильные события недели.</i>"]
    return "\n".join(lines)


# ---------------------------------------------------------------- словарик
GLOSSARY = """📖 <b>Словарь новичка</b>

<b>Как читать любую новость</b>
• <b>Прогноз (forecast)</b> — что ждали аналитики.
• <b>Факт (actual)</b> — что вышло на самом деле.
• <b>Было (previous)</b> — значение в прошлый раз.
• Рынок двигает <b>не сама цифра, а разница между фактом и прогнозом</b>. \
Совпало с прогнозом — обычно тишина.

<b>Обозначения периодов</b>
• <b>m/m</b> — к прошлому месяцу.
• <b>y/y</b> — к тому же месяцу год назад.
• <b>q/q</b> — к прошлому кварталу.
• <b>Core</b> («базовый») — без цен на еду и топливо, они слишком скачут.
• <b>Flash / Prelim</b> — предварительная оценка (выходит раньше, двигает сильнее).
• <b>Advance</b> — первая оценка ВВП, самая важная из трёх.

<b>Показатели</b>
• <b>CPI</b> — инфляция для людей, цены в магазинах.
• <b>PPI</b> — инфляция для заводов, цены на выходе с производства.
• <b>PCE</b> — инфляция по методике ФРС, именно её ФРС считает главной.
• <b>NFP</b> — сколько рабочих мест создано в США за месяц.
• <b>PMI / ISM</b> — опрос менеджеров. Выше 50 = рост, ниже 50 = спад.
• <b>GDP / ВВП</b> — раз��ер всей экономики.
• <b>JOLTS</b> — число открытых вакансий.

<b>Кто есть кто</b>
• <b>ФРС (Fed)</b> — центробанк США. <b>FOMC</b> — его комитет по ставке.
• <b>ЕЦБ (ECB)</b> — центробанк еврозоны. <b>BoE</b> — Банк Англии. \
<b>BoJ</b> — Банк Японии. <b>SNB</b> — Швейцарии. <b>BoC</b> — Канады. \
<b>RBA</b> — Австралии. <b>RBNZ</b> — Новой Зеландии.
• <b>dot plot</b> — график, где члены ФРС точками отмечают будущую ставку.

<b>Жаргон</b>
• <b>Ястребиный (hawkish)</b> — за высокую ставку. Плохо для акций, хорошо для валюты.
• <b>Голубиный (dovish)</b> — за низкую ставку. Хорошо для акций и золота.
• <b>Базисный пункт (б.п.)</b> — 0.01%. Снижение на 25 б.п. = на 0.25%.
• <b>Сквиз</b> — резкое движение, выбивающее стопы у толпы.
• <b>Кэрри-трейд</b> — занять дёшево в йене, купить дорогие активы. \
Когда Банк Японии повышает ставку, схема рушится и рынки падают.
• <b>Доходности (yields)</b> — процент по гособлигациям США. Растут — золоту и акциям тяжело.

<b>Почему золото реагирует на данные США</b>
Золото не платит проценты. Чем выше ставка и доходности, тем менее интересно \
держать золото → цена вниз. Слабые данные из США = ожидание снижения ставки = золото вверх."""


def glossary() -> str:
    return GLOSSARY


def rule_card(rule) -> str:
    """Подробная карточка одного события — для команды /what."""
    return "\n".join([
        f"{rule.emoji} <b>{escape(rule.name_ru)}</b>",
        f"Сила: {rule.power_label}   ключ: <code>{rule.key}</code>",
        "",
        f"📌 <b>Что это:</b> {escape(rule.what)}",
        f"📈 <b>Почему двигает рынок:</b> {escape(rule.why)}",
        f"🎯 <b>Обычно бьёт по:</b> {escape(rule.assets)}",
        "",
        f"Группа: {filters.GROUPS.get(rule.group, rule.group)}",
    ])
