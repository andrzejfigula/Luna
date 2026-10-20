"""
face_trace.py — the real RobotFace with the GPU face, offscreen (EGL), driven
through a script of moods, talking, listening and someone coming and going;
every frame's shader inputs are recorded and the jumps listed: a value that
moves much further in one frame than in the frames round it (a glitch, not
a glide). On the Pi, beside the running Luna (no window, no sound):

    ~/luna/venv/bin/python -X utf8 tools/face_trace.py [out.json]
"""

import json
import math
import os
import sys
import time

os.environ["PYOPENGL_PLATFORM"] = "egl"
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from OpenGL import GL                                         # noqa: E402
import gl_face_preview as P                                   # noqa: E402

# (at s, what changes): emotion, speaking, listening, someone seen
SCRIPT = [
    (0.0, dict(emo="neutral", seen=True)),
    (2.0, dict(emo="happy")),
    (4.5, dict(emo="sad")),
    (7.0, dict(emo="angry")),
    (9.5, dict(emo="surprised")),
    (11.5, dict(emo="neutral", listen=True)),
    (14.0, dict(listen=False, speak=True)),
    (18.0, dict(speak=False, emo="happy")),
    (20.0, dict(emo="thinking")),
    (23.0, dict(emo="excited")),
    (25.5, dict(emo="love")),
    (28.5, dict(emo="neutral", seen=False)),
    (31.0, dict(seen=True)),
    (33.0, dict(emo="sleeping")),
    (37.0, dict(emo="neutral")),
    (40.0, None),
]


def flat(u):
    out = {}
    for k, v in u.items():
        if k.startswith("_") or k in ("uTime",):
            continue
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif isinstance(v, (tuple, list)) and all(isinstance(x, (int, float)) for x in v):
            for i, x in enumerate(v):
                out[f"{k}.{i}"] = float(x)
    return out


def jumps(rows, times):
    """(score, frame, key, step, typical step) — steps far past their neighbours'."""
    found = []
    keys = rows[0].keys()
    for k in keys:
        xs = [r.get(k, 0.0) for r in rows]
        span = (max(xs) - min(xs)) or 1.0
        for i in range(2, len(xs) - 2):
            d = xs[i] - xs[i - 1]
            dt = max(1e-3, times[i] - times[i - 1])
            near = max(abs(xs[i - 1] - xs[i - 2]), abs(xs[i + 1] - xs[i]),
                       abs(xs[i + 2] - xs[i + 1]))
            if abs(d) > 0.12 * span and abs(d) > 3.0 * near + 0.02 * span:
                found.append((abs(d) / span, i, k, round(d, 3), round(near, 3), round(dt * 1000)))
    found.sort(reverse=True)
    return found


def main():
    out = next((a for a in sys.argv[1:] if not a.startswith("--") and a.endswith(".json")),
               "/tmp/face_trace.json")
    P.egl_context()
    fbo = P.framebuffer()
    import robot_face as rf
    import gl_face
    from shared_state import state
    rf.FACE_GL = False
    face = rf.RobotFace()
    rf.apply_style(3)
    face.gl = gl_face.GLFace(P.W, P.H)
    face.gl.target_fbo = fbo
    face.screen = gl_face.layer_surface(P.W, P.H)
    face.base = gl_face.layer_surface(P.W, P.H)
    face.back = gl_face.layer_surface(P.W, P.H)
    face.clock = type("NoWait", (), {"tick": lambda self, fps: 0})()
    rows, times, emos = [], [], []
    orig = face.gl.face_uniforms

    def rec(*a, **k):
        u = orig(*a, **k)
        rows.append(flat(u))
        times.append(time.monotonic())
        return u
    face.gl.face_uniforms = rec
    t0 = time.monotonic()
    cur = dict(emo="neutral", speak=False, listen=False, seen=True)
    si = 0
    frame_ms = []
    while True:
        t = time.monotonic() - t0
        while si < len(SCRIPT) and SCRIPT[si][0] <= t:
            if SCRIPT[si][1] is None:
                break
            cur.update(SCRIPT[si][1])
            si += 1
        if si < len(SCRIPT) and SCRIPT[si][1] is None and SCRIPT[si][0] <= t:
            break
        with state.lock:
            state.face_detected = cur["seen"]
            state.speaking = cur["speak"]
            state.listening = cur["listen"]
            state.audio_energy = (0.5 + 0.45 * math.sin(t * 17.0) * math.sin(t * 5.3)
                                  if cur["speak"] else 0.0)
        face.set_state(cur["emo"])
        f0 = time.perf_counter()
        face.draw()
        GL.glFinish()
        frame_ms.append((time.perf_counter() - f0) * 1000)
        emos.append(f"{t:5.2f} {cur['emo']}{' talk' if cur['speak'] else ''}"
                    f"{' listen' if cur['listen'] else ''}{'' if cur['seen'] else ' alone'}")
    found = jumps(rows, times)
    frame_ms.sort()
    print(f"[trace] {len(rows)} frames in {times[-1] - times[0]:.1f} s; frame median "
          f"{frame_ms[len(frame_ms) // 2]:.1f} ms, 90% {frame_ms[int(len(frame_ms) * 0.9)]:.1f} ms")
    seen_keys = set()
    for score, i, k, d, near, dt in found[:60]:
        if (i, k.split(".")[0]) in seen_keys:
            continue
        seen_keys.add((i, k.split(".")[0]))
        print(f"  {emos[i]:28s} #{i:4d} {k:14s} step {d:9.3f}  (round it {near:7.3f}, dt {dt} ms)")
    with open(out, "w") as f:
        json.dump({"rows": rows, "times": times, "emos": emos}, f)
    print(f"[trace] wrote {out}")


if __name__ == "__main__":
    main()
