"""Сбор статистики Claude для питомца.

Источники:
  1. Файлы status line (pet_statusline.py) в ~/.claude-desktop-pet/usage/*.json:
     проценты 5-часового и недельного лимита, время сброса, контекст и стоимость сессий.
  2. plan-usage-history.json десктоп-приложения Claude: замеры процентов лимитов
     (fh — 5 часов, sd — неделя) без времени сброса. Файл внутренний и
     недокументированный: если формат изменится, источник просто пропадёт.
  3. Журналы сессий Claude Code ~/.claude/projects/**/*.jsonl:
     токены каждого ответа (по дням, проектам, за последние 5 часов) и записи
     quotaLimits — момент упора в лимит и время его сброса.
  4. Папки проектов: сессии вкладки Code, git-worktrees.json, ~/.claude.json, журналы.

Журналы читаются инкрементально: для каждого файла запоминается позиция,
при следующем обновлении дочитываются только новые строки.
Модуль не зависит от tkinter — его можно проверять отдельно.
"""

import json
import os
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from pet_i18n import tr

USAGE_DIR = Path.home() / ".claude-desktop-pet" / "usage"
# Каталог Claude Code: по умолчанию ~/.claude, но его можно перенести переменной
# окружения CLAUDE_CONFIG_DIR — тогда там же лежат settings.json, журналы и .claude.json.
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
JOURNALS_DIR = CLAUDE_DIR / "projects"
CLI_CONFIGS = [CLAUDE_DIR / ".claude.json", Path.home() / ".claude.json"]  # ключ "projects" — папки проектов


def app_data_dirs():
    """
    Папки данных десктоп-приложения Claude. Обычная установка — %APPDATA%\\Claude;
    версия из Microsoft Store может держать их в своей песочнице Packages\\Claude_*.
    """
    dirs = []
    roaming = os.environ.get("APPDATA")
    if roaming:
        dirs.append(Path(roaming) / "Claude")
    packages = Path.home() / "AppData" / "Local" / "Packages"
    try:
        dirs += [p / "LocalCache" / "Roaming" / "Claude" for p in packages.glob("Claude_*")]
    except OSError:
        pass
    return [d for d in dirs if d.is_dir()]


APP_USAGE_FILE = "plan-usage-history.json"
APP_USAGE_KEYS = {"five_hour": "fh", "seven_day": "sd"}

WINDOWS = {"five_hour": "5 часов", "seven_day": "Неделя"}
WINDOW_SECONDS = {"five_hour": 5 * 3600, "seven_day": 7 * 86400}
# Окна, чьё время сброса оцениваем по замерам приложения, если status line его не дал.
# Неделю не оцениваем: её отсчёт привязан к аккаунту, а не к первому запросу.
ESTIMATE_RESET_WINDOWS = ("five_hour",)
SESSION_FILE_TTL = 3 * 86400     # файлы status line старше — удаляются
RETENTION_DAYS = 35              # сколько дней журнальных записей держать в памяти
SYNTHETIC_MODEL = "<synthetic>"  # служебные ответы Claude Code (например, отказ по лимиту)


# --- Форматирование -----------------------------------------------------------

def fmt_tokens(n):
    """1234 → «1.2 тыс», 2_500_000 → «2.5 млн»."""
    n = float(n or 0)
    if n >= 1e9:
        return tr("{n:.1f} млрд", n=n / 1e9)
    if n >= 1e6:
        return tr("{n:.1f} млн", n=n / 1e6)
    if n >= 1e3:
        return tr("{n:.1f} тыс", n=n / 1e3)
    return f"{n:.0f}"


def fmt_left(seconds):
    """Оставшееся время: «2 ч 05 мин», «45 мин», «3 дн 4 ч»."""
    s = max(0, int(seconds))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return tr("{d} дн {h} ч", d=d, h=h)
    if h:
        return tr("{h} ч {m:02d} мин", h=h, m=m)
    return tr("{m} мин", m=m)


def fmt_countdown(seconds):
    """Короткий таймер для мордочки питомца: «2:05» (ч:мин) или «45м»."""
    s = max(0, int(seconds))
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}:{m:02d}" if h else tr("{m}м", m=max(m, 1))


WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def weekday_name(i):
    """Короткое название дня недели (0 — понедельник) на текущем языке."""
    return tr(WEEKDAYS[i])


def fmt_since(ts, now=None):
    """Давность в пределах суток: «только что», «12 мин назад», «3 ч назад»; дальше — дата."""
    s = (now or time.time()) - ts
    if s < 60:
        return tr("только что")
    if s < 3600:
        return tr("{n} мин назад", n=int(s // 60))
    if s < 86400:
        return tr("{n} ч назад", n=int(s // 3600))
    return fmt_ago(ts, now)


def short_model(model):
    """«claude-opus-5-5» → «opus-5-5»: в подсказке префикс лишний."""
    return (model or "").removeprefix("claude-")


def fmt_ago(ts, now=None):
    """Когда была последняя работа: «сегодня», «вчера», «3 дн. назад», «12.09»."""
    now = now or time.time()
    days = (datetime.fromtimestamp(now).date() - datetime.fromtimestamp(ts).date()).days
    if days <= 0:
        return tr("сегодня")
    if days == 1:
        return tr("вчера")
    if days < 7:
        return tr("{n} дн. назад", n=days)
    return f"{datetime.fromtimestamp(ts):%d.%m.%Y}"


def fmt_reset(ts, now=None):
    """Время сброса: «18:40» сегодня, «завтра 09:10» или «пн 10:00»."""
    now = now or time.time()
    dt, today = datetime.fromtimestamp(ts), datetime.fromtimestamp(now).date()
    if dt.date() == today:
        return f"{dt:%H:%M}"
    if dt.date() == today + timedelta(days=1):
        return tr("завтра {at:%H:%M}", at=dt)
    return f"{weekday_name(dt.weekday())} {dt:%d.%m %H:%M}"


# --- Status line ---------------------------------------------------------------

def read_usage(now=None, first_answer=None):
    """
    Сводка из файлов status line.

    Возвращает {"limits": {окно: {"pct", "resets_at", "updated"}}, "sessions": [...]}.
    Лимиты общие для аккаунта, поэтому по каждому окну берётся самый свежий файл.
    Окно, у которого время сброса уже прошло, считается сброшенным: pct = 0
    и "stale" = True (новых данных ещё нет — придут со следующим ответом Claude).
    first_answer(lo, hi) — первый ответ Claude в промежутке (журнал Code и ChatLog):
    уточняет оценку сброса.
    """
    now = now or time.time()
    limits, sessions = {}, []
    try:
        files = list(USAGE_DIR.glob("*.json"))
    except OSError:
        files = []
    for f in files:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        updated = float(rec.get("updated") or 0)
        if now - updated > SESSION_FILE_TTL:
            f.unlink(missing_ok=True)
            continue
        sessions.append(rec)
        for name, lim in (rec.get("rate_limits") or {}).items():
            if name in WINDOWS and lim.get("used_percentage") is not None:
                if name not in limits or updated > limits[name]["updated"]:
                    limits[name] = {"pct": float(lim["used_percentage"]),
                                    "resets_at": lim.get("resets_at"), "updated": updated}
    # Замеры десктоп-приложения: берутся, если они свежее status line.
    # Время сброса в них нет — оставляем его из status line, если оно ещё впереди,
    # иначе для окон из ESTIMATE_RESET_WINDOWS оцениваем по истории замеров ("estimated").
    for name, (pct, t) in read_app_usage(now).items():
        cur = limits.get(name)
        if cur is None or t > cur["updated"]:
            reset = cur["resets_at"] if cur and cur["resets_at"] and cur["resets_at"] > now else None
            estimated = False
            if reset is None and name in ESTIMATE_RESET_WINDOWS:
                reset = estimate_app_reset(name, first_answer)
                estimated = reset is not None
            limits[name] = {"pct": pct, "resets_at": reset, "updated": t, "source": "приложение",
                            "estimated": estimated}
    for lim in limits.values():
        lim.setdefault("source", "status line")
        lim["stale"] = bool(lim["resets_at"]) and lim["resets_at"] <= now
        lim["last_pct"] = lim["pct"]   # значение до сброса — для уведомления «лимит обновился»
        if lim["stale"]:
            lim["pct"] = 0.0
    sessions.sort(key=lambda r: -float(r.get("updated") or 0))
    return {"limits": limits, "sessions": sessions}


def read_app_usage(now=None):
    """
    Последний замер лимитов из plan-usage-history.json приложения:
    {окно: (процент, время замера)}. Замер старше длины окна отбрасывается —
    за это время окно гарантированно сбросилось, и процент уже неверен.
    """
    now = now or time.time()
    best = {}
    for d in app_data_dirs():
        try:
            samples = json.loads((d / APP_USAGE_FILE).read_text(encoding="utf-8")).get("samples") or []
        except (OSError, ValueError, AttributeError):
            continue
        for s in samples:
            try:
                t = float(s["t"]) / 1000
                u = s.get("u") or {}
            except (KeyError, TypeError, ValueError):
                continue
            for name, key in APP_USAGE_KEYS.items():
                if u.get(key) is None or now - t > WINDOW_SECONDS[name]:
                    continue
                if name not in best or t > best[name][1]:
                    best[name] = (float(u[key]), t)
    return best


CHAT_LOG_PATH = USAGE_DIR.parent / "chat_answers.json"  # когда начинались ответы обычного чата
CHAT_LOG_KEEP = 2 * 86400   # сколько секунд хранить эти записи: оценке сброса нужны последние окна


class ChatLog:
    """
    Время начала ответов обычного чата (их видит наблюдатель chat_watch.ps1, в журналах
    Claude Code их нет) — чтобы и для чата знать, когда началось окно лимита.
    Хранится в CHAT_LOG_PATH списком отметок времени, переживает перезапуск питомца.
    """

    def __init__(self):
        try:
            data = json.loads(CHAT_LOG_PATH.read_text(encoding="utf-8"))
            self.times = sorted(float(t) for t in data if isinstance(t, (int, float)))
        except (OSError, ValueError, TypeError):
            self.times = []

    def add(self, ts):
        """Отметить начало ответа; старше CHAT_LOG_KEEP — выбросить. Сбой записи не страшен."""
        self.times = [t for t in self.times if ts - t < CHAT_LOG_KEEP] + [ts]
        try:
            CHAT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = CHAT_LOG_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps([round(t, 1) for t in self.times]), encoding="utf-8")
            os.replace(tmp, CHAT_LOG_PATH)
        except OSError:
            pass

    def first_answer(self, lo, hi):
        """Первое начало ответа чата в промежутке (lo, hi] или None."""
        return next((t for t in self.times if lo < t <= hi), None)


def app_usage_series(key):
    """Все замеры одного окна из plan-usage-history.json: [(время, процент)] по возрастанию времени."""
    points = {}
    for d in app_data_dirs():
        try:
            samples = json.loads((d / APP_USAGE_FILE).read_text(encoding="utf-8")).get("samples") or []
        except (OSError, ValueError, AttributeError):
            continue
        for s in samples:
            try:
                v = (s.get("u") or {}).get(key)
                if v is not None:
                    points[float(s["t"]) / 1000] = float(v)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
    return sorted(points.items())


def estimate_app_reset(name, first_answer=None):
    """
    Оценка времени сброса окна по замерам приложения (в них самих времени сброса нет).

    Окно начинается с первого запроса после прошлого сброса и длится WINDOW_SECONDS.
    Идём по замерам: новое окно началось между двумя замерами, если процент вырос
    с нуля, упал (окно сбросилось) или прошлое окно к этому замеру уже истекло.
    Момент начала уточняем первым ответом в этом промежутке — в журнале Claude Code
    или в ChatLog обычного чата (first_answer(lo, hi) -> время или None), иначе берём время замера — тогда
    оценка позже настоящей не больше чем на интервал между замерами.
    None — оценить нельзя (история начинается посреди окна, а сброса в ней ещё не было).
    Время в прошлом — окно уже истекло, новых замеров после этого не было.
    """
    window = WINDOW_SECONDS[name]
    start, known = None, False  # known — состояние окна известно (до первого замера — нет)
    prev_t = prev_v = None

    def begin(lo, hi):
        if first_answer and lo is not None:
            ts = first_answer(lo, hi)
            if ts:
                return ts
        return hi

    for t, v in app_usage_series(APP_USAGE_KEYS[name]):
        lo = prev_t
        if start is not None and t >= start + window:   # окно истекло между замерами
            lo = max(lo, start + window) if lo is not None else start + window
            start, known = None, True
        dropped = prev_v is not None and v < prev_v
        if v <= 0:
            if dropped or start is None:
                start, known = None, True
        elif dropped:
            # lo — не раньше конца прошлого окна: ответы до него ещё относились к старому окну
            start, known = begin(lo, t), True
        elif start is None and known:
            start = begin(lo, t)
        prev_t, prev_v = t, v
    return start + window if start is not None else None


# --- Папки проектов ---------------------------------------------------------------

def _norm(path):
    """Ключ для сравнения путей Windows: регистр и вид слешей не важны."""
    return os.path.normcase(os.path.normpath(str(path)))


def _app_session_records():
    """Записи сессий вкладки Code приложения (local_*.json) как словари."""
    for d in app_data_dirs():
        try:
            files = list((d / "claude-code-sessions").glob("*/*/local_*.json"))
        except OSError:
            continue
        for f in files:
            try:
                yield json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue


def session_title(sid):
    """
    Название сессии в боковой панели приложения (вкладка Code) по id журнала
    Claude Code (в записи приложения это cliSessionId); None — сессия не из приложения.
    """
    if not sid:
        return None
    for s in _app_session_records():
        if s.get("cliSessionId") == sid:
            return (s.get("title") or "").strip() or None
    return None


def app_sessions(limit):
    """
    Неархивные сессии вкладки Code, сначала недавние, не больше limit (None — все):
    [{"id": "local_…", "title", "cwd", "ts"}] — id подходит для ссылки claude://code/continue.
    """
    out, seen = [], set()
    for s in _app_session_records():
        sid = str(s.get("sessionId") or "")
        # одна и та же папка данных может найтись по двум путям (Store подменяет %APPDATA%)
        if not sid.startswith("local_") or s.get("isArchived") or sid in seen:
            continue
        seen.add(sid)
        ts = max(float(s.get("lastActivityAt") or 0), float(s.get("createdAt") or 0)) / 1000
        out.append({"id": sid, "title": (s.get("title") or "").strip(),
                    "cwd": s.get("cwd") or s.get("originCwd") or "", "ts": ts})
    out.sort(key=lambda x: -x["ts"])
    return out[:limit]


def project_folders(candidate_root=None, journal_cwds=None):
    """
    Все папки, с которыми работал Claude: [(Path, время последней работы или 0)],
    сначала недавние. Источники: сессии вкладки Code приложения (cwd, lastActivityAt),
    git-worktrees.json приложения, проекты Claude Code CLI (.claude.json),
    рабочие папки из журналов. Несуществующие папки и временные scratch-папки
    приложения пропускаются.

    candidate_root — папка, где МОГУТ лежать проекты (у питомца — его родительская
    папка). Её подпапки добавляются, только если хоть один известный Claude проект
    лежит прямо в ней: так новый, ещё пустой проект рядом с остальными тоже виден,
    а питомец, положенный, например, в «Загрузки», не вытащит в меню весь мусор оттуда.
    """
    found = {}  # нормализованный путь -> (Path, время)

    def add(path, ts=0.0):
        if not path:
            return
        p = Path(str(path))
        key = _norm(p)
        if "scratch-workspaces" in key or ".claude-desktop-pet" in key:
            return
        old = found.get(key)
        if old is None or ts > old[1]:
            found[key] = (old[0] if old else p, max(ts, old[1] if old else 0.0))

    for d in app_data_dirs():
        try:
            for f in (d / "claude-code-sessions").glob("*/*/local_*.json"):
                try:
                    s = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                ts = max(float(s.get("lastActivityAt") or 0), float(s.get("createdAt") or 0)) / 1000
                add(s.get("cwd") or s.get("originCwd"), ts)
        except OSError:
            pass
        try:
            cwds = json.loads((d / "git-worktrees.json").read_text(encoding="utf-8"))
            for path in ((cwds.get("untrackedDirGc") or {}).get("cwds") or {}):
                add(path)
        except (OSError, ValueError, AttributeError):
            pass
    for cfg in CLI_CONFIGS:
        try:
            for path in (json.loads(cfg.read_text(encoding="utf-8")).get("projects") or {}):
                add(path)
        except (OSError, ValueError, AttributeError):
            pass
    for path, ts in (journal_cwds or {}).items():
        add(path, ts)
    if candidate_root:
        root = _norm(candidate_root)
        if any(_norm(p.parent) == root for p, _ in found.values()):
            try:
                for p in Path(candidate_root).iterdir():
                    if p.is_dir() and not p.name.startswith((".", "_")):
                        add(p)
            except OSError:
                pass

    result = [(p, ts) for p, ts in found.values() if p.is_dir()]
    result.sort(key=lambda x: (-x[1], x[0].name.lower()))
    return result


# --- Журналы Claude Code --------------------------------------------------------

class JournalStats:
    """Инкрементальный разбор журналов: токены по ответам и записи о лимитах."""

    def __init__(self):
        self.lock = threading.Lock()
        self.offsets = {}        # файл -> позиция, до которой прочитан
        self.seen = set()        # (message.id, requestId): ответ пишется в журнал несколько раз
        self.records = []        # (ts, рабочая папка, input, output, cache_write, cache_read)
        self.quota = None        # последняя запись quotaLimits: (ts, dict)
        self.last_answer = 0.0   # время последнего настоящего ответа модели
        self.cwds = {}           # рабочая папка -> время последнего ответа в ней
        # сессия -> последний ответ основной ветки: {"ts", "cwd", "model", "context"};
        # context — токенов в контексте на этом ответе (вход + чтение и запись кэша)
        self.sessions = {}
        self.updated = 0.0

    def project_of(self, cwd):
        """
        Имя проекта по рабочей папке, без привязки к расположению питомца.
        Проект — самая короткая из известных рабочих папок, внутри которой лежит cwd:
        сессию обычно открывают в корне проекта, а Claude может уходить во вложенные папки.
        """
        if not cwd:
            return "—"
        key = _norm(cwd)
        if "scratch-workspaces" in key:
            return tr("прочее")
        best = cwd
        for known in list(self.cwds):
            k = _norm(known)
            if (key == k or key.startswith(k.rstrip("\\/") + os.sep)) and len(k) < len(_norm(best)):
                best = known
        return Path(best).name or str(best)

    def refresh(self):
        """Дочитать новые строки во всех журналах. Безопасно вызывать из фонового потока."""
        try:
            files = list(JOURNALS_DIR.rglob("*.jsonl"))
        except OSError:
            return
        new_records, quota, last_answer = [], None, 0.0
        for f in files:
            try:
                size = f.stat().st_size
                pos = self.offsets.get(f, 0)
                if size < pos:            # файл перезаписали — читаем заново
                    pos = 0
                if size == pos:
                    continue
                with open(f, "rb") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
                # недописанная последняя строка останется на следующий раз
                end = chunk.rfind(b"\n") + 1
                self.offsets[f] = pos + end
                for line in chunk[:end].splitlines():
                    self._parse(line, new_records)
                    q = self._quota(line)
                    if q and (quota is None or q[0] > quota[0]):
                        quota = q
            except OSError:
                continue
        if new_records:
            last_answer = max(r[0] for r in new_records)
        cutoff = time.time() - RETENTION_DAYS * 86400
        with self.lock:
            self.records = [r for r in self.records + new_records if r[0] >= cutoff]
            if quota and (self.quota is None or quota[0] > self.quota[0]):
                self.quota = quota
            self.last_answer = max(self.last_answer, last_answer)
            self.updated = time.time()

    def _parse(self, line, out):
        if b'"usage"' not in line:
            return
        try:
            d = json.loads(line)
        except ValueError:
            return
        msg = d.get("message")
        if d.get("type") != "assistant" or not isinstance(msg, dict):
            return
        usage = msg.get("usage")
        if not isinstance(usage, dict) or msg.get("model") == SYNTHETIC_MODEL:
            return
        key = (msg.get("id"), d.get("requestId"))
        if key != (None, None):
            if key in self.seen:
                return
            self.seen.add(key)
        ts = _ts(d.get("timestamp"))
        if ts is None:
            return
        cwd = d.get("cwd")
        if cwd and ts > self.cwds.get(cwd, 0.0):
            self.cwds[cwd] = ts
        # Контекст сессии — по последнему ответу основной ветки. Ответы субагентов
        # (isSidechain) идут в своём, отдельном контексте, их не смешиваем.
        sid = d.get("sessionId")
        if sid and not d.get("isSidechain"):
            old = self.sessions.get(sid)
            if old is None or ts >= old["ts"]:
                self.sessions[sid] = {
                    "ts": ts, "cwd": cwd, "model": msg.get("model"),
                    "context": int(usage.get("input_tokens") or 0)
                               + int(usage.get("cache_read_input_tokens") or 0)
                               + int(usage.get("cache_creation_input_tokens") or 0),
                }
        # храним саму папку: имя проекта считается при выборке, когда известны все папки
        out.append((ts, cwd,
                    int(usage.get("input_tokens") or 0),
                    int(usage.get("output_tokens") or 0),
                    int(usage.get("cache_creation_input_tokens") or 0),
                    int(usage.get("cache_read_input_tokens") or 0)))

    @staticmethod
    def _quota(line):
        if b'"quotaLimits"' not in line:
            return None
        try:
            d = json.loads(line)
        except ValueError:
            return None
        q, ts = d.get("quotaLimits"), _ts(d.get("timestamp"))
        return (ts, q) if isinstance(q, dict) and ts else None

    # --- выборки ---

    def first_answer(self, lo, hi):
        """Время первого ответа модели в промежутке (lo, hi] или None — для оценки начала окна лимита."""
        with self.lock:
            times = [r[0] for r in self.records if lo < r[0] <= hi]
        return min(times) if times else None

    def totals(self, since):
        """Суммы с момента since: сообщений, вход, выход, запись в кэш, чтение кэша."""
        with self.lock:
            sel = [r for r in self.records if r[0] >= since]
        return {"messages": len(sel),
                "input": sum(r[2] for r in sel), "output": sum(r[3] for r in sel),
                "cache_write": sum(r[4] for r in sel), "cache_read": sum(r[5] for r in sel)}

    def by_day(self, days):
        """[(дата, суммы)] за последние days дней, от новых к старым (пустые дни тоже)."""
        today = date.today()
        agg = defaultdict(lambda: [0, 0, 0, 0, 0])
        with self.lock:
            for r in self.records:
                d = datetime.fromtimestamp(r[0]).date()
                if (today - d).days < days:
                    a = agg[d]
                    a[0] += 1
                    for i in range(4):
                        a[i + 1] += r[i + 2]
        return [(today - timedelta(days=i), agg.get(today - timedelta(days=i), [0] * 5))
                for i in range(days)]

    def by_project(self, since):
        """{проект: [сообщений, вход, выход, запись в кэш, чтение кэша]} с момента since."""
        agg = defaultdict(lambda: [0, 0, 0, 0, 0])
        names = {}  # рабочая папка -> имя проекта (папок мало, записей много)
        with self.lock:
            for r in self.records:
                if r[0] >= since:
                    if r[1] not in names:
                        names[r[1]] = self.project_of(r[1])
                    a = agg[names[r[1]]]
                    a[0] += 1
                    for i in range(4):
                        a[i + 1] += r[i + 2]
        return dict(agg)

    def recent_sessions(self, since):
        """[(id сессии, данные)] с ответами после since, сначала свежие."""
        # list() снимает копию разом: словарь пополняется фоновым потоком разбора журналов
        items = [(sid, dict(s)) for sid, s in list(self.sessions.items()) if s["ts"] >= since]
        items.sort(key=lambda x: -x[1]["ts"])
        return items

    def blocked(self, now=None):
        """
        Упор в лимит по журналу: (тип окна, время сброса) или None.
        Считается действующим, если сброс ещё не наступил и после отказа
        не было ни одного настоящего ответа модели.
        """
        now = now or time.time()
        with self.lock:
            q, last = self.quota, self.last_answer
        if not q:
            return None
        ts, info = q
        reset = info.get("resetsAt")
        if info.get("status") == "rejected" and reset and reset > now and last <= ts:
            return info.get("rateLimitType") or "five_hour", float(reset)
        return None


def _ts(value):
    """ISO-время журнала («2026-10-17T18:22:20.058Z») → секунды эпохи."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# --- Дата продления подписки ------------------------------------------------------

def next_renewal(stored, today=None):
    """
    Ближайшая дата продления по введённой пользователем дате (ДД.ММ.ГГГГ).
    Подписка помесячная: если дата прошла, переносим на тот же день следующих
    месяцев (31-е в коротком месяце — последний день месяца).
    """
    if not stored:
        return None
    try:
        d = datetime.strptime(stored, "%d.%m.%Y").date()
    except ValueError:
        return None
    today = today or date.today()
    day, y, m = d.day, d.year, d.month
    while d < today:
        m += 1
        if m > 12:
            y, m = y + 1, 1
        last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
        d = date(y, m, min(day, last))
    return d
