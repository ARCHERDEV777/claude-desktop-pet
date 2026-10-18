"""Питомец Claude на рабочем столе.

Круглая иконка поверх всех окон:
  • клик — развернуть Claude (или свернуть, если он уже активен; если не запущен — запустить);
  • перетаскивание левой кнопкой — переместить;
  • в покое сворачивается в полупрозрачный шарик, при наведении мыши разворачивается;
  • пока Claude Code думает над ответом, по ореолу бежит светящаяся дуга
    (сигнал дают хуки в ~/.claude/settings.json → pet_hook.py);
  • правая кнопка — меню (папки проектов Claude, статистика, размер, автозапуск, выход);
  • цвет ореола — расход лимита подписки: зелёный < 50 %, жёлтый < 80 %, красный — дальше
    (данные — status line Claude Code → pet_statusline.py и замеры приложения, см. pet_stats.py);
  • наведение на питомца — подсказка: лимиты 5 ч и недели, контекст, токены, дата продления;
  • лимит исчерпан — грустные глаза и таймер до сброса на мордочке;
  • Claude не активен RUNNING_GRACE (3 мин) или не запущен — питомец спит:
    глаза закрыты, тело бледнее, над головой «z»;
  • уведомления-пузыри: 80 % и 95 % лимита, сброс лимита, полный контекст, скорое продление.

Запуск: «Запустить питомца.vbs» рядом с этим файлом (или pythonw claude_pet.pyw).
Нужны Windows, Python 3 с tkinter и Pillow (pip install pillow).

Перенос на другой компьютер — просто скопировать папку, путей конкретного ПК в коде нет:
  • пути к скриптам берутся от расположения этого файла; хуки, status line и автозапуск
    переписываются на новые пути при каждом старте;
  • папки проектов берутся из записей самого Claude (сессии приложения, Claude Code,
    журналы), а не из расположения питомца;
  • каталог Claude Code — ~/.claude или CLAUDE_CONFIG_DIR, если переменная задана;
  • настройки питомца — в профиле пользователя (~/.claude-desktop-pet), у каждого свои.
Ограничение: наблюдатель за обычным чатом (chat_watch.ps1) узнаёт кнопку остановки
ответа в английском и русском интерфейсе Claude; для других языков её название
нужно добавить в $StopNames в chat_watch.ps1.
"""

import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
import winreg
from datetime import date, datetime
from pathlib import Path

import pet_stats as ps

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont
except ImportError:
    import ctypes as _ctypes
    _ctypes.windll.user32.MessageBoxW(
        None, "Не установлена библиотека Pillow.\n\nВыполните в командной строке:\n    pip install pillow",
        "Питомец Claude", 0x10)
    raise SystemExit(1)

# --- Настройки -------------------------------------------------------------

APP_NAME = "ClaudeDesktopPet"
CLAUDE_EXE_NAME = "claude.exe"
CLAUDE_CLI_MARKER = "\\claude-code\\"  # у Claude Code CLI тот же claude.exe — его окна пропускаем
# Ссылки claude://, которые понимает приложение (меню «Открыть Claude» и «Открыть Code»).
# Первые три — из меню его значка Windows; остальные найдены в обработчике ссылок приложения и не описаны, после
# обновления Claude могут измениться. «Последнего чата» для обычного чата нет: его история
# хранится на сервере, локально id последнего чата не найти — есть только список недавних.
NEW_CHAT_URL = "claude://claude.ai/new?surface=chat&source=desktop_action"
NEW_CODE_SESSION_URL = "claude://code/new?source=desktop_action"
LAST_CODE_SESSION_URL = "claude://code/continue?session=last&source=desktop_action"
CODE_SESSION_URL = "claude://code/continue?session={id}&source=desktop_action"  # id — local_… из данных приложения
NEEDS_INPUT_URL = "claude://code/needs-input?source=desktop_action"  # сессии, ждущие ответа
CODE_SEARCH_URL = "claude://code/search?source=desktop_action"       # поиск по сессиям Code
RECENT_CHATS_URL = "claude://claude.ai/chat"        # без id чата — список недавних чатов
PROJECTS_URL = "claude://claude.ai/project"          # без id проекта — список проектов
TASKS_URL = "claude://claude.ai/tasks"
DIRECTORY_URL = "claude://claude.ai/directory"       # каталог коннекторов
CUSTOMIZE_URL = "claude://claude.ai/customize"       # плагины, навыки
SETTINGS_URL = "claude://claude.ai/settings"

SCRIPT_PATH = Path(__file__).resolve()
# Папка, где МОГУТ лежать проекты, — родитель папки питомца. Её подпапки попадают
# в меню «Открыть папку», только если в ней уже есть хоть один проект Claude
# (см. pet_stats.project_folders): основной список папок берётся из записей самого Claude.
PROJECTS_ROOT = SCRIPT_PATH.parent.parent
# Данные питомца лежат в профиле, а не в %APPDATA%: Claude из Microsoft Store подменяет
# %APPDATA% для всего, что запускает (хуки, команды), и питомец с хуками видели бы разные папки.
DATA_DIR = Path.home() / ".claude-desktop-pet"
SETTINGS_PATH = DATA_DIR / "settings.json"
STATE_PATH = DATA_DIR / "state.json"  # текущее состояние питомца — для диагностики
OLD_SETTINGS_PATH = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME / "settings.json"
SIZES = {"Маленький": 56*2, "Средний": 72*2, "Большой": 96*2, "Гигантский": 144*2}

IDLE_DELAY = 5        # через сколько секунд без мыши питомец сворачивается
IDLE_SCALE = 0.6      # размер в свёрнутом виде
IDLE_ALPHA = 0.6      # непрозрачность в свёрнутом виде

BODY_CENTER = (204, 104, 68)  # в тон значку Claude
BODY_EDGE = (246, 184, 156)   # края светлее за счёт градиента
EDGE_POWER = 4                # плавность осветления к краю: больше — уже светлая зона
HALO_RGB = (238, 241, 247)    # ореол: светлый и едва заметный
HALO_WIDTH = 0.10             # толщина ореола (доля размера)
HALO_ALPHA = 70               # непрозрачность ореола у тела (0–255), к краю сходит на нет
THINK_RGB = (255, 222, 200)   # светящаяся дуга, пока Claude думает
THINK_SPEED = 300             # скорость вращения дуги, градусов в секунду
THINK_TAIL = 220              # длина хвоста дуги, градусов
SWING_DEG = 360              # думают и Code, и чат: дуга ходит маятником на столько градусов туда и обратно
SWING_FADE_DEG = 25           # за сколько градусов до разворота дуга начинает притухать
SWING_TURN_MIN = 0.35         # яркость дуги в точке разворота (доля от обычной)

BUSY_DIR = DATA_DIR / "busy"  # метки «Claude думает» от pet_hook.py
BUSY_STALE = 120             # метка Claude Code живёт, пока её или журнал сессии обновляли за это время (сек)
CHAT_MARKER = BUSY_DIR / "chat-ui"  # метка от наблюдателя за обычным чатом (chat_watch.ps1)
CHAT_STALE = 5                # её наблюдатель обновляет постоянно, поэтому и забывается она быстро
CHAT_WATCH_SCRIPT = SCRIPT_PATH.with_name("chat_watch.ps1")
CLAUDE_SETTINGS = ps.CLAUDE_DIR / "settings.json"  # учитывает CLAUDE_CONFIG_DIR
HOOK_SCRIPT = SCRIPT_PATH.with_name("pet_hook.py")
STATUSLINE_SCRIPT = SCRIPT_PATH.with_name("pet_statusline.py")  # пишет лимиты для питомца

# --- Лимиты подписки и статистика ---
STATUS_INTERVAL_MS = 3000    # как часто пересчитывать лимиты, «запущен ли Claude», уведомления
JOURNAL_INTERVAL = 30        # как часто дочитывать журналы Claude Code, сек
LIMIT_COLORS = [             # (порог %, цвет ореола): первый порог, который НЕ превышен
    (50, (120, 210, 140)),   # зелёный
    (80, (255, 230, 0)),     # жёлтый — насыщенный, чтобы не путать с обычным светлым ореолом
    (999, (240, 95, 80)),    # красный
]
HALO_ALPHA_LIMIT = 175       # ореол заметнее, когда показывает лимит
SESSION_FRESH = 3600         # сессия «текущая» для подсказки, если status line обновлялся за это время, сек

# --- Состояние «Claude не запущен» (сон) ---
RUNNING_GRACE = 180         # без активности Claude (ответы, «думает») столько секунд — питомец засыпает
SLEEP_DESAT = 0.55          # насколько тело блекнет во сне (0 — как обычно, 1 — серое)
SLEEP_GREY = (150, 150, 158)
SLEEP_BOB_SPEED = 0.9        # покачивание во сне медленнее (обычно 2.2)
Z_PERIOD = 2.4               # за сколько секунд «z» поднимается и тает
Z_STEPS = 24                 # кадров анимации «z» в кэше

# --- Подсказка и уведомления ---
LIMIT_ICONS = {"five_hour": "⏳", "seven_day": "📅"}  # иконки строк лимитов в подсказке
TIP_DELAY = 0.8             # через сколько секунд наведения показывать подсказку
NOTIFY_THRESHOLDS = (80, 95)  # % лимита, при которых приходит уведомление
CONTEXT_WARN = 80            # % контекста сессии — совет сделать /compact (только терминальный Claude Code)
CONTEXT_WARN_TOKENS = 700_000  # токенов в контексте сессии — тот же совет по журналу (для приложения)
SESSIONS_DAYS = 3            # за сколько дней показывать сессии в окне «Статистика»
SESSIONS_SHOW = 8            # сколько сессий показывать
RENEWAL_WARN_DAYS = 3        # за сколько дней напоминать о продлении подписки
NOTIFY_SECONDS = 9           # сколько секунд висит пузырь
NOTIFIED_KEEP = 200          # сколько ключей отправленных уведомлений хранить в настройках
STATS_DAYS = 7               # глубина таблиц в окне «Статистика», дней
FOLDERS_MAX = 25             # сколько папок проектов показывать в меню «Открыть папку»
SESSIONS_MENU_MAX = 10       # сколько сегодняшних сессий показывать в меню «Открыть Code › Сессии»
SESSION_LABEL_MAX = 50       # длиннее — название сессии в меню обрезается
FONT_FILE = "segoeuib.ttf"   # шрифт таймера на мордочке (из C:\Windows\Fonts)

HOOK_EVENTS = {  # событие Claude Code → действие pet_hook.py
    "UserPromptSubmit": "start",
    "PostToolUse": "start",
    "Stop": "stop",
    "StopFailure": "stop",
    "SessionEnd": "stop",
}

# --- WinAPI ----------------------------------------------------------------

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
ULW_ALPHA, AC_SRC_ALPHA = 0x2, 0x1
SW_MINIMIZE, SW_RESTORE = 6, 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002

user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetForegroundWindow.restype = wt.HWND
user32.GetParent.restype = wt.HWND
kernel32.OpenProcess.restype = wt.HANDLE
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

gdi32 = ctypes.windll.gdi32
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wt.HANDLE, wt.DWORD]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE),
                                       wt.HDC, ctypes.POINTER(wt.POINT), wt.COLORREF,
                                       ctypes.POINTER(BLENDFUNCTION), wt.DWORD]


def update_layered(hwnd, img: Image.Image, alpha: float):
    """Выводит RGBA-картинку в окно с попиксельной прозрачностью; alpha — общая непрозрачность 0..1."""
    w, h = img.size
    r, g, b, a = img.convert("RGBa").split()  # Windows ждёт премультиплицированный BGRA
    data = Image.merge("RGBA", (b, g, r, a)).tobytes()

    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(mem, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, data, len(data))
    old = gdi32.SelectObject(mem, bitmap)
    blend = BLENDFUNCTION(0, 0, max(0, min(255, int(alpha * 255))), AC_SRC_ALPHA)
    user32.UpdateLayeredWindow(hwnd, screen, None, ctypes.byref(wt.SIZE(w, h)), mem,
                               ctypes.byref(wt.POINT(0, 0)), 0, ctypes.byref(blend), ULW_ALPHA)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, screen)


def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def single_instance() -> bool:
    kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}")
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def process_path(hwnd) -> str:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def is_claude_window(hwnd) -> bool:
    if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
        return False
    if user32.GetWindow(hwnd, 4):  # GW_OWNER — пропускаем всплывающие окна
        return False
    path = process_path(hwnd).lower()
    return path.endswith(CLAUDE_EXE_NAME) and CLAUDE_CLI_MARKER not in path


def find_claude_window():
    found = []

    def callback(hwnd, _):
        if is_claude_window(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found[0] if found else None


psapi = ctypes.windll.psapi
psapi.EnumProcesses.argtypes = [ctypes.POINTER(wt.DWORD), wt.DWORD, ctypes.POINTER(wt.DWORD)]


def claude_running(app_only=False) -> bool:
    """
    Запущен ли хоть один claude.exe — приложение или Claude Code CLI.
    app_only=True — только само приложение (ссылкам claude:// нужно оно, а не CLI).
    Окна не проверяем: свёрнутое в трей приложение окна не показывает, но работает.
    """
    pids = (wt.DWORD * 4096)()
    needed = wt.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed)):
        return True  # не смогли проверить — не усыпляем питомца зря
    buf = ctypes.create_unicode_buffer(1024)
    for pid in pids[:needed.value // ctypes.sizeof(wt.DWORD)]:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue
        try:
            size = wt.DWORD(len(buf))
            if (kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
                    and buf.value.lower().endswith(CLAUDE_EXE_NAME)
                    and not (app_only and CLAUDE_CLI_MARKER in buf.value.lower())):
                return True
        finally:
            kernel32.CloseHandle(handle)
    return False


def claude_launch_command():
    """Как запустить Claude на этом ПК: версия из Microsoft Store или обычная установка."""
    exe = None
    try:  # путь к приложению из обработчика ссылок claude://
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"claude\shell\open\command") as key:
            command = winreg.QueryValueEx(key, "")[0]
        exe = command.split('"')[1] if command.startswith('"') else command.split()[0]
    except (OSError, IndexError):
        pass
    if not exe:
        # Вне пакета Claude ссылки claude:// в реестре не видно — ищем папку пакета Store.
        packages = Path.home() / "AppData" / "Local" / "Packages"
        for package in sorted(packages.glob("Claude_*")):
            if package.is_dir():
                return ["explorer.exe", f"shell:AppsFolder\\{package.name}!Claude"]
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "AnthropicClaude" / "claude.exe"
        exe = str(local) if local.exists() else None
    if exe and "\\windowsapps\\" in exe.lower():
        # Приложения из Store запускаются через AppsFolder: «Claude_<версия>_x64__<издатель>» → «Claude_<издатель>!Claude».
        package = Path(exe).parent.parent.name
        name, _, publisher = package.partition("__")
        return ["explorer.exe", f"shell:AppsFolder\\{name.split('_')[0]}_{publisher}!Claude"]
    if exe:
        return [exe]
    return None


def bring_to_front(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    # Нажатие Alt снимает запрет Windows на смену активного окна из фона.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)


def virtual_screen():
    x, y = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    return x, y, x + user32.GetSystemMetrics(78), y + user32.GetSystemMetrics(79)


# --- Автозапуск ------------------------------------------------------------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def pythonw_path() -> Path:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return pythonw if pythonw.exists() else Path(sys.executable)


def autostart_command() -> str:
    return f'"{pythonw_path()}" "{SCRIPT_PATH}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def refresh_autostart():
    """Если папку перенесли (другой ПК, другой диск) — автозапуск переписывается на новый путь."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            current = winreg.QueryValueEx(key, APP_NAME)[0]
    except OSError:
        return
    if current != autostart_command():
        set_autostart(True)


def set_autostart(enabled: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


# --- Хуки Claude Code («Claude думает») -------------------------------------

def is_pet_hook(group) -> bool:
    return any("pet_hook.py" in " ".join([h.get("command", "")] + h.get("args", []))
               for h in group.get("hooks", []))


def pet_hook_group(event, action):
    hook = {"type": "command", "command": str(pythonw_path()), "args": [str(HOOK_SCRIPT), action], "timeout": 10}
    if event == "PostToolUse":
        hook["async"] = True  # не задерживать каждый вызов инструмента
        return {"matcher": "*", "hooks": [hook]}
    return {"hooks": [hook]}


def set_thinking_hooks(enabled: bool):
    """Добавляет (или убирает) хуки питомца в ~/.claude/settings.json, не трогая остальное."""
    try:
        config = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8")) if CLAUDE_SETTINGS.exists() else {}
    except (OSError, ValueError):
        return  # файл повреждён или занят — лучше не трогать
    hooks = config.get("hooks", {})
    for event, action in HOOK_EVENTS.items():
        groups = [g for g in hooks.get(event, []) if not is_pet_hook(g)]
        if enabled:
            groups.append(pet_hook_group(event, action))
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if hooks:
        config["hooks"] = hooks
    else:
        config.pop("hooks", None)
    write_claude_settings(config)


def is_pet_statusline(entry) -> bool:
    return isinstance(entry, dict) and "pet_statusline.py" in str(entry.get("command", ""))


def set_statusline(enabled: bool) -> bool:
    """
    Включает (или убирает) status line питомца в ~/.claude/settings.json.
    Чужой status line не трогаем: возвращаем False — лимиты тогда недоступны.
    Пути с прямыми слешами: команду запускает оболочка (Git Bash или cmd), обе их понимают.
    """
    try:
        config = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8")) if CLAUDE_SETTINGS.exists() else {}
    except (OSError, ValueError):
        return False
    current = config.get("statusLine")
    if current is not None and not is_pet_statusline(current):
        return False
    if enabled:
        config["statusLine"] = {"type": "command",
                                "command": f'"{pythonw_path().as_posix()}" "{STATUSLINE_SCRIPT.as_posix()}"'}
    else:
        config.pop("statusLine", None)
    write_claude_settings(config)
    return True


def foreign_statusline() -> bool:
    """В настройках Claude Code уже стоит чужой status line."""
    try:
        current = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8")).get("statusLine")
    except (OSError, ValueError):
        return False
    return current is not None and not is_pet_statusline(current)


def write_claude_settings(config):
    """Атомарная запись ~/.claude/settings.json; без изменений — файл не трогаем."""
    text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    try:
        if CLAUDE_SETTINGS.exists() and CLAUDE_SETTINGS.read_text(encoding="utf-8") == text:
            return
        CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        tmp = CLAUDE_SETTINGS.with_suffix(".json.pet-tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, CLAUDE_SETTINGS)
    except OSError:
        pass


def marker_age(marker, now):
    """Сколько секунд сессия Claude Code не подавала признаков жизни.

    Хук пишет в метку путь к журналу сессии (*.jsonl): Claude дописывает его
    на каждом шаге, поэтому метка, оставшаяся без «Stop» (обрыв по лимиту,
    отключённые на ходу хуки), перестаёт считаться за пару минут.
    """
    newest = marker.stat().st_mtime
    try:
        transcript = Path(marker.read_text(encoding="utf-8").strip())
        if transcript.suffix == ".jsonl":
            newest = max(newest, transcript.stat().st_mtime)
    except (OSError, ValueError):
        pass
    return now - newest


def clear_code_markers():
    """Убрать все метки Claude Code (например, при переключении слежения)."""
    try:
        for marker in BUSY_DIR.iterdir():
            if marker != CHAT_MARKER:
                marker.unlink(missing_ok=True)
    except OSError:
        pass


def claude_is_thinking():
    """Свежие метки «думает»: (Claude Code, обычный чат)."""
    now = time.time()
    code = chat = False
    try:
        for marker in BUSY_DIR.iterdir():
            is_chat = marker == CHAT_MARKER
            age = now - marker.stat().st_mtime if is_chat else marker_age(marker, now)
            if age < (CHAT_STALE if is_chat else BUSY_STALE):
                if is_chat:
                    chat = True
                else:
                    code = True
            else:
                marker.unlink(missing_ok=True)
    except OSError:
        pass
    return code, chat


# --- Рисование -------------------------------------------------------------

def lerp(a, b, t):
    return a + (b - a) * t


def lerp_rgb(c1, c2, t):
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


_fonts = {}


def face_font(px: int):
    """Жирный Segoe UI нужного размера (кэшируется); без него — встроенный шрифт PIL."""
    if px not in _fonts:
        try:
            _fonts[px] = ImageFont.truetype(FONT_FILE, px)
        except OSError:
            _fonts[px] = ImageFont.load_default()
    return _fonts[px]


def limit_color(pct):
    """Цвет ореола по проценту лимита; None — данных нет, ореол обычный."""
    if pct is None:
        return None
    for edge, rgb in LIMIT_COLORS:
        if pct < edge:
            return rgb
    return LIMIT_COLORS[-1][1]


def render(size: int, look_x: float, look_y: float, blink: float, mood: str = "normal",
           halo_rgb=None, text: str = "") -> Image.Image:
    """
    Рисует питомца со сглаживанием; look_* в диапазоне -1..1, blink 0..1.
    mood: "normal" | "happy" (мышь на питомце) | "sleep" (Claude не запущен) | "sad" (лимит исчерпан).
    halo_rgb — цвет ореола по лимиту (None — обычный светлый); text — таймер на мордочке.
    """
    ss = 4
    w = size * ss
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx = cy = w / 2
    outer = w / 2
    halo = w * HALO_WIDTH
    h_rgb, h_alpha = (halo_rgb, HALO_ALPHA_LIMIT) if halo_rgb else (HALO_RGB, HALO_ALPHA)
    for i in range(24):
        t = i / 23  # 0 — внешний край ореола, 1 — у тела
        rr = outer - halo * t
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=tuple(h_rgb) + (int(h_alpha * t ** 1.5),))

    r = outer - halo
    center, edge = BODY_CENTER, BODY_EDGE
    if mood == "sleep":  # во сне тело блекнет
        center = lerp_rgb(BODY_CENTER, SLEEP_GREY, SLEEP_DESAT)
        edge = lerp_rgb(BODY_EDGE, SLEEP_GREY, SLEEP_DESAT)
    # Радиальный градиент на весь радиус: к центру основной цвет,
    # к краю плавно светлеет (чем больше EDGE_POWER, тем уже светлая зона).
    steps = 96
    for i in range(steps + 1):
        k = 1 - i / steps  # 1 — край, 0 — центр
        rr = r * k
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=lerp_rgb(center, edge, k ** EDGE_POWER) + (255,))

    # Глаза — две вертикальные «таблетки», смещённые в сторону курсора.
    # Во сне взгляд не следит за мышью, а глаза закрыты.
    if mood == "sleep":
        look_x = look_y = 0.0
    ex = cx - r * 0.06 + look_x * r * 0.34
    ey = cy - r * 0.08 + look_y * r * 0.30
    if text:  # таймер внизу — глаза чуть выше, чтобы всё уместилось
        ey -= r * 0.10
    eye_w, eye_h, gap = r * 0.15, r * 0.40, r * 0.30
    for side, sx in ((-1, ex - gap / 2), (1, ex + gap / 2)):
        if mood == "happy":
            d.arc((sx - eye_w * 0.85, ey - eye_h * 0.1, sx + eye_w * 0.85, ey + eye_h * 0.45),
                  190, 350, fill="white", width=int(eye_w * 0.7))
        elif mood == "sleep":
            # закрытые глаза — дуги «‿»
            d.arc((sx - eye_w * 0.9, ey - eye_h * 0.25, sx + eye_w * 0.9, ey + eye_h * 0.2),
                  20, 160, fill="white", width=int(eye_w * 0.55))
        elif mood == "sad":
            # опущенные глаза и брови домиком: внутренний конец брови выше внешнего
            h = max(eye_w, eye_h * 0.6 * (1 - blink))
            top = ey - h / 2 + eye_h * 0.12
            d.rounded_rectangle((sx - eye_w / 2, top, sx + eye_w / 2, top + h),
                                radius=eye_w / 2, fill="white")
            outer_x, inner_x = sx + side * eye_w * 1.1, sx - side * eye_w * 0.7
            d.line((outer_x, top - eye_h * 0.12, inner_x, top - eye_h * 0.42),
                   fill="white", width=int(eye_w * 0.45))
        else:
            h = max(eye_w, eye_h * (1 - blink))
            d.rounded_rectangle((sx - eye_w / 2, ey - h / 2, sx + eye_w / 2, ey + h / 2),
                                radius=eye_w / 2, fill="white")

    if text:
        font = face_font(int(r * 0.34))
        d.text((cx, cy + r * 0.48), text, font=font, fill="white", anchor="mm")

    return img.resize((size, size), Image.LANCZOS)


def render_z(size: int, phase: float) -> Image.Image:
    """Три «z» над головой спящего питомца: поднимаются вправо-вверх и тают; phase 0..1."""
    ss = 4
    w = size * ss
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(3):
        t = (phase + i / 3) % 1.0           # каждая «z» в своей фазе
        alpha = int(235 * math.sin(t * math.pi))
        px = int(w * (0.10 + 0.10 * t))     # размер растёт по мере подъёма
        x = w * (0.58 + 0.14 * t)
        y = w * (0.42 - 0.26 * t)
        d.text((x, y), "z", font=face_font(max(8, px)), fill=(255, 255, 255, alpha), anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


def render_thinking_arc(size: int) -> Image.Image:
    """Светящаяся дуга по ореолу: яркая «голова» и затухающий хвост. Вращается в tick()."""
    ss = 4
    w = size * ss
    c = w / 2
    body = w / 2 - w * HALO_WIDTH

    # Хвост: от тусклого к яркому по ходу вращения.
    tail = Image.new("L", (w, w), 0)
    td = ImageDraw.Draw(tail)
    steps = 72
    for j in range(steps):
        start = -90 - THINK_TAIL + THINK_TAIL * j / steps
        head = min(1.0, (steps - j) / 6)  # мягкий край у «головы»
        td.pieslice((0, 0, w - 1, w - 1), start, start + THINK_TAIL / steps + 1,
                    fill=int(255 * ((j + 1) / steps) ** 2 * head))

    # Поперечный профиль: ярче у края тела, к внешнему краю ореола гаснет.
    band = Image.new("L", (w, w), 0)
    bd = ImageDraw.Draw(band)
    inner = body - w * 0.025
    for i in range(24):
        t = i / 23
        rr = w / 2 - (w / 2 - inner) * t
        bd.ellipse((c - rr, c - rr, c + rr, c + rr), fill=int(255 * t ** 1.2))
    bd.ellipse((c - inner, c - inner, c + inner, c + inner), fill=0)

    arc = Image.new("RGBA", (w, w), THINK_RGB + (0,))
    arc.putalpha(ImageChops.multiply(tail, band))
    return arc.resize((size, size), Image.LANCZOS)


# --- Тёмное меню ------------------------------------------------------------

MENU_BG = "#2b2b2b"
MENU_HOVER = "#3d3d3d"
MENU_FG = "#ececec"
MENU_DIM = "#808080"
MENU_SEP = "#404040"
MENU_FONT = ("Segoe UI", 10)
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
DWMWA_BORDER_COLOR = 34


def style_popup(window):
    """Без кнопки на панели задач, без перехвата фокуса, со скруглёнными углами (Windows 11)."""
    hwnd = user32.GetParent(window.winfo_id())
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW)
    try:
        dwm = ctypes.windll.dwmapi
        corner = ctypes.c_int(DWMWCP_ROUND)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), 4)
        border = ctypes.c_uint(0x00484848)  # COLORREF (BGR)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(border), 4)
    except Exception:
        pass


class DarkMenu:
    """Всплывающее меню в тёмной теме.

    Пункт — словарь {"label", "command" | "submenu", "checked", "disabled"}, None — разделитель.
    """

    def __init__(self, pet, items, x, y, parent=None):
        self.pet, self.parent, self.child = pet, parent, None
        self.hovered = None
        s = pet.scale
        self.top = top = tk.Toplevel(pet.root)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=MENU_BG)

        body = tk.Frame(top, bg=MENU_BG, padx=int(4 * s), pady=int(4 * s))
        body.pack(fill="both", expand=True)
        for item in items:
            if item is None:
                tk.Frame(body, bg=MENU_SEP, height=max(1, int(s))).pack(fill="x", padx=int(10 * s), pady=int(4 * s))
                continue
            self.add_row(body, item)

        top.update_idletasks()
        w = max(top.winfo_reqwidth(), int(190 * s))
        h = top.winfo_reqheight()
        left, top_y, right, bottom = virtual_screen()
        if x + w > right:
            x = (parent.x if parent else x) - w
        y = max(top_y, min(y, bottom - h))
        self.x, self.y, self.w, self.h = int(x), int(y), w, h
        top.geometry(f"{w}x{h}+{self.x}+{self.y}")
        top.deiconify()
        top.update_idletasks()
        style_popup(top)

        if parent is None:
            self.armed = False
            self.watch()

    def add_row(self, body, item):
        s = self.pet.scale
        disabled = item.get("disabled", False)
        fg = MENU_DIM if disabled else MENU_FG
        row = tk.Frame(body, bg=MENU_BG)
        row.pack(fill="x")
        mark = tk.Label(row, text="✓" if item.get("checked") else "", width=2, bg=MENU_BG, fg=fg, font=MENU_FONT)
        mark.pack(side="left", padx=(int(4 * s), 0))
        arrow = tk.Label(row, text="›" if "submenu" in item else "", width=2, bg=MENU_BG, fg=fg, font=MENU_FONT)
        arrow.pack(side="right", padx=(0, int(4 * s)))
        label = tk.Label(row, text=item["label"], anchor="w", bg=MENU_BG, fg=fg, font=MENU_FONT,
                         padx=int(2 * s), pady=int(5 * s))
        label.pack(side="left", fill="x", expand=True)
        if disabled:
            return
        widgets = (row, mark, label, arrow)
        for wdg in widgets:
            wdg.bind("<Enter>", lambda e: self.on_enter(widgets, item))
            wdg.bind("<ButtonRelease-1>", lambda e: self.on_click(item, row))

    def on_enter(self, widgets, item):
        if self.hovered is widgets:
            return
        if self.hovered:
            for wdg in self.hovered:
                wdg.configure(bg=MENU_BG)
        self.hovered = widgets
        for wdg in widgets:
            wdg.configure(bg=MENU_HOVER)
        if "submenu" in item:
            self.open_submenu(item, widgets[0])
        elif self.child:
            self.child.close()
            self.child = None

    def open_submenu(self, item, row):
        if self.child:
            self.child.close()
        x = self.x + self.w + int(2 * self.pet.scale)
        y = self.y + row.winfo_y() - int(4 * self.pet.scale)
        self.child = DarkMenu(self.pet, item["submenu"](), x, y, parent=self)

    def on_click(self, item, row):
        if "submenu" in item:
            self.open_submenu(item, row)
            return
        self.root_menu().close()
        if item.get("command"):
            item["command"]()

    def root_menu(self):
        menu = self
        while menu.parent:
            menu = menu.parent
        return menu

    def contains(self, px, py):
        inside = self.x <= px < self.x + self.w and self.y <= py < self.y + self.h
        return inside or bool(self.child and self.child.contains(px, py))

    def watch(self):
        """Закрываем меню по клику мимо него или по Esc."""
        if not self.top.winfo_exists():
            return
        pressed = any(user32.GetAsyncKeyState(k) & 0x8000 for k in (0x01, 0x02, 0x04))
        if not pressed:
            self.armed = True
        elif self.armed and not self.contains(*self.pet.root.winfo_pointerxy()):
            self.close()
            return
        if user32.GetAsyncKeyState(0x1B) & 0x8000:
            self.close()
            return
        self.top.after(30, self.watch)

    def close(self):
        if self.child:
            self.child.close()
            self.child = None
        if self.top.winfo_exists():
            self.top.destroy()
        if self.parent is None and self.pet.popup is self:
            self.pet.popup = None


# --- Подсказка, уведомления, окна статистики и даты ---------------------------

TIP_FONT = ("Segoe UI", 10)
BUBBLE_BG = "#3a2a22"        # пузырь уведомления — тёплый тёмный, в тон питомцу
BUBBLE_EDGE = "#cc6844"
TEXT_FONT = ("Consolas", 10)


def place_beside(pet, w, h):
    """Координаты окна w×h рядом с питомцем: слева, если там есть место, иначе справа."""
    left, top, right, bottom = virtual_screen()
    gap = int(8 * pet.scale)
    px, py = pet.root.winfo_rootx(), pet.root.winfo_rooty()
    x = px - w - gap if px - w - gap >= left else px + pet.win + gap
    y = py + pet.win // 2 - h // 2
    return int(min(max(x, left), right - w)), int(min(max(y, top), bottom - h))


class InfoTip:
    """Подсказка при наведении: тёмная плашка без фокуса и кнопки на панели задач."""

    def __init__(self, pet):
        self.pet = pet
        self.top = tk.Toplevel(pet.root)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=MENU_BG)
        s = pet.scale
        self.label = tk.Label(self.top, justify="left", anchor="w", bg=MENU_BG, fg=MENU_FG, font=TIP_FONT,
                              padx=int(10 * s), pady=int(7 * s))
        self.label.pack()
        self.visible = False
        self.styled = False

    def show(self, text):
        if self.label.cget("text") != text:
            self.label.configure(text=text)
        self.top.update_idletasks()
        w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        x, y = place_beside(self.pet, w, h)
        self.top.geometry(f"{w}x{h}+{x}+{y}")
        if not self.visible:
            self.top.deiconify()
            self.visible = True
            if not self.styled:
                self.top.update_idletasks()
                style_popup(self.top)
                self.styled = True

    def hide(self):
        if self.visible:
            self.top.withdraw()
            self.visible = False


class Bubble:
    """Пузырь-уведомление рядом с питомцем; исчезает сам через NOTIFY_SECONDS или по клику."""

    def __init__(self, pet, text):
        self.pet = pet
        s = pet.scale
        self.top = top = tk.Toplevel(pet.root)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=BUBBLE_EDGE)
        label = tk.Label(top, text=text, justify="left", wraplength=int(300 * s), bg=BUBBLE_BG, fg=MENU_FG,
                         font=TIP_FONT, padx=int(12 * s), pady=int(9 * s), cursor="hand2")
        label.pack(padx=max(1, int(s)), pady=max(1, int(s)))
        for wdg in (top, label):
            wdg.bind("<ButtonRelease-1>", lambda e: self.close())
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        x, y = place_beside(pet, w, h)
        top.geometry(f"{w}x{h}+{x}+{y - int(h * 0.8)}")
        top.deiconify()
        top.update_idletasks()
        style_popup(top)
        top.after(NOTIFY_SECONDS * 1000, self.close)

    def close(self):
        if self.top.winfo_exists():
            self.top.destroy()
        if self.pet.bubble is self:
            self.pet.bubble = None


class StatsWindow:
    """Окно «Статистика Claude»: лимиты, сессии, токены по дням и проектам."""

    def __init__(self, pet):
        self.pet = pet
        s = pet.scale
        self.top = top = tk.Toplevel(pet.root)
        top.title("Статистика Claude")
        top.configure(bg=MENU_BG)
        top.attributes("-topmost", True)
        top.geometry(f"{int(780 * s)}x{int(660 * s)}")
        bar = tk.Frame(top, bg=MENU_BG)
        bar.pack(fill="x", padx=int(8 * s), pady=(int(8 * s), 0))
        tk.Button(bar, text="Обновить", command=self.refresh, bg=MENU_HOVER, fg=MENU_FG,
                  activebackground=MENU_SEP, activeforeground=MENU_FG, relief="flat",
                  padx=int(10 * s)).pack(side="left")
        self.text = tk.Text(top, bg="#1e1e1e", fg=MENU_FG, font=TEXT_FONT, relief="flat", wrap="none",
                            padx=int(10 * s), pady=int(8 * s), insertbackground=MENU_FG)
        self.text.pack(fill="both", expand=True, padx=int(8 * s), pady=int(8 * s))
        top.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    def refresh(self):
        self.pet.refresh_journal(wait=True)
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, self.pet.stats_report())
        self.text.configure(state="disabled")

    def close(self):
        self.top.destroy()
        self.pet.stats_window = None


class RenewalDialog:
    """Ввод даты продления подписки (ДД.ММ.ГГГГ). Локально эта дата нигде не хранится."""

    def __init__(self, pet):
        self.pet = pet
        s = pet.scale
        self.top = top = tk.Toplevel(pet.root)
        top.title("Дата продления подписки")
        top.configure(bg=MENU_BG)
        top.attributes("-topmost", True)
        top.resizable(False, False)
        pad = {"padx": int(12 * s), "pady": int(4 * s)}
        tk.Label(top, text="Дата следующего списания (ДД.ММ.ГГГГ).\n"
                           "Подписка помесячная — прошедшая дата сама\nпереносится на следующий месяц.",
                 justify="left", bg=MENU_BG, fg=MENU_FG, font=TIP_FONT).pack(anchor="w", **pad)
        self.var = tk.StringVar(value=pet.settings.get("renewal", ""))
        entry = tk.Entry(top, textvariable=self.var, font=TIP_FONT, bg="#1e1e1e", fg=MENU_FG,
                         insertbackground=MENU_FG, relief="flat", width=14)
        entry.pack(anchor="w", **pad)
        self.error = tk.Label(top, text="", bg=MENU_BG, fg="#f06050", font=TIP_FONT)
        self.error.pack(anchor="w", padx=int(12 * s))
        bar = tk.Frame(top, bg=MENU_BG)
        bar.pack(fill="x", padx=int(12 * s), pady=int(10 * s))
        for text, cmd in (("Сохранить", self.save), ("Очистить", self.clear), ("Отмена", top.destroy)):
            tk.Button(bar, text=text, command=cmd, bg=MENU_HOVER, fg=MENU_FG, activebackground=MENU_SEP,
                      activeforeground=MENU_FG, relief="flat", padx=int(10 * s)).pack(side="left", padx=(0, int(6 * s)))
        entry.bind("<Return>", lambda e: self.save())
        top.bind("<Escape>", lambda e: top.destroy())
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        x, y = place_beside(pet, w, h)
        top.geometry(f"+{x}+{y}")
        entry.focus_force()

    def save(self):
        value = self.var.get().strip()
        try:
            datetime.strptime(value, "%d.%m.%Y")
        except ValueError:
            self.error.configure(text="Нужен формат ДД.ММ.ГГГГ, например 31.10.2026")
            return
        self.pet.settings["renewal"] = value
        self.pet.save_settings()
        self.top.destroy()

    def clear(self):
        self.pet.settings.pop("renewal", None)
        self.pet.save_settings()
        self.top.destroy()


# --- Приложение ------------------------------------------------------------

class Pet:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.scale = self.root.winfo_fpixels("1i") / 96
        self.settings = self.load_settings()

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # Холст только ловит мышь; картинку окна выводит update_layered().
        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack()

        self.cache = {}
        self.shown = None
        self.drag = None
        self.next_blink = time.time() + random.uniform(2, 5)
        self.blink_start = 0.0
        self.look = [0.0, 0.0]  # сглаженное направление взгляда
        self.expand = 1.0       # 1 — развёрнут, 0 — свёрнут и полупрозрачен
        self.last_near = time.time()
        self.think = 0.0        # 0..1 — видимость дуги «Claude думает»
        self.busy = False
        self.spin = 1           # 1 — по часовой (Claude Code), -1 — против (обычный чат), 0 — оба (маятник)
        self.thinking_who = (False, False)  # (думает Claude Code, думает чат)
        self.next_busy_check = 0.0
        self.arcs = {}
        self.zs = {}

        # --- лимиты, статистика, состояния ---
        self.usage = {"limits": {}, "sessions": []}  # из status line (pet_stats.read_usage)
        self.journal = ps.JournalStats()
        self.chat_log = ps.ChatLog()  # начала ответов обычного чата — для оценки сброса лимита
        self.chat_was = False         # думал ли чат при прошлой проверке (ловим начало ответа)
        self.journal_thread = None
        self.next_journal = 0.0
        self.running = True        # был ли Claude активен за RUNNING_GRACE (иначе питомец спит)
        self.app_running = True    # запущен ли процесс claude.exe — для текста подсказки во сне
        self.last_busy = 0.0       # когда последний раз видели «Claude думает»
        self.last_touch = 0.0      # когда последний раз мышь была на питомце (сбрасывает таймер сна)
        self.app_seen = False      # был ли claude.exe при прошлой проверке (ловим момент запуска)
        self.last_launch = 0.0     # когда Claude запустили: запуск будит питомца
        self.idle_for = 0.0        # сколько секунд нет активности Claude
        self.block = None          # (окно, время сброса), если лимит исчерпан
        self.was_blocked = False
        self.hover_since = None
        self.tip = None
        self.bubble = None
        self.stats_window = None

        self.apply_size()
        x, y = self.settings.get("x"), self.settings.get("y")
        if x is None or y is None:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            x, y = sw - self.win - int(40 * self.scale), sh - self.win - int(90 * self.scale)
        self.move_to(x, y)

        self.popup = None
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<ButtonPress-3>", self.on_menu)

        self.root.deiconify()
        self.root.update_idletasks()
        self.hwnd = user32.GetParent(self.root.winfo_id())
        self.set_window_styles()
        self.tip = InfoTip(self)
        # первый разбор журналов — сразу (около 0.2 с): иначе до его окончания питомец
        # счёл бы Claude неактивным и на пару секунд «уснул» при запуске
        self.journal.refresh()
        self.next_journal = time.time() + JOURNAL_INTERVAL
        self.update_status()
        self.tick()

    # настройки
    def load_settings(self):
        for path in (SETTINGS_PATH, OLD_SETTINGS_PATH):  # старое место — для переезда настроек
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
        return {}

    def save_settings(self):
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(self.settings, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # окно
    def set_window_styles(self):
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED) & ~WS_EX_APPWINDOW
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)

    def apply_size(self):
        self.size = int(self.settings.get("size", SIZES["Средний"]) * self.scale)
        self.margin = max(3, int(4 * self.scale))
        self.win = self.size + 2 * self.margin
        self.canvas.configure(width=self.win, height=self.win)
        self.cache.clear()
        self.arcs = {}
        self.zs = {}

    def move_to(self, x, y):
        left, top, right, bottom = virtual_screen()
        x = int(min(max(x, left), right - self.win))
        y = int(min(max(y, top), bottom - self.win))
        self.root.geometry(f"{self.win}x{self.win}+{x}+{y}")

    # анимация
    def tick(self):
        now = time.time()
        if now >= self.next_blink:
            self.blink_start = now
            self.next_blink = now + random.uniform(2.5, 6)
        bt = (now - self.blink_start) / 0.18
        blink = math.sin(bt * math.pi) if 0 <= bt <= 1 else 0.0

        px, py = self.root.winfo_pointerxy()
        cx = self.root.winfo_rootx() + self.win / 2
        cy = self.root.winfo_rooty() + self.win / 2
        dx, dy = px - cx, py - cy
        dist = math.hypot(dx, dy) or 1
        k = min(dist / (140 * self.scale), 1)
        self.look[0] += (dx / dist * k - self.look[0]) * 0.35
        self.look[1] += (dy / dist * k - self.look[1]) * 0.35
        look_x, look_y = self.look

        if now >= self.next_busy_check:
            self.next_busy_check = now + 0.4
            code, chat = claude_is_thinking()
            code = code and self.settings.get("thinking", True)    # «Следить за Claude Code»
            chat = chat and self.settings.get("chat_watch", True)  # «Следить за чатом Claude»
            self.busy = code or chat
            self.thinking_who = (code, chat)  # для подсказки: кто именно думает
            if chat and not self.chat_was:
                self.chat_log.add(now)  # чат начал отвечать — запрос ушёл, окно лимита могло начаться
            self.chat_was = chat
            if self.busy:
                self.last_busy = now  # «думает» — тоже активность: питомец просыпается сразу
            if self.busy:  # пока дуга гаснет, направление не меняем
                # 1 — по часовой (Code), -1 — против (чат), 0 — оба: дуга-маятник
                self.spin = 0 if code and chat else (1 if code else -1)
        self.think += ((1.0 if self.busy else 0.0) - self.think) * 0.12
        if self.think < 0.01:
            self.think = 0.0

        # Сворачивание: в покое питомец уменьшается и становится полупрозрачным.
        # Пока Claude думает, питомец развёрнут, чтобы это было видно.
        near = dist <= self.win / 2 + 16 * self.scale
        if near or self.drag or self.popup or self.busy:
            self.last_near = now
        idle = self.settings.get("collapse", True) and now - self.last_near > IDLE_DELAY
        self.expand += ((0.0 if idle else 1.0) - self.expand) * 0.2
        if abs(self.expand - round(self.expand)) < 0.01:
            self.expand = float(round(self.expand))

        alpha = round(IDLE_ALPHA + (1 - IDLE_ALPHA) * self.expand, 2)

        size = int(self.size * (IDLE_SCALE + (1 - IDLE_SCALE) * self.expand)) // 2 * 2
        hover = dist <= size / 2 and self.drag is None
        if hover and self.app_running:
            # наведение — тоже активность: таймер сна сбрасывается, питомец просыпается сразу.
            # При выключенном Claude спит дальше — там сон не по таймеру.
            self.last_touch = now
            self.running = True
        sleeping = not self.running and not self.busy
        if sleeping:
            mood = "sleep"
        elif self.block:
            mood = "sad"
        else:
            mood = "happy" if hover else "normal"
        # цвет лимита — пока Claude включён (даже если питомец задремал от простоя);
        # Claude выключен — обычный светлый ореол
        halo = limit_color(self.limit_level()) if self.app_running or self.busy else None
        text = ps.fmt_countdown(self.block[1] - now) if self.block and not sleeping else ""
        key = (size, round(look_x * 12), round(look_y * 12), round(blink * 4), mood, halo, text)
        if key not in self.cache:
            if len(self.cache) > 2000:
                self.cache.clear()
            self.cache[key] = render(size, key[1] / 12, key[2] / 12, key[3] / 4, mood, halo, text)

        self.update_tip(now, hover and not self.popup)

        offset = self.margin + (self.size - size) // 2
        bob = round(math.sin(now * (SLEEP_BOB_SPEED if sleeping else 2.2)) * self.margin * 0.7)
        glow = round(self.think * (0.8 + 0.2 * math.sin(now * 5)), 2) if self.think else 0
        if self.spin:
            # думает кто-то один: дуга бежит по кругу в свою сторону
            direction = self.spin
            angle = int(now * THINK_SPEED * self.spin) % 360 if self.think else 0
        else:
            # думают оба: маятник — SWING_DEG по часовой, затем столько же обратно.
            # На развороте голова и хвост меняются местами, поэтому дуга там притухает.
            pos = (now * THINK_SPEED) % (2 * SWING_DEG)
            direction = 1 if pos < SWING_DEG else -1
            angle = int(pos if direction > 0 else 2 * SWING_DEG - pos)
            to_turn = min(angle, SWING_DEG - angle)
            glow = round(glow * (SWING_TURN_MIN + (1 - SWING_TURN_MIN) * min(1.0, to_turn / SWING_FADE_DEG)), 2)
        z = int((now / Z_PERIOD % 1.0) * Z_STEPS) if sleeping else -1
        state = (key, bob, alpha, self.win, angle, direction, glow, z)
        if state != self.shown:
            self.shown = state
            frame = Image.new("RGBA", (self.win, self.win), (0, 0, 0, 0))
            frame.paste(self.cache[key], (offset, offset + bob))
            if z >= 0:
                if (size, z) not in self.zs:
                    self.zs[size, z] = render_z(size, z / Z_STEPS)
                frame.alpha_composite(self.zs[size, z], (offset, offset + bob))
            if glow:
                if (size, direction) not in self.arcs:
                    arc = render_thinking_arc(size)
                    # Против часовой — зеркальная дуга, чтобы «голова» по-прежнему шла впереди хвоста.
                    self.arcs[size, direction] = arc if direction > 0 else arc.transpose(Image.FLIP_LEFT_RIGHT)
                arc = self.arcs[size, direction].rotate(-angle, resample=Image.BICUBIC)
                if glow < 1:
                    arc.putalpha(arc.getchannel("A").point(lambda a: int(a * glow)))
                frame.alpha_composite(arc, (offset, offset + bob))
            update_layered(self.hwnd, frame, alpha)
        self.root.after(33, self.tick)

    # --- лимиты, состояние Claude, уведомления ---
    def limit_level(self):
        """Максимальный % из окон 5 ч и недели (по нему цвет ореола); None — данных нет."""
        if not self.settings.get("limits", True):
            return None
        pcts = [lim["pct"] for lim in self.usage["limits"].values()]
        if self.block:
            return 100.0
        return max(pcts) if pcts else None

    def first_answer(self, lo, hi):
        """Первый ответ Claude в промежутке (lo, hi]: из журнала Claude Code или из записей чата."""
        times = [t for t in (self.journal.first_answer(lo, hi), self.chat_log.first_answer(lo, hi)) if t]
        return min(times) if times else None

    def update_status(self):
        """Раз в STATUS_INTERVAL_MS: лимиты, «запущен ли Claude», упор в лимит, уведомления."""
        now = time.time()
        try:
            self.usage = ps.read_usage(now, self.first_answer)
            # Питомец не спит, пока Claude активен: за последние RUNNING_GRACE секунд был
            # ответ в журнале Claude Code, обновление status line или «думает» (Code или чат).
            # Сам запуск Claude — тоже активность: питомец просыпается сразу и засыпает,
            # только если после запуска RUNNING_GRACE секунд ничего не происходило.
            # Открытое, но простаивающее приложение — тоже сон; процесс нужен ещё
            # для подсказки: «отдыхает» (приложение открыто) или «не запущен».
            self.app_running = claude_running()
            if self.app_running and not self.app_seen:
                self.last_launch = now
            self.app_seen = self.app_running
            activity = max([self.journal.last_answer, self.last_busy, self.last_touch, self.last_launch] +
                           [float(r.get("updated") or 0) for r in self.usage["sessions"]])
            self.running = now - activity < RUNNING_GRACE
            self.idle_for = now - activity
            if now >= self.next_journal:
                self.next_journal = now + JOURNAL_INTERVAL
                self.refresh_journal()
            # лимит исчерпан: по status line (>= 100 %) или по записи об отказе в журнале
            block = self.journal.blocked(now)
            for name, lim in self.usage["limits"].items():
                if lim["pct"] >= 100 and lim["resets_at"] and lim["resets_at"] > now:
                    if not block or lim["resets_at"] > block[1]:
                        block = (name, float(lim["resets_at"]))
            self.block = block
            if self.settings.get("notify", True):
                self.check_notifications(now)
            self.was_blocked = bool(block)
            self.status_error = None
        except Exception as e:
            # сбой статистики не должен ронять питомца, но и пропадать молча не должен
            self.status_error = f"{type(e).__name__}: {e}"
        self.write_state(now)
        self.root.after(STATUS_INTERVAL_MS, self.update_status)

    def write_state(self, now):
        """
        Текущее состояние питомца в STATE_PATH — для диагностики («почему нет цвета»,
        «почему спит»). Файл перезаписывается каждые STATUS_INTERVAL_MS.
        """
        level = self.limit_level()
        state = {
            "time": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
            "app_running": self.app_running, "active": self.running, "busy": self.busy,
            "idle_sec": round(self.idle_for), "sleeping": not self.running and not self.busy,
            "limit_level": level, "halo": limit_color(level) if self.app_running or self.busy else None,
            "limits": {k: {"pct": v["pct"], "source": v.get("source"), "age_min": round((now - v["updated"]) / 60)}
                       for k, v in self.usage["limits"].items()},
            "block": self.block, "error": getattr(self, "status_error", None),
        }
        try:
            STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def refresh_journal(self, wait=False):
        """Дочитать журналы в фоне (wait=True — дождаться, для окна статистики)."""
        if self.journal_thread and self.journal_thread.is_alive():
            if wait:
                self.journal_thread.join()
            return
        self.journal_thread = threading.Thread(target=self.journal.refresh, daemon=True)
        self.journal_thread.start()
        if wait:
            self.journal_thread.join()

    def notify(self, key, text):
        """Показать пузырь один раз на ключ; ключи хранятся в настройках между запусками."""
        notified = self.settings.setdefault("notified", [])
        if key in notified:
            return
        notified.append(key)
        del notified[:-NOTIFIED_KEEP]
        self.save_settings()
        if self.bubble:
            self.bubble.close()
        self.bubble = Bubble(self, text)

    def check_notifications(self, now):
        for name, lim in self.usage["limits"].items():
            title = "5-часовой лимит" if name == "five_hour" else "Недельный лимит"
            reset = lim["resets_at"]
            # Оценённое время сброса может сдвинуться на минуты (журнал дочитывается позже),
            # поэтому в ключ уведомления идёт не оно, а номер интервала длиной в окно.
            exact = reset if reset and not lim.get("estimated") else None
            if lim["stale"]:
                # окно сброшено; сообщаем, только если перед сбросом было тревожно
                if lim.get("last_pct", 0) >= NOTIFY_THRESHOLDS[0]:
                    reset_id = exact or int(reset // ps.WINDOW_SECONDS[name])
                    self.notify(f"{name}:{reset_id}:reset", f"🔄 {title} обновился — можно работать в полную силу.")
                continue
            crossed = [t for t in NOTIFY_THRESHOLDS if lim["pct"] >= t]
            if crossed:
                # Без времени сброса (замер приложения) окно опознаётся по номеру
                # интервала длиной в само окно — уведомление не повторится в его пределах.
                win_id = exact or int(lim["updated"] // ps.WINDOW_SECONDS[name])
                for t in crossed[:-1]:  # младшие пороги помечаем, чтобы не всплывали позже
                    self.settings.setdefault("notified", []).append(f"{name}:{win_id}:{t}")
                tail = (f"\nСброс {ps.fmt_reset(reset, now)} (через {ps.fmt_left(reset - now)})."
                        if reset else "")
                self.notify(f"{name}:{win_id}:{crossed[-1]}", f"⚠ {title}: {lim['pct']:.0f} %.{tail}")
        if self.was_blocked and not self.block:
            self.notify(f"unblock:{int(now // 60)}", "✅ Лимит снова доступен.")
        elif self.block and not self.was_blocked:
            reset = self.block[1]
            self.notify(f"block:{int(reset)}", f"⛔ Лимит исчерпан.\nСброс {ps.fmt_reset(reset, now)} "
                                               f"(через {ps.fmt_left(reset - now)}).")
        # Контекст: процент есть только у терминального Claude Code (status line),
        # для остальных сессий — порог в токенах по журналу. Ключ общий: одно уведомление на сессию.
        for sid, s in self.journal.recent_sessions(now - SESSION_FRESH):
            if s["context"] >= CONTEXT_WARN_TOKENS:
                self.notify(f"ctx:{sid}",
                            f"🧠 Контекст сессии ({self.journal.project_of(s['cwd'])}): "
                            f"{ps.fmt_tokens(s['context'])} токенов.\n"
                            "Пора сделать /compact или начать новую сессию.")
        for rec in self.usage["sessions"]:
            ctx = rec.get("context_pct")
            if ctx is not None and float(ctx) >= CONTEXT_WARN and now - float(rec["updated"]) < SESSION_FRESH:
                project = self.journal.project_of(rec.get("cwd"))
                self.notify(f"ctx:{rec['session_id']}",
                            f"🧠 Контекст сессии ({project}) заполнен на {float(ctx):.0f} %.\n"
                            "Пора сделать /compact или начать новую сессию.")
        renewal = ps.next_renewal(self.settings.get("renewal"))
        if renewal:
            left = (renewal - date.today()).days
            if left <= RENEWAL_WARN_DAYS:
                when = "сегодня" if left == 0 else f"через {left} дн."
                self.notify(f"renew:{renewal}:{date.today()}", f"💳 Подписка продлевается {when} ({renewal:%d.%m}).")

    def session_info(self, sid, s):
        """
        Данные сессии из журнала (ts, cwd, model, context в токенах), дополненные
        процентом контекста и стоимостью из status line, если он для неё работал.
        """
        info = dict(s, session_id=sid, context_pct=None, cost_usd=None)
        for rec in self.usage["sessions"]:
            if rec.get("session_id") == sid:
                info["context_pct"], info["cost_usd"] = rec.get("context_pct"), rec.get("cost_usd")
                break
        return info

    def current_session(self, now):
        """Самая свежая сессия с ответом за последние SESSION_FRESH секунд или None."""
        recent = self.journal.recent_sessions(now - SESSION_FRESH)
        return self.session_info(*recent[0]) if recent else None

    @staticmethod
    def session_line(info, now):
        """«контекст 393 тыс ток. (39 %) · opus-5-5 · 2 мин назад · $3.20» — что известно."""
        ctx = f"контекст {ps.fmt_tokens(info['context'])} ток."
        if info.get("context_pct") is not None:
            ctx += f" ({float(info['context_pct']):.0f} %)"
        parts = [ctx]
        if info.get("model"):
            parts.append(ps.short_model(info["model"]))
        parts.append(ps.fmt_since(info["ts"], now))
        if info.get("cost_usd") is not None:
            parts.append(f"${float(info['cost_usd']):.2f}")
        return " · ".join(parts)

    def limit_lines(self, now, with_source=False, icons=False):
        """
        Строки про лимиты 5 ч / неделя (для подсказки и окна статистики).
        with_source=True — добавить строку «данные на … (источник)»: только в окне статистики,
        в подсказке она лишняя. icons=True — иконки в начале строк (только подсказка:
        в окне статистики текст выровнен моноширинным шрифтом).
        """
        lines = []
        mark = (lambda icon: icon + " ") if icons else (lambda icon: "")
        if not self.settings.get("limits", True):
            return [mark("📊") + "Лимиты: показ выключен в настройках"]
        if foreign_statusline() and not self.usage["limits"]:
            return [mark("📊") + "Лимиты: недоступны — в Claude Code стоит другой status line"]
        for name, title in ps.WINDOWS.items():
            lim = self.usage["limits"].get(name)
            if not lim:
                continue
            if lim["stale"]:
                lines.append(mark("🔄") + f"{title}: сброшен, новые данные — после ответа Claude Code")
            else:
                reset = lim["resets_at"]
                approx = "~" if lim.get("estimated") else ""  # оценка по замерам приложения
                tail = (f" · сброс через {approx}{ps.fmt_left(reset - now)} ({ps.fmt_reset(reset, now)})"
                        if reset else "")
                lines.append(mark(LIMIT_ICONS[name]) + f"{title}: {lim['pct']:.0f} %{tail}")
        if not lines:
            lines.append(mark("📊") + "Лимиты: данных пока нет — придут с ответом Claude Code")
        elif with_source:
            fresh = max(self.usage["limits"].values(), key=lambda lim: lim["updated"])
            lines.append(f"   данные на {datetime.fromtimestamp(fresh['updated']):%d.%m %H:%M} "
                         f"({fresh.get('source', 'status line')})")
        return lines

    def tip_text(self):
        now = time.time()
        # Claude выключен — статистика не нужна, только приглашение открыть его кликом
        if not self.app_running and not self.busy:
            return "💤 Claude выключен — нажми, и я его открою"
        lines = []
        if not self.running and not self.busy:
            lines.append(f"💤 Claude отдыхает — нет активности {ps.fmt_left(self.idle_for)}")
        elif self.busy:
            code, chat = self.thinking_who
            who = "Claude Code и чат" if code and chat else ("Claude Code" if code else "чат")
            lines.append(f"💭 Думает: {who}…")
        if self.block:
            reset = self.block[1]
            lines.append(f"⛔ Лимит исчерпан · сброс {ps.fmt_reset(reset, now)} (через {ps.fmt_left(reset - now)})")
        lines += self.limit_lines(now, icons=True)
        info = self.current_session(now)
        if info:
            # первая строка — папка и название сессии в приложении, вторая — расход
            name = self.journal.project_of(info['cwd'])
            title = ps.session_title(info["session_id"])
            lines.append(f"📁 Сессия: {name} · {title}" if title else f"📁 Сессия: {name}")
            lines.append("🧠 " + self.session_line(info, now))
        t5 = self.journal.totals(now - ps.WINDOW_SECONDS["five_hour"])
        today = self.journal.totals(datetime.combine(date.today(), datetime.min.time()).timestamp())
        lines.append(f"🕔 За 5 ч: {t5['messages']} отв. · выход {ps.fmt_tokens(t5['output'])} ток.")
        lines.append(f"📈 Сегодня: {today['messages']} отв. · выход {ps.fmt_tokens(today['output'])} ток.")
        renewal = ps.next_renewal(self.settings.get("renewal"))
        if renewal:
            left = (renewal - date.today()).days
            if left > 0:
                lines.append(f"💳 Подписка активна {left} {ps.plural(left, 'день', 'дня', 'дней')}. "
                             f"Истекает {renewal:%d.%m.%Y}")
            else:
                lines.append(f"💳 Подписка истекает сегодня ({renewal:%d.%m.%Y})")
        return "\n".join(lines)

    def update_tip(self, now, hover):
        """Подсказка появляется после TIP_DELAY наведения и обновляется раз в полсекунды."""
        if not hover or self.drag:
            self.hover_since = None
            self.tip.hide()
            return
        if self.hover_since is None:
            self.hover_since, self.next_tip = now, 0.0
        if now - self.hover_since >= TIP_DELAY and now >= self.next_tip:
            self.next_tip = now + 0.5
            self.tip.show(self.tip_text())

    def stats_report(self):
        """Текст окна «Статистика»."""
        now = time.time()
        out = [f"Статистика Claude на {datetime.now():%d.%m.%Y %H:%M}", ""]
        out.append("ЛИМИТЫ ПОДПИСКИ (status line Claude Code и замеры приложения)")
        if self.block:
            out.append(f"  ⛔ Лимит исчерпан, сброс {ps.fmt_reset(self.block[1], now)}")
        out += ["  " + s.strip() for s in self.limit_lines(now, with_source=True)]
        renewal = ps.next_renewal(self.settings.get("renewal"))
        out.append(f"  Продление подписки: {renewal:%d.%m.%Y} (через {(renewal - date.today()).days} дн.)"
                   if renewal else "  Продление подписки: дата не задана (меню → Настройки)")
        q = self.journal.quota
        if q:
            out.append(f"  Последний упор в лимит: {datetime.fromtimestamp(q[0]):%d.%m %H:%M} "
                       f"({q[1].get('rateLimitType', '?')})")
        out.append("")

        out.append(f"СЕССИИ (последние {SESSIONS_DAYS} дн., контекст на последнем ответе)")
        sessions = self.journal.recent_sessions(now - SESSIONS_DAYS * 86400)
        if not sessions:
            out.append("  ответов за это время нет")
        for sid, s in sessions[:SESSIONS_SHOW]:
            info = self.session_info(sid, s)
            out.append(f"  {datetime.fromtimestamp(info['ts']):%d.%m %H:%M}  "
                       f"{self.journal.project_of(info['cwd'])[:11]:<12}{self.session_line(info, now)}")
        out.append("")

        t5 = self.journal.totals(now - ps.WINDOW_SECONDS["five_hour"])
        out.append("ПОСЛЕДНИЕ 5 ЧАСОВ (журналы Claude Code)")
        out.append(f"  ответов {t5['messages']} · вход {ps.fmt_tokens(t5['input'])} · выход "
                   f"{ps.fmt_tokens(t5['output'])} · кэш: запись {ps.fmt_tokens(t5['cache_write'])}, "
                   f"чтение {ps.fmt_tokens(t5['cache_read'])}")
        out.append("")

        head = f"  {'':<12}{'Ответов':>8}{'Вход':>11}{'Выход':>11}{'Кэш запись':>12}{'Кэш чтение':>12}"
        out.append(f"ПО ДНЯМ (последние {STATS_DAYS} дн.)")
        out.append(head)
        for d, a in self.journal.by_day(STATS_DAYS):
            out.append(f"  {d:%d.%m} {ps.WEEKDAYS[d.weekday()]:<6}{a[0]:>8}{ps.fmt_tokens(a[1]):>11}"
                       f"{ps.fmt_tokens(a[2]):>11}{ps.fmt_tokens(a[3]):>12}{ps.fmt_tokens(a[4]):>12}")
        out.append("")

        out.append(f"ПО ПРОЕКТАМ (последние {STATS_DAYS} дн.)")
        out.append(head)
        projects = self.journal.by_project(now - STATS_DAYS * 86400)
        total_out = sum(a[2] for a in projects.values()) or 1
        for name, a in sorted(projects.items(), key=lambda kv: -kv[1][2]):
            out.append(f"  {name[:11]:<12}{a[0]:>8}{ps.fmt_tokens(a[1]):>11}{ps.fmt_tokens(a[2]):>11}"
                       f"{ps.fmt_tokens(a[3]):>12}{ps.fmt_tokens(a[4]):>12}   {a[2] / total_out * 100:.0f} % выхода")
        out.append("")
        out.append("Обычный чат приложения в журналах не виден, но лимит у него общий —")
        out.append("проценты 5 ч / недели учитывают и его.")
        return "\n".join(out)

    def open_stats(self):
        if self.stats_window and self.stats_window.top.winfo_exists():
            self.stats_window.top.lift()
            self.stats_window.refresh()
            return
        self.stats_window = StatsWindow(self)

    def toggle_limits(self):
        self.settings["limits"] = not self.settings.get("limits", True)
        self.save_settings()
        set_statusline(self.settings["limits"])

    def toggle_notify(self):
        self.settings["notify"] = not self.settings.get("notify", True)
        self.save_settings()

    # мышь
    def on_press(self, e):
        self.drag = {"px": e.x_root, "py": e.y_root,
                     "wx": self.root.winfo_x(), "wy": self.root.winfo_y(), "moved": False,
                     "foreground": user32.GetForegroundWindow()}

    def on_drag(self, e):
        if not self.drag:
            return
        dx, dy = e.x_root - self.drag["px"], e.y_root - self.drag["py"]
        if not self.drag["moved"] and math.hypot(dx, dy) < 5 * self.scale:
            return
        self.drag["moved"] = True
        self.move_to(self.drag["wx"] + dx, self.drag["wy"] + dy)

    def on_release(self, e):
        drag, self.drag = self.drag, None
        if not drag:
            return
        if drag["moved"]:
            self.settings["x"], self.settings["y"] = self.root.winfo_x(), self.root.winfo_y()
            self.save_settings()
        else:
            self.toggle_claude(drag["foreground"])

    def toggle_claude(self, foreground=None):
        hwnd = find_claude_window()
        if hwnd is None:
            command = claude_launch_command()
            if command is None:
                user32.MessageBoxW(None, "Не удалось найти установленное приложение Claude.", "Питомец Claude", 0x30)
                return
            try:
                subprocess.Popen(command)
            except OSError:
                pass
        elif foreground == hwnd and not user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_MINIMIZE)
        else:
            bring_to_front(hwnd)

    @staticmethod
    def open_claude_link(url, what):
        """Открыть ссылку claude:// (what — что открываем, для текста ошибки); закрытое приложение запустится само."""
        try:
            os.startfile(url)
        except OSError:
            user32.MessageBoxW(None, f"Не удалось открыть {what}.", "Питомец Claude", 0x30)

    # меню
    def menu_items(self):
        # Ссылкам claude:// нужно само приложение: пока оно закрыто, доступен только «Запустить Claude»,
        # а когда запущено — наоборот. Папки открываются и без Claude.
        running = claude_running(app_only=True)
        return [
            {"label": "Запустить Claude", "command": self.toggle_claude, "disabled": running},
            {"label": "Открыть Claude", "submenu": self.chat_items, "disabled": not running},
            {"label": "Открыть Code", "submenu": self.code_items, "disabled": not running},
            {"label": "Открыть папку", "submenu": self.folder_items},
            None,
            {"label": "Статистика", "command": self.open_stats},
            None,
            {"label": "Размер", "submenu": self.size_items},
            {"label": "Настройки", "submenu": self.settings_items},
            None,
            {"label": "Закрыть питомца", "command": self.root.destroy},
        ]

    def link_item(self, label, url, what):
        """Пункт меню, открывающий ссылку claude:// (what — для текста ошибки)."""
        return {"label": label, "command": lambda: self.open_claude_link(url, what)}

    def chat_items(self):
        return [
            self.link_item("Новый чат", NEW_CHAT_URL, "новый чат Claude"),
            self.link_item("Недавние чаты", RECENT_CHATS_URL, "недавние чаты"),
            self.link_item("Проекты", PROJECTS_URL, "проекты"),
            self.link_item("Задачи", TASKS_URL, "задачи"),
            None,
            self.link_item("Коннекторы", DIRECTORY_URL, "каталог коннекторов"),
            self.link_item("Плагины и навыки", CUSTOMIZE_URL, "плагины и навыки"),
            self.link_item("Настройки", SETTINGS_URL, "настройки Claude"),
        ]

    def code_items(self):
        return [
            self.link_item("Новый чат Code", NEW_CODE_SESSION_URL, "новую сессию Claude Code"),
            self.link_item("Последний чат Code", LAST_CODE_SESSION_URL, "последнюю сессию Claude Code"),
            {"label": "Сессии", "submenu": self.session_items},
            None,
            self.link_item("Ждут ответа", NEEDS_INPUT_URL, "сессии, ждущие ответа"),
            self.link_item("Поиск сессий", CODE_SEARCH_URL, "поиск сессий Claude Code"),
        ]

    def session_items(self):
        """Сегодняшние сессии вкладки Code (была активность сегодня), сначала свежие: название или папка."""
        today = datetime.combine(date.today(), datetime.min.time()).timestamp()
        sessions = [s for s in ps.app_sessions(None) if s["ts"] >= today][:SESSIONS_MENU_MAX]
        if not sessions:
            return [{"label": "Сегодня сессий нет", "disabled": True}]
        items = []
        for s in sessions:
            label = s["title"] or Path(s["cwd"]).name or s["id"]
            if len(label) > SESSION_LABEL_MAX:
                label = label[:SESSION_LABEL_MAX - 1].rstrip() + "…"
            items.append(self.link_item(label, CODE_SESSION_URL.format(id=s["id"]), "сессию Claude Code"))
        return items

    def size_items(self):
        current = self.settings.get("size", SIZES["Средний"])
        return [{"label": name, "checked": value == current, "command": lambda v=value: self.on_size(v)}
                for name, value in SIZES.items()]

    def settings_items(self):
        return [
            {"label": "Сворачиваться в покое", "checked": self.settings.get("collapse", True),
             "command": self.toggle_collapse},
            {"label": "Следить за чатом Claude", "checked": self.settings.get("chat_watch", True),
             "command": self.toggle_chat_watch},
            {"label": "Следить за Claude Code", "checked": self.settings.get("thinking", True),
             "command": self.toggle_thinking},
            {"label": "Показывать лимиты подписки", "checked": self.settings.get("limits", True),
             "command": self.toggle_limits},
            {"label": "Уведомления", "checked": self.settings.get("notify", True),
             "command": self.toggle_notify},
            {"label": "Дата продления подписки…", "command": lambda: RenewalDialog(self)},
            None,
            {"label": "Запускать вместе с Windows", "checked": autostart_enabled(),
             "command": lambda: set_autostart(not autostart_enabled())},
        ]

    def folder_items(self):
        """
        Все папки проектов, с которыми работал Claude (приложение, Claude Code, журналы),
        сначала недавние. Родительским путём подписываются папки с одинаковым именем
        и папки, лежащие не там, где большинство проектов.
        """
        folders = ps.project_folders(PROJECTS_ROOT, dict(self.journal.cwds))
        if not folders:
            return [{"label": "Папок проектов пока нет", "disabled": True}]
        names = [p.name.lower() for p, _ in folders]
        parents = [ps._norm(p.parent) for p, _ in folders]
        root = max(set(parents), key=parents.count)   # где лежит большинство проектов
        items = []
        for p, ts in folders[:FOLDERS_MAX]:
            label = p.name
            if names.count(p.name.lower()) > 1 or ps._norm(p.parent) != root:
                label += f"   ({p.parent})"
            if ts:
                label += f"   · {ps.fmt_ago(ts)}"
            items.append({"label": label, "command": lambda f=p: os.startfile(f)})
        return items

    def on_menu(self, e):
        if self.popup:
            self.popup.close()
        self.popup = DarkMenu(self, self.menu_items(), e.x_root, e.y_root)

    def toggle_thinking(self):
        self.settings["thinking"] = not self.settings.get("thinking", True)
        self.save_settings()
        clear_code_markers()
        set_thinking_hooks(self.settings["thinking"])

    def toggle_chat_watch(self):
        self.settings["chat_watch"] = not self.settings.get("chat_watch", True)
        self.save_settings()
        if self.settings["chat_watch"]:
            self.start_chat_watch()
        else:
            self.stop_chat_watch()

    # Наблюдатель за обычным чатом: скрытый PowerShell, ищет в окне Claude кнопку «Stop response».
    def start_chat_watch(self):
        if getattr(self, "chat_watch", None) and self.chat_watch.poll() is None:
            return
        try:
            self.chat_watch = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-File", str(CHAT_WATCH_SCRIPT),
                 "-Marker", str(CHAT_MARKER), "-ParentPid", str(os.getpid())],
                creationflags=0x08000000)  # CREATE_NO_WINDOW
        except OSError:
            self.chat_watch = None

    def stop_chat_watch(self):
        if getattr(self, "chat_watch", None) and self.chat_watch.poll() is None:
            self.chat_watch.terminate()
        self.chat_watch = None
        CHAT_MARKER.unlink(missing_ok=True)

    def toggle_collapse(self):
        self.settings["collapse"] = not self.settings.get("collapse", True)
        self.save_settings()

    def on_size(self, size):
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.settings["size"] = size
        self.save_settings()
        self.apply_size()
        self.move_to(x, y)

    def run(self):
        if self.settings.get("chat_watch", True):
            self.start_chat_watch()
        try:
            self.root.mainloop()
        finally:
            self.stop_chat_watch()


if __name__ == "__main__":
    set_dpi_awareness()
    if single_instance():
        refresh_autostart()
        pet = Pet()
        # Хуки пишутся с путями этого ПК — после переноса папки они обновятся сами.
        set_thinking_hooks(pet.settings.get("thinking", True))
        # status line с лимитами подписки (чужой status line не трогается)
        set_statusline(pet.settings.get("limits", True))
        pet.run()
