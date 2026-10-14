"""
tools/face_map.py — every face she can make, on one labelled sheet: the
moods, listening / thinking / talking, the gestures, every reply scene
(reply_scenes.py, caught in the middle) and the costumes. The real
RobotFace and the GPU face, offscreen (gl_face_preview's EGL context), so
it runs on the Pi beside the running Luna without touching her screen.

    ~/luna/venv/bin/python -X utf8 tools/face_map.py [out.png] [--at 0.5]

--at: where in a scene to catch it (0..1, default 0.5).
"""

import os
import sys
import time

os.environ["PYOPENGL_PLATFORM"] = "egl"
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from OpenGL import GL                                       # noqa: E402
import gl_face_preview as prev                              # noqa: E402

W, H = prev.W, prev.H
TW, TH = W // 2, H // 2          # a tile
COLS = 5
LABEL_H = 28


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = args[0] if args else "/tmp/face_map.png"
    at = float(sys.argv[sys.argv.index("--at") + 1]) if "--at" in sys.argv else 0.5
    prev.egl_context()
    fbo = prev.framebuffer()
    from PIL import Image, ImageDraw, ImageFont
    import robot_face as rf
    import gl_face
    import reply_scenes
    from config import GESTURE_DURATION
    from shared_state import state
    rf.FACE_GL = False
    face = rf.RobotFace()
    rf.apply_style(3)
    face.gl = gl_face.GLFace(W, H)
    face.gl.target_fbo = fbo
    face.screen = gl_face.layer_surface(W, H)
    face.base = gl_face.layer_surface(W, H)
    face.back = gl_face.layer_surface(W, H)
    face.clock = type("NoWait", (), {"tick": lambda self, fps: 0})()
    fonts = os.path.join(os.path.dirname(HERE), "assets", "fonts")
    f_lab = ImageFont.truetype(os.path.join(fonts, "NunitoSans-Bold.ttf"), 17)
    f_head = ImageFont.truetype(os.path.join(fonts, "NunitoSans-ExtraBold.ttf"), 30)

    def reset():
        with state.lock:
            state.reply_scene = None
            state.gesture_anim = None
            state.gesture_anim_start = 0.0
            state.costume = None
            state.speaking = state.listening = False
            state.luna_mode = "idle"
            state.face_detected = True
            state.face_override = None
            state.overlay = None
            state.caption = None

    def grab():
        px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM)
        return img.convert("RGB").resize((TW, TH), Image.LANCZOS)

    def settle(mood, frames=36, each=None):
        for i in range(frames):
            if each:
                each(i)
            face.set_state(mood)
            face.draw()
        GL.glFinish()

    sections = []

    # ── the moods (brain.py's emotion → face_renderer's state) ──
    tiles = []
    for mood in ("neutral", "happy", "excited", "love", "sad", "angry", "surprised",
                 "thinking", "sleeping"):
        reset()
        with state.lock:
            state.face_detected = mood != "sleeping"
        settle(mood)
        tiles.append((mood, grab()))
    reset()                                           # listening, talking
    with state.lock:
        state.listening = True
        state.luna_mode = "listening"
    settle("neutral")
    tiles.append(("listening", grab()))
    reset()

    def talk(i):
        with state.lock:
            state.speaking = True
            state.audio_energy = 0.6 if i % 3 else 0.2
    settle("happy", each=talk)
    tiles.append(("talking (happy)", grab()))
    sections.append(("Moods", tiles))

    # ── gestures (gesture_module / brain "gesture") ──
    tiles = []
    for g, dur in GESTURE_DURATION.items():
        reset()
        with state.lock:
            state.gesture_anim = g
            state.gesture_anim_start = time.time() - dur * at
        settle("happy", frames=6)
        tiles.append((g, grab()))
    sections.append(("Gestures", tiles))

    # ── reply scenes (reply_scenes.SCENES) ──
    tiles = []
    for name, sc in reply_scenes.SCENES.items():
        reset()
        for i in range(8):
            with state.lock:                         # held at that point of the scene
                state.reply_scene = name
                state.reply_scene_start = time.time() - sc.duration * at
            face.set_state(sc.mood or "neutral")
            face.draw()
        GL.glFinish()
        tiles.append((name + (f" ({sc.mood})" if sc.mood else ""), grab()))
    sections.append((f"Reply scenes (caught at {int(at * 100)}%)", tiles))

    # ── costumes ("zrób kotka") ──
    tiles = []
    for c in rf.COSTUMES:
        reset()
        with state.lock:
            state.costume = (c, time.time() + 600)
        settle("happy")
        tiles.append((c, grab()))
    reset()
    sections.append(("Costumes", tiles))

    # ── the sheet ──
    height = sum(50 + -(-len(t) // COLS) * (TH + LABEL_H) for _, t in sections) + 70
    sheet = Image.new("RGB", (COLS * TW, height), (18, 18, 24))
    d = ImageDraw.Draw(sheet)
    d.text((16, 14), "Luna — every face (style 3, GPU face)", font=f_head, fill=(255, 214, 120))
    y = 70
    for title, tiles in sections:
        d.text((16, y + 8), f"{title} · {len(tiles)}", font=f_head, fill=(235, 235, 245))
        y += 50
        for i, (label, img) in enumerate(tiles):
            x, yy = (i % COLS) * TW, y + (i // COLS) * (TH + LABEL_H)
            sheet.paste(img, (x, yy))
            d.rectangle((x, yy + TH, x + TW, yy + TH + LABEL_H), fill=(30, 30, 40))
            d.text((x + 10, yy + TH + 4), label, font=f_lab, fill=(255, 255, 255))
        y += -(-len(tiles) // COLS) * (TH + LABEL_H)
    sheet.save(out)
    n = sum(len(t) for _, t in sections)
    print(f"[face_map] {n} faces → {out} ({sheet.size[0]}×{sheet.size[1]})")


if __name__ == "__main__":
    main()
