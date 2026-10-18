"""Status line Claude Code для питомца: лимиты подписки и состояние сессии.

Вызывается из ~/.claude/settings.json → "statusLine". Claude Code передаёт на stdin
JSON сессии (см. https://code.claude.com/docs/en/statusline). Скрипт:
  • сохраняет нужное в %USERPROFILE%\\.claude-desktop-pet\\usage\\<session_id>.json —
    по файлу на сессию, чтобы параллельные сессии не затирали друг друга;
  • печатает короткую строку для нижней панели Claude Code.

Поля rate_limits приходят только подписчикам Pro/Max и только после первого
ответа в сессии; любое поле может отсутствовать. Скрипт никогда не падает.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

USAGE_DIR = Path.home() / ".claude-desktop-pet" / "usage"
WINDOWS = ("five_hour", "seven_day")


def pick(d, *path):
    """Безопасно достать вложенное поле: pick(data, "a", "b") → data["a"]["b"] или None."""
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def main():
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id", ""))) or "unknown"

    limits = {}
    for name in WINDOWS:
        pct = pick(data, "rate_limits", name, "used_percentage")
        reset = pick(data, "rate_limits", name, "resets_at")
        if pct is not None:
            limits[name] = {"used_percentage": float(pct), "resets_at": reset}

    record = {
        "updated": time.time(),
        "session_id": session,
        "cwd": pick(data, "workspace", "current_dir") or data.get("cwd"),
        "model": pick(data, "model", "display_name"),
        "context_pct": pick(data, "context_window", "used_percentage"),
        "cost_usd": pick(data, "cost", "total_cost_usd"),
        "rate_limits": limits,
    }
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = USAGE_DIR / f"{session}.json"
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)

    # Строка для Claude Code: «5ч 23% до 18:40 · нед 41% · ctx 8%»
    parts = []
    for name, short in (("five_hour", "5ч"), ("seven_day", "нед")):
        lim = limits.get(name)
        if lim:
            text = f"{short} {lim['used_percentage']:.0f}%"
            if name == "five_hour" and lim.get("resets_at"):
                text += f" до {datetime.fromtimestamp(lim['resets_at']):%H:%M}"
            parts.append(text)
    if record["context_pct"] is not None:
        parts.append(f"ctx {float(record['context_pct']):.0f}%")
    if parts:
        sys.stdout.buffer.write(" · ".join(parts).encode("utf-8"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
