"""
gl_face.py — PoC: Luna's Loona face drawn by the GPU (OpenGL).

One full-screen fragment shader draws the face from signed distance fields:
eyes (rounded blocks with the smile arc / worried / cross cuts and a lid),
pupils with catch-lights, brows, mouth and blush — anti-aliased edges, a soft
glass-dome shading with a specular highlight, and a glow that falls off with
the distance from each shape (a bloom for free, no blur passes).

Everything else — particles, hands, scenes, captions, the status bar, the
mirror and photo overlays — is still drawn by robot_face.py with pygame, on a
transparent layer that is laid over the face as a texture. All the animation
(blinks, gaze, emotions, micro-expressions, lip sync) stays in robot_face.py;
this file is only a new skin for it.

Off unless LUNA_FACE_GL=1 (robot_face.py). tools/gl_face_preview.py renders
the poses headless (EGL, no window) into a PNG sheet with frame timings.
"""

import ctypes
import math
import os
import sys
import time

import face_spec

_VERT = """
attribute vec2 aPos;
uniform vec4 uRect;           // x0, y0, x1, y1 in pixels, top-left origin
uniform vec2 uRes;
void main() {
    vec2 px = mix(uRect.xy, uRect.zw, aPos * 0.5 + 0.5);
    gl_Position = vec4(px.x / uRes.x * 2.0 - 1.0, 1.0 - px.y / uRes.y * 2.0, 0.0, 1.0);
}
"""

_FRAG = """
uniform vec2  uRes;
uniform float uTime;
uniform float uTilt;
uniform float uFace;          // 0: no face (another style) — only the layer

// each eye (face_spec.py → face_uniforms): its box, its lids, its iris
uniform vec4  uEye0;          // cx, cy, w, h (px, top-left origin) — the whole eye
uniform vec4  uEye1;
uniform vec4  uLidA0;         // upper lid down (0..1), its tilt (+ inner end lower),
uniform vec4  uLidA1;         //   its arch (+ middle up), lower lid up (0..1)
uniform vec4  uLidB0;         // lower lid's arch (+ middle up), the closed seam's
uniform vec4  uLidB1;         //   alpha, the eye's turn (rad), its corner radius
uniform vec4  uPupil0;        // dx, dy (from the eye centre), iris radius, shown
uniform vec4  uPupil1;
uniform vec4  uMorph;         // heart (love), wet (sad), round (surprised), star (excited)
uniform vec3  uHeartTop;
uniform vec3  uHeartBottom;
uniform vec3  uTop;
uniform vec3  uBottom;
uniform vec3  uGlow;
uniform vec3  uTint;
uniform float uTintAmt;
uniform vec3  uShine;
uniform vec3  uPupilCol;
uniform vec3  uIrisCol;

uniform vec4  uBrow0;         // x0, y0, x1, y1
uniform vec4  uBrow1;
uniform vec4  uBrowK;         // bend0, bend1, thickness, alpha

uniform vec4  uMouth;         // cx, cy, w, h
uniform vec4  uMouthK;        // bend (+ = smile), open 0..1, alpha, kind (face_spec: 0 line,
uniform float uMouthSlant;    //   1 open, 2 O, 3 grin, 4 gritted teeth, 5 wavy); slant px

uniform vec4  uBlush;         // fcx, fcy, alpha 0..1, spread
uniform vec3  uBlushCol;

uniform sampler2D uLayer;       // what stays put on the screen (status bar, captions…)
uniform float uHasLayer;
uniform sampler2D uFaceLayer;   // what moves with the face (particles, hands, scenes)
uniform float uHasFaceLayer;
uniform sampler2D uBackLayer;   // …and what goes behind it (costume ears, steam, hair)
uniform float uPass;          // 0: the soft part (glow, blush, screen), small
uniform sampler2D uSoft;      // 1: that, stretched over the screen (+ dither)
uniform vec2  uSoftRes;       // 2: one sharp shape (uShape) in its own box, blended
uniform float uShape;         // 3: a pygame layer (uLayerSel) over its rows, blended
uniform float uLayerSel;      //    0 the screen's, 1 the face's, 2 the one behind it

uniform vec2  uGlitch;        // (on, seed): the "glitch" scene tears the picture

float gA;                     // the coverage of the shape just drawn (stage 2)


float sdRoundBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + vec2(r);
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

float sdSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}

float dot2(vec2 v) { return dot(v, v); }
float sq(float x) { return x * x; }

// a heart (iq), y up: its tip at (0, 0), its lobes up to y ~1.1, x within ±0.6
float sdHeart(vec2 p) {
    p.x = abs(p.x);
    if (p.y + p.x > 1.0) return sqrt(dot2(p - vec2(0.25, 0.75))) - 0.35355;
    return sqrt(min(dot2(p - vec2(0.0, 1.0)), dot2(p - 0.5 * max(p.x + p.y, 0.0))))
           * sign(p.x - p.y);
}

// a five-pointed star (iq), y up, r its size, rf how deep the notches
float sdStar5(vec2 p, float r, float rf) {
    vec2 k1 = vec2(0.809016994375, -0.587785252292);
    vec2 k2 = vec2(-k1.x, k1.y);
    p.x = abs(p.x);
    p -= 2.0 * max(dot(k1, p), 0.0) * k1;
    p -= 2.0 * max(dot(k2, p), 0.0) * k2;
    p.x = abs(p.x);
    p.y -= r;
    vec2 ba = rf * vec2(-k1.y, k1.x) - vec2(0.0, 1.0);
    float h = clamp(dot(p, ba) / dot(ba, ba), 0.0, r);
    return length(p - ba * h) * sign(p.y * ba.x - p.x * ba.y);
}

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

// the "glitch" scene: a few bands of rows slide sideways
float glitchShift(float y) {
    if (uGlitch.x < 0.5) return 0.0;
    float dx = 0.0;
    for (int k = 0; k < 5; k++) {
        float fk = float(k);
        if (hash(vec2(uGlitch.y, fk * 7.1)) > 0.75 && k > 1) continue;   // 2-5 bands
        float y0 = hash(vec2(uGlitch.y + 3.3, fk)) * (uRes.y - 20.0);
        float bh = 8.0 + hash(vec2(fk, uGlitch.y + 1.7)) * 38.0;
        if (y >= y0 && y < y0 + bh)
            dx = (hash(vec2(uGlitch.y * 1.3, fk + 9.0)) - 0.5) * 84.0;
    }
    return dx;
}

// ── the eye ──────────────────────────────────────────────────────────────
// A rounded block (round when surprised, a heart in love), cut by two lids:
// the upper one comes down (tilted, arched), the lower one comes up (pushed
// up in the middle by a smile). Shut, they leave a glowing seam.

vec2 eyeLocal(vec2 p, vec4 e, vec4 lb, float side) {
    vec2 q = p - e.xy;
    float a = lb.z * -side;                         // + rot: the inner end down
    float c = cos(a), s = sin(a);
    return vec2(c * q.x - s * q.y, s * q.x + c * q.y);
}

// the lids' edges at x, and their slopes
vec2 lidTop(float x, vec2 b, vec4 la, float side) {
    float xn = clamp(x / b.x, -1.0, 1.0);
    float inner = -side * xn;                       // −1 the outer corner … +1 the inner
    float y = -b.y + 2.0 * b.y * la.x + la.y * b.y * inner
              - la.z * 2.0 * b.y * (1.0 - xn * xn);
    float sl = (-side * la.y * b.y + la.z * 4.0 * b.y * xn) / b.x;
    return vec2(y, abs(x) < b.x ? sl : -side * la.y * b.y / b.x);
}

vec2 lidBot(float x, vec2 b, vec4 la, vec4 lb) {
    float xn = clamp(x / b.x, -1.0, 1.0);
    float y = b.y - 2.0 * b.y * la.w - lb.x * 2.0 * b.y * (1.0 - xn * xn);
    float sl = (lb.x * 4.0 * b.y * xn) / b.x;
    return vec2(y, abs(x) < b.x ? sl : 0.0);
}

float eyeSDF(vec2 q, vec4 e, vec4 la, vec4 lb, float side) {
    vec2 b = e.zw * 0.5;
    float r = mix(min(lb.w, min(b.x, b.y)), min(b.x, b.y), uMorph.z);
    float d = sdRoundBox(q, b, r);
    vec2 t = lidTop(q.x, b, la, side);
    d = max(d, (t.x - q.y) / sqrt(1.0 + t.y * t.y));
    vec2 u = lidBot(q.x, b, la, lb);
    d = max(d, (q.y - u.x) / sqrt(1.0 + u.y * u.y));
    if (uMorph.x > 0.001) {                         // love: the eye becomes a heart
        float s = min(b.x / 0.64, 2.0 * b.y / 1.12);
        float heart = sdHeart(vec2(q.x, 0.56 * s - q.y) / s) * s;
        d = mix(d, heart, uMorph.x);
    }
    return d;
}

// the seam where the lids meet: a shut eye ("‿" asleep, "^" laughing)
float seamSDF(vec2 q, vec4 e, vec4 la, vec4 lb, float side) {
    vec2 b = e.zw * 0.5;
    float xc = clamp(q.x, -0.84 * b.x, 0.84 * b.x);
    vec2 t = lidTop(xc, b, la, side);
    vec2 u = lidBot(xc, b, la, lb);
    float ys = 0.5 * (t.x + u.x);
    float sl = 0.5 * (t.y + u.y);
    return length(vec2(q.x - xc, (q.y - ys) / sqrt(1.0 + sl * sl))) - 5.5;
}

vec3 eyeColour(vec2 q, vec2 b, float d, vec2 look, vec4 la, float side) {
    vec3 top = mix(mix(uTop, uTint, uTintAmt), uHeartTop, uMorph.x);
    vec3 bot = mix(mix(uBottom, uTint, uTintAmt * 0.85), uHeartBottom, uMorph.x);
    // pale gold above, through amber, to orange below; the brightest part
    // a little above the middle — lit from inside
    float v = clamp((q.y + b.y) / (2.0 * b.y), 0.0, 1.0);
    vec3 col = mix(top, bot, smoothstep(0.05, 1.0, v));
    vec2 cq = (q - vec2(0.0, -0.18 * b.y)) / b;
    col *= 1.08 - 0.30 * clamp(dot(cq, cq) * 0.7, 0.0, 1.0);   // a dome: darker sides
    col *= 0.86 + 0.14 * smoothstep(0.0, 9.0, -d);             // the very edge in shadow…
    col += top * 0.30 * exp(d / 2.5);                          // …under a thin lit rim
    // the upper lid's shadow on the eye below it
    vec2 t = lidTop(q.x, b, la, side);
    float lidded = smoothstep(0.02, 0.12, la.x);
    col *= 1.0 - 0.32 * lidded * exp(-max(q.y - t.x, 0.0) / (0.16 * b.y));
    // glass: a soft highlight up and to the left, drifting against the gaze
    vec2 gq = q + look * 0.22;
    vec2 hp = (gq - vec2(-0.38 * b.x, -0.58 * b.y)) / vec2(0.32 * b.x, 0.14 * b.y);
    col = mix(col, uShine, 0.55 * exp(-dot(hp, hp) * 1.6) * (1.0 - 0.7 * lidded));
    float rx = q.x / b.x;
    float band = exp(-sq((q.y - 0.70 * b.y) / (0.10 * b.y))) * (1.0 - rx * rx);
    col += uShine * band * 0.10;                               // light from below
    return col;
}

// the iris and the pupil over the eye's colour `c`
vec3 drawIris(vec2 q, vec3 c, vec4 pu) {
    if (pu.w <= 0.01 || pu.z < 2.0) return c;
    vec2 pq = q - pu.xy;
    float pr = pu.z;
    float ir = length(pq / vec2(0.93, 1.0));
    float ia = smoothstep(1.0, -1.0, ir - pr) * pu.w;
    if (ia <= 0.0) return c;
    // the iris: a deep warm brown, lighter and streaked toward its rim, a
    // dark ring round its edge; the pupil: nearly black
    float k = clamp(ir / pr, 0.0, 1.0);
    vec3 iris = mix(uPupilCol * 1.4, uIrisCol, smoothstep(0.45, 0.95, k));
    float ang = atan(pq.y, pq.x);
    iris *= 0.92 + 0.08 * sin(ang * 22.0) * smoothstep(0.5, 0.9, k);
    iris = mix(iris, uPupilCol * 0.6, smoothstep(0.86, 1.0, k));          // the limbal ring
    float pa = smoothstep(0.52, 0.47, k);
    iris = mix(iris, uPupilCol * 0.35, pa);                               // the pupil
    iris += uIrisCol * 0.35 * exp(-sq((pq.y - 0.55 * pr) / (0.16 * pr)))
            * (1.0 - pa) * smoothstep(1.0, 0.7, k);                       // lit from below
    vec3 o = mix(c, iris, ia);
    // a soft shadow the iris throws on the eye round it
    o = mix(o, o * 0.72, (1.0 - ia) * exp(-max(ir - pr, 0.0) / 4.0) * pu.w * 0.6);
    // catch-lights: a big soft one up-left, a small one down-right (wet: more)
    vec2 s1 = (pq - vec2(-0.34 * pr, -0.38 * pr)) / vec2(0.30 * pr, 0.27 * pr);
    float h1 = smoothstep(1.0, 0.78, length(s1)) * (1.0 - uMorph.w);
    vec2 s2 = (pq - vec2(0.30 * pr, 0.30 * pr)) / (0.12 * pr);
    float h2 = smoothstep(1.0, 0.70, length(s2)) * 0.85;
    vec2 s3 = (pq - vec2(0.12 * pr, -0.52 * pr)) / (0.10 * pr);
    float h3 = smoothstep(1.0, 0.70, length(s3)) * uMorph.y;
    vec2 s4 = (pq - vec2(-0.05 * pr, 0.62 * pr)) / vec2(0.50 * pr, 0.08 * pr);
    float h4 = smoothstep(1.0, 0.5, length(s4)) * uMorph.y * 0.7;         // a wet shine
    o = mix(o, uShine, max(max(h1, h2), max(h3, h4)) * ia);
    if (uMorph.w > 0.01) {                 // excited: a star shines in each iris
        float ds = sdStar5(vec2(pq.x, -pq.y + 0.06 * pr), 0.74 * pr, 0.48);
        float sa = smoothstep(1.0, -1.0, ds) * ia * uMorph.w;
        o = mix(o, mix(uShine, uTop, 0.3), sa);
        o += uShine * 0.25 * exp(-max(ds, 0.0) / 3.0) * ia * uMorph.w;
    }
    return o;
}

// one eye over `col`; its glow is added to `glow`
vec3 drawEye(vec2 p, vec3 col, inout vec3 glow, vec4 e, vec4 la, vec4 lb, vec4 pu,
             float side) {
    vec2 b = e.zw * 0.5;
    vec2 q = eyeLocal(p, e, lb, side);
    if (uPass > 0.5 && (abs(q.x) > b.x + 4.0 || abs(q.y) > b.y + 4.0)) return col;
    float d = eyeSDF(q, e, la, lb, side);
    float ds = lb.y > 0.01 ? seamSDF(q, e, la, lb, side) : 1e5;
    float sa = lb.y * (1.0 - uMorph.x);
    if (uPass < 0.5) {
        vec3 gc = mix(mix(uGlow, uTint, uTintAmt), uHeartBottom, uMorph.x);
        float breath = 1.0 + 0.07 * sin(uTime);          // she breathes: so does the light
        float dg = max(min(d, mix(1e5, ds, sa)), 0.0);
        glow += gc * (0.46 * exp(-dg / 12.0) + 0.20 * breath * exp(-dg / 42.0))
                * smoothstep(0.0, 8.0, e.w);
        return col;
    }
    float a = clamp(0.5 - d, 0.0, 1.0);
    float as_ = clamp(0.5 - ds, 0.0, 1.0) * sa;
    if (a <= 0.0 && as_ <= 0.0) return col;
    vec3 c = eyeColour(q, b, d, pu.xy, la, side);
    c = drawIris(q, c, pu);
    // the seam: lit like the top of the eye
    vec3 sc = mix(mix(uTop, uTint, uTintAmt), uShine, 0.25);
    float cov = max(a, as_);
    vec3 outc = mix(sc, c, a / max(cov, 1e-4));
    gA = cov;
    return mix(col, outc, cov);
}

vec3 drawBrow(vec2 p, vec3 col, inout vec3 glow, vec4 s, float bend) {
    if (uBrowK.w <= 0.01) return col;
    vec2 m = (s.xy + s.zw) * 0.5;
    float hl = max(1.0, length(s.zw - s.xy) * 0.5);
    if (uPass > 0.5 && (abs(p.x - m.x) > hl + uBrowK.z
                        || abs(p.y - m.y) > abs(s.w - s.y) * 0.5 + uBrowK.z + abs(bend))) return col;
    float x = clamp((p.x - m.x) / hl, -1.0, 1.0);
    vec2 pp = vec2(p.x, p.y + bend * (1.0 - x * x));
    float taper = 0.62 + 0.38 * (1.0 - x * x);                  // fuller in the middle
    float d = sdSeg(pp, s.xy, s.zw) - uBrowK.z * 0.5 * taper;
    if (uPass < 0.5) {
        glow += uGlow * 0.40 * exp(-max(d, 0.0) / 10.0) * uBrowK.w;
        return col;
    }
    float a = clamp(0.5 - d, 0.0, 1.0) * uBrowK.w;
    gA = a;
    float v = clamp((pp.y - m.y) / (uBrowK.z * taper) + 0.5, 0.0, 1.0);
    vec3 c = mix(mix(uTop, uTint, uTintAmt * 0.8), mix(uBottom, uTint, uTintAmt * 0.6), v * 0.8);
    c = mix(c, uShine, 0.40 * exp(-sq((v - 0.22) / 0.16)));
    return mix(col, c, a);
}

vec3 drawMouth(vec2 p, vec3 col, inout vec3 glow) {
    float alpha = uMouthK.z;
    if (alpha <= 0.01) return col;
    vec2 q = p - uMouth.xy;
    float hw = uMouth.z * 0.5;
    float h = uMouth.w;
    float kind = uMouthK.w;
    if (uPass > 0.5 && (abs(q.x) > hw + h * 0.5 + 6.0
                        || abs(q.y) > max(h, uMouth.z * step(1.5, kind) * step(kind, 2.5)) * 0.5
                                      + h * step(2.5, kind) + abs(uMouthK.x)
                                      + abs(uMouthSlant) + 6.0)) return col;
    float d;
    float inner = 1e5;
    float teeth = 0.0, tongue = 0.0;
    if (kind < 0.5) {                         // a line: smile / frown / slant
        float x = clamp(q.x / hw, -1.0, 1.0);
        vec2 pq = vec2(q.x, q.y - uMouthK.x * (1.0 - x * x));
        float taper = 0.70 + 0.30 * (1.0 - x * x);
        d = sdSeg(pq, vec2(-hw, uMouthSlant), vec2(hw, -uMouthSlant)) - h * 0.5 * taper;
    } else if (kind < 1.5) {                  // open, talking: a smiling lower lip
        float x = clamp(q.x / hw, -1.0, 1.0);
        vec2 b = vec2(hw, h * 0.5);
        vec2 pq = vec2(q.x, q.y - max(uMouthK.x, 0.0) * 0.35 * (1.0 - x * x) * step(0.0, q.y));
        d = sdRoundBox(pq, b, min(b.y, 26.0));
        inner = d + 7.0;
        teeth = smoothstep(0.5, -0.5, q.y + h * 0.5 - 7.0 - h * 0.20)
                * smoothstep(0.3, 0.6, uMouthK.y);
        vec2 tq = (q - vec2(0.0, h * 0.40)) / vec2(hw * 0.55, h * 0.30);
        tongue = smoothstep(1.0, 0.8, length(tq));
    } else if (kind < 2.5) {                  // "O"
        vec2 r = vec2(uMouth.z * 0.5 * 0.86, uMouth.z * 0.5);
        d = (length(q / r) - 1.0) * min(r.x, r.y);
        inner = d + r.x * 0.30;
    } else if (kind < 3.5) {                  // a grin: "D" — a smiling top, round below
        float x = clamp(q.x / hw, -1.0, 1.0);
        vec2 c = vec2(0.0, -h * 0.28);
        vec2 R = vec2(hw, h * 0.98);
        float de = (length((q - c) / R) - 1.0) * min(R.x, R.y);
        float yt = -h * 0.28 + 0.16 * h * (1.0 - x * x);       // the top edge: a smile
        d = max(de, (yt - q.y) / sqrt(1.0 + sq(0.32 * h * x / hw)));
        inner = d + 7.0;
        teeth = smoothstep(0.5, -0.5, q.y - yt - 15.0);
        vec2 tq = (q - vec2(0.0, h * 0.58)) / vec2(hw * 0.52, h * 0.24);
        tongue = smoothstep(1.0, 0.8, length(tq));
    } else if (kind < 4.5) {                  // gritted teeth
        vec2 b = vec2(hw, h * 0.5);
        float x = clamp(q.x / hw, -1.0, 1.0);
        vec2 pq = vec2(q.x, q.y - uMouthSlant * x);
        d = sdRoundBox(pq, b, 12.0);
        inner = d + 6.0;
        float gaps = min(abs(fract(q.x / (hw / 2.5) + 0.5) - 0.5) * (hw / 2.5), abs(pq.y));
        teeth = smoothstep(1.2, 2.6, gaps);
    } else {                                  // wavy: nervous
        float x = clamp(q.x, -hw, hw);
        float k = 3.0 * 3.14159 / hw;
        float y = 7.0 * sin(x * k);
        float sl = 7.0 * k * cos(x * k);
        d = length(vec2(q.x - x, (q.y - y) / sqrt(1.0 + sl * sl))) - h * 0.5;
    }
    if (uPass < 0.5) {
        glow += mix(uGlow, uTint, uTintAmt) * 0.40 * exp(-max(d, 0.0) / 12.0) * alpha;
        return col;
    }
    float a = clamp(0.5 - d, 0.0, 1.0) * alpha;
    gA = a;
    float v = clamp(q.y / max(h, 10.0) + 0.5, 0.0, 1.0);
    vec3 c = mix(mix(uTop, uTint, uTintAmt), mix(uBottom, uTint, uTintAmt), 0.30 + 0.55 * v);
    c += uShine * 0.18 * exp(d / 2.5);                       // a lit rim
    if (inner < 1e4) {                        // the dark inside: teeth, a tongue
        float ia = clamp(0.5 - inner, 0.0, 1.0);
        vec3 inside = vec3(0.07, 0.025, 0.012) + vec3(0.10, 0.03, 0.02) * (1.0 - v);
        inside *= 0.7 + 0.3 * smoothstep(-14.0, 0.0, inner);  // deeper toward the middle
        inside = mix(inside, vec3(0.86, 0.32, 0.30), tongue * 0.9);
        inside = mix(inside, vec3(1.0, 0.95, 0.86), teeth * 0.92);
        c = mix(c, inside, ia);
    }
    return mix(col, c, a);
}

void main() {
    vec2 fc;
    if (uPass < 0.5) {
        fc = vec2(gl_FragCoord.x, uSoftRes.y - gl_FragCoord.y) * (uRes / uSoftRes);
    } else {
        fc = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);
        fc.x -= glitchShift(fc.y);
    }
    vec2 uv = fc / uRes;
    // the head's tilt: turn the face (and its layer) about the screen centre
    vec2 c0 = uRes * 0.5;
    vec2 dv = fc - c0;
    float cs = cos(uTilt), sn = sin(uTilt);
    vec2 p = c0 + vec2(cs * dv.x - sn * dv.y, sn * dv.x + cs * dv.y);
    vec3 glow = vec3(0.0);
    if (uPass < 0.5) {
        // a deep, faintly warm screen with a vignette
        vec2 vq = uv - vec2(0.5, 0.46);
        vec3 col = vec3(0.030, 0.020, 0.016) * (1.0 - 1.6 * dot(vq, vq));
        // glass: a faint diagonal sheen across the panel
        float sheen = exp(-sq((uv.x + uv.y * 0.6 - 0.35) / 0.10));
        col += vec3(0.010, 0.009, 0.012) * sheen;
        if (uFace > 0.5) {
            if (uBlush.z > 0.01) {                       // blush under the eyes
                vec2 bq = (p - uBlush.xy - vec2(-232.0, 70.0)) / vec2(uBlush.w * 1.5, uBlush.w);
                col += uBlushCol * 0.60 * uBlush.z * exp(-dot(bq, bq) * 2.0);
                bq = (p - uBlush.xy - vec2(232.0, 70.0)) / vec2(uBlush.w * 1.5, uBlush.w);
                col += uBlushCol * 0.60 * uBlush.z * exp(-dot(bq, bq) * 2.0);
            }
            col = drawEye(p, col, glow, uEye0, uLidA0, uLidB0, uPupil0, -1.0);
            col = drawEye(p, col, glow, uEye1, uLidA1, uLidB1, uPupil1, 1.0);
            col = drawBrow(p, col, glow, uBrow0, uBrowK.x);
            col = drawBrow(p, col, glow, uBrow1, uBrowK.y);
            col = drawMouth(p, col, glow);
            col += glow * 0.55;
        } else {
            col = vec3(0.0);
        }
        gl_FragColor = vec4(col, 1.0);
    } else if (uPass < 1.5) {
        vec3 col = texture2D(uSoft, vec2(uv.x, 1.0 - uv.y)).rgb;   // (drawn bottom row first)
        col += (hash(fc + fract(uTime)) - 0.5) / 255.0;            // dither: no banding
        gl_FragColor = vec4(col, 1.0);
    } else if (uPass < 2.5) {
        // one shape, premultiplied: blended over what is there
        gA = 0.0;
        vec3 c = vec3(0.0);
        if (uShape < 0.5)      c = drawEye(p, c, glow, uEye0, uLidA0, uLidB0, uPupil0, -1.0);
        else if (uShape < 1.5) c = drawEye(p, c, glow, uEye1, uLidA1, uLidB1, uPupil1, 1.0);
        else if (uShape < 2.5) c = drawBrow(p, c, glow, uBrow0, uBrowK.x);
        else if (uShape < 3.5) c = drawBrow(p, c, glow, uBrow1, uBrowK.y);
        else                   c = drawMouth(p, c, glow);
        gl_FragColor = vec4(c, gA);
    } else {
        vec4 l = vec4(0.0);
        if (uLayerSel < 0.5) {
            l = texture2D(uLayer, uv);
        } else {
            vec2 lu = p / uRes;
            if (lu.x >= 0.0 && lu.x <= 1.0 && lu.y >= 0.0 && lu.y <= 1.0)
                l = (uLayerSel < 1.5) ? texture2D(uFaceLayer, lu) : texture2D(uBackLayer, lu);
        }
        gl_FragColor = vec4(l.rgb * l.a, l.a);
    }
}
"""


def _pick_platform():
    """PyOpenGL must load the same GL as SDL's window: EGL under Wayland."""
    if "PYOPENGL_PLATFORM" in os.environ or not sys.platform.startswith("linux"):
        return
    drv = ""
    try:
        import pygame
        if pygame.display.get_init():
            drv = pygame.display.get_driver()
    except Exception:
        pass
    if drv in ("wayland", "kmsdrm") or (not drv and os.environ.get("WAYLAND_DISPLAY")):
        os.environ["PYOPENGL_PLATFORM"] = "egl"


class _Layer:
    """A pygame layer's texture and the bytes last sent, per 32-row band."""
    BAND = 32

    def __init__(self, tex, width, height):
        self.tex = tex
        self.w = width
        self.bands = [(y, min(self.BAND, height - y)) for y in range(0, height, self.BAND)]
        self.sent = [None] * len(self.bands)      # the band's bytes on the texture
        self.zero = {h: bytes(width * 4 * h) for _, h in self.bands}

    def runs(self):
        """(y0, y1) of the runs of bands with something on them."""
        out = []
        for (y, h), data in zip(self.bands, self.sent):
            if data is None:
                continue
            if out and out[-1][1] == y:
                out[-1] = (out[-1][0], y + h)
            else:
                out.append((y, y + h))
        return out


def layer_surface(width, height):
    """A transparent pygame surface whose memory is R, G, B, A — what the
    GPU takes as it is. pygame's usual layout (B, G, R, A) made Mesa swap
    every pixel on the CPU: 26 ms for a whole layer instead of ~2 (Pi 4)."""
    import pygame
    if sys.byteorder == "little":
        return pygame.Surface((width, height), pygame.SRCALPHA, 32,
                              masks=(0xFF, 0xFF00, 0xFF0000, 0xFF000000))
    return pygame.Surface((width, height), pygame.SRCALPHA)


def _gl_format(GL, surface):
    """The GL format of a 32-bit pygame surface's own memory, or None when
    it isn't one GL reads directly (or its rows are padded)."""
    if surface.get_bytesize() != 4 or surface.get_pitch() != surface.get_width() * 4:
        return None
    masks = tuple(surface.get_masks())
    if masks == (0xFF0000, 0xFF00, 0xFF, 0xFF000000) and sys.byteorder == "little":
        return GL.GL_BGRA
    if masks == (0xFF, 0xFF00, 0xFF0000, 0xFF000000) and sys.byteorder == "little":
        return GL.GL_RGBA
    return None


# a costume's own eyes: uniforms laid over the style's (face_uniforms)
COSTUME_EYES = {
    "googly_eyes": {"uTop": (1.0, 1.0, 1.0), "uBottom": (0.80, 0.82, 0.88),
                    "uGlow": (0.55, 0.60, 0.75), "uShine": (1.0, 1.0, 1.0),
                    "uPupilCol": (0.03, 0.03, 0.05), "uTintAmt": 0.0},
    "crazy_robot": {"uTop": (0.70, 1.0, 0.55), "uBottom": (0.10, 0.62, 0.30),
                    "uGlow": (0.15, 0.85, 0.40), "uShine": (0.92, 1.0, 0.90),
                    "uPupilCol": (0.02, 0.10, 0.04)},
}


# …and a costume's own face settings (face_spec's keys)
COSTUME_SPEC = {
    "googly_eyes": {"round": 1.0, "heart": 0.0, "star": 0.0, "brow_a": 0.0,
                    "lid_top": (0.0, 0.0), "lid_tilt": (0.0, 0.0), "lid_bot": (0.0, 0.0),
                    "lid_bot_bend": (0.0, 0.0), "gaze_x": 0.0, "gaze_y": 0.0},
}


def _rgb(c):
    return tuple(v / 255.0 for v in c[:3])


def _lerp(a, b, t):
    return a + (b - a) * t


class GLFace:
    """Compiles the shader and draws a frame from a dict of uniforms (see
    face_uniforms) plus, optionally, the pygame layer to lay over it."""

    def __init__(self, width, height):
        _pick_platform()
        from OpenGL import GL
        self.GL = GL
        self.w, self.h = width, height
        self.prog = None
        errors = []
        for head in ("#version 120\n", "#version 100\nprecision mediump float;\n"):
            try:
                self.prog = self._program(head + _VERT, head + _FRAG)
                self.glsl = head.split()[1]
                break
            except RuntimeError as e:
                errors.append(str(e))
        if self.prog is None:
            raise RuntimeError("shader did not compile: " + " | ".join(errors))
        GL.glUseProgram(self.prog)
        self._loc = {}
        quad = (ctypes.c_float * 8)(-1, -1, 1, -1, -1, 1, 1, 1)
        self.vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(quad), quad, GL.GL_STATIC_DRAW)
        self.apos = GL.glGetAttribLocation(self.prog, "aPos")
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        # the two pygame layers: fixed to the screen (sharp), and turning with
        # the face (smoothed, it is sampled turned)
        self.screen_l = _Layer(self._texture(width, height, GL.GL_NEAREST), width, height)
        self.face_l = _Layer(self._texture(width, height, GL.GL_LINEAR), width, height)
        self.back_l = _Layer(self._texture(width, height, GL.GL_LINEAR), width, height)
        # the soft part's framebuffer: a quarter of the size (it is all
        # glow and gradients), smoothed when stretched
        self.sw, self.sh = max(1, width // 4), max(1, height // 4)
        self.soft = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.soft)
        for k, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR),
                     (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                     (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE),
                     (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, k, v)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, self.sw, self.sh, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        self.soft_fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.soft_fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_2D, self.soft, 0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        self.target_fbo = 0              # where the frame goes (0: the window)
        self.uploaded = 0                # bytes sent to the GPU (the preview's numbers)
        self.eased = face_spec.Eased()   # the mood's settings on screen, gliding
        self._t_last = 0.0
        self.shape_rects = []            # each shape's box on the screen (face_uniforms)
        print(f"[gl] face shader ready (GLSL {self.glsl}, "
              f"{GL.glGetString(GL.GL_RENDERER).decode(errors='replace')})", flush=True)

    def _texture(self, w, h, filt):
        GL = self.GL
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        for k, v in ((GL.GL_TEXTURE_MIN_FILTER, filt), (GL.GL_TEXTURE_MAG_FILTER, filt),
                     (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE),
                     (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, k, v)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, bytes(w * h * 4))
        return tex

    def _program(self, vs, fs):
        GL = self.GL
        prog = GL.glCreateProgram()
        for src, kind in ((vs, GL.GL_VERTEX_SHADER), (fs, GL.GL_FRAGMENT_SHADER)):
            sh = GL.glCreateShader(kind)
            GL.glShaderSource(sh, src)
            GL.glCompileShader(sh)
            if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
                raise RuntimeError(GL.glGetShaderInfoLog(sh).decode(errors="replace")[:400])
            GL.glAttachShader(prog, sh)
        GL.glBindAttribLocation(prog, 0, "aPos")
        GL.glLinkProgram(prog)
        if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
            raise RuntimeError(GL.glGetProgramInfoLog(prog).decode(errors="replace")[:400])
        return prog

    def _u(self, name, value):
        GL = self.GL
        loc = self._loc.get(name)
        if loc is None:
            loc = self._loc[name] = GL.glGetUniformLocation(self.prog, name)
        if loc < 0:
            return
        if isinstance(value, (int, float)):
            GL.glUniform1f(loc, float(value))
        elif len(value) == 2:
            GL.glUniform2f(loc, *map(float, value))
        elif len(value) == 3:
            GL.glUniform3f(loc, *map(float, value))
        else:
            GL.glUniform4f(loc, *map(float, value))

    def upload(self, layer, surface):
        """A pygame layer (SRCALPHA, the screen's size) → its texture: its
        memory read as it is (no conversion), and only the 32-row bands whose
        bytes changed are sent — the status bar is redrawn every frame but
        changes once a minute. (Finding the drawn area with
        get_bounding_rect() cost 3 ms for the screen, 8 ms band by band —
        more than sending it all; 13 Oct, Pi 4.) True when anything is on it."""
        GL = self.GL
        fmt = _gl_format(GL, surface)
        if fmt is None:                          # an unusual layout: convert it
            import pygame
            raw, fmt = pygame.image.tobytes(surface, "RGBA"), GL.GL_RGBA
        else:
            raw = surface.get_view("2").raw
        pitch = layer.w * 4
        any_ = bound = False
        for i, (y, h) in enumerate(layer.bands):
            # (bytes, not a memoryview: comparing those goes item by item —
            # 21 ms a frame; bytes compare at memcmp speed)
            chunk = raw[y * pitch:(y + h) * pitch]
            empty = chunk == layer.zero[h]
            any_ = any_ or not empty
            if layer.sent[i] is None and empty:
                continue                          # (a new texture is clear already)
            if layer.sent[i] is not None and chunk == layer.sent[i]:
                continue                          # the same pixels are there already
            if not bound:
                GL.glBindTexture(GL.GL_TEXTURE_2D, layer.tex)
                bound = True
            data = chunk
            GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, y, layer.w, h, fmt,
                               GL.GL_UNSIGNED_BYTE, data)
            self.uploaded += len(data)
            layer.sent[i] = None if empty else data
        return any_

    def upload_layer(self, surface):
        """(the preview's call) the screen layer."""
        return self.upload(self.screen_l, surface)

    def _sampler(self, name, unit, tex):
        GL = self.GL
        GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        loc = self._loc.get(name)
        if loc is None:
            loc = self._loc[name] = GL.glGetUniformLocation(self.prog, name)
        GL.glUniform1i(loc, unit)

    def _quad(self):
        GL = self.GL
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glEnableVertexAttribArray(self.apos)
        GL.glVertexAttribPointer(self.apos, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

    def render(self, uniforms, has_layer=False, face_layer=None, screen_layer=None,
               back_layer=None):
        """face_layer / screen_layer: pygame surfaces to upload first (or
        has_layer: the screen layer was uploaded already). The stages: the
        soft part small, stretched over the screen, each shape in its own
        box, the layers over their rows — every pixel is worked on only where
        something is (one full-screen shader for all of it: 16 ms a frame)."""
        GL = self.GL
        has_face = face_layer is not None and self.upload(self.face_l, face_layer)
        has_back = back_layer is not None and self.upload(self.back_l, back_layer)
        if screen_layer is not None:
            has_layer = self.upload(self.screen_l, screen_layer)
        GL.glUseProgram(self.prog)
        self._u("uRes", (self.w, self.h))
        self._u("uSoftRes", (self.sw, self.sh))
        for k, v in uniforms.items():
            self._u(k, v)
        full = (0.0, 0.0, float(self.w), float(self.h))
        self._sampler("uLayer", 0, self.screen_l.tex)
        self._sampler("uSoft", 1, 0)
        self._sampler("uFaceLayer", 2, self.face_l.tex)
        self._sampler("uBackLayer", 3, self.back_l.tex)
        GL.glDisable(GL.GL_BLEND)
        # 0: glow, blush and the screen, small
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.soft_fbo)
        GL.glViewport(0, 0, self.sw, self.sh)
        self._u("uPass", 0.0)
        self._u("uRect", full)
        self._quad()
        # 1: stretched over the whole screen
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.target_fbo)
        GL.glViewport(0, 0, self.w, self.h)
        self._sampler("uSoft", 1, self.soft)
        self._u("uPass", 1.0)
        self._quad()
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)    # premultiplied
        if has_back:                         # behind the face: costume ears, steam…
            self._u("uPass", 3.0)
            self._u("uLayerSel", 2.0)
            self._u("uRect", full)
            self._quad()
        # 2: the sharp shapes, each in its own box
        if uniforms.get("uFace", 0.0) > 0.5:
            self._u("uPass", 2.0)
            for i, rect in enumerate(self.shape_rects):
                if rect is None:
                    continue
                self._u("uShape", float(i))
                self._u("uRect", rect)
                self._quad()
        # 3: the pygame layers — the face's (turned) and the screen's, by rows
        self._u("uPass", 3.0)
        if has_face:
            self._u("uLayerSel", 1.0)
            self._u("uRect", full)
            self._quad()
        if has_layer:
            self._u("uLayerSel", 0.0)
            for y0, y1 in self.screen_l.runs():
                self._u("uRect", (0.0, float(y0), float(self.w), float(y1)))
                self._quad()
        GL.glDisable(GL.GL_BLEND)

    def _box(self, cx, cy, hx, hy, tilt):
        """A shape's box (centre, half sizes, in the face's own coordinates)
        → the box it covers on the screen with the head turned, or None."""
        if hx <= 0 or hy <= 0:
            return None
        c0x, c0y = self.w / 2.0, self.h / 2.0
        cs, sn = math.cos(tilt), math.sin(tilt)
        xs, ys = [], []
        for dx, dy in ((-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy)):
            qx, qy = cx + dx - c0x, cy + dy - c0y
            xs.append(c0x + cs * qx + sn * qy)
            ys.append(c0y - sn * qx + cs * qy)
        x0, x1 = max(0.0, min(xs) - 1), min(float(self.w), max(xs) + 1)
        y0, y1 = max(0.0, min(ys) - 1), min(float(self.h), max(ys) + 1)
        return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None

    def _shape_boxes(self, u):
        """Where stage 2 draws: the eyes, the brows, the mouth."""
        tilt = u["uTilt"]
        boxes = []
        if u["uGlitch"][0] > 0.5:                  # torn sideways: anywhere in the rows
            return [(0.0, 0.0, float(self.w), float(self.h))] * 5
        for i in (0, 1):
            ex, ey, w, h = u[f"uEye{i}"]
            boxes.append(self._box(ex, ey, w / 2 + 8, h / 2 + 8, tilt))
        bend0, bend1, thick, alpha = u["uBrowK"]
        for i, bend in ((0, bend0), (1, bend1)):
            x0, y0, x1, y1 = u[f"uBrow{i}"]
            if alpha <= 0.01:
                boxes.append(None)
                continue
            pad = thick + abs(bend) + 2
            boxes.append(self._box((x0 + x1) / 2, (y0 + y1) / 2,
                                   abs(x1 - x0) / 2 + thick, abs(y1 - y0) / 2 + pad, tilt))
        mx, my, w, h = u["uMouth"]
        bend, open_, alpha, kind = u["uMouthK"]
        if alpha <= 0.01:
            boxes.append(None)
        else:
            hx = w / 2 + h / 2 + 8
            hy = (max(h, w) / 2 + h + abs(bend) + abs(u["uMouthSlant"]) + 10)
            boxes.append(self._box(mx, my, hx, hy, tilt))
        return boxes

    # ── Luna's animation state → the shader's inputs ──────────────────────
    def face_uniforms(self, face, rf, fcx, fcy):
        """face: the RobotFace; rf: the robot_face module (its live style
        globals). The mood's settings (face_spec.py), eased over real time,
        with the live animation on top: blinks close the lids, squints and
        wide eyes from the reply scenes, the gaze, the mouth while talking."""
        now = time.monotonic()
        dt = (now - self._t_last) if self._t_last else 1.0 / 30
        self._t_last = now
        emo = face._emotion
        costume = getattr(face, "_costume", None)
        target = face_spec.spec(emo, listening=face._listen)
        target.update(getattr(face, "_spec_mod", None) or {})   # a reply scene's touch
        googly = costume == "googly_eyes"
        if googly:                                # big round googly eyes, nothing else
            target.update(COSTUME_SPEC["googly_eyes"])
        cur = self.eased.step(target, dt)
        u = {"uTime": (face.breath_phase if hasattr(face, "breath_phase") else 0.0),
             "uTilt": math.radians(face.head_angle),
             "uFace": 1.0 if rf.EYE_MODE == "block" else 0.0,
             "uTop": _rgb(rf.EYE_GRAD_TOP), "uBottom": _rgb(rf.EYE_GRAD_BOTTOM),
             "uGlow": _rgb(rf.GLOW_COL), "uShine": _rgb(rf.IRIS_SHINE),
             "uPupilCol": _rgb(rf.PUPIL_DARK),
             "uIrisCol": _rgb(getattr(rf, "IRIS_COL", (120, 52, 10))),
             "uBlushCol": _rgb(rf.BLUSH_COL),
             "uHeartTop": (1.0, 0.62, 0.70), "uHeartBottom": (0.90, 0.16, 0.38)}
        tint = face._eye_color
        amt = 0.45 if tint else 0.0
        heat = cur["tint"] + 0.45 * face.angry_pulse          # angry: red, and pulsing
        if heat > 0.01:
            tint = rf.ANGRY_COL if not tint else tint
            amt = max(amt, heat)
        u["uTint"] = _rgb(tint or rf.EYE_GRAD_TOP)
        u["uTintAmt"] = min(0.85, amt)
        u["uMorph"] = (cur["heart"], cur["wet"], cur["round"], cur["star"])
        look = COSTUME_EYES.get(costume)
        if look:                                  # a costume's own eyes (googly, robot…)
            u.update(look)
        conv = getattr(face, "_pupil_converge", 0.0)
        brows = []
        for i, (eye, side) in enumerate(((face.left_eye, -1), (face.right_eye, 1))):
            cx, cy = fcx + eye.rel_x, fcy + eye.rel_y + cur["eye_dy"]
            w = min(float(eye.w), rf.EYE_SPREAD * 2 - 44)
            h = eye.h * (1.0 + 0.15 * eye.widen)
            if googly:
                w = h = min(w, eye.h * 1.3)
            # the eye leans a little toward where she looks; the iris does the rest
            ex, ey = cx + eye.pupil_ox * 0.30, cy + eye.pupil_oy * 0.30
            top, tilt, bend = cur["lid_top"][i], cur["lid_tilt"][i], cur["lid_bend"][i]
            bot, bbend = cur["lid_bot"][i], cur["lid_bot_bend"][i]
            # squints (reply scenes, idle micro-expressions) bring both lids
            # in; wide eyes open them
            sq = eye.squint
            top, bot = top + (1.0 - top) * 0.30 * sq, bot + (1.0 - bot) * 0.18 * sq
            top, bot = top * (1.0 - 0.7 * eye.widen), bot * (1.0 - 0.7 * eye.widen)
            # a blink: the lids meet ~60 % of the way down, their curves meet too
            shut = 1.0 - max(0.0, min(1.0, eye.blink_t))
            open_ = max(0.0, 1.0 - top - bot)
            top, bot = top + shut * open_ * 0.62, bot + shut * open_ * 0.38
            mid = 0.5 * (bend + bbend)
            bend, bbend = _lerp(bend, mid, shut), _lerp(bbend, mid, shut)
            tilt *= 1.0 - shut
            # shut (or nearly): the glowing seam where the lids meet
            gap = max(1.0 - top - bot, 1.0 - top - bot + bend - bbend) * h
            seam = max(0.0, min(1.0, 1.0 - gap / 14.0))
            u[f"uEye{i}"] = (ex, ey, w, h)
            u[f"uLidA{i}"] = (top, tilt, bend, bot)
            u[f"uLidB{i}"] = (bbend, seam, math.radians(cur["rot"][i]), cur["eye_r"])
            # the iris: where she looks (face tracking + the mood's own glance)
            pr = min(w, h) * 0.27 * cur["pupil"][i] * eye.pupil_scale
            dx = eye.pupil_ox * 0.85 + cur["gaze_x"] - side * conv * 0.6   # cross-eyed: in
            dy = eye.pupil_oy * 0.85 + cur["gaze_y"]
            if googly:                            # loose pupils, rolling about
                t = face.breath_phase * 2.3 + i * 1.7
                pr = min(w, h) * 0.30
                dx, dy = h * 0.2 * math.sin(t), h * 0.2 * abs(math.cos(t * 0.7))
            mx_, my_ = max(0.0, w / 2 - pr * 0.95), max(0.0, h / 2 - pr * 0.80)
            dx, dy = max(-mx_, min(mx_, dx)), max(-my_, min(my_, dy))
            shown = (1.0 - cur["heart"]) if rf.BLOCK_PUPIL else 0.0
            shown *= max(0.0, min(1.0, (gap - 8.0) / 22.0))     # a slit: just the glow
            u[f"uPupil{i}"] = (dx, dy, pr, shown)
            # the brow over it: 66 % of the eye's width, its inner end tilted
            bw = w * 0.66
            by = ey - h / 2 - cur["brow_gap"] - cur["brow_y"][i]
            t = cur["brow_tilt"][i] * 0.5
            if side < 0:                          # the left eye: its inner end on the right
                brows.append((ex - bw / 2, by - t, ex + bw / 2, by + t))
            else:
                brows.append((ex - bw / 2, by + t, ex + bw / 2, by - t))
        u["uBrow0"], u["uBrow1"] = brows
        u["uBrowK"] = (cur["brow_bend"], cur["brow_bend"], 17.0, cur["brow_a"])
        u.update(self._mouth(face, rf, fcx, fcy, cur))
        u["uBlush"] = (fcx, fcy, cur["blush"], 30.0)
        sp = getattr(face, "_scene_p", 0.0)
        tearing = (getattr(face, "_scene_name", None) == "glitch" and 0.12 < sp < 0.82)
        u["uGlitch"] = (1.0, float(int(sp * 24))) if tearing else (0.0, 0.0)
        self.shape_rects = self._shape_boxes(u)
        return u

    def _mouth(self, face, rf, fcx, fcy, cur):
        """The mood's mouth — or, while she talks, one opened by her voice."""
        m = face.mouth
        mx = fcx + m.rel_x + cur["mouth_dx"]
        my = fcy + m.rel_y + cur["mouth_dy"]
        kind = self.eased.mouth
        w, h, bend = cur["mouth_w"], cur["mouth_h"], cur["mouth_bend"]
        slant, open_ = cur["mouth_slant"], 0.0
        alpha = cur["mouth_a"] * self.eased.mouth_fade
        talking = face._speaking or m.speak_fade > 0.05
        if talking:
            e = m.talk_open
            alpha = max(alpha, min(1.0, m.speak_fade))
            if e > 0.06:
                kind, open_ = face_spec.OPEN, e
                w = _lerp(m.mouth_w * 0.45, m.mouth_w, max(0.0, min(1.0, (e - 0.06) / 0.5)))
                h = max(12.0, 10.0 + (e + m.jaw_bounce * 0.3) * 82.0)
                bend = max(0.0, bend)
            else:                                 # between words: closed, still smiling
                kind, w, h = face_spec.LINE, max(110.0, w * 0.9), 12.0
                bend = 0.5 * bend + m.corner_lift * 8.0
                slant = 0.0
        return {"uMouth": (mx, my, w, h), "uMouthK": (bend, open_, alpha, float(kind)),
                "uMouthSlant": slant}
