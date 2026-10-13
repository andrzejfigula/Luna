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

uniform vec4  uEye0;          // cx, cy, w, h (px, top-left origin)
uniform vec4  uEye1;
uniform vec4  uShape0;        // happy, sad, angry, lid (0..1 of the height)
uniform vec4  uShape1;
uniform vec4  uPupil0;        // dx, dy (from the eye centre), radius, shown
uniform vec4  uPupil1;
uniform float uRadius;
uniform vec3  uTop;
uniform vec3  uBottom;
uniform vec3  uGlow;
uniform vec3  uTint;
uniform float uTintAmt;
uniform vec3  uShine;
uniform vec3  uPupilCol;

uniform vec4  uBrow0;         // x0, y0, x1, y1
uniform vec4  uBrow1;
uniform vec4  uBrowK;         // bend0, bend1, thickness, alpha

uniform vec4  uMouth;         // cx, cy, w, h
uniform vec4  uMouthK;        // bend (+ = smile), open 0..1, alpha, kind (0 line, 1 open, 2 O)
uniform float uMouthSlant;    // px the right end is higher (angry)

uniform vec4  uBlush;         // fcx, fcy, alpha 0..1, spread
uniform vec3  uBlushCol;

uniform sampler2D uLayer;       // what stays put on the screen (status bar, captions…)
uniform float uHasLayer;
uniform sampler2D uFaceLayer;   // what moves with the face (particles, hands, scenes)
uniform float uHasFaceLayer;
uniform float uPass;          // 0: the soft part (glow, blush, screen), small
uniform sampler2D uSoft;      // 1: that, stretched over the screen (+ dither)
uniform vec2  uSoftRes;       // 2: one sharp shape (uShape) in its own box, blended
uniform float uShape;         // 3: a pygame layer (uLayerSel) over its rows, blended
uniform float uLayerSel;      //    0 the screen's, 1 the one turning with the face

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

// > 0 on the corner C's side of the line A-B
float corner(vec2 q, vec2 A, vec2 B, vec2 C) {
    vec2 t = normalize(B - A);
    vec2 n = vec2(-t.y, t.x);
    return dot(q - A, n) * sign(dot(C - A, n));
}

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

// the "glitch" scene: a few bands of rows slide sideways (reply_scenes.Glitch
// does it to the pygame picture; the face is the GPU's now)
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

// the eye's shape: a rounded block, cut into a smile arc / worried or cross
// corners / a lowered lid
float eyeSDF(vec2 q, vec4 e, vec4 sh, float side) {
    vec2 b = e.zw * 0.5;
    float r = min(uRadius, min(b.x, b.y));
    float d = sdRoundBox(q, b, r);
    // happy "^": an ellipse taken out of the bottom
    vec2 R = vec2(1.4 * b.x, 1.3 * b.y);
    float cut = (length((q - vec2(0.0, 1.14 * b.y)) / R) - 1.0) * R.y;
    d = mix(d, max(d, -cut), sh.x);
    // sad: the outer top corner slopes down
    float sad = corner(q, vec2(side * b.x, -0.1 * b.y), vec2(-0.4 * side * b.x, -b.y),
                       vec2(side * b.x, -b.y));
    d = mix(d, max(d, sad), sh.y);
    // angry: the inner top corner slopes down
    float ang = corner(q, vec2(-side * b.x, 0.0), vec2(0.5 * side * b.x, -b.y),
                       vec2(-side * b.x, -b.y));
    d = mix(d, max(d, ang), sh.z);
    // lid: the top edge comes down, a little rounder in the middle
    float lidY = -b.y + 2.0 * b.y * sh.w - (1.0 - (q.x * q.x) / (b.x * b.x)) * b.y * 0.12 * sh.w;
    d = max(d, lidY - q.y);
    return d;
}

vec3 eyeColour(vec2 q, vec2 b, float d) {
    vec3 top = mix(uTop, uTint, uTintAmt);
    vec3 bot = mix(uBottom, uTint, uTintAmt * 0.85);
    float v = clamp((q.y + b.y) / (2.0 * b.y), 0.0, 1.0);
    vec3 col = mix(top, bot, smoothstep(0.0, 1.0, v));
    float rx = q.x / b.x;
    col *= 1.0 - 0.20 * rx * rx;                         // a dome: darker sides
    col += top * 0.22 * exp(d / 4.0);                    // lit rim along the edge
    vec2 hp = (q - vec2(-0.36 * b.x, -0.56 * b.y)) / vec2(0.30 * b.x, 0.15 * b.y);
    col = mix(col, uShine, 0.60 * exp(-dot(hp, hp) * 1.4));   // specular
    vec2 hp2 = (q - vec2(0.42 * b.x, -0.50 * b.y)) / vec2(0.07 * b.x, 0.07 * b.y);
    col = mix(col, uShine, 0.45 * exp(-dot(hp2, hp2) * 1.8)); // a small glint
    float band = exp(-pow((q.y - 0.66 * b.y) / (0.10 * b.y), 2.0)) * (1.0 - rx * rx);
    col += uShine * band * 0.10;                         // light from below
    return col;
}

// one eye over `col`; its glow is added to `glow`
vec3 drawEye(vec2 p, vec3 col, inout vec3 glow, vec4 e, vec4 sh, vec4 pu, float side) {
    vec2 q = p - e.xy;
    vec2 b = e.zw * 0.5;
    if (uPass > 0.5 && (abs(q.x) > b.x + 2.0 || abs(q.y) > b.y + 2.0)) return col;
    float d = eyeSDF(q, e, sh, side);
    float dd = max(d, 0.0);
    if (uPass < 0.5) {
        // under a smiling "^" the glow fades by height, not around the cut-out
        // (it lit a dark hole the shape of the cut)
        float top = max(sdRoundBox(q - vec2(0.0, -0.45 * b.y), vec2(b.x, 0.55 * b.y),
                                   min(uRadius, 0.55 * b.y)), 0.0);
        float dg = mix(dd, top, sh.x);
        vec3 gc = mix(uGlow, uTint, uTintAmt);
        glow += gc * (0.50 * exp(-dg / 13.0) + 0.22 * exp(-dg / 45.0)) * smoothstep(0.0, 8.0, e.w);
        return col;
    }
    float a = clamp(0.5 - d, 0.0, 1.0);
    if (a <= 0.0) return col;
    gA = a;
    vec3 c = eyeColour(q, b, d);
    // pupil: a soft dark rounded square with two catch-lights
    if (pu.w > 0.01) {
        vec2 pq = q - pu.xy;
        float pr = pu.z;
        float dp = sdRoundBox(pq, vec2(pr), pr * 0.48);
        float pa = smoothstep(1.5, -1.5, dp) * pu.w;
        float ring = exp(-abs(dp + 2.0) / 3.0) * 0.25 * pu.w;
        c = mix(c, c * 0.55, ring);
        c = mix(c, uPupilCol, pa);
        vec2 s1 = (pq - vec2(-0.36 * pr, -0.36 * pr)) / (0.30 * pr);
        vec2 s2 = (pq - vec2(0.34 * pr, 0.30 * pr)) / (0.13 * pr);
        float sh1 = smoothstep(1.0, 0.75, length(s1)) * pa;
        float sh2 = smoothstep(1.0, 0.70, length(s2)) * pa * 0.8;
        c = mix(c, uShine, max(sh1, sh2));
    }
    return mix(col, c, a);
}

vec3 drawBrow(vec2 p, vec3 col, inout vec3 glow, vec4 s, float bend) {
    if (uBrowK.w <= 0.01) return col;
    vec2 m = (s.xy + s.zw) * 0.5;
    float hl = max(1.0, length(s.zw - s.xy) * 0.5);
    if (uPass > 0.5 && (abs(p.x - m.x) > hl + uBrowK.z
                        || abs(p.y - m.y) > abs(s.w - s.y) * 0.5 + uBrowK.z + abs(bend))) return col;
    float x = clamp((p.x - m.x) / hl, -1.0, 1.0);
    vec2 pp = vec2(p.x, p.y + bend * (1.0 - x * x));
    float d = sdSeg(pp, s.xy, s.zw) - uBrowK.z * 0.5;
    if (uPass < 0.5) {
        glow += uGlow * 0.45 * exp(-max(d, 0.0) / 10.0) * uBrowK.w;
        return col;
    }
    float a = clamp(0.5 - d, 0.0, 1.0) * uBrowK.w;
    gA = a;
    float v = clamp((pp.y - m.y) / uBrowK.z + 0.5, 0.0, 1.0);
    vec3 c = mix(uTop, uBottom, v * 0.8);
    c = mix(c, uShine, 0.35 * exp(-pow((v - 0.25) / 0.18, 2.0)));
    return mix(col, c, a);
}

vec3 drawMouth(vec2 p, vec3 col, inout vec3 glow) {
    float alpha = uMouthK.z;
    if (alpha <= 0.01) return col;
    vec2 q = p - uMouth.xy;
    float hw = uMouth.z * 0.5;
    float kind = uMouthK.w;
    if (uPass > 0.5 && (abs(q.x) > hw + uMouth.w * 0.5 + 4.0
                        || abs(q.y) > max(uMouth.w, uMouth.z * step(1.5, kind)) * 0.5
                                      + abs(uMouthK.x) + abs(uMouthSlant) + 4.0)) return col;
    float d;
    float inner = 1e5;
    if (kind < 0.5) {                         // a line: smile / frown / slant
        float x = clamp(q.x / hw, -1.0, 1.0);
        vec2 pq = vec2(q.x, q.y - uMouthK.x * (1.0 - x * x));
        d = sdSeg(pq, vec2(-hw, uMouthSlant), vec2(hw, -uMouthSlant)) - uMouth.w * 0.5;
    } else if (kind < 1.5) {                  // open, talking
        vec2 b = vec2(hw, uMouth.w * 0.5);
        d = sdRoundBox(q, b, min(b.y, 24.0));
        inner = d + 7.0;
    } else {                                  // "O"
        float r = uMouth.z * 0.5;
        d = length(q) - r;
        inner = d + r * 0.38;
    }
    if (uPass < 0.5) {
        glow += uGlow * 0.40 * exp(-max(d, 0.0) / 12.0) * alpha;
        return col;
    }
    float a = clamp(0.5 - d, 0.0, 1.0) * alpha;
    gA = a;
    float v = clamp(q.y / max(uMouth.w, 10.0) + 0.5, 0.0, 1.0);
    vec3 c = mix(uTop, uBottom, 0.35 + 0.55 * v);
    if (inner < 1e4) {                        // the dark inside: teeth, a tongue
        float ia = clamp(0.5 - inner, 0.0, 1.0);
        float h = uMouth.w;
        vec3 inside = vec3(0.06, 0.02, 0.01) + vec3(0.10, 0.03, 0.02) * (1.0 - v);
        float teeth = (kind < 1.5) ? smoothstep(0.5, -0.5, q.y + h * 0.5 - 7.0 - h * 0.22)
                                     * smoothstep(0.3, 0.6, uMouthK.y) : 0.0;
        inside = mix(inside, vec3(1.0, 0.96, 0.88), teeth * 0.9);
        vec2 tq = (q - vec2(0.0, h * 0.42)) / vec2(hw * 0.55, h * 0.32);
        float tongue = smoothstep(1.0, 0.8, length(tq)) * step(0.5, kind) * step(kind, 1.5);
        inside = mix(inside, vec3(0.85, 0.30, 0.28), tongue * 0.85);
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
        float sheen = exp(-pow((uv.x + uv.y * 0.6 - 0.35) / 0.10, 2.0));
        col += vec3(0.010, 0.009, 0.012) * sheen;
        if (uFace > 0.5) {
            if (uBlush.z > 0.01) {                       // blush under the eyes
                vec2 bq = (p - uBlush.xy - vec2(-240.0, 80.0)) / vec2(uBlush.w * 1.3, uBlush.w);
                col += uBlushCol * 0.55 * uBlush.z * exp(-dot(bq, bq) * 2.2);
                bq = (p - uBlush.xy - vec2(240.0, 80.0)) / vec2(uBlush.w * 1.3, uBlush.w);
                col += uBlushCol * 0.55 * uBlush.z * exp(-dot(bq, bq) * 2.2);
            }
            col = drawEye(p, col, glow, uEye0, uShape0, uPupil0, -1.0);
            col = drawEye(p, col, glow, uEye1, uShape1, uPupil1, 1.0);
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
        if (uShape < 0.5)      c = drawEye(p, c, glow, uEye0, uShape0, uPupil0, -1.0);
        else if (uShape < 1.5) c = drawEye(p, c, glow, uEye1, uShape1, uPupil1, 1.0);
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
                l = texture2D(uFaceLayer, lu);
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
        self.k = {"happy": 0.0, "sad": 0.0, "angry": 0.0}   # eased shape weights
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

    def render(self, uniforms, has_layer=False, face_layer=None, screen_layer=None):
        """face_layer / screen_layer: pygame surfaces to upload first (or
        has_layer: the screen layer was uploaded already). The stages: the
        soft part small, stretched over the screen, each shape in its own
        box, the layers over their rows — every pixel is worked on only where
        something is (one full-screen shader for all of it: 16 ms a frame)."""
        GL = self.GL
        has_face = face_layer is not None and self.upload(self.face_l, face_layer)
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
            boxes.append(self._box(ex, ey, w / 2 + 3, h / 2 + 3, tilt))
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
            hx = w / 2 + h / 2 + 4
            hy = max(h, w if kind > 1.5 else 0.0) / 2 + abs(bend) + abs(u["uMouthSlant"]) + 4
            boxes.append(self._box(mx, my, hx, hy, tilt))
        return boxes

    # ── Luna's animation state → the shader's inputs ──────────────────────
    def face_uniforms(self, face, rf, fcx, fcy):
        """face: the RobotFace; rf: the robot_face module (its live style
        globals). Mirrors Eye._draw_block / Eye._draw_brow / Mouth.draw, with
        the shape changes eased instead of switched."""
        k = self.k
        for name, on in (("happy", face._happy), ("sad", face._sad), ("angry", face._angry)):
            k[name] = _lerp(k[name], 1.0 if on else 0.0, 0.18)
        u = {"uTime": (face.breath_phase if hasattr(face, "breath_phase") else 0.0),
             "uTilt": math.radians(face.head_angle),
             "uFace": 1.0 if rf.EYE_MODE == "block" else 0.0,
             "uRadius": float(rf.EYE_RADIUS) * 1.15,
             "uTop": _rgb(rf.EYE_GRAD_TOP), "uBottom": _rgb(rf.EYE_GRAD_BOTTOM),
             "uGlow": _rgb(rf.GLOW_COL), "uShine": _rgb(rf.IRIS_SHINE),
             "uPupilCol": _rgb(rf.PUPIL_DARK), "uBlushCol": _rgb(rf.BLUSH_COL)}
        tint = face._eye_color
        amt = 0.45 if tint else 0.0
        if face.angry_pulse > 0.01:
            tint = rf.ANGRY_COL if not tint else tint
            amt = max(amt, 0.6 * face.angry_pulse)
        u["uTint"] = _rgb(tint or rf.EYE_GRAD_TOP)
        u["uTintAmt"] = amt
        brows, bend = [], []
        for i, (eye, side) in enumerate(((face.left_eye, -1), (face.right_eye, 1))):
            cx, cy = fcx + eye.rel_x, fcy + eye.rel_y
            w = float(eye.w)
            h_mod = eye.h * (1.0 - eye.squint * 0.4) * (1.0 + eye.widen * 0.2)
            vis_h = max(4.0, h_mod * eye.blink_t)
            ex, ey = cx + eye.pupil_ox * 0.55, cy + eye.pupil_oy * 0.55
            w = min(w, rf.EYE_SPREAD * 2 - 44)
            u[f"uEye{i}"] = (ex, ey, w, vis_h)
            lid = eye.squint * 0.5 if eye.squint > 0.02 else 0.0
            u[f"uShape{i}"] = (k["happy"] * (eye.blink_t > 0.4), k["sad"], k["angry"], lid)
            pr = min(w, vis_h) * 0.20 * eye.pupil_scale
            shown = max(0.0, min(1.0, (eye.blink_t - 0.25) / 0.2)) if vis_h > 30 else 0.0
            if not rf.BLOCK_PUPIL:
                shown = 0.0
            u[f"uPupil{i}"] = (eye.pupil_ox * 0.45,
                               eye.pupil_oy * 0.45 - vis_h * 0.16 * k["happy"], pr, shown)
            # brows: 30 px above the eye's top, 70 % of its width
            bw = w * 0.70
            by = ey - vis_h / 2 - 30
            x0, x1 = ex - bw / 2, ex + bw / 2
            y0 = y1 = by
            if face._angry:
                y0, y1 = (by + 10, by - 10) if side < 0 else (by - 10, by + 10)
            elif face._sad:
                drop = eye.droop * 14
                y0, y1 = (by, by - drop) if side < 0 else (by - drop, by)
            elif face._listen:
                y0 = y1 = by - 10 * eye.widen
            brows.append((x0, y0, x1, y1))
            bend.append(12.0 * k["happy"])
        u["uBrow0"], u["uBrow1"] = brows
        blink = min(face.left_eye.blink_t, face.right_eye.blink_t)
        u["uBrowK"] = (bend[0], bend[1], 15.0, max(0.0, min(1.0, (blink - 0.4) / 0.15)))
        u.update(self._mouth(face, rf, fcx, fcy))
        bl = max(face.left_blush.alpha, face.right_blush.alpha) / 255.0
        u["uBlush"] = (fcx, fcy, min(1.0, bl * 1.4), 30.0)
        sp = getattr(face, "_scene_p", 0.0)
        tearing = (getattr(face, "_scene_name", None) == "glitch" and 0.12 < sp < 0.82)
        u["uGlitch"] = (1.0, float(int(sp * 24))) if tearing else (0.0, 0.0)
        self.shape_rects = self._shape_boxes(u)
        return u

    def _mouth(self, face, rf, fcx, fcy):
        m = face.mouth
        mx, my = fcx + m.rel_x, fcy + m.rel_y
        alpha = max(0.0, min(1.0, m.visible))
        talking = face._speaking or m.speak_fade > 0.05
        emo = face._emotion
        slant, kind, bend, open_ = 0.0, 0.0, 0.0, 0.0
        w, h = 160.0, 10.0
        if talking:
            e = m.talk_open
            if e > 0.06:
                kind, open_ = 1.0, e
                w = _lerp(m.mouth_w * 0.45, m.mouth_w, max(0.0, min(1.0, (e - 0.06) / 0.5)))
                h = max(12.0, 10.0 + (e + m.jaw_bounce * 0.3) * 82.0)
            else:
                w, h, bend = 140.0, 10.0, m.corner_lift * 8.0
        elif emo in ("happy", "excited", "love"):
            w, h, bend = 210.0, 20.0, 30.0
            my += 6
        elif emo == "surprised":
            kind, w = 2.0, 80.0
        elif emo == "angry":
            w, h, slant = 200.0, 16.0, 8.0
        elif emo == "sad":
            w, h, bend = 170.0, 16.0, -22.0
            my += 30
        elif emo == "sleeping":
            w, h, bend, alpha = 150.0, 8.0, -6.0, alpha * 0.6
        else:
            alpha = 0.0
        return {"uMouth": (mx, my, w, h), "uMouthK": (bend, open_, alpha, kind),
                "uMouthSlant": slant}
