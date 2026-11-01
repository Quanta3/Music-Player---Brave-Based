#!/usr/bin/env python3
"""Brave Music Panel for Linux Mint.

A small edge-hover music controller for a dedicated Brave + YouTube Music
instance. Playback commands are sent only to the MPRIS player whose D-Bus
owner belongs to the browser process started by this application.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "Brave Music Panel"
MUSIC_URL = "https://music.youtube.com/"
PLAYERCTL = shutil.which("playerctl") or "playerctl"
BUSCTL = shutil.which("busctl") or "busctl"
WMCTRL = shutil.which("wmctrl")

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "brave-music-panel"
PROFILE_DIR = DATA_DIR / "brave-profile"
SETUP_MARKER = DATA_DIR / "setup-complete"
LOG_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "brave-music-panel"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "app.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(APP_NAME)


def run_command(args: list[str], timeout: float = 2.0) -> subprocess.CompletedProcess[str]:
    """Run a command without a shell and return captured text output."""
    try:
        return subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.debug("Command failed %r: %s", args, exc)
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def find_brave() -> Optional[str]:
    for name in ("brave-browser", "brave", "brave-browser-stable", "brave-browser-beta"):
        found = shutil.which(name)
        if found:
            return found
    for path in ("/usr/bin/brave-browser", "/usr/bin/brave", "/opt/brave.com/brave/brave-browser"):
        if Path(path).exists() and os.access(path, os.X_OK):
            return path
    return None


def read_proc_parent(pid: int) -> Optional[int]:
    """Read PPID from /proc/<pid>/stat, handling spaces in comm."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        close = raw.rfind(")")
        fields = raw[close + 2 :].split()
        # fields[0] is state (field 3); fields[1] is PPID (field 4).
        return int(fields[1])
    except (OSError, ValueError, IndexError):
        return None


def process_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\0", b" ").decode("utf-8", errors="replace")
    except OSError:
        return ""


def process_belongs_to_session(pid: int, root_pid: int, profile_dir: Path) -> bool:
    """Fail-closed process ownership check for our dedicated Brave profile."""
    profile = str(profile_dir.resolve())
    current = pid
    visited: set[int] = set()
    for _ in range(40):
        if current <= 1 or current in visited:
            break
        visited.add(current)
        if current == root_pid:
            return True
        cmdline = process_cmdline(current)
        if profile in cmdline:
            return True
        parent = read_proc_parent(current)
        if parent is None or parent == current:
            break
        current = parent
    return False


class BraveSession(QObject):
    """Owns exactly one Brave profile and its matching MPRIS player."""

    def __init__(self) -> None:
        super().__init__()
        self.executable = find_brave()
        self.process: Optional[subprocess.Popen[bytes]] = None
        self.player: Optional[str] = None
        self._last_art_url = ""
        self._cached_windows: list[str] = []
        self._browser_visible_override = False

    @property
    def root_pid(self) -> Optional[int]:
        if self.process is None:
            return None
        return self.process.pid

    def launch(self) -> tuple[bool, str]:
        if not self.executable:
            return False, "Brave was not found. Install Brave Browser first."
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        if self.process is not None and self.process.poll() is None:
            return True, "Your dedicated YouTube Music session is already running."

        args = [
            self.executable,
            f"--user-data-dir={PROFILE_DIR}",
            f"--app={MUSIC_URL}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
        ]
        try:
            self.process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.player = None
            self._cached_windows.clear()
            log.info("Started dedicated Brave session pid=%s profile=%s", self.process.pid, PROFILE_DIR)
            return True, "Starting YouTube Music in its dedicated Brave profile…"
        except OSError as exc:
            log.exception("Could not launch Brave")
            return False, f"Could not start Brave: {exc}"

    def _player_pid(self, player: str) -> Optional[int]:
        service = f"org.mpris.MediaPlayer2.{player}"
        result = run_command(
            [
                BUSCTL,
                "--user",
                "call",
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "GetConnectionUnixProcessID",
                "s",
                service,
            ]
        )
        match = re.search(r"\bu\s+(\d+)", result.stdout)
        return int(match.group(1)) if result.returncode == 0 and match else None

    def _player_is_ours(self, player: str) -> bool:
        root = self.root_pid
        if root is None:
            return False
        owner_pid = self._player_pid(player)
        if owner_pid is None:
            return False
        return process_belongs_to_session(owner_pid, root, PROFILE_DIR)

    def discover_player(self) -> Optional[str]:
        """Find the MPRIS player exported by the Brave process we launched."""
        if self.player and self._player_is_ours(self.player):
            return self.player
        self.player = None
        if self.root_pid is None:
            return None
        result = run_command([PLAYERCTL, "-l"])
        if result.returncode != 0:
            return None
        for candidate in result.stdout.splitlines():
            candidate = candidate.strip()
            if not candidate:
                continue
            # We only expect Brave here, but still validate PID/profile ownership.
            if candidate.startswith("brave.") and self._player_is_ours(candidate):
                self.player = candidate
                log.info("Bound MPRIS player %s to our Brave process", candidate)
                return candidate
        return None

    def _command(self, *args: str) -> tuple[bool, str]:
        player = self.discover_player()
        if not player:
            return False, "The dedicated YouTube Music player is not connected yet."
        result = run_command([PLAYERCTL, "-p", player, *args])
        if result.returncode != 0:
            log.warning("playerctl failed for owned player %s: %s", player, result.stderr.strip())
            return False, result.stderr.strip() or "Playback command failed."
        return True, result.stdout.strip()

    def play_pause(self) -> tuple[bool, str]:
        return self._command("play-pause")

    def next_track(self) -> tuple[bool, str]:
        return self._command("next")

    def previous_track(self) -> tuple[bool, str]:
        return self._command("previous")

    def play(self) -> tuple[bool, str]:
        return self._command("play")

    def status(self) -> str:
        ok, output = self._command("status")
        return output if ok else "Disconnected"

    def metadata(self) -> dict[str, str]:
        fields = {
            "title": "{{title}}",
            "artist": "{{artist}}",
            "album": "{{album}}",
            "art_url": "{{mpris:artUrl}}",
            "length": "{{mpris:length}}",
        }
        data: dict[str, str] = {}
        for name, template in fields.items():
            ok, value = self._command("metadata", "--format", template)
            data[name] = value if ok else ""
        return data

    def position_seconds(self) -> float:
        ok, value = self._command("position")
        try:
            return max(0.0, float(value)) if ok else 0.0
        except ValueError:
            return 0.0

    def seek(self, seconds: float) -> tuple[bool, str]:
        return self._command("position", f"{max(0.0, seconds):.2f}")

    def browser_windows(self) -> list[str]:
        """Return X11 window IDs belonging to this Brave process tree."""
        if not WMCTRL or self.root_pid is None:
            return []
        result = run_command([WMCTRL, "-lp"])
        if result.returncode != 0:
            return []
        windows: list[str] = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 3:
                continue
            window_id, _desktop, pid_text = parts[:3]
            try:
                pid = int(pid_text)
            except ValueError:
                continue
            if process_belongs_to_session(pid, self.root_pid, PROFILE_DIR):
                windows.append(window_id)
        return windows

    def minimize_browser(self) -> bool:
        if not WMCTRL:
            return False
        windows = self.browser_windows()
        if not windows:
            return False
        all_ok = True
        for window_id in windows:
            # wmctrl's -Y action takes the window ID directly (with -i for hex IDs).
            result = run_command([WMCTRL, "-i", "-Y", window_id])
            all_ok = all_ok and result.returncode == 0
        return all_ok

    def auto_minimize_browser(self) -> bool:
        if self._browser_visible_override:
            return False
        return self.minimize_browser()

    def show_browser(self) -> bool:
        if not WMCTRL:
            return False
        windows = self.browser_windows()
        if not windows:
            return False
        result = run_command([WMCTRL, "-i", "-a", windows[0]])
        if result.returncode == 0:
            self._browser_visible_override = True
        return result.returncode == 0

    def stop_session(self) -> None:
        """Terminate only the process group started for our dedicated profile."""
        if self.process is None or self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self.process.terminate()
            except OSError:
                pass
        self.player = None
        log.info("Sent SIGTERM to dedicated Brave process group %s", self.process.pid)


class EdgeHandle(QWidget):
    def __init__(self, on_hover) -> None:
        super().__init__(None)
        self.on_hover = on_hover
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(18, 92)
        self.setStyleSheet(
            "QWidget { background: #9877f5; border-top-left-radius: 11px; "
            "border-bottom-left-radius: 11px; border: 1px solid #b8a3ff; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("♫")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #ffffff; font-size: 17px; background: transparent; border: 0;")
        layout.addWidget(label)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.on_hover()
        super().enterEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.on_hover()
        super().mousePressEvent(event)


class MusicPanel(QWidget):
    def __init__(self, session: BraveSession) -> None:
        super().__init__(None)
        self.session = session
        self.first_run = not SETUP_MARKER.exists()
        self.pinned = False
        self.is_expanded = False
        self.is_seeking = False
        self.duration = 0.0
        self._last_track_key = ""
        self._art_request_url = ""
        self._hide_animation: Optional[QPropertyAnimation] = None
        self._show_animation: Optional[QPropertyAnimation] = None

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(342, 438)
        self.setStyleSheet(self._stylesheet())

        self.network = QNetworkAccessManager(self)
        self.network.finished.connect(self._art_download_finished)
        self._build_ui()

        self.handle = EdgeHandle(self.expand)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(280)
        self.hide_timer.timeout.connect(self._maybe_collapse)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1100)
        self.poll_timer.timeout.connect(self.refresh)
        self.poll_timer.start()

        self._position_widgets()
        self.handle.show()
        self.move(self._hidden_geometry().topLeft())
        self.hide()
        self.refresh()

    @staticmethod
    def _stylesheet() -> str:
        return """
        QWidget#panelRoot { background: #17151f; border: 1px solid #383144; border-radius: 22px; }
        QLabel { color: #f5f1ff; background: transparent; }
        QLabel#eyebrow { color: #a89bbd; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
        QLabel#songTitle { color: #ffffff; font-size: 17px; font-weight: 700; }
        QLabel#artist { color: #b8aec8; font-size: 12px; }
        QLabel#status { color: #a99eb9; font-size: 10px; }
        QLabel#timeLabel { color: #958aa7; font-size: 10px; }
        QLabel#art { background: #292333; border-radius: 15px; color: #a58bf5; font-size: 36px; }
        QPushButton { color: #eee9f8; background: #292432; border: 1px solid #3b3447; border-radius: 13px; padding: 7px; }
        QPushButton:hover { background: #3a3247; border-color: #8e75d8; }
        QPushButton:pressed { background: #5d4b86; }
        QPushButton#mainControl { color: #171222; background: #b49aff; border: 0; border-radius: 23px; font-size: 20px; font-weight: 800; }
        QPushButton#mainControl:hover { background: #c4b2ff; }
        QPushButton#smallButton { padding: 4px; border-radius: 10px; font-size: 12px; }
        QPushButton#textButton { background: transparent; border: 0; color: #b9a5ff; font-size: 11px; }
        QSlider::groove:horizontal { height: 4px; background: #40394c; border-radius: 2px; }
        QSlider::sub-page:horizontal { background: #a98cf7; border-radius: 2px; }
        QSlider::handle:horizontal { background: #e6dcff; width: 10px; margin: -4px 0; border-radius: 5px; }
        """

    def _build_ui(self) -> None:
        self.root = QFrame(self)
        self.root.setObjectName("panelRoot")
        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(19, 16, 19, 17)
        root_layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(7)
        brand = QLabel("♫")
        brand.setStyleSheet("color: #b49aff; font-size: 20px; font-weight: 700;")
        top.addWidget(brand)
        eyebrow = QLabel("MUSIC PANEL")
        eyebrow.setObjectName("eyebrow")
        top.addWidget(eyebrow)
        top.addStretch(1)
        self.pin_button = QPushButton("◇")
        self.pin_button.setObjectName("smallButton")
        self.pin_button.setFixedSize(30, 28)
        self.pin_button.setToolTip("Pin panel open")
        self.pin_button.clicked.connect(self.toggle_pin)
        top.addWidget(self.pin_button)
        self.hide_button = QPushButton("›")
        self.hide_button.setObjectName("smallButton")
        self.hide_button.setFixedSize(30, 28)
        self.hide_button.setToolTip("Hide panel")
        self.hide_button.clicked.connect(self.collapse)
        top.addWidget(self.hide_button)
        root_layout.addLayout(top)

        self.status_label = QLabel("Starting your private Brave session…")
        self.status_label.setObjectName("status")
        root_layout.addWidget(self.status_label)

        track_row = QHBoxLayout()
        track_row.setSpacing(13)
        self.art_label = QLabel("♫")
        self.art_label.setObjectName("art")
        self.art_label.setFixedSize(92, 92)
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        track_row.addWidget(self.art_label)

        track_info = QVBoxLayout()
        track_info.setSpacing(6)
        now = QLabel("NOW PLAYING")
        now.setObjectName("eyebrow")
        track_info.addWidget(now)
        self.title_label = QLabel("Waiting for a song")
        self.title_label.setObjectName("songTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(48)
        track_info.addWidget(self.title_label)
        self.artist_label = QLabel("YouTube Music · Brave")
        self.artist_label.setObjectName("artist")
        self.artist_label.setWordWrap(True)
        track_info.addWidget(self.artist_label)
        track_info.addStretch(1)
        track_row.addLayout(track_info, 1)
        root_layout.addLayout(track_row)

        progress_top = QHBoxLayout()
        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setObjectName("timeLabel")
        self.total_label = QLabel("0:00")
        self.total_label.setObjectName("timeLabel")
        progress_top.addWidget(self.elapsed_label)
        progress_top.addStretch(1)
        progress_top.addWidget(self.total_label)
        root_layout.addLayout(progress_top)

        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.sliderPressed.connect(self._seek_started)
        self.progress.sliderReleased.connect(self._seek_finished)
        root_layout.addWidget(self.progress)

        controls = QHBoxLayout()
        controls.setContentsMargins(4, 2, 4, 2)
        controls.setSpacing(16)
        self.previous_button = QPushButton("|◀")
        self.previous_button.setFixedSize(48, 44)
        self.previous_button.setToolTip("Previous song")
        self.previous_button.clicked.connect(self._previous)
        controls.addStretch(1)
        controls.addWidget(self.previous_button)
        self.play_button = QPushButton("▶")
        self.play_button.setObjectName("mainControl")
        self.play_button.setFixedSize(54, 54)
        self.play_button.setToolTip("Play / pause")
        self.play_button.clicked.connect(self._play_pause)
        controls.addWidget(self.play_button)
        self.next_button = QPushButton("▶|")
        self.next_button.setFixedSize(48, 44)
        self.next_button.setToolTip("Next song")
        self.next_button.clicked.connect(self._next)
        controls.addWidget(self.next_button)
        controls.addStretch(1)
        root_layout.addLayout(controls)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #332d3e;")
        root_layout.addWidget(divider)

        footer = QHBoxLayout()
        self.browser_button = QPushButton("Open YouTube Music")
        self.browser_button.setObjectName("textButton")
        self.browser_button.clicked.connect(self._show_browser)
        footer.addWidget(self.browser_button)
        footer.addStretch(1)
        self.hide_browser_button = QPushButton("Hide browser")
        self.hide_browser_button.setObjectName("textButton")
        self.hide_browser_button.clicked.connect(self._hide_browser)
        footer.addWidget(self.hide_browser_button)
        root_layout.addLayout(footer)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.root)

        self.hide_browser_button.setVisible(self.first_run)

    def _position_widgets(self) -> None:
        screen = QApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen else self.geometry()
        self._screen_geometry = geometry
        y = geometry.y() + max(12, (geometry.height() - self.height()) // 2)
        handle_y = geometry.y() + max(12, (geometry.height() - self.handle.height()) // 2)
        self._shown_x = geometry.x() + geometry.width() - self.width()
        self._hidden_x = geometry.x() + geometry.width() + 3
        self._panel_y = y
        self._handle_x = geometry.x() + geometry.width() - self.handle.width()
        self.handle.move(self._handle_x, handle_y)

    def _hidden_geometry(self):
        return self.geometry().__class__(self._hidden_x, self._panel_y, self.width(), self.height())

    def expand(self) -> None:
        self.hide_timer.stop()
        if self.is_expanded:
            self.show()
            return
        self.is_expanded = True
        self.handle.hide()
        self.show()
        self.raise_()
        start = self.geometry()
        target = self.geometry().__class__(self._shown_x, self._panel_y, self.width(), self.height())
        self._show_animation = QPropertyAnimation(self, b"geometry", self)
        self._show_animation.setDuration(190)
        self._show_animation.setStartValue(start)
        self._show_animation.setEndValue(target)
        self._show_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._show_animation.start()

    def collapse(self) -> None:
        if self.pinned:
            self.pinned = False
            self.pin_button.setText("◇")
        if not self.is_expanded:
            self.handle.show()
            return
        self.is_expanded = False
        self.hide_timer.stop()
        start = self.geometry()
        target = self.geometry().__class__(self._hidden_x, self._panel_y, self.width(), self.height())
        self._hide_animation = QPropertyAnimation(self, b"geometry", self)
        self._hide_animation.setDuration(180)
        self._hide_animation.setStartValue(start)
        self._hide_animation.setEndValue(target)
        self._hide_animation.setEasingCurve(QEasingCurve.Type.InCubic)
        self._hide_animation.finished.connect(self._finish_collapse)
        self._hide_animation.start()

    def _finish_collapse(self) -> None:
        self.hide()
        self.handle.show()

    def _maybe_collapse(self) -> None:
        if self.pinned or not self.is_expanded:
            return
        if not self.geometry().contains(QCursor.pos()):
            self.collapse()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self.pinned:
            self.hide_timer.start()
        super().leaveEvent(event)

    def toggle_pin(self) -> None:
        self.pinned = not self.pinned
        self.pin_button.setText("◆" if self.pinned else "◇")
        self.pin_button.setToolTip("Unpin panel" if self.pinned else "Pin panel open")
        if not self.pinned and not self.geometry().contains(QCursor.pos()):
            self.hide_timer.start()

    @staticmethod
    def _format_time(seconds: float) -> str:
        total = max(0, int(seconds))
        return f"{total // 60}:{total % 60:02d}"

    def _seek_started(self) -> None:
        self.is_seeking = True

    def _seek_finished(self) -> None:
        self.is_seeking = False
        if self.duration > 0:
            seconds = self.duration * self.progress.value() / 1000.0
            ok, message = self.session.seek(seconds)
            if not ok:
                self.status_label.setText(message)

    def _play_pause(self) -> None:
        ok, message = self.session.play_pause()
        if not ok:
            self.status_label.setText(message)
        self.refresh()

    def _previous(self) -> None:
        ok, message = self.session.previous_track()
        if not ok:
            self.status_label.setText(message)
        QTimer.singleShot(250, self.refresh)

    def _next(self) -> None:
        ok, message = self.session.next_track()
        if not ok:
            self.status_label.setText(message)
        QTimer.singleShot(250, self.refresh)

    def _show_browser(self) -> None:
        if self.session.show_browser():
            self.status_label.setText("YouTube Music window restored")
        else:
            self.status_label.setText("Could not restore browser window (wmctrl/X11 required)")

    def _hide_browser(self) -> None:
        if self.session.minimize_browser():
            self.first_run = False
            try:
                SETUP_MARKER.touch(exist_ok=True)
            except OSError:
                log.exception("Could not write setup marker")
            self.hide_browser_button.setVisible(False)
            self.status_label.setText("Browser minimized · music stays active")
        else:
            self.status_label.setText("Could not minimize browser (install wmctrl; X11 required)")

    def _load_art(self, url: str) -> None:
        if not url or url == self._art_request_url:
            return
        self._art_request_url = url
        parsed = urlparse(url)
        if parsed.scheme == "file":
            path = QUrl(url).toLocalFile()
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self._set_art_pixmap(pixmap)
            return
        if parsed.scheme in ("http", "https"):
            request = QNetworkRequest(QUrl(url))
            request.setTransferTimeout(5000)
            self.network.get(request)

    def _art_download_finished(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                pixmap = QPixmap()
                pixmap.loadFromData(reply.readAll())
                if not pixmap.isNull():
                    self._set_art_pixmap(pixmap)
        finally:
            reply.deleteLater()

    def _set_art_pixmap(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            self.art_label.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.art_label.setPixmap(scaled)
        self.art_label.setStyleSheet("background: #292333; border-radius: 15px;")

    def refresh(self) -> None:
        player = self.session.discover_player()
        if not player:
            self.status_label.setText("Waiting for your dedicated YouTube Music session…")
            self.title_label.setText("Waiting for a song")
            self.artist_label.setText("Start playback in YouTube Music")
            self.play_button.setText("▶")
            self.duration = 0.0
            if not self.is_seeking:
                self.progress.setValue(0)
            self.elapsed_label.setText("0:00")
            self.total_label.setText("0:00")
            return

        status = self.session.status()
        self.play_button.setText("Ⅱ" if status.lower() == "playing" else "▶")
        data = self.session.metadata()
        title = data.get("title") or "YouTube Music"
        artist = data.get("artist") or data.get("album") or ""
        self.title_label.setText(title)
        self.artist_label.setText(artist if artist else "Playing in your dedicated Brave session")
        self.status_label.setText("BRAVE SESSION CONNECTED  ·  CONTROLS ISOLATED")

        try:
            length_us = float(data.get("length", "0") or 0)
            self.duration = max(0.0, length_us / 1_000_000.0)
        except ValueError:
            self.duration = 0.0
        position = self.session.position_seconds()
        self.elapsed_label.setText(self._format_time(position))
        self.total_label.setText(self._format_time(self.duration))
        if not self.is_seeking:
            value = int(1000 * position / self.duration) if self.duration > 0 else 0
            self.progress.setValue(max(0, min(1000, value)))
        self._load_art(data.get("art_url", ""))

        if self.first_run:
            self.hide_browser_button.setVisible(True)


class TrayController(QObject):
    def __init__(self, app: QApplication, session: BraveSession, panel: MusicPanel) -> None:
        super().__init__()
        self.app = app
        self.session = session
        self.panel = panel
        self.tray = QSystemTrayIcon(self._make_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        show_action = menu.addAction("Show music panel")
        show_action.triggered.connect(self.panel.expand)
        browser_action = menu.addAction("Open YouTube Music")
        browser_action.triggered.connect(self._show_browser)
        menu.addSeparator()
        self.play_action = menu.addAction("Play / pause")
        self.play_action.triggered.connect(self._play_pause)
        stop_action = menu.addAction("Stop dedicated music session")
        stop_action.triggered.connect(self._stop_session)
        menu.addSeparator()
        quit_action = menu.addAction("Quit panel")
        quit_action.triggered.connect(self.app.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._activated)
        self.tray.show()

    @staticmethod
    def _make_icon() -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#9877f5"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(3, 3, 58, 58)
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPixelSize(39)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "♫")
        painter.end()
        return QIcon(pixmap)

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.panel.is_expanded:
                self.panel.collapse()
            else:
                self.panel.expand()

    def _show_browser(self) -> None:
        if not self.session.show_browser():
            self.tray.showMessage(APP_NAME, "Could not restore the browser window. Is wmctrl installed?", QSystemTrayIcon.MessageIcon.Warning)

    def _play_pause(self) -> None:
        ok, message = self.session.play_pause()
        if not ok:
            self.tray.showMessage(APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning)

    def _stop_session(self) -> None:
        self.session.stop_session()
        self.tray.showMessage(APP_NAME, "Stopped only the dedicated Brave music session.")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("System tray is not currently available")

    session = BraveSession()
    ok, message = session.launch()
    if not ok:
        QMessageBox.critical(None, APP_NAME, message)
        return 1

    panel = MusicPanel(session)
    tray = TrayController(app, session, panel)

    # On later launches, minimize the dedicated YouTube Music app window once
    # it appears. First launch remains visible so the user can sign in.
    if not panel.first_run:
        auto_hide_timer = QTimer(panel)
        auto_hide_timer.setInterval(1400)
        auto_hide_timer.timeout.connect(session.auto_minimize_browser)
        auto_hide_timer.start()
        # Stop retrying after a short startup window; a tray action can restore it.
        QTimer.singleShot(12000, auto_hide_timer.stop)

    # Keep Python references alive for the lifetime of QApplication.
    app._music_panel = panel  # type: ignore[attr-defined]
    app._music_tray = tray  # type: ignore[attr-defined]
    app._brave_session = session  # type: ignore[attr-defined]

    log.info("Brave Music Panel started")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
