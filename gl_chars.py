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
import gl_face

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

vec2 gFC;      // the screen's pixel (y down), before the head's tilt: PIXEL's fixed matrix

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
    over(acc, c, cover(d) * al);
    acc.rgb += c * 0.35 * exp(-max(d, 0.0) / 6.0) * clamp(1.0 - d / 18.0, 0.0, 1.0)
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
    gFC = fc;
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
    return vec4(0.0, 0.0, 0.0, max(rCell(cc, ci), rStates(cc)));
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
# The matrix is fixed to the screen and fills it; the face moves through it
# (each cell lit by what of the face is under its centre).
PIXEL_PITCH = 16
_PIXEL = """
#define GRID
const float PITCH = 16.0;                         // 50 × 30 cells on 800 × 480
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

// her marks (…, ?, !, Zs, a tear, hearts…) as pixel art: upright and on whole
// cells whatever the head's tilt — only where they sit follows the face
vec2 screenPos(vec2 f) {                          // facePos, the other way
    vec2 c0 = uRes * 0.5;
    vec2 p = uChA.xy + uChE.xy + rot2(f - uChA.xy, -uChE.z);
    return c0 + rot2(p - c0, -uTilt);
}

vec2 markCell(vec2 f) { return floor((screenPos(f) - uRes * 0.5) / PITCH + 0.5); }

float inGlyph(vec2 d, float w, float h) {
    return step(0.0, d.x) * step(0.0, d.y) * step(d.x, w - 1.0) * step(d.y, h - 1.0);
}

// a row's bits, the leftmost cell the highest
float bit(float row, float x, float w) { return mod(floor(row / exp2(w - 1.0 - x)), 2.0); }

float glyph(vec2 d, float w, float h, float row) { return inGlyph(d, w, h) * bit(row, d.x, w); }

float rowQ(float y) {                             // ? 5 × 7
    return y < 0.5 ? 14.0 : (y < 1.5 ? 17.0 : (y < 2.5 ? 1.0 : (y < 3.5 ? 6.0
         : (y < 4.5 ? 4.0 : (y < 5.5 ? 0.0 : 4.0)))));
}
float rowBang(float y) { return y > 4.5 && y < 5.5 ? 0.0 : 3.0; }      // ! 2 × 7
float rowHeart(float y) {                         // 7 × 6
    return y < 0.5 ? 54.0 : (y < 2.5 ? 127.0 : (y < 3.5 ? 62.0 : (y < 4.5 ? 28.0 : 8.0)));
}
float rowStar(float y) {                          // 5 × 5
    return y < 0.5 ? 4.0 : (y < 1.5 ? 14.0 : (y < 2.5 ? 31.0 : (y < 3.5 ? 14.0 : 10.0)));
}
float rowZ(float y) {                             // 5 × 5
    return y < 0.5 ? 31.0 : (y < 1.5 ? 2.0 : (y < 2.5 ? 4.0 : (y < 3.5 ? 8.0 : 31.0)));
}
float rowBubble(float y) {                        // 9 × 7: the box, its tail
    return (y < 0.5 || (y > 3.5 && y < 4.5)) ? 511.0 : (y < 3.5 ? 257.0 : (y < 5.5 ? 128.0 : 256.0));
}

vec4 pCell(vec2 cc, vec2 ci, vec2 sc) {   // ci: the screen's cell, sc its centre
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
    if (abs(ci.x + 0.5) > uGrid.x - 2.0) {            // the screen's edge bars: her voice, the music
        float level = max(max(uChF.x * (0.15 + 0.95 * uEnergy), uChG.x * (0.2 + 0.8 * uEnergy)),
                          uChE.w * (0.08 + 0.92 * uChH.x));       // listening: the mic
        float row = 1.0 - sc.y / uRes.y;
        if (row < level) { c = mix(uPal0, uPal2, row); v = 0.9; }
    }
    if (uChC.x > 0.3 && uChF.x < 0.5) {                // thinking: "…" filling up, three 2 × 2 dots
        vec2 d = ci - markCell(vec2(uEye1.x + uEye1.z * 0.5 + 40.0, uEye1.y - uEye1.w * 0.5 - 28.0)) + vec2(4.0, 1.0);
        float k = floor(d.x / 3.0);
        if (inGlyph(d, 8.0, 2.0) > 0.5 && mod(d.x, 3.0) < 1.5) {
            float lt = step(k, mod(floor(uT * 3.0), 4.0) - 0.5);
            c = uPal0;
            v = max(v, (0.45 + 0.55 * lt) * smoothstep(0.3, 0.6, uChC.x));
        }
    }
    if (uChD.x + uChD.y > 0.2) {                       // curious, confused: "?"
        vec2 d = ci - markCell(gC() + vec2(272.0, -118.0)) + vec2(2.0, 3.0);
        if (glyph(d, 5.0, 7.0, rowQ(d.y)) > 0.5) {
            c = uPal3;
            v = max(v, smoothstep(0.1, 0.3, uChD.x + uChD.y));
        }
    }
    float bang = max(uChC.w, uChB.w);
    if (bang > 0.2) {                                  // alert, surprised: "!"
        vec2 d = ci - markCell(gC() + vec2(-272.0, -112.0)) + vec2(1.0, 3.0);
        if (glyph(d, 2.0, 7.0, rowBang(d.y)) > 0.5) {
            c = vec3(1.0, 0.28, 0.25);
            v = max(v, bang);
        }
    }
    if (uChC.y > 0.05) {                               // asleep: Zs rising a cell at a time
        for (int k = 0; k < 2; k++) {
            float fk = float(k);
            float t = fract(uT * 0.3 + fk * 0.5);
            vec2 d = ci - markCell(gC() + vec2(170.0 + 80.0 * fk, -60.0)) + vec2(0.0, floor(t * 6.0));
            if (glyph(d, 5.0, 5.0, rowZ(d.y)) > 0.5) {
                c = uPal0;
                v = max(v, uChC.y * (1.0 - t) * 1.6);
            }
        }
    }
    if (uChB.y > 0.05) {                               // sad: a tear falling a cell at a time
        float t = fract(uT * 0.6);
        vec2 d = ci - markCell(vec2(uEye0.x - uEye0.z * 0.25, uEye0.y + uEye0.w * 0.5 + PITCH))
                 - vec2(0.0, floor(t * 6.0));
        if ((d.x == 0.0 && (d.y == 0.0 || d.y == 2.0)) || (abs(d.x) <= 1.0 && d.y == 1.0)) {
            c = vec3(0.45, 0.75, 1.0);
            v = max(v, uChB.y * (1.0 - t));
        }
    }
    if (uChB.z > 0.05) {                               // cross: a pulsing anger mark
        vec2 a = abs(ci - markCell(vec2(uEye1.x + uEye1.z * 0.5 + 34.0, uEye1.y - uEye1.w * 0.5 - 24.0)));
        if (max(a.x, a.y) == 2.0 && min(a.x, a.y) >= 1.0) {
            c = vec3(1.0, 0.25, 0.25);
            v = max(v, uChB.z * (0.55 + 0.45 * step(0.35, fract(uT * 2.0))));
        }
    }
    if (uChH.y < 0.999) {                              // waking: a line scans down, lighting it up
        float row = floor(uChH.y * (uGrid.w + 2.0)) - uGrid.y - 1.0;
        if (ci.y == row) { c = uPal0; v = max(v, 1.0); }
        else if (ci.y > row) v *= 0.0;
    }
    float cel = max(uChC.z, 0.8 * uMorph.x);
    if (uAcc.x > 0.5 && cel > 0.1) {                   // hearts, rising a cell at a time
        for (int k = 0; k < 2; k++) {
            float fk = float(k);
            float t = fract(uT * 0.35 + fk * 0.5);
            vec2 d = ci - markCell(gC() + vec2((fk < 0.5 ? -1.0 : 1.0) * 280.0, 110.0)) + vec2(3.0, 3.0)
                     + vec2(0.0, floor(t * 15.0));
            if (glyph(d, 7.0, 6.0, rowHeart(d.y)) > 0.5) { c = uPal2; v = max(v, cel * sin(3.14159 * t)); }
        }
    }
    if (uAcc.y > 0.5 && uChC.z > 0.1) {                // stars blinking
        for (int k = 0; k < 3; k++) {
            float fk = float(k);
            vec2 d = ci - markCell(gC() + vec2(-200.0 + 200.0 * fk, -150.0 + 20.0 * mod(fk, 2.0))) + vec2(2.0, 2.0);
            float blink = step(0.4, fract(uT * 2.0 + fk * 0.33));
            if (glyph(d, 5.0, 5.0, rowStar(d.y)) > 0.5) {
                c = uPal3;
                v = max(v, uChC.z * blink);
            }
        }
    }
    if (uAcc.z > 0.5 && uChF.x > 0.5) {                // a speech bubble while she talks
        vec2 d = ci - markCell(gC() + vec2(236.0, -150.0)) + vec2(4.0, 2.0);
        if (glyph(d, 9.0, 7.0, rowBubble(d.y)) > 0.5) { c = vec3(0.92); v = max(v, 0.8); }
        if (d.y == 2.0 && d.x >= 2.0 && d.x <= 6.0 && mod(d.x, 2.0) == 0.0) {   // its three dots
            float lt = step(d.x * 0.5 - 1.0, mod(floor(uT * 4.0), 4.0) - 0.5);
            c = uPal0;
            v = max(v, lt);
        }
    }
    if (uAcc.w > 0.5 && uChG.x > 0.5) {                // headphones while the music plays
        float band = abs(length(g - vec2(0.0, 90.0)) - 300.0);
        if (band < 8.0 && g.y < -110.0) { c = uPal2; v = max(v, 0.85); }
        if (abs(g.x) > 252.0 && abs(g.x) < 293.0 && g.y > -110.0 && g.y < 10.0) { c = uPal2 * 0.9; v = max(v, 0.85); }
    }
    return vec4(c, v);
}

vec4 gridCell(vec2 ci) {
    vec2 sc = uRes * 0.5 + (ci + 0.5) * PITCH;
    return pCell(facePos(sc), ci, sc);
}

void pGrid(inout vec4 acc) {
    vec2 rel = gFC - uRes * 0.5;
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
    pGrid(acc);
}
"""

# ── MOCHI: a pink plush round a dark display ──────────────────────────────────
_MOCHI = """
vec2 mBC() { return uChA.xy + vec2(0.0, 54.0); }
const vec2 M_BB = vec2(246.0, 164.0);
const vec2 M_DB = vec2(204.0, 124.0);

// the plush: a soft rounded head and two side pods
float mBody(vec2 p) {
    vec2 q = p - mBC();
    float head = sdRoundBox(q, M_BB, 118.0);
    vec2 pq = vec2(abs(q.x) - 246.0, q.y - 30.0);
    return smin(head, ellD(pq, vec2(38.0, 74.0)), 16.0);
}

void mBodyDraw(vec2 p, inout vec4 acc) {
    float d = mBody(p);
    float a = cover(d);
    if (a <= 0.0) return;
    vec2 g = normalize(vec2(mBody(p + vec2(1.0, 0.0)) - d, mBody(p + vec2(0.0, 1.0)) - d) + 1e-6);
    vec2 q = p - mBC();
    float pod = smoothstep(196.0, 236.0, abs(q.x));
    vec3 c = mix(uPal0, uPal1, clamp(0.35 + 0.45 * q.y / M_BB.y, 0.0, 1.0));
    c = mix(c, uPal1 * 0.92, pod * 0.8);
    c = lit(c, g, d, 46.0, q / M_BB * 0.25);
    c += vec3(1.0, 0.92, 0.95) * 0.20 * exp(d / 10.0) * smoothstep(0.0, -60.0, q.y);   // a soft rim
    // the dark display, inset, with a soft pink edge light
    vec2 dq = q - vec2(0.0, -4.0);
    float dd = sdRoundBox(dq, M_DB, 74.0);
    vec3 disp = vec3(0.040, 0.026, 0.040) * (1.0 - 0.35 * dot(dq / M_DB, dq / M_DB));
    vec2 hq = (dq / M_DB - vec2(-0.45, -0.62)) * vec2(2.0, 4.5);
    disp += vec3(0.05, 0.04, 0.05) * exp(-dot(hq, hq));            // a sheen
    disp += uPal3 * 0.16 * exp(dd / 9.0);                           // its edge glows pink
    if (uBlush.z + uChF.x * uEnergy > 0.01) {                      // rosy cheeks (and her voice)
        for (int k = 0; k < 2; k++) {
            vec2 bq = (p - vec2(uChA.x + (k == 0 ? -150.0 : 150.0), uEye0.y + uEye0.w * 0.55 + 14.0))
                      / vec2(34.0, 16.0);
            disp += uPal3 * (0.55 * uBlush.z + 0.35 * uChF.x * uEnergy) * exp(-dot(bq, bq) * 1.5);
        }
    }
    c = mix(c, disp, cover(dd));
    c = mix(c, uPal1 * 0.62, cover(abs(dd) - 2.0) * 0.6);           // the display's lip
    over(acc, c * mix(1.0, uDim, 0.35), a);
}

// bunny ears behind the head: droop when sad, prick up when surprised, wiggle when happy
void mEars(vec2 p, inout vec4 acc) {
    float tilt = 0.30 + 0.55 * uChB.y - 0.16 * uChB.w + 0.06 * uChB.x * sin(uT * 7.0)
                 + 0.25 * uChC.y - 0.14 * uChE.w + 0.10 * uChB.z;      // (listening: pricked up)
    for (int k = 0; k < 2; k++) {
        float side = k == 0 ? -1.0 : 1.0;
        vec2 base = mBC() + vec2(side * 112.0, -M_BB.y + 10.0);
        vec2 q = rot2(p - base, -side * tilt);
        q.y += 62.0;
        float d = ellD(q, vec2(40.0, 66.0));
        float a = cover(d);
        if (a <= 0.0) continue;
        vec3 c = mix(uPal0, uPal1, 0.25 + 0.3 * q.y / 66.0);
        c = mix(c, mix(uPal3, uPal0, 0.45), cover(ellD(q - vec2(0.0, 6.0), vec2(20.0, 46.0))));
        c *= 0.9 + 0.2 * exp(d / 12.0) * step(q.x * side, 0.0);
        over(acc, c * mix(1.0, uDim, 0.35), a);
    }
}

// in front of the head: a flower, a sleeping cap
void mFront(vec2 p, inout vec4 acc) {
    if (uAcc.y > 0.5) {
        vec2 fq = rot2(p - (mBC() + vec2(186.0, -150.0)), 0.3 * sin(uT * 0.8));
        float a = atan(fq.y, fq.x);
        float r = length(fq);
        float petal = r - (19.0 + 8.0 * cos(5.0 * a));
        vec3 c = mix(vec3(1.0, 0.97, 0.98), uPal3, smoothstep(6.0, 26.0, r) * 0.55);
        over(acc, c, cover(petal));
        over(acc, vec3(1.0, 0.82, 0.30) * (1.1 - 0.4 * clamp(fq.y / 8.0, -1.0, 1.0)), cover(r - 8.0));
    }
    if (uAcc.z > 0.5 && uChC.y > 0.02) {
        vec2 b = mBC() + vec2(-40.0, -M_BB.y - 6.0);
        vec2 tip = mBC() + vec2(-250.0, -M_BB.y + 40.0);
        vec2 ba = tip - b;
        float h = clamp(dot(p - b, ba) / dot(ba, ba), 0.0, 1.0);
        float cone = length(p - b - ba * h) - mix(92.0, 12.0, pow(h, 0.8));
        float band = sdRoundBox(rot2(p - b - vec2(0.0, 2.0), 0.1), vec2(100.0, 16.0), 12.0);
        float pom = length(p - tip) - 22.0;
        float al = uChC.y;
        vec3 hc = mix(vec3(0.85, 0.25, 0.42), uPal3, 0.4) * (1.0 - 0.25 * h);
        over(acc, hc, cover(cone) * al);
        over(acc, vec3(1.0, 0.97, 0.98), cover(band) * al);
        over(acc, vec3(1.0, 0.98, 0.99), cover(pom) * al);
    }
}

void mEye(vec2 p, vec4 e, vec4 la, vec4 lb, vec4 pu, float side, inout vec4 acc) {
    vec2 q;
    float d = eyeD(p, e, la, lb, side, q);
    float ds = seamD(q, e, la, lb, side) - 1.5;
    float a = cover(d);
    float sa = cover(ds) * lb.y;
    if (a > 0.0) {
        vec2 b = e.zw * 0.5;
        vec3 c = mix(uPal2, vec3(0.88, 0.90, 1.0), smoothstep(-0.2, 1.0, q.y / b.y) * 0.4);
        vec2 hp = (q - pu.xy * 0.4 - vec2(-0.32 * b.x, -0.40 * b.y)) / (0.20 * min(b.x, b.y));
        c = mix(c, vec3(1.0), exp(-dot(hp, hp)) * 0.7);
        c = mix(c, uPal3, exp(d / 5.0) * smoothstep(0.1, 1.0, q.y / b.y) * 0.55);
        over(acc, c * uDim, a);
    }
    if (sa > 0.0) over(acc, uPal2 * uDim, sa);
    acc.rgb += vec3(1.0, 0.88, 0.94) * 0.30 * halo(min(d, mix(1e5, ds, lb.y)), 7.0)
               * (1.0 - max(a, sa)) * uChA.w * uDim;
}

void mMouth(vec2 p, inout vec4 acc) {
    if (uMouthK.z <= 0.01) return;
    float inner, teeth, tongue;
    float d = mouthSDF(p - uMouth.xy, inner, teeth, tongue);
    float a = cover(d) * uMouthK.z;
    vec3 c = uPal2;
    if (inner < 1e4) {
        vec3 ins = mix(vec3(0.22, 0.04, 0.08), uPal3, tongue * 0.8);
        c = mix(c, ins, cover(inner));
    }
    over(acc, c * uDim, a);
    acc.rgb += uPal3 * 0.25 * halo(d, 5.0) * uMouthK.z * (1.0 - a) * uDim;
}

vec3 soft(vec2 p, vec2 uv) {
    vec2 vq = uv - vec2(0.5, 0.52);
    vec3 col = vec3(0.045, 0.026, 0.040) * (1.0 - 1.3 * dot(vq, vq));
    float d = mBody(p - vec2(0.0, 14.0));
    col *= 1.0 - 0.6 * exp(-max(d, 0.0) / 22.0);                 // its shadow
    col += uPal3 * 0.10 * exp(-max(mBody(p), 0.0) / 30.0) * uChA.w;   // a soft pink light round it
    if (uChH.y < 0.999)                                              // waking: a pink pop
        col += uPal3 * 0.6 * exp(-abs(length(p - mBC()) - 120.0 - uChH.y * 380.0) / 14.0) * (1.0 - uChH.y);
    return col;
}

void shape(vec2 p, inout vec4 acc) {
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
    else if (uShape < 8.5) {}                      // (props: above)
    else if (uShape < 10.5) mEars(p, acc);
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
# 11 one in front, 12-15 the state's own marks uPt4-7
EYE0, EYE1, MOUTH, BODY, BROWS, PROP, SCREEN, ACC, FRONT, STATE = 0, 1, 2, 3, 4, 5, 9, 10, 11, 12

# the margin round an eye's / the mouth's box for its own halo (px)
_HALO = {"mochi": 14.0, "pip": 18.0}

_rng = [None]                    # tests: a seeded random for the characters' habits


def seed(n):
    _rng[0] = random.Random(n)


# the characters drawn from a grid of cells: (columns, rows) round the face's centre
GRIDS = {"retro": (62, 38), "pixel": (50, 30)}


def grid_size(kind, w, h):
    """(columns, rows) of a character's cells texture; PIXEL's covers the screen."""
    if kind == "pixel":
        cols, rows = -(-int(w) // PIXEL_PITCH), -(-int(h) // PIXEL_PITCH)
        return cols + cols % 2, rows + rows % 2
    return GRIDS[kind]


class CharPass:
    """The characters' programs (compiled when first shown) and their draws."""

    def __init__(self, gl):
        self.gl = gl
        self.progs = {}
        self.made = 0
        self.grids = {}                  # kind → (texture, framebuffer)
        self.broken = set()              # kinds whose shader did not compile

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
            cols, rows = grid_size(kind, self.gl.w, self.gl.h)
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
            fs = head + PASSES[stage] + _HEAD + SOURCES[kind] + _MAIN
            t0 = time.perf_counter()
            p = gl_face._Prog(gl.GL, gl._program(head + gl_face._VERT, fs))
            gl.GL.glUseProgram(p.id)
            p.u("uRes", (gl.w, gl.h))
            p.u("uSoftRes", (gl.sw, gl.sh))
            p.unit("uCells", 4)
            if kind in GRIDS:
                cols, rows = grid_size(kind, self.gl.w, self.gl.h)
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
            cols, rows = grid_size(kind, self.gl.w, self.gl.h)
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
    love = u["uMorph"][0]
    if kind == "mochi":
        k = max(cel, love * 0.8) * ("hearts" in acc)
        for i in range(3 if k > 0.02 else 0):
            t = (now * 0.45 + i / 3.0) % 1.0
            side = -1.0 if i % 2 else 1.0
            x = fcx + side * (215.0 + 25.0 * i) + 14.0 * math.sin(now * 2.0 + i)
            y = fcy + 30.0 - 190.0 * t
            out.append(((x, y, 34.0 - 8.0 * t, 1.0 + 0.98 * min(1.0, 1.4 * k * math.sin(math.pi * t))),
                        False))
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
    if kind in ("mochi", "pip") and ch["confused"] + ch["curious"] > 0.03:
        k = max(ch["confused"], ch["curious"] * 0.7)
        out.append(((fcx + 270.0, fcy - 150.0 - 8.0 * math.sin(now * 3.0), 40.0, 2.0 + 0.98 * k), False))
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
            at(fcx + side * 336.0, fcy + 60.0, 46.0, 15.0, listen)
        at(fcx + 240.0, fcy - 150.0, 62.0, 11.0, think)  # a thought cloud
        for ph in (0.0, 0.5):
            t = (zt + ph) % 1.0
            at(fcx + 318.0 + 26.0 * t, fcy - 40.0 - 120.0 * t, 22.0 + 10.0 * t, 9.0,   # (past her ear)
               sleep * math.sin(math.pi * t))
    if kind == "pip":
        at(e1[0] + e1[2] * 0.5 + 56.0, e1[1] - e1[3] * 0.5 - 10.0, 40.0, 12.0, listen)  # signal bars
        for ph in (0.0, 0.5):
            t = (zt + ph) % 1.0
            at(fcx + 220.0 + 30.0 * t, fcy - 50.0 - 110.0 * t, 22.0 + 10.0 * t, 9.0,
               sleep * math.sin(math.pi * t))
    if kind in ("mochi", "pip") and sad > 0.02:         # a tear
        at(e0[0] - e0[2] * 0.22, e0[1] + e0[3] * 0.5 + 10.0 + 60.0 * tt, 16.0, 8.0, sad * tk)
    if kind in ("mochi", "pip"):
        at(e1[0] + e1[2] * 0.5 + 40.0, e1[1] - e1[3] * 0.5 - 30.0, 36.0, 10.0,
           angry * (0.7 + 0.3 * math.sin(now * 6.0)))
        at(fcx - 270.0, fcy - 150.0, 44.0, 7.0, bang)
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


def _box(gl, x0, y0, x1, y1, tilt):
    return gl._box((x0 + x1) / 2.0, (y0 + y1) / 2.0, (x1 - x0) / 2.0, (y1 - y0) / 2.0, tilt)


def _boxes(gl, kind, u, ch, props, fcx, fcy, console, acc, marks=()):
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
        out.append((SCREEN, (0.0, 0.0, float(gl.w), float(gl.h))))   # the whole screen, fixed
    by = fcy + 54.0                                    # MOCHI's head
    if kind == "mochi":
        if "ears" in acc:
            add(ACC, fcx, by - 164.0 - 40.0, 205.0, 92.0)
        add(BODY, fcx, by, 300.0, 172.0)
    if kind in _HALO:
        m = _HALO[kind]
        for i in (0, 1):
            ex, ey, w, h = u[f"uEye{i}"]
            add(EYE0 + i, ex, ey, w / 2 + m, h / 2 + m)
        mx, my, w, h = u["uMouth"]
        bend, _, alpha, mk = u["uMouthK"]
        if alpha > 0.01:
            add(MOUTH, mx, my, w / 2 + h / 2 + m, max(h, w * (mk == 2.0)) / 2 + h + abs(bend)
                + abs(u["uMouthSlant"]) + m)
    if kind == "pip":
        if "sprout" in acc or "cap" in acc:
            add(ACC, fcx + 10.0, fcy - 172.0, 130.0, 92.0)
        if "bowtie" in acc:
            add(FRONT, fcx, fcy + 186.0, 70.0, 32.0)
    if kind == "mochi":
        if "flower" in acc:
            add(FRONT, fcx + 186.0, by - 150.0, 36.0, 36.0)
        if "hat" in acc and ch["sleep"] > 0.02:
            add(FRONT, fcx - 145.0, by - 147.0, 200.0, 118.0)
    for i, (pt, behind) in enumerate(props):
        if not behind:
            add(PROP + i, pt[0], pt[1], pt[2] * 1.35 + 22, pt[2] * 1.35 + 22)
    for i, pt in enumerate(marks):                     # the state's own marks, on top
        r = pt[2] * 1.35 + 22
        add(STATE + i, pt[0], pt[1], r, r)
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
    if kind == "mochi" and ch["confused"] > 0.02:     # puzzled: one eye smaller
        ex, ey, w, h = u["uEye1"]
        u["uEye1"] = (ex, ey + 6.0 * ch["confused"], w * (1.0 - 0.12 * ch["confused"]),
                      h * (1.0 - 0.28 * ch["confused"]))
    sway_y = ch["body_y"]
    if kind == "mochi":                           # a soft float; a bounce when happy
        sway_y += ch["motion"] * (3.0 * math.sin(now * 1.3)
                                  - 6.0 * ch["happy"] * abs(math.sin(now * 4.0)))
    if kind == "pip" and ch["happy"] > 0.3:       # bouncy
        sway_y -= 4.0 * ch["motion"] * ch["happy"] * abs(math.sin(now * 5.0))
    ch["body_y"] = sway_y
    music = 1.0 if u.get("_vis") else 0.0
    pal = cfg["pal"]
    props = _props(kind, life, ch, u, fcx, fcy, now, acc)
    pts = [p for p, _ in props] + [(0.0, 0.0, 0.0, 0.0)] * (4 - len(props))
    marks = _state_props(kind, ch, u, fcx, fcy, now)
    sts = marks + [(0.0, 0.0, 0.0, 0.0)] * (4 - len(marks))
    u.update({
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
    u["_char_boxes"] = _boxes(gl, kind, u, ch, props, fcx, fcy, console, acc, marks)
    gl.char_now = ch
    return u
