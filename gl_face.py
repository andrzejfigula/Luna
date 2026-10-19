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
import random
import sys
import time

import face_spec
import themes
import visualizer

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
uniform vec4  uLidB1;         //   alpha, the eye's turn (rad), its squircle exponent
uniform vec4  uPupil0;        // dx, dy (from the eye centre), iris radius, shown
uniform vec4  uPupil1;
uniform vec4  uMorph;         // heart (love), wet (sad), round (surprised), star (excited)
uniform vec4  uFx;            // (spiral, static, time, seed): dizzy and lost-signal eyes
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
uniform float uEnergy;        // her voice, 0..1: the eyes glow a little brighter
uniform float uWarm;          // a warm mood: the pupils' rims glow warmer
uniform float uDim;           // asleep: the eyes dim
uniform float uPixel;         // a theme's pixel art (themes.py): block size px, 0 off
uniform vec3  uMouthCol;      // …its mouth's own colour, by uMouthColAmt
uniform float uMouthColAmt;
uniform float uWave;          // > 0: the wavy mouth is a voice wave this tall (HAL)

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

// ── the light ────────────────────────────────────────────────────────────
// One key light, warm, from above and a little in front (y is down), a faint
// amber fill. Every feature is a small rounded object: its edge rolls over in
// a bevel `bw` wide (the normal there leans outward, along the outline — the
// SDF's gradient), its middle is a gentle dome. The tops catch the light, the
// undersides turn deep orange.
vec3 lit(vec3 albedo, vec2 grad, float d, float bw, vec2 dome) {
    vec3 L = normalize(vec3(-0.28, -0.80, 0.55));
    float lc = cos(uTilt), ls = sin(uTilt);       // (the room's light: the head turns under it)
    L.xy = vec2(lc * L.x - ls * L.y, ls * L.x + lc * L.y);
    float t = clamp(-d / bw, 0.0, 1.0);
    float slope = 1.7 * (1.0 - t) * (1.0 - t);
    vec3 n = normalize(vec3(grad * slope + dome, 1.0));
    float diff = max(dot(n, L), 0.0);
    vec3 c = albedo * (0.62 + 0.56 * diff) + albedo * vec3(0.05, 0.03, 0.0);   // key + fill
    c *= mix(1.0, 0.68, smoothstep(0.05, 0.75, n.y));                   // the underside
    float spec = pow(max(dot(n, normalize(L + vec3(0.0, 0.0, 1.0))), 0.0), 34.0);
    return c + uShine * spec * 0.42;
}

// the outward direction of a shape at q (its SDF's gradient, by differences)
#define GRAD(F, q, d) normalize(vec2(F(q + vec2(1.0, 0.0)) - d, F(q + vec2(0.0, 1.0)) - d) + 1e-6)

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

// a squircle: |x/a|^n + |y/b|^n = 1 — n 2 an ellipse, higher squarer
float sdSquircle(vec2 q, vec2 b, float n) {
    vec2 a = abs(q) / b;
    float f = pow(pow(a.x, n) + pow(a.y, n), 1.0 / n);
    return (f - 1.0) * min(b.x, b.y) * (0.75 + 0.25 * min(b.x, b.y) / max(b.x, b.y));
}

float eyeSDF(vec2 q, vec4 e, vec4 la, vec4 lb, float side) {
    vec2 b = e.zw * 0.5;
    float d = sdSquircle(q, b, mix(lb.w, 2.0, uMorph.z));       // round when surprised
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
    // the upper lid's shadow on the eye below it
    vec2 t = lidTop(q.x, b, la, side);
    float lidded = smoothstep(0.02, 0.12, la.x) * (1.0 - uMorph.x);   // (hearts have no lids)
    col *= 1.0 - 0.32 * lidded * exp(-max(q.y - t.x, 0.0) / (0.16 * b.y));
    // glass: a soft highlight up and to the left, drifting against the gaze
    vec2 gq = q + look * 0.22;
    vec2 hp = (gq - vec2(-0.38 * b.x, -0.58 * b.y)) / vec2(0.32 * b.x, 0.14 * b.y);
    col = mix(col, uShine, 0.50 * exp(-dot(hp, hp) * 1.6) * (1.0 - 0.7 * lidded));
    // light coming through the glass: the lower edge glows
    col += bot * 0.28 * exp(min(d, 0.0) / 7.0) * smoothstep(0.55, 1.0, v);
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
    // a big glossy black pupil: deepest in the middle, a touch of warm
    // brown at its rim, a faint glow of the eye's light at its bottom
    float k = clamp(ir / pr, 0.0, 1.0);
    vec3 iris = mix(uPupilCol * 0.30, uPupilCol * 1.5, smoothstep(0.55, 1.0, k));
    iris += uIrisCol * 0.30 * exp(-sq((pq.y - 0.62 * pr) / (0.18 * pr)))
            * smoothstep(1.0, 0.75, k);
    iris += uIrisCol * 0.55 * uWarm * smoothstep(0.70, 0.97, k);         // a warm rim
    iris += uShine * 0.08 * exp(-sq((k - 0.80) / 0.05))                   // a glassy ring
            * clamp(0.5 - (pq.x + pq.y) / (2.0 * pr), 0.0, 1.0);
    vec3 o = mix(c, iris, ia);
    // a soft shadow the iris throws on the eye round it
    float irs = length((pq - vec2(0.05 * pr, 0.12 * pr)) / vec2(0.93, 1.0));
    o = mix(o, o * 0.66, (1.0 - ia) * exp(-max(irs - pr, 0.0) / 5.0) * pu.w * 0.65);
    vec2 hq = pq + pu.xy * 0.16;          // the catch-lights lag the gaze: they are the light's
    // catch-lights: a big soft one up-left, a small one down-right (wet: more)
    vec2 s1 = (hq - vec2(-0.30 * pr, -0.34 * pr)) / vec2(0.34 * pr, 0.32 * pr);
    float h1 = smoothstep(1.0, 0.86, length(s1)) * (1.0 - uMorph.w);
    vec2 s2 = (hq - vec2(0.34 * pr, 0.32 * pr)) / (0.13 * pr);
    float h2 = smoothstep(1.0, 0.80, length(s2)) * (0.75 + 0.2 * sin(uTime * 7.0));   // shimmer
    vec2 s3 = (hq - vec2(0.12 * pr, -0.52 * pr)) / (0.10 * pr);
    float h3 = smoothstep(1.0, 0.70, length(s3)) * uMorph.y;
    vec2 s4 = (hq - vec2(-0.05 * pr, 0.62 * pr)) / vec2(0.50 * pr, 0.08 * pr);
    float h4 = smoothstep(1.0, 0.5, length(s4)) * uMorph.y * 0.7;         // a wet shine
    o = mix(o, uShine, max(max(h1, h2), max(h3, h4)) * ia);
    if (uMorph.w > 0.01) {                 // excited: a star shines in each iris
        float wa = 0.25 * sin(uTime * 2.0);           // the star wobbles, and breathes
        vec2 sp = mat2(cos(wa), -sin(wa), sin(wa), cos(wa)) * vec2(pq.x, -pq.y + 0.06 * pr);
        float ds = sdStar5(sp, (0.70 + 0.06 * sin(uTime * 5.0)) * pr, 0.48);
        float sa = smoothstep(1.0, -1.0, ds) * ia * uMorph.w;
        o = mix(o, mix(uShine, uTop, 0.3), sa);
        o += uShine * 0.25 * exp(-max(ds, 0.0) / 3.0) * ia * uMorph.w;
    }
    return o;
}

float browSDF(vec2 p, vec4 s, float bend) {
    vec2 m = (s.xy + s.zw) * 0.5;
    float hl = max(1.0, length(s.zw - s.xy) * 0.5);
    float x = clamp((p.x - m.x) / hl, -1.0, 1.0);
    vec2 pp = vec2(p.x, p.y + bend * (1.0 - x * x));
    float taper = 0.62 + 0.38 * (1.0 - x * x);                  // fuller in the middle
    return sdSeg(pp, s.xy, s.zw) - uBrowK.z * 0.5 * taper;
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
        glow += gc * (0.40 * exp(-dg / 10.0) + 0.17 * breath * exp(-dg / 40.0))
                * (1.0 + 0.35 * uEnergy) * uDim
                * smoothstep(0.0, 8.0, e.w);
        return col;
    }
    float a = clamp(0.5 - d, 0.0, 1.0);
    float as_ = clamp(0.5 - ds, 0.0, 1.0) * sa;
    if (a <= 0.0 && as_ <= 0.0) return col;
    vec3 c = eyeColour(q, b, d, pu.xy, la, side);
    // its volume: a bevel round the edge (lids too), a dome over the middle
    vec2 g = vec2(0.0);                   // (only the bevel needs the edge's direction)
    if (d > -16.0)
        g = normalize(vec2(eyeSDF(q + vec2(1.0, 0.0), e, la, lb, side) - d,
                           eyeSDF(q + vec2(0.0, 1.0), e, la, lb, side) - d) + 1e-6);
    c = lit(c, g, d, 16.0, q / b * 0.30);
    c = drawIris(q, c, pu);
    if (uBrowK.w > 0.01) {                // the brow's soft shadow, falling down onto it
        float db = browSDF(p - vec2(0.0, 9.0), side < 0.0 ? uBrow0 : uBrow1,
                           side < 0.0 ? uBrowK.x : uBrowK.y);
        c *= 1.0 - 0.30 * uBrowK.w * exp(-max(db, 0.0) / 9.0) * (1.0 - uMorph.x);
    }
    // the lids are things: a lowered upper lid has a lit edge, so has a
    // lower lid pushed up by the cheeks
    vec3 top = mix(uTop, uTint, uTintAmt);
    vec2 lt = lidTop(q.x, b, la, side);
    float dl = max(q.y - lt.x, 0.0) / sqrt(1.0 + lt.y * lt.y);
    float lidk = 1.0 - uMorph.x;
    c = mix(c, mix(top, uShine, 0.4), exp(-dl / 2.2) * smoothstep(0.03, 0.15, la.x) * 0.75 * lidk);
    vec2 lw = lidBot(q.x, b, la, lb);
    float du = max(lw.x - q.y, 0.0) / sqrt(1.0 + lw.y * lw.y);
    c = mix(c, top, exp(-du / 2.4) * smoothstep(0.03, 0.15, la.w) * 0.55 * lidk);
    if (uFx.x > 0.01) {                    // dizzy: a dark spiral turning in each eye
        float R = 0.92 * min(b.x, b.y);
        vec2 qs = q / vec2(1.15, 1.0);
        float r = length(qs);
        float pitch = R / 3.2;
        float f = r / pitch - (atan(qs.y, qs.x) * side + uFx.z * 7.0) / 6.2832;
        float dl2 = abs(fract(f) - 0.5) * pitch;
        float sp = smoothstep(4.5, 2.5, dl2) * smoothstep(R, R - 10.0, r) * uFx.x;
        c = mix(c, uPupilCol * 0.55, sp);
    }
    if (uFx.y > 0.01) {                    // lost signal: static, scanlines, a rolling bar
        vec2 cell = floor(vec2(q.x / 7.0, q.y / 3.0));
        float n = fract(sin(dot(cell + vec2(uFx.w, 0.37 * uFx.w), vec2(12.9898, 78.233))) * 43758.5453);
        vec3 st = mix(uPupilCol * 0.35, mix(uShine, uTop, 0.4), step(0.55, n) * n);
        float span = 2.0 * b.y + 30.0;
        float bar = exp(-sq((q.y + b.y + 15.0 - mod(uFx.z * 90.0, span)) / 7.0));
        st += uShine * 0.22 * bar;
        st *= 0.85 + 0.15 * step(0.5, fract(q.y / 4.0));
        c = mix(c, st, uFx.y);
    }
    // sad: a wet line along the bottom edge
    c += uShine * 0.45 * exp(d / 1.8) * smoothstep(0.2 * b.y, b.y, q.y) * uMorph.y;
    c *= (1.0 + 0.10 * uEnergy) * uDim;
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
    float d = browSDF(p, s, bend);
    if (uPass < 0.5) {
        glow += uGlow * 0.32 * exp(-max(d, 0.0) / 9.0) * uBrowK.w;
        return col;
    }
    float a = clamp(0.5 - d, 0.0, 1.0) * uBrowK.w;
    gA = a;
    vec2 g = normalize(vec2(browSDF(p + vec2(1.0, 0.0), s, bend) - d,
                            browSDF(p + vec2(0.0, 1.0), s, bend) - d) + 1e-6);
    vec3 c = mix(mix(uTop, uTint, uTintAmt * 0.8), mix(uBottom, uTint, uTintAmt * 0.6), 0.25);
    c = lit(c, g, d, uBrowK.z * 0.5, vec2(0.0));                 // a rounded tube
    return mix(col, c, a);
}

// the mouth's shape at q (from its centre): its SDF, and inside it the dark
// (inner < 0), the teeth and the tongue
float mouthSDF(vec2 q, out float inner, out float teeth, out float tongue) {
    float hw = uMouth.z * 0.5;
    float h = uMouth.w;
    float kind = uMouthK.w;
    float d;
    inner = 1e5;
    teeth = 0.0;
    tongue = 0.0;
    if (kind < 0.5) {                         // a line: smile / frown / slant
        float x = clamp(q.x / hw, -1.0, 1.0);
        vec2 pq = vec2(q.x, q.y - uMouthK.x * (1.0 - x * x));
        float taper = 0.70 + 0.30 * (1.0 - x * x);
        d = sdSeg(pq, vec2(-hw, uMouthSlant), vec2(hw, -uMouthSlant)) - h * 0.5 * taper;
    } else if (kind < 1.5) {                  // open, talking: a smiling lower lip
        float x = clamp(q.x / hw, -1.0, 1.0);
        vec2 b = vec2(hw, h * 0.5);
        // (the curve fades in below the middle — a hard step there showed as
        // a 1 px line across the open mouth)
        vec2 pq = vec2(q.x, q.y - max(uMouthK.x, 0.0) * 0.35 * (1.0 - x * x)
                                  * smoothstep(0.0, max(h * 0.5, 4.0), q.y));
        d = sdSquircle(pq, b, 2.6);
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
        float amp = 7.0, ph = 0.0;
        if (uWave > 0.0) {                    // a voice wave: still at its ends, moving
            float xn = x / hw;
            amp = uWave * (1.0 - xn * xn);
            ph = uTime * 9.0;
            k *= 1.6;
        }
        float y = amp * sin(x * k + ph);
        float sl = amp * k * cos(x * k + ph);
        d = length(vec2(q.x - x, (q.y - y) / sqrt(1.0 + sl * sl))) - h * 0.5;
    }
    return d;
}

float mouthD(vec2 q) {
    float i, t, g;
    return mouthSDF(q, i, t, g);
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
                                      + abs(uMouthSlant) + uWave + 6.0)) return col;
    float inner, teeth, tongue;
    float d = mouthSDF(q, inner, teeth, tongue);
    if (uPass < 0.5) {
        glow += mix(uGlow, uTint, uTintAmt) * 0.32 * exp(-max(d, 0.0) / 10.0) * alpha;
        return col;
    }
    float a = clamp(0.5 - d, 0.0, 1.0) * alpha;
    if (a <= 0.0) return col;
    gA = a;
    vec2 g = GRAD(mouthD, q, d);
    vec3 c = mix(mix(uTop, uTint, uTintAmt), mix(uBottom, uTint, uTintAmt), 0.35);
    c = mix(c, uMouthCol, uMouthColAmt);
    // the lips: a line is a rounded tube; an open mouth's rim rolls over
    c = lit(c, g, d, kind < 0.5 || kind > 4.5 ? h * 0.5 : 8.0, vec2(0.0));
    if (inner < 1e4) {                        // the dark inside: teeth, a tongue
        float ia = clamp(0.5 - inner, 0.0, 1.0);
        float v = clamp(q.y / max(h, 10.0) + 0.5, 0.0, 1.0);
        vec3 inside = vec3(0.06, 0.02, 0.010) + vec3(0.09, 0.03, 0.02) * (1.0 - v);
        inside *= 0.55 + 0.45 * smoothstep(-16.0, 0.0, inner);   // deeper toward the middle
        vec3 tg = vec3(0.86, 0.32, 0.30) * (0.70 + 0.45 * smoothstep(0.6, 0.2, v));
        inside = mix(inside, tg, tongue * 0.9);
        vec3 th = vec3(1.0, 0.95, 0.86) * (0.80 + 0.20 * smoothstep(1.0, 0.0, v));
        inside = mix(inside, th, teeth * 0.92);
        inside *= 1.0 - 0.45 * exp(inner / 5.0);                 // shadowed under the lips
        c = mix(c, inside, ia);
    }
    return mix(col, c, a);
}

// ── shadows and the floor ────────────────────────────────────────────────
// (the soft pass) Each feature floats a little in front of a dark surface:
// a contact shadow right under it, in its own shape, and a wider soft one;
// under the eyes, past the shadow, a faint warm reflection of the eye. The
// glow round a feature is what the shadow darkens — that is how it shows on
// a nearly black screen.
float eyeShadow(vec2 p, vec4 e, vec4 la, vec4 lb, float side) {
    if (e.w < 8.0) return 0.0;
    vec2 b = e.zw * 0.5;
    vec2 q = eyeLocal(p - vec2(0.0, 0.06 * e.w + 4.0), e, lb, side);
    float d = max(eyeSDF(q, e, la, lb, side), 0.0);
    float below = smoothstep(e.y - 0.2 * b.y, e.y + 0.9 * b.y, p.y);
    return (0.85 * exp(-d / 5.0) + 0.35 * exp(-d / 18.0)) * below;
}

vec3 eyeFloor(vec2 p, vec4 e, vec4 la, vec4 lb, float side) {
    float yf = e.y + e.w * 0.5 + 9.0;                  // the floor, just under the eye
    if (p.y < yf || e.w < 30.0 || uMorph.x > 0.5) return vec3(0.0);
    vec2 q = eyeLocal(vec2(p.x, 2.0 * yf - p.y), e, lb, side);
    float d = eyeSDF(q, e, la, lb, side);
    float k = smoothstep(6.0, -14.0, d) * exp(-(p.y - yf) / 30.0);
    return mix(uBottom, uTint, uTintAmt) * 0.34 * k;
}

float featureShadow(vec2 p) {
    float s = max(eyeShadow(p, uEye0, uLidA0, uLidB0, -1.0),
                  eyeShadow(p, uEye1, uLidA1, uLidB1, 1.0));
    if (uBrowK.w > 0.01) {
        vec2 o = vec2(0.0, 7.0);
        float d = max(min(browSDF(p - o, uBrow0, uBrowK.x), browSDF(p - o, uBrow1, uBrowK.y)), 0.0);
        s = max(s, (0.75 * exp(-d / 4.0) + 0.25 * exp(-d / 12.0)) * uBrowK.w);
    }
    if (uMouthK.z > 0.01) {
        float d = max(mouthD(p - uMouth.xy - vec2(0.0, 7.0)), 0.0);
        s = max(s, (0.75 * exp(-d / 4.0) + 0.25 * exp(-d / 12.0)) * uMouthK.z);
    }
    return s;
}

void main() {
    vec2 fc;
    if (uPass < 0.5) {
        fc = vec2(gl_FragCoord.x, uSoftRes.y - gl_FragCoord.y) * (uRes / uSoftRes);
    } else {
        fc = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);
        fc.x -= glitchShift(fc.y);
    }
    if (uPixel > 1.5 && uPass < 2.5)          // pixel art: one sample per block
        fc = (floor(fc / uPixel) + 0.5) * uPixel;
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
            float sh = featureShadow(p);
            col += glow * 0.55 * (1.0 - 0.9 * sh);
            col *= 1.0 - 0.6 * sh;
            col += (eyeFloor(p, uEye0, uLidA0, uLidB0, -1.0)
                    + eyeFloor(p, uEye1, uLidA1, uLidB1, 1.0)) * (1.0 - sh);
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
        if (uPixel > 1.5) {                   // …and a small palette
            vec3 s = c / max(gA, 0.001);      // (c is premultiplied)
            gA = step(0.5, gA);
            c = floor(s * 5.0 + 0.5) / 5.0 * gA;
        }
        gl_FragColor = vec4(c, gA);
    } else {
        vec4 l = vec4(0.0);
        if (uLayerSel < 0.5) {
            l = LAYER(texture2D(uLayer, uv));
        } else {
            vec2 lu = p / uRes;
            if (lu.x >= 0.0 && lu.x <= 1.0 && lu.y >= 0.0 && lu.y <= 1.0)
                l = LAYER((uLayerSel < 1.5) ? texture2D(uFaceLayer, lu) : texture2D(uBackLayer, lu));
        }
        gl_FragColor = vec4(l.rgb * l.a, l.a);
    }
}
"""

# passes 1 and 3 on their own: the same lines as in _FRAG, without the face's
# big shader around them (in it the stretch alone took ~5 ms of the GPU, as a
# shader of its own well under one; 19 Oct, Pi 4)
_FRAG_FLAT = """
uniform vec2  uRes;
uniform float uTime;
uniform float uTilt;
uniform vec2  uGlitch;
uniform float uLayerSel;
uniform sampler2D uSoft;
uniform sampler2D uLayer;
uniform sampler2D uFaceLayer;
uniform sampler2D uBackLayer;

""" + _FRAG[_FRAG.index("float hash(vec2 p)"):_FRAG.index("// ── the light")] + """
void main() {
    vec2 fc = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);
    fc.x -= glitchShift(fc.y);
    vec2 uv = fc / uRes;
#ifdef STRETCH
    vec3 col = texture2D(uSoft, vec2(uv.x, 1.0 - uv.y)).rgb;   // (drawn bottom row first)
    col += (hash(fc + fract(uTime)) - 0.5) / 255.0;            // dither: no banding
    gl_FragColor = vec4(col, 1.0);
#else
    vec2 c0 = uRes * 0.5;
    vec2 dv = fc - c0;
    float cs = cos(uTilt), sn = sin(uTilt);
    vec2 p = c0 + vec2(cs * dv.x - sn * dv.y, sn * dv.x + cs * dv.y);
    vec4 l = vec4(0.0);
    if (uLayerSel < 0.5) {
        l = LAYER(texture2D(uLayer, uv));
    } else {
        vec2 lu = p / uRes;
        if (lu.x >= 0.0 && lu.x <= 1.0 && lu.y >= 0.0 && lu.y <= 1.0)
            l = LAYER((uLayerSel < 1.5) ? texture2D(uFaceLayer, lu) : texture2D(uBackLayer, lu));
    }
    gl_FragColor = vec4(l.rgb * l.a, l.a);
#endif
}
"""


class _Prog:
    """A small program's id, its uniforms' locations and the values they hold."""

    def __init__(self, GL, pid):
        self.GL, self.id, self.loc, self.set = GL, pid, {}, {}

    def u(self, name, value):
        GL = self.GL
        loc = self.loc.get(name)
        if loc is None:
            loc = self.loc[name] = GL.glGetUniformLocation(self.id, name)
        if loc < 0:
            return
        v = float(value) if isinstance(value, (int, float)) else tuple(map(float, value))
        if self.set.get(loc) == v:
            return
        self.set[loc] = v
        if isinstance(v, float):
            GL.glUniform1f(loc, v)
        elif len(v) == 2:
            GL.glUniform2f(loc, *v)
        elif len(v) == 3:
            GL.glUniform3f(loc, *v)
        else:
            GL.glUniform4f(loc, *v)

    def unit(self, name, unit):
        loc = self.GL.glGetUniformLocation(self.id, name)
        if loc >= 0:
            self.GL.glUniform1i(loc, unit)


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
        self.h = height
        self.sent = [None] * len(self.bands)      # the band's pixels on the texture
        self.zero = {h: bytes(width * 4 * h) for _, h in self.bands}

    def runs(self, pad=0):
        """(y0, y1) of the runs of bands with something on them, each widened
        by pad rows (a turned layer reaches past its own rows)."""
        out = []
        for (y, h), data in zip(self.bands, self.sent):
            if data is None:
                continue
            y0, y1 = max(0, y - pad), min(self.h, y + h + pad)
            if out and out[-1][1] >= y0:
                out[-1] = (out[-1][0], y1)
            else:
                out.append((y0, y1))
        return out


_np = []


def _numpy():
    """numpy, or None where it isn't installed (loaded once, when needed)."""
    if not _np:
        try:
            import numpy
            _np.append(numpy)
        except ImportError:
            _np.append(None)
    return _np[0]


# the layers' memory is pygame's own (B, G, R, A on a little-endian Pi): its
# blits take their fast paths there — an image blitted into an R, G, B, A
# layer went the slow generic way, 1.7 ms for a sound wave instead of 0.06.
# GL takes the bytes as they are (as RGBA: Mesa swapping them on the CPU was
# 26 ms a layer) and the shader swaps them back (LAYER).
_SWAP = sys.byteorder == "little"
_LAYER_MASKS = (0xFF0000, 0xFF00, 0xFF, 0xFF000000)
_LAYER_DEF = "#define LAYER(c) (c).bgra\n" if _SWAP else "#define LAYER(c) (c)\n"


def layer_surface(width, height):
    """A transparent pygame surface laid out the way the layers' textures
    take it as it is (_SWAP)."""
    import pygame
    if _SWAP:
        return pygame.Surface((width, height), pygame.SRCALPHA, 32, masks=_LAYER_MASKS)
    return pygame.Surface((width, height), pygame.SRCALPHA, 32,
                          masks=(0xFF000000, 0xFF0000, 0xFF00, 0xFF))


def _gl_format(GL, surface):
    """GL_RGBA when a 32-bit pygame surface's own memory is what the layers'
    textures hold (layer_surface), or None: convert it (or its rows are padded)."""
    if surface.get_bytesize() != 4 or surface.get_pitch() != surface.get_width() * 4:
        return None
    masks = tuple(surface.get_masks())
    if masks == (_LAYER_MASKS if _SWAP else (0xFF000000, 0xFF0000, 0xFF00, 0xFF)):
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


class _Life:
    """The small things that keep the eyes alive between expressions:
    micro-saccades (tiny quick jumps of the gaze), a brow flicking up now and
    then, the right eye a frame behind the left when she blinks. Real time,
    not frames."""

    def __init__(self):
        self.sacc = (0.0, 0.0)            # where the jump goes
        self.sacc_now = [0.0, 0.0]        # …and where the eyes are on the way
        self.sacc_t = 0.0                 # the next jump
        self.sacc_v = [0.0, 0.0]
        self.flick = None                 # (side, start) — one brow up a moment
        self.flick_t = time.monotonic() + random.uniform(15, 35)
        self.shut_prev = 0.0
        self.seen = False                 # someone in view (last frame)
        self.seen_t = -9.0                # …since when: the pupils open on seeing them
        self.mood = None
        self.pop_t = -9.0                 # a new mood: the eyes pop a little
        self.emph_t = -9.0                # a stressed syllable: the brows lift
        self.lids = []                    # (start, dur, depth): half blinks, slow blinks…
        self.half_t = time.monotonic() + random.uniform(8, 20)
        self.cat_t = 0.0                  # love: the next slow blink
        self.talk = False                 # talking (last frame)
        self.press_t = -9.0               # the end of a sentence: the lips press
        self.away_t = 0.0                 # talking: the next glance away…
        self.away = (-9.0, 1.0)           # …(start, side)
        self.up_t = 0.0                   # sad: the next glance up…
        self.up_at = -9.0
        self.yawned = False               # one yawn as she gets drowsy
        self.yawn_t = -99.0
        self.mumble_t = time.monotonic() + random.uniform(8, 15)
        self.mumble_at = -9.0
        self.smirk_t = 0.0                # happy: now and then a lopsided smile
        self.smirk = (-9.0, 1.0)
        self.near = 0.0                   # how close the person is (eased, 0..1)
        self.listen = 0.0                 # listening (eased) — one brow cocked
        self.cock = 0                     # …which one
        self.flash_t = -9.0               # someone appears: an eyebrow flash
        self.contact = 0.0                # since when someone's been in view
        self.shy_t, self.shy_next, self.shy_side = -9.0, 0.0, 1.0
        self.lost = (-9.0, 0.0, 0.0)      # they left: (when, where the eyes were)
        self.last_look = (0.0, 0.0)
        self.aha_t = -9.0                 # done thinking: "aha!"
        self.sigh_t, self.sigh_next = -9.0, time.monotonic() + random.uniform(25, 45)
        self.hmm_t, self.hmm_next = -9.0, 0.0     # thinking: a "hmm" purse of the lips
        self.rem_t = time.monotonic() + random.uniform(20, 40)   # asleep: dreaming
        self.closed_at = -9.0             # the last blink: a fresh wet glint after
        self.touched = 0.0                # the last touch we reacted to
        self.taps = []                    # recent taps: three quick ones tickle
        self.giggle_t = -9.0
        self.boop_t = -9.0                # a tap on the nose: cross-eyed
        self.boing = (-9.0, 0)            # a tapped eye squashes and springs back
        self.mood_t = time.monotonic()    # since when this mood
        self.dream_t = time.monotonic() + random.uniform(40, 80)   # asleep: a smile
        self.waking = False

    def lid(self, now, i=-1):
        """The extra lid moves on top of the blinks: quick to close, slower
        to open (0 open … 1 shut). An entry's 4th item, if any, is the one
        eye it shuts (0 left, 1 right)."""
        v = 0.0
        for b in self.lids:
            if len(b) > 3 and i >= 0 and b[3] != i:
                continue
            el = (now - b[0]) / b[1]
            if 0.0 <= el < 1.0:
                c = el / 0.3 if el < 0.3 else 1.0 - (el - 0.3) / 0.7
                v = max(v, b[2] * c * c * (3.0 - 2.0 * c))
        return v

    def prune(self, now):
        self.lids = [b for b in self.lids if now - b[0] < b[1]]

    def yawn(self, now):
        """0 → 1 → 0 over a yawn's 2.8 s: slow to open, a hold, a close."""
        el = (now - self.yawn_t) / 2.8
        if not 0.0 <= el < 1.0:
            return 0.0
        c = min(1.0, el / 0.45, (1.0 - el) / 0.3)
        return c * c * (3.0 - 2.0 * c)

    def moods(self, now, emo, talking, drowsy, listening):
        """The timed habits of each mood."""
        if talking and not self.talk:
            if random.random() < 0.6:            # a blink as she starts to speak
                self.lids.append((now, 0.22, 1.0))
            self.away_t = now + random.uniform(3.0, 6.0)
        if self.talk and not talking:
            self.press_t = now                   # …and the lips press as she ends
        self.talk = talking
        if talking and now > self.away_t:        # a glance aside, composing a thought
            self.away = (now, random.choice((-1.0, 1.0)))
            self.away_t = now + random.uniform(4.0, 7.0)
        calm = emo in ("neutral", "listening", "happy") and not talking
        if now > self.half_t:                    # a lazy half blink
            self.half_t = now + random.uniform(8, 20)
            if calm:
                self.lids.append((now, 0.5, 0.45))
        if emo == "love" and now > self.cat_t:   # love: a slow, soft blink
            self.cat_t = now + random.uniform(5, 9)
            self.lids.append((now, 1.2, 0.85))
        if emo == "sad" and now > self.up_t:     # sad: a glance up at you, then down
            self.up_t = now + random.uniform(5, 9)
            self.up_at = now
        if emo == "happy" and not talking and now > self.smirk_t:
            self.smirk_t = now + random.uniform(6, 12)
            self.smirk = (now, random.choice((-1.0, 1.0)))
        if emo == "sleeping" and now > self.dream_t + 3.0:   # a sweet dream: a smile
            self.dream_t = now + random.uniform(40, 80)
        if emo == "sleeping" and now > self.mumble_t:   # mumbling in her sleep
            self.mumble_t = now + random.uniform(8, 15)
            self.mumble_at = now
        if drowsy > 0.35 and not self.yawned and not talking:
            self.yawned, self.yawn_t = True, now
        elif drowsy <= 0.0 and now - self.yawn_t > 3.0:
            self.yawned = False
        if listening and self.listen < 0.05:
            self.cock = random.choice((0, 1))
            self.flash_t = now                    # her name: brows up, she's listening
        if emo == "thinking" and now > self.hmm_next:
            self.hmm_next = now + random.uniform(4, 7)
            self.hmm_t = now
        self.prune(now)

    def step(self, now, dt, calm, steady=False, jitter=False):
        if now > self.sacc_t:
            amp = 0.45 if steady else 1.0  # eye contact: steadier
            self.sacc = (random.uniform(-5.0, 5.0) * amp, random.uniform(-3.5, 3.5) * amp)
            # excited: the eyes dart about
            self.sacc_t = now + (random.uniform(0.15, 0.5) if jitter
                                 else random.uniform(0.5, 2.2))
        # a stiff spring: fast, a hair of overshoot — in 4 ms steps (one
        # step per frame blew up at 20 fps: 30/s × 50 ms is past stable)
        n = max(1, min(60, int(math.ceil(min(dt, 0.25) / 0.004))))
        h = min(dt, 0.25) / n
        for _ in range(n):
            for j in (0, 1):
                self.sacc_v[j] += ((self.sacc[j] - self.sacc_now[j]) * 900.0
                                   - self.sacc_v[j] * 42.0) * h
                self.sacc_now[j] += self.sacc_v[j] * h
        if now > self.flick_t:
            self.flick_t = now + random.uniform(15, 40)
            if calm:
                self.flick = (random.choice((0, 1)), now)

    @staticmethod
    def bump(now, t0, dur):
        """0 → 1 → 0 over dur seconds after t0."""
        el = now - t0
        return math.sin(math.pi * el / dur) if 0.0 <= el < dur else 0.0

    def brow_flick(self, i, now):
        if not self.flick or self.flick[0] != i:
            return 0.0
        el = now - self.flick[1]
        return 12.0 * math.sin(math.pi * el / 0.7) if 0.0 <= el < 0.7 else 0.0


# …and a costume's own face settings (face_spec's keys)
COSTUME_SPEC = {
    "googly_eyes": {"round": 1.0, "heart": 0.0, "star": 0.0, "brow_a": 0.0,
                    "lid_top": (0.0, 0.0), "lid_tilt": (0.0, 0.0), "lid_bot": (0.0, 0.0),
                    "lid_bot_bend": (0.0, 0.0), "gaze_x": 0.0, "gaze_y": 0.0},
}


def theme_spec(target, theme):
    """A theme's face settings over the mood's: some set ("spec"), some added
    ("spec_add": HAL's round lens; the doctor's bored half-closed lids)."""
    target.update(theme.get("spec") or {})
    for k, add in (theme.get("spec_add") or {}).items():
        top = 1.0 if k.startswith("lid_") else float("inf")      # (a lid shuts, no more)
        v = target[k]
        target[k] = (tuple(min(top, a + b) for a, b in zip(v, add)) if isinstance(v, tuple)
                     else min(top, v + add))
    return target


def _rgb(c):
    return tuple(v / 255.0 for v in c[:3])


def _lerp_col(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


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
                self.prog = self._program(head + _VERT, head + _LAYER_DEF + _FRAG)
                self.glsl = head.split()[1]
                break
            except RuntimeError as e:
                errors.append(str(e))
        if self.prog is None:
            raise RuntimeError("shader did not compile: " + " | ".join(errors))
        # the stretch and the layers: small shaders of their own
        head += _LAYER_DEF
        self.p_stretch = _Prog(GL, self._program(head + _VERT, head + "#define STRETCH\n" + _FRAG_FLAT))
        self.p_layer = _Prog(GL, self._program(head + _VERT, head + _FRAG_FLAT))
        for p in (self.p_stretch, self.p_layer):
            GL.glUseProgram(p.id)
            p.u("uRes", (width, height))
            for name, unit in (("uLayer", 0), ("uSoft", 1), ("uFaceLayer", 2), ("uBackLayer", 3)):
                p.unit(name, unit)
        GL.glUseProgram(self.prog)
        self._loc = {}
        self._set = {}                   # uniform location → the value it holds
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
        self.life = _Life()
        self._t_last = 0.0
        self.shape_rects = []            # each shape's box on the screen (face_uniforms)
        self.vis = None                  # the radio visualizer's pass (gl_vis.py), when needed
        self.lamp = None                 # the lamp's scenes (gl_lamp.py), when needed
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
        """Set a uniform of the face's program, skipped when it holds that
        value already (a PyOpenGL call is ~20 µs, and most stay put)."""
        GL = self.GL
        loc = self._loc.get(name)
        if loc is None:
            loc = self._loc[name] = GL.glGetUniformLocation(self.prog, name)
        if loc < 0:
            return
        v = float(value) if isinstance(value, (int, float)) else tuple(map(float, value))
        if self._set.get(loc) == v:
            return
        self._set[loc] = v
        if isinstance(v, float):
            GL.glUniform1f(loc, v)
        elif len(v) == 2:
            GL.glUniform2f(loc, *v)
        elif len(v) == 3:
            GL.glUniform3f(loc, *v)
        else:
            GL.glUniform4f(loc, *v)

    def upload(self, layer, surface):
        """A pygame layer (SRCALPHA, the screen's size) → its texture: its
        memory read as it is (no conversion), and only the 32-row bands whose
        bytes changed are sent — the status bar is redrawn every frame but
        changes once a minute. (Finding the drawn area with
        get_bounding_rect() cost 3 ms for the screen, 8 ms band by band —
        more than sending it all; 13 Oct, Pi 4.) True when anything is on it."""
        GL = self.GL
        fmt = _gl_format(GL, surface)
        np = _numpy()
        if fmt is not None and np is not None:
            return self._upload_np(np, layer, surface, fmt)
        return self._upload_bytes(layer, surface, fmt)

    def _upload_bytes(self, layer, surface, fmt):
        """upload() without numpy (or for a surface laid out differently)."""
        GL = self.GL
        if fmt is None:                          # an unusual layout: convert it
            import pygame
            raw, fmt = pygame.image.tobytes(surface, "BGRA" if _SWAP else "RGBA"), GL.GL_RGBA
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

    def _upload_np(self, np, layer, surface, fmt):
        """upload() reading the surface's memory in place, 8 bytes at a time:
        the empty and unchanged bands are found at memory speed (the bytes
        copies of the whole layer cost 2-3 ms each; 19 Oct, Pi 4)."""
        GL = self.GL
        view = surface.get_view("1")
        cur = chunk = None
        try:
            cur = np.frombuffer(view, dtype=np.uint64)
            row = layer.w // 2                       # (uint64s in a row)
            if all(h == layer.BAND for _, h in layer.bands) and cur.size == layer.h * row:
                # (max of uint32s: 3x faster than any() on the Pi)
                lit = cur.view(np.uint32).reshape(len(layer.bands), -1).max(axis=1).tolist()
            else:
                lit = [bool(cur[y * row:(y + h) * row].any()) for y, h in layer.bands]
            any_ = bound = False
            for i, (y, h) in enumerate(layer.bands):
                prev = layer.sent[i]
                if lit[i]:
                    any_ = True
                    chunk = cur[y * row:(y + h) * row]
                    if prev is not None and np.array_equal(chunk, prev):
                        continue                     # the same pixels are there already
                    data = chunk.copy()
                    sent = data.view(np.uint8)       # (PyOpenGL would cast uint64s)
                elif prev is None:
                    continue                         # (clear there already)
                else:
                    data = sent = layer.zero[h]
                if not bound:
                    GL.glBindTexture(GL.GL_TEXTURE_2D, layer.tex)
                    bound = True
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, y, layer.w, h, fmt,
                                   GL.GL_UNSIGNED_BYTE, sent)
                self.uploaded += layer.w * 4 * h
                layer.sent[i] = data if lit[i] else None
            return any_
        finally:
            del cur, chunk, view                     # (the view locks the surface)

    def clear(self, layer, surface):
        """Clear a layer's surface where its texture has something — the
        rows the last upload found drawn on (three full-screen fills were
        ~2 ms a frame; 19 Oct, Pi 4)."""
        for y0, y1 in layer.runs():
            surface.fill((0, 0, 0, 0), (0, y0, layer.w, y1 - y0))

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
        if self._set.get(loc) != ("unit", unit):
            self._set[loc] = ("unit", unit)
            GL.glUniform1i(loc, unit)

    def _bind_quad(self):
        GL = self.GL
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glEnableVertexAttribArray(self.apos)
        GL.glVertexAttribPointer(self.apos, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)

    def _quad(self):
        self._bind_quad()
        self.GL.glDrawArrays(self.GL.GL_TRIANGLE_STRIP, 0, 4)

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
            if k[0] != "_":
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
        flat = [(k, uniforms[k]) for k in ("uTime", "uTilt", "uGlitch") if k in uniforms]
        ps, pl = self.p_stretch, self.p_layer
        GL.glUseProgram(ps.id)
        for k, v in flat:
            ps.u(k, v)
        ps.u("uRect", full)
        self._bind_quad()
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)    # premultiplied
        if uniforms.get("_vis"):             # the radio's picture (gl_vis.py), behind it all
            if self.vis is None:
                import gl_vis
                self.vis = gl_vis.VisPass(self)
            self.vis.draw(uniforms["_vis"], uniforms.get("uBlush", (self.w / 2, self.h / 2))[:2])
            self._bind_quad()                # (its own buffer was bound)
        # the turned layers reach this many rows past their own
        t = abs(float(uniforms.get("uTilt", 0.0)))
        pad = int(math.sin(min(t, 1.5)) * self.w / 2 + (1 - math.cos(t)) * self.h / 2) + 2
        GL.glUseProgram(pl.id)
        for k, v in flat:
            pl.u(k, v)
        if has_back:                         # behind the face: costume ears, steam…
            pl.u("uLayerSel", 2.0)
            self._rows(pl, self.back_l.runs(pad))
        # 2: the sharp shapes, each in its own box
        if uniforms.get("uFace", 0.0) > 0.5:
            GL.glUseProgram(self.prog)
            self._u("uPass", 2.0)
            for i, rect in enumerate(self.shape_rects):
                if rect is None:
                    continue
                self._u("uShape", float(i))
                self._u("uRect", rect)
                GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            GL.glUseProgram(pl.id)
        # 3: the pygame layers — the face's (turned) and the screen's, by
        # rows: only where something is (a full-screen pass of the face's
        # layer was ~1.5 ms of the GPU's frame with a dot on it)
        if has_face:
            pl.u("uLayerSel", 1.0)
            self._rows(pl, self.face_l.runs(pad))
        if has_layer:
            pl.u("uLayerSel", 0.0)
            self._rows(pl, self.screen_l.runs())
        GL.glUseProgram(self.prog)
        GL.glDisable(GL.GL_BLEND)

    def _rows(self, prog, runs):
        """The layer pass over these (y0, y1) rows (the quad is bound;
        prog: the layer's program, or None for the face's own)."""
        GL = self.GL
        set_u = prog.u if prog else self._u
        for y0, y1 in runs:
            set_u("uRect", (0.0, float(y0), float(self.w), float(y1)))
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

    def render_lamp(self, lamp, screen_layer=None):
        """The lamp's scene (gl_lamp.py) alone over the whole screen — no
        face under it — and the screen layer (the clock's digits) on top."""
        GL = self.GL
        has_layer = screen_layer is not None and self.upload(self.screen_l, screen_layer)
        if self.lamp is None:
            import gl_lamp
            self.lamp = gl_lamp.LampPass(self)
        self.lamp.draw(lamp)
        self._t_last = 0.0                   # (the face's easing: no jump when it is back)
        if has_layer:
            GL.glUseProgram(self.prog)
            self._u("uRes", (self.w, self.h))
            self._sampler("uLayer", 0, self.screen_l.tex)
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
            self._u("uPass", 3.0)
            self._u("uLayerSel", 0.0)
            self._bind_quad()
            self._rows(None, self.screen_l.runs())
            GL.glDisable(GL.GL_BLEND)
        GL.glUseProgram(self.prog)

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
        px = u.get("uPixel", 0.0)               # (a block may reach past the shape)
        boxes = []
        if u["uGlitch"][0] > 0.5:                  # torn sideways: anywhere in the rows
            return [(0.0, 0.0, float(self.w), float(self.h))] * 5
        for i in (0, 1):
            ex, ey, w, h = u[f"uEye{i}"]
            boxes.append(self._box(ex, ey, w / 2 + 8 + px, h / 2 + 8 + px, tilt))
        bend0, bend1, thick, alpha = u["uBrowK"]
        for i, bend in ((0, bend0), (1, bend1)):
            x0, y0, x1, y1 = u[f"uBrow{i}"]
            if alpha <= 0.01:
                boxes.append(None)
                continue
            pad = thick + abs(bend) + 2 + px
            boxes.append(self._box((x0 + x1) / 2, (y0 + y1) / 2,
                                   abs(x1 - x0) / 2 + thick + px, abs(y1 - y0) / 2 + pad, tilt))
        mx, my, w, h = u["uMouth"]
        bend, open_, alpha, kind = u["uMouthK"]
        if alpha <= 0.01:
            boxes.append(None)
        else:
            hx = w / 2 + h / 2 + 8 + px
            hy = (max(h, w) / 2 + h + abs(bend) + abs(u["uMouthSlant"]) + 10 + px)
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
        theme = themes.get()                      # Doktor Lód's ice cubes, HAL's lens
        theme_spec(target, theme)
        googly = costume == "googly_eyes"
        if googly:                                # big round googly eyes, nothing else
            target.update(COSTUME_SPEC["googly_eyes"])
        cur = self.eased.step(target, dt)
        life = getattr(self, "life", None) or _Life()
        self.life = life
        talking = face._speaking
        calm = emo in ("neutral", "listening") and not talking
        seen = bool(getattr(face, "_face_seen", False))
        if seen and not life.seen:
            life.seen_t = now                     # someone came into view
        life.seen = seen
        pop_k = 0.06
        if emo != life.mood:
            life.mood_t = now
            if life.mood is not None and emo != "sleeping":
                life.pop_t = now
                if life.mood == "thinking":       # got it: "aha!"
                    life.aha_t = now
                if emo == "surprised":            # a take: squeeze shut, then pop wide
                    life.lids.append((now, 0.18, 0.9))
                    life.pop_t = now + 0.12
            life.mood = emo
        if emo == "surprised":
            pop_k = 0.12
        life.step(now, dt, calm, steady=seen and talking, jitter=emo == "excited")
        drowsy = getattr(face, "_drowsy", 0.0)
        life.moods(now, emo, talking, drowsy, face._listen)
        k6 = 1.0 - math.exp(-6.0 * dt)
        st = getattr(rf, "state", None)          # close up: the eyes cross a touch
        fw = getattr(st, "face_w", 0.0) if seen and st is not None else 0.0
        life.near += (max(0.0, min(1.0, (fw - 0.25) / 0.25)) - life.near) * k6
        life.listen += ((1.0 if face._listen and not talking else 0.0) - life.listen) * k6
        if seen and life.contact <= 0.0:          # someone appears: brows flash up
            life.contact = now
            life.flash_t = now
        elif not seen and life.contact > 0.0:     # they left: keep looking where they were
            life.contact = 0.0
            life.lost = (now, *life.last_look)
        glow_on = getattr(face, "awake_glow", 0.0)
        if (seen and not talking and glow_on < 0.3 and emo in ("neutral", "happy")
                and now - life.contact > 12.0 and now > life.shy_next):
            life.shy_t, life.shy_next = now, now + 40.0   # looked at a long while: shy
            life.shy_side = random.choice((-1.0, 1.0))
        if (not seen and not talking and glow_on < 0.3 and emo == "neutral"
                and drowsy <= 0.0 and now > life.sigh_next):
            life.sigh_t, life.sigh_next = now, now + random.uniform(25, 45)   # alone: a sigh
        if emo == "sleeping" and now > life.rem_t + 3.0:
            life.rem_t = now + random.uniform(20, 40)
        rem = 1.0 if emo == "sleeping" and life.rem_t <= now else 0.0
        shy = life.bump(now, life.shy_t, 2.5)
        sigh = life.bump(now, life.sigh_t, 1.8)
        flash = life.bump(now, life.flash_t, 0.45)
        aha = life.bump(now, life.aha_t, 0.5)
        lost = max(0.0, min(1.0, 2.5 - (now - life.lost[0]))) if not seen else 0.0
        # a touch: the eyes glance at it; a tap on an eye shuts that one;
        # a stroke half closes them, contented; a poke shakes them
        tkind = getattr(face, "_touch_kind", None)
        tel = time.time() - getattr(face, "_touch_react_t", -99.0)
        tpt = getattr(face, "_touch_pt", None)
        if tpt and getattr(face, "_touch_react_t", 0.0) != life.touched:
            life.touched = face._touch_react_t
            if tkind == "tap":
                life.taps = [t for t in life.taps if now - t < 2.0] + [now]
                if len(life.taps) >= 3:           # tap-tap-tap: that tickles
                    life.giggle_t, life.taps = now, []
            if getattr(face, "_touch_zone", None) == "eye" and tkind == "tap":
                near_eye = 0 if tpt[0] < fcx else 1
                life.lids.append((now, 0.35, 1.0, near_eye))
                life.boing = (now, near_eye)
            elif (tkind == "tap" and abs(tpt[0] - fcx) < 70
                  and abs(tpt[1] - fcy - face_spec.LAYOUT["nose_y"]) < 55):
                life.boop_t = now                 # boop! on the nose
        # (not a tap on an eye itself: that eye just flinches)
        glance = (min(1.0, tel / 0.15) * max(0.0, min(1.0, (1.4 - tel) / 0.4))
                  if tpt and tkind in ("tap", "stroke") and tel >= 0.0
                  and getattr(face, "_touch_zone", None) != "eye" else 0.0)
        content = (max(0.0, min(1.0, tel / 0.3, (2.5 - tel) / 0.6))
                   if tkind == "stroke" and tel >= 0.0 else 0.0)
        poke = (max(0.0, 1.0 - tel / 0.5) if tkind == "multi" and tel >= 0.0 else 0.0)
        boop = life.bump(now, life.boop_t, 0.7)
        giggle = life.bump(now, life.giggle_t, 1.3)
        # a gesture: she glances at her own raised hand
        hand_look = None
        gest, gp = getattr(face, "_gesture", None), getattr(face, "_gesture_p", 0.0)
        hands = getattr(face, "hand", None)
        if gest in ("wave", "thumbs_up", "heart") and hands and gp < 0.55:
            hx, hy, _ = min(hands.values(), key=lambda v: v[1])
            if hy < 300:
                hand_look = (fcx + hx, fcy + hy,
                             min(1.0, gp / 0.1) * max(0.0, min(1.0, (0.55 - gp) / 0.15)))
        # a photo's flash: dazzled for a moment
        dazzle = max(0.0, 1.0 - (time.time() - getattr(face, "_flash_t", -99.0)) / 1.8)
        # waking: a quick double blink once the eyes are open
        if getattr(face, "wake_anim", 0) and not life.waking:
            life.waking = True
            life.lids += [(now + 0.6, 0.2, 1.0), (now + 0.9, 0.2, 1.0)]
        elif not getattr(face, "wake_anim", 0):
            life.waking = False
        beatv = (max(0.0, math.sin(now * math.tau * 1.15)) ** 4) * cur["heart"]
        # after a blink: a fresh wet glint
        glint = life.bump(now, life.closed_at + 0.12, 0.7)
        hour = time.localtime().tm_hour
        night = 1.0 if (hour >= 22 or hour < 6) else 0.0     # late: softer, warmer eyes
        yawn = life.yawn(now)
        away = life.bump(now, life.away[0], 0.9)
        up = life.bump(now, life.up_at, 1.4)
        pop = pop_k * life.bump(now, life.pop_t, 0.35)
        emph = life.bump(now, life.emph_t, 0.28)
        breath = math.sin(getattr(face, "breath_phase", 0.0))
        voice = getattr(face, "_audio_energy", 0.0) if talking else 0.0
        u = {"uTime": (face.breath_phase if hasattr(face, "breath_phase") else 0.0),
             "uTilt": math.radians(face.head_angle),
             "uFace": 1.0 if rf.EYE_MODE == "block" else 0.0,
             "uTop": _rgb(rf.EYE_GRAD_TOP), "uBottom": _rgb(rf.EYE_GRAD_BOTTOM),
             "uGlow": _rgb(_lerp_col(_lerp_col(rf.GLOW_COL, (90, 150, 255), 0.30 * cur["wet"]),
                                     (255, 160, 120), 0.22 * min(1.0, cur["blush"]) + 0.15 * night)),
             "uShine": _rgb(rf.IRIS_SHINE),
             "uPupilCol": _rgb(rf.PUPIL_DARK),
             "uIrisCol": _rgb(getattr(rf, "IRIS_COL", (120, 52, 10))),
             "uBlushCol": _rgb(rf.BLUSH_COL),
             "uHeartTop": (1.0, 0.62, 0.70), "uHeartBottom": (0.90, 0.16, 0.38),
             # her voice lights the eyes up a little
             "uEnergy": min(1.0, max(0.0, voice)),
             # warm moods warm the pupils' rims; asleep, the eyes dim
             "uWarm": min(1.0, cur["blush"] * 1.2),
             "uDim": (0.70 - 0.12 * max(0.0, min(1.0, (now - life.mood_t - 300.0) / 300.0))
                      if emo == "sleeping" else 1.0) * (1.0 - 0.12 * night)}
        if cur["tint"] > 0.3:                     # angry: the glow flickers like heat
            fl = 1.0 + 0.12 * math.sin(now * 13.0) * math.sin(now * 7.3)
            u["uGlow"] = tuple(min(1.0, c * fl) for c in u["uGlow"])
        tint = face._eye_color
        amt = 0.45 if tint else 0.0
        heat = cur["tint"] + 0.45 * face.angry_pulse          # angry: red, and pulsing
        if heat > 0.01:
            tint = rf.ANGRY_COL if not tint else tint
            amt = max(amt, heat)
        u["uTint"] = _rgb(tint or rf.EYE_GRAD_TOP)
        u["uTintAmt"] = min(0.85, amt)
        u["uMorph"] = (cur["heart"], max(cur["wet"], 0.35 * glint, 4.0 * pop),
                       cur["round"], cur["star"])
        fx = getattr(face, "_eye_fx", None) or (0.0, 0.0)
        u["uFx"] = (fx[0], fx[1], now % 1000.0, float(int(now * 20.0) % 997))
        u.update(uPixel=0.0, uMouthCol=(0.0, 0.0, 0.0), uMouthColAmt=0.0)
        u.update(theme.get("eyes") or {})
        look = COSTUME_EYES.get(costume)
        if look:                                  # a costume's own eyes (googly, robot…)
            u.update(look)
        conv = getattr(face, "_pupil_converge", 0.0)
        brows = []
        asleep = emo == "sleeping"
        for i, (eye, side) in enumerate(((face.left_eye, -1), (face.right_eye, 1))):
            cx, cy = fcx + eye.rel_x, fcy + eye.rel_y + cur["eye_dy"]
            if asleep:                            # the shut eyes rise and fall with her breath
                cy += 3.0 * breath
            w = min(float(eye.w), rf.EYE_SPREAD * 2 - 44)
            h = eye.h * (1.0 + 0.15 * eye.widen)
            w, h = w * (1.0 + 0.008 * breath), h * (1.0 + 0.008 * breath)   # breathing
            w, h = w * (1.0 + pop), h * (1.0 + pop)                        # a new mood: pop
            w, h = w * (1.0 + 0.05 * aha), h * (1.0 + 0.07 * aha)          # aha: wide
            if life.boing[1] == i and 0.0 <= now - life.boing[0] < 0.7:    # tapped: boing
                el = now - life.boing[0]
                sb = math.exp(-el * 7.0) * math.sin(el * 30.0)
                w, h = w * (1.0 + 0.10 * sb), h * (1.0 - 0.16 * sb)
            if cur["heart"] > 0.5:                # hearts beat (~70 a minute)
                beat = 0.05 * max(0.0, math.sin(now * math.tau * 1.15)) ** 4
                w, h = w * (1.0 + beat), h * (1.0 + beat)
            stretch = 0.06 * abs(math.sin(getattr(face, "bounce_phase", 0.0))) * min(
                1.0, getattr(face, "bounce_amp", 0.0) / 22.0)
            w, h = w * (1.0 - 0.5 * stretch), h * (1.0 + stretch)          # squash & stretch
            if getattr(face, "wake_anim", 0):     # waking: a big stretch
                wk = 0.10 * math.sin(math.pi * max(0.0, min(1.0, getattr(face, "wake_ripple", 1.0))))
                w, h = w * (1.0 - 0.4 * wk), h * (1.0 + wk)
            if googly or theme.get("circle"):
                w = h = min(w, eye.h * 1.3)
            # the eye leans a little toward where she looks; the iris does the rest
            ex, ey = cx + eye.pupil_ox * 0.30, cy + eye.pupil_oy * 0.30
            if cur["tint"] > 0.3:                 # angry: a faint tremble
                ex += 0.9 * math.sin(now * 47.0 + i)
            ex += 7.0 * poke * math.sin(now * 60.0)   # poked: a shake
            if emo == "excited":                  # excited: the eyes hop
                ey -= 4.0 * abs(math.sin(now * 2.5 * math.pi))
            ey += 4.0 * sigh                      # a sigh: the eyes sink…
            ey -= 7.0 * abs(math.sin(now * 14.0)) * giggle   # giggling: they bounce
            top, tilt, bend = cur["lid_top"][i], cur["lid_tilt"][i], cur["lid_bend"][i]
            bot, bbend = cur["lid_bot"][i], cur["lid_bot_bend"][i]
            # the lids follow the gaze: looking down, the upper lid comes down
            # with it; looking up, the lower lid rises a touch
            look = max(-1.0, min(1.0, (eye.pupil_oy * 0.85 + cur["gaze_y"]) / (0.5 * h)))
            top += 0.20 * max(0.0, look) * max(0.0, 1.0 - top - bot)
            bot += 0.08 * max(0.0, -look) * max(0.0, 1.0 - top - bot)
            # drowsy, or just waking: heavy lids
            heavy = max(getattr(face, "_drowsy", 0.0) * 0.45,
                        (1.0 - getattr(face, "wake_ripple", 1.0)) * 0.55
                        if getattr(face, "wake_anim", 0) else 0.0)
            top += heavy * (1.0 - top - bot)
            if talking and emo in ("happy", "excited"):   # laughing: the cheeks push up
                bot += 0.25 * min(1.0, voice) * (1.0 - top - bot)
            top += (0.25 * sigh + 0.35 * content + 0.10 * shy) * max(0.0, 1.0 - top - bot)
            bot += 0.15 * content * max(0.0, 1.0 - top - bot)     # (stroked: contented)
            # giggling: "^^"; booped: scrunched; dazzled by a flash: squinting
            bot += 0.45 * giggle * max(0.0, 1.0 - top - bot)
            top += (0.15 * giggle + 0.30 * boop + 0.40 * dazzle) * max(0.0, 1.0 - top - bot)
            bot += 0.20 * dazzle * max(0.0, 1.0 - top - bot)
            if emo == "thinking" and i == 0:      # thinking hard: the narrow eye narrows
                top += min(0.12, (now - life.mood_t) / 30.0) * max(0.0, 1.0 - top - bot)
            if rem:                               # dreaming: the shut lids flicker
                f = 0.02 * math.sin(now * 14.0 + i)
                top, bot = top + f, bot - f
            if yawn > 0.0:                        # a yawn screws the eyes up
                top, bot = top + 0.45 * yawn * (1.0 - top - bot), bot + 0.25 * yawn * (1.0 - top - bot)
            # squints (reply scenes, idle micro-expressions) bring both lids
            # in; wide eyes open them
            sq = eye.squint
            top, bot = top + (1.0 - top) * 0.30 * sq, bot + (1.0 - bot) * 0.18 * sq
            top, bot = top * (1.0 - 0.7 * eye.widen), bot * (1.0 - 0.7 * eye.widen)
            # a blink: the lids meet ~60 % of the way down, their curves meet too
            shut = 1.0 - max(0.0, min(1.0, eye.blink_t))
            shut = max(shut, life.lid(now, i))    # half blinks, slow blinks, a take
            if shut > 0.8 and not asleep:
                life.closed_at = now
            if i == 1:                            # the right eye a frame behind the left
                shut, life.shut_prev = 0.5 * (shut + life.shut_prev), life.shut_prev
            else:
                life.shut_prev = shut
            ey += 4.0 * shut                      # a blink squashes the eye down a little
            h *= 1.0 - 0.04 * shut
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
            u[f"uLidB{i}"] = (bbend, seam, math.radians(cur["rot"][i]), cur["eye_n"])
            # the iris: where she looks (face tracking + the mood's own glance)
            pr = min(w, h) * 0.26 * cur["pupil"][i] * eye.pupil_scale
            pr *= 1.0 + 0.03 * math.sin(now * 0.8)                 # pupils breathe too
            pr *= 1.0 + 0.06 * getattr(face, "awake_glow", 0.0)    # interested: a bit wider
            pr *= 1.0 + 0.15 * life.bump(now, life.seen_t, 1.6)    # someone's there: wide
            pr *= 1.0 + 0.06 * life.listen                          # listening hard
            if cur["tint"] > 0.3:                                   # angry words: pin pupils
                pr *= 1.0 - 0.18 * emph
            if emo == "excited":                                    # excited: racing
                pr *= 1.0 + 0.05 * math.sin(now * 12.0)
            if emo == "surprised":                                  # the take: pinpricks
                pr *= 1.0 - 2.0 * pop
            pr *= 1.0 - 0.35 * dazzle
            dx = eye.pupil_ox * 0.85 + cur["gaze_x"] - side * conv * 0.6   # cross-eyed: in
            dy = eye.pupil_oy * 0.85 + cur["gaze_y"]
            if not asleep:                        # micro-saccades
                dx, dy = dx + life.sacc_now[0], dy + life.sacc_now[1]
            if i == 0 and seen:
                life.last_look = (eye.pupil_ox, eye.pupil_oy)
            if lost > 0.0:                        # they left: still looking there
                dx += (life.lost[1] - eye.pupil_ox) * 0.85 * lost
                dy += (life.lost[2] - eye.pupil_oy) * 0.85 * lost
            if glance > 0.0:                      # a touch: a glance at it
                gx = max(-0.30 * w, min(0.30 * w, (tpt[0] - cx) * 0.35))
                gy = max(-0.25 * h, min(0.25 * h, (tpt[1] - cy) * 0.35))
                dx += (gx - dx) * glance
                dy += (gy - dy) * glance
            if hand_look:                         # her own hand: a glance at it
                gx = max(-0.30 * w, min(0.30 * w, (hand_look[0] - cx) * 0.35))
                gy = max(-0.25 * h, min(0.25 * h, (hand_look[1] - cy) * 0.35))
                dx += (gx - dx) * hand_look[2]
                dy += (gy - dy) * hand_look[2]
            dx -= side * 18.0 * boop              # booped: cross-eyed
            dx += life.shy_side * 26.0 * shy      # shy: a look aside and down
            dy += 14.0 * shy
            dx -= side * 6.0 * life.near          # someone close: the eyes converge
            dx += life.away[1] * 24.0 * away      # talking: a glance aside…
            dy += 6.0 * away                      # …and a little down
            dy -= 20.0 * up                       # sad: a look up at you
            if emo == "sad" and not seen:         # …alone: drifting, lost in thought
                dx += 14.0 * math.sin(now * 0.35)
                dy += 6.0
            if emo == "thinking":                 # searching for it: a slow circle
                dx += 8.0 * math.sin(now * 0.7)
                dy += 5.0 * math.cos(now * 0.7)
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
            by -= 10.0 * eye.widen - 5.0 * eye.squint             # brows go with the eyes…
            by += 4.0 * shut                                       # …dip as she blinks…
            by -= life.brow_flick(i, now)                          # …and flick up now and then
            by -= 0.15 * max(0.0, -(eye.pupil_oy * 0.85 + cur["gaze_y"]))   # looking up
            by -= 6.0 * emph * (-0.8 if cur["tint"] > 0.3 else 1.0)   # a stressed syllable
            by -= 5.0 * life.listen * (i == life.cock)             # listening: one cocked
            by -= 10.0 * yawn
            by -= 14.0 * flash + 10.0 * aha       # a greeting flash; "aha!"
            if emo == "surprised":
                by -= 120.0 * pop                 # (pop peaks at 0.12)
            by += 6.0 * sigh
            if talking and emo in ("happy", "excited"):   # bobbing with her syllables
                by -= 3.0 * life.bump(now, getattr(self, "_vis_t", -9.0), 0.18)
            by -= 5.0 * life.bump(now, life.press_t + 0.3, 0.8)   # done: "your turn"
            t = cur["brow_tilt"][i] * 0.5
            if talking and cur["wet"] > 0.5:      # sad, talking: the inner brows quiver
                t -= 2.5 * cur["wet"] * math.sin(now * 13.0 + i)
            if side < 0:                          # the left eye: its inner end on the right
                brows.append((ex - bw / 2, by - t, ex + bw / 2, by + t))
            else:
                brows.append((ex - bw / 2, by + t, ex + bw / 2, by - t))
        u["uBrow0"], u["uBrow1"] = brows
        u["uBrowK"] = (cur["brow_bend"], cur["brow_bend"],
                       21.0 + 6.0 * cur["tint"] - 7.0 * max(0.0, 1.0 - cur["brow_a"]),
                       cur["brow_a"])
        u.update(self._mouth(face, rf, fcx, fcy, cur))
        blush = min(1.0, cur["blush"] + 0.55 * shy + 0.5 * content + 0.25 * beatv
                    + 0.4 * giggle)
        u["uBlush"] = (fcx, fcy, blush, 30.0)
        self.blush_now = blush                    # (robot_face: the "///" lines)
        sp = getattr(face, "_scene_p", 0.0)
        tearing = (getattr(face, "_scene_name", None) == "glitch" and 0.12 < sp < 0.82)
        u["uGlitch"] = (1.0, float(int(sp * 24))) if tearing else (0.0, 0.0)
        try:                                      # the radio playing (visualizer.py)
            vis = visualizer.uniforms(talking, night > 0.5, self.w, self.h)
            u["_vis"] = vis if vis["uVisK"][1] > 0.005 else None     # (gl_vis.py)
            u["uEnergy"] = max(u["uEnergy"], 0.5 * visualizer.music_energy())
        except Exception as e:
            u["_vis"] = None
            if not getattr(self, "_vis_err", False):
                self._vis_err = True
                print(f"[vis] {e}", flush=True)
        self.shape_rects = self._shape_boxes(u)
        return u

    # the mouth's shapes while she talks — wide "a", round "o", flat "e" —
    # (fallback, no sound to read: a new one at each syllable)
    VISEMES = ((1.0, 1.0), (0.58, 1.12), (1.14, 0.58), (0.86, 0.80))

    @staticmethod
    def viseme_of(shape):
        """The mouth's (width, height, teeth) for a sound: (brightness,
        zero-crossings) from openai_tts.Envelope. Dark sounds (o, u) round
        and narrow it, bright ones (e, i) spread it flat, a hiss (s, sz, cz)
        shows the teeth through a narrow gap. Thresholds from her own voice
        (255 cached clips: vowels 0.06–0.22, hiss 0.8+)."""
        b, z = shape
        fric = (max(0.0, min(1.0, (z - 0.15) / 0.20))
                * max(0.0, min(1.0, (b - 0.45) / 0.40)))
        v = max(0.0, min(1.0, (b - 0.07) / 0.18))
        vw, vh = _lerp(0.68, 1.15, v), _lerp(1.12, 0.66, v)
        return _lerp(vw, 1.05, fric), _lerp(vh, 0.50, fric), fric

    def _viseme(self, e, shape=None):
        now = time.monotonic()
        prev = getattr(self, "_vis_prev", 0.0)
        if e - prev > 0.07 or now - getattr(self, "_vis_t", 0.0) > 0.30:
            self._vis = random.randrange(len(self.VISEMES))
            self._vis_t = now
            if e > 0.55 and getattr(self, "life", None):
                self.life.emph_t = now            # a stressed syllable
        self._vis_prev = e
        if shape is not None:                     # the real sound
            tw, th, tf = self.viseme_of(shape)
        else:
            (tw, th), tf = self.VISEMES[getattr(self, "_vis", 0)], 0.0
        cw, ch, cf = getattr(self, "_vis_wh", (1.0, 1.0, 0.0))
        k = 0.55 if shape is not None else 0.35
        self._vis_wh = (cw + (tw - cw) * k, ch + (th - ch) * k, cf + (tf - cf) * k)
        return self._vis_wh

    def _mouth(self, face, rf, fcx, fcy, cur):
        """The mood's mouth — or, while she talks, one opened by her voice."""
        m = face.mouth
        mx = fcx + m.rel_x + cur["mouth_dx"]
        my = fcy + m.rel_y + cur["mouth_dy"]
        kind = self.eased.mouth
        w, h, bend = cur["mouth_w"], cur["mouth_h"], cur["mouth_bend"]
        slant, open_ = cur["mouth_slant"], 0.0
        alpha = cur["mouth_a"] * self.eased.mouth_fade
        w *= 1.0 + 0.02 * math.sin(getattr(face, "breath_phase", 0.0))   # breathing
        now = time.monotonic()
        if face._emotion == "thinking":           # mulling it over: the mouth drifts
            mx += 10.0 * math.sin(now * 0.9)
            slant += 3.0 * math.sin(now * 0.6)
        if (face._emotion in ("neutral", "listening") and getattr(face, "_face_seen", False)
                and getattr(face, "awake_glow", 0.0) > 0.5):
            bend += 5.0                           # looking at someone she's talking to
        life = getattr(self, "life", None) or _Life()
        sm = life.bump(now, life.smirk[0], 1.6)   # happy: a lopsided smile
        slant += life.smirk[1] * 8.0 * sm
        bend += 6.0 * sm
        talking = face._speaking or m.speak_fade > 0.05
        if face._emotion == "sleeping" and not talking:   # deep breaths: lips part
            h += 2.5 * max(0.0, math.sin(getattr(face, "breath_phase", 0.0)))
        mu = life.bump(now, life.mumble_at, 0.9)  # asleep: a mumble
        if face._emotion == "sleeping" and mu > 0.05 and not talking:
            kind, open_ = face_spec.OPEN, 0.3 * mu
            w, h = w * (1.0 - 0.25 * mu), 13.0 + 16.0 * abs(math.sin(now * 9.0)) * mu
        y = life.yawn(now)
        if y > 0.05 and not talking:              # a yawn: the mouth opens wide and tall
            kind, open_ = face_spec.OPEN, y
            w, h = _lerp(w, 96.0, y), _lerp(16.0, 118.0, y)
            bend, slant = bend * (1.0 - y), 0.0
            alpha = max(alpha, y)
        if not talking:
            emo = face._emotion
            if emo == "sad":                      # a trembling lip, now and then
                slant += 1.6 * max(0.0, math.sin(now * 0.8)) ** 4 * math.sin(now * 22.0)
            elif kind == face_spec.O:             # surprised: the "o" breathes
                w, h = w * (1.0 + 0.06 * math.sin(now * 2.2)), h * (1.0 + 0.06 * math.sin(now * 2.2))
            elif kind == face_spec.GRIT:          # angry: grinding the teeth
                w += 3.0 * math.sin(now * 9.0)
                mx += 1.5 * math.sin(now * 4.5)
            hm = life.bump(now, life.hmm_t, 1.0)  # thinking: "hmm" — the lips purse
            w *= 1.0 - 0.25 * hm
            bend -= 3.0 * hm
            bend -= 8.0 * life.bump(now, life.sigh_t, 1.8)   # a sigh
        if not talking:
            g = life.bump(now, life.giggle_t, 1.3)
            bend += 14.0 * g + 6.0 * life.bump(now, life.press_t + 0.4, 0.8)
            w *= 1.0 + 0.1 * g
            if face._emotion == "sleeping":       # a sweet dream
                bend += 10.0 * life.bump(now, life.dream_t, 3.0)
        pr = life.bump(now, life.press_t, 0.5)    # a sentence ends: the lips press
        if talking:
            e = m.talk_open
            alpha = max(alpha, min(1.0, m.speak_fade))
            vw, vh, teeth = self._viseme(e, getattr(face, "_audio_shape", None))
            if e > 0.06:
                kind, open_ = face_spec.OPEN, max(e, 0.65 * teeth)   # (open_ shows the teeth)
                w = _lerp(m.mouth_w * 0.55, m.mouth_w * 1.15,
                          max(0.0, min(1.0, (e - 0.06) / 0.5))) * vw
                # (at least 24 px: thinner, the lips met in a light streak)
                h = max(24.0, (10.0 + (e + m.jaw_bounce * 0.3) * 82.0) * vh)
                bend = max(0.0, bend) + m.corner_lift * 10.0   # a smile while talking
            else:                                 # between words: closed, still smiling
                kind, w, h = face_spec.LINE, max(140.0, w * 0.9), 15.0
                bend = 0.5 * bend + m.corner_lift * 8.0
                slant = 0.0
        if pr > 0.0 and kind == face_spec.LINE:
            w, h, bend = w * (1.0 - 0.12 * pr), h * (1.0 - 0.2 * pr), bend - 6.0 * pr
        wave = 0.0
        tm = themes.get().get("mouth")            # a theme's own mouth (themes.py)
        if tm:
            if tm.get("wave"):                    # HAL: a voice wave, flat when quiet
                kind, w, h, bend, slant, open_ = face_spec.WAVY, tm["wave"], 6.0, 0.0, 0.0, 0.0
                wave = 1.5 + (48.0 * min(1.0, m.talk_open * 1.6) if talking else 0.0)
                alpha = 1.0
            mx += tm.get("dx", 0.0)               # the doctor's smirk: off-centre, lopsided
            slant += tm.get("slant", 0.0)
            if not talking:
                w *= tm.get("w", 1.0)
            if kind == face_spec.LINE:
                h = max(h, tm.get("min_h", 0.0))  # pixel art: a chunky line
        return {"uMouth": (mx, my, w, h), "uMouthK": (bend, open_, alpha, float(kind)),
                "uMouthSlant": slant, "uWave": wave}
