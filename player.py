"""Replay macro events with ``pynput`` controllers.

Each event is ``(relative_ms, [kind, payload])``. We sleep the gap between
consecutive events to preserve timing.

Playback options:
    repeat       -- number of full passes (default 1)
    speed        -- time multiplier: 2.0 plays twice as fast, 0.5 half speed
    cancel_event -- ``threading.Event``; playback aborts early when set.
                    Any keys still held are released before returning.
"""

from __future__ import annotations

import threading
import time

from pynput import keyboard, mouse


_BTN_MAP = {
    "left": mouse.Button.left,
    "right": mouse.Button.right,
    "middle": mouse.Button.middle,
}


def _char_vk(ch: str):
    """Explicit Windows VK code for a single character.

    Returns ``None`` for characters we don't map. Using explicit VK codes
    (instead of ``KeyCode.from_char``) avoids pynput's ``VkKeyScan``
    resolution, which routes uppercase characters through Unicode injection
    -- Chrome and most apps ignore those for keyboard accelerators.
    """
    o = ord(ch)
    if 0x61 <= o <= 0x7A:   # a-z -> physical key, no implicit shift
        return 0x41 + (o - 0x61)
    if 0x41 <= o <= 0x5A:   # A-Z -> physical key, no implicit shift
        return o
    if 0x30 <= o <= 0x39:   # 0-9
        return o
    if ch == " ":
        return 0x20
    return None


def _parse_key(name: str):
    """Translate a stored key string back into a pynput Key/KeyCode.

    Single-character keys are treated as *physical keys*: mapped to an
    explicit VK code with no implicit shift. Uppercase output only happens
    when the macro itself holds shift (stored combos include an explicit
    ``Key.shift`` event, and the ``Type`` command emits one for capital
    letters).
    """
    # Named special keys live on pynput.keyboard.Key
    if hasattr(keyboard.Key, name):
        return getattr(keyboard.Key, name)

    # pynput renders keys like "Key.ctrl_l" -> name would be the full repr
    if name.startswith("Key."):
        short = name[len("Key."):]
        if hasattr(keyboard.Key, short):
            return getattr(keyboard.Key, short)

    # Numpad keys: "Numpad0".."Numpad9" -> VK_NUMPAD0 + n
    if name.startswith("Numpad") and name[6:].isdigit():
        return keyboard.KeyCode.from_vk(0x60 + int(name[6:]))

    # Single character -> explicit VK (no layout/modifier resolution).
    if len(name) == 1:
        vk = _char_vk(name)
        if vk is not None:
            return keyboard.KeyCode.from_vk(vk)
        return keyboard.KeyCode.from_char(name.lower())

    return None


def _button(name: str):
    return _BTN_MAP.get(name)


def _sleep(seconds: float, cancel_event: threading.Event | None) -> bool:
    """Sleep in small slices so a cancel request aborts the wait quickly.

    Returns False if cancelled.
    """
    if cancel_event is None:
        time.sleep(seconds)
        return True
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        if cancel_event.is_set():
            return False
        time.sleep(min(0.05, remaining))


def play(
    events: list,
    on_done: callable = None,
    repeat: int = 1,
    speed: float = 1.0,
    cancel_event: threading.Event | None = None,
) -> None:
    """Replay a captured macro. ``events`` is ``[[ms, [kind, payload]], ...]``.

    Runs synchronously; call from a worker thread if you need it non-blocking.
    """
    kc = keyboard.Controller()
    mc = mouse.Controller()
    held_keys: list = []

    def release_all():
        for k in reversed(held_keys):
            try:
                kc.release(k)
            except Exception:
                pass
        held_keys.clear()

    try:
        for _pass in range(max(1, repeat)):
            if cancel_event is not None and cancel_event.is_set():
                break
            last_t = 0
            for entry in events:
                if cancel_event is not None and cancel_event.is_set():
                    break
                t, ev = entry[0], entry[1]
                kind, payload = ev[0], ev[1]

                delay_ms = t - last_t
                if delay_ms > 0:
                    if not _sleep((delay_ms / 1000.0) / speed, cancel_event):
                        break
                last_t = t

                print(f"[SoftMacro]   {t:>6}ms  {kind:<11} {payload!r}")
                try:
                    if kind == "key_down":
                        k = _parse_key(payload)
                        if k is not None:
                            kc.press(k)
                            held_keys.append(k)
                    elif kind == "key_up":
                        k = _parse_key(payload)
                        if k is not None:
                            kc.release(k)
                            if k in held_keys:
                                held_keys.remove(k)
                    elif kind == "mouse_down":
                        b = _button(payload)
                        if b is not None:
                            mc.press(b)
                    elif kind == "mouse_up":
                        b = _button(payload)
                        if b is not None:
                            mc.release(b)
                    elif kind == "mouse_move":
                        x, y = int(payload[0]), int(payload[1])
                        mc.position = (x, y)
                    elif kind == "scroll":
                        # payload is {"direction": ..., "amount": int}
                        direction = payload.get("direction", "down") if isinstance(payload, dict) else "down"
                        amount = int(payload.get("amount", 1)) if isinstance(payload, dict) else 1
                        dx, dy = 0, 0
                        if direction == "up":    dy = amount
                        elif direction == "down":  dy = -amount
                        elif direction == "left":  dx = -amount
                        elif direction == "right": dx = amount
                        mc.scroll(dx, dy)
                    elif kind == "delay":
                        # payload is milliseconds -- sleep it now. We do NOT
                        # advance last_t: the delay is in addition to the
                        # event's own timestamp.
                        if not _sleep(int(payload) / 1000.0 / speed, cancel_event):
                            break
                except Exception as e:  # pragma: no cover - defensive
                    print(f"[SoftMacro] playback error on {kind}/{payload!r}: {e}")
    finally:
        release_all()

    if on_done is not None:
        try:
            on_done()
        except Exception:
            pass
