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

    … tools/gl_face_preview.py --fx [out_dir] [theme…] [look…]

What gl_fx.py draws over the face — the listening waves, hands (HAL: glyphs),
costumes — per theme, on the real RobotFace; a sheet each and every frame.

    … tools/gl_face_preview.py --chars [out_dir] [kind…]

The drawn characters (gl_chars.py) and Luna's three skins: a sheet each of
every expression, visemes, gestures and accessories, a GIF of transitions and
speech, and each one's GPU time per frame — on a fake clock, seeded.

    … tools/gl_face_preview.py --lamp [out.png] [scene…]

The lamp's scenes (lamp_scenes.py): two frames each and the GPU time; one
scene named: full size.
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


FX_LOOKS = [            # (name, how to set it up: a state field → value; "start" fields: now)
    ("listen", {"listening": True, "mic_level": 0.45}),
    ("wave", {"gesture_anim": "wave", "gesture_anim_start": 0.9}),
    ("thumbs_up", {"gesture_anim": "thumbs_up", "gesture_anim_start": 1.0}),
    ("heart", {"gesture_anim": "heart", "gesture_anim_start": 1.4}),
    ("thinking", {"emotion": "thinking"}),
    ("scissors", {"game_hand": "scissors"}),
    ("paper", {"game_hand": "paper"}),
    ("air_heart", {"reply_scene": "air_heart", "reply_scene_start": 2.6}),
    ("cat", {"costume": "cat"}),
    ("steampunk", {"costume": "steampunk"}),
    ("crazy_robot", {"costume": "crazy_robot"}),
    ("party", {"costume": "party"}),
    # the particles (one of each put in, the mood's own come on their own)
    ("sad", {"emotion": "sad", "inject": "tear"}),
    ("angry", {"emotion": "angry"}),
    ("surprised", {"emotion": "surprised"}),
    ("sleeping", {"emotion": "sleeping", "inject": "zzz"}),
    ("love", {"emotion": "love"}),
    ("excited", {"emotion": "excited"}),
    ("waves", {"inject": "wave"}),
]
# the reply scenes that draw props (reply_scenes.py), caught a little past halfway
SCENE_LOOKS = ("big_pupils", "flutter", "heart_eyes", "sparkle_eyes", "snap", "air_heart",
               "laugh", "sigh", "think_bubble", "scared", "relief", "curious", "sunny",
               "cloudy", "rainy", "snowy", "lightbulb", "music_notes",
               # the hands (a drawn character draws its own: gl_chars)
               "clap", "wave_both", "scratch_head", "salute", "thumbs_down", "ok_sign")


def fx_sheet(out_dir, theme_keys=("luna", "hal"), only=None):
    """The real RobotFace with the GPU face, offscreen, per theme: listening,
    the gestures, a costume — what gl_fx.py draws. A sheet per theme and each
    frame at full size; the listening waves' radii frame by frame (smooth:
    no steps) and the cost of a frame with them."""
    egl_context()
    fbo = framebuffer()
    from PIL import Image, ImageDraw
    import robot_face as rf
    import gl_face
    import themes
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
    os.makedirs(out_dir, exist_ok=True)
    import reply_scenes
    looks = list(FX_LOOKS) + [
        ("s_" + n, {"reply_scene": n,
                    "reply_scene_start": reply_scenes.SCENES[n].duration * 0.6 - 0.8})
        for n in SCENE_LOOKS]
    blank = {"listening": False, "mic_level": 0.0, "gesture_anim": None, "game_hand": None,
             "reply_scene": None, "costume": None}
    face.draw()                              # (the shaders compiled: not in the numbers)
    for key in theme_keys:
        themes.current = lambda now=None, key=key: key
        tiles = []
        for name, setup in looks:
            if only and name not in only and not (name.startswith("s_") and "scenes" in only):
                continue
            with state.lock:
                for k, v in blank.items():
                    setattr(state, k, v)
                state.face_detected = True
                now = time.time()
                for k, v in setup.items():
                    if k.endswith("_start"):
                        setattr(state, k, now - v)
                    elif k == "game_hand":
                        state.game_hand = (v, now + 60)
                    elif k == "costume":
                        state.costume = (v, now + 600)
                    elif k not in ("emotion", "inject"):
                        setattr(state, k, v)
            emo = setup.get("emotion", "happy" if "costume" in setup else "neutral")
            face.set_state(emo)
            fcx, fcy = W // 2, H // 2 + rf.FACE_Y_OFFSET
            inject = setup.get("inject")
            if inject == "tear":
                face.tear_particles += [rf.TearParticle(fcx - 160, fcy + 20),
                                        rf.TearParticle(fcx + 160, fcy + 40)]
            elif inject == "zzz":
                face.zzz_particles += [rf.ZzzParticle(fcx + 40, fcy - 100),
                                       rf.ZzzParticle(fcx - 30, fcy - 60)]
            elif inject == "wave":
                face.sound_waves += [rf.SoundWave(fcx, fcy + 120) for _ in range(3)]
                face.sound_waves[1].r, face.sound_waves[2].r = 45.0, 70.0
                face.wake_anim, face.wake_ripple = face._WAKE_ACTIVE, 0.25
                face.steam_particles += [rf.SteamParticle(fcx + dx, fcy - 80) for dx in (-190, 190)]
                for _ in range(4):
                    face.star_particles.append(rf.StarParticle(fcx + 250, fcy - 120))
            t_end = time.monotonic() + (2.6 if name == "thinking" else 0.8)
            radii, costs = [], []
            while time.monotonic() < t_end:
                face.set_state(emo)
                t0 = time.perf_counter()
                face.draw()
                GL.glFinish()
                costs.append(time.perf_counter() - t0)
                if name == "listen":
                    arcs = [i for i in getattr(rf, "_FX", {}).get(id(face.base), []) if i[0] == "arcs"]
                    if arcs:
                        radii.append(arcs[0][4][0])
            px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
            img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM).convert("RGB")
            img.save(os.path.join(out_dir, f"{key}_{name}.png"))
            ImageDraw.Draw(img).text((10, 36), f"{key}: {name}", fill=(255, 255, 255))
            tiles.append(img)
            costs.sort()
            print(f"[fx] {key} {name}: {len(costs)} frames, median {costs[len(costs) // 2] * 1000:.1f} ms"
                  + (f", radii {' '.join(f'{r:.2f}' for r in radii[-8:])}" if radii else ""),
                  flush=True)
        cols = 4
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * W // 2, rows * H // 2))
        for i, t in enumerate(tiles):
            sheet.paste(t.resize((W // 2, H // 2), Image.LANCZOS),
                        ((i % cols) * W // 2, (i // cols) * H // 2))
        sheet.save(os.path.join(out_dir, f"{key}_sheet.png"))
    print(f"[fx] wrote {out_dir}; images made {face.gl.fx.made if getattr(face.gl, "fx", None) else 0}")


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
    shots = [("wstegi pomaranczowe", 40), ("pierscienie neonowe", 41), ("iskry zachod", 42),
             ("slupki zielone", 43), ("oscyloskop niebieskie", 44), ("nutki rozowe", 45),
             ("wstegi fioletowe", 46), ("iskry neonowe", 47), ("wstegi zachod", 48),
             ("nutki zlote", 49), ("slupki czerwone", 50), ("pierscienie fioletowe talking", 51)]
    for name, at in shots:
        sty, pal = name.split()[:2]                   # (a style, its colours)
        visualizer._style[:] = [sty, 1e12]
        visualizer._colset[0] = pal
        visualizer._col[:] = [np.array(c) for c in visualizer.COLORS[pal]]
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
    for sty in ("off",) + visualizer.SHOWN:
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


def lamp_sheet(out, only=None):
    """The lamp's scenes (lamp_scenes.py, gl_lamp.py): each simulated for a
    while on a fake clock, two frames apart, and its GPU time per frame."""
    from PIL import Image, ImageDraw
    import pygame
    import gl_face
    import lamp_scenes
    egl_context()
    fbo = framebuffer()
    pygame.init()
    g = gl_face.GLFace(W, H)
    g.target_fbo = fbo
    layer = gl_face.layer_surface(W, H)
    tiles = []
    for scene in only or lamp_scenes.SCENES:
        t0 = 1_000_000.0
        data = {"scene": scene, "t0": t0}
        for i, at in enumerate((20.0, 47.0)):
            now = t0
            while now < t0 + at:                      # the simulation, in steps
                now += 1 / 20
                u = lamp_scenes.uniforms(data, now, t0 + 3600, W, H)
            layer.fill((0, 0, 0, 0))
            if scene == "zegar":
                lamp_scenes.draw_clock(layer, now + 5, W, H)
            g.render_lamp(u, layer)
            px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
            img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM)
            ImageDraw.Draw(img).text((10, 8), f"{scene} {at:.0f}s", fill=(255, 255, 255, 255))
            tiles.append(img)
        GL.glFinish()
        t1 = time.perf_counter()
        for _ in range(30):
            g.render_lamp(u, layer)
        GL.glFinish()
        print(f"[lamp] {scene}: {(time.perf_counter() - t1) / 30 * 1000:.1f} ms a frame")
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    full = only is not None and len(only) == 1
    tw, th = (W, H) if full else (W // 2, H // 2)
    sheet = Image.new("RGB", (cols * tw, rows * th))
    for i, t in enumerate(tiles):
        sheet.paste(t.convert("RGB").resize((tw, th), Image.LANCZOS),
                    ((i % cols) * tw, (i // cols) * th))
    sheet.save(out)
    print(f"[lamp] wrote {out}")


def lamp_motion(out, scene, secs=8.0, fps=12, start=30.0):
    """One scene moving: a GIF (half size) and next to it a strip of every
    5th frame — how alive it looks, not just how it looks."""
    from PIL import Image
    import pygame
    import gl_face
    import lamp_scenes
    egl_context()
    fbo = framebuffer()
    pygame.init()
    g = gl_face.GLFace(W, H)
    g.target_fbo = fbo
    layer = gl_face.layer_surface(W, H)
    t0 = 1_000_000.0
    data = {"scene": scene, "t0": t0}
    now = t0
    while now < t0 + start:                           # (settled, faded in)
        now += 1 / 20
        u = lamp_scenes.uniforms(data, now, t0 + 3600, W, H)
    frames = []
    for i in range(int(secs * fps)):
        now += 1 / fps
        u = lamp_scenes.uniforms(data, now, t0 + 3600, W, H)
        layer.fill((0, 0, 0, 0))
        if scene == "zegar":
            lamp_scenes.draw_clock(layer, now, W, H)
        g.render_lamp(u, layer)
        px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        frames.append(Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM)
                      .convert("RGB"))
    small = [f.resize((W // 2, H // 2), Image.LANCZOS) for f in frames]
    gif = os.path.splitext(out)[0] + ".gif"
    small[0].save(gif, save_all=True, append_images=small[1:], duration=int(1000 / fps), loop=0)
    picks = small[::5][:8]
    strip = Image.new("RGB", (2 * W // 2, 4 * H // 2))
    for i, f in enumerate(picks):
        strip.paste(f, ((i % 2) * W // 2, (i // 2) * H // 2))
    strip.save(out)
    full = Image.new("RGB", (2 * W, 2 * H))           # four frames full size, 0.5 s apart
    for i, f in enumerate(frames[:4 * fps // 2:fps // 2]):
        full.paste(f, ((i % 2) * W, (i // 2) * H))
    full.save(os.path.splitext(out)[0] + "_full.png")
    print(f"[lamp] wrote {gif} and {out} (every {5 / fps:.2f} s)")


# the drawn characters (characters.py, gl_chars.py): every expression, the
# voice's visemes, gestures, accessories — deterministic (a fake clock, seeded)
CHAR_POSES = [
    ("neutral", {}, None),
    ("happy", dict(emotion="happy", blush=170), None),
    ("thinking", dict(emotion="thinking"), None),
    ("sad", dict(emotion="sad", droop=1.0, oy=10), None),
    ("angry", dict(emotion="angry"), None),
    ("surprised", dict(emotion="surprised", widen=1.0), None),
    ("listening", dict(listen=True, widen=0.6), None),
    ("speaking", dict(speak=0.6), "visemes"),
    ("blink+speak", dict(speak=0.5, blink=0.12), "visemes"),
    ("sleeping", dict(emotion="sleeping", blink=0.0), None),
    ("love", dict(emotion="love"), None),
    ("excited", dict(emotion="excited"), None),
    ("celebrate", dict(emotion="happy"), "g:celebrate"),
    ("confused", {}, "g:confused"),
    ("alert", {}, "g:alert"),
    ("nod", {}, "g:nod"),
    ("glance", dict(ox=-40, oy=-14), None),
    ("all accessories", dict(emotion="happy"), "acc:all"),
    ("no accessories", {}, "acc:none"),
    ("effects off", {}, "fx:off"),
    ("waking", {}, "wake"),
    ("sync lost", {}, "g:alert"),
]
# a few of her real sounds: (brightness, zero-crossings) of openai_tts.Envelope, and the jaw
VISEME_TRACK = [((0.10, 0.05), 0.7), ((0.07, 0.04), 0.55), ((0.20, 0.08), 0.45),
                ((0.90, 0.50), 0.25), ((0.12, 0.05), 0.8), ((0.06, 0.03), 0.6),
                ((0.0, 0.0), 0.02), ((0.16, 0.06), 0.5)]


def chars_sheet(out_dir, kinds=None):
    egl_context()
    fbo = framebuffer()
    import random
    from PIL import Image, ImageDraw
    import robot_face as rf
    import characters
    import face_spec
    import gl_chars
    import gl_face
    import themes
    os.makedirs(out_dir, exist_ok=True)
    clock = [5000.0]
    gl_face._clock = lambda: clock[0]
    gl_face._hour = lambda: 14
    random.seed(7)
    gl_chars.seed(7)
    rf.apply_style(3)
    g = gl_face.GLFace(W, H)
    g.target_fbo = fbo
    face = FakeFace(rf)
    face.mouth.rel_y = face_spec.LAYOUT["mouth_y"]
    for e in (face.left_eye, face.right_eye):
        e.rel_y = face_spec.LAYOUT["eye_y"]
    fcx, fcy = W // 2, H // 2 + rf.FACE_Y_OFFSET
    acc_real, con_real, fx_real = (characters.accessories, characters.retro_console,
                                   characters.fx_level)
    timings = {}

    def frame(n, track=False, setup=None, kind=None):
        u = None
        for i in range(n):
            clock[0] += 1 / 30
            if track:
                (b, z), jaw = VISEME_TRACK[int(clock[0] * 9) % len(VISEME_TRACK)]
                face._audio_shape = (b, z)
                face.mouth.talk_open = jaw
                face._audio_energy = jaw
            if setup and setup.startswith("g:") and i == n - 18:
                characters.trigger(setup[2:])
            u = g.face_uniforms(face, rf, fcx, fcy)
        return u

    def shot(u, label):
        g.render(u)
        px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM).convert("RGB")
        ImageDraw.Draw(img).text((10, 8), label, fill=(255, 255, 255))
        return img

    for kind in kinds or ("luna", "hal") + characters.KINDS:
        themes.current = lambda now=None, key=kind: key
        modes = [None]
        if kind == "retro":
            modes = ["console", "face"]
        for mode in modes:
            characters.retro_console = (lambda now=None, m=mode: m != "face")
            tiles = []
            for label, kw, setup in CHAR_POSES:
                characters.accessories = acc_real
                characters.fx_level = fx_real
                if kind in characters.CHARS and setup == "acc:all":
                    characters.accessories = lambda k, now=None: characters.CHARS[k]["accessories"]
                elif kind in characters.CHARS and setup == "acc:none":
                    characters.accessories = lambda k, now=None: ()
                elif setup == "fx:off":
                    characters.fx_level = lambda now=None: 0.0
                face.pose(**kw)
                face._audio_shape, face._audio_energy, face._gesture = None, 0.0, None
                face.fps = 30
                face._mic = 0.75 if kw.get("listen") else 0.0      # (the mic's level)
                face._WAKE_ACTIVE = 1
                face.wake_anim, face.wake_ripple = (1, 0.42) if setup == "wake" else (0, 1.0)
                if getattr(g, "char_life", None):     # (each pose on its own: no gesture left over)
                    g.char_life.active.clear()
                u = frame(40, setup == "visemes", setup, kind)
                tiles.append(shot(u, f"{kind}{'/' + mode if mode else ''}: {label}"))
            # the cost of a frame: GPU time, the speaking pose
            face.pose(speak=0.6)
            u = frame(10, True)
            GL.glFinish()
            t0 = time.perf_counter()
            for _ in range(60):
                g.render(u)
            GL.glFinish()
            gpu = (time.perf_counter() - t0) / 60 * 1000
            t0 = time.perf_counter()
            for _ in range(60):
                clock[0] += 1 / 30
                u = g.face_uniforms(face, rf, fcx, fcy)
            cpu = (time.perf_counter() - t0) / 60 * 1000
            name = kind + ("_" + mode if mode else "")
            timings[name] = (gpu, cpu)
            print(f"[chars] {name}: GPU {gpu:.1f} ms a frame, uniforms (CPU) {cpu:.2f} ms",
                  flush=True)
            # a transition strip and the speaking, as a GIF (15 fps)
            seq = []
            for emo, n in (("neutral", 8), ("happy", 14), ("sad", 14), ("surprised", 10),
                           ("angry", 12), ("neutral", 10)):
                face.pose(emotion=emo)
                for _ in range(n):
                    u = frame(2)
                    seq.append(shot(u, f"{name}: {emo}").resize((W // 2, H // 2)))
            face.pose(speak=0.6)
            for _ in range(36):
                u = frame(2, True)
                seq.append(shot(u, f"{name}: speaking").resize((W // 2, H // 2)))
            seq[0].save(os.path.join(out_dir, f"{name}.gif"), save_all=True,
                        append_images=seq[1:], duration=66, loop=0)
            cols = 4
            rows = (len(tiles) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * W // 2, rows * H // 2))
            for i, t in enumerate(tiles):
                sheet.paste(t.resize((W // 2, H // 2), Image.LANCZOS),
                            ((i % cols) * W // 2, (i // cols) * H // 2))
            sheet.save(os.path.join(out_dir, f"{name}_sheet.png"))
            tiles[0].save(os.path.join(out_dir, f"{name}_neutral.png"))
    characters.accessories, characters.retro_console, characters.fx_level = (
        acc_real, con_real, fx_real)
    print(f"[chars] wrote {out_dir}; programs compiled "
          f"{g.chars.made if getattr(g, 'chars', None) else 0}")
    return timings


def main():
    if "--chars" in sys.argv:                         # --chars [out_dir] [kind…]
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        return chars_sheet(args[0] if args else "/tmp/gl_chars", args[1:] or None)
    if "--motion" in sys.argv:                        # --motion out.png scene [secs]
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        return lamp_motion(args[0], args[1], float(args[2]) if len(args) > 2 else 8.0,
                           start=float(args[3]) if len(args) > 3 else 30.0)
    if "--lamp" in sys.argv:                          # --lamp [out.png] [scene…]
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        return lamp_sheet(args[0] if args else "/tmp/gl_lamp.png", args[1:] or None)
    if "--radio" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        return radio_sheet(args[0] if args else "/tmp/gl_face_radio.png",
                           args[1] if len(args) > 1 else None)
    if "--fx" in sys.argv:                            # --fx [out_dir] [theme…] [look…]
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        import themes
        keys = [a for a in args[1:] if a in themes.THEMES] or ("luna", "hal")
        looks = [a for a in args[1:] if a not in themes.THEMES]
        return fx_sheet(args[0] if args else "/tmp/gl_fx", keys, looks or None)
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
