"""
paint_preview.py — the Malowanie page drawn offscreen into a PNG (no window, no
sound, a scratch data dir), to check the toolbar after a layout change.

    cd ~/luna && SDL_VIDEODRIVER=dummy ./venv/bin/python tools/paint_preview.py /tmp/paint.png
"""

import os
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ["LUNA_DATA_DIR"] = tempfile.mkdtemp(prefix="luna-paint-preview-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import paint  # noqa: E402
import ui_paint  # noqa: E402


def main(out):
    pygame.init()
    scr = pygame.display.set_mode((paint.W, paint.H))
    paint.open_page()
    paint._s["colour"] = 8
    scr.fill((10, 10, 20))
    ui_paint.draw(scr, time.time(), paint.W, paint.H)
    pygame.image.save(scr, out)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/paint.png")
