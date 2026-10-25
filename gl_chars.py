"""
gl_chars.py — the four drawn characters' shaders (characters.py has their data).

They draw the same pose as Luna: gl_face.face_uniforms computes the lids,
the gaze, the pupils, the brows and the mouth (her moods, blinks, saccades,
reply scenes, visemes) and apply() below moves them to the character's own
layout, adds its expression channels, gestures and props, and picks the
boxes to draw in. The shapes' maths — the lidded eye, the seam of a shut
eye, the brow, every mouth — are gl_face's own lines, sliced out of its
shader, so a character can't drift from what the pose means.

Each character is a small program of its own (#define), compiled the
first time it is shown; GLFace.render() runs it in the same stages as
Luna's face: the soft part (background, glow, particles) at a quarter of
the size, stretched; then each sharp piece in its own box, premultiplied.
GLSL 1.20 or ES 1.00, like gl_face.
"""

import math
import random
import time

import characters
import dock
import gl_face
import mochi_rig

_F = gl_face._FRAG


def _cut(a, b):
    return _F[_F.index(a):_F.index(b)]


_HEAD = """
uniform vec2  uRes;
uniform vec2  uSoftRes;
uniform float uTime;
uniform float uTilt;
uniform float uPass;
uniform float uShape;
uniform vec4  uEye0, uEye1, uLidA0, uLidA1, uLidB0, uLidB1, uPupil0, uPupil1;
uniform vec4  uMorph;
uniform vec4  uBrow0, uBrow1, uBrowK;
uniform vec4  uMouth, uMouthK;
uniform float uMouthSlant;
uniform float uWave;
uniform vec3  uWaveBands;
uniform vec2  uGlitch;
uniform float uEnergy;
uniform float uDim;
uniform vec3  uShine;
uniform vec4  uBlush;
uniform vec4  uChA;     // the face's centre (x, y), motion, glow
uniform vec4  uChB;     // happy, sad, angry, surprise
uniform vec4  uChC;     // think, sleep, celebrate, alert
uniform vec4  uChD;     // curious, confused, glitch, crt (RETRO: 1 on)
uniform vec4  uChE;     // the gesture's sway: dx, dy, turn (rad); listening
uniform vec4  uChF;     // speaking, effects (0 off .. 1 full), console (RETRO), a rolling line
uniform vec4  uChG;     // music playing, the character's own (a, b, c)
uniform vec4  uAcc;     // its accessories, each 0 / 1 (characters.py order)
uniform vec3  uPal0, uPal1, uPal2, uPal3;
uniform vec4  uPt0, uPt1, uPt2, uPt3;    // props: x, y, size, kind + alpha * 0.98
uniform vec4  uPt4, uPt5, uPt6, uPt7;    // …the state's own (listening, asleep, a tear…)
uniform vec4  uChH;     // the mic's level (listening), the wake (0 → 1; 1: awake)
uniform float uT;       // seconds
uniform sampler2D uCells;   // RETRO / PIXEL: each cell worked out once (stage 4)
uniform vec4  uGrid;    // …its half size and size in cells
uniform vec4  uHand0, uHand1;   // her hands: x, y, turn (rad; the heart: its beat), pose + alpha * 0.98
uniform sampler2D uArt;     // RETRO / PIXEL: the hands' pixel art (HAND_ART, stage 6)
uniform vec4  uMoEar;   // MOCHI (mochi_rig.py): the ears' lean L, R (rad), their tips' flop L, R
uniform vec4  uMoEye;   // …the eyes' glyphs: kind, amount (left), kind, amount (right)
uniform vec4  uMoFace;  // …the eyes' scale L, R (in apply), starry, her cheeks' blush
uniform vec4  uMoMouth; // …her own mouth: kind, amount, half width
uniform vec4  uMoPaw;   // …the paws' sizes L, R
uniform vec4  uMoBody;  // …squash, the pods' light, puffed cheeks
uniform vec4  uMoIris;  // …the iris's size, the pupil's, where it looks (× the eye's radius)

""" + _cut("float sdRoundBox", "// ── the light") + _cut("// ── the light", "// the outward") \
    + _cut("vec2 eyeLocal", "vec3 eyeColour") + _cut("float browSDF", "// one eye over") \
    + _cut("// the mouth's shape at q", "vec3 drawMouth") + """

float cover(float d) { return clamp(0.5 - d, 0.0, 1.0); }

// premultiplied "over"; light alone is added to .rgb
void over(inout vec4 acc, vec3 c, float a) {
    acc = vec4(c * a + acc.rgb * (1.0 - a), a + acc.a * (1.0 - a));
}

vec2 rot2(vec2 v, float a) {
    float c = cos(a), s = sin(a);
    return vec2(c * v.x - s * v.y, s * v.x + c * v.y);
}

// the screen's pixel → the face's: the head's tilt, then the gesture's sway
vec2 facePos(vec2 fc) {
    vec2 c0 = uRes * 0.5;
    vec2 p = c0 + rot2(fc - c0, uTilt);
    return uChA.xy + rot2(p - uChA.xy - uChE.xy, uChE.z);
}

float eyeD(vec2 p, vec4 e, vec4 la, vec4 lb, float side, out vec2 q) {
    q = eyeLocal(p, e, lb, side);
    return eyeSDF(q, e, la, lb, side);
}

float seamD(vec2 q, vec4 e, vec4 la, vec4 lb, float side) {
    return lb.y > 0.01 ? seamSDF(q, e, la, lb, side) : 1e5;
}

float maxc(vec3 c) { return max(c.x, max(c.y, c.z)); }

float smin(float a, float b, float k) {
    float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
    return mix(b, a, h) - k * h * (1.0 - h);
}

float ellD(vec2 q, vec2 r) { return (length(q / r) - 1.0) * min(r.x, r.y); }

// a sharp shape's own halo: gone before its box's edge (no seam there)
float halo(float d, float r) {
    return exp(-max(d, 0.0) / r) * clamp(1.0 - d / 14.0, 0.0, 1.0);
}

// a soft glow's distance to an eye: its box, as open as its lids (the
// squircle's own distance goes astray far from it: streaks in the glow)
float glowEye(vec2 p, vec4 e, vec4 la) {
    float open = clamp(1.0 - la.x - la.w, 0.04, 1.0);
    vec2 c = e.xy + vec2(0.0, (la.x - la.w) * e.w * 0.5);
    return sdRoundBox(p - c, vec2(e.z * 0.5, max(e.w * 0.5 * open, 4.0)), min(e.z, e.w * open) * 0.3);
}

// a cell's place in the cells texture
vec4 cellAt(vec2 ci) {
    return texture2D(uCells, (ci + uGrid.xy + 0.5) / uGrid.zw);
}

// ── props: hearts, a question mark, stars, sparkles, a rocket ──
float sdQuestion(vec2 q) {               // unit size, y down, centred
    vec2 h = q - vec2(0.0, -0.34);
    float ring = abs(length(h) - 0.30) - 0.11;
    if (h.y > 0.0 && h.x < 0.0) ring = 1e5;          // the hook: open at its lower left
    float stem = sdSeg(q, vec2(0.0, -0.04), vec2(0.0, 0.20)) - 0.11;
    return min(min(ring, stem), length(q - vec2(0.0, 0.52)) - 0.13);
}

float sdBang(vec2 q) {
    return min(sdSeg(q, vec2(0.0, -0.66), vec2(0.0, 0.18)) - 0.13 + 0.06 * (q.y + 0.66),
               length(q - vec2(0.0, 0.55)) - 0.14);
}

float sdSparkle(vec2 q) {
    vec2 a = abs(q);
    return (pow(sqrt(a.x) + sqrt(a.y), 2.0) - 0.85) * 0.5;
}

void prop(vec2 p, vec4 pt, inout vec4 acc) {
    if (pt.z <= 0.0) return;
    float kind = floor(pt.w + 0.001);
    float al = clamp(fract(pt.w + 0.001) / 0.98, 0.0, 1.0);
    float s = pt.z;
    vec2 q = (p - pt.xy) / s;
    float d;
    vec3 c;
    if (kind < 1.5) {                                   // a heart
        d = sdHeart(vec2(q.x, 0.62 - q.y) * 0.9) * s / 0.9;
        c = mix(uPal3, vec3(1.0), 0.35 * smoothstep(0.2, -0.6, q.y + 0.5 * q.x));
    } else if (kind < 2.5) {                            // ?
        d = sdQuestion(q) * s;
        c = uPal0;
    } else if (kind < 3.5) {                            // a star
        d = sdStar5(vec2(q.x, -q.y), 0.9, 0.45) * s;
        c = mix(uPal3, vec3(1.0), 0.3);
    } else if (kind < 4.5) {                            // a sparkle
        d = sdSparkle(q) * s;
        c = mix(uPal0, vec3(1.0), 0.45);
    } else if (kind < 6.5) {                            // a rocket, flying up
        float body = length(q / vec2(0.32, 0.75)) - 1.0;
        float fin = sdRoundBox(q - vec2(0.0, 0.55), vec2(0.55, 0.16), 0.08);
        float win = length(q - vec2(0.0, -0.15)) - 0.15;
        float fl = length((q - vec2(0.0, 1.05)) / vec2(0.20, 0.38 + 0.1 * sin(uT * 40.0))) - 1.0;
        d = min(min(body * 0.3, fin), fl * 0.2) * s;
        c = body * 0.3 < fin ? mix(vec3(0.92, 0.90, 0.86), uPal3, step(q.y, -0.45)) : uPal3;
        if (fl * 0.2 < min(body * 0.3, fin)) c = mix(vec3(1.0, 0.9, 0.4), uPal0, q.y - 0.8);
        if (win < 0.0) c = vec3(0.25, 0.55, 0.85);
    } else if (kind < 7.5) {                            // !
        d = sdBang(q) * s;
        c = uPal3;
    } else if (kind < 8.5) {                            // a tear
        vec2 t = vec2(q.x, q.y < 0.1 ? 0.1 + (q.y - 0.1) * 0.55 : q.y);
        d = (length(t - vec2(0.0, 0.1)) - 0.42) * s;
        c = mix(vec3(0.55, 0.78, 1.0), vec3(1.0), 0.6 * smoothstep(0.2, 0.0, length(q - vec2(-0.13, 0.04))));
    } else if (kind < 9.5) {                            // a "z"
        d = (min(min(sdSeg(q, vec2(-0.42, -0.45), vec2(0.42, -0.45)),
                     sdSeg(q, vec2(0.42, -0.45), vec2(-0.42, 0.45))),
                 sdSeg(q, vec2(-0.42, 0.45), vec2(0.42, 0.45))) - 0.12) * s;
        c = uPal0;
    } else if (kind < 10.5) {                           // an anger mark
        vec2 a = abs(q);
        d = max(abs(length(a - vec2(0.62)) - 0.40) - 0.10, max(a.x, a.y) - 0.62) * s;
        c = vec3(1.0, 0.30, 0.32);
    } else if (kind < 11.5) {                           // a thought cloud, "…" filling it
        float cl = min(min(length(q - vec2(-0.35, 0.05)) - 0.38, length(q - vec2(0.05, -0.18)) - 0.45),
                       min(length(q - vec2(0.42, 0.06)) - 0.36,
                           sdRoundBox(q - vec2(0.03, 0.18), vec2(0.62, 0.2), 0.2)));
        float trail = min(length(q - vec2(-0.62, 0.62)) - 0.12, length(q - vec2(-0.85, 0.85)) - 0.07);
        d = min(cl, trail) * s;
        c = mix(uPal2, vec3(1.0), 0.55);
        float dots = 1e5;
        for (int k = 0; k < 3; k++) {
            float fk = float(k);
            float on = step(fk, mod(floor(uT * 3.0), 4.0) - 0.5);
            dots = min(dots, mix(1e5, length(q - vec2(-0.32 + 0.32 * fk, 0.02)) - 0.09, on));
        }
        c = mix(c, uPal1 * 0.75, cover(dots * s));
    } else if (kind < 12.5) {                           // signal arcs, filling with the mic
        vec2 o = q - vec2(0.0, 0.55);
        float r = length(o);
        float ang = abs(atan(o.x, -o.y));
        float k = clamp(floor((r - 0.14) / 0.36), 0.0, 2.0);
        float arc = max(abs(r - (0.32 + 0.36 * k)) - 0.08, (ang - 0.8) * r);
        float dot0 = r - 0.11;
        d = min(arc, dot0) * s;
        c = uPal0;
        if (arc < dot0) al *= 0.22 + 0.78 * step(k / 3.0, uChH.x * 1.15);
    } else {                                            // "(((" listening: arcs facing the face
        vec2 qq = vec2(q.x * (pt.x < uChA.x ? 1.0 : -1.0), q.y);
        vec2 o = qq - vec2(0.9, 0.0);
        float r = length(o);
        float ang = abs(atan(o.y, -o.x));
        float k = clamp(floor((r - 0.2) / 0.3), 0.0, 2.0);
        d = max(abs(r - (0.35 + 0.3 * k)) - 0.07, (ang - 0.75) * r) * s;
        c = uPal3;
        float wave = step(abs(k - mod(floor(-uT * 4.0), 3.0)), 0.5);       // sound coming in
        al *= 0.25 + 0.5 * step(2.0 - k, uChH.x * 3.3) + 0.25 * wave;
    }
    float glow = 0.35;
#ifdef PLUSH
    // MOCHI's: soft and puffy — pink and white, lighter inside, a darker rim,
    // a highlight up by the light, a quieter glow
    if (kind > 1.5 && kind < 7.5 || kind > 8.5 && kind < 9.5) c = mix(c, mix(uPal3, vec3(1.0), 0.6), 0.6);
    if (kind > 2.5 && kind < 3.5) d -= 0.07 * s;          // a star with round points
    c *= 0.80 + 0.20 * smoothstep(0.0, -0.22 * s, d);
    c = mix(c, vec3(1.0), 0.55 * exp(-dot(q + vec2(0.22, 0.20), q + vec2(0.22, 0.20)) / 0.025)
                      * step(kind, 4.5));
    glow = 0.16;
#endif
    over(acc, c, cover(d) * al);
    acc.rgb += c * glow * exp(-max(d, 0.0) / 6.0) * clamp(1.0 - d / 18.0, 0.0, 1.0)
               * al * (1.0 - cover(d));
}

// (one call: each call of a big function is a copy of it in the compiled
// shader — eight of prop() took the Pi's compiler most of a minute)
void props(vec2 p, inout vec4 acc) {
    vec4 pt = uShape < 5.5 ? uPt0 : uShape < 6.5 ? uPt1 : uShape < 7.5 ? uPt2
            : uShape < 8.5 ? uPt3 : uShape < 12.5 ? uPt4 : uShape < 13.5 ? uPt5
            : uShape < 14.5 ? uPt6 : uPt7;
    prop(p, pt, acc);
}

// ── hands: RETRO and PIXEL in their cells (pixel art), MOCHI and PIP drawn ──
// the nearer hand's art at a cell (cc its centre, cs the cell's size):
// x lit (0, dim, 1), y 1 inside its outline (the cells under it go dark),
// z the pose, w how far down the art (0 top .. 1)
vec4 handArt(vec2 cc, float cs) {
    bool one = uHand1.w > 0.5 && (uHand0.w < 0.5 || length(cc - uHand1.xy) < length(cc - uHand0.xy));
    vec4 h = one ? uHand1 : uHand0;
    if (h.w < 0.5) return vec4(0.0);
    float pose = floor(h.w + 0.001);
    vec2 s = (cc - h.xy) / cs;
    float gy = floor(s.y + 6.0);
    float sx = s.x;
    if (pose < 7.5)                         // turned: bent at the knuckles, whole cells
        sx += floor((gy < 5.5 ? 4.0 : gy < 8.5 ? 2.0 : 0.0) * tan(clamp(h.z, -0.8, 0.8)) + 0.5);
    if (h.x < uChA.x) sx = -sx;             // the left hand: mirrored
    float gx = floor(sx + 5.0);
    if (gx < -1.0 || gx > 10.0 || gy < -1.0 || gy > 12.0) return vec4(0.0);
    vec4 t = texture2D(uArt, vec2(((pose - 1.0) * 12.0 + gx + 1.5) / 96.0, (gy + 1.5) / 14.0));
    float al = clamp(fract(h.w + 0.001) / 0.98, 0.0, 1.0);
    return vec4(t.r * al, step(0.5, t.g * al), pose, clamp(gy / 11.0, 0.0, 1.0));
}

// a capsule that narrows from ra at a to rb at b (a finger, a thumb)
float sdTaper(vec2 p, vec2 a, vec2 b, float ra, float rb) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - mix(ra, rb, h);
}

// a drawn hand's own frame: unit size s px, the left one mirrored, turned
// about its wrist at wy (a wave moves the fingers, not the forearm)
vec2 handLocal(vec2 p, vec4 h, float s, float wy) {
    vec2 q = rot2(p - h.xy - vec2(0.0, wy * s), h.z * step(h.w, 7.5)) / s + vec2(0.0, wy);
    if (h.x < uChA.x) q.x = -q.x;
    return q;
}
"""

# one program per stage (PASS_CELLS / PASS_SOFT / the shapes): the compiler
# drops what a stage doesn't call. 22 Oct: one program for all three took the
# Pi's V3D compiler 50-80 s at its first draw (a new shader, no cache) — the
# watchdog saw no frame for 30 s and restarted her into the same compile.
_MAIN = """
void main() {
#if defined(PASS_CELLS)
    vec2 ci = floor(gl_FragCoord.xy) - uGrid.xy;   // each cell once, into the small texture
    gl_FragColor = gridCell(ci);
#elif defined(PASS_SOFT)
    vec2 fc = vec2(gl_FragCoord.x, uSoftRes.y - gl_FragCoord.y) * (uRes / uSoftRes);
    vec3 col = soft(facePos(fc), fc / uRes);
#ifdef CRT
    col = crtSoft(col, fc);
#endif
    gl_FragColor = vec4(col, 1.0);
#else
    vec2 fc = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);
    fc.x -= glitchShift(fc.y);
#ifdef CRT
    vec2 sc = fc;
    fc = crtWarp(fc);                   // its picture's sync: wobbling, tearing
#endif
    vec4 acc = vec4(0.0);
    shape(facePos(fc), acc);
#ifdef CRT
    acc = crtPost(acc, sc);             // scanlines, grain, blocks
#endif
    gl_FragColor = acc;
#endif
}
"""

PASSES = {"soft": "#define PASS_SOFT\n", "cells": "#define PASS_CELLS\n", "shape": ""}
DEFINES = {"mochi": "#define PLUSH\n"}       # a character's own style of the shared props

# ── RETRO: a beige console, its dark CRT, amber pixel eyes ──────────────────
_RETRO = """
#define GRID
const float CELL = 10.0;

vec2 rSC() { return uChA.xy + vec2(0.0, uChF.z > 0.5 ? -18.0 : -10.0); }
vec2 rSB() { return uChF.z > 0.5 ? vec2(214.0, 126.0) : vec2(300.0, 172.0); }
vec2 rBC() { return uChA.xy + vec2(0.0, 10.0); }
const vec2 R_BB = vec2(290.0, 198.0);

// one eye on the grid: lit, its pupil a dark block with a glint (cells
// far from the eye skip the maths)
float rEye(vec2 cc, vec4 e, vec4 la, vec4 lb, vec4 pu, float side) {
    if (abs(cc.x - e.x) > e.z * 0.5 + 2.0 * CELL || abs(cc.y - e.y) > e.w * 0.5 + 2.0 * CELL)
        return 0.0;
    vec2 q;
    float d = eyeD(cc, e, la, lb, side, q);
    float v = 0.0;
    if (d < 0.0) {
        v = d > -CELL ? 1.0 : 0.82;
        vec2 pq = q - floor(pu.xy / CELL + 0.5) * CELL;
        float pr = max(pu.z * 0.62, 1.5 * CELL);
        if (pu.w > 0.3 && abs(pq.x) < pr && abs(pq.y) < pr)
            v = (pq.x < -pr + CELL && pq.y < -pr + CELL) ? 1.0 : 0.05;
    }
    if (seamD(q, e, la, lb, side) < CELL * 0.35) v = max(v, lb.y);
    return v;
}

// the states on its screen, in cells: listening (● REC, the mic's bars),
// speaking (an equaliser), asleep (Zs rising), sad (a tear), cross (#), surprised (!)
float rGlyphZ(vec2 g) {                   // a 5×5 "Z", g the cell in it
    if (g.x < 0.0 || g.y < 0.0 || g.x > 4.0 || g.y > 4.0) return 0.0;
    return (g.y < 0.5 || g.y > 3.5 || abs(g.x - (4.0 - g.y)) < 0.5) ? 1.0 : 0.0;
}

float rStates(vec2 cc) {
    vec2 sc = rSC(), sb = rSB();
    vec2 tl = sc + vec2(-sb.x, sb.y) + vec2(2.0 * CELL, -7.0 * CELL);   // bottom left, inside
    vec2 br = sc + sb + vec2(-3.0 * CELL, -7.0 * CELL);                   // bottom right
    vec2 tr = sc + vec2(sb.x, -sb.y) + vec2(-3.0 * CELL, 2.0 * CELL);
    float v = 0.0;
    vec2 g = floor((cc - tl) / CELL);
    if (uChE.w > 0.05 && g.y >= 0.0 && g.y <= 4.0) {
        if (g.y <= 1.0 && g.x >= 0.0 && g.x <= 1.0)
            v = max(v, uChE.w * step(0.45, fract(uT * 1.2)));        // ● blinking
        if (g.x >= 3.0 && g.x <= 11.0 && mod(g.x - 3.0, 2.0) < 0.5) {
            float k = (g.x - 3.0) / 2.0;                            // five bars, 1..5 tall
            if (g.y >= 4.0 - k)
                v = max(v, uChE.w * (0.22 + 0.78 * step(k / 5.0, uChH.x * 1.15)));
        }
    }
    vec2 h = floor((cc - br) / CELL);
    if (uChF.x > 0.3 && h.y >= 0.0 && h.y <= 4.0 && h.x <= 0.0 && h.x >= -8.0
            && mod(-h.x, 2.0) < 0.5) {                               // speaking: an equaliser
        float k = -h.x / 2.0;
        float lv = floor(1.0 + 4.0 * clamp(uEnergy * (0.55 + 0.45 * sin(uT * 11.0 + k * 1.9)), 0.0, 1.0));
        if (h.y >= 5.0 - lv) v = max(v, uChF.x * 0.9);
    }
    if (uChC.y > 0.05) {                                            // asleep: Zs, rising in steps
        for (int k = 0; k < 2; k++) {
            float fk = float(k);
            float t = fract(uT * 0.3 + fk * 0.5);
            vec2 at = tr + vec2(-(5.0 + 6.0 * fk) * CELL, (4.0 - floor(t * 5.0)) * CELL);
            v = max(v, rGlyphZ(floor((cc - at) / CELL)) * uChC.y * (1.0 - t) * 1.4);
        }
    }
    if (uChB.y > 0.05) {                                            // sad: a tear falls, cell by cell
        float t = fract(uT * 0.6);
        vec2 at = vec2(uEye0.x - uEye0.z * 0.25, uEye0.y + uEye0.w * 0.5 + CELL * (1.0 + floor(t * 6.0)));
        vec2 d = floor((cc - at) / CELL);
        float drop = (d.x == 0.0 && (d.y == 0.0 || d.y == 2.0)) || (abs(d.x) <= 1.0 && d.y == 1.0) ? 1.0 : 0.0;
        v = max(v, drop * uChB.y * (1.0 - t));
    }
    if (uChB.z > 0.05) {                                            // cross: a pulsing "#"
        vec2 at = vec2(uEye1.x + uEye1.z * 0.5 + 2.5 * CELL, uEye1.y - uEye1.w * 0.5 - 1.5 * CELL);
        vec2 d = floor((cc - at) / CELL + 0.5);
        float hash_ = (abs(d.x) <= 2.0 && abs(d.y) <= 2.0 && (abs(d.x) == 1.0 || abs(d.y) == 1.0)) ? 1.0 : 0.0;
        v = max(v, hash_ * uChB.z * (0.55 + 0.45 * step(0.35, fract(uT * 2.0))));
    }
    if (uChB.w > 0.05) {                                            // surprised: "!"
        vec2 at = vec2(uEye0.x - uEye0.z * 0.5 - 3.0 * CELL, uEye0.y - 2.0 * CELL);
        vec2 d = floor((cc - at) / CELL + 0.5);
        float bang = (d.x == 0.0 && ((d.y >= -2.0 && d.y <= 1.0) || d.y == 3.0)) ? 1.0 : 0.0;
        v = max(v, bang * uChB.w);
    }
    float puzzled = max(uChD.x, uChD.y);
    if (puzzled > 0.05) {                                           // curious, confused: "?"
        vec2 at = vec2(uEye1.x + uEye1.z * 0.5 + 2.0 * CELL, uEye1.y - 2.0 * CELL);
        vec2 d = floor((cc - at) / CELL + 0.5);
        float q = (d.y == -2.0 && abs(d.x) <= 1.0) || (d.y == -1.0 && d.x == 1.0)
                  || (d.y == 0.0 && d.x >= 0.0 && d.x <= 1.0) || (d.y == 2.0 && d.x == 0.0) ? 1.0 : 0.0;
        v = max(v, q * puzzled);
    }
    return v;
}

float rCell(vec2 cc, vec2 ci) {
    float v = max(rEye(cc, uEye0, uLidA0, uLidB0, uPupil0, -1.0),
                  rEye(cc, uEye1, uLidA1, uLidB1, uPupil1, 1.0));
    float load = uChC.x * (1.0 - uChF.x);              // thinking: a loading bar for a mouth
    vec2 mq = abs(cc - uMouth.xy);
    if (uMouthK.z > 0.01 && load < 0.99 && mq.x < uMouth.z * 0.5 + uMouth.w + CELL
            && mq.y < uMouth.w * 1.6 + abs(uMouthK.x) + abs(uMouthSlant) + 2.0 * CELL) {
        float inner, teeth, tongue;
        float d = mouthSDF(cc - uMouth.xy, inner, teeth, tongue);
        if (d < 0.0)
            v = max(v, (inner < 0.0 ? 0.15 + 0.8 * teeth : 1.0) * uMouthK.z * (1.0 - load));
    }
    if (load > 0.01 && mq.y < 3.0 * CELL) {
        float row = floor((cc.y - uMouth.y) / CELL);
        float x = ci.x + 11.0;
        float seg = floor(x / 3.0);
        float inSeg = step(-1.0, row) * step(row, 0.0) * step(0.0, x) * step(seg, 6.5)
                      * step(mod(x, 3.0), 1.5);
        float head = mod(floor(uT * 8.0), 10.0);
        float on = step(head - 2.5, seg) * step(seg, head);       // three lit, scrolling
        v = max(v, inSeg * load * (0.22 + 0.78 * on));
    }
    if (uChC.z > 0.05) {                               // a win: sparkles blinking in steps
        for (int k = 0; k < 4; k++) {
            float fk = float(k);
            vec2 at = uChA.xy + vec2((fk < 2.0 ? -1.0 : 1.0) * (150.0 + 22.0 * mod(fk, 2.0)),
                                     -100.0 + 70.0 * mod(fk, 2.0));
            vec2 r = abs(floor((cc - at) / CELL));
            float plus = (r.x < 0.5 && r.y < 2.5) || (r.y < 0.5 && r.x < 2.5) ? 1.0 : 0.0;
            float on = step(0.5, fract(uT * 2.5 + fk * 0.37));
            v = max(v, plus * on * uChC.z);
        }
    }
    if (uAcc.y > 0.5 && uChC.y < 0.5 && cc.y > uEye0.y - uEye0.w && cc.y < uEye0.y + uEye0.w) {
        for (int k = 0; k < 2; k++) {
            vec4 e = k == 0 ? uEye0 : uEye1;
            vec2 r = abs(cc - e.xy) - vec2(e.z * 0.5 + CELL * 1.5, e.w * 0.36 + CELL);
            float frame = step(max(r.x, r.y), 0.0) * step(-CELL, max(r.x, r.y));
            v = max(v, frame * 0.85);
            if (max(r.x, r.y) < -CELL) v = v * 0.6 + 0.10;      // tinted lenses
        }
        float br = abs(cc.y - (uEye0.y - uEye0.w * 0.2));
        if (br < CELL * 0.5 && abs(cc.x - uChA.x) < (uEye1.x - uEye0.x) * 0.5 - uEye0.z * 0.5)
            v = max(v, 0.85);
    }
    return v;
}

vec4 gridCell(vec2 ci) {
    vec2 cc = uChA.xy + (ci + 0.5) * CELL;
    float v = max(rCell(cc, ci), rStates(cc));
    vec4 hd = handArt(cc, CELL);
    if (hd.y > 0.5)                    // a hand, a heart: a sprite over the rest (a dark edge)
        v = hd.x * (hd.z > 7.5 ? 0.6 + 0.4 * step(0.5, uHand0.z) : 1.0);
    return vec4(0.0, 0.0, 0.0, v);
}

void rScreen(vec2 p, inout vec4 acc) {
    vec2 sc = rSC(), sb = rSB();
    bool console = uChF.z > 0.5;
    float crt = uChD.w;
    float dsc = sdRoundBox(p - sc, sb, 26.0);
    float inside = console ? cover(dsc) : 1.0;
    if (inside <= 0.0) return;
    if (console) {                                     // the glass: dark, curved
        vec2 n = (p - sc) / sb;
        vec3 glass = vec3(0.034, 0.027, 0.018) * (1.0 - 0.5 * dot(n, n)) + uPal0 * 0.012;
        vec2 hq = (n - vec2(-0.55, -0.62)) * vec2(2.4, 5.0);
        glass += vec3(0.035) * exp(-dot(hq, hq));      // a reflection, top left
        glass *= 1.0 - 0.5 * smoothstep(-14.0, 0.0, dsc);
        over(acc, glass, inside);
    }
    vec2 rel = p - uChA.xy;
    vec2 ci = floor(rel / CELL);
    float v = cellAt(ci).a;
    vec2 f = rel - (ci + 0.5) * CELL;
    float px = cover(sdRoundBox(f, vec2(CELL * 0.40), 1.6));
    float on = smoothstep(0.55, 1.0, crt);
    float bright = (1.0 - 0.62 * uChC.y) * uDim * (0.92 + 0.12 * uEnergy);
    vec3 col = uPal0 * v * (px + 0.12 * (1.0 - px)) * bright * on;
    col *= mix(1.0, 0.86 + 0.14 * step(1.0, mod(p.y, 3.0)), uChF.y);   // scanlines
    float yr = sc.y - sb.y + (1.0 - uChF.w) * 2.0 * sb.y;               // a rolling line
    col += uPal0 * 0.07 * exp(-sq((p.y - yr) / 12.0)) * uChF.w * step(dsc, 0.0);
    if (crt < 1.0) {                                   // starting up: a line opens out
        float lx = max(2.0, sb.x * smoothstep(0.0, 0.3, crt));
        float ly = max(1.5, sb.y * smoothstep(0.3, 0.6, crt));
        float beam = cover(sdRoundBox(p - sc, vec2(lx, ly), 1.0));
        col += mix(vec3(1.0, 0.95, 0.85), uPal0, 0.5) * beam * 0.8 * (1.0 - smoothstep(0.5, 0.95, crt));
    }
    if (!console) {                                    // face only: the screen's corners
        vec2 a = abs(p - sc) - sb;
        float corner = step(max(a.x, a.y), 0.0) * step(-4.0, max(a.x, a.y))
                       * step(-34.0, min(a.x, a.y));
        col += uPal0 * 0.55 * corner * on * (1.0 - 0.6 * uChC.y);
    }
    acc.rgb += col * inside;
}

void rBody(vec2 p, inout vec4 acc) {
    vec2 bc = rBC();
    float d = sdRoundBox(p - bc, R_BB, 56.0);
    float a = cover(d);
    if (a <= 0.0) return;
    vec2 g = normalize(vec2(sdRoundBox(p + vec2(1.0, 0.0) - bc, R_BB, 56.0) - d,
                            sdRoundBox(p + vec2(0.0, 1.0) - bc, R_BB, 56.0) - d) + 1e-6);
    vec3 c = uPal1 * (1.04 - 0.14 * (p.y - bc.y) / R_BB.y);
    c = lit(c, g, d, 22.0, vec2(0.0));
    vec2 sc = rSC(), sb = rSB();
    float db = sdRoundBox(p - sc, sb + vec2(20.0), 38.0);           // the bezel
    c = mix(c, uPal2 * (1.15 - 0.25 * (p.y - sc.y) / sb.y), cover(db));
    c = mix(c, uPal1 * 0.55, cover(abs(db) - 1.2) * 0.6);
    vec2 rq = p - (bc + vec2(214.0, -160.0));                        // a rainbow, top right
    rq.x -= rq.y * 0.35;
    float below = step(sc.y + sb.y + 20.0, p.y);                    // (the controls: under the screen)
    if (abs(rq.y) < 22.0 && rq.x > 0.0 && rq.x < 35.0) {
        float k = floor(rq.x / 7.0);
        vec3 rb = k < 0.5 ? vec3(0.90, 0.22, 0.18) : k < 1.5 ? vec3(0.98, 0.56, 0.12)
                : k < 2.5 ? vec3(0.98, 0.84, 0.20) : k < 3.5 ? vec3(0.30, 0.74, 0.30)
                : vec3(0.22, 0.48, 0.88);
        c = mix(c, rb, 0.95 * step(mod(rq.x, 7.0), 5.6));
    }
    vec2 dq = p - (bc + vec2(-210.0, 152.0));                        // the D-pad
    if (below > 0.5 && abs(dq.x) < 44.0 && abs(dq.y) < 44.0) {
        float dp = min(sdRoundBox(dq, vec2(30.0, 10.0), 3.0), sdRoundBox(dq, vec2(10.0, 30.0), 3.0));
        float sh = min(sdRoundBox(dq - vec2(2.0, 4.0), vec2(30.0, 10.0), 3.0),
                       sdRoundBox(dq - vec2(2.0, 4.0), vec2(10.0, 30.0), 3.0));
        c = mix(c, c * 0.5, exp(-max(sh, 0.0) / 3.0) * 0.4);
        c = mix(c, uPal2 * (1.25 - 0.4 * dq.y / 30.0), cover(dp));
    }
    for (int k = 0; k < 2; k++) {                                     // two red buttons
        if (below < 0.5 || p.x < bc.x + 150.0) break;
        vec2 bq = p - (bc + vec2(186.0 + 48.0 * float(k), 160.0 - 22.0 * float(k)));
        float bd = length(bq) - 17.0;
        c = mix(c, c * 0.55, exp(-max(length(bq - vec2(2.0, 4.0)) - 17.0, 0.0) / 3.0) * 0.5);
        vec3 red = uPal3 * (1.15 - 0.5 * clamp((bq.y + bq.x * 0.3) / 17.0, -1.0, 1.0));
        red += vec3(0.5) * exp(-dot(bq + vec2(6.0, 7.0), bq + vec2(6.0, 7.0)) / 20.0);
        c = mix(c, red, cover(bd));
    }
    vec2 gq = p - (bc + vec2(0.0, 166.0));                            // the speaker's slots
    if (abs(gq.x) < 48.0 && abs(gq.y) < 14.0)
        c = mix(c, c * 0.45, cover(sdRoundBox(vec2(mod(gq.x + 48.0, 16.0) - 8.0, gq.y),
                                              vec2(3.0, 12.0), 3.0)));
    vec2 lq = p - (bc + vec2(-214.0, -160.0));                        // the power light
    float led = length(lq) - 6.0;
    float lon = 0.35 + 0.65 * (1.0 - uChC.y) * (0.75 + 0.25 * sin(uT * 2.0 * uChC.y + 1.0));
    c = mix(c, mix(uPal2, uPal0 * 1.3, lon), cover(led));
    acc.rgb += uPal0 * 0.35 * lon * exp(-max(led, 0.0) / 5.0) * a;
    over(acc, c * mix(1.0, uDim, 0.4), a);
}

void rCart(vec2 p, inout vec4 acc) {                                  // a cartridge, in its side slot
    vec2 q = p - (rBC() + vec2(R_BB.x + 16.0, -40.0));
    float d = sdRoundBox(q, vec2(30.0, 46.0), 5.0);
    float a = cover(d);
    if (a <= 0.0) return;
    vec3 c = vec3(0.42, 0.42, 0.44) * (1.1 - 0.3 * q.x / 30.0);
    vec2 lq = q - vec2(4.0, -6.0);
    float lab = sdRoundBox(lq, vec2(18.0, 26.0), 3.0);
    c = mix(c, mix(uPal3, uPal0, step(0.0, lq.y)), cover(lab));
    c = mix(c, c * 0.6, cover(abs(q.y - 34.0) - 1.0) * step(abs(q.x), 26.0));
    over(acc, c, a);
}

vec3 soft(vec2 p, vec2 uv) {
    vec2 vq = uv - vec2(0.5, 0.46);
    vec3 col = vec3(0.022, 0.018, 0.014) * (1.0 - 1.5 * dot(vq, vq));
    float on = smoothstep(0.55, 1.0, uChD.w);
    float d = min(glowEye(p, uEye0, uLidA0), glowEye(p, uEye1, uLidA1));
    if (uMouthK.z > 0.01) d = min(d, mouthD(p - uMouth.xy));
    float g = exp(-max(d, 0.0) / 16.0) * 0.5 + 0.25 * exp(-max(d, 0.0) / 50.0);
    float k = uChA.w * on * (1.0 - 0.6 * uChC.y) * uDim;
    if (uChF.z > 0.5) {
        g *= smoothstep(6.0, -12.0, sdRoundBox(p - rSC(), rSB(), 26.0));
        float dbody = sdRoundBox(p - rBC() - vec2(0.0, 16.0), R_BB, 56.0);
        col *= 1.0 - 0.7 * exp(-max(dbody, 0.0) / 26.0);
    } else {
        float ds = sdRoundBox(p - rSC(), rSB(), 40.0);
        col += uPal0 * 0.016 * smoothstep(40.0, -60.0, ds) * on;
    }
    return col + uPal0 * g * k * 0.32;
}

void shape(vec2 p, inout vec4 acc) {
    if ((uShape > 4.5 && uShape < 8.5) || uShape > 11.5) {   // props, the state's marks
        props(p, acc);                               // (one call: see props)
        return;
    }
    if (uShape < 3.5) rBody(p, acc);
    else if (uShape < 8.5) {}                      // (props: above)
    else if (uShape < 9.5) rScreen(p, acc);
    else rCart(p, acc);
}
"""

# ── PIXEL: a pure matrix of luminous cells ────────────────────────────────────
_PIXEL = """
#define GRID
const float PITCH = 14.0;
const vec2 G_HALF = vec2(322.0, 196.0);           // 46 × 28 cells
vec2 gC() { return uChA.xy + vec2(0.0, 4.0); }

// one eye in cells: cyan to blue, its pupil a dark block with a glint;
// a heart in love, a star when excited, a line when shut
float pEye(vec2 cc, vec4 e, vec4 la, vec4 lb, vec4 pu, float side, inout vec3 c) {
    if (abs(cc.x - e.x) > e.z * 0.5 + 2.0 * PITCH || abs(cc.y - e.y) > e.w * 0.5 + 2.0 * PITCH)
        return 0.0;
    vec2 q;
    float d = eyeD(cc, e, la, lb, side, q);
    float v = 0.0;
    if (d < 0.0) {
        c = mix(uPal0, uPal1, clamp(q.y / max(e.w, 1.0) + 0.5, 0.0, 1.0));
        c = mix(c, uPal2, uMorph.x);
        v = 1.0;
        vec2 pq = q - floor(pu.xy / PITCH + 0.5) * PITCH;
        float pr = max(pu.z * 0.62, PITCH);
        if (uMorph.w > 0.3) {
            if (sdStar5(vec2(pq.x, -pq.y) / (pr * 1.5), 1.0, 0.45) < 0.0) c = uPal3;
        } else if (pu.w > 0.3 && abs(pq.x) < pr && abs(pq.y) < pr) {
            if (pq.x < -pr + PITCH && pq.y < -pr + PITCH) c = vec3(1.0);
            else v = 0.0;
        }
    }
    if (seamD(q, e, la, lb, side) < PITCH * 0.35) {
        c = uPal0;
        v = max(v, lb.y);
    }
    return v;
}

// a pattern's cell: lit where a shape (unit size, centred at `at`, s px) covers it
float pat(float d) { return d < 0.0 ? 1.0 : 0.0; }

vec4 pCell(vec2 cc, vec2 ci) {
    vec3 c = vec3(0.0);
    float v = pEye(cc, uEye0, uLidA0, uLidB0, uPupil0, -1.0, c);
    vec3 c1 = vec3(0.0);
    float v1 = pEye(cc, uEye1, uLidA1, uLidB1, uPupil1, 1.0, c1);
    if (v1 > v) { v = v1; c = c1; }
    vec2 mq = abs(cc - uMouth.xy);
    if (uMouthK.z > 0.01 && mq.x < uMouth.z * 0.5 + uMouth.w + PITCH
            && mq.y < uMouth.w * 1.6 + abs(uMouthK.x) + abs(uMouthSlant) + 2.0 * PITCH) {
        float inner, teeth, tongue;
        float d = mouthSDF(cc - uMouth.xy, inner, teeth, tongue);
        if (d < 0.0) {
            if (inner >= 0.0) { c = uPal2; v = uMouthK.z; }
            else if (teeth > 0.5) { c = vec3(1.0); v = 0.9; }
            else if (tongue > 0.5) { c = vec3(1.0, 0.25, 0.30); v = 0.6; }
        }
    }
    vec2 g = cc - gC();
    float ax = abs(ci.x + 0.5);
    if (ax > 21.0) {                                   // the side bars: her voice, the music
        float level = max(max(uChF.x * (0.15 + 0.95 * uEnergy), uChG.x * (0.2 + 0.8 * uEnergy)),
                          uChE.w * (0.08 + 0.92 * uChH.x));       // listening: the mic
        float row = (G_HALF.y - g.y) / (2.0 * G_HALF.y);
        if (row < level) { c = mix(uPal0, uPal2, row); v = 0.9; }
    }
    float on = 0.0;
    if (uChC.x > 0.3 && uChF.x < 0.5) {                // thinking: "…" filling up
        for (int k = 0; k < 3; k++) {
            vec2 at = vec2(uEye1.x + uEye1.z * 0.5 + 18.0 + 28.0 * float(k), uEye1.y - uEye1.w * 0.5 - 20.0);
            float lt = step(float(k), mod(floor(uT * 3.0), 4.0) - 0.5);
            if (length(cc - at) < 8.0) { c = uPal0; v = max(v, (0.25 + 0.75 * lt) * uChC.x); }
        }
    }
    if (uChD.x + uChD.y > 0.2) {                       // curious, confused: "?"
        if (pat(sdQuestion((cc - (gC() + vec2(262.0, -96.0))) / 76.0)) > 0.5) {
            c = uPal3;
            v = max(v, max(uChD.x, uChD.y));
        }
    }
    float bang = max(uChC.w, uChB.w);
    if (bang > 0.2 && pat(sdBang((cc - (gC() + vec2(-272.0, -112.0))) / 76.0)) > 0.5) {
        c = vec3(1.0, 0.28, 0.25);                     // alert, surprised: "!"
        v = max(v, bang);
    }
    if (uChC.y > 0.05) {                               // asleep: pixel Zs rising
        for (int k = 0; k < 2; k++) {
            float fk = float(k);
            float t = fract(uT * 0.3 + fk * 0.5);
            vec2 at = gC() + vec2(170.0 + 70.0 * fk, -60.0 - floor(t * 6.0) * PITCH);
            vec2 z = floor((cc - at) / PITCH);
            if (z.x >= 0.0 && z.y >= 0.0 && z.x <= 4.0 && z.y <= 4.0
                    && (z.y < 0.5 || z.y > 3.5 || abs(z.x - (4.0 - z.y)) < 0.5)) {
                c = uPal0;
                v = max(v, uChC.y * (1.0 - t) * 1.6);
            }
        }
    }
    if (uChB.y > 0.05) {                               // sad: a pixel tear falling
        float t = fract(uT * 0.6);
        vec2 d = floor((cc - vec2(uEye0.x - uEye0.z * 0.25,
                                  uEye0.y + uEye0.w * 0.5 + PITCH * (1.0 + floor(t * 6.0)))) / PITCH);
        if ((d.x == 0.0 && (d.y == 0.0 || d.y == 2.0)) || (abs(d.x) <= 1.0 && d.y == 1.0)) {
            c = vec3(0.45, 0.75, 1.0);
            v = max(v, uChB.y * (1.0 - t));
        }
    }
    if (uChB.z > 0.05) {                               // cross: a pulsing pixel anger mark
        vec2 d = floor((cc - vec2(uEye1.x + uEye1.z * 0.5 + 34.0, uEye1.y - uEye1.w * 0.5 - 24.0)) / PITCH + 0.5);
        vec2 a = abs(d);
        if (max(a.x, a.y) == 2.0 && min(a.x, a.y) >= 1.0) {
            c = vec3(1.0, 0.25, 0.25);
            v = max(v, uChB.z * (0.55 + 0.45 * step(0.35, fract(uT * 2.0))));
        }
    }
    if (uChH.y < 0.999) {                              // waking: a line scans down, lighting it up
        float row = floor(uChH.y * 30.0) - 15.0;
        if (ci.y == row) { c = uPal0; v = max(v, 1.0); }
        else if (ci.y > row) v *= 0.0;
    }
    float cel = max(uChC.z, 0.8 * uMorph.x);
    if (uAcc.x > 0.5 && cel > 0.1) {                   // pixel hearts, rising
        for (int k = 0; k < 2; k++) {
            float fk = float(k);
            float t = fract(uT * 0.35 + fk * 0.5);
            vec2 at = gC() + vec2((fk < 0.5 ? -1.0 : 1.0) * 286.0, 110.0 - 240.0 * t);
            vec2 hq = (cc - at) / 64.0;
            if (sdHeart(vec2(hq.x, 0.55 - hq.y)) < 0.0) { c = uPal2; v = max(v, cel * sin(3.14159 * t)); }
        }
    }
    if (uAcc.y > 0.5 && uChC.z > 0.1) {                // pixel stars blinking in steps
        for (int k = 0; k < 3; k++) {
            float fk = float(k);
            vec2 at = gC() + vec2(-200.0 + 200.0 * fk, -150.0 + 20.0 * mod(fk, 2.0));
            float blink = step(0.4, fract(uT * 2.0 + fk * 0.33));
            if (sdStar5(vec2(cc.x - at.x, at.y - cc.y) / 40.0, 1.0, 0.45) < 0.0) {
                c = uPal3;
                v = max(v, uChC.z * blink);
            }
        }
    }
    if (uAcc.z > 0.5 && uChF.x > 0.5) {                // a speech bubble while she talks
        vec2 bq = g - vec2(236.0, -150.0);
        float box = sdRoundBox(bq, vec2(56.0, 30.0), 12.0);
        float tail = sdSeg(bq, vec2(-30.0, 30.0), vec2(-50.0, 52.0)) - 6.0;
        if (abs(box) < 7.0 || (tail < 0.0 && box > 0.0)) { c = vec3(0.92); v = max(v, 0.8); }
        for (int k = 0; k < 3; k++) {
            float lt = step(float(k), mod(floor(uT * 4.0), 4.0) - 0.5);
            if (length(bq - vec2(-28.0 + 28.0 * float(k), 0.0)) < 7.0) { c = uPal0; v = max(v, lt); }
        }
    }
    if (uAcc.w > 0.5 && uChG.x > 0.5) {                // headphones while the music plays
        float band = abs(length(g - vec2(0.0, 90.0)) - 300.0);
        if (band < 8.0 && g.y < -110.0) { c = uPal2; v = max(v, 0.85); }
        if (ax > 18.0 && ax < 20.9 && g.y > -110.0 && g.y < 10.0) { c = uPal2 * 0.9; v = max(v, 0.85); }
    }
    vec4 hd = handArt(cc, PITCH);
    if (hd.y > 0.5) {                  // a hand, a heart: on top, the cells round it dark
        c = hd.z > 7.5 ? mix(uPal2, vec3(1.0), 0.15) : mix(uPal0, uPal1, hd.w);
        v = hd.x * (hd.z > 7.5 ? 0.6 + 0.4 * step(0.5, uHand0.z) : 1.0);
    }
    return vec4(c, v);
}

vec4 gridCell(vec2 ci) {
    return pCell(gC() + (ci + 0.5) * PITCH, ci);
}

void pGrid(vec2 p, inout vec4 acc) {
    vec2 rel = p - gC();
    if (abs(rel.x) > G_HALF.x || abs(rel.y) > G_HALF.y) return;
    vec2 ci = floor(rel / PITCH);
    if (uChD.z > 0.5) {                                // a glitch: bands of rows slip sideways
        float h = hash(vec2(floor(ci.y / 3.0), floor(uT * 15.0)));
        if (h > 0.62) ci.x += floor((h - 0.81) * 12.0);
    }
    vec4 cell = cellAt(ci);
    vec2 f = rel - (floor(rel / PITCH) + 0.5) * PITCH;
    float db = sdRoundBox(f, vec2(PITCH * 0.38), 2.5);
    float px = cover(db);
    float bright = uDim * (1.0 - 0.55 * uChC.y);
    vec3 lc = cell.rgb * cell.a * bright;
    if (uChD.z > 0.5) lc = lc.brg * 0.6 + lc * 0.6;
    vec3 col = lc * (px + 0.18 * exp(-max(db, 0.0) / 2.5))
             + uPal1 * 0.045 * px * (1.0 - cell.a);    // the matrix, unlit
    acc.rgb += col;
}

vec3 soft(vec2 p, vec2 uv) {
    vec2 vq = uv - vec2(0.5, 0.46);
    vec3 col = vec3(0.010, 0.012, 0.024) * (1.0 - 1.4 * dot(vq, vq));
    float de = min(glowEye(p, uEye0, uLidA0), glowEye(p, uEye1, uLidA1));
    float dm = uMouthK.z > 0.01 ? mouthD(p - uMouth.xy) : 1e5;
    float k = uChA.w * uDim * (1.0 - 0.55 * uChC.y);
    col += mix(uPal0, uPal1, 0.5) * (0.30 * exp(-max(de, 0.0) / 18.0) + 0.12 * exp(-max(de, 0.0) / 60.0)) * k;
    col += uPal2 * 0.22 * exp(-max(dm, 0.0) / 16.0) * k * uMouthK.z;
    return col;
}

void shape(vec2 p, inout vec4 acc) {
    if ((uShape > 4.5 && uShape < 8.5) || uShape > 11.5) {   // props, the state's marks
        props(p, acc);                               // (one call: see props)
        return;
    }
    pGrid(p, acc);
}
"""

# ── MOCHI: a plush bunny round a dark display ─────────────────────────────────
# Velvet, not plastic: soft wrapped light, the fibres bright where the surface
# turns away, a fuzzy outline, the nap's faint grain — all fixed to the face
# (no shimmer). mochi_rig.py moves her ears, paws, eye glyphs and mouths
# (uMoEar, uMoEye, uMoFace, uMoMouth, uMoPaw, uMoBody, uMoIris).
_MOCHI = """
vec2 mBC() { return uChA.xy + vec2(0.0, 70.0); }
const vec2 M_BB = vec2(232.0, 148.0);      // the head's half size (the pods beside it)
const vec2 M_DC = vec2(0.0, -6.0);         // the display, from the head's centre
const vec2 M_DB = vec2(182.0, 107.0);

float mhash(vec2 p) {                      // (no sin: cheaper on the Pi's GPU)
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mhash(i), mhash(i + vec2(1.0, 0.0)), f.x),
               mix(mhash(i + vec2(0.0, 1.0)), mhash(i + vec2(1.0, 1.0)), f.x), f.y);
}

// fur: an outline that breaks up by a pixel or two
float fuzz(vec2 p) {
    return (vnoise(p * 0.9) - 0.5) * 2.0;
}

// velvet over a padded shape: d < 0 inside, g its outward direction, bw how
// wide its edge rolls over, dome the whole surface's tip; fp: the nap's place
vec3 plush(vec3 base, vec2 g, float d, float bw, vec2 dome, vec2 fp) {
    float roll = 1.0 - clamp(-d / bw, 0.0, 1.0);
    vec3 n = normalize(vec3(g * (1.6 * roll * roll) + dome, 1.0));
    float lc = cos(uTilt), ls = sin(uTilt);
    vec3 L = normalize(vec3(-0.30, -0.78, 0.62));
    L.xy = vec2(lc * L.x - ls * L.y, ls * L.x + lc * L.y);
    float wrap = clamp((dot(n, L) + 0.5) / 1.5, 0.0, 1.0);
    vec3 c = mix(base * base * vec3(0.80, 0.62, 0.72), base * 1.04, clamp(0.08 + 0.96 * wrap, 0.0, 1.0));
    c = mix(c, base * base * vec3(0.60, 0.44, 0.54), smoothstep(0.05, 0.85, n.y) * 0.5);   // the underside: rosy, not grey
    c += vec3(1.0, 0.88, 0.93) * pow(1.0 - n.z, 1.5) * (0.10 + 0.22 * wrap);   // the fibres' rim
    c += vec3(1.0, 0.95, 0.97) * 0.09 * pow(max(dot(n, normalize(L + vec3(0.0, 0.0, 1.0))), 0.0), 6.0);
    return c * (0.955 + 0.09 * vnoise(fp * 0.55));
}

// the head's own frame, squashed onto its base (a landing)
vec2 mLocal(vec2 p) {
    vec2 q = p - mBC();
    float sq_ = uMoBody.x;
    q.y = (q.y - M_BB.y) / (1.0 - sq_) + M_BB.y;
    q.x /= 1.0 + 0.6 * sq_;
    return q;
}

float mHead(vec2 q) { return sdRoundBox(q, M_BB, 124.0); }
float mPods(vec2 q) { return ellD(vec2(abs(q.x) - 228.0, q.y - 10.0), vec2(46.0, 72.0)); }
float mBody(vec2 q) { return min(mHead(q), mPods(q)); }
float mDisp(vec2 q) { return sdRoundBox(q - M_DC, M_DB, 74.0); }

// the display: dark glass, a faint sheen, its edge lit pink, rosy cheeks
vec3 mGlassCol(vec2 p, vec2 q, float dd) {
    vec2 dq = q - M_DC;
    vec3 disp = vec3(0.036, 0.022, 0.034) * (1.0 - 0.35 * dot(dq / M_DB, dq / M_DB));
    vec2 hq = (dq / M_DB - vec2(-0.45, -0.62)) * vec2(2.0, 4.5);
    disp += vec3(0.045, 0.035, 0.045) * exp(-dot(hq, hq));
    disp += uPal3 * 0.11 * exp(dd / 8.0);
    disp *= 1.0 - 0.6 * exp(dd / 10.0) * smoothstep(20.0, -90.0, dq.y);  // the rim's shadow inside
    float blush = 0.55 * uBlush.z + 0.35 * uChF.x * uEnergy + 0.65 * uMoFace.w;
    if (blush > 0.01) {                                                  // rosy cheeks (puffed: rounder)
        for (int k = 0; k < 2; k++) {
            vec2 bq = (p - vec2(uChA.x + (k == 0 ? -152.0 : 152.0), uEye0.y + 66.0))
                      / (vec2(30.0, 15.0) * (1.0 + 0.35 * vec2(uMoBody.z, 1.6 * uMoBody.z)));
            disp += uPal3 * blush * 0.6 * exp(-dot(bq, bq) * 1.4);
        }
    }
    return disp;
}

// the casing comes in four strips round the glass's middle (the soft pass
// paints that: none of this per pixel there); each strip draws only the
// points it owns, so where their boxes overlap nothing is drawn twice
const vec2 M_GB = vec2(156.0, 82.0);

// the glass's middle in its own box, opaque: with the radio's picture on
// (drawn after the soft pass) it would show through her face otherwise
void mGlass(vec2 p, inout vec4 acc) {
    vec2 q = mLocal(p);
    vec2 rq = q - M_DC;
    if (abs(rq.x) >= M_GB.x || abs(rq.y) >= M_GB.y) return;       // (the strips' own)
    over(acc, mGlassCol(p, q, mDisp(q)) * mix(1.0, uDim, 0.35), 1.0);
}

void mBodyDraw(vec2 p, inout vec4 acc) {
    vec2 q = mLocal(p);
    vec2 rq = q - M_DC;
    float part = floor(fract(uShape) * 10.0 + 0.5);   // 0 top, 1 bottom, 2 left, 3 right
    bool own = part < 0.5 ? rq.y < -M_GB.y : part < 1.5 ? rq.y >= M_GB.y
             : abs(rq.y) < M_GB.y && (part < 2.5 ? rq.x < -M_GB.x : rq.x >= M_GB.x);
    if (!own) return;
    float dd = mDisp(q);
    if (dd < -4.0 && abs(q.x) < 170.0) {             // inside the glass: none of the plush's maths
        over(acc, mGlassCol(p, q, dd) * mix(1.0, uDim, 0.35), 1.0);
        return;
    }
    float dh = mHead(q);
    float dp = mPods(q);
    if (min(dh, dp) > 2.5) return;
    float fz = min(dh, dp) > -4.0 || abs(dp) < 4.0 ? fuzz(q) : 0.0;   // (fur: only at an edge)
    float a = cover(min(dh, dp) + fz);
    if (a <= 0.0) return;
    // the casing: padded, rolling down at its edge and into the display, where
    // a soft rim rises round it first
    vec3 c = vec3(0.0);
    if (dd > -1.5) {
        vec2 gh = dh > -58.0 ? normalize(vec2(mHead(q + vec2(1.0, 0.0)) - dh,      // (deeper in:
                                              mHead(q + vec2(0.0, 1.0)) - dh) + 1e-6) // no roll)
                             : vec2(0.0);
        vec2 gd = dd < 40.0 ? normalize(vec2(mDisp(q + vec2(1.0, 0.0)) - dd,
                                             mDisp(q + vec2(0.0, 1.0)) - dd) + 1e-6) : vec2(0.0);
        float rimS = 1.4 * exp(-max(dd, 0.0) / 6.0) - 0.45 * exp(-sq((dd - 20.0) / 10.0));
        vec2 dome = q / M_BB * vec2(0.20, 0.26) - gd * rimS;
        vec3 base = mix(uPal0, uPal1, clamp(0.22 + 0.42 * q.y / M_BB.y, 0.0, 1.0));
        c = plush(base, gh, dh, 58.0, dome, q);
        c *= 1.0 - 0.30 * exp(-max(dd, 0.0) / 3.5);                      // the crease round the glass
        c *= 1.0 - 0.22 * exp(-max(dp, 0.0) / 9.0) * step(0.0, dp);      // the pods' shade on it
    }
    if (dd < 0.5) c = mix(c, mGlassCol(p, q, dd), cover(dd));
    // the pods: round cushions on her sides, a ring of light round each (the
    // side light: it wakes with the mic and her voice)
    float pa = cover(dp + fz);
    if (pa > 0.0) {
        float side = sign(q.x);
        vec2 pq = vec2(abs(q.x) - 228.0, q.y - 10.0);
        vec2 gp = normalize(pq / vec2(46.0 * 46.0, 72.0 * 72.0) + 1e-6);
        gp.x *= side;
        vec3 pc = plush(mix(uPal0, uPal1, 0.30 + 0.30 * pq.y / 72.0), gp, dp, 30.0,
                        vec2(side * pq.x / 46.0 * 0.25, 0.0), q);
        float cd = ellD(pq - vec2(20.0, 0.0), vec2(17.0, 54.0));
        pc = mix(pc, pc * 1.05 + vec3(0.03), cover(cd) * 0.8);
        float ring = uMoBody.y + 0.45 * uChF.x * uEnergy;
        vec3 lc = mix(uPal3, vec3(1.0), 0.55);
        pc = mix(pc, lc, cover(abs(cd) - 1.8) * (0.25 + 0.75 * clamp(ring, 0.0, 1.0)));
        pc += lc * 0.35 * ring * exp(-abs(cd) / 5.0);
        c = mix(c, pc, pa);
    }
    over(acc, c * mix(1.0, uDim, 0.35), a);
}

// a bunny ear from its base b, leaning out by `lean` (rad), the top half
// flopped over by `flop`; q its own frame (y up the ear negative)
float earD(vec2 p, vec2 b, float side, float lean, float flop, out vec2 q) {
    q = rot2(p - b, -side * lean);
    float k = smoothstep(-60.0, -120.0, q.y);
    vec2 r = q - vec2(0.0, -64.0);
    q = vec2(0.0, -64.0) + rot2(r, -side * flop * 1.3 * k);
    float yn = clamp(-q.y / 150.0, 0.0, 1.0);
    vec2 eq = vec2(q.x / (0.74 + 0.30 * smoothstep(0.0, 0.65, yn)), q.y + 76.0);
    return ellD(eq, vec2(40.0, 78.0));
}

void mEar(vec2 p, float side, inout vec4 acc) {
    {
        vec2 b = mBC() + vec2(side * 118.0, -M_BB.y + 24.0);
        float lean = side < 0.0 ? uMoEar.x : uMoEar.y;
        float flop = side < 0.0 ? uMoEar.z : uMoEar.w;
        vec2 q, q2;
        float d = earD(p, b, side, lean, flop, q);
        if (d > 2.5) return;
        float a = cover(d + (d > -4.0 ? fuzz(q) : 0.0));
        if (a <= 0.0) return;
        vec2 g = vec2(0.0);
        if (d > -20.0)
            g = normalize(vec2(earD(p + vec2(1.0, 0.0), b, side, lean, flop, q2) - d,
                               earD(p + vec2(0.0, 1.0), b, side, lean, flop, q2) - d) + 1e-6);
        vec3 c = plush(mix(uPal0, uPal1, 0.12 + 0.20 * clamp(q.y / -150.0, 0.0, 1.0)), g, d, 20.0,
                       vec2(0.0), q);
        // the inner ear: a pink hollow, deeper toward the base, its rim in shade
        float di = ellD(vec2(q.x / (0.74 + 0.30 * smoothstep(0.0, 0.65, -q.y / 150.0)), q.y + 84.0),
                        vec2(19.0, 56.0));
        vec3 inner = mix(uPal3, uPal0, 0.40) * (0.74 + 0.26 * smoothstep(-20.0, -125.0, q.y));
        inner *= 0.82 + 0.18 * smoothstep(0.0, -9.0, di);
        c = mix(c, inner, cover(di + 0.5 * fuzz(q + 9.0)) * 0.94);
        c *= 0.70 + 0.30 * smoothstep(0.0, -50.0, q.y);                // the head's shade at its base
        over(acc, c * mix(1.0, uDim, 0.35), a);
    }
}

// in front of the head: the flower
void mFront(vec2 p, inout vec4 acc) {
    if (uAcc.y > 0.5) {
        vec2 fq = rot2(p - (mBC() + vec2(152.0, -134.0)), 0.25);
        float pet = 1e5;
        for (int k = 0; k < 5; k++) {
            float an = float(k) * 1.2566;
            pet = min(pet, length(fq - 11.0 * vec2(cos(an), sin(an))) - 9.5);
        }
        over(acc, vec3(0.0), 0.3 * exp(-max(pet, 0.0) / 4.0) * (1.0 - cover(pet)));   // its shade
        float r = length(fq);
        vec3 c = mix(vec3(1.0, 0.97, 0.98), vec3(1.0, 0.84, 0.90), smoothstep(8.0, 20.0, r) * 0.7);
        c *= 0.86 + 0.14 * smoothstep(0.0, -4.0, pet) - 0.08 * clamp(fq.y / 20.0, -1.0, 1.0);
        over(acc, c, cover(pet));
        vec3 yc = vec3(1.0, 0.80, 0.28) * (1.08 - 0.35 * clamp((fq.y + fq.x) / 10.0, -1.0, 1.0));
        over(acc, yc, cover(r - 6.5));
    }
}

// the eyes' glyphs (mochi_rig): 1 ◠ happy, 2 > < squeezed, 3 — asleep, 4 a
// flat top, 5 a heart (beating)
float mGlyph(vec2 q, vec2 b, float kind, float side) {
    float r = min(b.x, b.y);
    float th = 0.15 * r;
    if (kind > 4.5) {
        float s = r * 1.55 * (1.0 + 0.08 * pow(max(0.0, sin(uT * 7.0)), 3.0));
        return sdHeart(vec2(q.x, 0.52 * s - q.y) / s) * s;
    }
    if (kind < 1.5) {
        vec2 o = q - vec2(0.0, 0.26 * r);
        float rr = 0.64 * r;
        if (o.y > 0.0) return length(vec2(abs(o.x) - rr, o.y)) - th;
        return abs(length(o) - rr) - th;
    }
    if (kind < 2.5) {
        float ax = -side * 0.42 * r;                   // its point toward the middle
        vec2 a2 = vec2(ax, 0.0);
        return min(sdSeg(q, vec2(-ax, -0.5 * r), a2), sdSeg(q, a2, vec2(-ax, 0.5 * r))) - th;
    }
    if (kind < 3.5) {
        float x = clamp(q.x, -0.62 * r, 0.62 * r);
        return length(vec2(q.x - x, q.y - 0.1 * r * sq(x / (0.62 * r)))) - th * 0.85;
    }
    return max((length(q / (b * 0.9)) - 1.0) * r * 0.9, -0.06 * r - q.y);
}

// her eye's inside, all × the eye's radius (round, like the eye);
// uMoIris scales the iris and the pupil per look, .zw where it looks
const float M_IRIS_R = 0.60;                  // the iris: 60% of the eye's width
const float M_PUPIL_R = 0.50;                 // the pupil: half the iris's
const float M_IRIS_FOLLOW = 1.0;              // how far the iris follows the gaze in the eye
const vec2  M_GLINT = vec2(-0.42, -0.42);     // the glint, × the pupil (up by the light)
const float M_GLINT_R = 0.17;                 // …its radius, × the pupil's
const vec2  M_GLINT2 = vec2(0.42, 0.40);      // a much smaller one down the other side
const float M_GLINT2_R = 0.07;
const vec3  M_IRIS_TOP = vec3(0.90, 0.38, 0.60);   // soft rose, a touch deeper on top…
const vec3  M_IRIS_LOW = vec3(0.98, 0.52, 0.71);   // …lighter below
const vec3  M_PUPIL_COL = vec3(0.21, 0.06, 0.14);  // dark plum

// the iris, its pupil and glints over the eye's colour c; q the eye's own
// point, r its radius, at where the iris looks; im: how much is iris
vec3 mIris(vec3 c, vec2 q, float r, vec2 at, float open, out float im) {
    im = 0.0;
    float ir_ = M_IRIS_R * uMoIris.x * r;
    // out to the rim (a fifth tucked under it), eased in over the last 40%
    float lim = max(r - 0.8 * ir_, 1.0), al = length(at);
    vec2 off = al > 0.6 * lim ? at * (lim - 0.16 * lim * lim / (al - 0.2 * lim)) / al : at;
    vec2 iq = q - off;
    vec2 gq = iq + 0.3 * off;                              // the glints lag: they're the light's
    float id = length(iq) - ir_;
    if (open < 0.01 || id > 2.0) return c;
    im = smoothstep(1.5, -1.5, id) * open;                 // a soft edge, no outline
    vec3 col = mix(M_IRIS_TOP, M_IRIS_LOW, smoothstep(-ir_, ir_, iq.y));
    float pr = min(M_PUPIL_R * uMoIris.y * M_IRIS_R * r, 0.8 * ir_);
    col = mix(col, M_PUPIL_COL, smoothstep(1.2, -1.2, length(iq) - pr));
    float sh = 1.0 + 0.2 * uMoFace.z;                      // excited: a little bigger
    vec3 wc = vec3(1.0, 0.97, 0.99);
    col = mix(col, wc, smoothstep(0.8, -0.8, length(gq - M_GLINT * pr) - M_GLINT_R * pr * sh));
    col = mix(col, wc, smoothstep(0.7, -0.7, length(gq - M_GLINT2 * pr) - M_GLINT2_R * pr * sh) * 0.6);
    return mix(c, col, im);
}

void mEye(vec2 p, vec4 e, vec4 la, vec4 lb, vec4 pu, float side, inout vec4 acc) {
    vec2 q;
    float d = eyeD(p, e, la, lb, side, q);
    vec2 b = e.zw * 0.5;
    float r = min(b.x, b.y);
    float gk = side < 0.0 ? uMoEye.x : uMoEye.z;
    float ga = side < 0.0 ? uMoEye.y : uMoEye.w;
    if (ga > 0.003) d = mix(d, mGlyph(p - e.xy, b, gk, side), ga);
    float ds = seamD(q, e, la, lb, side) - 1.5;
    float a = cover(d);
    float sa = cover(ds) * lb.y * (1.0 - ga);
    if (a > 0.0) {
        // a glowing white, its edge pink
        vec3 c = mix(uPal2, mix(uPal3, uPal2, 0.5), smoothstep(-0.32 * r, 0.0, d) * 0.8);
        c = mix(c, mix(uPal3, uPal2, 0.35), smoothstep(-0.1, 1.0, q.y / b.y) * 0.3);
        // the iris: open eyes only (a glyph, a heart or a slit: just the glow;
        // the pout's flat top keeps it, peeking from below)
        float gone = (gk > 3.5 && gk < 4.5) ? 0.0 : ga;
        float open = (1.0 - lb.y) * (1.0 - gone) * (1.0 - uMorph.x)
                     * smoothstep(5.0, 16.0, (1.0 - la.x - la.w) * e.w);
        float im;
        c = mIris(c, q, r, pu.xy * M_IRIS_FOLLOW + uMoIris.zw * r, open, im);
        if (uMoFace.z > 0.01) {                         // starry: a sparkle in each (white on the iris)
            vec2 sq1 = (q - vec2(0.24 * b.x, 0.20 * b.y)) / (0.36 * r);
            float sp = min(sdSparkle(sq1), sdSparkle((q + vec2(0.28 * b.x, 0.30 * b.y)) / (0.2 * r)));
            c = mix(c, mix(uPal3, vec3(1.0, 0.97, 0.99), im), cover(sp * 0.3 * r) * uMoFace.z * (1.0 - ga));
        }
        over(acc, c * uDim, a);
    }
    if (sa > 0.0) over(acc, uPal2 * uDim, sa);
    // two little lashes at the outer corner, riding the upper lid
    float open = (1.0 - lb.y) * (1.0 - ga) * (1.0 - uMorph.x) * smoothstep(0.75, 0.4, la.x);
    if (open > 0.01 && q.x * side > 0.5 * b.x && q.y < 0.0) {
        float n = mix(lb.w, 2.0, uMorph.z);
        vec2 a1 = vec2(side * 0.70 * b.x, -b.y * pow(1.0 - pow(0.70, n), 1.0 / n));
        vec2 a2 = vec2(side * 0.90 * b.x, -b.y * pow(1.0 - pow(0.90, n), 1.0 / n));
        a1.y = max(a1.y, lidTop(a1.x, b, la, side).x) - 1.0;
        a2.y = max(a2.y, lidTop(a2.x, b, la, side).x) - 1.0;
        float ld = min(sdSeg(q, a1, a1 + vec2(side * 0.10, -0.22) * r),
                       sdSeg(q, a2, a2 + vec2(side * 0.22, -0.12) * r)) - 1.7;
        over(acc, mix(uPal2, uPal3, 0.3) * uDim, cover(ld) * open);
    }
    // the seam's halo only while the seam shows (asleep, the glyph replaces it:
    // its filled shape glowed as a grey oval under the "—")
    acc.rgb += vec3(1.0, 0.84, 0.92) * 0.30 * max(halo(d, 7.0), halo(ds, 7.0) * lb.y * (1.0 - ga))
               * (1.0 - max(a, sa)) * uChA.w * uDim;
}

// her own mouths (mochi_rig): 1 a small smile, 2 open, 3 "o", 4 a pout, 5 a
// tongue out, 6 flat, 7 a frown, 8 a tiny line; s its half width
float mMouthShape(vec2 q, float kind, float s, out float inner, out float tongue) {
    inner = 1e5;
    tongue = 0.0;
    float x = clamp(q.x, -s, s);
    float xn = x / s;
    float th = max(2.2, 0.13 * s);
    if (kind < 2.5) {                                    // a "D" on its back
        float h = kind < 1.5 ? 0.66 * s : 0.9 * s;
        float yt = -0.10 * h - 0.16 * h * sq(q.x / s);
        float d = max(ellD(q - vec2(0.0, -0.1 * h), vec2(s, h)), yt - q.y);
        inner = d + (kind < 1.5 ? 1.2 : 2.2);
        tongue = smoothstep(1.0, 0.8, length((q - vec2(0.0, 0.62 * h)) / vec2(0.58 * s, 0.42 * h)));
        return d;
    }
    if (kind < 3.5) {
        float d = ellD(q, vec2(0.85 * s, s));
        inner = d + 2.6;
        return d;
    }
    if (kind < 4.5) return length(vec2(q.x - x, q.y + 0.36 * s * (1.0 - xn * xn) - 0.1 * s)) - th;
    if (kind < 5.5) {
        float line = length(vec2(q.x - x, q.y - (0.26 * s * (1.0 - xn * xn) - 0.16 * s * xn))) - th;
        float tg = ellD(q - vec2(0.22 * s, 0.30 * s), vec2(0.24 * s, 0.32 * s));
        tongue = cover(tg);
        inner = tg;
        return min(line, tg);
    }
    if (kind < 6.5) return sdSeg(q, vec2(-s, 0.0), vec2(s, 0.0)) - th;
    if (kind < 7.5) return length(vec2(q.x - x, q.y + 0.30 * s * (1.0 - xn * xn) - 0.15 * s)) - th;
    return length(vec2(q.x - x, q.y - 0.24 * s * (1.0 - xn * xn))) - th;
}

void mMouth(vec2 p, inout vec4 acc) {
    float al = max(uMouthK.z, uMoMouth.y);
    if (al <= 0.01) return;
    vec2 q = p - uMouth.xy;
    float inner, teeth, tongue;
    float d = mouthSDF(q, inner, teeth, tongue);          // the pose's: her voice's shapes
    if (uMoMouth.y > 0.003) {
        float i2, t2;
        float d2 = mMouthShape(q, uMoMouth.x, uMoMouth.z, i2, t2);
        float k = uMouthK.z < 0.01 ? 1.0 : uMoMouth.y;
        d = mix(d, d2, k);
        inner = mix(inner, i2, k);
        tongue = mix(tongue, t2, k);
    }
    float a = cover(d) * al;
    vec3 c = mix(uPal3, vec3(1.0, 0.9, 0.95), 0.45);       // a soft pink, no teeth
    if (inner < 1e4)
        c = mix(c, mix(vec3(0.58, 0.10, 0.27), mix(uPal3, vec3(1.0), 0.25), 0.2 + 0.8 * tongue),
                cover(inner));
    over(acc, c * uDim, a);
    acc.rgb += uPal3 * 0.22 * halo(d, 5.0) * al * (1.0 - a) * uDim;
}

// a plush paw, unit size (y down): a round mitt with four toes round its top
// (curled: their knuckles; scissors: two round toes up) — a paw, no arm.
// Its outline only; the pads and seams in pawMarks
float pawSDF(vec2 q, float pose) {
    float d;
    if (pose < 1.5) {
        d = ellD(q - vec2(0.0, 0.05), vec2(0.46, 0.41));
        d = smin(d, min(length(q - vec2(-0.30, -0.19)), length(q - vec2(0.30, -0.19))) - 0.15, 0.07);
        d = smin(d, min(length(q - vec2(-0.11, -0.31)), length(q - vec2(0.11, -0.31))) - 0.16, 0.07);
    } else if (pose < 5.5) {
        d = ellD(q - vec2(0.0, 0.03), vec2(0.44, 0.41));
        for (int k = 0; k < 4; k++) {                    // the knuckles of the tucked toes
            float x = -0.27 + 0.18 * float(k);
            d = smin(d, length(q - vec2(x, -0.27 + 0.05 * abs(x) / 0.27)) - 0.13, 0.06);
        }
    } else {
        d = ellD(q - vec2(0.0, 0.05), vec2(0.43, 0.40));
        d = smin(d, min(sdSeg(q, vec2(-0.14, -0.24), vec2(-0.14, -0.46)),
                        sdSeg(q, vec2(0.14, -0.24), vec2(0.14, -0.46))) - 0.12, 0.06);
    }
    return d;
}

// open: four beans in an arc and a big three-lobed pad; curled: the tucked
// toes' seams; scissors: a bean on each toe. → the pads' distance
float pawMarks(vec2 q, float pose, out float seam) {
    seam = 1e5;
    if (pose < 1.5) {
        vec2 t0 = vec2(-0.28, -0.16), t1 = vec2(-0.11, -0.28), t2 = vec2(0.11, -0.28), t3 = vec2(0.28, -0.16);
        float b = smin(ellD(q - vec2(0.0, 0.13), vec2(0.19, 0.13)),
                       min(length(q - vec2(-0.11, 0.21)), length(q - vec2(0.11, 0.21))) - 0.10, 0.06);
        return min(b, min(min(ellD(q - t0, vec2(0.07, 0.085)), ellD(q - t1, vec2(0.075, 0.09))),
                          min(ellD(q - t2, vec2(0.075, 0.09)), ellD(q - t3, vec2(0.07, 0.085)))));
    }
    if (pose < 5.5) {
        for (int k = 0; k < 3; k++) {
            float x = -0.18 + 0.18 * float(k);
            seam = min(seam, sdSeg(q, vec2(x, -0.40 + 0.03 * abs(x) / 0.18), vec2(x * 0.92, -0.22)));
        }
        return 1e5;
    }
    return min(ellD(q - vec2(-0.14, -0.46), vec2(0.055, 0.065)), ellD(q - vec2(0.14, -0.46), vec2(0.055, 0.065)));
}

void mHand(vec2 p, inout vec4 acc) {
    bool right = uShape > 16.5;
    vec4 h = right ? uHand1 : uHand0;
    float pose = floor(h.w + 0.001);
    float al = clamp(fract(h.w + 0.001) / 0.98, 0.0, 1.0);
    float s = right ? uMoPaw.y : uMoPaw.x;
    if (al <= 0.0 || s <= 1.0) return;
    vec2 q = rot2(p - h.xy - vec2(0.0, 0.40 * s), -h.z) / s + vec2(0.0, 0.40);   // turned at the wrist
    if (!right) q.x = -q.x;
    if (length(q) > 0.56 + 16.0 / s) return;
    float d = pawSDF(q, pose) * s;
    // its soft shade on what's behind (a paw resting: on the floor too)
    float sd = ellD(q - vec2(0.03, 0.08), vec2(0.48, 0.44)) * s;
    over(acc, vec3(0.0), 0.32 * exp(-max(sd, 0.0) / 6.0) * al);
    float a = cover(d + (d > -4.0 ? fuzz(q * s) : 0.0)) * al;
    if (a <= 0.0) return;
    // its outward direction: the mitt's ellipse (the exact one — the outline
    // twice more, every pose's branch — cost the Pi 2 ms)
    vec2 g = normalize((q - vec2(0.0, 0.04)) / vec2(0.21, 0.17));
    if (!right) g.x = -g.x;
    g = rot2(g, h.z);
    vec3 c = plush(mix(uPal0, uPal1, clamp(0.12 + 0.4 * q.y, 0.0, 0.6)), g, d, 0.22 * s,
                   rot2(q * vec2(right ? 0.22 : -0.22, 0.22), h.z), q * s);
    if (q.y < 0.4) {                                   // the pads: soft raised pink, lit from above
        float seam;
        float bd = pawMarks(q, pose, seam) * s;
        vec3 bean = mix(uPal3 * 0.92, vec3(1.0, 0.70, 0.82), 0.4 * smoothstep(0.0, -6.0, bd));
        bean *= 1.0 - 0.18 * smoothstep(-3.0, 0.0, bd) * step(0.0, q.y - 0.05);
        c = mix(c, bean, cover(bd));
        c = mix(c, c * 0.72, cover(seam * s - 1.4) * 0.8);
    }
    over(acc, c * mix(1.0, uDim, 0.35), a);
}

vec3 soft(vec2 p, vec2 uv) {
    vec2 vq = uv - vec2(0.5, 0.55);
    vec3 col = vec3(0.050, 0.028, 0.044) * (1.0 - 1.4 * dot(vq, vq));
    vec2 q = p - mBC();
    col += uPal3 * 0.10 * exp(-max(mBody(q), 0.0) / 34.0) * uChA.w;     // a soft pink light round her
    float fl = length((q - vec2(0.0, M_BB.y + 4.0)) / vec2(290.0, 30.0));
    col *= 1.0 - 0.7 * exp(-fl * fl * 2.2);                              // her shade on the floor
    float dd = mDisp(q);                         // the glass's middle (the strips do its edge)
    if (dd < 0.0) col = mGlassCol(p, q, dd) * mix(1.0, uDim, 0.35);
    if (uChH.y < 0.999)                                                  // waking: a pink pop
        col += uPal3 * 0.6 * exp(-abs(length(p - mBC()) - 120.0 - uChH.y * 380.0) / 14.0) * (1.0 - uChH.y);
    return col;
}

void shape(vec2 p, inout vec4 acc) {
    if (uShape > 15.5) {                             // her paws (one call: see props)
        mHand(p, acc);
        return;
    }
    if ((uShape > 4.5 && uShape < 8.5) || uShape > 11.5) {   // props, the state's marks
        props(p, acc);                               // (one call: see props)
        return;
    }
    if (uShape < 1.5) {                        // an eye (one call: see props)
        bool r = uShape > 0.5;
        mEye(p, r ? uEye1 : uEye0, r ? uLidA1 : uLidA0, r ? uLidB1 : uLidB0,
             r ? uPupil1 : uPupil0, r ? 1.0 : -1.0, acc);
    } else if (uShape < 2.5) mMouth(p, acc);
    else if (uShape < 3.5) mBodyDraw(p, acc);
    else if (uShape < 4.5) mGlass(p, acc);
    else if (uShape < 8.5) {}                      // (props: above)
    else if (uShape < 10.5) mEar(p, uShape < 9.5 ? -1.0 : 1.0, acc);   // an ear each
    else mFront(p, acc);
}
"""

# ── PIP: neon outlines, dot pupils ────────────────────────────────────────────
_PIP = """
// a wrist computer's phosphor CRT: scanlines, grain, a soft wobble always;
// now and then (uChH.z, a seed in uChH.w) the sync slips — bands of lines
// tear sideways, a bright tearing bar, blocks of the picture go wrong
#define CRT

vec2 crtWarp(vec2 fc) {
    float fx = uChF.y;
    float g = uChH.z;
    fc.x += sin(fc.y * 0.045 + uT * 7.0) * 0.6 * fx;               // a soft wobble, always
    if (g > 0.01) {
        float band = floor(fc.y / 7.0);
        float h = hash(vec2(band, uChH.w));
        fc.x += step(0.62, h) * (h - 0.81) * 70.0 * g;              // lines slipping
        float bar = uRes.y * fract(uChH.w * 0.137);                 // the tearing bar
        float tb = exp(-sq((fc.y - bar) / 9.0));
        fc.x += tb * 26.0 * g * sign(hash(vec2(uChH.w, 3.0)) - 0.5);
        fc.y += (hash(vec2(uChH.w, 7.0)) - 0.5) * 10.0 * g;           // the picture jumps
    }
    return fc;
}

vec4 crtPost(vec4 acc, vec2 fc) {
    float fx = uChF.y;
    float g = uChH.z;
    acc.rgb *= 0.74 + 0.26 * step(1.0, mod(fc.y, 3.0));             // scanlines
    acc.rgb *= 1.0 - 0.05 * fx * hash(vec2(floor(uT * 24.0), 1.0)); // a faint flicker
    acc.rgb += acc.rgb * (hash(fc + fract(uT * 3.7)) - 0.5) * 0.30 * (0.4 + 0.6 * fx);   // grain
    if (g > 0.01) {                                                 // digital blocks
        float h = hash(floor(fc / vec2(16.0, 8.0)) + uChH.w);
        if (h > 1.0 - 0.18 * g) acc *= 0.15;
        else if (h > 1.0 - 0.30 * g) acc.rgb = min(acc.rgb * 1.8 + uPal0 * 0.12 * acc.a, vec3(1.0));
        float bar = uRes.y * fract(uChH.w * 0.137);
        acc.rgb += uPal0 * 0.35 * exp(-sq((fc.y - bar) / 3.0)) * g * acc.a;
    }
    return acc;
}

vec3 crtSoft(vec3 col, vec2 fc) {
    float fx = uChF.y;
    vec2 uv = fc / uRes;
    float roll = fract(uT * 0.08);                                  // a slow bright band rolling down
    col += uPal0 * 0.025 * exp(-sq((uv.y - roll) / 0.05)) * (0.3 + 0.7 * fx);
    vec2 v = uv - 0.5;
    col *= 1.0 - 0.9 * dot(v * v, v * v) * 6.0;                     // the tube's corners darker
    col += uPal0 * 0.006 * (0.3 + 0.7 * fx);                        // the phosphor's faint floor
    col += uPal0 * 0.10 * uChH.z * step(0.7, hash(vec2(floor(fc.y / 7.0), uChH.w)));   // sync lost
    return col;
}

const float P_T = 7.0;                        // the outline's width

// an eye: a neon outline (the lids cut it: "^" when happy, "\" when cross),
// its pupil a cluster of dots — twinkling when excited, a spinner when thinking
void pEyeDraw(vec2 p, vec4 e, vec4 la, vec4 lb, vec4 pu, float side, inout vec4 acc) {
    vec2 q;
    float d = eyeD(p, e, la, lb, side, q);
    float ds = seamD(q, e, la, lb, side) + 1.0;
    vec2 b = e.zw * 0.5;
    float ring = abs(d + P_T * 0.5) - P_T * 0.5;
    vec3 c = mix(uPal0, uPal1, clamp(q.y / (2.0 * b.y) + 0.5, 0.0, 1.0));
    float a = cover(ring);
    float sa = cover(ds) * lb.y;
    if (d < -P_T - 2.0 && pu.w > 0.05) {
        const float PITCH = 13.0;
        vec2 gi = floor(q / PITCH);
        vec2 gc = (gi + 0.5) * PITCH;
        float pr = pu.z * 0.95;
        float on = step(length(gc - pu.xy), pr);
        float rad = 3.6 + 0.9 * sin(uT * 9.0 + (gi.x + gi.y) * 0.9) * uChB.x;
        if (uChC.x > 0.3) {                   // thinking: a spinner of dots
            vec2 r = q - pu.xy;
            float ang = atan(r.y, r.x);
            float k = floor(ang / 0.7854 + 0.5);
            vec2 dc = vec2(cos(k * 0.7854), sin(k * 0.7854)) * pr * 0.75;
            float tail = fract(k / 8.0 - uT * 1.3);
            on = mix(on, 1.0, uChC.x);
            gc = pu.xy + dc;
            rad = 4.5 * mix(1.0, 0.5 + 0.8 * tail, uChC.x);
        }
        float dd = length(q - gc) - rad;
        float da = cover(dd) * on * pu.w * cover(d + P_T + 2.0);
        over(acc, mix(uPal3, uPal1, 0.25) * uDim, da);
        acc.rgb += uPal1 * 0.25 * halo(dd, 4.0) * on * pu.w * uDim * (1.0 - da);
    }
    c *= 1.0 + 0.35 * uChF.x * uEnergy;                // his voice: the neon flares
    over(acc, c * uDim, max(a, sa));
    float dg = min(ring, mix(1e5, ds, lb.y));
    acc.rgb += uPal0 * 0.55 * halo(dg, 7.0) * (1.0 - max(a, sa)) * uChA.w * uDim;
}

void pMouth(vec2 p, inout vec4 acc) {
    if (uMouthK.z <= 0.01) return;
    float inner, teeth, tongue;
    float d = mouthSDF(p - uMouth.xy, inner, teeth, tongue);
    float a = cover(d) * uMouthK.z;
    vec3 c = mix(uPal0, uPal1, 0.3);
    if (inner < 1e4) {                        // open: an outline, the inside dark
        float ia = cover(inner + 1.0);
        c = mix(c, vec3(0.0), ia);
        a *= 1.0 - ia * 0.85;
    }
    over(acc, c * uDim, a);
    acc.rgb += uPal0 * 0.45 * halo(d, 6.0) * uMouthK.z * (1.0 - a) * uDim;
}

// on top: a sprout (its leaves wiggle when happy, droop when sad), a cap
void pTop(vec2 p, inout vec4 acc) {
    vec2 c0 = uChA.xy + vec2(0.0, -122.0);
    float capOn = uAcc.y;
    if (capOn > 0.5) {
        vec2 q = p - c0;
        float dome = max(ellD(q, vec2(74.0, 46.0)), q.y);
        float brim = sdRoundBox(q - vec2(46.0, 4.0), vec2(64.0, 7.0), 6.0);
        float d = min(dome, brim);
        float ring = abs(d + 3.0) - 3.0;
        over(acc, mix(uPal0, uPal1, 0.4) * 0.30, cover(d) * 0.8);
        over(acc, uPal0, cover(ring));
        over(acc, uPal3, cover(length(q - vec2(0.0, -48.0)) - 7.0));
        acc.rgb += uPal0 * 0.4 * halo(ring, 6.0) * (1.0 - cover(ring)) * uChA.w;
    }
    if (uAcc.x > 0.5) {
        vec2 base = c0 + vec2(0.0, capOn > 0.5 ? -50.0 : -4.0);
        float sway = 0.12 * sin(uT * 2.3) * (0.4 + uChB.x) - 0.5 * uChB.y;
        vec2 top = base + rot2(vec2(0.0, capOn > 0.5 ? -24.0 : -38.0), sway * 0.4);
        float stem = sdSeg(p, base, top) - 3.5;
        over(acc, uPal0 * 0.85, cover(stem));
        for (int k = 0; k < 2; k++) {
            float side = k == 0 ? -1.0 : 1.0;
            float ang = side * (0.95 - 0.55 * uChB.y) + sway;
            vec2 lq = rot2(p - top, -ang);
            lq.y += 20.0;
            float leaf = ellD(lq, vec2(11.0, 22.0));
            float vein = abs(lq.x) - 1.2;
            vec3 lc = mix(uPal1, uPal0, clamp(lq.y / 22.0 + 0.5, 0.0, 1.0));
            over(acc, mix(lc, uPal0 * 0.5, cover(vein) * step(abs(lq.y), 16.0) * 0.6), cover(leaf));
            acc.rgb += uPal0 * 0.3 * halo(leaf, 6.0) * (1.0 - cover(leaf)) * uChA.w;
        }
    }
}

void pTie(vec2 p, inout vec4 acc) {                  // a bow tie below the mouth
    vec2 q = p - (uChA.xy + vec2(0.0, 186.0));
    vec2 aq = vec2(abs(q.x), q.y);
    float wing = max(sdSeg(aq, vec2(12.0, 0.0), vec2(54.0, 0.0)) - (8.0 + 0.45 * (aq.x - 12.0)),
                     aq.x - 54.0);
    float knot = sdRoundBox(q, vec2(12.0, 11.0), 4.0);
    float d = min(wing, knot);
    float ring = abs(d + 3.0) - 3.0;
    over(acc, uPal2 * 0.30, cover(d) * 0.8);
    over(acc, mix(uPal2, uPal1, 0.4), cover(min(ring, knot)));
    acc.rgb += uPal2 * 0.4 * halo(ring, 6.0) * (1.0 - cover(ring)) * uChA.w;
}

// a hand, unit size (y down, the wrist at +0.55, the thumb towards the
// face), proportioned like one: the palm narrowing to the wrist, tapered
// fingers (the middle longest), a two-part thumb from low on the palm; a fist
// from the front, its curled fingers stacked, knuckles out. lines: the joints,
// the palm's creases, a thumbnail, a thumb folded across
float pipHandSDF(vec2 q, float pose, out float lines) {
    lines = 1e5;
    if (pose > 7.5)                                     // the heart gesture
        return sdHeart(vec2(q.x, 0.5 - q.y) * 1.1) / 1.1;
    if (pose > 2.5 && pose < 3.5) q.y = 0.42 - q.y;     // thumb down: upside down
    if (pose < 1.5 || pose > 6.5) {                     // open (or ok): the palm out
        vec2 pq = q - vec2(0.02, 0.22);
        pq.x *= 1.0 + 0.22 * clamp(pq.y / 0.3, 0.0, 1.0);          // narrower at the wrist
        float d = sdRoundBox(pq, vec2(0.28, 0.29), 0.13);
        d = min(d, sdTaper(q, vec2(-0.05, -0.02), vec2(-0.07, -0.50), 0.070, 0.058));   // middle
        d = min(d, sdTaper(q, vec2(0.11, 0.0), vec2(0.15, -0.45), 0.066, 0.055));       // ring
        d = min(d, sdTaper(q, vec2(0.23, 0.05), vec2(0.30, -0.30), 0.058, 0.048));      // little
        lines = min(sdSeg(q, vec2(-0.12, -0.25), vec2(0.0, -0.25)), sdSeg(q, vec2(0.08, -0.21), vec2(0.20, -0.21)));
        lines = min(lines, sdSeg(q, vec2(0.23, -0.11), vec2(0.33, -0.12)));
        lines = min(lines, sdSeg(q, vec2(-0.18, 0.09), vec2(0.24, 0.05)));               // the palm's creases
        lines = min(lines, max(abs(length(q - vec2(-0.34, 0.40)) - 0.24), q.x + 0.14));
        if (pose < 1.5) {
            d = min(d, sdTaper(q, vec2(-0.19, 0.0), vec2(-0.26, -0.43), 0.068, 0.056));  // index
            lines = min(lines, sdSeg(q, vec2(-0.29, -0.21), vec2(-0.17, -0.22)));
            d = min(d, sdTaper(q, vec2(-0.22, 0.36), vec2(-0.40, 0.18), 0.095, 0.080));  // the thumb
            d = min(d, sdTaper(q, vec2(-0.40, 0.18), vec2(-0.49, 0.03), 0.080, 0.066));
            lines = min(lines, sdSeg(q, vec2(-0.45, 0.13), vec2(-0.36, 0.21)));
        } else {                                        // ok: index and thumb close a ring
            d = min(d, abs(length(q - vec2(-0.27, -0.05)) - 0.12) - 0.055);
            d = min(d, sdTaper(q, vec2(-0.22, 0.36), vec2(-0.36, 0.08), 0.095, 0.07));
        }
        return d;
    }
    float d = sdRoundBox(q - vec2(0.05, 0.24), vec2(0.25, 0.29), 0.16);   // a fist
    float first = pose > 5.5 && pose < 6.5 ? 2.0 : pose > 4.5 && pose < 5.5 ? 1.0 : 0.0;
    for (int k = 0; k < 4; k++) {                       // the curled fingers, knuckles out
        float fk = float(k);
        if (fk < first) continue;
        float y = 0.03 + 0.14 * fk;
        d = min(d, sdSeg(q, vec2(-0.08, y), vec2(0.27, y)) - 0.066);
        if (k < 3) lines = min(lines, sdSeg(q, vec2(-0.06, y + 0.07), vec2(0.31, y + 0.07)));
    }
    if (pose < 3.5) {                                   // the thumb up: short, a nail
        d = smin(d, sdTaper(q, vec2(-0.16, 0.10), vec2(-0.19, -0.25), 0.092, 0.078), 0.03);
        lines = min(lines, abs(sdRoundBox(q - vec2(-0.19, -0.25), vec2(0.035, 0.045), 0.03)));
        lines = min(lines, sdSeg(q, vec2(-0.25, -0.08), vec2(-0.12, -0.09)));
        lines = min(lines, sdSeg(q, vec2(-0.09, 0.0), vec2(-0.09, 0.48)));     // where the fingers curl in
    } else {                                            // folded across the fingers
        lines = min(lines, abs(sdTaper(q, vec2(-0.19, 0.44), vec2(0.10, 0.31), 0.068, 0.056)));
        if (pose > 4.5 && pose < 5.5) {                 // pointing: the index finger
            d = min(d, sdTaper(q, vec2(-0.10, 0.0), vec2(-0.11, -0.46), 0.066, 0.055));
            lines = min(lines, sdSeg(q, vec2(-0.16, -0.20), vec2(-0.05, -0.20)));
        } else if (pose > 5.5) {                        // scissors: index and middle apart
            d = min(d, sdTaper(q, vec2(-0.11, 0.0), vec2(-0.25, -0.43), 0.066, 0.055));
            d = min(d, sdTaper(q, vec2(0.05, 0.0), vec2(0.11, -0.47), 0.066, 0.055));
        }
    }
    return d;
}

void pHand(vec2 p, inout vec4 acc) {
    vec4 h = uShape < 16.5 ? uHand0 : uHand1;
    float pose = floor(h.w + 0.001);
    float al = clamp(fract(h.w + 0.001) / 0.98, 0.0, 1.0);
    float s = pose > 7.5 ? 84.0 * (1.0 + 0.1 * h.z) : 132.0;
    vec2 q = handLocal(p, h, s, pose > 2.5 && pose < 3.5 ? -0.13 : 0.55);   // turned at the wrist
    float crease;
    float d = pipHandSDF(q, pose, crease) * s;
    float ring = abs(d + 2.4) - 2.4;
    float lines = min(ring, max(crease * s - 1.6, d + 3.5));
    vec3 c = pose > 7.5 ? mix(uPal3, uPal0, 0.35) : mix(uPal0, uPal1, clamp(q.y + 0.5, 0.0, 1.0));
    c *= 1.0 + 0.35 * uChF.x * uEnergy;                // his voice: the neon flares
    over(acc, mix(uPal0, uPal1, 0.4) * 0.16 * uDim, cover(d) * al);
    over(acc, c * uDim, cover(lines) * al);
    acc.rgb += uPal0 * 0.5 * halo(lines, 7.0) * (1.0 - cover(lines)) * uChA.w * uDim * al;
}

vec3 soft(vec2 p, vec2 uv) {
    vec2 vq = uv - vec2(0.5, 0.46);
    vec3 col = vec3(0.008, 0.022, 0.016) * (1.0 - 1.3 * dot(vq, vq));
    float de = min(glowEye(p, uEye0, uLidA0), glowEye(p, uEye1, uLidA1));
    float k = uChA.w * uDim;
    col += uPal0 * (0.20 * exp(-max(de, 0.0) / 18.0) + 0.10 * exp(-max(de, 0.0) / 70.0)) * k;
    if (uChH.y < 0.999)                                // waking: a neon power-on ring
        col += uPal0 * 0.7 * exp(-abs(length(p - uChA.xy) - uChH.y * 460.0) / 8.0) * (1.0 - uChH.y);
    return col;
}

void shape(vec2 p, inout vec4 acc) {
    if (uShape > 15.5) {                             // his hands (one call: see props)
        pHand(p, acc);
        return;
    }
    if ((uShape > 4.5 && uShape < 8.5) || uShape > 11.5) {   // props, the state's marks
        props(p, acc);                               // (one call: see props)
        return;
    }
    if (uShape < 1.5) {                        // an eye (one call: see props)
        bool r = uShape > 0.5;
        pEyeDraw(p, r ? uEye1 : uEye0, r ? uLidA1 : uLidA0, r ? uLidB1 : uLidB0,
             r ? uPupil1 : uPupil0, r ? 1.0 : -1.0, acc);
    } else if (uShape < 2.5) pMouth(p, acc);
    else if (uShape < 8.5) {}                      // (props: above)
    else if (uShape < 10.5) pTop(p, acc);
    else pTie(p, acc);
}
"""

SOURCES = {"retro": _RETRO, "pixel": _PIXEL, "mochi": _MOCHI, "pip": _PIP}

# shape ids in a character's boxes: 0, 1 the eyes, 2 the mouth, 3 the body,
# 4 the brows, 5-8 props uPt0-3, 9 a screen / grid, 10 an accessory behind,
# 11 one in front, 12-15 the state's own marks uPt4-7, 16-17 the hands (MOCHI, PIP)
EYE0, EYE1, MOUTH, BODY, BROWS, PROP, SCREEN, ACC, FRONT, STATE, HAND = (
    0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 16)

# robot_face's hand poses → the shaders' (3: 2 upside down; 8 the heart gesture)
HAND_IDS = {"open": 1, "paper": 1, "hourglass": 1, "thumb": 2, "thumb_down": 3, "fist": 4,
            "point": 5, "scissors": 6, "ok": 7, "heart": 8}

# RETRO's and PIXEL's hands, cell by cell (10 × 12, a right hand, its thumb
# towards the face): "#" lit, "+" dim (a fist's fingers), "." off
HAND_ART = {
    1: (".....#....", "...#.#.#..", "...#.#.#..", "...#.#.#.#", "...#.#.#.#", "#..#.#.#.#",
        "#..#######", ".#.#######", ".#########", "..#++++###", "...######.", "...######."),
    2: ("..........", "...##.....", "...##.....", "...##.....", "..######..", "..########",
        "..#++++++#", "..########", "..#++++++#", "..########", "...######.", "...#####.."),
    4: ("..........", "..........", "..........", "...####...", "..#######.", "..########",
        "..#++++++#", "..########", "..####+++#", "..########", "...######.", "...#####.."),
    5: ("...#......", "...#......", "...#......", "...#......", "..####....", "..########",
        "..#++++++#", "..########", "..####+++#", "..########", "...######.", "...#####.."),
    6: ("..#....#..", "..#....#..", "...#..#...", "...#..#...", "..######..", "..########",
        "..#++++++#", "..########", "..####+++#", "..########", "...######.", "...#####.."),
    7: (".....#.#..", ".....#.#.#", ".....#.#.#", "..##.#.#.#", ".#..######", ".#..######",
        "..########", "..########", "...#######", "...######.", "...######.", "...#####.."),
    8: ("..........", "..........", ".##....##.", "####..####", "##########", "##########",
        ".########.", "..######..", "...####...", "....##....", "..........", ".........."),
}


def hand_atlas():
    """The hands' art as an RGBA texture: (width, height, bytes), a 12 × 14
    tile per pose 1-8 (the art, a cell round it); r lit (dim: 115), g 255
    inside its outline (the art and the cells next to it)."""
    tiles = [HAND_ART[1], HAND_ART[2], HAND_ART[2][::-1]] + [HAND_ART[k] for k in range(4, 9)]
    w, h = 12 * len(tiles), 14
    px = bytearray(w * h * 4)
    for t, rows in enumerate(tiles):
        lit = {(x, y): ch for y, row in enumerate(rows) for x, ch in enumerate(row) if ch != "."}
        for y in range(-1, 13):
            for x in range(-1, 11):
                near = any((x + dx, y + dy) in lit for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)))
                i = ((y + 1) * w + t * 12 + x + 1) * 4
                ch = lit.get((x, y))
                px[i] = 255 if ch == "#" else 115 if ch == "+" else 0
                px[i + 1] = 255 if near else 0
                px[i + 3] = 255
    return w, h, bytes(px)

# the margin round an eye's / the mouth's box for its own halo (px)
_HALO = {"mochi": 14.0, "pip": 18.0}

_rng = [None]                    # tests: a seeded random for the characters' habits


def seed(n):
    _rng[0] = random.Random(n)


# the characters drawn from a grid of cells: (columns, rows) round the face's centre
GRIDS = {"retro": (62, 38), "pixel": (46, 28)}


class CharPass:
    """The characters' programs (compiled when first shown) and their draws."""

    def __init__(self, gl):
        self.gl = gl
        self.progs = {}
        self.made = 0
        self.grids = {}                  # kind → (texture, framebuffer)
        self.broken = set()              # kinds whose shader did not compile
        self.art_tex = None              # the hands' pixel art (hand_atlas)

    def art(self):
        """The hands' art texture, bound to the active unit."""
        GL = self.gl.GL
        if self.art_tex is None:
            w, h, data = hand_atlas()
            self.art_tex = self.gl._texture(w, h, GL.GL_NEAREST)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0,
                            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, data)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.art_tex)

    def usable(self, kind):
        """Compiled (now, if not yet) — or False, logged once: the face then
        falls back to Luna's own shader rather than failing every frame."""
        if kind in self.broken or kind not in SOURCES:
            return False
        try:
            for stage in ("soft", "shape") + (("cells",) if kind in GRIDS else ()):
                self.prog(kind, stage)
            return True
        except Exception as e:
            self.broken.add(kind)
            print(f"[gl] character {kind}: shader failed, drawing Luna's face: {e}", flush=True)
            return False

    def grid(self, kind):
        g = self.grids.get(kind)
        if g is None:
            GL = self.gl.GL
            cols, rows = GRIDS[kind]
            tex = self.gl._texture(cols, rows, GL.GL_NEAREST)
            fbo = GL.glGenFramebuffers(1)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
            GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                      GL.GL_TEXTURE_2D, tex, 0)
            g = self.grids[kind] = (tex, fbo)
        return g

    def prog(self, kind, stage="shape"):
        p = self.progs.get((kind, stage))
        if p is None:
            import watchdog
            watchdog.busy(120, f"compiling {kind}")       # its first draw compiles it
            gl = self.gl
            head = "#version 120\n" if gl.glsl == "120" else "#version 100\nprecision mediump float;\n"
            fs = head + PASSES[stage] + DEFINES.get(kind, "") + _HEAD + SOURCES[kind] + _MAIN
            t0 = time.perf_counter()
            p = gl_face._Prog(gl.GL, gl._program(head + gl_face._VERT, fs))
            gl.GL.glUseProgram(p.id)
            p.u("uRes", (gl.w, gl.h))
            p.u("uSoftRes", (gl.sw, gl.sh))
            p.unit("uCells", 4)
            p.unit("uArt", 6)
            if kind in GRIDS:
                cols, rows = GRIDS[kind]
                p.u("uGrid", (cols // 2, rows // 2, cols, rows))
            self.progs[(kind, stage)] = p
            self.made += 1
            print(f"[gl] character {kind}: {stage} program ({time.perf_counter() - t0:.1f} s)",
                  flush=True)
        return p

    def _uniforms(self, p, u):
        for k, v in u.items():
            if k[0] != "_":
                p.u(k, v)

    def soft(self, kind, u):
        """Stage 0: into the small framebuffer (bound by the caller)."""
        p = self.prog(kind, "soft")
        GL = self.gl.GL
        GL.glUseProgram(p.id)
        self._uniforms(p, u)
        p.u("uRect", (0.0, 0.0, float(self.gl.w), float(self.gl.h)))
        self.gl._bind_quad()
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        if kind in GRIDS:                # every cell once (the caller binds the screen after)
            p = self.prog(kind, "cells")
            GL.glUseProgram(p.id)
            self._uniforms(p, u)
            p.u("uRect", (0.0, 0.0, float(self.gl.w), float(self.gl.h)))
            tex, fbo = self.grid(kind)
            cols, rows = GRIDS[kind]
            GL.glActiveTexture(GL.GL_TEXTURE6)            # (the hands' art)
            self.art()
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
            GL.glViewport(0, 0, cols, rows)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

    def shapes(self, kind, u):
        """Stage 2: each piece in its own box, in order (blending is on)."""
        p = self.prog(kind, "shape")
        GL = self.gl.GL
        GL.glUseProgram(p.id)
        self._uniforms(p, u)
        if kind in GRIDS:
            GL.glActiveTexture(GL.GL_TEXTURE4)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.grid(kind)[0])
        self.gl._bind_quad()
        for sid, rect in u.get("_char_boxes", ()):
            p.u("uShape", float(sid))
            p.u("uRect", rect)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)


# ── the pose → the character's uniforms ───────────────────────────────────────

def _bump(el, dur):
    return math.sin(math.pi * el / dur) if 0.0 <= el < dur else 0.0


def _props(kind, life, ch, u, fcx, fcy, now, acc):
    """Up to four props: (x, y, size, kind + alpha), behind the face or not."""
    out = []
    cel = ch["celebrate"]
    if kind == "mochi":                      # her symbols pop once (mochi_rig), not a stream
        for x, y, size, k in getattr(life, "mochi", {}).get("pops", ()):
            if int(k) != 1 or "hearts" in acc:
                out.append(((fcx + x, fcy + y, size, k), False))
    if kind == "pip":
        k = max(cel, 0.5 * ch["happy"] * (u["uMorph"][3] > 0.5))
        for i in range(4 if k > 0.02 else 0):
            a = (now * 1.7 + i * 0.25) % 1.0
            x = fcx + (-1.0 if i < 2 else 1.0) * (250.0 + 30.0 * (i % 2))
            y = fcy - 110.0 + 120.0 * (i % 2)
            out.append(((x, y, 22.0 * (0.6 + 0.4 * math.sin(math.pi * a)),
                         4.0 + 0.98 * k * math.sin(math.pi * a)), False))
    if kind == "retro" and "rocket" in acc and cel > 0.02:
        t = min(1.0, (now % 3.0) / 2.2)
        x = fcx + 330.0 - 40.0 * t
        y = fcy + 230.0 - 470.0 * t
        out.append(((x, y, 34.0, 6.0 + 0.98 * cel), False))
    if kind == "pip" and ch["confused"] + ch["curious"] > 0.03:
        k = max(ch["confused"], ch["curious"] * 0.7)
        out.append(((fcx + 300.0, fcy - 96.0 - 8.0 * math.sin(now * 3.0), 40.0, 2.0 + 0.98 * k), False))
    return out[:4]


def _state_props(kind, ch, u, fcx, fcy, now):
    """Up to four of the character's own state marks (uPt4-7): listening,
    thinking, asleep, a tear, anger, surprise — RETRO and PIXEL draw theirs
    in their cells, the rest here. (x, y, size, kind + alpha)."""
    out = []

    def at(x, y, size, k, a):
        if a > 0.02 and len(out) < 4:
            out.append((x, y, size, k + 0.98 * min(1.0, a)))

    e0, e1 = u["uEye0"], u["uEye1"]
    listen, think, sleep = ch["listen"], ch["think"] * (1.0 - ch["speak"]), ch["sleep"]
    sad, angry, bang = ch["sad"], ch["angry"], max(ch["surprise"], ch["alert"])
    zt, tt = (now * 0.45) % 1.0, (now * 0.6) % 1.0
    tk = math.sin(math.pi * tt) ** 0.5
    if kind == "mochi":
        for side in (-1.0, 1.0):                         # "(((" by her pods
            at(fcx + side * 312.0, fcy + 80.0, 34.0, 15.0, listen)
        at(fcx + 250.0, fcy - 146.0, 50.0, 11.0, think)  # a small thought cloud
        for ph in (0.0, 0.5):                            # z Z, slow (past her ear)
            t = (zt * 0.8 + ph) % 1.0
            at(fcx + 300.0 + 26.0 * t, fcy - 30.0 - 110.0 * t, 16.0 + 12.0 * t, 9.0,
               sleep * math.sin(math.pi * t))
    if kind == "pip":
        at(e1[0] + e1[2] * 0.5 + 56.0, e1[1] - e1[3] * 0.5 - 10.0, 40.0, 12.0, listen)  # signal bars
        for ph in (0.0, 0.5):
            t = (zt + ph) % 1.0
            at(fcx + 220.0 + 30.0 * t, fcy - 50.0 - 110.0 * t, 22.0 + 10.0 * t, 9.0,
               sleep * math.sin(math.pi * t))
    if kind in ("mochi", "pip") and sad > 0.02:         # a tear
        at(e0[0] - e0[2] * 0.22, e0[1] + e0[3] * 0.5 + 10.0 + 60.0 * tt, 16.0, 8.0, sad * tk)
    if kind == "pip":                                   # (MOCHI pouts; her "!" pops once)
        at(e1[0] + e1[2] * 0.5 + 40.0, e1[1] - e1[3] * 0.5 - 30.0, 36.0, 10.0,
           angry * (0.7 + 0.3 * math.sin(now * 6.0)))
        at(fcx - 270.0, fcy - 150.0, 44.0, 7.0, bang)
    return out


def _hand_at(kind, hx, hy, console):
    """Where a character shows a hand robot_face holds at (hx, hy) from the
    face's centre: PIXEL within its matrix (not over the side bars), RETRO
    on its screen (smaller moves), the others beside their faces. Rising
    from below the screen stays rising: the grid, the screen clip it. The
    grid ones keep a hand in the row under the eyes, beside the mouth (PIXEL:
    a hand on the head in the matrix's top corner), never over an eye."""
    rise = max(0.0, hy - 150.0) * 1.3
    if kind == "pixel":
        if hy < -60.0:
            return math.copysign(252.0, hx), -128.0 + rise
        return max(-224.0, min(224.0, hx)), 118.0 + rise
    if kind == "retro":
        cy, (bx, by) = (-18.0, (214.0, 126.0)) if console else (-10.0, (300.0, 172.0))
        return max(-(bx - 60.0), min(bx - 60.0, hx * 0.6)), cy + by - 40.0 + rise
    return max(-340.0, min(340.0, hx * 1.1)), hy


# the heart gesture: where each shows its heart (PIXEL, RETRO: for a mouth)
HEART_AT = {"pixel": (0.0, 100.0), "pip": (0.0, 196.0)}      # (MOCHI: mochi_rig, paws to her cheeks)


def _hands(kind, face, fcx, fcy, console):
    """Her hands (robot_face's, drawn by the character): up to two
    (x, y, turn in rad — the heart: its beat —, pose + alpha * 0.98)."""
    if getattr(face, "_gesture", None) == "heart":
        k = getattr(face, "_heart_pulse", 0.0)
        env = min(1.0, 2.5 * math.sin(math.pi * getattr(face, "_gesture_p", 0.0)))
        hx, hy = HEART_AT.get(kind) or (0.0, 66.0 if console else 98.0)
        return [(fcx + hx, fcy + hy, k, 8.0 + 0.98 * max(0.0, env))] if env > 0.02 else []
    out = []
    for side in ("L", "R"):
        hand = getattr(face, "hand", {}).get(side)
        if not hand or hand[1] > 400.0:              # tucked away below
            continue
        x, y = _hand_at(kind, hand[0], hand[1], console)
        pose = HAND_IDS.get(face.hand_pose.get(side), 1)
        out.append((fcx + x, fcy + y, math.radians(hand[2]), pose + 0.98))
    return out


def _remap(u, face, L, fcx, fcy, life, ch, dt, now, kind):
    """The pose's eyes, brows and mouth moved to the character's layout."""
    s = L["eye_s"]
    sy = L.get("eye_sy", s)
    asleep = getattr(face, "_emotion", "") == "sleeping"
    gx, gy = ch["gaze"]
    brows = []
    for i, (eye, side) in enumerate(((face.left_eye, -1.0), (face.right_eye, 1.0))):
        ex, ey, w, h = u[f"uEye{i}"]
        nx = fcx + side * L["eye_x"] + (ex - fcx - eye.rel_x) * s
        ny = fcy + L["eye_y"] + (ey - fcy - eye.rel_y) * sy
        w2, h2 = w * s, h * sy
        u[f"uEye{i}"] = (nx, ny, w2, h2)
        dx, dy, pr, shown = u[f"uPupil{i}"]
        dx, dy = life.gaze_filter(i, dx * s + gx, dy * sy + gy, dt, asleep)
        pr *= min(s, sy)
        mx_, my_ = max(0.0, w2 / 2 - pr * 0.95), max(0.0, h2 / 2 - pr * 0.8)
        u[f"uPupil{i}"] = (max(-mx_, min(mx_, dx)), max(-my_, min(my_, dy)), pr, shown)
        x0, y0, x1, y1 = u[f"uBrow{i}"]
        brows.append((nx + (x0 - ex) * s, ny + (y0 - ey) * sy, nx + (x1 - ex) * s, ny + (y1 - ey) * sy))
    u["uBrow0"], u["uBrow1"] = brows
    b0, b1, thick, ba = u["uBrowK"]
    u["uBrowK"] = (b0 * sy, b1 * sy, thick * L.get("brow_t", 0.35), ba)
    mx, my, w, h = u["uMouth"]
    bend, open_, alpha, mk = u["uMouthK"]
    ms = L["mouth_s"]
    cw, chh, co = characters.mouth_scale(kind)
    talking = ch["speak"] > 0.5
    if talking and mk == 1.0:                     # open, talking: the viseme, the character's way
        h = 24.0 + (h - 24.0) * co
        open_ = life.mouth_step(open_)
        lv = characters.CHARS[kind].get("mouth", {}).get("levels")
        if lv:                                    # pixel hardware: the height in steps too
            h = 24.0 + math.floor((h - 24.0) / 80.0 * lv + 0.5) * 80.0 / lv
    u["uMouth"] = (fcx + (mx - fcx) * ms, fcy + L["mouth_y"] + (my - fcy - face.mouth.rel_y) * ms,
                   w * ms * cw, h * ms * chh)
    u["uMouthK"] = (bend * ms, open_, alpha, mk)
    u["uMouthSlant"] = u["uMouthSlant"] * ms
    u["uWave"] = 0.0


def _mochi(gl, face, u, life, ch, fcx, fcy, now, dt, sway_y):
    """MOCHI's rig (mochi_rig.py) this frame: her eyes follow her gaze (the
    iris inside the eye, the whole eye a little), sized and moved by the look; her paws,
    ears, glyphs and mouth as uniforms. → {"hands": uHand0/1, "u": the rest}."""
    rig = getattr(life, "rig", None)
    if rig is None:
        rig = life.rig = mochi_rig.MochiRig(now)
    closed = (u.get("uLidB0", (0.0, 0.0))[1], u.get("uLidB1", (0.0, 0.0))[1])
    # her head's frame on the screen (facePos turned round): the paws press on the glass
    c0x, c0y, tilt = gl.w / 2.0, gl.h / 2.0, float(u.get("uTilt", 0.0))
    dx, dy, c, s = fcx + ch["body_x"] - c0x, fcy + sway_y - c0y, math.cos(tilt), math.sin(tilt)
    frame = (c0x + c * dx + s * dy, c0y - s * dx + c * dy, -tilt - ch["body_rot"] - rig.tilt.x)
    r = rig.step(face, ch, now, dt, characters.fx_level(now), closed,
                 (fcx + ch["body_x"], fcy + ch["body_y"]), set(life.active),
                 dock.CY - 30.0 - fcy - ch["body_y"] - 2.0, frame)     # (the dock's pill, its float)
    life.mochi = r
    gx, gy = r["gaze"]
    for i in (0, 1):
        ex, ey, w, h = u[f"uEye{i}"]
        dx, dy = u[f"uPupil{i}"][:2]
        s = r["scale"][i]
        u[f"uEye{i}"] = (ex + dx * 0.2 + gx, ey + dy * 0.15 + gy, w * s, h * s)
    ch["body_rot"] += r["tilt"]
    hands = []
    for x, y, turn, pose, size in r["paws"]:
        hands.append((fcx + x, fcy + y, turn, pose + 0.98))
    (_, _, _, _, s0), (_, _, _, _, s1) = r["paws"]
    return {"hands": hands, "u": {
        "uMoEar": tuple(r["ears"]), "uMoEye": r["eyes"],
        "uMoFace": (r["scale"][0], r["scale"][1], r["sparkle"], r["blush"]),
        "uMoMouth": (float(r["mouth"][0]), r["mouth"][1], r["mouth"][2], 0.0),
        "uMoPaw": (s0, s1, 0.0, 0.0), "uMoBody": (r["squash"], r["pods"], r["puff"], 0.0),
        "uMoIris": r["iris"]}}


def _box(gl, x0, y0, x1, y1, tilt):
    return gl._box((x0 + x1) / 2.0, (y0 + y1) / 2.0, (x1 - x0) / 2.0, (y1 - y0) / 2.0, tilt)


def _boxes(gl, kind, u, ch, props, fcx, fcy, console, acc, marks=(), hands=()):
    """Where stage 2 draws, in order: what's behind first."""
    tilt = u["uTilt"]
    pad = 6.0 + abs(ch["body_x"]) + abs(ch["body_y"]) + 420.0 * abs(ch["body_rot"])
    pad += 36.0 * ch.get("sync", 0.0)                  # PIP: lines slip sideways
    out = []

    def add(sid, cx, cy, hx, hy):
        r = gl._box(cx, cy, hx + pad, hy + pad, tilt)
        if r is not None:
            out.append((sid, r))

    for i, (pt, behind) in enumerate(props):
        if behind:
            add(PROP + i, pt[0], pt[1], pt[2] * 1.35 + 22, pt[2] * 1.35 + 22)
    if kind == "retro":
        if console:
            if "cartridge" in acc:
                add(ACC, fcx + 306.0, fcy - 30.0, 34.0, 50.0)
            bx, by, hx, hy = fcx, fcy + 10.0, 290.0, 198.0
            sx, sy, shx, shy = fcx, fcy - 18.0, 214.0, 126.0
            # the case round the screen, in four strips (the screen draws its own middle)
            top, bot = by - hy, by + hy
            add(BODY, bx, (top + sy - shy + 8) / 2.0, hx, (sy - shy + 8 - top) / 2.0)
            add(BODY, bx, (sy + shy - 8 + bot) / 2.0, hx, (bot - (sy + shy - 8)) / 2.0)
            add(BODY, (bx - hx + sx - shx + 8) / 2.0, sy, (sx - shx + 8 - (bx - hx)) / 2.0, shy)
            add(BODY, (sx + shx - 8 + bx + hx) / 2.0, sy, (bx + hx - (sx + shx - 8)) / 2.0, shy)
            add(SCREEN, sx, sy, shx, shy)
        else:
            add(SCREEN, fcx, fcy - 10.0, 300.0, 172.0)
    if kind == "pixel":
        add(SCREEN, fcx, fcy + 4.0, 322.0, 196.0)
    by = fcy + 70.0                                    # MOCHI's head
    if kind == "mochi":
        if "ears" in acc:                              # an ear each: base, middle, tip
            ears = u["uMoEar"]
            for i, side in enumerate((-1.0, 1.0)):
                lean, flop = ears[i], ears[2 + i]
                bx, byy = fcx + side * 118.0, by - 124.0
                mx_, my_ = bx + side * 64.0 * math.sin(lean), byy - 64.0 * math.cos(lean)
                a2 = lean + 1.3 * flop
                tx, ty = mx_ + side * 92.0 * math.sin(a2), my_ - 92.0 * math.cos(a2)
                xs, ys = (bx, mx_, tx), (byy, my_, ty)
                add(SCREEN + i, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                    (max(xs) - min(xs)) / 2 + 48.0, (max(ys) - min(ys)) / 2 + 48.0)
        gx, gy, cy = 156.0, 82.0, by - 6.0               # her casing: four strips round the
        add(BODY, fcx, (by - 156.0 + cy - gy) / 2.0, 282.0, (cy - gy - by + 156.0) / 2.0)   # glass
        add(BODY + 0.1, fcx, (cy + gy + by + 156.0) / 2.0, 282.0, (by + 156.0 - cy - gy) / 2.0)
        add(BODY + 0.2, fcx - (282.0 + gx) / 2.0, cy, (282.0 - gx) / 2.0, gy)
        add(BODY + 0.3, fcx + (282.0 + gx) / 2.0, cy, (282.0 - gx) / 2.0, gy)
        if u.get("_vis"):                              # the radio's picture: the glass covers it
            add(BROWS, fcx, cy, gx, gy)
    if kind in _HALO:
        m = _HALO[kind]
        for i in (0, 1):
            ex, ey, w, h = u[f"uEye{i}"]
            add(EYE0 + i, ex, ey, w / 2 + m, h / 2 + m)
        mx, my, w, h = u["uMouth"]
        bend, _, alpha, mk = u["uMouthK"]
        _, own, ms, _ = u.get("uMoMouth", (0.0, 0.0, 0.0, 0.0))   # (MOCHI's own mouths)
        if max(alpha, own) > 0.01:
            add(MOUTH, mx, my, max(w / 2 + h / 2, ms + 4.0) + m,
                max(max(h, w * (mk == 2.0)) / 2 + h + abs(bend) + abs(u["uMouthSlant"]), ms * 1.1) + m)
    if kind == "pip":
        if "sprout" in acc or "cap" in acc:
            add(ACC, fcx + 10.0, fcy - 172.0, 130.0, 92.0)
        if "bowtie" in acc:
            add(FRONT, fcx, fcy + 186.0, 70.0, 32.0)
    if kind == "mochi":
        if "flower" in acc:
            add(FRONT, fcx + 152.0, by - 134.0, 32.0, 32.0)
    for i, (pt, behind) in enumerate(props):
        if not behind:
            add(PROP + i, pt[0], pt[1], pt[2] * 1.35 + 22, pt[2] * 1.35 + 22)
    for i, pt in enumerate(marks):                     # the state's own marks, on top
        r = pt[2] * 1.35 + 22
        add(STATE + i, pt[0], pt[1], r, r)
    if kind == "pip":                                  # the hands, in front of it all
        for i, h in enumerate(hands):
            add(HAND + i, h[0], h[1], 124.0, 124.0)
    if kind == "mochi":                                # her paws
        sz = u["uMoPaw"]
        for i, h in enumerate(hands):                  # its own frame's box, turned at the wrist
            s, t = sz[i], h[2]
            hx_, y0, y1 = 0.54 * s + 14.0, -0.52 * s - 6.0, 0.6 * s + 14.0
            c, sn = math.cos(t), math.sin(t)
            xs, ys = [], []
            for lx, ly in ((-hx_, y0), (hx_, y0), (-hx_, y1), (hx_, y1)):
                ly -= 0.4 * s
                xs.append(h[0] + c * lx - sn * ly)
                ys.append(h[1] + 0.4 * s + sn * lx + c * ly)
            add(HAND + i, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2)
    return out


def apply(gl, face, u, cur, fcx, fcy, kind, now, dt):
    """Lay the character over the pose's uniforms (gl_face.face_uniforms)."""
    life = getattr(gl, "char_life", None)
    if life is None or life.kind != kind:
        life = gl.char_life = characters.CharLife(kind, now, rng=_rng[0])
    ch = life.step(face, cur, now, dt)
    cfg = characters.CHARS[kind]
    console = kind == "retro" and characters.retro_console(now)
    L = cfg["layout"] if kind != "retro" or console else cfg["layout_face"]
    _remap(u, face, L, fcx, fcy, life, ch, dt, now, kind)
    acc = characters.accessories(kind, now)
    names = cfg["accessories"]
    flags = [1.0 if n in acc else 0.0 for n in names[:4]] + [0.0] * (4 - min(4, len(names)))
    sway_y = ch["body_y"]
    if kind == "mochi":                           # a soft float, nothing more
        sway_y += ch["motion"] * 2.0 * math.sin(now * 1.3)
    mo = _mochi(gl, face, u, life, ch, fcx, fcy, now, dt, sway_y) if kind == "mochi" else None
    if kind == "pip" and ch["happy"] > 0.3:       # bouncy
        sway_y -= 4.0 * ch["motion"] * ch["happy"] * abs(math.sin(now * 5.0))
    ch["body_y"] = sway_y
    music = 1.0 if u.get("_vis") else 0.0
    pal = cfg["pal"]
    props = _props(kind, life, ch, u, fcx, fcy, now, acc)
    pts = [p for p, _ in props] + [(0.0, 0.0, 0.0, 0.0)] * (4 - len(props))
    marks = _state_props(kind, ch, u, fcx, fcy, now)
    sts = marks + [(0.0, 0.0, 0.0, 0.0)] * (4 - len(marks))
    hands = mo["hands"] if mo else _hands(kind, face, fcx, fcy, console)
    hs = hands + [(0.0, 0.0, 0.0, 0.0)] * (2 - len(hands))
    if mo:
        u.update(mo["u"])
    u.update({
        "uHand0": hs[0], "uHand1": hs[1],
        "uChA": (fcx, fcy, ch["motion"], 0.55 + 0.45 * ch["fx"]),
        "uChB": (ch["happy"], ch["sad"], ch["angry"], ch["surprise"]),
        "uChC": (ch["think"], ch["sleep"], ch["celebrate"], ch["alert"]),
        "uChD": (ch["curious"], ch["confused"], ch["glitch"], ch["crt"]),
        "uChE": (ch["body_x"], sway_y, ch["body_rot"], ch["listen"]),
        "uChF": (ch["speak"], ch["fx"], 1.0 if console else 0.0, ch["roll"]),
        "uChG": (music, 0.0, 0.0, 0.0),
        "uAcc": tuple(flags),
        "uPal0": pal[0], "uPal1": pal[1], "uPal2": pal[2], "uPal3": pal[3],
        "uPt0": pts[0], "uPt1": pts[1], "uPt2": pts[2], "uPt3": pts[3],
        "uPt4": sts[0], "uPt5": sts[1], "uPt6": sts[2], "uPt7": sts[3],
        "uChH": (ch["mic"], ch["wake"], ch.get("sync", 0.0), ch.get("seed", 0.0)),
        "uT": now % 1000.0,
        "uShine": (1.0, 0.97, 0.92),
    })
    u["_char"] = kind
    u["_char_boxes"] = _boxes(gl, kind, u, ch, props, fcx, fcy, console, acc, marks, hands)
    gl.char_now = ch
    return u
