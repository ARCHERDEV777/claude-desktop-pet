# Claude Desktop Pet

**English** | [Русский](README.ru.md)

A small desktop pet for Windows that keeps you company while you work with the Claude app and Claude Code. It is a round little face that floats above all windows. It shows when Claude is thinking, how much of your subscription limit you have used, and whether Claude is running at all.

![Pet states](pet.png)

*Each label in the picture is given in Russian and English and shows a pet state: idle, following the cursor, thinking, limit colors, limit reached, sleeping.*

## Features

- **Click** to bring Claude to the front. If Claude is already active, the click minimizes it; if Claude is not running, it starts it.
- **Drag** with the left mouse button to move the pet around the screen.
- **Idle.** When the mouse is far away, the pet shrinks into a semi-transparent ball and expands again on hover. Its eyes follow the cursor, and it blinks now and then.
- **Claude is thinking.** While Claude Code works on a reply, a glowing arc runs clockwise around the halo. For the regular chat, the arc runs counterclockwise.
- **Halo color** shows 5-hour subscription limit usage: green below 50 %, yellow up to 80 %, red at 80 % and above.
- **Limit reached.** The pet looks sad and shows a countdown to the reset on its face.
- **Sleep.** If Claude is not running or has been inactive for 3 minutes, the pet falls asleep.
- **Hover tooltip:** 5-hour and weekly limits, context usage, tokens, subscription renewal date.
- **Notification bubbles:** at 80 % and 95 % of the limit, when the limit resets, when the context is full, and before the subscription renews.
- **Right-click menu:**
  - launch or quit Claude;
  - quick links into Claude: new chat, recent chats, projects, tasks, connectors, settings;
  - Claude Code: new session, last session, sessions waiting for input, search;
  - project folders;
  - statistics;
  - pet size;
  - start with Windows.

The pet's interface (menu, tooltips, notifications) is in Russian.

## Requirements

- Windows 10 or 11.
- The Claude app for Windows and/or Claude Code.
- Python 3 from python.org. Keep the *tcl/tk and IDLE* option checked during installation. Python from the Microsoft Store will not work: it redirects the `%APPDATA%` folder for the programs it starts.
- The Pillow library.

## Installation

1. Download the repository: **Code → Download ZIP**, or:
   ```
   git clone https://github.com/ARCHERDEV777/claude-desktop-pet.git
   ```
2. Install the dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Double-click **`Start Pet.vbs`**. The script finds your Python installation and starts the pet without a console window.

To start the pet with Windows, turn on **«Запускать вместе с Windows»** ("Start with Windows") in its menu.

## How it works

| File | Purpose |
|---|---|
| `claude_pet.pyw` | The pet itself: window, animation, menu, notifications. |
| `pet_stats.py` | Collects statistics: limits, tokens from Claude Code logs, project folders. |
| `pet_hook.py` | Claude Code hook. Marks when Claude is thinking about a reply. |
| `pet_statusline.py` | Claude Code status line. Saves limit and context percentages and also prints them at the bottom of the Claude Code window. |
| `chat_watch.ps1` | Watches the regular chat: checks whether the Stop response button is visible in the Claude window. |
| `Start Pet.vbs` | Starts the pet without a console and finds Python automatically. |

On startup, the pet adds its hooks and status line to `~/.claude/settings.json`. It leaves other settings alone: if you already have your own status line, the pet does not replace it. If you move the pet folder, the paths in the settings are updated on the next start. The hooks are turned off with the menu items **«Следить за Claude Code»** ("Watch Claude Code") and **«Показывать лимиты подписки»** ("Show subscription limits").

The pet's settings and service files are stored in `%USERPROFILE%\.claude-desktop-pet`. If the `CLAUDE_CONFIG_DIR` variable is set, the Claude Code folder is taken from it.

## Limitations

- Windows only.
- Limit percentages are available only on Pro and Max subscriptions, and only after the first reply in a Claude Code session.
- The Code tab in the app does not call the status line, so without Claude Code in a terminal the percentages come from the app's own measurements. The app requests the limits when it starts, and every 5–15 minutes only within a day after you right-clicked its tray icon to open the menu. The pet does this for you: once a day it "clicks" the icon (even when it is hidden behind the tray arrow), choosing a moment when Claude is not in the foreground and you have not pressed anything for a couple of seconds, so no menu appears. Close to the end of the day it clicks anyway, and the menu may flash at the cursor for an instant before the pet closes it. Turn it off in menu → Settings → «Щёлкать по значку Claude в трее» ("Click Claude's tray icon"). If the click does not register, or the option is off, the pet reminds you to right-click the icon yourself. If the measurement is older than 5 hours, the tooltip shows "no fresh data". These measurements have no reset time: the pet works out the weekly reset by itself once it sees the percentage drop, and then repeats it every 7 days. Until it has seen a reset, you can set the day and time manually: menu → Settings → «Недельный сброс лимита…» ("Weekly limit reset…"). The time the pet works out itself always takes priority over the manual one.
- Some data is read from internal files of the Claude app. Their format is undocumented and may change after a Claude update. If that happens, the affected indicators simply disappear, and the pet keeps working.
- Regular chat tracking recognizes the stop button only in the English and Russian Claude interface. For another language, add the button's name to `$StopNames` in `chat_watch.ps1`.

## Uninstalling

1. In the menu, uncheck «Следить за Claude Code», «Показывать лимиты подписки» and «Запускать вместе с Windows». This removes the hooks and autostart.
2. Quit the pet (menu item «Выключить питомца», "Quit pet").
3. Delete the pet folder and the `%USERPROFILE%\.claude-desktop-pet` folder.

## License

[MIT](LICENSE): free to use, modify and distribute as long as the author's name is kept.

---

Unofficial project, not affiliated with Anthropic.
