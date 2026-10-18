"""
gl_face_preview.py — render the OpenGL face (gl_face.py) headless, no window:
an EGL context without a surface draws into an offscreen framebuffer, so it
runs on the Pi beside the running Luna without touching her screen.

    ~/luna/venv/bin/python -X utf8 tools/gl_face_preview.py [out.png]

Writes a sheet of poses (neutral, happy, sad, angry, surprised, listening,
blink, talking, sleeping, glance, tilt, layer) and prints the GPU time per
frame — the 30 fps budget is 33 ms.

    … tools/gl_face_preview.py --radio [out.png] [stream-url]

The radio visualizer (visualizer.py): 8 s of a station decoded (not played),
fed through visualizer.tap on a fake clock, two frames per style.
"""

import ctypes
import os
import sys
import time

os.environ["PYOPENGL_PLATFORM"] = "egl"
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from OpenGL import EGL, GL                                   # noqa: E402
from OpenGL.raw.EGL.EXT.platform_base import eglGetPlatformDisplayEXT   # noqa: E402

W, H = 800, 480
EGL_PLATFORM_SURFACELESS_MESA = 0x31DD


def egl_context():
    dpy = eglGetPlatformDisplayEXT(EGL_PLATFORM_SURFACELESS_MESA, EGL.EGL_DEFAULT_DISPLAY, None)
    major, minor = EGL.EGLint(), EGL.EGLint()
    if not EGL.eglInitialize(dpy, ctypes.pointer(major), ctypes.pointer(minor)):
        raise RuntimeError("eglInitialize failed")
    EGL.eglBindAPI(EGL.EGL_OPENGL_API)
    # (the default asks for window surfaces — a surfaceless display has none)
    attrs = (EGL.EGLint * 5)(EGL.EGL_RENDERABLE_TYPE, EGL.EGL_OPENGL_BIT,
                             EGL.EGL_SURFACE_TYPE, EGL.EGL_PBUFFER_BIT, EGL.EGL_NONE)
    cfg, n = EGL.EGLConfig(), EGL.EGLint()
    EGL.eglChooseConfig(dpy, attrs, ctypes.pointer(cfg), 1, ctypes.pointer(n))
    if n.value < 1:
        raise RuntimeError("no EGL config")
    ctx = EGL.eglCreateContext(dpy, cfg, EGL.EGL_NO_CONTEXT, None)
    if not EGL.eglMakeCurrent(dpy, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, ctx):
        raise RuntimeError("eglMakeCurrent (surfaceless) failed")
    return dpy, ctx


def framebuffer():
    fbo = GL.glGenFramebuffers(1)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, W, H, 0, GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE, None)
    GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                              GL.GL_TEXTURE_2D, tex, 0)
    if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
        raise RuntimeError("framebuffer incomplete")
    return fbo


class FakeFace:
    """The attributes gl_face.face_uniforms reads, set by hand per pose."""

    def __init__(self, rf):
        self.left_eye, self.right_eye = rf.Eye(-rf.EYE_SPREAD, -30, 1, 1), rf.Eye(rf.EYE_SPREAD, -30, 1, 1)
        self.mouth = rf.Mouth(0, 155)
        self.left_blush, self.right_blush = rf.Blush(-240, 80), rf.Blush(240, 80)
        self.pose()

    def pose(self, emotion="neutral", w=206, h=147, blink=1.0, ox=0.0, oy=0.0,
             squint=0.0, widen=0.0, droop=0.0, listen=False, speak=0.0, tilt=0.0,
             blush=0.0, mouth_vis=None, tint=None, scene=None, scene_p=0.0):
        self._scene_name, self._scene_p = scene, scene_p
        self._emotion = emotion
        self._happy = emotion in ("happy", "excited", "love")
        self._sad, self._angry = emotion == "sad", emotion == "angry"
        self._listen, self._speaking = listen, speak > 0
        self._eye_color, self.angry_pulse = tint, 0.0
        self.head_angle, self.breath_phase = tilt, 0.0
        for e in (self.left_eye, self.right_eye):
            e.w, e.h, e.blink_t = w, h, blink
            e.pupil_ox, e.pupil_oy, e.pupil_scale = ox, oy, 1.0
            e.squint, e.widen, e.droop = squint, widen, droop
        m = self.mouth
        m.speak_fade = 1.0 if speak else 0.0
        m.talk_open, m.mouth_w, m.jaw_bounce = speak, 170.0, 0.0
        m.corner_lift = 0.8 if self._happy else 0.0
        m.visible = mouth_vis if mouth_vis is not None else (
            1.0 if speak else 0.85 if self._happy else 0.7
            if emotion in ("surprised", "sad", "angry") else 0.5 if emotion == "sleeping" else 0.0)
        self.left_blush.alpha = self.right_blush.alpha = blush


POSES = [
    ("neutral", {}),
    ("happy", dict(emotion="happy", blush=170)),
    ("sad", dict(emotion="sad", droop=1.0, oy=10)),
    ("angry", dict(emotion="angry")),
    ("surprised", dict(emotion="surprised", w=230, h=190, widen=1.0)),
    ("listening", dict(listen=True, widen=0.6, tint=(255, 245, 215))),
    ("blink", dict(blink=0.18)),
    ("talking", dict(speak=0.7)),
    ("sleeping", dict(emotion="sleeping", blink=0.05)),
    ("glance", dict(ox=-40, oy=-14)),
    ("squint", dict(squint=0.7, blush=120)),
    ("tilt", dict(emotion="happy", tilt=8.0)),
    ("glitch", dict(scene="glitch", scene_p=0.4, widen=0.5)),
]


def live(out, gpu=True):
    """The real RobotFace — its own update() and draw(), blinks, gaze and all —
    with the GPU face, offscreen: frames per emotion, and the whole frame's cost
    (pygame's part, the upload and the GPU)."""
    egl_context()
    fbo = framebuffer()
    from PIL import Image, ImageDraw
    import pygame
    import robot_face as rf
    import gl_face
    from shared_state import state
    rf.FACE_GL = False                       # its window: the dummy one
    face = rf.RobotFace()
    rf.apply_style(3)
    if gpu:
        face.gl = gl_face.GLFace(W, H)
        face.gl.target_fbo = fbo
        face.screen = gl_face.layer_surface(W, H)
        face.base = gl_face.layer_surface(W, H)
        face.back = gl_face.layer_surface(W, H)
    face.clock = type("NoWait", (), {"tick": lambda self, fps: 0})()
    tiles, costs = [], []
    looks = [(e, None) for e in ("neutral", "happy", "sad", "angry", "surprised", "love",
                                 "sleeping")]
    looks += [("happy", c) for c in rf.COSTUMES]          # "zamień się w kotka"…
    for emo, costume in looks:
        with state.lock:
            state.face_detected = emo != "sleeping"
            state.costume = (costume, time.time() + 600) if costume else None
        for i in range(40):
            face.set_state(emo)              # (face_renderer.py does this per frame)
            t0 = time.perf_counter()
            face.draw()
            GL.glFinish()
            costs.append(time.perf_counter() - t0)
        if gpu:
            px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
            img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM)
        else:
            size = face.screen.get_size()         # (the dummy window may be bigger)
            img = Image.frombytes("RGB", size, pygame.image.tobytes(face.screen, "RGB"))
            img = img.crop((0, 0, W, H))
        ImageDraw.Draw(img).text((10, 8), costume or emo, fill=(255, 255, 255))
        tiles.append(img)
    costs.sort()
    print(f"[live] whole frame: median {costs[len(costs) // 2] * 1000:.1f} ms, "
          f"90% {costs[int(len(costs) * 0.9)] * 1000:.1f} ms")
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * W // 2, rows * H // 2))
    for i, t in enumerate(tiles):
        sheet.paste(t.convert("RGB").resize((W // 2, H // 2), Image.LANCZOS),
                    ((i % cols) * W // 2, (i // cols) * H // 2))
    sheet.save(out)
    print(f"[live] wrote {out}")


def radio_sheet(out, url=None):
    import subprocess
    import numpy as np
    from PIL import Image, ImageDraw
    import robot_face as rf
    import gl_face
    import radio
    import visualizer
    url = url or radio.CATALOG[0][3][0][1]
    pcm = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-t", "8",
                          "-i", url, "-f", "s16le", "-ac", "2", "-ar", "44100", "-"],
                         capture_output=True, timeout=40).stdout
    a = np.frombuffer(pcm, np.int16).astype(np.float32)
    print(f"[radio] {len(a) / 88200:.1f} s decoded from {url}")
    clock = [1000.0]
    visualizer.time = type("T", (), {"time": staticmethod(lambda: clock[0])})()
    egl_context()
    fbo = framebuffer()
    rf.apply_style(3)
    g = gl_face.GLFace(W, H)
    g.target_fbo = fbo
    face = FakeFace(rf)
    fcx, fcy = W // 2, H // 2 + rf.FACE_Y_OFFSET
    level = float(np.sqrt(np.mean(a * a))) or 1.0
    chunk = 8820
    tiles, ms = [], []
    shots = [("fala", 30), ("fala", 55), ("slupki", 30), ("slupki", 55),
             ("oczy", 30), ("oczy", 55), ("wszystko", 40), ("fala talking", 45)]
    for name, at in shots:
        sty = name.split()[0]
        visualizer._style[:] = [sty, 1e12]
        face.pose(speak=0.6 if "talking" in name else 0.0)
        visualizer.reset()
        for i in range(at):
            visualizer.tap(a[i * chunk:(i + 1) * chunk], level)
            for _ in range(3):
                clock[0] += 0.0333
                u = g.face_uniforms(face, rf, fcx, fcy)
        GL.glFinish()
        t0 = time.perf_counter()
        g.render(u)
        GL.glFinish()
        ms.append((time.perf_counter() - t0) * 1000)
        px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM)
        ImageDraw.Draw(img).text((10, 8), name, fill=(255, 255, 255, 255))
        tiles.append(img)
    # GPU cost with and without (the same pose)
    for sty in ("off", "fala", "slupki", "oczy"):
        visualizer._style[:] = [sty, 1e12]
        u = g.face_uniforms(face, rf, fcx, fcy)
        GL.glFinish()
        t0 = time.perf_counter()
        for _ in range(60):
            g.render(u)
        GL.glFinish()
        print(f"[radio] {sty}: {(time.perf_counter() - t0) / 60 * 1000:.1f} ms a frame")
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * W // 2, rows * H // 2))
    for i, t in enumerate(tiles):
        sheet.paste(t.convert("RGB").resize((W // 2, H // 2), Image.LANCZOS),
                    ((i % cols) * W // 2, (i // cols) * H // 2))
    sheet.save(out)
    print(f"[radio] wrote {out}")


def main():
    if "--radio" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        return radio_sheet(args[0] if args else "/tmp/gl_face_radio.png",
                           args[1] if len(args) > 1 else None)
    if "--live" in sys.argv or "--pygame" in sys.argv:
        gpu = "--pygame" not in sys.argv              # --pygame: today's face, to compare
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        return live(args[0] if args else "/tmp/gl_face_live.png", gpu)
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/gl_face_sheet.png"
    egl_context()
    fbo = framebuffer()
    import numpy as np
    from PIL import Image, ImageDraw
    import pygame
    import robot_face as rf
    import gl_face
    rf.apply_style(3)
    g = gl_face.GLFace(W, H)
    g.target_fbo = fbo                          # not a window: the offscreen one
    face = FakeFace(rf)
    fcx, fcy = W // 2, H // 2 + rf.FACE_Y_OFFSET
    tiles = []
    for name, kw in POSES:
        face.pose(**kw)
        for _ in range(30):                     # let the eased shapes settle
            u = g.face_uniforms(face, rf, fcx, fcy)
        g.render(u)
        px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM)
        ImageDraw.Draw(img).text((10, 8), name, fill=(255, 255, 255, 255))
        tiles.append(img)
    # a pygame layer on top (as robot_face will lay its particles, captions…)
    pygame.init()
    layer = gl_face.layer_surface(W, H)
    pygame.draw.circle(layer, (255, 120, 150, 220), (640, 90), 26)
    pygame.draw.rect(layer, (0, 0, 0, 170), pygame.Rect(0, H - 60, W, 60))
    face.pose(emotion="happy", blush=150)
    for _ in range(30):                         # (the eased shapes settle)
        u = g.face_uniforms(face, rf, fcx, fcy)
    has = g.upload_layer(layer)
    g.render(u, has_layer=has)
    px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
    img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM)
    ImageDraw.Draw(img).text((10, 8), "layer", fill=(255, 255, 255, 255))
    tiles.append(img)

    # GPU time per frame
    face.pose(speak=0.6)
    u = g.face_uniforms(face, rf, fcx, fcy)
    GL.glFinish()
    t0 = time.perf_counter()
    n = 60
    for _ in range(n):
        g.render(u)
    GL.glFinish()
    ms = (time.perf_counter() - t0) / n * 1000
    # the upload as in use: a status bar that stays, a particle that moves
    t0 = time.perf_counter()
    for i in range(n):
        layer.fill((0, 0, 0, 0))
        pygame.draw.rect(layer, (20, 20, 20, 230), pygame.Rect(0, 0, W, 30))
        pygame.draw.circle(layer, (255, 120, 150, 220), (100 + i * 8, 300), 14)
        g.upload_layer(layer)
    GL.glFinish()
    up = (time.perf_counter() - t0) / n * 1000
    # the worst case: the whole layer changes every frame (a photo overlay)
    t0 = time.perf_counter()
    for i in range(n):
        layer.fill((i * 4 % 255, 40, 80, 255))
        g.upload_layer(layer)
    GL.glFinish()
    full = (time.perf_counter() - t0) / n * 1000
    print(f"[preview] {ms:.1f} ms per face frame; layer upload {up:.1f} ms "
          f"(status bar + a particle), {full:.1f} ms (all of it changing); "
          f"30 fps = 33 ms")

    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * W // 2, rows * H // 2))
    for i, t in enumerate(tiles):
        sheet.paste(t.convert("RGB").resize((W // 2, H // 2), Image.LANCZOS),
                    ((i % cols) * W // 2, (i // cols) * H // 2))
    sheet.save(out)
    print(f"[preview] wrote {out}")


if __name__ == "__main__":
    main()
