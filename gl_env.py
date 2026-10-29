"""
gl_env.py — the fine part of Luna's world outside (environment.py): the arc's
line, rain, snow, stars and the moon, as small meshes moved in the vertex shader. The
sky itself (gradient, sun, clouds, fog, the arc's glow) is the soft pass's,
in gl_face.py.

Per pixel over the whole screen the same drops cost the Pi's GPU 9 ms a frame
(28 Oct); as a few hundred thin quads, next to nothing. Every particle's place
is its seed and the clocks (environment.Env.clk): stable, no resets.
"""
import ctypes
import random

RAIN_N, SNOW_N, STAR_N, ARC_N = 520, 360, 60, 120

# the clouds' shapes: gl_face's sky draws them (and their billows), the stars
# and the moon here hide behind them. Eight formations, back to front
# (environment.Env.frame): F = x, its underside's y, width, seed; G = opacity,
# near (0 far..1), kind * 2 + height, the shape's slow change. Kinds: 0 a heap
# (cumulus), 1 a band of rolls (stratocumulus), 2 a veil of streaks (cirrus)
CLOUD_GLSL = """
uniform vec4  uEnvF[8], uEnvG[8];

float envcH(float n) {
    n = fract(n * 0.1031 + 0.137);
    n *= n + 33.33;
    return fract((n + n) * n);
}
// a cheap smooth wave, -0.5..0.5, period 1
float envcW(float x) { float f = fract(x); return 4.0 * f * (1.0 - f) - 0.5; }
float envcMin(float a, float b, float k) {
    float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
    return mix(b, a, h) - k * h * (1.0 - h);
}

float envcK(vec4 g) { return floor(g.z * 0.5); }          // the kind
float envcT(vec4 g) { return g.z - 2.0 * envcK(g); }      // the height

// a formation's distance (px, < 0 inside), before its billows. A heap: five
// puffs, the highest off centre, a tower on some, a soft flat underside; a
// band or a veil: a long low lens
float envCloudD(vec2 q, vec4 f, vec4 g) {
    vec2 p = q - f.xy;
    float w = f.z;
    float kind = envcK(g), ht = envcT(g);
    if (kind > 0.5) {
        float hh = w * (kind > 1.5 ? 0.10 : 0.11) * ht;
        vec2 e = vec2(max(abs(p.x) - 0.5 * w + hh, 0.0), p.y + hh);
        return length(e) - hh;
    }
    p.y /= ht;
    float peak = (envcH(f.w * 3.1) - 0.5) * 0.9;
    float d = 1e4;
    for (int i = 0; i < 5; i++) {
        float fi = float(i);
        float h = envcH(f.w * 13.7 + fi * 7.31);
        float t = fi * 0.5 - 1.0;
        float k = 1.0 - 0.42 * (t - peak) * (t - peak);
        float r = w * (0.13 + 0.12 * h) * max(k, 0.25)
                  * (1.0 + 0.09 * envcW(g.w * (1.0 + floor(h * 4.0) * 0.25) + h));
        vec2 c = vec2(t * w * 0.31 + (h - 0.5) * w * 0.07, -r * (0.35 + 0.40 * envcH(h * 91.7)));
        d = envcMin(d, length(p - c) - r, w * 0.06);
    }
    float tw = envcH(f.w * 5.3);                       // 0 a low heap .. 1 towering
    vec2 c = vec2(peak * w * 0.31 + (tw - 0.5) * w * 0.06, -w * (0.28 + 0.10 * tw));
    d = envcMin(d, length(p - c) - w * (0.03 + 0.11 * tw), w * 0.06);
    return -envcMin(-d, w * 0.025 - p.y, w * 0.05);
}

// the edge's softness (px): a few px, far ones a little softer (the sky's
// quarter-size pass, stretched, still keeps them crisp)
float envcS(vec4 f, vec4 g) { return 3.5 + f.z * (0.010 - 0.005 * g.y); }

// how much the clouds cover this point (0..1)
float envcOne(vec2 q, vec4 f, vec4 g) {
    if (g.x < 0.004) return 0.0;
    vec2 p = q - f.xy;
    if (abs(p.x) > 0.62 * f.z || p.y > 0.12 * f.z || p.y < -0.62 * f.z * envcT(g)) return 0.0;
    float s = envcS(f, g);
    float a = g.x * (1.0 - smoothstep(-s, s, envCloudD(q, f, g)));
    return envcK(g) > 1.5 ? 0.4 * a : a;                  // a veil: thin
}
float envCover(vec2 q) {
    float a = 0.0;
    for (int i = 0; i < 8; i++) a = max(a, envcOne(q, uEnvF[i], uEnvG[i]));
    return a;
}
"""

_VERT = """
attribute vec2 aPos;          // the corner: across -1..1, along 0..1
attribute vec4 aSeed;         // the particle's: x, y, size/near (0..1), phase
uniform vec2  uRes;
uniform float uKind;          // 0 the arc, 1 rain, 2 snow, 3 stars, 4 the moon
uniform vec4  uK;             // (count), alpha, length / size / half width, speed
uniform vec4  uEnvArcG, uEnvArcA, uEnvClk, uEnvX, uEnvMask, uEnvMoon, uEnvL;
varying vec2  vUV;
varying float vA;
""" + CLOUD_GLSL + """

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
        } else if (uKind < 3.5) {               // a star, behind the clouds
            c = vec2(aSeed.x * W, aSeed.y * uEnvX.w * 0.55);
            r = 0.7 + 0.6 * aSeed.z;
            vA = uK.y * (0.35 + 0.65 * aSeed.z) * mask(c) * (1.0 - envCover(c))
                 * (0.65 + 0.35 * sin(6.28318 * uEnvClk.z * per(0.04 + 0.08 * aSeed.w)
                                      + aSeed.w * 60.0));
        } else {                                // the moon, a quad 5 r wide
            c = uEnvMoon.xy;
            r = uEnvMoon.z * 1.25;
            vA = uEnvMoon.w * (1.0 - envCover(c));
        }
        vUV = vec2(aPos.x, aPos.y * 2.0 - 1.0) * 2.0;
        pos = c + vUV * r;
        if (uKind > 3.5) vUV *= 1.25;           // (the moon's: in its radii)
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
    } else if (uKind < 3.5) {
        a = vA * exp(-dot(vUV, vUV));
    } else {                                    // a crescent, a faint rest, a faint halo
        float e = uK.z;
        float disk = 1.0 - smoothstep(1.0 - e, 1.0 + e, length(vUV));
        float cut = 1.0 - smoothstep(1.0 - e, 1.0 + e, length(vUV - vec2(-0.42, -0.30)) * 1.04);
        a = vA * (disk * (1.0 - cut) + 0.07 * disk * cut
                  + 0.14 * exp(-max(0.0, length(vUV) - 1.0) * 2.2) * (1.0 - disk));
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
        for k in ("uEnvArcG", "uEnvArcA", "uEnvClk", "uEnvX", "uEnvMask", "uEnvMoon", "uEnvL") \
                + tuple(f"uEnv{a}[{i}]" for a in "FG" for i in range(8)):
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
        moon = u["uEnvMoon"]
        if moon[3] > 0.003:
            self._set("uKind", 4.0)
            self._set("uCol", u["uEnvMoonC"])
            self._set("uK", (0.0, 1.0, 1.2 / max(1.0, moon[2]), 0.0))
            mesh("stars", GL.GL_TRIANGLES, 6)
        GL.glDisableVertexAttribArray(1)
