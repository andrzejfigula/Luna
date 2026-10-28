"""
gl_env.py — the fine part of Luna's world outside (environment.py): the arc's
line, rain, snow and stars, as small meshes moved in the vertex shader. The
sky itself (gradient, sun, clouds, fog, the arc's glow) is the soft pass's,
in gl_face.py.

Per pixel over the whole screen the same drops cost the Pi's GPU 9 ms a frame
(28 Oct); as a few hundred thin quads, next to nothing. Every particle's place
is its seed and the clocks (environment.Env.clk): stable, no resets.
"""
import ctypes
import random

RAIN_N, SNOW_N, STAR_N, ARC_N = 520, 360, 60, 120

_VERT = """
attribute vec2 aPos;          // the corner: across -1..1, along 0..1
attribute vec4 aSeed;         // the particle's: x, y, size/near (0..1), phase
uniform vec2  uRes;
uniform float uKind;          // 0 the arc, 1 rain, 2 snow, 3 stars
uniform vec4  uK;             // (count), alpha, length / size / half width, speed
uniform vec4  uEnvArcG, uEnvArcA, uEnvClk, uEnvX, uEnvMask;
varying vec2  vUV;
varying float vA;

// a rate that repeats whole in the clocks' 600 s (no jump when they wrap)
float per(float f) { return floor(f * 600.0 + 0.5) / 600.0; }

// her face: the weather thinner over it
float mask(vec2 p) {
    vec2 m = (p - uEnvMask.xy) / uEnvMask.zw;
    return mix(0.35, 1.0, smoothstep(0.6, 1.15, length(m)));
}

void main() {
    float W = uRes.x, H = uRes.y, s = uEnvX.y;
    vec2 pos;
    vUV = aPos;
    if (uKind < 0.5) {                          // the arc: in from the edge, gone before her brow
        float t = aPos.y;
        float a = mix(uEnvArcA.x, uEnvArcA.y, t);
        pos = uEnvArcG.xy + (uEnvArcG.z + aPos.x * uK.z) * vec2(cos(a), sin(a));
        vA = uK.y * smoothstep(-0.02, 0.30, t) * (1.0 - smoothstep(0.62, 1.0, t))
             * (0.78 + 0.22 * sin(t * 7.0 + uEnvArcG.w));
    } else if (uKind < 1.5) {                   // a drop: falls, leans with the wind
        float z = aSeed.z;
        float len = uK.z * (0.6 + 0.8 * z);
        float span = H + len + 40.0;
        float y = fract(aSeed.y + uEnvClk.x * per(uK.w * (0.7 + 0.6 * z) / span)) * span - 20.0;
        vec2 head = vec2(aSeed.x * (W + abs(s) * H) - max(s, 0.0) * H + s * y, y);
        vec2 d = normalize(vec2(s, 1.0));
        float hw = 1.1 + 0.6 * z;
        pos = head - d * len * aPos.y + vec2(d.y, -d.x) * aPos.x * hw;
        vA = uK.y * (0.45 + 0.55 * z) * (0.6 + 0.4 * aSeed.w) * mask(head);
    } else {                                    // a flake or a star: a soft dot
        vec2 c;
        float r;
        if (uKind < 2.5) {
            float z = aSeed.z;
            r = uK.z * (0.6 + 1.0 * z);
            float span = H + 4.0 * r + 20.0;
            float y = fract(aSeed.y + uEnvClk.y * per(uK.w * (0.6 + 0.8 * z) / span)) * span
                      - 2.0 * r - 10.0;
            float sw = 0.6 * s;
            c = vec2(aSeed.x * (W + abs(sw) * H + 40.0) - max(sw, 0.0) * H - 20.0 + sw * y
                     + (6.0 + 10.0 * z) * sin(6.28318 * uEnvClk.y * per(0.05 + 0.06 * aSeed.w)
                                              + aSeed.w * 40.0), y);
            vA = uK.y * (0.45 + 0.55 * z) * mask(c);
        } else {
            c = vec2(aSeed.x * W, aSeed.y * uEnvX.w * 0.55);
            r = 0.7 + 0.6 * aSeed.z;
            vA = uK.y * (0.35 + 0.65 * aSeed.z) * mask(c)
                 * (0.65 + 0.35 * sin(6.28318 * uEnvClk.z * per(0.04 + 0.08 * aSeed.w)
                                      + aSeed.w * 60.0));
        }
        vUV = vec2(aPos.x, aPos.y * 2.0 - 1.0) * 2.0;
        pos = c + vUV * r;
    }
    gl_Position = vec4(pos.x / W * 2.0 - 1.0, 1.0 - pos.y / H * 2.0, 0.0, 1.0);
}
"""

_FRAG = """
uniform float uKind;
uniform vec3  uCol;
uniform vec4  uK;
varying vec2  vUV;
varying float vA;
void main() {
    float a;
    if (uKind < 0.5) {                          // the line, then a little glow
        float d = abs(vUV.x) * uK.z;
        a = vA * (0.8 * clamp(uK.w - d + 0.5, 0.0, 1.0) + 0.3 * exp(-d / 2.5));
    } else if (uKind < 1.5) {
        a = vA * max(0.0, 1.0 - abs(vUV.x)) * (1.0 - vUV.y);   // its tail fades
    } else {
        a = vA * exp(-dot(vUV, vUV));
    }
    gl_FragColor = vec4(uCol * a, 0.0);         // (light added: premultiplied, no cover)
}
"""


def _quads(seeds):
    """Two triangles a particle: (corner x, y, seed×4) per vertex."""
    out = []
    for sd in seeds:
        for cx, cy in ((-1, 0), (1, 0), (1, 1), (-1, 0), (1, 1), (-1, 1)):
            out += (cx, cy, *sd)
    return out


class EnvPass:
    """Made by gl_face.GLFace on the first frame with the world outside on."""

    def __init__(self, face):
        GL = self.GL = face.GL
        self.face = face
        hv = "#version 120\n" if face.glsl == "120" else "#version 100\nprecision highp float;\n"
        hf = "#version 120\n" if face.glsl == "120" else "#version 100\nprecision mediump float;\n"
        self.prog = face._program(hv + _VERT, hf + _FRAG)
        self._loc = {}
        rnd = random.Random(1028)             # the same sky every time
        seeds = lambda n: [(rnd.random(), rnd.random(), rnd.random(), rnd.random())  # noqa: E731
                           for _ in range(n)]
        self.bufs = {}
        for kind, data in (("rain", _quads(seeds(RAIN_N))), ("snow", _quads(seeds(SNOW_N))),
                           ("stars", _quads(seeds(STAR_N)))):
            self.bufs[kind] = self._vbo(data)
        arc = []
        for i in range(ARC_N + 1):
            t = i / ARC_N
            arc += (-1.0, t, 0.0, 0.0, 0.0, 0.0, 1.0, t, 0.0, 0.0, 0.0, 0.0)
        self.bufs["arc"] = self._vbo(arc)
        print("[gl] world outside ready", flush=True)

    def _vbo(self, data):
        GL = self.GL
        buf = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buf)
        arr = (ctypes.c_float * len(data))(*data)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(arr), arr, GL.GL_STATIC_DRAW)
        return buf

    def _set(self, name, value):
        GL = self.GL
        loc = self._loc.get(name)
        if loc is None:
            loc = self._loc[name] = GL.glGetUniformLocation(self.prog, name)
        if loc < 0:
            return
        if isinstance(value, (int, float)):
            GL.glUniform1f(loc, float(value))
        else:
            {2: GL.glUniform2f, 3: GL.glUniform3f, 4: GL.glUniform4f}[len(value)](
                loc, *map(float, value))

    def draw(self, u):
        """u: the face's uniforms (environment.Env.frame's in them). Blending
        premultiplied is on; leaves another program's quad to be bound again."""
        GL, face = self.GL, self.face
        GL.glUseProgram(self.prog)
        self._set("uRes", (face.w, face.h))
        for k in ("uEnvArcG", "uEnvArcA", "uEnvClk", "uEnvX", "uEnvMask"):
            self._set(k, u[k])
        stride = 6 * 4
        GL.glEnableVertexAttribArray(1)

        def mesh(kind, mode, n):
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.bufs[kind])
            GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, None)
            GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(8))
            GL.glDrawArrays(mode, 0, n)

        arc = u["uEnvArc"]
        if arc[3] > 0.005:
            self._set("uKind", 0.0)
            self._set("uCol", tuple(c * arc[3] for c in arc[:3]))
            self._set("uK", (0.0, 1.0, 8.0, u["uEnvArcA"][2]))
            mesh("arc", GL.GL_TRIANGLE_STRIP, 2 * (ARC_N + 1))
        for kind, key, k, cap in (("stars", "uEnvStars", 3.0, STAR_N), ("rain", "uEnvRain", 1.0, RAIN_N),
                                  ("snow", "uEnvSnow", 2.0, SNOW_N)):
            p = u.get(key)
            n = min(cap, int(p[0])) if p else 0
            if n <= 0 or p[1] <= 0.003:
                continue
            self._set("uKind", k)
            self._set("uCol", u[key + "C"])
            self._set("uK", p)
            mesh(kind, GL.GL_TRIANGLES, 6 * n)
        GL.glDisableVertexAttribArray(1)
