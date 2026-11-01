# Brave Music Panel

A lightweight, edge-hover music controller for **YouTube Music running in a dedicated Brave Browser profile** on Linux Mint.

The goal is simple: keep YouTube Music playing in the background while controlling playback from a small desktop panel or the system tray—without keeping the browser window on screen.

> **Platform note:** Linux Mint with Cinnamon on an X11 session is the recommended environment. Media controls may also work on other Linux desktop sessions that expose Brave through MPRIS, but minimizing and restoring the browser window relies on X11 tooling.

## Features

- Opens YouTube Music (`https://music.youtube.com/`) in a dedicated Brave profile.
- Keeps the dedicated browser profile separate from your regular Brave profile.
- Shows a compact panel from a handle on the right edge of the screen.
- Automatically collapses the panel when the pointer leaves; the panel can also be pinned open.
- Provides play/pause, previous-track, next-track, and seek controls.
- Displays the current track title, artist, album artwork, elapsed time, and duration when Brave exposes that metadata through MPRIS.
- Adds a system-tray icon with actions to show the panel, open YouTube Music, play/pause, stop the dedicated session, or quit the panel.
- Can optionally start automatically when you log in.
- Keeps playback controls isolated to the Brave process launched by this application.

## How it works

The application is written in Python with [PySide6](https://doc.qt.io/qtforpython-6/). It uses:

- **Brave Browser** to run YouTube Music.
- **MPRIS over D-Bus** to discover the browser's media session and read/control playback.
- **`playerctl`** to communicate with the MPRIS player.
- **`busctl`** to retrieve the D-Bus process ID that owns an MPRIS service.
- **`/proc` process information** to verify that the MPRIS service belongs to the Brave process/profile launched by this application.
- **`wmctrl`** to minimize and restore the dedicated Brave window on X11.
- **Qt's system-tray support** for the background tray icon.

### Playback isolation

Brave is launched with a separate user-data directory:

```text
~/.local/share/brave-music-panel/brave-profile/
```

The app does **not** use `playerctl`'s default-player selection. Before issuing a media command, it enumerates MPRIS players and verifies the D-Bus service owner's process against the dedicated Brave process and profile. If it cannot verify ownership, it refuses to send the command instead of falling back to another browser session or media player.

Your normal Brave profile and its tabs are not used for playback control.

## Requirements

- Linux Mint (Cinnamon + X11 recommended)
- Python 3
- `python3-venv`
- Brave Browser
- `playerctl`
- `busctl` (normally provided by systemd)
- `wmctrl` (for minimizing/restoring the Brave window on X11)
- Qt's X11 runtime dependencies

Install the system packages on Linux Mint / Ubuntu-based distributions:

```bash
sudo apt update
sudo apt install \
  python3 \
  python3-venv \
  playerctl \
  wmctrl \
  libxcb-cursor0 \
  libxcb-icccm4 \
  libxcb-keysyms1 \
  libxcb-render-util0 \
  libxcb-xinerama0 \
  libxcb-xkb1 \
  libxkbcommon-x11-0
```

`libxcb-cursor0` is especially important for the Qt `xcb` platform plugin on newer Qt versions. Some systems may already have some of these libraries installed.

Install Brave Browser separately if it is not already installed. The application looks for common executable names such as `brave-browser` and `brave`.

## Installation

Clone the repository:

```bash
git clone https://github.com/<your-username>/<your-repository>.git
cd <your-repository>
```

Make the scripts executable and run the installer:

```bash
chmod +x install.sh run.sh launch.sh diagnose.sh uninstall.sh
./install.sh
```

The installer:

1. Copies the application files to `~/.local/share/brave-music-panel/`.
2. Creates a Python virtual environment in that directory.
3. Installs the dependencies from `requirements.txt`.
4. Creates an application-menu entry.
5. Asks whether to enable automatic startup at login.

Do **not** run the installer with `sudo`. It installs the app into your own home directory.

After installation, launch **Brave Music Panel** from the Linux Mint applications menu. You can also start the copy in the repository with:

```bash
./run.sh
```

## First-time setup

The dedicated Brave profile starts separately from your regular Brave profile, so it will initially be signed out.

1. Launch Brave Music Panel.
2. Sign in to your Google account in the dedicated YouTube Music window.
3. Start a track. A user interaction may be needed before the browser allows playback.
4. Click **Hide browser** in the panel. The dedicated browser window should minimize while playback continues.
5. Hover over the small handle at the right edge of the screen to reveal the panel.

The dedicated profile is reused on later launches. Your YouTube Music login and listening history are stored by Brave in that profile, not by this Python application. Login persistence depends on Google's session and security policies; it is not guaranteed indefinitely. Do not delete the profile directory if you want to keep that browser session.

YouTube Music's Home page and recommendations are account-dependent. Sign in with the account whose listening history and recommendations you want to use, and make sure YouTube watch history is not paused if you want it to continue informing recommendations.

## Usage

| Action | How |
| --- | --- |
| Show the panel | Hover over the handle on the right edge of the screen |
| Hide the panel | Move the pointer away or click the hide control |
| Keep the panel open | Click the pin icon |
| Play / pause | Click the main playback button |
| Change track | Use previous / next |
| Seek | Drag the progress slider |
| Restore YouTube Music | Click **Open YouTube Music** or use the tray menu |
| Show/hide the panel | Click the tray icon |
| Stop only the dedicated Brave session | Use **Stop dedicated music session** in the tray menu |
| Exit the controller | Use **Quit panel** in the tray menu |

Quitting the panel does not intentionally stop the dedicated Brave session. Use **Stop dedicated music session** when you want the app to terminate the browser process group it started.

## Configuration and data locations

| Purpose | Location |
| --- | --- |
| Installed app and virtual environment | `~/.local/share/brave-music-panel/` |
| Dedicated Brave profile and login data | `~/.local/share/brave-music-panel/brave-profile/` |
| First-run setup marker | `~/.local/share/brave-music-panel/setup-complete` |
| Application log | `~/.local/state/brave-music-panel/app.log` |
| Launcher log | `~/.local/state/brave-music-panel/launcher.log` |
| Installer log | `~/.local/state/brave-music-panel/install.log` |
| Applications-menu entry | `~/.local/share/applications/brave-music-panel.desktop` |
| Optional autostart entry | `~/.config/autostart/brave-music-panel.desktop` |

The app also respects `XDG_DATA_HOME`, `XDG_STATE_HOME`, and `XDG_CONFIG_HOME` where those locations are used by its scripts.

## Troubleshooting

### The app does not open from the applications menu

Run it from a terminal so errors are visible:

```bash
BRAVE_MUSIC_PANEL_CONSOLE=1 \
  ~/.local/share/brave-music-panel/launch.sh
```

Then inspect the launcher log:

```bash
tail -n 100 ~/.local/state/brave-music-panel/launcher.log
```

### Qt reports that the `xcb` platform plugin cannot load

Install the XCB runtime dependencies and try again:

```bash
sudo apt install \
  libxcb-cursor0 \
  libxcb-icccm4 \
  libxcb-keysyms1 \
  libxcb-render-util0 \
  libxcb-xinerama0 \
  libxcb-xkb1 \
  libxkbcommon-x11-0
```

### The panel says it is waiting for the dedicated YouTube Music session

Make sure the dedicated YouTube Music window is open and that you have started playback at least once. Then check the available MPRIS players:

```bash
playerctl -l
```

The dedicated player is identified by its owning process, so its instance name may differ between launches. The app intentionally does not assume a fixed MPRIS player name.

### Check the app's diagnostics

From the cloned repository, run:

```bash
./diagnose.sh
```

Check the application log:

```bash
tail -f ~/.local/state/brave-music-panel/app.log
```

### Browser minimizing or restoring does not work

The window-management integration uses `wmctrl` and is designed for X11. Check your session type:

```bash
echo "$XDG_SESSION_TYPE"
```

If the session is Wayland, MPRIS playback controls may still work, but browser-window minimize/restore is not guaranteed by this implementation.

## Uninstall

From the cloned repository:

```bash
./uninstall.sh
```

**Important:** the current uninstall script removes the installed application directory, including the dedicated Brave profile and its saved login/session data. Back up the profile first if you want to preserve it:

```bash
cp -a ~/.local/share/brave-music-panel/brave-profile \
  ~/brave-music-panel-profile-backup
```

The app log directory under `~/.local/state/brave-music-panel/` is left in place by the uninstall script.

## Current limitations

- This is a controller for a YouTube Music session, not a standalone audio player or YouTube search client.
- Search, playlist browsing, queue editing, and direct recommendation selection from the panel are not implemented in this version. Use the **Open YouTube Music** action for those tasks.
- The panel depends on Brave exposing its media session through MPRIS.
- Browser minimize/restore is X11-oriented and depends on `wmctrl`.
- YouTube, Google, and Brave can change their browser behavior, authentication requirements, or media integration at any time.
- Brave Shields and YouTube's own policies determine ad behavior. This project does not guarantee an ad-free YouTube experience.

## Privacy

- The app uses a dedicated local Brave profile and does not read your regular Brave profile.
- Google sign-in credentials and cookies are handled by Brave; this app does not ask for or store your Google password.
- The app has no remote backend or telemetry service in this version.
- Track metadata is read from the local MPRIS session. Album artwork may be fetched from the artwork URL supplied by the media session.
- Logs are stored locally under `~/.local/state/brave-music-panel/`.

## Contributing

Bug reports, suggestions, and pull requests are welcome. When reporting a problem, include:

- Your Linux Mint version and desktop environment.
- Whether the session is X11 or Wayland (`echo "$XDG_SESSION_TYPE"`).
- The output of `./diagnose.sh`.
- Relevant lines from `~/.local/state/brave-music-panel/launcher.log` and `app.log`.

Please remove personal information from logs before sharing them.

## License

No license has been added to this repository yet. Add a `LICENSE` file before distributing the project or accepting contributions under a particular open-source license.

---

This project is an independent community project and is not affiliated with, endorsed by, or sponsored by Brave Software, Google, or YouTube.
