"""
gl_fx.py — what moves over the GPU face, drawn by the GPU too: the listening
waves (crescents as distance fields), lines (whiskers, springs, confetti),
the hands and a costume's pieces (images made once at 2× and mipmapped, then
turned and placed to a fraction of a pixel), and HAL's glyphs (an hourglass,
a cursor, a tick… instead of hands).

Drawn on pygame's layer they were placed to whole pixels (the waves stepped
2 px at a time), turned by pygame.transform.rotate (no filtering: jagged
ears and cogs) and then turned again with the head, from the layer.

robot_face collects a frame's items (the tuples below) in two lists — behind
the face and in front of it — and GLFace.render draws them (FxPass.draw), each
in its own small box, turned with the head about the screen's centre.
"""

import ctypes
import math
from collections import OrderedDict

# ── the items (pure Python: robot_face builds them, the tests read them) ─────

def sprite(key, make, x, y, angle=0.0, scale=1.0, alpha=1.0, flip=(1.0, 1.0), res=2):
    """An image centred at (x, y), turned angle degrees anticlockwise (as
    pygame.transform.rotate). make(res) draws it at res× (once per key; 4
    for an image whose edges pygame doesn't smooth); scale: screen px per
    image px at res 1, or (across, down)."""
    sx, sy = scale if isinstance(scale, tuple) else (scale, scale)
    return ("sprite", key, make, float(x), float(y), float(angle), (float(sx), float(sy)),
            float(alpha), flip, res)


def arcs(x, y, side, rings, col, core=None):
    """")" (side 1) or "(" crescents round (x, y): rings = [(radius, alpha)…],
    up to three — thick in the middle, thin at the ends, glowing."""
    rings = (list(rings) + [(10.0, 0.0)] * 3)[:3]
    core = core or tuple(c + (255 - c) * 0.25 for c in col)
    return ("arcs", float(x), float(y), float(side), tuple(float(r) for r, _ in rings),
            tuple(max(0.0, min(1.0, float(a))) for _, a in rings), col, core)


def lines(pts, width, col, alpha=1.0, core=None, core_w=0.0, pairs=False, glow=0.0):
    """A polyline (or, pairs: separate segments 0-1, 2-3…) up to 16 points,
    width px with round ends; core: a thinner line of another colour along
    it (core_w px). One point: a dot."""
    return ("lines", tuple((float(x), float(y)) for x, y in pts[:16]), float(width),
            col, float(alpha), core or col, float(core_w), bool(pairs), float(glow))


def ring(x, y, r, width, col, alpha=1.0, glow=0.0):
    """A circle's outline, width px (a sound wave round the mouth, the
    wake ripple); glow: a halo that far out (px)."""
    return ("ring", float(x), float(y), float(r), float(width), col, float(alpha), float(glow))


def hand(parts, x, y, angle, cols, flip=(1.0, 1.0), alpha=1.0):
    """A hand (robot_face.hand_parts) centred at (x, y), turned angle
    degrees; cols: (top, bottom, crease, glow); flip: (-1, 1) the left hand,
    (1, -1) upside down. Distance fields: exact edges at any turn."""
    return ("hand", tuple(parts), float(x), float(y), float(angle), cols,
            (float(flip[0]), float(flip[1])), float(alpha))


GLYPHS = {"hourglass": 1, "cursor": 2, "check": 3, "cross": 4, "rock": 5, "paper": 6,
          "scissors": 7, "signal": 8, "heart": 9}
CURSOR_TIP = (-0.45, -0.80)          # the cursor's tip, × its size, from its centre


def glyph(name, x, y, size, col, core, angle=0.0, alpha=1.0, t=0.0, width=4.0):
    """One of GLYPHS, line art glowing like a display: size px from its
    centre to its edge, t its animation (the hourglass's sand 0..1)."""
    return ("glyph", GLYPHS[name], float(x), float(y), float(size), col, core,
            float(angle), float(alpha), float(t), float(width))


HAND_HALF = (120.0, 144.0)            # a hand's box round its centre (its own frame)


def hand_uniforms(parts):
    """(boxes, their corners/turns/light, how many, the ring) for the shader:
    each box (cx, cy, half w, half h) and (corner, radians, the hand's light
    at its top and bottom 0..1) in the hand's 120x150 frame."""
    hb, hk, ring = [], [], (0.0, 0.0, 0.0, 0.0)
    for part in parts:
        if part[0] == "ring":
            ring = (float(part[1]), float(part[2]), 0.0, 1.0)
            continue
        _, w, h, r, cx, cy, ang = part
        light = [max(0.0, min(1.0, y / 150.0)) ** 1.1 for y in (cy - h / 2, cy + h / 2)]
        hb += [cx, cy, w / 2, h / 2]
        hk += [r, math.radians(ang), *light]
    return hb[:32], hk[:32], min(8, len(hb) // 4), ring


def bounds(item):
    """The box an item covers before the head turns it: (x0, y0, x1, y1)."""
    kind = item[0]
    if kind == "sprite":
        return None                           # (its image's size: known once made)
    if kind == "arcs":
        _, x, y, side, radii, alphas, _, _ = item
        r = max(r for r, a in zip(radii, alphas) if a > 0) if any(alphas) else 0.0
        x0, x1 = (x, x + side * (r + 24)) if side > 0 else (x + side * (r + 24), x)
        return (x0, y - r * 0.75 - 24, x1, y + r * 0.75 + 24)
    if kind == "lines":
        pts, w, glow = item[1], item[2], item[8]
        pad = w / 2 + 2 + glow * 4
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    if kind == "hand":
        return (-HAND_HALF[0], -HAND_HALF[1], HAND_HALF[0], HAND_HALF[1])
    if kind == "ring":
        _, x, y, r, w, _, _, glow = item
        e = r + w / 2 + 2 + glow * 4
        return (x - e, y - e, x + e, y + e)
    if kind == "glyph":
        x, y, s = item[2], item[3], item[4]
        r = s * 1.45 + 18                     # (any turn, and the glow)
        return (x - r, y - r, x + r, y + r)
    return None


# ── the GPU side ─────────────────────────────────────────────────────────────

_VERT = """
attribute vec2 aPos;
uniform vec2  uRes;
uniform float uTilt;          // the head's turn (the face's layers turn with it)
uniform vec2  uC;             // the item's centre (px, top-left origin)
uniform vec2  uHalf;          // its box's half size (px)
uniform vec2  uOff;           // the box's centre in the item's own frame
uniform float uRot;           // the item's own turn (rad, anticlockwise)
varying vec2  vL;             // px in the item's frame (y down), 0: its centre
void main() {
    vL = aPos * vec2(1.0, -1.0) * uHalf + uOff;
    float c = cos(uRot), s = sin(uRot);
    vec2 p = uC + vec2(c * vL.x + s * vL.y, -s * vL.x + c * vL.y);
    vec2 c0 = uRes * 0.5;
    vec2 d = p - c0;
    float ct = cos(uTilt), st = sin(uTilt);
    p = c0 + vec2(ct * d.x + st * d.y, -st * d.x + ct * d.y);
    gl_Position = vec4(p.x / uRes.x * 2.0 - 1.0, 1.0 - p.y / uRes.y * 2.0, 0.0, 1.0);
}
"""

_FRAG = """
varying vec2  vL;
uniform float uKind;          // 0 image, 1 crescents, 2 lines, 3 glyph, 4 hand, 5 ring
uniform vec2  uHalf;
uniform vec2  uOff;
uniform vec2  uFlip;          // the image mirrored: -1
uniform sampler2D uTex;       // (premultiplied, mipmapped)
uniform vec4  uCol;           // the colour (the glow's), alpha
uniform vec3  uCore;          // the bright middle of a line / a glyph
uniform vec4  uP;             // crescents: side; lines: pairs, width, core width, glow;
                              // glyph: which, size px, line width px, t
uniform vec3  uR;             // crescents: radii
uniform vec3  uA;             //   …and their alphas
uniform vec2  uPts[16];       // lines: points (px, the item's frame)
uniform float uN;
uniform vec4  uHB[8];         // a hand's boxes: cx, cy, half w, half h (its 120x150 frame)
uniform vec4  uHK[8];         //   corner, turn (rad), its light at the top, the bottom 0..1
uniform float uHN;
uniform vec4  uHRing;         //   the "O" of "ok": cx, cy, -, on
uniform vec3  uHTop, uHBot, uHCrease;

float dot2(vec2 v) { return dot(v, v); }
float sdSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0);
    return length(pa - ba * h);
}
// one edge of a polygon (iq): the nearest squared distance, the inside's sign
void edge(vec2 p, vec2 a, vec2 b, inout float d, inout float s) {
    vec2 e = b - a, w = p - a;
    vec2 q = w - e * clamp(dot(w, e) / dot(e, e), 0.0, 1.0);
    d = min(d, dot(q, q));
    bvec3 c = bvec3(p.y >= a.y, p.y < b.y, e.x * w.y > e.y * w.x);
    if (all(c) || all(not(c))) s = -s;
}
float sdHeart(vec2 p) {       // y up, its tip at (0, 0), lobes up to ~1.1
    p.x = abs(p.x);
    if (p.y + p.x > 1.0) return sqrt(dot2(p - vec2(0.25, 0.75))) - 0.35355;
    return sqrt(min(dot2(p - vec2(0.0, 1.0)), dot2(p - 0.5 * max(p.x + p.y, 0.0))))
           * sign(p.x - p.y);
}
float ring(vec2 q, float r) { return abs(length(q) - r); }
float sdRBox(vec2 q, vec2 b, float r) {
    r = min(r, min(b.x, b.y));
    vec2 d = abs(q) - b + r;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - r;
}

// a hand: rounded blocks painted in order, each with a crease round it and
// the light of robot_face.gradient_block (a dome, a sheen); a glow and a soft
// shadow under the whole
vec3 dome(vec2 q, vec2 hb, vec3 top, vec3 bot) {
    float ys = clamp((q.y + hb.y) / (2.0 * hb.y), 0.0, 1.0);
    float xs = clamp(q.x / hb.x, -1.0, 1.0);
    vec3 c = mix(top, bot, pow(ys, 1.25));
    float dy = (ys - 0.42) * 2.0;
    c *= 1.06 - 0.34 * clamp(xs * xs * 0.9 + dy * dy * 1.1, 0.0, 1.6);
    float sx = xs * 1.15, sy = (ys - 0.24) * 3.2;
    return min(c + exp(-(sx * sx + sy * sy) * 2.2) * 0.35, vec3(1.0));
}
vec4 over(vec4 acc, vec3 c, float a) { return vec4(c * a, a) + acc * (1.0 - a); }
vec3 handLight(float y) { return mix(uHTop, uHBot, pow(clamp(y / 150.0, 0.0, 1.0), 1.1)); }

vec4 hand(vec2 p) {
    float S = 1.6;                                    // px per unit of its frame
    vec2 u = p * uFlip / S + vec2(60.0, 75.0);
    vec2 us = (p - vec2(5.0, 9.0)) * uFlip / S + vec2(60.0, 75.0);   // the shadow's
    vec4 acc = vec4(0.0);
    float du = 1e3, ds = 1e3;
    for (int i = 0; i < 8; i++) {
        if (float(i) < uHN) {
            vec4 b = uHB[i], k = uHK[i];
            float cs = cos(k.y), sn = sin(k.y);
            vec2 d = u - b.xy, e = us - b.xy;
            vec2 q = vec2(cs * d.x - sn * d.y, sn * d.x + cs * d.y);
            vec2 qs = vec2(cs * e.x - sn * e.y, sn * e.x + cs * e.y);
            float de = sdRBox(q, b.zw + 1.5, k.x + 1.5) * S;
            float df = sdRBox(q, b.zw, k.x) * S;
            acc = over(acc, uHCrease, clamp(0.5 - de, 0.0, 1.0));
            acc = over(acc, dome(q, b.zw, mix(uHTop, uHBot, k.z), mix(uHTop, uHBot, k.w)),
                       clamp(0.5 - df, 0.0, 1.0));
            du = min(du, de);
            ds = min(ds, sdRBox(qs, b.zw + 1.5, k.x + 1.5) * S);
        }
    }
    if (uHRing.w > 0.5) {                             // thumb + index: the "O"
        vec2 d = u - uHRing.xy;
        float l = length(d);
        acc = over(acc, uHCrease, clamp(0.5 - (l - 24.5) * S, 0.0, 1.0));
        acc = over(acc, dome(d, vec2(23.0), handLight(uHRing.y - 23.0), handLight(uHRing.y + 23.0)),
                   clamp(0.5 - (l - 23.0) * S, 0.0, 1.0));
        acc = over(acc, uHCrease, clamp(0.5 - (l - 12.5) * S, 0.0, 1.0));
        acc *= clamp((l - 11.0) * S + 0.5, 0.0, 1.0);
        du = min(du, (l - 24.5) * S);
        ds = min(ds, (length(us - uHRing.xy) - 24.5) * S);
    }
    float glow = 0.24 * exp(-max(du, 0.0) / 6.0);
    float shadow = 0.47 * (1.0 - smoothstep(-5.0, 8.0, ds));
    vec4 under = over(vec4(uCol.rgb * glow, glow), vec3(0.0), shadow);
    return acc + under * (1.0 - acc.a);
}

// a glyph at q (units of its size, y down): (line, fill, solid) distances —
// the outline drawn bright, the inside dim, the solid parts lit whole
vec3 glyph(vec2 q, float id, float t) {
    float big = 1e3;
    float ln = big, fl = big, so = big;
    if (id < 1.5) {                                   // hourglass
        float d = 1e9, s = 1.0;
        vec2 a = vec2(-0.50, -0.78), b = vec2(0.50, -0.78), c = vec2(0.08, 0.0),
             e = vec2(0.50, 0.78), f = vec2(-0.50, 0.78), g = vec2(-0.08, 0.0);
        edge(q, a, b, d, s); edge(q, b, c, d, s); edge(q, c, e, d, s);
        edge(q, e, f, d, s); edge(q, f, g, d, s); edge(q, g, a, d, s);
        float glass = s * sqrt(d);
        ln = min(abs(glass), min(sdSeg(q, vec2(-0.64, -0.88), vec2(0.64, -0.88)),
                                 sdSeg(q, vec2(-0.64, 0.88), vec2(0.64, 0.88))));
        fl = glass;
        float inner = glass + 0.08;
        float top = max(inner, max(-0.62 * (1.0 - t) - q.y, q.y + 0.03));
        float pile = 0.70 - 0.58 * t + 0.42 * abs(q.x) * t;
        float bot = max(inner, max(pile - q.y, q.y - 0.70));
        so = min(top, t > 0.01 ? bot : big);
        if (t > 0.02 && t < 0.97)
            so = min(so, sdSeg(q, vec2(0.0, 0.0), vec2(0.0, pile)) - 0.025);
    } else if (id < 2.5) {                            // cursor (its tip: CURSOR_TIP)
        float d = 1e9, s = 1.0;
        vec2 o = vec2(-0.45, -0.80);
        vec2 p0 = o, p1 = o + vec2(0.0, 1.38), p2 = o + vec2(0.33, 1.05),
             p3 = o + vec2(0.55, 1.56), p4 = o + vec2(0.74, 1.47),
             p5 = o + vec2(0.52, 0.98), p6 = o + vec2(0.95, 0.98);
        edge(q, p0, p1, d, s); edge(q, p1, p2, d, s); edge(q, p2, p3, d, s);
        edge(q, p3, p4, d, s); edge(q, p4, p5, d, s); edge(q, p5, p6, d, s);
        edge(q, p6, p0, d, s);
        fl = s * sqrt(d);
        ln = abs(fl);
    } else if (id < 4.5) {                            // tick / cross in a ring
        ln = ring(q, 0.80);
        fl = length(q) - 0.80;
        if (id < 3.5) {
            ln = min(ln, min(sdSeg(q, vec2(-0.38, 0.02), vec2(-0.10, 0.32)),
                             sdSeg(q, vec2(-0.10, 0.32), vec2(0.42, -0.30))));
        } else {
            ln = min(ln, min(sdSeg(q, vec2(-0.32, -0.32), vec2(0.32, 0.32)),
                             sdSeg(q, vec2(0.32, -0.32), vec2(-0.32, 0.32))));
        }
    } else if (id < 5.5) {                            // rock
        float d = 1e9, s = 1.0;
        vec2 a = vec2(-0.72, 0.18), b = vec2(-0.48, -0.45), c = vec2(0.02, -0.70),
             e = vec2(0.58, -0.48), f = vec2(0.78, 0.10), g = vec2(0.45, 0.62),
             h = vec2(-0.35, 0.64);
        edge(q, a, b, d, s); edge(q, b, c, d, s); edge(q, c, e, d, s);
        edge(q, e, f, d, s); edge(q, f, g, d, s); edge(q, g, h, d, s);
        edge(q, h, a, d, s);
        fl = s * sqrt(d);
        ln = min(abs(fl), min(sdSeg(q, vec2(-0.10, -0.66), vec2(0.06, -0.22)),
                              sdSeg(q, vec2(0.06, -0.22), vec2(-0.16, 0.16))));
    } else if (id < 6.5) {                            // a sheet of paper
        float d = 1e9, s = 1.0;
        vec2 a = vec2(-0.55, -0.80), b = vec2(0.22, -0.80), c = vec2(0.55, -0.47),
             e = vec2(0.55, 0.80), f = vec2(-0.55, 0.80);
        edge(q, a, b, d, s); edge(q, b, c, d, s); edge(q, c, e, d, s);
        edge(q, e, f, d, s); edge(q, f, a, d, s);
        fl = s * sqrt(d);
        ln = min(abs(fl), min(sdSeg(q, vec2(0.22, -0.80), vec2(0.22, -0.47)),
                              sdSeg(q, vec2(0.22, -0.47), vec2(0.55, -0.47))));
        ln = min(ln, sdSeg(q, vec2(-0.33, -0.22), vec2(0.33, -0.22)));
        ln = min(ln, sdSeg(q, vec2(-0.33, 0.08), vec2(0.33, 0.08)));
        ln = min(ln, sdSeg(q, vec2(-0.33, 0.38), vec2(0.10, 0.38)));
    } else if (id < 7.5) {                            // scissors
        ln = min(ring(q - vec2(-0.30, 0.56), 0.21), ring(q - vec2(0.30, 0.56), 0.21));
        ln = min(ln, min(sdSeg(q, vec2(-0.17, 0.40), vec2(0.32, -0.86)),
                         sdSeg(q, vec2(0.17, 0.40), vec2(-0.32, -0.86))));
        so = length(q - vec2(0.0, -0.04)) - 0.07;
    } else if (id < 8.5) {                            // a signal: a lens, waves out of it
        so = length(q) - 0.20;
        ln = ring(q, 0.32);
        vec2 h = vec2(abs(q.x), q.y);
        float ang = abs(atan(h.y, h.x));
        float r = length(h);
        for (int i = 0; i < 2; i++) {
            float rr = i == 0 ? 0.56 : 0.84;
            ln = min(ln, max(abs(r - rr), (ang - 0.62) * r));
        }
        fl = big;
    } else {                                          // heart
        vec2 hp = vec2(q.x, -q.y) * 0.62 + vec2(0.0, 0.52);
        fl = sdHeart(hp) / 0.62;
        ln = abs(fl);
    }
    return vec3(ln, fl, so);
}

void main() {
    vec2 p = vL;
    if (uKind < 0.5) {                                // an image
        vec2 uv = (p - uOff) / uHalf * uFlip * 0.5 + 0.5;
        gl_FragColor = texture2D(uTex, uv) * uCol.a;
    } else if (uKind < 1.5) {                         // crescents: sound coming in
        vec2 q = vec2(p.x * uP.x, p.y);
        float a = atan(q.y, q.x);
        float span = 0.80;
        float u = clamp((a + span) / (2.0 * span), 0.0, 1.0);
        float th = 7.0 * (0.25 + 0.75 * sin(3.14159 * u));
        float len = length(q);
        float cut = (abs(a) - span) * len;            // past its ends (px)
        vec4 o = vec4(0.0);
        for (int i = 0; i < 3; i++) {
            float r = i == 0 ? uR.x : (i == 1 ? uR.y : uR.z);
            float al = i == 0 ? uA.x : (i == 1 ? uA.y : uA.z);
            if (al > 0.004) {
                float d = max(abs(len - r) - th * 0.5, cut);
                float core = clamp(0.5 - d, 0.0, 1.0);
                float halo = 0.45 * exp(-max(d, 0.0) / 4.5) * (1.0 - core);
                o += al * vec4(uCore * core + uCol.rgb * halo, core + halo);
            }
        }
        gl_FragColor = min(o, vec4(1.0));
    } else if (uKind < 2.5) {                         // lines
        float d = 1e5;
        if (uN < 1.5) {
            d = length(p - uPts[0]);
        } else {
            for (int i = 0; i < 15; i++) {
                if (float(i) < uN - 1.0 && (uP.x < 0.5 || mod(float(i), 2.0) < 0.5))
                    d = min(d, sdSeg(p, uPts[i], uPts[i + 1]));
            }
        }
        float o = clamp(uP.y * 0.5 - d + 0.5, 0.0, 1.0);
        float c = clamp(uP.z * 0.5 - d + 0.5, 0.0, 1.0);
        float halo = uP.w > 0.0 ? 0.4 * exp(-max(d - uP.y * 0.5, 0.0) / uP.w) * (1.0 - o) : 0.0;
        vec3 rgb = mix(uCol.rgb, uCore, c) * o + uCol.rgb * halo;
        gl_FragColor = vec4(rgb, o + halo) * uCol.a;
    } else if (uKind > 4.5) {                         // a ring: uP = (radius, width, glow)
        float d = abs(length(p) - uP.x);
        float o = clamp(uP.y * 0.5 - d + 0.5, 0.0, 1.0);
        float halo = uP.z > 0.0 ? 0.4 * exp(-max(d - uP.y * 0.5, 0.0) / uP.z) * (1.0 - o) : 0.0;
        gl_FragColor = vec4(uCol.rgb * (o + halo), o + halo) * uCol.a;
    } else if (uKind > 3.5) {                         // a hand
        gl_FragColor = hand(p) * uCol.a;
    } else {                                          // a glyph
        float s = uP.y, w = uP.z;
        vec3 g = glyph(p / s, uP.x, uP.w) * s;
        float lit = max(clamp(w * 0.5 - g.x + 0.5, 0.0, 1.0), clamp(0.5 - g.z, 0.0, 1.0));
        float fill = clamp(0.5 - g.y, 0.0, 1.0) * 0.20;
        float halo = 0.55 * exp(-max(min(g.x - w * 0.5, g.z), 0.0) / 6.0);
        float dim = (fill + halo) * (1.0 - lit);
        gl_FragColor = vec4(uCore * lit + uCol.rgb * dim, lit + dim) * uCol.a;
    }
}
"""


def _rgb(c):
    return tuple(min(1.0, max(0.0, v / 255.0)) for v in c[:3])


class FxPass:
    """Made by GLFace on the first frame with items; draw() between its
    passes (blending premultiplied, the quad bound)."""
    MAX_TEX = 40                                     # images kept on the GPU
    UNIT = 4

    def __init__(self, face):
        GL = self.GL = face.GL
        self.face = face
        head = ("#version 120\n" if face.glsl == "120"
                else "#version 100\nprecision highp float;\n")
        from gl_face import _Prog
        self.p = _Prog(GL, face._program(head + _VERT, head + _FRAG))
        GL.glUseProgram(self.p.id)
        self.p.u("uRes", (face.w, face.h))
        self.p.unit("uTex", self.UNIT)          # (0–3: the face's layers, bound for its passes)
        self.pts = GL.glGetUniformLocation(self.p.id, "uPts")
        self.hb = GL.glGetUniformLocation(self.p.id, "uHB")
        self.hk = GL.glGetUniformLocation(self.p.id, "uHK")
        self.hands = {}                              # parts -> hand_uniforms
        self._parts = None                           # the hand whose arrays are set
        self.tex = OrderedDict()                     # key → (texture, w, h, res)
        self.mip = hasattr(GL, "glGenerateMipmap")
        self.made = 0                                # images made (the preview's numbers)
        print("[gl] effects pass ready", flush=True)

    def texture(self, key, make, res=2):
        key = (key, res)
        t = self.tex.get(key)
        if t is not None:
            self.tex.move_to_end(key)
            return t
        GL = self.GL
        import pygame
        img = make(res)
        w, h = img.get_size()
        if img.get_bitsize() != 32 or not img.get_flags() & pygame.SRCALPHA:
            img = img.convert_alpha()
        data = pygame.image.tobytes(img.premul_alpha(), "RGBA")
        tid = GL.glGenTextures(1)
        GL.glActiveTexture(GL.GL_TEXTURE0 + self.UNIT)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tid)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, data)
        mip = self.mip
        if mip:
            try:
                GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
            except Exception as e:                   # noqa: BLE001
                print(f"[gl] no mipmaps ({e!r})", flush=True)
                mip = self.mip = False
        for k, v in ((GL.GL_TEXTURE_MIN_FILTER,
                      GL.GL_LINEAR_MIPMAP_LINEAR if mip else GL.GL_LINEAR),
                     (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                     (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE),
                     (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, k, v)
        t = self.tex[key] = (tid, w, h, res)
        self.made += 1
        while len(self.tex) > self.MAX_TEX:
            _, old = self.tex.popitem(last=False)
            GL.glDeleteTextures([old[0]])
        return t

    def draw(self, items, tilt):
        GL, p = self.GL, self.p
        GL.glUseProgram(p.id)
        p.u("uTilt", tilt)
        self.face._bind_quad()
        GL.glActiveTexture(GL.GL_TEXTURE0 + self.UNIT)
        for it in items:
            kind = it[0]
            if kind == "sprite":
                _, key, make, x, y, angle, scale, alpha, flip, res = it
                if alpha <= 0.004:
                    continue
                tid, w, h, res = self.texture(key, make, res)
                GL.glBindTexture(GL.GL_TEXTURE_2D, tid)
                p.u("uKind", 0.0)
                p.u("uHalf", (w * scale[0] / res / 2, h * scale[1] / res / 2))
                p.u("uOff", (0.0, 0.0))
                p.u("uC", (x, y))
                p.u("uRot", math.radians(angle))
                p.u("uFlip", flip)
                p.u("uCol", (1.0, 1.0, 1.0, alpha))
            else:
                b = bounds(it)
                if b is None:
                    continue
                x0, y0, x1, y1 = b
                p.u("uRot", 0.0)
                p.u("uC", (0.0, 0.0))
                p.u("uOff", ((x0 + x1) / 2, (y0 + y1) / 2))
                p.u("uHalf", ((x1 - x0) / 2, (y1 - y0) / 2))
                if kind == "arcs":
                    _, x, y, side, radii, alphas, col, core = it
                    if max(alphas) <= 0.004:
                        continue
                    # (in its own frame: its centre of curvature at 0)
                    p.u("uC", (x, y))
                    p.u("uOff", ((x0 + x1) / 2 - x, (y0 + y1) / 2 - y))
                    p.u("uKind", 1.0)
                    p.u("uP", (side, 0.0, 0.0, 0.0))
                    p.u("uR", radii)
                    p.u("uA", alphas)
                    p.u("uCol", (*_rgb(col), 1.0))
                    p.u("uCore", _rgb(core))
                elif kind == "lines":
                    _, pts, w, col, alpha, core, core_w, pairs, glow = it
                    if alpha <= 0.004:
                        continue
                    p.u("uKind", 2.0)
                    flat = [v for xy in pts for v in xy]
                    GL.glUniform2fv(self.pts, len(pts), (ctypes.c_float * len(flat))(*flat))
                    p.u("uN", float(len(pts)))
                    p.u("uP", (1.0 if pairs else 0.0, w, core_w, glow))
                    p.u("uCol", (*_rgb(col), alpha))
                    p.u("uCore", _rgb(core))
                elif kind == "ring":
                    _, x, y, r, w, col, alpha, glow = it
                    if alpha <= 0.004:
                        continue
                    p.u("uC", (x, y))
                    p.u("uOff", (0.0, 0.0))
                    p.u("uHalf", ((x1 - x0) / 2, (y1 - y0) / 2))
                    p.u("uKind", 5.0)
                    p.u("uP", (r, w, glow, 0.0))
                    p.u("uCol", (*_rgb(col), alpha))
                elif kind == "hand":
                    _, parts, x, y, angle, cols, flip, alpha = it
                    if alpha <= 0.004:
                        continue
                    if parts != self._parts:
                        hu = self.hands.get(parts)
                        if hu is None:
                            hu = self.hands[parts] = hand_uniforms(parts)
                        hb, hk, n, ring = hu
                        GL.glUniform4fv(self.hb, n, (ctypes.c_float * len(hb))(*hb))
                        GL.glUniform4fv(self.hk, n, (ctypes.c_float * len(hk))(*hk))
                        p.u("uHN", float(n))
                        p.u("uHRing", ring)
                        self._parts = parts
                    p.u("uC", (x, y))
                    p.u("uOff", (0.0, 0.0))
                    p.u("uRot", math.radians(angle))
                    p.u("uFlip", flip)
                    p.u("uKind", 4.0)
                    top, bot, crease, glow = cols
                    p.u("uHTop", _rgb(top))
                    p.u("uHBot", _rgb(bot))
                    p.u("uHCrease", _rgb(crease))
                    p.u("uCol", (*_rgb(glow), alpha))
                elif kind == "glyph":
                    _, gid, x, y, size, col, core, angle, alpha, t, width = it
                    if alpha <= 0.004:
                        continue
                    r = (x1 - x0) / 2
                    p.u("uC", (x, y))
                    p.u("uOff", (0.0, 0.0))
                    p.u("uHalf", (r, r))
                    p.u("uRot", math.radians(angle))
                    p.u("uKind", 3.0)
                    p.u("uP", (float(gid), size, width, t))
                    p.u("uCol", (*_rgb(col), alpha))
                    p.u("uCore", _rgb(core))
                else:
                    continue
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glActiveTexture(GL.GL_TEXTURE0)
