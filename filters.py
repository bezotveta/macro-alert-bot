"""Белый список макрособытий + расшифровки простыми словами.

Каждое правило (Rule) — это одна «новость», которую отслеживает бот.

power — сила события:
    3 = «большая палка», сквизы на валютах и металлах
    2 = крупное, заметное движение
    1 = второстепенное, обычно тихо

Любое правило можно выключить прямо в Telegram: /off <ключ>
или кнопками в меню /menu. Ключ — это поле key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# ------------------------------------------------------------------- группы
GROUPS: dict[str, str] = {
    "fed": "🇺🇸 ФРС США — ставка и риторика",
    "us_inflation": "🇺🇸 Инфляция в США",
    "us_jobs": "🇺🇸 Рынок труда США",
    "growth": "📈 Экономика и деловая активность",
    "central_banks": "🏦 Ставки центробанков мира",
    "world_inflation": "🌍 Инфляция в мире",
    "world_jobs": "🌍 Рынок труда в мире",
    "china": "🇨🇳 Китай — медь, металлы, AUD",
    "energy": "🛢 Нефть и энергия",
}

POWER_LABEL = {3: "🔴🔴🔴 большая палка", 2: "🟠🟠 крупное", 1: "🟡 второстепенное"}
POWER_SHORT = {3: "🔴🔴🔴", 2: "🟠🟠", 1: "🟡"}


@dataclass(frozen=True)
class Rule:
    key: str            # короткий ключ для команд /on и /off
    group: str          # ключ группы из GROUPS
    power: int          # 3 / 2 / 1
    emoji: str
    name_ru: str        # человеческое название с расшифровкой
    what: str           # что это такое простыми словами
    why: str            # почему двигает рынок
    assets: str         # по каким инструментам обычно бьёт
    pattern: str        # регулярка по названию события в календаре
    currencies: tuple[str, ...] = ()
    kind: str = "event"  # inflation | labor_hot | labor_weak | growth | rate | event

    @property
    def label(self) -> str:
        return self.name_ru

    @property
    def badge(self) -> str:
        return POWER_SHORT[self.power]

    @property
    def power_label(self) -> str:
        return POWER_LABEL[self.power]


# --------------------------------------------------------------------- правила
# Порядок важен: правила проверяются сверху вниз, побеждает первое совпадение.
RULES: list[Rule] = [
    # ============================== ФРС США ==============================
    Rule(
        key="fomc_rate", group="fed", power=3, emoji="🏛",
        name_ru="Ставка ФРС (FOMC) — решение по ставке в США",
        what="ФРС объявляет, под какой процент банки берут деньги. Это главная цифра для всех рынков мира.",
        why="Ставка выше → деньги дороже → акции и золото вниз, доллар вверх. Ставка ниже → наоборот. "
            "Самое сильное плановое событие вообще.",
        assets="доллар, золото, серебро, S&P 500, Nasdaq, крипта — всё сразу",
        pattern=r"(federal funds rate|fomc statement|fomc rate decision)",
        currencies=("USD",), kind="rate",
    ),
    Rule(
        key="fomc_presser", group="fed", power=3, emoji="🎤",
        name_ru="Пресс-конференция главы ФРС",
        what="Через 30 минут после решения глава ФРС отвечает на вопросы журналистов.",
        why="Часто двигает рынок сильнее самого решения: важны намёки на будущее. Одна фраза — и рынок разворачивается на 180°.",
        assets="доллар, золото, индексы США",
        pattern=r"fomc press conference",
        currencies=("USD",), kind="event",
    ),
    Rule(
        key="fomc_projections", group="fed", power=3, emoji="📊",
        name_ru="Прогнозы ФРС / dot plot — «точечный график» будущих ставок",
        what="Раз в квартал каждый член ФРС ставит точку там, где видит ставку через год-два.",
        why="Показывает, сколько снижений или повышений уже заложено. Сдвиг точек = резкий импульс по доллару и золоту.",
        assets="доллар, золото, доходности гособлигаций США",
        pattern=r"(fomc economic projections|summary of economic projections)",
        currencies=("USD",), kind="event",
    ),
    Rule(
        key="fed_testimony", group="fed", power=3, emoji="🏛",
        name_ru="Отчёт главы ФРС в Конгрессе",
        what="Дважды в год глава ФРС полдня отвечает на вопросы конгрессменов.",
        why="Длинная сессия без сценария = много неожиданных фраз, рынок штормит несколько часов подряд.",
        assets="доллар, золото, индексы США",
        pattern=r"(fed chair.*testif|semi-?annual monetary policy report)",
        currencies=("USD",), kind="event",
    ),
    Rule(
        key="fomc_minutes", group="fed", power=2, emoji="📝",
        name_ru="Протокол заседания ФРС (FOMC Minutes)",
        what="Подробная стенограмма прошлого заседания, выходит через 3 недели после него.",
        why="Видно, насколько сильно спорили внутри ФРС. Даёт всплеск волатильности, но короткий.",
        assets="доллар, золото",
        pattern=r"fomc meeting minutes",
        currencies=("USD",), kind="event",
    ),
    Rule(
        key="fed_speak", group="fed", power=1, emoji="🗣",
        name_ru="Выступления представителей ФРС",
        what="Речи главы ФРС и членов совета вне заседаний.",
        why="Иногда меняют ожидания по ставке. Обычно короткие импульсы, но перед заседанием бывают сильными.",
        assets="доллар, золото",
        pattern=r"(fed chair|fomc member|fed vice chair|fed governor|fed president).*(speaks|speech|testifies)",
        currencies=("USD",), kind="event",
    ),

    # ============================ инфляция США ============================
    Rule(
        key="cpi", group="us_inflation", power=3, emoji="🔥",
        name_ru="CPI — индекс потребительских цен (инфляция в США)",
        what="Считает, насколько подорожала корзина товаров и услуг для обычных людей. "
             "m/m = к прошлому месяцу, y/y = к тому же месяцу год назад, Core = без еды и бензина.",
        why="Главный ориентир ФРС по ставке. Выше прогноза → ставку не снизят → акции и золото вниз, доллар вверх. "
            "Одно из двух самых сильных событий месяца, движение начинается в первую секунду.",
        assets="золото, серебро, EURUSD, USDJPY, Nasdaq, S&P 500",
        pattern=r"\bcpi\b",
        currencies=("USD",), kind="inflation",
    ),
    Rule(
        key="core_pce", group="us_inflation", power=3, emoji="🔥",
        name_ru="Core PCE — базовая инфляция, любимый индикатор ФРС",
        what="То же, что CPI, но по методике ФРС и без еды и топлива (они слишком скачут).",
        why="Именно на эту цифру ФРС официально смотрит при решении по ставке. Выходит позже CPI, поэтому реакция чуть спокойнее, но всё равно сильная.",
        assets="золото, доллар, индексы США",
        pattern=r"core pce price index",
        currencies=("USD",), kind="inflation",
    ),
    Rule(
        key="ppi", group="us_inflation", power=2, emoji="🏭",
        name_ru="PPI — индекс цен производителей (инфляция на заводах)",
        what="Насколько подорожало сырьё и продукция на выходе с заводов, ещё до магазинов.",
        why="Опережает CPI на 1-2 месяца: сегодня дорожает у производителя — завтра в магазине. "
            "Часто выходит за день до CPI и задаёт настрой рынку.",
        assets="доллар, золото",
        pattern=r"\bppi\b",
        currencies=("USD",), kind="inflation",
    ),

    # =========================== рынок труда США ===========================
    Rule(
        key="nfp", group="us_jobs", power=3, emoji="💼",
        name_ru="NFP / Non-Farm Payrolls — новые рабочие места в США за месяц",
        what="Сколько рабочих мест создано вне сельского хозяйства. Выходит в первую пятницу месяца.",
        why="Второе по силе событие месяца. Много новых мест → экономика сильна → ставку держат высоко → доллар вверх, золото вниз. "
            "В момент выхода EURUSD и золото могут пролететь 100+ пунктов за секунды — классический сквиз.",
        assets="золото, EURUSD, USDJPY, индексы США",
        pattern=r"non-?farm employment change",
        currencies=("USD",), kind="labor_hot",
    ),
    Rule(
        key="unemployment", group="us_jobs", power=3, emoji="📉",
        name_ru="Уровень безработицы в США",
        what="Какой процент желающих работать не может найти работу. Выходит одновременно с NFP.",
        why="Растёт → экономика слабеет → ФРС начнёт снижать ставку → золото вверх, доллар вниз. "
            "ФРС по закону обязана следить за занятостью, поэтому цифра критична.",
        assets="золото, доллар, индексы США",
        pattern=r"^unemployment rate$",
        currencies=("USD",), kind="labor_weak",
    ),
    Rule(
        key="earnings", group="us_jobs", power=2, emoji="💵",
        name_ru="Average Hourly Earnings — средняя зарплата в час в США",
        what="На сколько процентов выросли зарплаты. Выходит вместе с NFP.",
        why="Растущие зарплаты = люди больше тратят = инфляция не падает. ФРС смотрит очень внимательно.",
        assets="доллар, золото",
        pattern=r"average hourly earnings",
        currencies=("USD",), kind="labor_hot",
    ),
    Rule(
        key="jolts", group="us_jobs", power=2, emoji="📋",
        name_ru="JOLTS — число открытых вакансий в США",
        what="Сколько вакансий сейчас открыто у американских работодателей.",
        why="Показывает, остывает ли рынок труда. Резкое падение вакансий = ранний сигнал слабости экономики.",
        assets="доллар, золото",
        pattern=r"jolts job openings",
        currencies=("USD",), kind="labor_hot",
    ),
    Rule(
        key="claims", group="us_jobs", power=1, emoji="📮",
        name_ru="Initial Jobless Claims — заявки на пособие по безработице за неделю",
        what="Сколько человек за неделю впервые обратились за пособием. Каждый четверг.",
        why="Самая свежая картина по рынку труда. Обычно тихо, но скачок выше 250 тысяч встряхивает рынок.",
        assets="доллар, золото",
        pattern=r"unemployment claims",
        currencies=("USD",), kind="labor_weak",
    ),

    # ==================== экономика и деловая активность ====================
    Rule(
        key="gdp", group="growth", power=2, emoji="📈",
        name_ru="GDP — ВВП США (рост экономики за квартал)",
        what="Сколько всего товаров и услуг произвела страна. Публикуется тремя порциями: "
             "Advance (первая оценка, самая важная), Prelim, Final.",
        why="Слабый ВВП = страх рецессии = акции вниз, золото вверх. Сильный = доллар вверх.",
        assets="доллар, золото, индексы США",
        pattern=r"(advance gdp|prelim gdp|final gdp|gdp q/q)",
        currencies=("USD",), kind="growth",
    ),
    Rule(
        key="retail", group="growth", power=2, emoji="🛒",
        name_ru="Retail Sales — розничные продажи в США",
        what="Сколько американцы потратили в магазинах за месяц.",
        why="Потребитель — это около 70% экономики США. Слабые продажи → страх рецессии → акции вниз, золото вверх.",
        assets="доллар, индексы США, золото",
        pattern=r"(core )?retail sales m/m",
        currencies=("USD",), kind="growth",
    ),
    Rule(
        key="ism", group="growth", power=2, emoji="🏗",
        name_ru="ISM PMI — индекс деловой активности в США",
        what="Опрос менеджеров по закупкам. Выше 50 = экономика растёт, ниже 50 = сжимается.",
        why="Ранний сигнал разворота экономики. Провал ниже 48 обычно = уход из акций в золото и облигации.",
        assets="доллар, индексы США, медь",
        pattern=r"ism (manufacturing|services|non-manufacturing) pmi",
        currencies=("USD",), kind="growth",
    ),
    Rule(
        key="flash_pmi", group="growth", power=2, emoji="⚡️",
        name_ru="Flash PMI — предварительная деловая активность (США, ЕС, Британия)",
        what="Быстрая оценка активности в промышленности и услугах, выходит раньше остальной статистики.",
        why="Первый сигнал о состоянии экономики в текущем месяце. По евро и фунту даёт заметные движения.",
        assets="EURUSD, GBPUSD, индексы",
        pattern=r"flash (manufacturing|services|composite) pmi",
        currencies=("USD", "EUR", "GBP"), kind="growth",
    ),
    Rule(
        key="uom", group="growth", power=2, emoji="🧭",
        name_ru="Индекс Мичигана — настроения потребителей и инфляционные ожидания",
        what="Опрос американцев: как они оценивают своё финансовое будущее и какой инфляции ждут.",
        why="Инфляционные ожидания из этого отчёта ФРС считает крайне важными. Сюрприз бьёт по золоту сильно.",
        assets="золото, доллар",
        pattern=r"uom (consumer sentiment|inflation expectations)",
        currencies=("USD",), kind="growth",
    ),
    Rule(
        key="consumer_conf", group="growth", power=1, emoji="🧑‍🤝‍🧑",
        name_ru="CB Consumer Confidence — индекс доверия потребителей",
        what="Ещё один опрос об уверенности американцев в экономике.",
        why="Дополняет индекс Мичигана. Реакция обычно умеренная.",
        assets="доллар, индексы США",
        pattern=r"cb consumer confidence",
        currencies=("USD",), kind="growth",
    ),

    # ========================= центробанки мира =========================
    Rule(
        key="ecb", group="central_banks", power=3, emoji="🇪🇺",
        name_ru="ЕЦБ — решение по ставке в еврозоне",
        what="Европейский центральный банк объявляет ставку сразу для 20 стран еврозоны.",
        why="Главное событие для евро. Разница между ставками ФРС и ЕЦБ задаёт направление EURUSD. "
            "Сюрприз = сквиз на 150+ пунктов.",
        assets="EURUSD, EURGBP, золото в евро, европейские индексы",
        pattern=r"(main refinancing rate|deposit facility rate|monetary policy statement|rate decision)",
        currencies=("EUR",), kind="rate",
    ),
    Rule(
        key="ecb_presser", group="central_banks", power=3, emoji="🎤",
        name_ru="Пресс-конференция ЕЦБ",
        what="Глава ЕЦБ объясняет решение и отвечает на вопросы — через 45 минут после ставки.",
        why="Именно здесь евро обычно и делает свою «палку», а не на самом решении.",
        assets="EURUSD, европейские индексы",
        pattern=r"ecb press conference",
        currencies=("EUR",), kind="event",
    ),
    Rule(
        key="boe", group="central_banks", power=3, emoji="🇬🇧",
        name_ru="Банк Англии — решение по ставке",
        what="Ставка в Британии плюс раскладка, кто из членов комитета как проголосовал.",
        why="Фунт — одна из самых резких валют. Неожиданный расклад голосов = 100-200 пунктов по GBPUSD за минуты.",
        assets="GBPUSD, EURGBP, британские индексы",
        pattern=r"(official bank rate|mpc official bank rate votes|monetary policy summary|boe press conference)",
        currencies=("GBP",), kind="rate",
    ),
    Rule(
        key="boj", group="central_banks", power=3, emoji="🇯🇵",
        name_ru="Банк Японии — решение по ставке",
        what="Ставка в Японии. Десятилетиями держалась около нуля или ниже.",
        why="Любой намёк на повышение = разворот кэрри-трейда = обвал USDJPY и распродажа риска по всему миру. "
            "Один из главных источников внезапных сквизов на рынке.",
        assets="USDJPY, золото, Nikkei, мировые индексы",
        pattern=r"(boj policy rate|monetary policy statement|boj press conference|boj outlook report)",
        currencies=("JPY",), kind="rate",
    ),
    Rule(
        key="snb", group="central_banks", power=2, emoji="🇨🇭",
        name_ru="Швейцарский нацбанк (SNB) — решение по ставке",
        what="Ставка в Швейцарии, раз в квартал.",
        why="Франк — валюта-убежище, а SNB известен внезапными решениями. USDCHF и EURCHF дёргаются очень резко.",
        assets="USDCHF, EURCHF, золото",
        pattern=r"snb (policy rate|press conference|monetary policy assessment)",
        currencies=("CHF",), kind="rate",
    ),
    Rule(
        key="boc", group="central_banks", power=2, emoji="🇨🇦",
        name_ru="Банк Канады — решение по ставке",
        what="Ставка в Канаде.",
        why="Главный ключ к USDCAD. Канадский доллар вдобавок сильно зависит от нефти.",
        assets="USDCAD, нефть",
        pattern=r"(boc rate statement|overnight rate|boc press conference)",
        currencies=("CAD",), kind="rate",
    ),
    Rule(
        key="rba", group="central_banks", power=2, emoji="🇦🇺",
        name_ru="РБА, Резервный банк Австралии — решение по ставке",
        what="Ставка в Австралии.",
        why="AUD — это ставка на Китай и металлы. Двигает AUDUSD и косвенно медь, серебро, железную руду.",
        assets="AUDUSD, медь, серебро",
        pattern=r"(cash rate|rba rate statement|rba press conference)",
        currencies=("AUD",), kind="rate",
    ),
    Rule(
        key="rbnz", group="central_banks", power=2, emoji="🇳🇿",
        name_ru="РБНЗ, Резервный банк Новой Зеландии — решение по ставке",
        what="Ставка в Новой Зеландии.",
        why="NZDUSD ходит резко из-за низкой ликвидности: сюрприз даёт быстрый сквиз.",
        assets="NZDUSD, AUDNZD",
        pattern=r"(official cash rate|rbnz rate statement|rbnz press conference)",
        currencies=("NZD",), kind="rate",
    ),
    Rule(
        key="cbr", group="central_banks", power=3, emoji="🇷🇺",
        name_ru="ЦБ РФ — решение по ключевой ставке",
        what="Ключевая ставка Банка России.",
        why="Двигает рубль, ОФЗ и акции Мосбиржи. Через 1.5 часа — пресс-конференция главы ЦБ, часто важнее решения.",
        assets="рубль, ОФЗ, индекс Мосбиржи",
        pattern=r"(ключев\w* ставк\w*|interest rate decision|key rate)",
        currencies=("RUB",), kind="rate",
    ),

    # ========================= инфляция в мире =========================
    Rule(
        key="eu_cpi", group="world_inflation", power=2, emoji="🇪🇺",
        name_ru="Инфляция в еврозоне (CPI Flash Estimate)",
        what="Первая оценка роста потребительских цен в еврозоне за месяц.",
        why="Определяет, будет ли ЕЦБ снижать ставку. Сильный драйвер евро, особенно немецкие предварительные данные.",
        assets="EURUSD, европейские индексы",
        pattern=r"(cpi flash estimate|core cpi flash estimate|german prelim cpi)",
        currencies=("EUR",), kind="inflation",
    ),
    Rule(
        key="uk_cpi", group="world_inflation", power=2, emoji="🇬🇧",
        name_ru="Инфляция в Британии (CPI)",
        what="Рост потребительских цен в Великобритании.",
        why="Британская инфляция годами была выше европейской, поэтому цифры регулярно дают резкие движения фунта.",
        assets="GBPUSD, EURGBP",
        pattern=r"\bcpi\b",
        currencies=("GBP",), kind="inflation",
    ),
    Rule(
        key="ca_cpi", group="world_inflation", power=2, emoji="🇨🇦",
        name_ru="Инфляция в Канаде (CPI)",
        what="Рост цен в Канаде, включая «медианную» и «усечённую» версии Банка Канады.",
        why="Определяет шаги Банка Канады, а значит направление USDCAD.",
        assets="USDCAD",
        pattern=r"\bcpi\b",
        currencies=("CAD",), kind="inflation",
    ),
    Rule(
        key="au_cpi", group="world_inflation", power=2, emoji="🇦🇺",
        name_ru="Инфляция в Австралии (CPI)",
        what="Рост цен в Австралии: подробные данные выходят раз в квартал плюс месячная оценка.",
        why="Квартальные данные редкие и крупные — дают сильные движения AUD.",
        assets="AUDUSD, медь",
        pattern=r"\bcpi\b",
        currencies=("AUD",), kind="inflation",
    ),
    Rule(
        key="jp_cpi", group="world_inflation", power=1, emoji="🇯🇵",
        name_ru="Инфляция в Японии (Tokyo / National Core CPI)",
        what="Рост цен в Токио и по стране целиком.",
        why="Чем выше, тем ближе Банк Японии к повышению ставки. Косвенно бьёт по йене.",
        assets="USDJPY",
        pattern=r"(tokyo core cpi|national core cpi)",
        currencies=("JPY",), kind="inflation",
    ),

    # ======================== рынок труда в мире ========================
    Rule(
        key="ca_jobs", group="world_jobs", power=2, emoji="🇨🇦",
        name_ru="Занятость в Канаде (Employment Change)",
        what="Сколько рабочих мест создано в Канаде за месяц.",
        why="Канадский аналог NFP. Часто выходит одновременно с американским — тогда USDCAD штормит вдвойне.",
        assets="USDCAD",
        pattern=r"employment change",
        currencies=("CAD",), kind="labor_hot",
    ),
    Rule(
        key="au_jobs", group="world_jobs", power=2, emoji="🇦🇺",
        name_ru="Занятость в Австралии (Employment Change)",
        what="Изменение числа занятых в Австралии за месяц.",
        why="Главный внутренний драйвер AUD между заседаниями РБА.",
        assets="AUDUSD",
        pattern=r"employment change",
        currencies=("AUD",), kind="labor_hot",
    ),
    Rule(
        key="uk_jobs", group="world_jobs", power=2, emoji="🇬🇧",
        name_ru="Рынок труда Британии (пособия и зарплаты)",
        what="Claimant Count Change — новые получатели пособия; Average Earnings Index — рост зарплат.",
        why="Рост зарплат в Британии = инфляция = Банк Англии держит ставку высоко. Двигает фунт.",
        assets="GBPUSD",
        pattern=r"(claimant count change|average earnings index)",
        currencies=("GBP",), kind="labor_hot",
    ),

    # ============================== Китай ==============================
    Rule(
        key="cn_gdp", group="china", power=2, emoji="🇨🇳",
        name_ru="ВВП Китая",
        what="Рост китайской экономики за квартал.",
        why="Китай — главный покупатель меди, стали и нефти. Слабый ВВП = обвал в промышленных металлах и AUD.",
        assets="медь, серебро, AUDUSD, нефть",
        pattern=r"\bgdp\b",
        currencies=("CNY",), kind="growth",
    ),
    Rule(
        key="cn_pmi", group="china", power=2, emoji="🏭",
        name_ru="PMI Китая — деловая активность (включая Caixin)",
        what="Опрос китайских заводов и сферы услуг. Выше 50 = рост, ниже 50 = спад.",
        why="Самый ранний сигнал по спросу на металлы. Медь и серебро реагируют сразу.",
        assets="медь, серебро, AUDUSD",
        pattern=r"(caixin (manufacturing|services) pmi|manufacturing pmi|non-manufacturing pmi)",
        currencies=("CNY",), kind="growth",
    ),
    Rule(
        key="cn_trade", group="china", power=1, emoji="🚢",
        name_ru="Торговый баланс Китая",
        what="Разница между экспортом и импортом. Важен именно импорт сырья.",
        why="Показывает реальный спрос Китая на металлы и нефть.",
        assets="медь, нефть, AUDUSD",
        pattern=r"trade balance",
        currencies=("CNY",), kind="growth",
    ),

    # ============================ нефть ============================
    Rule(
        key="opec", group="energy", power=2, emoji="🛢",
        name_ru="Встреча ОПЕК+ (квоты на добычу нефти)",
        what="Страны-экспортёры решают, сколько нефти добывать в следующем месяце.",
        why="Решение по квотам = разрыв в цене нефти = движение CAD, рубля и инфляционных ожиданий.",
        assets="нефть, USDCAD, рубль",
        pattern=r"opec",
        currencies=(), kind="event",
    ),
    Rule(
        key="oil_inventories", group="energy", power=1, emoji="🛢",
        name_ru="Запасы нефти в США (Crude Oil Inventories)",
        what="Как изменились коммерческие запасы нефти за неделю. Каждую среду.",
        why="Быстрые движения в нефти и CAD. По акциям и металлам эффект слабый — по умолчанию выключено.",
        assets="нефть, USDCAD",
        pattern=r"crude oil inventories",
        currencies=("USD",), kind="growth",
    ),
]

RULES_BY_KEY: dict[str, Rule] = {rule.key: rule for rule in RULES}
ALL_KEYS: tuple[str, ...] = tuple(rule.key for rule in RULES)


def get(key: str) -> Optional[Rule]:
    return RULES_BY_KEY.get(key.strip().lower())


def by_group(min_power: int = 1) -> dict[str, list[Rule]]:
    """Правила, сгруппированные для меню, в порядке GROUPS."""
    out: dict[str, list[Rule]] = {}
    for group in GROUPS:
        rules = [r for r in RULES if r.group == group and r.power >= min_power]
        if rules:
            out[group] = rules
    return out


def match(
    event,
    *,
    disabled: Iterable[str] = (),
    min_power: int = 1,
    include_adp: bool = False,
) -> Optional[Rule]:
    """Возвращает правило, если событие входит в белый список, иначе None."""
    title = (event.title or "").strip().lower()
    if not title:
        return None
    if not include_adp and "adp" in title:
        return None  # ADP часто путают с NFP, но рынок на него почти не реагирует

    off = {key.strip().lower() for key in disabled}
    currency = (event.currency or "").upper()

    for rule in RULES:
        if rule.key in off or rule.power < min_power:
            continue
        if rule.currencies and currency not in rule.currencies:
            continue
        if re.search(rule.pattern, title, re.IGNORECASE):
            return rule
    return None
