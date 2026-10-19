"""
render_bench.py — the real RobotFace (update + draw + the GPU face) offscreen
on a fake clock: a fixed script of moods, talking, listening, a costume and
the sleeping zzz, the same pixels every run. Prints the cost of a frame
(CPU and GPU) and can save every Nth frame, to compare two versions of the
code pixel for pixel. Runs on the Pi beside Luna (EGL, no window).

    cd <a luna copy> && ~/luna/venv/bin/python -X utf8 tools/render_bench.py \\
        [--fps 30] [--anim 30] [--secs 24] [--save DIR] [--every 6]
    python3 tools/render_bench.py --diff DIR_A DIR_B
"""

import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "--diff" in sys.argv:
    from PIL import Image, ImageChops
    a, b = [x for x in sys.argv[1:] if not x.startswith("--")][:2]
    worst = 0
    for name in sorted(os.listdir(a)):
        if not os.path.exists(os.path.join(b, name)):
            continue
        ia = Image.open(os.path.join(a, name)).convert("RGB")
        ib = Image.open(os.path.join(b, name)).convert("RGB")
        d = ImageChops.difference(ia, ib)
        box = d.getbbox()
        mx = max(hi for _, hi in d.getextrema())
        worst = max(worst, mx)
        if box:
            px = sum(1 for p in d.getdata() if max(p) > 8)
            print(f"{name}: differs in {box}, max {mx}, {px} px > 8")
    print(f"[diff] worst channel difference {worst}")
    sys.exit(0)

os.environ["PYOPENGL_PLATFORM"] = "egl"
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("LUNA_DATA_DIR", "/tmp/render_bench_data")

from tools.gl_face_preview import egl_context, framebuffer, W, H   # noqa: E402


def arg(name, default):
    if name in sys.argv:
        return type(default)(sys.argv[sys.argv.index(name) + 1])
    return default


FPS, SECS = arg("--fps", 30), arg("--secs", 24.0)
PROFILE = arg("--profile", -1.0)          # cProfile one second of the script from here
SAVE, EVERY = arg("--save", ""), arg("--every", 6)
TRACE = arg("--trace", "")                # a CSV of the animation's values per frame

# the fake clock: every frame moves it 1/FPS (the script's times are seconds)
T0 = 1_760_000_000.0
NOW = [T0]
_real_lt, _real_sf = time.localtime, time.strftime
time.time = lambda: NOW[0]
time.monotonic = lambda: NOW[0] - T0 + 1000.0
time.localtime = lambda s=None: _real_lt(NOW[0] if s is None else s)
time.strftime = lambda f, t=None: _real_sf(f, t if t is not None else time.localtime())
random.seed(7)

# (seconds from the start, what happens)
SCRIPT = [
    (0.0, dict(face=True, emo="neutral")),
    (3.0, dict(listening=True, convo=True)),
    (5.0, dict(listening=False, speaking=True, emo="happy")),
    (9.0, dict(speaking=False, emo="surprised")),
    (11.0, dict(emo="love", costume="cat")),
    (15.0, dict(costume=None, emo="sad")),
    (18.0, dict(emo="angry")),
    (20.0, dict(face=False, emo="sleeping", convo=False)),
]


def main():
    egl_context()
    fbo = framebuffer()
    from OpenGL import GL
    import robot_face as rf
    import gl_face
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
    face.fps = FPS
    face.anim_fps = arg("--anim", 30)           # the animation's pace (face_renderer's)
    costume = next(iter(rf.COSTUMES), None)
    if SAVE:
        os.makedirs(SAVE, exist_ok=True)
        from PIL import Image
    n = int(SECS * FPS)
    cpu, gpu = [], []
    cur = {}
    step = 0
    seg = {}
    trace = ["t,blink_open,eye_w,eye_h,pupil_ox,face_oy,head_angle,idle,talk_open"]
    for i in range(n):
        t = i / FPS
        while step < len(SCRIPT) and SCRIPT[step][0] <= t + 1e-9:
            cur.update(SCRIPT[step][1])
            step += 1
        with state.lock:
            state.face_detected = cur.get("face", True)
            state.listening = cur.get("listening", False)
            state.speaking = state.audio_playing = cur.get("speaking", False)
            # (a voice by the clock, not by the frame: the same at any frame rate)
            state.audio_energy = (0.45 + 0.4 * math.sin(19.0 * t) * math.sin(4.3 * t)
                                  if state.speaking else 0.0)
            state.conversation_active = cur.get("convo", False)
            c = cur.get("costume")
            state.costume = ((costume if c else None), NOW[0] + 600) if c and costume else None
        face.set_state(cur.get("emo", "neutral"))
        prof = PROFILE <= t < PROFILE + 1.0
        if prof:
            import cProfile
            pr = pr if "pr" in dir() else cProfile.Profile()
            pr.enable()
        t0 = time.perf_counter()
        face.draw()
        t1 = time.perf_counter()
        if prof:
            pr.disable()
        GL.glFinish()
        t2 = time.perf_counter()
        cpu.append(t1 - t0)
        gpu.append(t2 - t1)
        seg.setdefault(step, []).append(t1 - t0)
        if TRACE:
            e = face.left_eye
            trace.append(f"{t:.4f},{face.blink_open:.4f},{e.w:.3f},{e.h:.3f},{face.pupil_ox:.3f},"
                         f"{face.face_oy:.3f},{face.head_angle:.4f},{face.idle_frames:.2f},"
                         f"{face.mouth.talk_open:.4f}")
        if SAVE and i % EVERY == 0:
            px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
            img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM)
            # named by the time on the script, so 30 and 45 fps runs line up
            img.convert("RGB").save(os.path.join(SAVE, f"t{int(round(t * 1000)):06d}.png"))
        NOW[0] += 1.0 / FPS

    if TRACE:
        with open(TRACE, "w") as f:
            f.write("\n".join(trace) + "\n")
    if PROFILE >= 0:
        import pstats
        pstats.Stats(pr).sort_stats("tottime").print_stats(18)

    def stat(xs):
        xs = sorted(xs)
        return (f"median {1000 * xs[len(xs) // 2]:.1f} ms, 90% {1000 * xs[int(len(xs) * 0.9)]:.1f}, "
                f"mean {1000 * sum(xs) / len(xs):.1f}")
    for k in sorted(seg):
        xs = sorted(seg[k])
        print(f"[bench]   from {SCRIPT[k - 1][0]:4.1f} s {SCRIPT[k - 1][1]}: CPU median "
              f"{1000 * xs[len(xs) // 2]:.1f} ms, max {1000 * xs[-1]:.1f}")
    print(f"[bench] {n} frames at {FPS} fps — CPU {stat(cpu)}; GPU after it {stat(gpu)}")
    st = rf.frame_stats
    k = max(1, st["frames"])
    print("[bench] per frame: " + ", ".join(f"{x} {1000 * st.get(x, 0) / k:.2f}" for x in
                                            ("update", "face", "compose", "gl")) + " ms")
    p = getattr(gl_face, "PROF", None)
    if p:
        m = max(1, p["n"])
        print("[bench] gl: " + ", ".join(f"{x} {1000 * p[x] / m:.2f}" for x in
                                         ("uni", "up_face", "up_back", "up_screen", "draw", "g0", "g1", "gback",
                                          "gshape", "gface", "gscreen") if x in p) + " ms")


main()
