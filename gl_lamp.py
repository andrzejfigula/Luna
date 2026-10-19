"""
gl_lamp.py — the ambient lamp's scenes (lamp_scenes.py → here), drawn by the
GPU instead of her face: jellyfish, aurora, clock ring, fireflies, lava lamp,
fireplace. One shader at half the screen's size into its own texture, then
stretched over the whole screen (opaque, dithered — dark gradients band
otherwise). Fireflies and jellyfish come placed (lamp_scenes' simulation),
each drawn in its own small box and added, like gl_vis's sparks.

Noise is one texture fetch (a random 256² texture, smoothstepped between
texels), not a hash per corner: the Pi 4's GPU has little ALU to spare.
"""

import ctypes
import random

_FRAG = """
uniform vec2  uRes;           // the screen (px)
uniform vec2  uFbo;           // what this is drawn into (px)
uniform vec4  uK;             // (scene 1..6, seconds, brightness 0..1, -)
uniform sampler2D uNoise;
uniform vec4  uBlob[8];       // lava: x, y, radius (P units), hue
uniform vec4  uBlobA[8];      // lava: cos, sin of the stretch axis, along, across
uniform float uDraw;          // 0 the background; 1 a firefly, 2 a jellyfish — in its box
uniform vec4  uItem, uItemK, uItemL, uItemM;
uniform vec4  uRope[6];       // a tentacle: 12 points (px), two to a vec4

float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return texture2D(uNoise, (i + f + 0.5) / 256.0).r;
}
float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 4; i++) {
        v += a * noise(p);
        p = mat2(1.6, 1.2, -1.2, 1.6) * p;
        a *= 0.5;
    }
    return v / 0.9375;
}
float sdSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-5), 0.0, 1.0);
    return length(pa - ba * h);
}

vec3 stars(vec2 P, float t, float dens) {
    vec2 g = P * 70.0;
    vec2 c = floor(g);
    float h = hash(c);
    if (h < dens) return vec3(0.0);
    vec2 o = vec2(hash(c + 7.1), hash(c + 3.3)) * 0.6 + 0.2;
    float d = length(g - c - o);
    float tw = 0.6 + 0.4 * sin(t * (0.5 + 1.5 * hash(c + 1.7)) + h * 50.0);
    return vec3(0.75, 0.82, 1.0) * 0.40 * tw * exp(-d * d * 14.0) * (h - dens) / (1.0 - dens);
}

// ── 1 jellyfish: the deep water behind them ─────────────────────────────
vec3 deepWater(vec2 P, float t) {
    vec3 col = vec3(0.000, 0.006, 0.020) * (0.25 + 0.75 * P.y * P.y);
    vec2 g = vec2(P.x * 16.0, P.y * 16.0 + t * 0.05);     // marine snow, sinking
    vec2 c = floor(g);
    float h = hash(c);
    if (h > 0.955) {
        vec2 o = vec2(0.5 + 0.3 * sin(t * 0.2 + h * 30.0), hash(c + 4.1));
        float d = length(g - c - o);
        col += vec3(0.30, 0.45, 0.70) * 0.07 * exp(-d * d * 120.0) * (h - 0.955) / 0.045;
    }
    return col;
}

// ── a jellyfish in its box ───────────────────────────────────────────────
// uItem: x, y (where the bell's rim is), size px, brightness
// uItemK: cos, sin of its tilt, the pulse's phase 0..1, lean of the tentacles
// uItemL: its own clock (s), hue 0..1, tentacle length (sizes), seed
// uItemM: its turn about its axis (rad), -, -, -
// (its tentacles: ropes, simulated in lamp_scenes.py, each drawn by rope())
float squeeze(float ph) {                  // the pulse: a quick squeeze, slow relaxing
    ph = fract(ph);
    return ph < 0.28 ? smoothstep(0.0, 0.28, ph) : 1.0 - smoothstep(0.28, 1.0, ph);
}
vec3 jelly(vec2 f) {
    float s = uItem.z;
    vec2 v = (f - uItem.xy) / s;
    v.y = -v.y;                                        // y up
    vec2 q = vec2(uItemK.x * v.x + uItemK.y * v.y, -uItemK.y * v.x + uItemK.x * v.y);
    float ph = uItemK.z, lean = uItemK.w;
    float T = uItemL.x, hue = uItemL.y, L = uItemL.z, seed = uItemL.w;
    float yaw = uItemM.x;
    // the squeeze runs from the top of the bell down to its rim
    float cTop = squeeze(ph), cRim = squeeze(ph - 0.07), cTail = squeeze(ph - 0.18);
    float flare = 0.07 * (1.0 - cRim) * smoothstep(0.5, 0.9, fract(ph - 0.07));
    float wTop = 0.92 - 0.20 * cTop, wRim = 1.0 - 0.30 * cRim + flare;
    float bh = 0.70 + 0.20 * cTop;
    float hy0 = clamp(q.y / bh, 0.0, 1.0);
    float bw = mix(wRim, wTop, smoothstep(0.0, 0.8, hy0));
    vec3 cT = mix(vec3(0.32, 0.30, 1.0), vec3(0.62, 0.32, 1.0), hue);
    vec3 cR = mix(vec3(0.22, 0.85, 1.0), vec3(0.38, 0.55, 1.0), hue);
    float xr = clamp(q.x / wRim, -1.0, 1.0);
    float under = (0.20 + 0.14 * cRim) * bh * (1.0 - xr * xr) - 0.05;   // the hollow, curling in
    vec3 col = vec3(0.0);
    float glowP = 0.85 + 0.35 * cTop;                              // it brightens as it squeezes
    if (q.y > under - 0.35 && abs(q.x) < wRim + 0.45) {
    float wob = 0.035 * (noise(vec2(atan(q.x, q.y) * 2.5 + seed * 9.0, T * 0.9)) - 0.5);
    float de = (length(vec2(q.x / bw, q.y / bh)) - 1.0) * min(bw, bh) + wob;
    float d = max(de, under - q.y);
    float inside = smoothstep(0.025, -0.025, d);
    float hy = clamp(q.y / bh, 0.0, 1.0);
    vec3 cb = mix(cR, cT, clamp(hy * 1.4, 0.0, 1.0));
    col = cb * (0.10 + 0.12 * hy) * inside;                        // translucent body
    col += cT * 0.16 * inside * exp(-dot(q - vec2(0.0, 0.45 * bh), q - vec2(0.0, 0.45 * bh)) * 5.0);
    col += cb * 0.50 * exp(-abs(de) * 20.0) * smoothstep(under - 0.03, under + 0.05, q.y);
    // light rippling down the bell
    col += cR * 0.07 * inside * smoothstep(0.6, 1.0, sin(hy * 11.0 - T * 2.6 + seed * 6.0));
    // meridians and four gonads, turning with it: seen through the glassy bell
    float u = clamp(q.x / max(bw, 0.05), -0.999, 0.999);
    float lon = asin(u);
    float front = sqrt(1.0 - u * u);
    float canal = pow(abs(cos((lon - yaw) * 4.0)), 18.0);
    col += cT * 0.11 * inside * canal * smoothstep(0.05, 0.45, q.y) * (0.5 + 0.5 * front);
    for (int i = 0; i < 4; i++) {
        float lg = yaw + 1.5708 * float(i) + 0.785;
        float gx = sin(lg) * 0.42 * bw, depth = 0.55 + 0.45 * cos(lg);
        vec2 gq = vec2((q.x - gx) / (0.55 + 0.45 * abs(cos(lg))), q.y - 0.30 * bh);
        col += mix(cT, vec3(0.85, 0.50, 1.0), 0.4) * 0.20 * depth * inside * exp(-dot(gq, gq) * 55.0);
    }
    float hem = exp(-abs(q.y - under) * 26.0) * smoothstep(wRim + 0.04, wRim - 0.12, abs(q.x));
    col += cR * 0.32 * hem * (0.7 + 0.3 * sin(lon * 9.0 - yaw * 9.0 + T * 2.0));
    col += cb * 0.12 * exp(-max(d, 0.0) * 9.0) * (1.0 - inside);   // its own faint light
    col *= glowP;
    }
    return col * uItem.w;
}

// ── a jellyfish's tentacle or oral arm: a chain of points in the water
// uItemK: width px, brightness, frilled (an arm) 0/1, seed; uItemL: colour, clock
vec3 rope(vec2 f) {
    float best = 1e6, bs = 0.0;
    vec2 prev = uRope[0].xy;
    for (int j = 0; j < 6; j++) {
        vec4 r = uRope[j];
        vec2 pa = f - prev, ba = r.xy - prev;
        float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-4), 0.0, 1.0);
        float d = length(pa - ba * h);
        if (d < best) { best = d; bs = (float(j) * 2.0 - 1.0 + h) / 11.0; }
        pa = f - r.xy; ba = r.zw - r.xy;
        h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-4), 0.0, 1.0);
        d = length(pa - ba * h);
        if (d < best) { best = d; bs = (float(j) * 2.0 + h) / 11.0; }
        prev = r.zw;
    }
    bs = clamp(bs, 0.0, 1.0);
    float w = uItemK.x * (1.0 - 0.55 * bs);
    float T = uItemL.w, seed = uItemK.w;
    float k;
    if (uItemK.z > 0.5) {                              // an oral arm: wide, frilled
        float frill = 0.55 + 0.45 * noise(vec2(bs * 14.0 - T * 1.2, seed * 10.0));
        k = smoothstep(w * 2.5, 0.0, best) * frill;
    } else {                                           // beads of light running down
        k = exp(-best / w) * (0.65 + 0.35 * smoothstep(0.6, 1.0, sin(bs * 9.0 - T * 2.4 + seed * 6.0)));
    }
    return uItemL.rgb * k * (1.0 - bs) * uItemK.y;
}

// ── 2 aurora ─────────────────────────────────────────────────────────────
vec3 aurora(vec2 P, float t) {
    vec3 col = mix(vec3(0.006, 0.012, 0.026), vec3(0.001, 0.003, 0.010), P.y);
    col += stars(P, t, 0.982);
    for (int k = 0; k < 3; k++) {
        float fk = float(k);
        float dir = k == 1 ? -1.0 : 1.0;
        float x = P.x * (0.75 + 0.2 * fk) + fk * 3.1;
        // folds sliding along: they bunch the rays up and spread them out
        float xf = x + 0.38 * (noise(vec2(x * 0.9 + t * 0.03 * dir, fk * 5.0)) - 0.5)
                 + 0.05 * sin(x * 5.0 + t * 0.45 * dir + fk);
        // the hem: big curves that keep changing, ripples running along it
        float rip = smoothstep(0.35, 0.75, noise(vec2(x * 0.8 - t * 0.05 * dir, fk * 3.0 + 20.0)));
        float edge = (k == 0 ? 0.30 : (k == 1 ? 0.24 : 0.42))
                   + 0.95 * (noise(vec2(xf * 0.75 + t * 0.012 * dir, t * 0.035 + fk * 9.0)) - 0.5)
                   + 0.030 * sin(xf * 8.0 - t * 0.9 * dir + fk * 2.0) * rip
                   + 0.012 * (noise(vec2(xf * 15.0 - t * 1.1 * dir, fk)) - 0.5);
        float d = P.y - edge;
        float lower = smoothstep(-0.03, 0.008, d);
        float top = 0.28 + 0.28 * noise(vec2(xf * 1.5 - t * 0.04 * dir, fk * 4.0 + t * 0.05));
        float up = exp(-max(d, 0.0) * (2.2 + 0.4 * fk)) * smoothstep(top + 0.15, top - 0.10, d);
        // rays drifting along and shimmering, light running up them
        float xr = xf * 22.0 + t * 0.6 * dir;
        float rays = 0.30 + 0.70 * noise(vec2(xr, P.y * 0.6 + fk));
        rays *= 0.65 + 0.35 * noise(vec2(xf * 55.0 - t * 0.9 * dir, t * 0.7));
        rays *= 0.70 + 0.30 * noise(vec2(xr * 0.7, P.y * 5.0 - t * 0.8));
        // bright patches travelling along the curtain; where it is at all
        float wave = 0.40 + 0.60 * smoothstep(0.25, 0.85, noise(vec2(xf * 1.3 - t * 0.10 * dir, fk * 7.0 + 3.0)));
        float m = smoothstep(0.24, 0.64, noise(vec2(x * 0.7 - t * 0.025 * dir, fk * 13.0 + 1.0)));
        float pulse = 0.75 + 0.25 * noise(vec2(t * 0.15, fk * 5.0 + 40.0));
        vec3 lo = k == 0 ? vec3(0.10, 1.00, 0.60) : (k == 1 ? vec3(0.05, 0.85, 0.85)
                                                            : vec3(0.20, 0.55, 1.00));
        vec3 hi = k == 2 ? vec3(0.55, 0.22, 1.00) : (k == 1 ? vec3(0.32, 0.25, 1.00)
                                                            : vec3(0.10, 0.45, 1.00));
        vec3 c = mix(lo, hi, smoothstep(0.02, 0.35, d));
        float g = (k == 0 ? 0.85 : (k == 1 ? 0.70 : 0.50)) * m * wave * pulse;
        col += c * lower * up * rays * g;
        col += lo * 0.14 * exp(-abs(d) * 30.0) * g;                       // the bright hem
        col += lo * 0.10 * exp(min(d, 0.0) * 7.0) * (1.0 - lower) * g;    // its glow below
        col += vec3(0.65, 0.18, 0.55) * 0.07 * exp(-abs(d + 0.012) * 70.0) * g * wave;  // pink fringe
    }
    return col;
}

// ── 3 the clock's ring (the time itself: pygame, over it) ───────────────
vec3 clockRing(vec2 P, float t) {
    vec2 v = P - vec2(0.0, 0.5);
    float r = length(v);
    vec2 dv = v / max(r, 1e-4);
    vec3 col = vec3(0.003, 0.005, 0.012) + stars(P, t, 0.993) * 0.5;
    for (int k = 0; k < 4; k++) {
        float fk = float(k);
        float sp = (k == 1 || k == 3) ? -1.0 : 1.0;
        float a = t * 0.035 * sp * (1.0 + 0.3 * fk);
        vec2 rd = vec2(dv.x * cos(a) - dv.y * sin(a), dv.x * sin(a) + dv.y * cos(a));
        float rk = 0.405 + 0.012 * fk - 0.018
                 + 0.045 * (noise(rd * 1.3 + vec2(fk * 5.3, t * 0.025)) - 0.5);
        float b = -a * 1.7 + 0.6 * fk;
        vec2 rb = vec2(dv.x * cos(b) - dv.y * sin(b), dv.x * sin(b) + dv.y * cos(b));
        float along = smoothstep(0.30, 0.85, noise(rb * 1.1 + vec2(fk * 2.7, 4.0 + t * 0.015)));
        float dist = abs(r - rk);
        float line = exp(-dist * 300.0) * 0.75 + exp(-dist * 55.0) * 0.10;
        vec3 rc = k == 0 ? vec3(0.20, 0.85, 1.00) : (k == 1 ? vec3(0.20, 0.35, 1.00)
                  : (k == 2 ? vec3(0.55, 0.30, 1.00) : vec3(0.25, 0.60, 1.00)));
        col += rc * line * (0.12 + 0.88 * along) * 0.50;
    }
    return col;
}

// ── 4 fireflies: the dark meadow; each fly in its box ───────────────────
vec3 meadow(vec2 P) {
    return vec3(0.000, 0.005, 0.016) * (0.3 + 0.7 * P.y) + vec3(0.003, 0.006, 0.008) * exp(-P.y * 7.0);
}
// uItem: head x, y, tail x, y (px); uItemK: radius px, brightness; uItemL: colour
vec3 firefly(vec2 f) {
    vec2 a = uItem.xy, b = uItem.zw;
    vec2 pa = f - a, ba = b - a;
    float L2 = dot(ba, ba);
    float h = L2 > 0.01 ? clamp(dot(pa, ba) / L2, 0.0, 1.0) : 0.0;
    float d = length(pa - ba * h);
    float r = uItemK.x;
    float k = 1.3 * exp(-d * d / (r * r)) + 0.30 * exp(-d * d / (r * r * 7.0))
            + 0.10 * exp(-d * d / (r * r * 30.0));
    vec3 c = uItemL.rgb * k * (1.0 - 0.85 * h);
    c += vec3(1.0, 0.95, 0.80) * 0.35 * exp(-d * d / (r * r * 0.2)) * (1.0 - h);
    return c * uItemK.y;
}

// ── 5 lava lamp: one field of all the wax, not separate balls ───────────
vec3 lava(vec2 P, float t) {
    vec2 w = vec2(noise(P * 2.3 + vec2(t * 0.021, 3.7)), noise(P * 2.3 + vec2(7.1, -t * 0.018)));
    vec2 p = P + (w - 0.5) * 0.08;                     // warped: no perfect circles
    float F = 0.0, hue = 0.0;
    vec2 g = vec2(0.0);
    for (int i = 0; i < 8; i++) {
        vec4 bl = uBlob[i];
        vec4 ax = uBlobA[i];
        vec2 v = p - bl.xy;
        float ux = (v.x * ax.x + v.y * ax.y) / ax.z;
        float uy = (-v.x * ax.y + v.y * ax.x) / ax.w;
        float R2 = bl.z * bl.z;
        float q = (ux * ux + uy * uy) / R2;
        if (q < 1.0) {
            float m = 1.0 - q;
            float k = m * m * m;
            F += k;
            hue += k * bl.w;
            g += -6.0 * m * m / R2 * (ux / ax.z * ax.xy + uy / ax.w * vec2(-ax.y, ax.x));
        }
    }
    const float T = 0.30;
    vec3 bg = vec3(0.020, 0.007, 0.036)
            * clamp(1.0 - length((P - vec2(0.0, 0.45)) * vec2(0.8, 1.0)) * 1.15, 0.0, 1.0);
    float gn = length(g) + 1e-4;
    float s = (F - T) / gn;                            // ~ how far inside the edge
    float aa = 1.5 / uFbo.y;
    float inside = smoothstep(-aa, aa, s);
    hue /= max(F, 1e-4);
    vec3 col = bg + vec3(0.16, 0.05, 0.32) * 0.20 * pow(clamp(F / T, 0.0, 1.0), 3.0) * (1.0 - inside);
    if (s > -aa) {
        float kz = clamp(s / 0.09, 0.0, 1.0);
        float z = sqrt(kz * (2.0 - kz));               // a dome: 0 at the edge, 1 deep in
        vec2 o = -g / gn;
        vec3 n = vec3(o * sqrt(1.0 - z * z), z);
        vec3 deep = mix(vec3(0.10, 0.035, 0.32), vec3(0.30, 0.055, 0.48), hue);
        float swirl = noise(p * 5.0 + vec2(t * 0.03, -t * 0.02));
        vec3 c = deep * (0.50 + 0.35 * z) * (0.85 + 0.30 * swirl);
        float below = max(dot(n, vec3(0.15, -0.84, 0.52)), 0.0);   // the lamp under it
        float above = max(dot(n, vec3(-0.36, 0.78, 0.51)), 0.0);   // cool light from above
        c += vec3(0.75, 0.10, 0.55) * 0.34 * pow(below, 3.0);
        c += vec3(0.15, 0.40, 1.00) * 0.28 * pow(above, 4.0);
        c += vec3(0.30, 0.12, 0.60) * 0.22 * pow(1.0 - z, 3.0);
        c += vec3(0.75, 0.80, 1.00) * 0.08 * pow(max(dot(n, vec3(-0.30, 0.45, 0.84)), 0.0), 24.0);
        c *= 0.85 + 0.30 * smoothstep(0.75, 0.0, P.y);
        col = mix(col, c, inside);
    }
    return col;
}

// ── 6 fireplace ──────────────────────────────────────────────────────────
vec3 embers(vec2 P, float t) {
    vec3 c = vec3(0.0);
    for (int k = 0; k < 2; k++) {
        float fk = float(k);
        vec2 g = vec2(P.x * 14.0 + fk * 7.3, (P.y - t * (0.09 + 0.05 * fk)) * 9.0);
        vec2 cell = floor(g);
        float h = hash(cell + fk * 17.0);
        if (h > 0.88) {
            vec2 o = vec2(0.5 + 0.30 * sin(t * 1.3 + h * 40.0), hash(cell + 2.3));
            vec2 e = (g - cell - o) * vec2(1.0, 1.5);
            float life = smoothstep(0.80, 0.25, P.y) * smoothstep(0.18, 0.30, P.y)
                       * smoothstep(0.30, 0.08, abs(P.x));
            float fl = 0.5 + 0.5 * sin(t * (5.0 + 4.0 * h) + h * 20.0);
            c += vec3(1.0, 0.42, 0.08) * exp(-dot(e, e) * 50.0) * life * (0.35 + 0.65 * fl) * 0.9;
        }
    }
    return c;
}
vec3 fireplace(vec2 P, float t) {
    float flick = 0.85 + 0.15 * noise(vec2(t * 2.2, 1.0));
    vec3 col = vec3(0.005, 0.003, 0.002);
    vec2 gq = (P - vec2(0.0, 0.08)) * vec2(1.0, 1.7);
    col += vec3(0.40, 0.10, 0.02) * 0.22 * exp(-dot(gq, gq) * 6.0) * flick;
    // flames: rising noise stretched upright makes the tongues; the higher,
    // the more of it is needed to burn, so they taper, split and come loose
    for (int k = 0; k < 2; k++) {
        float fk = float(k);
        float Y = P.y - 0.095;
        float X = P.x + 0.05 * (noise(vec2(Y * 4.0 - t * 0.9, 3.0 + fk * 5.0)) - 0.5) * max(Y, 0.0) * 5.0;
        float E = exp(-(X / (0.22 - 0.04 * fk)) * (X / (0.22 - 0.04 * fk)));
        float n = fbm(vec2(X * (7.0 + 2.0 * fk), Y * 2.0 - t * (1.3 + 0.4 * fk)) + fk * 9.0);
        float n2 = noise(vec2(X * 16.0, Y * 5.0 - t * 2.6) + fk * 3.0);
        float heat = n * 0.9 + n2 * 0.25 + E * 0.95 - (0.80 + 1.7 * max(Y, 0.0));
        heat *= smoothstep(-0.05, 0.02, Y);
        float a = smoothstep(0.0, 0.22, heat);
        vec3 c = mix(vec3(0.42, 0.05, 0.01), vec3(0.95, 0.32, 0.04), smoothstep(0.02, 0.25, heat));
        c = mix(c, vec3(1.0, 0.60, 0.20), smoothstep(0.25, 0.50, heat));
        c = mix(c, vec3(1.0, 0.80, 0.48), smoothstep(0.50, 0.75, heat) * 0.5);
        col += c * a * (k == 0 ? 0.75 : 0.45) * flick;
    }
    // the bed of coals: a low glow, breathing
    float bed = smoothstep(0.08, 0.035, P.y) * smoothstep(0.40, 0.22, abs(P.x));
    float glowc = 0.45 + 0.55 * noise(vec2(P.x * 9.0, t * 0.35)) * noise(vec2(P.x * 23.0 + 5.0, t * 0.6));
    col = mix(col, vec3(0.03, 0.012, 0.006) + vec3(0.85, 0.22, 0.03) * 0.45 * glowc * flick, bed);
    // two logs over the coals, their tops lit by the fire, a few glowing cracks
    for (int k = 0; k < 2; k++) {
        vec2 a = k == 0 ? vec2(-0.30, 0.058) : vec2(0.30, 0.052);
        vec2 b = k == 0 ? vec2(0.22, 0.092) : vec2(-0.18, 0.088);
        float d = sdSeg(P, a, b) - 0.030;
        float inl = smoothstep(0.004, -0.004, d);
        vec2 ab = normalize(b - a);
        float side = dot(P - a, vec2(-ab.y, ab.x));     // > 0: the top of the log
        float rim = exp(d * 70.0) * smoothstep(-0.005, 0.03, side);
        float crack = smoothstep(0.70, 0.88, noise(vec2(dot(P - a, ab) * 9.0 + float(k) * 5.0, side * 40.0)));
        vec3 wood = vec3(0.030, 0.014, 0.007) + vec3(0.95, 0.38, 0.06) * 0.28 * rim * flick
                  + vec3(1.0, 0.35, 0.05) * 0.30 * crack * (0.6 + 0.4 * sin(t * 1.3 + float(k) * 2.0));
        col = mix(col, wood, inl);
    }
    col += embers(P, t);
    return col;
}

void main() {
    vec2 f = vec2(gl_FragCoord.x, uFbo.y - gl_FragCoord.y) * (uRes / uFbo);
    vec3 c;
    if (uDraw > 2.5) {
        c = rope(f);
    } else if (uDraw > 1.5) {
        c = jelly(f);
    } else if (uDraw > 0.5) {
        c = firefly(f);
    } else {
        vec2 P = vec2((gl_FragCoord.x / uFbo.x - 0.5) * uRes.x / uRes.y, gl_FragCoord.y / uFbo.y);
        float m = uK.x, t = uK.y;
        if (m < 1.5)      c = deepWater(P, t);
        else if (m < 2.5) c = aurora(P, t);
        else if (m < 3.5) c = clockRing(P, t);
        else if (m < 4.5) c = meadow(P);
        else if (m < 5.5) c = lava(P, t);
        else              c = fireplace(P, t);
    }
    gl_FragColor = vec4(c * uK.z, 1.0);
}
"""

# the picture stretched over the screen, opaque, dithered
_COMPOSE = """
uniform sampler2D uTex;
uniform vec2 uRes;
float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
void main() {
    vec3 c = texture2D(uTex, gl_FragCoord.xy / uRes).rgb;
    c += (hash(gl_FragCoord.xy) - 0.5) / 255.0;
    gl_FragColor = vec4(c, 1.0);
}
"""

NOISE = 256


class LampPass:
    """Made by gl_face.GLFace on the first lamp-scene frame; draw() each frame
    (it alone covers the screen: no face under it)."""

    def __init__(self, face, scale=0.5):
        GL = self.GL = face.GL
        self.face = face
        head = "#version 120\n" if face.glsl == "120" else "#version 100\nprecision mediump float;\n"
        from gl_face import _VERT
        self.prog = face._program(head + _VERT, head + _FRAG)
        self.comp = face._program(head + _VERT, head + _COMPOSE)
        self._loc = {}
        self.fw, self.fh = max(1, int(face.w * scale)), max(1, int(face.h * scale))
        self.tex = face._texture(self.fw, self.fh, GL.GL_LINEAR)
        self.fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_2D, self.tex, 0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, face.target_fbo)
        rng = random.Random(7)                       # the same noise every time
        self.noise = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.noise)
        for k, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR),
                     (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                     (GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT),
                     (GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, k, v)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, NOISE, NOISE, 0, GL.GL_RGBA,
                        GL.GL_UNSIGNED_BYTE, rng.randbytes(NOISE * NOISE * 4))
        print("[gl] lamp scenes shader ready", flush=True)

    def _loc_of(self, prog, name):
        loc = self._loc.get((prog, name))
        if loc is None:
            loc = self._loc[(prog, name)] = self.GL.glGetUniformLocation(prog, name)
        return loc

    def _set(self, prog, name, value):
        GL = self.GL
        loc = self._loc_of(prog, name)
        if loc < 0:
            return
        if isinstance(value, (int, float)):
            GL.glUniform1f(loc, float(value))
        else:
            {2: GL.glUniform2f, 3: GL.glUniform3f, 4: GL.glUniform4f}[len(value)](
                loc, *map(float, value))

    def _set_array(self, prog, name, rows):
        loc = self._loc_of(prog, name + "[0]")
        if loc < 0 or not rows:
            return
        flat = (ctypes.c_float * (4 * len(rows)))(*[float(x) for r in rows for x in r])
        self.GL.glUniform4fv(loc, len(rows), flat)

    def draw(self, lamp):
        """lamp: lamp_scenes.uniforms()'s dict. Draws the whole screen into
        the face's target framebuffer; leaves blending off."""
        GL, face = self.GL, self.face
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glViewport(0, 0, self.fw, self.fh)
        GL.glDisable(GL.GL_BLEND)
        GL.glUseProgram(self.prog)
        full = (0.0, 0.0, float(face.w), float(face.h))
        self._set(self.prog, "uRes", (face.w, face.h))
        self._set(self.prog, "uFbo", (self.fw, self.fh))
        self._set(self.prog, "uRect", full)
        self._set(self.prog, "uK", lamp["uK"])
        GL.glActiveTexture(GL.GL_TEXTURE0 + 5)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.noise)
        GL.glUniform1i(self._loc_of(self.prog, "uNoise"), 5)
        if lamp.get("uBlob"):
            self._set_array(self.prog, "uBlob", lamp["uBlob"])
            self._set_array(self.prog, "uBlobA", lamp["uBlobA"])
        self._set(self.prog, "uDraw", 0.0)
        face._quad()
        items = lamp.get("items") or ()
        if items:                            # fireflies, jellyfish: each in its own box
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE)
            for it in items:
                kind, box, item, itemk, iteml = it[:5]
                self._set(self.prog, "uDraw", kind)
                self._set(self.prog, "uRect", box)
                if item is not None:
                    self._set(self.prog, "uItem", item)
                self._set(self.prog, "uItemK", itemk)
                self._set(self.prog, "uItemL", iteml)
                if len(it) > 5 and it[5] is not None:
                    self._set(self.prog, "uItemM", it[5])
                if len(it) > 6:                      # a rope's points
                    self._set_array(self.prog, "uRope", it[6])
                face._quad()
            GL.glDisable(GL.GL_BLEND)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, face.target_fbo)
        GL.glViewport(0, 0, face.w, face.h)
        GL.glUseProgram(self.comp)
        self._set(self.comp, "uRes", (face.w, face.h))
        self._set(self.comp, "uRect", full)
        GL.glActiveTexture(GL.GL_TEXTURE0 + 4)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glUniform1i(self._loc_of(self.comp, "uTex"), 4)
        face._quad()
        GL.glActiveTexture(GL.GL_TEXTURE0)
