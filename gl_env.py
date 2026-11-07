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

import environment

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


# ── the glass in front: drops, their wet tracks, flakes, frost ───────────
# A drop lives one cycle of its own (its place new each cycle, from its seed
# and the cycle's number): lands, sits, may run down along a wavy path and
# leave a track, dries. What it shows is the sky texture through a lens:
# the world outside upside down, a dark rim, the light's glint.
GLASS_N = 160

_GVERT = """
attribute vec2 aPos;          // the corner: across -1..1, along 0..1
attribute vec4 aSeed;         // its index / GLASS_N, three randoms
uniform vec2  uRes;
uniform float uKind;          // 1 a drop, 2 a runner's track, 3 a flake, 4 frost (in uRect)
uniform vec4  uK;             // how many, radius px, life s, runners' share
uniform vec4  uRect;
uniform vec4  uEnvGlass, uEnvGlassK, uEnvGlassL, uEnvMask;
varying vec2  vUV, vC, vL;
varying vec4  vP, vE;

float per(float f) { return max(1.0, floor(f * 600.0 + 0.5)) / 600.0; }
float h1(float n) { return fract(sin(n) * 43758.5453); }

void main() {
    float W = uRes.x, H = uRes.y;
    vec2 pos;
    vUV = aPos;
    vC = vec2(0.0);
    vL = vec2(0.0, -1.0);
    vP = vec4(0.0);
    vE = vec4(0.0);
    if (uKind > 3.5) {
        pos = mix(uRect.xy, uRect.zw, vec2(aPos.x * 0.5 + 0.5, aPos.y));
        vUV = pos;
    } else {
        float flake = uKind > 2.5 ? 1.0 : 0.0;
        float on = clamp(uK.x - aSeed.x * GN, 0.0, 1.0);
        float life = uK.z * (0.7 + 0.6 * aSeed.z);
        float cyc = uEnvGlassK.x * per(1.0 / life) + aSeed.w;
        float k = floor(cyc), t = cyc - k;
        float id = aSeed.y * 251.0 + k * 13.17 + flake * 3.7;
        float hs = h1(id + 3.1), hr = h1(id + 5.3), hw = h1(id + 7.9);
        float r = uK.y * (0.35 + 0.65 * hs * hs);
        vec2 c0 = vec2(h1(id) * W, (h1(id + 1.7) * 1.08 - 0.04) * H);
        float born = smoothstep(0.0, 0.025, t), gone = 1.0 - smoothstep(0.8, 1.0, t);
        float a = on * born * gone;
        r *= mix(0.7, 1.0, born) * mix(0.7, 1.0, gone);
        // a runner: still a while, then down in fits and starts (its path a
        // function of y alone, so its track follows it)
        float run = (flake < 0.5 && hr < uK.w && hs > 0.3) ? 1.0 : 0.0;
        float s = run * max(0.0, t - 0.12 - 0.45 * hw) * life;
        float dist = (14.0 + 34.0 * hs) * (s - 0.8 * sin(1.6 * s) / 1.6);
        float A = 2.0 + 4.0 * hw, ph = hw * 40.0, sl = uEnvGlassK.y * 0.5;
        float yh = c0.y + dist;
        float xh = c0.x + A * (sin(yh * 0.021 + ph) - sin(c0.y * 0.021 + ph)) + sl * dist;
        vec2 m = (vec2(xh, yh) - uEnvMask.xy) / uEnvMask.zw;
        a *= mix(0.7, 1.0, smoothstep(0.55, 1.1, length(m)));      // fewer over her face
        if (uKind > 1.5 && uKind < 2.5) {       // the track: from where it sat to where it is
            float y0 = c0.y - 0.4 * r, y1 = min(yh, H + 4.0);
            float x0 = min(c0.x, xh) - 2.0 * A - r, x1 = max(c0.x, xh) + 2.0 * A + r;
            pos = vec2(mix(x0, x1, aPos.x * 0.5 + 0.5), mix(y0, y1, aPos.y));
            vUV = pos;
            vP = vec4(c0, yh, A);
            vE = vec4(ph, sl, 0.42 * r, a * step(4.0, dist));
        } else {
            float e = 1.0 + 0.6 * smoothstep(0.0, 1.2, s);          // running: drawn out behind
            float uy = aPos.y * 2.0 - 1.0;
            vUV = vec2(aPos.x, uy < 0.0 ? uy * e : uy) * 1.3;
            pos = vec2(xh, yh) + vUV * r;
            vC = vec2(xh / W, 1.0 - yh / H);
            vec2 l = uEnvGlassL.xy - vec2(xh, yh);
            vL = l / max(1.0, length(l));
            vE = vec4(e, r, (hw - 0.5) * 0.24, a);
            vP = vec4((hs - 0.5) * 0.2, flake * uEnvGlass.w * smoothstep(0.15, 0.45, t), hw * 6.28, 0.0);
            if (a < 0.002) pos = vec2(-99.0);
        }
    }
    gl_Position = vec4(pos.x / W * 2.0 - 1.0, 1.0 - pos.y / H * 2.0, 0.0, 1.0);
}
""".replace("GN", f"{GLASS_N:.1f}")

_GFRAG = """
uniform vec2  uRes;
uniform float uKind;
uniform vec4  uEnvGlass, uEnvGlassK, uEnvGlassL;
uniform vec3  uEnvGlassC;
uniform sampler2D uSky;       // what is behind: the frame so far (or the sky alone)
uniform sampler2D uSkyNz;     // its tiling noise (frost's reach)
uniform sampler2D uFrost;     // ice ferns (frost_texture)
varying vec2  vUV, vC, vL;
varying vec4  vP, vE;

vec3 sky(vec2 uv) { return texture2D(uSky, clamp(uv, 0.002, 0.998)).rgb; }

// a drop, premultiplied: p in its radii (y down), e drawn out above, its
// px radius, a little out of round
vec4 drop(vec2 p, float e, float rpx, vec2 wob) {
    vec2 q = vec2(p.x, p.y < 0.0 ? p.y / e : p.y);
    float d = length(q) * (1.0 + wob.x * (q.x * q.x - q.y * q.y) + wob.y * q.x * q.y);
    float cov = 1.0 - smoothstep(1.0 - 1.3 / rpx, 1.0, d);
    float h = sqrt(max(0.0, 1.0 - d * d));
    // a lens: the world behind upside down and wide, half mixed with what is
    // right behind it; a faint rim where the light bends away
    vec3 flip = sky(vC + vec2(-q.x * uRes.y / uRes.x, q.y) * (0.22 + 0.10 * h) + vec2(0.0, 0.10));
    vec3 c = mix(sky(vC + vec2(p.x, -p.y) * rpx / uRes), flip, 0.45) * (0.96 + 0.14 * h);
    c *= 1.0 - 0.30 * smoothstep(0.66, 1.0, d);
    vec2 L = vL;
    vec2 g = q - L * 0.45;
    vec2 k = q + L * 0.5;
    float lit = uEnvGlassL.z;
    c += vec3(1.0, 0.97, 0.90) * lit * (0.60 * exp(-dot(g, g) * 60.0)           // its glint
                                        + 0.12 * exp(-dot(k, k) * 9.0) * (1.0 - d)  // the light through it
                                        + 0.14 * smoothstep(0.78, 0.98, d)
                                          * max(0.0, dot(q / max(d, 0.01), L)));   // the lit edge
    float ring = smoothstep(0.98, 1.05, d) * (1.0 - smoothstep(1.05, 1.28, d));
    return vec4(c * cov, cov) * 0.95 + vec4(0.0, 0.0, 0.0, 0.07 * ring);
}

void main() {
    vec4 o;
    if (uKind > 3.5) {                          // frost: from the edges in, thickest in the corners
        vec2 q = vUV;
        float B = uEnvGlassK.z;
        float dx = min(q.x, uRes.x - q.x), dy = min(q.y, uRes.y - q.y);
        float d = -28.0 * log(exp(-dx / 28.0) + exp(-dy / 28.0));
        float corner = clamp(1.0 - max(dx, dy) / (2.0 * B + 1.0), 0.0, 1.0);
        float n = texture2D(uSkyNz, q / 150.0).r;
        float front = B * (0.30 + 1.0 * n) * (1.0 + 0.8 * corner);
        // ice ferns (frost_texture), twice, turned, so its tiles don't show
        vec4 f1 = texture2D(uFrost, q / 256.0);
        vec4 f2 = texture2D(uFrost, vec2(q.x * 0.6 - q.y * 0.8, q.x * 0.8 + q.y * 0.6) / 330.0 + 0.37);
        float fern = max(f1.r, f2.r);
        float cov = 1.0 - smoothstep(0.25 * front, front, d);          // thick by the edge
        float reach = 1.0 - smoothstep(0.6 * front, 1.3 * front, d);   // the ferns out past it
        float a = 0.32 * cov * cov + 0.28 * cov * max(f1.g, f2.g) + 0.70 * fern * reach;
        float glint = f1.b * reach;
        a *= 1.0 - smoothstep(0.8, 1.0, min(dx, dy) / (1.25 * B * (1.0 + 0.6 * corner) + 1.0));  // (its quads)
        a = clamp(a, 0.0, 0.92) * uEnvGlassK.w;                         // a light frost: faint
        vec3 c = uEnvGlassC * (0.80 + 0.30 * fern) + vec3(0.9, 0.95, 1.0) * glint * uEnvGlassL.z;
        o = vec4(c * a, a);
    } else if (uKind > 1.5 && uKind < 2.5) {    // a wet track, a few beads left on it
        vec2 q = vUV;
        float cx = vP.x + vP.w * (sin(q.y * 0.021 + vE.x) - sin(vP.y * 0.021 + vE.x)) + vE.y * (q.y - vP.y);
        float back = max(0.0, vP.z - q.y);
        float hw = vE.z * (0.55 + 0.45 * exp(-back / 90.0));
        float x = (q.x - cx) / max(hw, 0.8);
        float wet = (1.0 - smoothstep(0.55, 1.0, abs(x))) * exp(-back / 260.0)
                    * smoothstep(0.0, 6.0, q.y - vP.y + 3.0);
        vec2 uv = vec2(q.x / uRes.x, 1.0 - q.y / uRes.y);
        vec3 c = sky(uv + vec2(-x * 0.012, 0.0)) * (0.96 - 0.15 * smoothstep(0.4, 1.0, abs(x)));
        float lx = x - sign(vL.x + 0.001) * 0.45;
        c += vec3(1.0, 0.97, 0.9) * uEnvGlassL.z * 0.4 * exp(-lx * lx * 10.0);
        float a = 0.75 * wet;
        // the beads: tiny drops left at its edge, still where they were left
        float cell = floor(q.y / 17.0);
        float hb = fract(sin(cell * 12.989 + vE.x) * 4375.85);
        float yb = (cell + 0.25 + 0.5 * fract(hb * 7.3)) * 17.0;
        vec2 bp = vec2(q.x - cx - (hb - 0.5) * 1.6 * hw, q.y - yb) / (0.7 + 1.5 * hb);
        float bd = length(bp);
        float bead = step(0.45, hb) * step(10.0, vP.z - yb) * (1.0 - smoothstep(0.75, 1.0, bd))
                     * smoothstep(0.0, 6.0, yb - vP.y);
        vec2 bg = bp + vec2(0.35, 0.4);
        vec3 bc = sky(uv + bp * vec2(-0.004, 0.004)) * (1.0 - 0.25 * smoothstep(0.3, 0.9, bd))
                  + vec3(1.0, 0.97, 0.9) * uEnvGlassL.z * 0.5 * exp(-dot(bg, bg) * 7.0);
        c = mix(c, bc, bead);
        a = max(a, 0.9 * bead * exp(-back / 600.0));
        o = vec4(c * a, a) * vE.w;
    } else {
        vec2 p = vUV;
        float m = vP.y;                          // 0 a flake .. 1 melted to a drop
        vec4 dr = vec4(0.0);
        if (uKind < 2.5 || m > 0.01)
            dr = drop(uKind < 2.5 ? p : p / 0.62, vE.x, vE.y * (uKind < 2.5 ? 1.0 : 0.62), vec2(vE.z, vP.x));
        if (uKind > 2.5) {                       // a flake: six arms, a soft middle
            float rr = length(p);
            float th = atan(p.y, p.x) + vP.z;
            float arm = pow(abs(cos(3.0 * th)), 14.0) * (1.0 - smoothstep(0.45, 1.0, rr));
            float twig = pow(abs(cos(3.0 * th + 0.52)), 30.0) * (1.0 - smoothstep(0.3, 0.6, rr))
                         * smoothstep(0.15, 0.3, rr);
            float fa = clamp(0.95 * exp(-rr * rr * 10.0) + 0.85 * arm + 0.5 * twig
                             + 0.18 * exp(-rr * rr * 2.5), 0.0, 1.0) * 0.9;
            vec3 fc = uEnvGlassC * 1.25 + vec3(0.06);
            dr = mix(vec4(fc * fa, fa), dr, m);
        }
        o = dr * vE.w;
    }
    gl_FragColor = o;
}
"""


def frost_texture(n=256, seed=11):
    """Ice ferns that tile (_GFRAG's uFrost): n×n RGBA bytes — r the
    crystals (stems, their branches at 60°, theirs again), g the same
    blurred (the milky ice under them), b a few glints. ~0.1 s, once."""
    import math
    import numpy as np
    rnd = np.random.default_rng(seed)
    img = np.zeros((n, n), np.float32)

    def line(x, y, a, length, w):
        t = np.linspace(0.0, length, max(2, int(length * 2)))
        xs, ys = x + np.cos(a) * t, y + np.sin(a) * t
        x0, y0 = np.floor(xs).astype(int), np.floor(ys).astype(int)
        fx, fy = xs - x0, ys - y0
        for dx, dy, f in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                          (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            np.add.at(img, ((y0 + dy) % n, (x0 + dx) % n), f * w)

    def fern(x, y, a, length, w, depth):
        line(x, y, a, length, w)
        if depth >= 2 or length < 5:
            return
        step = max(3.5, length / rnd.uniform(6, 10))
        s = step * rnd.uniform(0.5, 1.0)
        while s < length * 0.92:
            bx, by = x + math.cos(a) * s, y + math.sin(a) * s
            bl = length * 0.36 * (1.0 - s / length) ** 0.8 * rnd.uniform(0.7, 1.2)
            for side in (-1, 1):
                if rnd.random() < 0.8:
                    fern(bx, by, a + side * math.radians(60 + rnd.uniform(-6, 6)), bl, w * 0.8, depth + 1)
            s += step * rnd.uniform(0.8, 1.2)

    for _ in range(70):
        fern(rnd.uniform(0, n), rnd.uniform(0, n), rnd.uniform(0, math.tau), rnd.uniform(14, 60), 0.8, 0)
    r = np.clip(img, 0.0, 1.0)
    g = r.copy()
    for _ in range(3):                                  # a soft blur that wraps
        g = (g + np.roll(g, 1, 0) + np.roll(g, -1, 0) + np.roll(g, 1, 1) + np.roll(g, -1, 1)) / 5.0
        g = (g + np.roll(g, 2, 0) + np.roll(g, -2, 0) + np.roll(g, 2, 1) + np.roll(g, -2, 1)) / 5.0
    g = np.clip(g * 1.4, 0.0, 1.0)
    b = (rnd.random((n, n)) > 0.996).astype(np.float32) * r
    rgba = np.stack([r, g, b, np.ones_like(r)], -1)
    return (rgba * 255.0 + 0.5).astype(np.uint8).tobytes()


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
        self._hv, self._hf = hv, hf
        self._loc = {}
        self.gprog = None                     # the glass (made when it is first wet or cold)
        self.behind = None                    # the frame under the drops (False: can't copy)
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
        self.bufs["glass"] = self._vbo(_quads([(i / GLASS_N, rnd.random(), rnd.random(), rnd.random())
                                               for i in range(GLASS_N)]))
        print("[gl] world outside ready", flush=True)

    def _vbo(self, data):
        GL = self.GL
        buf = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buf)
        arr = (ctypes.c_float * len(data))(*data)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(arr), arr, GL.GL_STATIC_DRAW)
        return buf

    def _set(self, name, value, prog=None):
        GL = self.GL
        prog = prog or self.prog
        loc = self._loc.get((prog, name))
        if loc is None:
            loc = self._loc[(prog, name)] = GL.glGetUniformLocation(prog, name)
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
        GL.glEnableVertexAttribArray(1)
        mesh = self._mesh

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

    def _mesh(self, kind, mode, n):
        GL = self.GL
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.bufs[kind])
        attrib = getattr(self.face, "attrib", GL.glVertexAttribPointer)
        attrib(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 24, None)
        attrib(1, 4, GL.GL_FLOAT, GL.GL_FALSE, 24, ctypes.c_void_p(8))
        GL.glDrawArrays(mode, 0, n)

    def glass(self, u):
        """The glass in front of her (gl_face draws it after her face, before
        the screen's layer). Blending premultiplied is on."""
        g = u.get("uEnvGlass")
        if not g or max(g[:3]) <= 0.004 or self.gprog is False or not getattr(self.face, "sky", 0):
            return
        GL = self.GL
        GL.glEnableVertexAttribArray(1)
        try:
            self._glass(u, g, self._mesh)
        except Exception as e:                        # noqa: BLE001
            self.gprog = False
            print(f"[gl] the glass in front off: {e}", flush=True)
        GL.glDisableVertexAttribArray(1)

    def _behind(self, W, H):
        """The frame so far (sky, her face) for the drops to bend: one copy
        (RGB: the window has no alpha to copy); None: the sky alone."""
        GL = self.GL
        if self.behind is False:
            return None
        try:
            GL.glActiveTexture(GL.GL_TEXTURE0 + 6)
            if self.behind is None:
                self.behind = self.face._texture(W, H, GL.GL_LINEAR)
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, W, H, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, None)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.behind)
            GL.glCopyTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, 0, 0, W, H)
            return self.behind
        except Exception as e:                        # noqa: BLE001
            self.behind = False
            print(f"[gl] the drops show the sky alone: {e}", flush=True)
            return None
        finally:
            GL.glActiveTexture(GL.GL_TEXTURE0)

    def _glass(self, u, g, mesh):
        """Wet tracks, drops, flakes, then frost on the edges (four quads,
        only the band)."""
        GL, face = self.GL, self.face
        if self.gprog is None:
            hf = self._hf.replace("mediump", "highp")      # (the frost's noise: steps in mediump)
            try:
                self.gprog = face._program(self._hv + _GVERT, hf + _GFRAG)
            except RuntimeError:
                self.gprog = face._program(self._hv + _GVERT, self._hf + _GFRAG)
            n = 256
            GL.glActiveTexture(GL.GL_TEXTURE0 + 7)       # (its own unit: unit 0 keeps the layer's)
            self.frost = face._texture(n, n, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, n, n, 0,
                            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, frost_texture(n))
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glUseProgram(self.gprog)
            for name, unit in (("uSky", 6), ("uSkyNz", 5), ("uFrost", 7)):
                loc = GL.glGetUniformLocation(self.gprog, name)
                if loc >= 0:
                    GL.glUniform1i(loc, unit)
            print("[gl] the glass in front ready", flush=True)
        gp = self.gprog
        GL.glUseProgram(gp)
        W, H = face.w, face.h
        self._set("uRes", (W, H), gp)
        for k in ("uEnvGlass", "uEnvGlassK", "uEnvGlassL", "uEnvGlassC", "uEnvMask"):
            self._set(k, u[k], gp)
        T = environment.TUNE
        wet, snow, frost = g[0], g[1], g[2]
        if max(wet, snow) > 0.004:                   # what the drops show: her too, upside down
            tex = self._behind(W, H) or face.sky
            GL.glActiveTexture(GL.GL_TEXTURE0 + 6)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glUseProgram(gp)
        if wet > 0.004:
            n = T["glass_drops"] * min(1.0, wet * 1.15)
            self._set("uK", (n, T["drop_r"], T["drop_life"], T["drop_run"] * (0.5 + 0.5 * wet)), gp)
            for kind in (2.0, 1.0):                   # (the tracks under the drops)
                self._set("uKind", kind, gp)
                mesh("glass", GL.GL_TRIANGLES, 6 * min(GLASS_N, int(n) + 1))
        if snow > 0.004:
            n = T["glass_flakes"] * min(1.0, snow * 1.15)
            self._set("uK", (n, T["flake_r"], T["flake_life"], 0.0), gp)
            self._set("uKind", 3.0, gp)
            mesh("glass", GL.GL_TRIANGLES, 6 * min(GLASS_N, int(n) + 1))
        nz = getattr(face, "sky_nz", 0)
        B = u["uEnvGlassK"][2]
        if frost > 0.004 and nz and B >= 1.0:
            for unit, tex in ((5, nz), (7, self.frost)):
                GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            self._set("uKind", 4.0, gp)
            b = min(H / 2.0, 1.25 * B)                    # the band, then deeper in the corners
            c = min(W / 2.0, H / 2.0, 1.6 * b) - b
            for rect in ((0, 0, W, b), (0, H - b, W, H), (0, b, b, H - b), (W - b, b, W, H - b),
                         (b, b, b + c, b + c), (W - b - c, b, W - b, b + c),
                         (b, H - b - c, b + c, H - b), (W - b - c, H - b - c, W - b, H - b)):
                if rect[2] - rect[0] < 1 or rect[3] - rect[1] < 1:
                    continue
                self._set("uRect", rect, gp)
                mesh("glass", GL.GL_TRIANGLES, 6)
