"""Generate softmacro.ico from the tray icon artwork.

Run from the project root:  python tools\\make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tray import make_icon_image  # noqa: E402

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    target = ROOT / "softmacro.ico"
    make_icon_image().save(target, sizes=SIZES)
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
