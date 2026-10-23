"""Демо-режим питомца для записи видео: все состояния, меню, подсказки, уведомления и окна по сценарию.

Запуск (обычного питомца на время демо лучше закрыть, иначе на экране будут два):
    pythonw pet_demo.pyw           — на текущем языке питомца (или двойной клик по Start Demo.vbs)
    pythonw pet_demo.pyw en        — на английском (ru — на русском, both — сначала ru, потом en)
    pythonw pet_demo.pyw en 10     — второе число: пауза перед началом, сек (успеть включить запись)

Что подменяется (сам питомец, claude_pet.pyw, не меняется):
  • данные — выдуманные: лимиты, «думает», сессии, папки, статистика; настоящие журналы
    и названия сессий в кадр не попадают;
  • мышь — питомец «видит» курсор там, где велит сценарий, а не настоящий;
  • ничего не сохраняется: ни настройки питомца, ни настройки Claude, ни метки уведомлений;
  • пункты меню ничего не делают (кроме «Выключить питомца» — завершает демо), ссылки не открываются.
Esc — прервать демо. В конце демо закрывается само.
"""

import importlib.machinery
import importlib.util
import math
import sys
import time
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_loader = importlib.machinery.SourceFileLoader("claude_pet", str(HERE / "claude_pet.pyw"))
_spec = importlib.util.spec_from_loader("claude_pet", _loader)
cp = importlib.util.module_from_spec(_spec)
_loader.exec_module(cp)
ps, i18n, tr = cp.ps, cp.i18n, cp.tr

# --- Настройки сценария ---
START_DELAY = 15          # пауза перед началом по умолчанию, сек
STEP_PAUSE = 0.7         # пауза между пунктами меню при показе, сек
BUBBLE_TIME = 3.8        # сколько показывать каждое уведомление, сек
FOLLOW_RADIUS = 150      # радиус круга, по которому «ходит» курсор, px (до масштаба)
FOLLOW_SPEED = 1.6       # скорость курсора по кругу, рад/с
DEMO_RENEW_DAYS = 10     # подписка в демо истекает через столько дней
ESC = 0x1B

# Подставные данные: проекты, сессии (заголовки на двух языках), модель
DEMO_MODEL = "claude-opus-5-5"
DEMO_PROJECTS = ["Trading", "Website", "Docs", "Analytics"]
DEMO_SESSIONS = [  # (проект, заголовок ru, заголовок en)
    ("Trading", "Робот для QUIK", "QUIK trading robot"),
    ("Website", "Новая главная страница", "New landing page"),
    ("Docs", "Инструкция для пользователей", "User guide"),
    ("Analytics", "Отчёт по сделкам", "Trades report"),
]

# Подписи к шагам: ключ → (ru, en)
CAPTIONS = {
    "start": ("Демо питомца Claude начнётся через {n}…", "Claude pet demo starts in {n}…"),
    "normal": ("Обычный: Claude запущен, мышь далеко", "Normal: Claude running, mouse far away"),
    "follow": ("Следит за курсором", "Follows the cursor"),
    "blink": ("Моргает", "Blinks"),
    "happy": ("Радуется: курсор на питомце, подсказка", "Happy: cursor on the pet, tooltip"),
    "collapse": ("Сворачивается: 5 секунд без мыши", "Shrinks: 5 seconds without the mouse"),
    "sizes": ("Размеры: маленький, большой, гигантский", "Sizes: small, large, huge"),
    "code": ("Думает Claude Code: дуга по часовой", "Claude Code thinking: clockwise arc"),
    "chat": ("Думает обычный чат: дуга против часовой", "Regular chat thinking: counterclockwise arc"),
    "both": ("Думают оба: дуга-маятник", "Both thinking: pendulum arc"),
    "green": ("Лимит < 50 %: зелёный ореол", "Limit < 50 %: green halo"),
    "yellow": ("Лимит 50–80 %: жёлтый ореол", "Limit 50–80 %: yellow halo"),
    "red": ("Лимит ≥ 80 %: красный ореол", "Limit ≥ 80 %: red halo"),
    "notify": ("Уведомления о лимите", "Limit notifications"),
    "blocked": ("Лимит исчерпан: грусть и таймер до сброса", "Limit reached: sad face and reset timer"),
    "soon": ("Скоро сброс: меньше часа — минуты", "Reset soon: under an hour, minutes"),
    "unblock": ("Лимит снова доступен", "The limit is available again"),
    "context": ("Уведомления о контексте и подписке", "Context and subscription notifications"),
    "combo": ("Сочетание: радуется + думает + 65 %", "Combination: happy + thinking + 65 %"),
    "collapsed_limit": ("Свёрнут с лимитом: цвет виден и в покое", "Shrunk with limit: color stays visible"),
    "sleep": ("Спит: нет активности Claude", "Sleeping: no Claude activity"),
    "off": ("Claude выключен", "Claude is off"),
    "off_menu": ("Меню при выключенном Claude", "Menu when Claude is off"),
    "menu": ("Меню питомца", "Pet menu"),
    "stats": ("Окно «Статистика»", "Statistics window"),
    "renewal": ("Дата продления подписки", "Subscription renewal date"),
    "end": ("Конец демо", "End of demo"),
}


def cap(key, **fields):
    ru, en = CAPTIONS[key]
    return (en if i18n.LANG == "en" else ru).format(**fields)


class FakeJournal:
    """Подставной журнал Claude Code: те же методы, что у ps.JournalStats, данные выдуманные."""

    def __init__(self):
        now = time.time()
        self.cwds = {f"D:/Projects/{p}": now for p in DEMO_PROJECTS}
        self.last_answer = now
        self.quota = (now - 20 * 3600, {"rateLimitType": "five_hour"})

    def refresh(self):
        pass

    def project_of(self, cwd):
        return Path(cwd).name if cwd else "—"

    def first_answer(self, lo, hi):
        return None

    def blocked(self, now=None):
        return None

    def totals(self, since):
        hours = (time.time() - since) / 3600
        k = min(hours, 24) / 5
        return {"messages": int(64 * k), "input": int(1300 * k), "output": int(92_000 * k),
                "cache_write": int(180_000 * k), "cache_read": int(11_500_000 * k)}

    def by_day(self, days):
        today = date.today()
        pattern = [1.0, 0.6, 0.0, 0.8, 1.3, 0.4, 0.9]
        return [(today - timedelta(days=i), [int(v * f) for v in (210, 400, 260_000, 520_000, 31_000_000)])
                for i, f in zip(range(days), pattern * 10)]

    def by_project(self, since):
        shares = {"Trading": 0.55, "Website": 0.25, "Docs": 0.12, "Analytics": 0.08}
        return {p: [int(v * s) for v in (900, 1800, 1_150_000, 2_300_000, 140_000_000)] for p, s in shares.items()}

    def recent_sessions(self, since):
        now = time.time()
        out = []
        for i, (project, _, _) in enumerate(DEMO_SESSIONS):
            ts = now - i * 2.5 * 3600 - 30
            if ts >= since:
                out.append((f"demo-{i}", {"ts": ts, "cwd": f"D:/Projects/{project}", "model": DEMO_MODEL,
                                          "context": [128_000, 342_000, 76_000, 515_000][i]}))
        return out


def demo_title(sid):
    """Заголовок подставной сессии на текущем языке (вместо ps.session_title)."""
    if sid and sid.startswith("demo-"):
        _, ru, en = DEMO_SESSIONS[int(sid[5:])]
        return en if i18n.LANG == "en" else ru
    return None


class DemoState:
    """То, что в настоящем питомце приходит от Claude: думает ли, запущено ли приложение."""
    code = False
    chat = False
    app = True


STATE = DemoState()
# подмена источников на уровне модуля питомца: их вызывает его код напрямую
cp.claude_is_thinking = lambda: (STATE.code, STATE.chat)
cp.claude_running = lambda app_only=False: STATE.app
cp.set_autostart = lambda enabled: None
cp.set_thinking_hooks = lambda enabled: None
ps.session_title = demo_title


class DemoPet(cp.Pet):
    """Питомец, которым управляет сценарий. Ничего не сохраняет и не открывает."""

    def __init__(self):
        self.pointer_mode = "far"
        self.forced_tip = None   # функция текста: подсказка видна без наведения (сон, Claude выключен)
        super().__init__()
        self.journal = FakeJournal()
        self.chat_log.add = lambda ts: None
        # настройки — только в памяти: всё включено, подписка истекает через DEMO_RENEW_DAYS
        self.settings.update(collapse=True, thinking=True, chat_watch=True, limits=True, notify=True,
                             renewal=f"{date.today() + timedelta(days=DEMO_RENEW_DAYS):%d.%m.%Y}")
        self.real_size = self.settings.get("size", cp.SIZES["Средний"])
        self.root.winfo_pointerxy = self.fake_pointer  # взгляд, наведение и сворачивание — по сценарию
        self.set_limits(30, 12)

    # --- подмены ---
    def save_settings(self):
        pass

    def update_status(self):
        pass

    def notify(self, key, text):
        self.show_bubble(text)

    def toggle_claude(self, foreground=None):
        pass

    @staticmethod
    def open_claude_link(url, what):
        pass

    def toggle_thinking(self):
        pass

    def toggle_chat_watch(self):
        pass

    def toggle_collapse(self):
        pass

    def toggle_limits(self):
        pass

    def toggle_notify(self):
        pass

    def set_lang(self, code):
        pass

    def session_items(self):
        return [{"label": demo_title(f"demo-{i}"), "command": lambda: None} for i in range(len(DEMO_SESSIONS))]

    def folder_items(self):
        now = time.time()
        return [{"label": f"{p}   · {ps.fmt_ago(now - i * 86400)}", "command": lambda: None}
                for i, p in enumerate(DEMO_PROJECTS)]

    def update_tip(self, now, hover):
        if self.forced_tip and not self.popup:
            self.tip.show(self.forced_tip())
        else:
            super().update_tip(now, hover)

    # --- мышь ---
    def center(self):
        return self.root.winfo_rootx() + self.win / 2, self.root.winfo_rooty() + self.win / 2

    def fake_pointer(self):
        cx, cy = self.center()
        if self.pointer_mode == "on":
            return int(cx), int(cy)
        if self.pointer_mode == "follow":
            a = time.time() * FOLLOW_SPEED
            r = FOLLOW_RADIUS * self.scale
            return int(cx + r * math.cos(a)), int(cy + r * math.sin(a))
        return int(cx - 600 * self.scale), int(cy - 250 * self.scale)  # «далеко»: слева сверху

    # --- данные ---
    def set_limits(self, five, week, reset_in=3 * 3600 + 13 * 60):
        now = time.time()
        self.usage = {"sessions": [], "limits": {
            "five_hour": {"pct": float(five), "resets_at": now + reset_in, "updated": now, "source": "приложение",
                          "estimated": True, "stale": False, "last_pct": float(five)},
            "seven_day": {"pct": float(week), "resets_at": None, "updated": now, "source": "приложение",
                          "estimated": False, "stale": False, "last_pct": float(week)},
        }}

    def show_bubble(self, text):
        if self.bubble:
            self.bubble.close()
        self.bubble = cp.Bubble(self, text)


class Caption:
    """Подпись к шагу демо — над питомцем (меню открывается вниз), если не влезает — под ним."""

    def __init__(self, pet):
        self.pet = pet
        s = pet.scale
        self.top = tk.Toplevel(pet.root)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=cp.BUBBLE_EDGE)
        self.label = tk.Label(self.top, bg="#1e1e1e", fg="#f2f2f2", font=("Segoe UI Semibold", 12),
                              padx=int(14 * s), pady=int(7 * s))
        self.label.pack(padx=max(1, int(s)), pady=max(1, int(s)))

    def show(self, text):
        self.label.configure(text=text)
        self.top.update_idletasks()
        w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        p = self.pet
        left, top, right, bottom = cp.virtual_screen()
        x = int(min(max(p.root.winfo_rootx() + p.win / 2 - w / 2, left), right - w))
        y = p.root.winfo_rooty() - h - int(10 * p.scale)
        if y < top:
            y = p.root.winfo_rooty() + p.win + int(10 * p.scale)
        self.top.geometry(f"{w}x{h}+{x}+{y}")
        self.top.deiconify()


class Scenario:
    """Шаги демо по очереди: каждый шаг — генератор, yield N — подождать N секунд."""

    def __init__(self, pet, langs, start_delay):
        self.pet, self.langs, self.start_delay = pet, langs, start_delay
        self.caption = Caption(pet)
        self.steps = self.script()
        self.watch_esc()
        pet.root.after(100, self.advance)

    def watch_esc(self):
        if cp.user32.GetAsyncKeyState(ESC) & 0x8000:
            self.pet.root.destroy()
            return
        self.pet.root.after(100, self.watch_esc)

    def advance(self):
        try:
            delay = next(self.steps)
        except StopIteration:
            self.pet.root.destroy()
            return
        self.pet.root.after(int(delay * 1000), self.advance)

    # --- помощники ---
    def say(self, key, **fields):
        self.caption.show(cap(key, **fields))

    def reset(self):
        """Спокойное состояние между шагами."""
        p = self.pet
        STATE.code = STATE.chat = False
        STATE.app = True
        # «думает» питомец перечитывает раз в 0.4 с — гасим сразу, иначе он успеет развернуться
        p.busy, p.thinking_who, p.next_busy_check = False, (False, False), 0.0
        p.running = p.app_running = True
        p.block = None
        p.forced_tip = None
        p.pointer_mode = "far"
        p.last_near = time.time()
        p.set_limits(30, 12)
        if p.bubble:
            p.bubble.close()

    def walk_menu(self, menu, items, path):
        """Провести «курсор» по пунктам меню; path — {номер пункта: путь в подменю} для раскрытия."""
        body = menu.top.winfo_children()[0]
        rows = body.winfo_children()
        for i, item in enumerate(items):
            if item is None or item.get("disabled"):
                continue
            row = rows[i]
            menu.on_enter((row, *row.winfo_children()), item)
            yield STEP_PAUSE
            if "submenu" in item and i in path and menu.child:
                yield from self.walk_menu(menu.child, item["submenu"](), path[i])

    def open_menu(self):
        p = self.pet
        cx, cy = p.center()
        items = p.menu_items()
        p.popup = cp.DarkMenu(p, items, int(cx), int(cy))
        return p.popup, items

    def close_menu(self):
        if self.pet.popup:
            self.pet.popup.close()

    # --- сценарий ---
    def script(self):
        p = self.pet
        for n in range(self.start_delay, 0, -1):
            i18n.set_lang(self.langs[0])
            self.say("start", n=n)
            yield 1
        for lang in self.langs:
            i18n.set_lang(lang)
            yield from self.run_once()
        self.say("end")
        yield 2.5

    def run_once(self):
        p = self.pet
        self.reset()
        self.say("normal")
        yield 4

        self.say("follow")
        p.pointer_mode = "follow"
        yield 5

        self.say("blink")
        p.pointer_mode = "far"
        for _ in range(4):
            p.next_blink = time.time()
            yield 0.9

        self.say("happy")
        p.pointer_mode = "on"
        yield 5

        self.say("collapse")
        p.pointer_mode = "far"
        p.last_near = time.time() - cp.IDLE_DELAY
        yield 4

        self.say("sizes")
        p.last_near = time.time()
        home = p.root.winfo_x(), p.root.winfo_y()  # у края экрана большой размер сдвигает питомца
        for name in ("Маленький", "Большой", "Гигантский"):
            p.on_size(cp.SIZES[name])
            yield 1.8
        p.on_size(p.real_size)
        p.move_to(*home)
        yield 1

        self.say("code")
        STATE.code = True
        yield 4
        p.pointer_mode = "on"
        yield 3.5
        p.pointer_mode = "far"
        STATE.code = False

        self.say("chat")
        STATE.chat = True
        yield 4

        self.say("both")
        STATE.code = True
        yield 4
        p.pointer_mode = "on"
        yield 3.5
        self.reset()
        yield 1

        for key, five in (("green", 35), ("yellow", 65), ("red", 88)):
            self.say(key)
            p.set_limits(five, 21)
            yield 3
        p.pointer_mode = "on"
        yield 3.5
        p.pointer_mode = "far"

        self.say("notify")
        now = time.time()
        title = tr("5-часовой лимит")
        reset_tail = tr("\nСброс {at} (через {left}).", at=ps.fmt_reset(now + 4380, now), left=ps.fmt_left(4380))
        p.set_limits(80, 24, 4380)
        p.show_bubble(f"⚠ {title}: 80 %.{reset_tail}")
        yield BUBBLE_TIME
        p.set_limits(95, 26, 4380)
        p.show_bubble(f"⚠ {title}: 95 %.{reset_tail}")
        yield BUBBLE_TIME

        self.say("blocked")
        reset = time.time() + 72 * 60 + 30
        p.block = ("five_hour", reset)
        p.set_limits(100, 27, reset - time.time())
        p.show_bubble(tr("⛔ Лимит исчерпан.\nСброс {at} (через {left}).", at=ps.fmt_reset(reset, now),
                         left=ps.fmt_left(reset - now)))
        yield BUBBLE_TIME
        p.pointer_mode = "on"
        yield 4
        p.pointer_mode = "far"

        self.say("soon")
        if p.bubble:
            p.bubble.close()  # в пузыре прошлого шага — старый таймер
        p.block = ("five_hour", time.time() + 35 * 60 + 30)
        yield 4

        self.say("unblock")
        p.block = None
        p.set_limits(0, 27)
        p.show_bubble(tr("✅ Лимит снова доступен."))
        yield BUBBLE_TIME
        p.show_bubble(tr("🔄 {title} обновился — можно работать в полную силу.", title=title))
        yield BUBBLE_TIME

        self.say("context")
        p.set_limits(30, 27)
        project = DEMO_PROJECTS[0]
        p.show_bubble(tr("🧠 Контекст сессии ({project}): {tokens} токенов.\n"
                         "Пора сделать /compact или начать новую сессию.",
                         project=project, tokens=ps.fmt_tokens(712_000)))
        yield BUBBLE_TIME
        p.show_bubble(tr("🧠 Контекст сессии ({project}) заполнен на {pct:.0f} %.\n"
                         "Пора сделать /compact или начать новую сессию.", project=project, pct=84))
        yield BUBBLE_TIME
        renewal = date.today() + timedelta(days=2)
        p.show_bubble(tr("💳 Подписка продлевается {when} ({date:%d.%m}).",
                         when=tr("через {n} дн.", n=2), date=renewal))
        yield BUBBLE_TIME
        if p.bubble:
            p.bubble.close()

        self.say("combo")
        p.set_limits(65, 30)
        STATE.code = True
        p.pointer_mode = "on"
        yield 5
        self.reset()

        self.say("collapsed_limit")
        p.set_limits(88, 30)
        p.last_near = time.time() - cp.IDLE_DELAY
        yield 4
        self.reset()
        yield 0.8

        self.say("sleep")
        p.running = False
        p.idle_for = 4 * 60 + 20
        yield 3
        p.forced_tip = p.tip_text
        yield 4

        self.say("off")
        STATE.app = False
        p.app_running = False
        yield 4
        p.forced_tip = None

        self.say("off_menu")
        menu, items = self.open_menu()
        yield 1.2
        yield from self.walk_menu(menu, items, {})
        yield 0.8
        self.close_menu()
        self.reset()
        yield 1

        self.say("menu")
        menu, items = self.open_menu()
        yield 1.2
        labels = [it["label"] if it else None for it in items]
        sub = {labels.index(tr(k)): {} for k in ("Открыть Claude", "Открыть папку", "Размер", "Настройки", "Язык")}
        code = p.code_items()
        sub[labels.index(tr("Открыть Code"))] = {[it["label"] if it else None for it in code].index(tr("Сессии")): {}}
        yield from self.walk_menu(menu, items, sub)
        yield 1
        self.close_menu()
        yield 0.8

        self.say("stats")
        p.open_stats()
        win = p.stats_window.top
        win.update_idletasks()
        x, y = cp.place_beside(p, max(win.winfo_width(), win.winfo_reqwidth()),
                               max(win.winfo_height(), win.winfo_reqheight()))
        win.geometry(f"+{x}+{y}")
        yield 7
        p.stats_window.close()

        self.say("renewal")
        dialog = cp.RenewalDialog(p)
        yield 4.5
        dialog.top.destroy()
        self.reset()
        yield 1


def main():
    args = sys.argv[1:]
    lang = args[0] if args else i18n.LANG
    langs = ["ru", "en"] if lang == "both" else [lang if lang in i18n.LANGS else i18n.LANG]
    delay = int(args[1]) if len(args) > 1 and args[1].isdigit() else START_DELAY
    cp.set_dpi_awareness()
    pet = DemoPet()
    Scenario(pet, langs, delay)
    pet.root.mainloop()


if __name__ == "__main__":
    main()
