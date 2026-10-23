"""Перевод текста питомца: русский (исходный) и английский.

Русский текст остаётся прямо в коде и служит ключом: tr("Сессия: {name}", name=...)
на русском возвращает его как есть, на английском — строку из EN с теми же {полями}.
Поля подставляются через str.format, поэтому в шаблонах работают и форматы ({pct:.0f}).
Строки без перевода в EN показываются по-русски — так пропуск виден сразу.

Язык хранится в настройках питомца (~/.claude-desktop-pet/settings.json, ключ "lang"):
его читают и сам питомец, и status line (pet_statusline.py) — отдельный процесс.
"""

import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude-desktop-pet" / "settings.json"
LANGS = {"ru": "Русский", "en": "English"}  # названия языков в меню — всегда на своём языке
DEFAULT_LANG = "ru"


def stored_lang():
    """Язык из настроек питомца; нет файла или ключа — DEFAULT_LANG."""
    try:
        value = json.loads(SETTINGS_PATH.read_text(encoding="utf-8")).get("lang")
    except (OSError, ValueError, AttributeError):
        value = None
    return value if value in LANGS else DEFAULT_LANG


LANG = stored_lang()


def set_lang(code):
    global LANG
    LANG = code if code in LANGS else DEFAULT_LANG


def tr(text, **fields):
    """Строка на текущем языке; fields подставляются в {поля} шаблона."""
    template = EN.get(text, text) if LANG == "en" else text
    return template.format(**fields) if fields else template


def plural(n, one, few, many):
    """
    Слово в нужной форме для числа n по русской форме: plural(10, "день", "дня", "дней").
    На английском — пара из EN_PLURALS по форме one: «day» / «days».
    """
    n = abs(int(n))
    if LANG == "en":
        single, multi = EN_PLURALS.get(one, (one, many))
        return single if n == 1 else multi
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


EN_PLURALS = {
    "день": ("day", "days"),
}

EN = {
    # --- запуск и системные сообщения ---
    "Не установлена библиотека Pillow.\n\nВыполните в командной строке:\n    pip install pillow":
        "The Pillow library is not installed.\n\nRun in a command prompt:\n    pip install pillow",
    "Питомец Claude": "Claude pet",
    "Не удалось найти установленное приложение Claude.": "Could not find the installed Claude app.",
    "Не удалось открыть {what}.": "Could not open {what}.",
    "Не удалось запустить Claude.": "Could not launch Claude.",
    "⬆ Claude обновился: {old} → {new}.": "⬆ Claude updated: {old} → {new}.",
    "⬆ Claude обновился и переехал в новую папку.": "⬆ Claude updated and moved to a new folder.",
    "Новая папка: {path}": "New folder: {path}",
    "{title}: нет свежих данных (замер {at})": "{title}: no fresh data (measured {at})",
    "Запуск Claude отменён.": "Claude launch cancelled.",
    "Claude не нашёлся за {sec} с — похоже, приложение не установлено.":
        "Claude was not found within {sec} s — the app seems not to be installed.",
    "Ищу приложение Claude…\nКликните по питомцу ещё раз, чтобы отменить.":
        "Looking for the Claude app…\nClick the pet again to cancel.",

    # --- главное меню ---
    "Запустить Claude": "Launch Claude",
    "Выключить Claude": "Quit Claude",
    "Выключить Claude? Незаконченные ответы и задачи прервутся.":
        "Quit Claude? Unfinished replies and tasks will be interrupted.",
    "Открыть Claude": "Open Claude",
    "Открыть Code": "Open Code",
    "Открыть папку": "Open folder",
    "Статистика": "Statistics",
    "Размер": "Size",
    "Настройки": "Settings",
    "Язык": "Language",
    "Выключить питомца": "Quit pet",

    # --- «Открыть Claude» (пункты и что открываем — для текста ошибки) ---
    "Новый чат": "New chat",
    "новый чат Claude": "a new Claude chat",
    "Недавние чаты": "Recent chats",
    "недавние чаты": "recent chats",
    "Проекты": "Projects",
    "проекты": "projects",
    "Задачи": "Tasks",
    "задачи": "tasks",
    "Коннекторы": "Connectors",
    "каталог коннекторов": "the connector directory",
    "Плагины и навыки": "Plugins and skills",
    "плагины и навыки": "plugins and skills",
    "настройки Claude": "Claude settings",

    # --- «Открыть Code» ---
    "Новый чат Code": "New Code chat",
    "новую сессию Claude Code": "a new Claude Code session",
    "Последний чат Code": "Last Code chat",
    "последнюю сессию Claude Code": "the last Claude Code session",
    "Сессии": "Sessions",
    "Сегодня сессий нет": "No sessions today",
    "сессию Claude Code": "the Claude Code session",
    "Ждут ответа": "Waiting for you",
    "сессии, ждущие ответа": "sessions waiting for you",
    "Поиск сессий": "Search sessions",
    "поиск сессий Claude Code": "Claude Code session search",
    "Папок проектов пока нет": "No project folders yet",

    # --- размер ---
    "Маленький": "Small",
    "Средний": "Medium",
    "Большой": "Large",
    "Гигантский": "Huge",

    # --- настройки ---
    "Сворачиваться в покое": "Shrink when idle",
    "Следить за чатом Claude": "Watch Claude chat",
    "Следить за Claude Code": "Watch Claude Code",
    "Показывать лимиты подписки": "Show subscription limits",
    "Щёлкать по значку Claude в трее (лимиты обновляются)": "Click Claude's tray icon (keeps limits updating)",
    "Уведомления": "Notifications",
    "Дата продления подписки…": "Subscription renewal date…",
    "Недельный сброс лимита…": "Weekly limit reset…",
    "Запускать вместе с Windows": "Start with Windows",

    # --- подсказка ---
    "💤 Claude выключен — нажми, и я его открою": "💤 Claude is off — click me and I'll open it",
    "💤 Claude отдыхает — нет активности {left}": "💤 Claude is resting — no activity for {left}",
    "Claude Code и чат": "Claude Code and chat",
    "чат": "chat",
    "💭 Думает: {who}…": "💭 Thinking: {who}…",
    "⛔ Лимит исчерпан · сброс {at} (через {left})": "⛔ Limit reached · resets {at} (in {left})",
    "📁 Сессия: {name} · {title}": "📁 Session: {name} · {title}",
    "📁 Сессия: {name}": "📁 Session: {name}",
    "контекст {tokens} ток.": "context {tokens} tok.",
    "🕔 За 5 ч: {n} отв. · выход {tokens} ток.": "🕔 Last 5 h: {n} replies · output {tokens} tok.",
    "📈 Сегодня: {n} отв. · выход {tokens} ток.": "📈 Today: {n} replies · output {tokens} tok.",
    "💳 Подписка активна {n} {days}. Истекает {date:%d.%m.%Y}":
        "💳 Subscription active for {n} {days}. Expires {date:%d.%m.%Y}",
    "💳 Подписка истекает сегодня ({date:%d.%m.%Y})": "💳 Subscription expires today ({date:%d.%m.%Y})",

    # --- лимиты (подсказка и окно статистики) ---
    "5 часов": "5 hours",
    "Неделя": "Week",
    "Лимиты: недоступны — в Claude Code стоит другой status line":
        "Limits: unavailable — Claude Code uses another status line",
    "Лимиты: данных пока нет — придут с ответом Claude Code":
        "Limits: no data yet — it will come with a Claude Code reply",
    "{title}: сброшен, новые данные — после ответа Claude Code":
        "{title}: reset, new data after a Claude Code reply",
    " · сброс через {approx}{left} ({at})": " · resets in {approx}{left} ({at})",
    " · сброс не позже чем через {left} ({at})": " · resets within {left} ({at})",
    "Статистика по лимитам обновлена {ago}": "Limit stats updated {ago}",
    "Claude не обновляет лимиты — щёлкни правой кнопкой по его значку в трее":
        "Claude has stopped updating limits — right-click its tray icon",
    "   данные на {at:%d.%m %H:%M} ({source})": "   data as of {at:%d.%m %H:%M} ({source})",
    "приложение": "app",

    # --- уведомления ---
    "5-часовой лимит": "5-hour limit",
    "Недельный лимит": "Weekly limit",
    "🔄 {title} обновился — можно работать в полную силу.": "🔄 {title} has reset — full speed ahead.",
    "\nСброс {at} (через {left}).": "\nResets {at} (in {left}).",
    "✅ Лимит снова доступен.": "✅ The limit is available again.",
    "📊 Claude перестал обновлять лимиты.\nЩёлкни правой кнопкой по его значку в трее — опрос возобновится на сутки.":
        "📊 Claude has stopped updating limits.\nRight-click its tray icon — polling resumes for a day.",
    "⛔ Лимит исчерпан.\nСброс {at} (через {left}).": "⛔ Limit reached.\nResets {at} (in {left}).",
    "🧠 Контекст сессии ({project}): {tokens} токенов.\nПора сделать /compact или начать новую сессию.":
        "🧠 Session context ({project}): {tokens} tokens.\nTime to run /compact or start a new session.",
    "🧠 Контекст сессии ({project}) заполнен на {pct:.0f} %.\nПора сделать /compact или начать новую сессию.":
        "🧠 Session context ({project}) is {pct:.0f} % full.\nTime to run /compact or start a new session.",
    "сегодня": "today",
    "через {n} дн.": "in {n} d",
    "💳 Подписка продлевается {when} ({date:%d.%m}).": "💳 Subscription renews {when} ({date:%d.%m}).",

    # --- окно «Статистика» ---
    "Статистика Claude": "Claude statistics",
    "Обновить": "Refresh",
    "Статистика Claude на {now:%d.%m.%Y %H:%M}": "Claude statistics as of {now:%d.%m.%Y %H:%M}",
    "ЛИМИТЫ ПОДПИСКИ (status line Claude Code и замеры приложения)":
        "SUBSCRIPTION LIMITS (Claude Code status line and app measurements)",
    "  ⛔ Лимит исчерпан, сброс {at}": "  ⛔ Limit reached, resets {at}",
    "  Продление подписки: {date:%d.%m.%Y} (через {n} дн.)": "  Subscription renewal: {date:%d.%m.%Y} (in {n} d)",
    "  Продление подписки: дата не задана (меню → Настройки)":
        "  Subscription renewal: date not set (menu → Settings)",
    "  Последний упор в лимит: {at:%d.%m %H:%M} ({kind})": "  Last time the limit was hit: {at:%d.%m %H:%M} ({kind})",
    "СЕССИИ (последние {days} дн., контекст на последнем ответе)":
        "SESSIONS (last {days} d, context at the last reply)",
    "  ответов за это время нет": "  no replies in this period",
    "ПОСЛЕДНИЕ 5 ЧАСОВ (журналы Claude Code)": "LAST 5 HOURS (Claude Code logs)",
    "  ответов {n} · вход {inp} · выход {out} · кэш: запись {cw}, чтение {cr}":
        "  replies {n} · input {inp} · output {out} · cache: write {cw}, read {cr}",
    "Ответов": "Replies",
    "Вход": "Input",
    "Выход": "Output",
    "Кэш запись": "Cache write",
    "Кэш чтение": "Cache read",
    "ПО ДНЯМ (последние {days} дн.)": "BY DAY (last {days} d)",
    "ПО ПРОЕКТАМ (последние {days} дн.)": "BY PROJECT (last {days} d)",
    "   {pct:.0f} % выхода": "   {pct:.0f} % of output",
    "Обычный чат приложения в журналах не виден, но лимит у него общий —":
        "The app's regular chat is not in the logs, but it shares the same limit —",
    "проценты 5 ч / недели учитывают и его.": "the 5 h / week percentages include it too.",

    # --- окно даты продления ---
    "Дата продления подписки": "Subscription renewal date",
    "Дата следующего списания (ДД.ММ.ГГГГ).\nПодписка помесячная — прошедшая дата сама\nпереносится на следующий месяц.":
        "Next billing date (DD.MM.YYYY).\nThe subscription is monthly — a past date\nmoves to the next month by itself.",
    "Сохранить": "Save",
    "Очистить": "Clear",
    "Отмена": "Cancel",
    "Нужен формат ДД.ММ.ГГГГ, например 31.10.2026": "Use the DD.MM.YYYY format, e.g. 31.10.2026",

    # --- окно недельного сброса ---
    "Недельный сброс лимита": "Weekly limit reset",
    "Недельный лимит сбрасывается в один и тот же день и час —\n"
    "они видны в подсказке индикатора лимитов в окне Claude.\n"
    "Питомец вычисляет их сам, когда заметит сброс в замерах\n"
    "приложения. Заданное здесь используется, только пока\n"
    "он не вычислил время сам.":
        "The weekly limit resets on the same day and hour every week —\n"
        "see the tooltip of the limits indicator in the Claude window.\n"
        "The pet works them out by itself once it notices a reset\n"
        "in the app's measurements. The time set here is used only\n"
        "until the pet has worked it out.",
    "Нужно время ЧЧ:ММ, например 03:00": "Use the HH:MM format, e.g. 03:00",
    "Недельный сброс: пока неизвестен — вычислится сам после ближайшего сброса":
        "Weekly reset: unknown yet — will be worked out after the next reset",
    "Недельный сброс: {at} (задан вручную, пока питомец не вычислил сам)":
        "Weekly reset: {at} (set manually until the pet works it out)",
    "Недельный сброс: {at} (status line Claude Code)": "Weekly reset: {at} (Claude Code status line)",
    "Недельный сброс: ~{at} (по замерам приложения, точность {acc})":
        "Weekly reset: ~{at} (from app measurements, accurate to {acc})",

    # --- окно «Контекст и предупреждения» ---
    "Контекст и предупреждения…": "Context and warnings…",
    "Контекст и предупреждения": "Context and warnings",
    "Модель текущей сессии: {model}": "Current session model: {model}",
    "неизвестна": "unknown",
    "Лимит контекста модели, токенов (например 1000000 или 200k):":
        "Model context limit, tokens (e.g. 1000000 or 200k):",
    "Предупреждать о смене чата при заполнении, %:": "Suggest a new chat when context is this full, %:",
    "Без лимита модели предупреждение приходит по порогу {tokens} токенов.":
        "Without a model limit the warning comes at {tokens} tokens.",
    "Сбросить лимит модели": "Reset model limit",
    "Порог — целое число от {lo} до {hi}": "The threshold must be a whole number from {lo} to {hi}",
    "Лимит — число токенов не меньше {n}, например 1000000 или 200k":
        "The limit must be at least {n} tokens, e.g. 1000000 or 200k",

    # --- форматирование времени и чисел (pet_stats.py) ---
    "{n:.1f} млрд": "{n:.1f} B",
    "{n:.1f} млн": "{n:.1f} M",
    "{n:.1f} тыс": "{n:.1f} K",
    "{d} дн {h} ч": "{d} d {h} h",
    "{h} ч {m:02d} мин": "{h} h {m:02d} min",
    "{m} мин": "{m} min",
    "{m}м": "{m}m",
    "только что": "just now",
    "{n} мин назад": "{n} min ago",
    "{n} ч назад": "{n} h ago",
    "вчера": "yesterday",
    "{n} дн. назад": "{n} d ago",
    "завтра {at:%H:%M}": "tomorrow {at:%H:%M}",
    "прочее": "other",
    "пн": "Mon", "вт": "Tue", "ср": "Wed", "чт": "Thu", "пт": "Fri", "сб": "Sat", "вс": "Sun",

    # --- status line (pet_statusline.py) ---
    "5ч": "5h",
    "нед": "wk",
    " до ": " until ",
}
