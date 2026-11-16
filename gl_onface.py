"""
gl_onface.py — draws what onface.py simulates: the snow lying on Luna's
eyes, flakes and clumps in the air round her, rain that hits her, beads of
water on her eyes with their wet tracks, drips and splashes.

A particle is a quad whose place comes from two vec4 in a uniform array
(CH at a time: GLES 2 promises room for no more), a snow cap a strip along
the eye's top edge. Drawn by gl_face after her eyes, before the glass.
"""
import ctypes

import onface

CH = 48            # particles a draw call
NC = onface.NC

_VERT = """
attribute vec2 aPos;          // the corner: across -1..1, along 0..1 (a cap: the column, 0 foot / 1 top)
attribute vec4 aSeed;         // x: which of the CH
uniform vec2  uRes;
uniform float uKind;          // 0 a snow cap, 1 a wet track, 2 water, 3 rain, 4 a ring, 5 snow
uniform vec4  uA[CH], uB[CH];
uniform vec2  uCap[NC];       // a cap's columns: the eye's top edge, the snow's depth
uniform vec4  uEyeT[2];       // an eye: its middle on the screen, cos / sin of its turn
uniform vec4  uEyeK[2];       // …half its width, a column's width
uniform float uEyeI;
varying vec2  vUV, vQ;
varying vec4  vP;

vec2 outOf(vec4 T, vec2 q) { return T.xy + vec2(T.z * q.x - T.w * q.y, T.w * q.x + T.z * q.y); }

void main() {
    vec2 pos;
    vQ = vec2(0.0);
    if (uKind < 0.5) {
        int e = int(uEyeI + 0.5);
        vec2 c = uCap[int(aPos.x + 0.5)];
        float x = -uEyeK[e].x + (aPos.x + 0.5) * uEyeK[e].y;
        vUV = vec2(x, aPos.y);
        vP = vec4(c.y + 4.0, c.y, uEyeI, 0.0);
        pos = outOf(uEyeT[e], vec2(x, mix(c.x + 2.0, c.x - c.y - 2.0, aPos.y)));
    } else {
        int i = int(aSeed.x + 0.5);
        vec4 A = uA[i], B = uB[i];
        vec2 q = vec2(aPos.x, aPos.y * 2.0 - 1.0);
        if (uKind < 1.5) {                      // a track, in its eye's frame: x0, y from, to
            float half_w = B.x + B.z + 1.5;
            float y = mix(A.y, A.z, aPos.y);
            vUV = vec2(aPos.x * half_w, y);
            vP = B;
            vQ = vec2((1.0 - aPos.y) * (A.z - A.y), A.z - A.y);     // px behind its head, its length
            pos = outOf(uEyeT[int(A.w + 0.5)], vec2(A.x + vUV.x, y));
        } else if (uKind < 2.5) {               // water: x, y, r, alpha; stretch, the way it goes
            float r = max(A.z, 0.8);
            vec2 d = vec2(q.x * (1.35 * r + 1.5), q.y * (1.35 * r * B.x + 1.5));    // (room for its shadow)
            vUV = vec2(d.x / r, d.y / (r * B.x));
            vP = vec4(r, A.w, B.w, B.x);
            pos = A.xy + vec2(B.z, -B.y) * d.x + B.yz * d.y;
        } else if (uKind < 3.5) {               // rain: its head, length, alpha; the way, half width
            vUV = aPos;
            vP = vec4(0.0, A.w, 0.0, 0.0);
            pos = A.xy - B.xy * A.z * (1.0 - aPos.y) + vec2(B.y, -B.x) * aPos.x * (B.z + 0.5);
        } else if (uKind < 4.5) {               // a ring: x, y, r, alpha
            vUV = q * (A.z + 2.0);
            vP = vec4(A.z, A.w, 0.0, 0.0);
            pos = A.xy + vUV;
        } else {                                // snow: x, y, r, alpha; seed, a clump
            vUV = q * (A.z + 1.0) / A.z;
            vP = vec4(A.z, A.w, B.x, B.y);
            pos = A.xy + q * (A.z + 1.0);
        }
    }
    gl_Position = vec4(pos.x / uRes.x * 2.0 - 1.0, 1.0 - pos.y / uRes.y * 2.0, 0.0, 1.0);
}
"""

_FRAG = """
uniform float uKind;
uniform vec3  uSnowC, uWaterC;
varying vec2  vUV, vQ;
varying vec4  vP;

// a drop's outline: q in its radii (y the way it goes); sagging, out of round
float blob(vec2 q, float w, float fat) {
    q.x *= 1.0 - 0.15 * fat * clamp(q.y, -1.3, 1.3);
    float l = length(q);
    vec2 n = q / max(l, 0.01);                  // (by its direction: the same far outside it)
    return l * (1.0 + (0.6 + fat) * (0.09 * sin(w) * (n.x * n.x - n.y * n.y) + 0.11 * cos(1.7 * w) * n.x * n.y)
                + 0.07 * fat * sin(2.3 * w) * (n.x * n.x * n.x - 3.0 * n.x * n.y * n.y));
}

void main() {
    vec4 o;
    if (uKind < 0.5) {                          // the cap: lumpy on top, lit there, blue below
        float h = vP.y;
        float d = (1.0 - vUV.y) * vP.x - 2.0;   // px under its top
        d -= (0.8 + 0.8 * sin(vUV.x * 0.63 + vP.z * 2.1) + 0.5 * sin(vUV.x * 1.71 + 1.3))
             * clamp(h * 0.25, 0.0, 1.0);
        float a = clamp(d, 0.0, 1.0) * clamp(h * 0.8, 0.0, 1.0);
        float lit = 1.0 - 0.20 * smoothstep(1.0, 9.0, d);
        o = vec4(uSnowC * vec3(lit, 0.4 + 0.6 * lit, 0.7 + 0.3 * lit) * a, a);
    } else if (uKind < 1.5) {
        // a track: a film as wide as the bead behind it, uneven, that thins,
        // breaks into stretches and leaves beads as it dries
        float y = vUV.y, back = vQ.x, w = vP.y;
        float hw = vP.z * (0.42 + 0.58 * exp(-back / 26.0)) * (0.82 + 0.22 * sin(y * 0.27 + 3.0 * w));
        float x = (vUV.x - vP.x * sin(%(K).4f * y + w)) / max(hw, 0.7);
        float dry = 1.0 - vP.w;
        float gaps = smoothstep(-0.2, 0.2, sin(y * 0.52 + 5.0 * w) + 0.6 * sin(y * 1.31 + w) - 1.3 * dry + 0.25);
        float film = (1.0 - smoothstep(0.55, 1.0, abs(x))) * smoothstep(0.0, 5.0, vQ.y - back)
                     * mix(1.0, gaps, max(dry, smoothstep(12.0, 50.0, back))) * smoothstep(0.0, 0.25, vP.w);
        float edge = film * smoothstep(0.35, 0.95, abs(x));
        float hl = film * exp(-(x + 0.5) * (x + 0.5) * 12.0);
        float cell = floor(y / 7.0);                // the beads left on it, each where it was left
        float hb = fract(sin(cell * 12.989 + w) * 4375.85);
        vec2 bp = vec2(vUV.x - vP.x * sin(%(K).4f * y + w) - (fract(hb * 3.1) - 0.5) * 1.6 * vP.z,
                       y - (cell + 0.3 + 0.4 * fract(hb * 7.3)) * 7.0) / (0.7 + 1.3 * hb * hb);
        float bd = length(bp);
        float bead = step(0.45, hb) * (1.0 - smoothstep(0.6, 1.0, bd)) * step(5.0, back)
                     * smoothstep(0.0, 4.0, vQ.y - back) * smoothstep(0.0, 0.15, vP.w);
        vec2 bg = bp + vec2(0.35, 0.40);
        o = vec4(uWaterC * (0.42 * hl + 0.9 * bead * exp(-dot(bg, bg) * 9.0)),
                 0.05 * film + 0.30 * edge + bead * (0.18 + 0.40 * smoothstep(0.4, 1.0, bd)));
    } else if (uKind < 2.5) {
        // water on her: it bends her own light, so dark toward the light and
        // round its edge, bright in a crescent on the far side; a hard small
        // glint; a shadow on the eye under it
        vec2 q = vUV, L = vec2(-0.50, -0.866);
        float r = vP.x, fat = smoothstep(2.5, 6.0, r);
        float d = blob(q, vP.z, fat);
        float cov = (1.0 - smoothstep(1.0 - 1.5 / r, 1.0, d)) * vP.y;
        vec2 n = q / max(length(q), 0.001);
        float toL = dot(n, L), s = dot(q, L);
        float dark = 0.30 * smoothstep(-0.25, 0.75, s) + smoothstep(0.66, 1.0, d) * (0.30 + 0.34 * max(0.0, toL));
        float bright = 0.62 * smoothstep(0.45, 0.86, d) * (1.0 - smoothstep(0.90, 1.0, d)) * pow(max(0.0, -toL), 2.2)
                       + 0.20 * smoothstep(-0.2, 0.9, -s) * (1.0 - d);
        vec2 g = q - L * 0.50;
        float glint = exp(-dot(g, g) * mix(14.0, 70.0, fat));
        float sh = (1.0 - smoothstep(0.80, 1.30, blob(q + L * 0.26, vP.z, fat))) * (1.0 - cov) * vP.y * fat;
        o = vec4(uWaterC * (bright + 1.1 * glint) * cov, cov * (0.05 + min(0.75, dark) + 0.5 * glint) + 0.26 * sh);
    } else if (uKind < 3.5) {
        float a = vP.y * (1.0 - abs(vUV.x)) * vUV.y * vUV.y;
        o = vec4(uWaterC * a, a * 0.4);
    } else if (uKind < 4.5) {
        // a splash's ripple: soft, lit on one side and dark on the other
        float l = length(vUV);
        float a = vP.y * (1.0 - smoothstep(0.3, 2.2, abs(l - vP.x)));
        float side = dot(vUV / max(l, 0.01), vec2(-0.50, -0.866));
        o = vec4(uWaterC * a * 0.38 * (0.35 + 0.65 * max(0.0, -side)), a * (0.06 + 0.26 * max(0.0, side)));
    } else {
        float d = length(vUV);
        float a = vP.y * (1.0 - smoothstep(mix(0.30, 0.62, vP.w), 1.0, d));
        o = vec4(uSnowC * a, a);
    }
    gl_FragColor = o;
}
""" % {"K": onface.K_WAVE}


class OnFacePass:
    """Made by gl_face.GLFace the first time something is on her."""

    def __init__(self, face):
        GL = self.GL = face.GL
        self.face = face
        hv = "#version 120\n" if face.glsl == "120" else "#version 100\nprecision highp float;\n"
        hf = "#version 120\n" if face.glsl == "120" else "#version 100\nprecision mediump float;\n"
        hv += "#define CH %d\n#define NC %d\n" % (CH, NC)
        self.prog = face._program(hv + _VERT, hf + _FRAG)
        self._loc = {n: GL.glGetUniformLocation(self.prog, n)
                     for n in ("uRes", "uKind", "uA", "uB", "uCap", "uEyeT", "uEyeK", "uEyeI",
                               "uSnowC", "uWaterC")}
        quads = []
        for i in range(CH):
            for cx, cy in ((-1, 0), (1, 0), (1, 1), (-1, 0), (1, 1), (-1, 1)):
                quads += (cx, cy, i, 0.0, 0.0, 0.0)
        strip = []
        for j in range(NC):
            strip += (j, 0.0, 0.0, 0.0, 0.0, 0.0, j, 1.0, 0.0, 0.0, 0.0, 0.0)
        self.quads, self.strip = self._vbo(quads), self._vbo(strip)
        print("[gl] weather on her ready", flush=True)

    def _vbo(self, data):
        GL = self.GL
        buf = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buf)
        arr = (ctypes.c_float * len(data))(*data)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(arr), arr, GL.GL_STATIC_DRAW)
        return buf

    def _bind(self, buf):
        GL = self.GL
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buf)
        attrib = getattr(self.face, "attrib", GL.glVertexAttribPointer)
        attrib(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 24, None)
        attrib(1, 4, GL.GL_FLOAT, GL.GL_FALSE, 24, ctypes.c_void_p(8))

    def draw(self, d, u):
        """d: onface.OnFace.frame's; u: the face's uniforms (the colours).
        Blending premultiplied is on; leaves another program's quad to be
        bound again."""
        GL, L = self.GL, self._loc
        GL.glUseProgram(self.prog)
        GL.glUniform2f(L["uRes"], float(self.face.w), float(self.face.h))
        sc = u.get("uEnvGlassC") or u.get("uEnvSnowC") or (0.86, 0.90, 1.0)
        GL.glUniform3f(L["uSnowC"], *(0.80 + 0.20 * min(1.0, float(c)) for c in sc[:3]))   # (her own glow lights it)
        wc = u.get("uEnvRainC") or (0.7, 0.8, 0.95)
        GL.glUniform3f(L["uWaterC"], *(max(0.55, min(1.0, float(c) * 1.3)) for c in wc[:3]))
        GL.glUniform4fv(L["uEyeT"], 2, (ctypes.c_float * 8)(*d["eyeT"]))
        GL.glUniform4fv(L["uEyeK"], 2, (ctypes.c_float * 8)(*d["eyeK"]))
        GL.glEnableVertexAttribArray(1)
        A, B = d["A"], d["B"]
        bound = None
        for kind, first, count in d["runs"]:
            if kind == 0:                        # the caps (between the water and the flakes)
                for i, on in enumerate(d["snow"]):
                    if not on:
                        continue
                    if bound != 0:
                        self._bind(self.strip)
                        bound = 0
                        GL.glUniform1f(L["uKind"], 0.0)
                    GL.glUniform1f(L["uEyeI"], float(i))
                    GL.glUniform2fv(L["uCap"], NC, (ctypes.c_float * (2 * NC))(
                        *d["cap"][2 * NC * i:2 * NC * (i + 1)]))
                    GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 2 * NC)
                continue
            if count <= 0:
                continue
            if bound != 1:
                self._bind(self.quads)
                bound = 1
            GL.glUniform1f(L["uKind"], float(kind))
            while count > 0:
                n = min(CH, count)
                GL.glUniform4fv(L["uA"], n, (ctypes.c_float * (4 * n))(*A[4 * first:4 * (first + n)]))
                GL.glUniform4fv(L["uB"], n, (ctypes.c_float * (4 * n))(*B[4 * first:4 * (first + n)]))
                GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6 * n)
                first += n
                count -= n
        GL.glDisableVertexAttribArray(1)
