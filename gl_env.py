"""
gl_env.py — the fine part of Luna's world outside (environment.py): the arc's
line, rain, snow, stars and the moon, as small meshes moved in the vertex shader. The
sky itself (gradient, sun, clouds, fog, the arc's glow) is the soft pass's,
in gl_face.py.

Per pixel over the whole screen the same drops cost the Pi's GPU 9 ms a frame
(28 Oct); as a few hundred thin quads, next to nothing. Every particle's place
is its seed and the clocks (environment.Env.clk): stable, no resets. Stars
and the moon hide behind the clouds by the sky's alpha (gl_face._FRAG_SKY).
"""
import ctypes
import random

RAIN_N, SNOW_N, STAR_N, ARC_N = 520, 360, 160, 120

_VERT = """
attribute vec2 aPos;          // the corner: across -1..1, along 0..1
attribute vec4 aSeed;         // the particle's: x, y, size/near (0..1), phase
uniform vec2  uRes;
uniform float uKind;          // 0 the arc, 1 rain, 2 snow, 3 stars, 4 the moon
uniform vec4  uK;             // (count), alpha, length / size / half width, speed
uniform vec4  uEnvArcG, uEnvArcA, uEnvClk, uEnvX, uEnvMask, uEnvMoon;
varying vec2  vUV, vSky;
varying float vA, vS;

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
    vS = 0.0;
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
            c = vec2(aSeed.x * W, aSeed.y * aSeed.y * uEnvX.w * 0.95);
            float z3 = aSeed.z * aSeed.z * aSeed.z;
            r = 0.8 + 2.2 * z3;
            vS = smoothstep(0.35, 0.9, z3);         // the brightest: a sparkle
            vA = uK.y * (0.30 + 0.70 * aSeed.z) * mask(c)
                 * (0.65 + 0.35 * sin(6.28318 * uEnvClk.z * per(0.04 + 0.08 * aSeed.w)
                                      + aSeed.w * 60.0));
        } else {                                // the moon, a quad 5 r wide
            c = uEnvMoon.xy;
            r = uEnvMoon.z * 4.0;                   // (room for its halo)
            vA = uEnvMoon.w;
        }
        vUV = vec2(aPos.x, aPos.y * 2.0 - 1.0) * 2.0;
        if (uKind > 2.5 && uKind < 3.5) vUV *= 3.0;   // (a star's: room for its rays)
        pos = c + vUV * r;
        if (uKind > 3.5) vUV *= 4.0;            // (the moon's: in its radii)
    }
    vSky = vec2(pos.x / W, 1.0 - pos.y / H);
    gl_Position = vec4(pos.x / W * 2.0 - 1.0, 1.0 - pos.y / H * 2.0, 0.0, 1.0);
}
"""

_FRAG = """
uniform float uKind;
uniform vec3  uCol;
uniform vec4  uK;
uniform sampler2D uSky;       // the sky (gl_face): its alpha, the cloud in front
varying vec2  vUV, vSky;
varying float vA, vS;
void main() {
    float a;
    if (uKind < 0.5) {                          // the line, then a little glow
        float d = abs(vUV.x) * uK.z;
        a = vA * (0.8 * clamp(uK.w - d + 0.5, 0.0, 1.0) + 0.3 * exp(-d / 2.5));
    } else if (uKind < 1.5) {
        a = vA * max(0.0, 1.0 - abs(vUV.x)) * (1.0 - vUV.y);   // its tail fades
    } else if (uKind < 2.5) {
        a = vA * exp(-dot(vUV, vUV));
    } else if (uKind < 3.5) {                   // a star: a point, the bright ones four rays
        vec2 v = abs(vUV);
        a = vA * (exp(-dot(vUV, vUV))
                  + 0.8 * vS * (exp(-v.x * 0.8 - v.y * v.y * 5.0) + exp(-v.y * 0.8 - v.x * v.x * 5.0)))
            * (1.0 - texture2D(uSky, vSky).a);
    } else {                                    // the moon: its phase, seas, earthshine, a glow
        float e = uK.z;
        float l = length(vUV);
        float disk = 1.0 - smoothstep(1.0 - e, 1.0 + e, l);
        float sq = sqrt(max(0.0, 1.0 - vUV.y * vUV.y));
        float lit = smoothstep(-0.06, 0.06, uK.w * vUV.x - uK.x * sq);   // (x: cos of its age, w: side)
        vec2 v = vUV;                            // the seas, roughly where they are
        float sea = 1.0 - smoothstep(0.05, 0.42, length((v - vec2(-0.42, 0.02)) * vec2(1.3, 0.8)));
        sea = max(sea, 1.0 - smoothstep(0.05, 0.30, length(v - vec2(-0.12, -0.38))));
        sea = max(sea, 1.0 - smoothstep(0.04, 0.24, length((v - vec2(0.22, -0.22)) * vec2(0.9, 1.2))));
        sea = max(sea, 0.8 - 0.8 * smoothstep(0.03, 0.22, length(v - vec2(0.38, 0.02))));
        sea = max(sea, 0.6 - 0.6 * smoothstep(0.03, 0.20, length(v - vec2(-0.12, 0.40))));
        a = vA * (disk * (lit * (1.0 - 0.16 * sea) + 0.06 * (1.0 - lit))
                  + (0.14 + 0.20 * uK.y) * (exp(-max(0.0, l - 1.0) * 2.0) + 0.55 * exp(-max(0.0, l - 1.0) * 0.6))
                    * (1.0 - smoothstep(2.4, 4.0, l)) * (1.0 - disk))    // a halo, wide
            * (1.0 - 0.85 * texture2D(uSky, vSky).a);            // (a little through thin cloud)
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
        for k in ("uEnvArcG", "uEnvArcA", "uEnvClk", "uEnvX", "uEnvMask", "uEnvMoon"):
            self._set(k, u[k])
        GL.glActiveTexture(GL.GL_TEXTURE0 + 6)
        GL.glBindTexture(GL.GL_TEXTURE_2D, getattr(face, "sky", 0) or 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        if "uSky" not in self._loc:
            self._loc["uSky"] = GL.glGetUniformLocation(self.prog, "uSky")
            if self._loc["uSky"] >= 0:
                GL.glUniform1i(self._loc["uSky"], 6)
        stride = 6 * 4
        attrib = getattr(face, "attrib", GL.glVertexAttribPointer)
        GL.glEnableVertexAttribArray(1)

        def mesh(kind, mode, n):
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.bufs[kind])
            attrib(0, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, None)
            attrib(1, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(8))
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
            ph = u.get("uEnvMoonP", (0.3, 1.0))
            self._set("uK", (ph[0], ph[2] if len(ph) > 2 else 0.6, 1.2 / max(1.0, moon[2]), ph[1]))
            mesh("stars", GL.GL_TRIANGLES, 6)
        GL.glDisableVertexAttribArray(1)
