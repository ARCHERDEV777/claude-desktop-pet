"""Хук Claude Code для питомца: отмечает, что Claude сейчас думает.

Вызывается из ~/.claude/settings.json:
  pet_hook.py start — запрос отправлен / Claude работает (UserPromptSubmit, PostToolUse);
  pet_hook.py stop  — ответ закончен (Stop, StopFailure, SessionEnd).

Для каждой сессии создаётся файл-метка в %USERPROFILE%\\.claude-desktop-pet\\busy
(не в %APPDATA%: Claude из Microsoft Store подменяет её для запускаемых им программ);
питомец крутит ореол, пока есть свежие метки. Скрипт ничего не печатает
(вывод UserPromptSubmit попал бы в контекст Claude) и никогда не падает.
"""

import json
import os
import re
import sys
from pathlib import Path

BUSY_DIR = Path.home() / ".claude-desktop-pet" / "busy"


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id", ""))) or "unknown"
    marker = BUSY_DIR / session
    if action == "start":
        BUSY_DIR.mkdir(parents=True, exist_ok=True)
        # путь к журналу сессии: по нему питомец проверяет, что сессия ещё жива
        marker.write_text(str(data.get("transcript_path", "")), encoding="utf-8")
    elif action == "stop":
        marker.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
