"""
The weather on her (onface.py, gl_onface.py) offscreen on the Pi, no screen
taken: a sheet of moments (snow piled up, a blink shaking it off, a turn of
the head; rain's beads, a blink wiping them) and what it costs.

    ssh raspberry@raspberrypi.local 'cd ~/luna && ./venv/bin/python tools/onface_preview.py [out_dir]'

Writes onface_sheet.png (and each frame, onface_NN.png) into out_dir
(/tmp/onface).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gl_face_preview as P                                  # noqa: E402  (sets up EGL, the path)

GL, W, H = P.GL, P.W, P.H
FPS = 30.0


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/onface"
    P.egl_context()
    fbo = P.framebuffer()
    from PIL import Image, ImageDraw
    import robot_face as rf
    import gl_face
    import environment
    import onface
    import themes
    themes.current = lambda now=None: "luna"
    rf.apply_style(3)
    g = gl_face.GLFace(W, H)
    g.target_fbo = fbo
    face = P.FakeFace(rf)
    fcx, fcy = W // 2, H // 2 + rf.FACE_Y_OFFSET
    fake = [1000.0]
    gl_face._clock = lambda: fake[0]
    env = environment.get()
    os.makedirs(out, exist_ok=True)
    tiles, cost = [], []

    def run(secs, **pose):
        """`secs` of her life in a pose; a pair (from, to) eases across it."""
        n = max(1, int(round(secs * FPS)))
        u = None
        for k in range(n):
            fake[0] += 1.0 / FPS
            f = (k + 1) / n
            face.pose(**{a: v[0] + (v[1] - v[0]) * f if isinstance(v, tuple) else v
                         for a, v in pose.items()})
            t0 = time.perf_counter()
            u = g.face_uniforms(face, rf, fcx, fcy)
            cost.append(time.perf_counter() - t0)
        return u

    def shot(u, label):
        g.render(u)
        px = GL.glReadPixels(0, 0, W, H, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        img = Image.frombytes("RGBA", (W, H), px).transpose(Image.FLIP_TOP_BOTTOM).convert("RGB")
        img.save(os.path.join(out, "onface_%02d.png" % len(tiles)))
        d = g.onface
        note = "%s  snow %.0f/%.0f  n=%d" % (label, d.eyes[0].snow, d.eyes[1].snow,
                                              (u.get("_onface") or {}).get("n", 0))
        ImageDraw.Draw(img).text((10, 8), note, fill=(255, 255, 255))
        tiles.append(img)
        print(note, flush=True)

    def gpu(u, n=40):
        GL.glFinish()
        t0 = time.perf_counter()
        for _ in range(n):
            g.render(u)
        GL.glFinish()
        return (time.perf_counter() - t0) / n * 1000

    def start(words):
        env.simulate(words)
        env.cur = env.glass = None
        g.onface = None
        del cost[:]

    start("night heavy-snow temp=-5")
    u = run(8)
    shot(u, "snow 8 s")
    u = run(50)
    shot(u, "snow 60 s")
    with_, d = gpu(u), u["_onface"]
    u["_onface"] = None
    print("snow: physics %.2f ms a frame (all of face_uniforms), GPU %.2f ms with, %.2f without"
          % (sum(cost) / len(cost) * 1000, with_, gpu(u)), flush=True)
    u["_onface"] = d
    u = run(0.1, blink=(1.0, 0.0))
    shot(u, "blink: shut")
    u = run(0.1, blink=(0.0, 1.0))
    shot(u, "blink: open again")
    u = run(0.4)
    shot(u, "0.4 s later")
    run(20)
    u = run(0.12, tilt=(0.0, 0.22))
    shot(u, "a quick tilt")
    u = run(0.3, tilt=0.22)
    shot(u, "0.3 s later")
    u = run(15, emotion="happy")
    shot(u, "happy, 15 s")

    start("day heavy-rain")
    u = run(4)
    shot(u, "rain 4 s")
    u = run(16)
    shot(u, "rain 20 s")
    with_, d = gpu(u), u["_onface"]
    u["_onface"] = None
    print("rain: physics %.2f ms a frame (all of face_uniforms), GPU %.2f ms with, %.2f without"
          % (sum(cost) / len(cost) * 1000, with_, gpu(u)), flush=True)
    u["_onface"] = d
    run(0.1, blink=(1.0, 0.0))
    u = run(0.1, blink=(0.0, 1.0))
    shot(u, "after a blink")
    u = run(0.12, tilt=(0.0, -0.22))
    shot(u, "a quick tilt")
    start("day")
    onface.TUNE["on"] = 0.0
    u = run(2)
    print("dry: all of face_uniforms %.2f ms with it off" % (sum(cost) / len(cost) * 1000))
    onface.TUNE["on"] = 1.0
    del cost[:]
    u = run(2)
    print("dry: %.2f ms with it on (nothing to do)" % (sum(cost) / len(cost) * 1000))

    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * W, rows * H))
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * W, (i // cols) * H))
    sheet.save(os.path.join(out, "onface_sheet.png"))
    print(os.path.join(out, "onface_sheet.png"))


if __name__ == "__main__":
    main()
