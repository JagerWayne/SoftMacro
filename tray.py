"""System-tray icon for SoftMacro (pystray + Pillow).

The tray icon gives the app a visible home when running headless
(pythonw + autorun). Menu:

    Open Web UI          -- opens the management UI in the browser
    Restart web server   -- rebinds the web UI (after a port change)
    Show macro keyboard  -- same as pressing the hotkey
    Exit                 -- shuts SoftMacro down
"""

from __future__ import annotations

import queue
import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw, ImageFont

import config
from branding import APP_TITLE


def web_url() -> str:
    """URL of the management UI on its currently configured port."""
    return f"http://127.0.0.1:{config.get_web_port()}"


def _load_font(size: int):
    for candidate in (
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_icon_image() -> Image.Image:
    """Draw the tray glyph: dark rounded square, accent border, three key
    caps along the bottom and a bold 'S' above them."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([2, 2, 62, 62], radius=14, fill=(20, 20, 26, 255))
    d.rounded_rectangle([2, 2, 62, 62], radius=14, outline=(136, 192, 255, 255), width=2)

    # Three little grey key caps.
    d.rounded_rectangle([7, 42, 17, 52], radius=3, fill=(106, 106, 106, 255))
    d.rounded_rectangle([22, 42, 32, 52], radius=3, fill=(106, 106, 106, 255))
    d.rounded_rectangle([37, 42, 47, 52], radius=3, fill=(106, 106, 106, 255))

    font = _load_font(30)
    d.text((32, 20), "S", font=font, fill=(255, 255, 255, 255), anchor="mm")
    return img


class TrayIcon:
    """Runs pystray on its own thread; talks to tkinter via the app queue."""

    def __init__(self, sink: queue.Queue) -> None:
        self.sink = sink
        self._icon = pystray.Icon(
            "SoftMacro",
            icon=make_icon_image(),
            title=APP_TITLE,
            menu=pystray.Menu(
                pystray.MenuItem("Open Web UI", self._open_web, default=True),
                pystray.MenuItem("Check for updates", self._open_updates),
                pystray.MenuItem("Restart web server", self._restart_web),
                pystray.MenuItem(
                    "Show macro keyboard",
                    lambda icon=None, item=None: self.sink.put(("show", None)),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Exit",
                    lambda icon=None, item=None: self.sink.put(("exit", None)),
                ),
            ),
        )
        self._thread = threading.Thread(
            target=self._icon.run, name="softmacro-tray", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass

    def _open_web(self, icon=None, item=None):
        webbrowser.open(web_url())

    def _open_updates(self, icon=None, item=None):
        webbrowser.open(web_url() + "/settings#updates")

    def _restart_web(self, icon=None, item=None):
        self.sink.put(("restart_web", None))
