"""
gl_vis.py — the radio visualizer's picture (visualizer.py → here), behind
the face. Its own small shader, drawn at half size into its own texture and
added over the screen after the face's soft background (gl_face.render), so
the face's big shader stays as fast as it was (one shader with both: every
face frame +4 ms, the effects 13–66 ms at full size; Pi 4, 18 Oct).

Styles (uVisK.x): 1 ribbons, 2 rings, 3 sparks, 4 bars, 5 stereo waves +
heart, 6 notes. All stand on a glossy floor that mirrors them. Sparks and
notes come placed (uPart, uNote: visualizer.uniforms), each drawn in its own
small box — a loop over all of them per pixel cost +12 ms.
"""

_FRAG = """
uniform vec2  uRes;           // the screen (px); this is drawn at half of it
uniform vec2  uHalf;
uniform vec4  uVis0, uVis1, uVis2, uVis3;   // 16 bands 0..1, bass first
uniform vec4  uVisK;          // (style 1..6, strength, level, seconds)
uniform vec2  uVisLR;         // the left / right channel's level 0..1
uniform vec4  uVisBeat;       // seconds since the last four beats (99: none)
uniform vec3  uVisCol, uVisCol2;   // the palette: main, accent (the station's kind)
uniform vec2  uVisC;          // her face's centre (px)
uniform float uDraw;          // 0 the background, 1 one spark, 2 one note — in its box
uniform vec4  uItem;          // a spark: x, y, radius, brightness; a note: x, y, scale, brightness
uniform vec4  uItemK;         // a spark: colour; a note: cos, sin of its tilt, beamed pair, colour

float sq(float x) { return x * x; }
float dot2(vec2 v) { return dot(v, v); }
float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
float sdSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}
// a heart (iq), y up: its tip at (0, 0), its lobes up to y ~1.1
float sdHeart(vec2 p) {
    p.x = abs(p.x);
    if (p.y + p.x > 1.0) return sqrt(dot2(p - vec2(0.25, 0.75))) - 0.35355;
    return sqrt(min(dot2(p - vec2(0.0, 1.0)), dot2(p - 0.5 * max(p.x + p.y, 0.0))))
           * sign(p.x - p.y);
}

float visBand1(float i) {
    vec4 v = i < 4.0 ? uVis0 : (i < 8.0 ? uVis1 : (i < 12.0 ? uVis2 : uVis3));
    float j = mod(i, 4.0);
    return j < 1.0 ? v.x : (j < 2.0 ? v.y : (j < 3.0 ? v.z : v.w));
}
float visBand(float i) {
    float i0 = floor(clamp(i, 0.0, 15.0));
    float f = fract(i);
    return mix(visBand1(i0), visBand1(min(i0 + 1.0, 15.0)), f * f * (3.0 - 2.0 * f));
}
float lastBeat() { return exp(-uVisBeat.x * 5.0); }     // a flash on the beat, ~0.4 s
vec3 hot(vec3 c, float k) { return mix(c, vec3(1.0, 0.95, 0.82), k); }

// sparkles: one in a few cells, twinkling
float twinkle(vec2 f, float cs, float dens, float t) {
    vec2 cell = floor(f / cs);
    float h = hash(cell);
    if (h < 1.0 - dens) return 0.0;
    vec2 ctr = (cell + 0.5 + 0.35 * vec2(hash(cell + 7.1) - 0.5, hash(cell + 3.3) - 0.5)) * cs;
    float d = length(f - ctr);
    float tw = 0.5 + 0.5 * sin(t * (3.0 + 4.0 * h) + h * 60.0);
    return tw * (exp(-d * d / 4.0) + 0.3 * exp(-d / 4.0));
}

// 1 — ribbons: six glowing strands, quieter under her face, sparkle dust
vec3 visRibbons(vec2 f, float t) {
    if (f.y < uRes.y * 0.18) return vec3(0.0);
    vec3 c = vec3(0.0);
    float s = abs(f.x / uRes.x - 0.5) * 2.0;
    float mid = visBand(s * 15.0);
    float bass = (visBand1(0.0) + visBand1(1.0) + visBand1(2.0)) / 3.0;
    float side = 0.30 + 0.70 * smoothstep(0.05, 0.55, s);
    float base = uRes.y * 0.66;
    float bt = lastBeat();
    for (int k = 0; k < 6; k++) {
        float fk = float(k);
        // one ribbon: the strands share its shape, each a little wider (a fan)
        float fr = 0.0085;
        float amp = (14.0 + 75.0 * mid + 45.0 * bass) * side * (0.45 + 0.13 * fk);
        float a1 = f.x * fr - t * 0.7 + fk * 0.10;
        float a2 = f.x * fr * 2.3 + t * 0.5 + fk * 0.16;
        float y = base + 5.0 * fk - 12.0 + amp * sin(a1) + 0.45 * amp * sin(a2);
        float slope = amp * fr * (cos(a1) + 1.035 * cos(a2));
        float d = abs(f.y - y) / sqrt(1.0 + slope * slope);   // across the line, not down
        if (d > 60.0) continue;
        float w = 1.6 + 1.0 * fract(fk * 0.37);
        float b = (0.40 + 0.80 * mid + 0.5 * bt) * (k == 0 ? 1.0 : 0.65);
        vec3 lc = mix(uVisCol, uVisCol2, fract(fk * 0.41));
        c += lc * b * (0.9 * exp(-d * d / (w * w)) + 0.14 * exp(-d / 12.0));
        c += vec3(1.0, 0.93, 0.78) * b * 0.5 * exp(-d * d / (0.35 * w * w));
    }
    float near = exp(-abs(f.y - base) / 70.0);
    c += hot(uVisCol2, 0.5) * twinkle(f + vec2(-t * 12.0, 0.0), 10.0, 0.06, t) * near * (0.4 + mid) * side;
    return c;
}

// 2 — rings of sound beside her head: three breathing, one flying out per beat
vec3 visRings(vec2 f, float t) {
    vec2 v = f - uVisC;
    v.y *= 1.25;
    float r = length(v);
    float arc = smoothstep(1.05, 0.55, atan(abs(v.y), abs(v.x)));   // ( ) only, not above
    if (arc <= 0.0 || r < 250.0) return vec3(0.0);
    float lvl = uVisK.z;
    vec3 c = vec3(0.0);
    for (int k = 0; k < 3; k++) {
        float fk = float(k);
        float rr = 300.0 + 42.0 * fk + 14.0 * lvl * sin(t * 2.0 + fk);
        float d = abs(r - rr);
        float b = (0.25 + 0.6 * lvl) * (1.0 - 0.25 * fk);
        c += mix(uVisCol, uVisCol2, 0.3 * fk) * b * (exp(-d * d / 6.0) + 0.25 * exp(-d / 10.0));
    }
    for (int k = 0; k < 4; k++) {
        float a = k == 0 ? uVisBeat.x : (k == 1 ? uVisBeat.y : (k == 2 ? uVisBeat.z : uVisBeat.w));
        if (a > 2.0) continue;
        float d = abs(r - (290.0 + 330.0 * a));
        float w = 2.5 + 3.0 * a;
        c += hot(uVisCol, 0.4 * exp(-a * 3.0)) * 1.1 * exp(-a * 1.6)
             * (exp(-d * d / (w * w)) + 0.35 * exp(-d / 16.0));
    }
    return c * arc;
}

// 3 — sparks: glowing bokeh rising (each its own quad: oneSpark), sparkle dust
vec3 oneSpark(vec2 f) {
    vec4 q = uItem;
    float d = length(f - q.xy);
    float m = uItemK.x;
    return mix(uVisCol, uVisCol2, m) * q.w
           * (0.55 * smoothstep(q.z, q.z - 2.0, d) * (0.6 + 0.4 * m) + 0.35 * exp(-d / (q.z * 0.9)));
}
vec3 visSparks(vec2 f, float t) {
    return hot(uVisCol2, 0.6) * twinkle(f + vec2(0.0, t * 30.0), 12.0, 0.04, t) * (0.5 + uVisK.z);
}

// 4 — spectrum bars either side, bass at the edges, LED segments
vec3 visBars(vec2 f, float floorY) {
    bool left = f.x < uRes.x * 0.5;
    float e = (left ? f.x : uRes.x - f.x) - 14.0;
    float cell = floor(e / 24.0);
    float yb = floorY - f.y;
    if (cell < 0.0 || cell > 8.0 || yb < 0.0) return vec3(0.0);
    float fx = fract(e / 24.0);
    float lvl = left ? uVisLR.x : uVisLR.y;
    float band = visBand1(floor(cell * 1.85));
    float h = (0.05 + 0.50 * band * (0.65 + 0.5 * lvl)) * uRes.y;
    float w = smoothstep(0.08, 0.18, fx) * smoothstep(0.92, 0.82, fx);
    float seg = smoothstep(0.15, 0.35, fract(yb / 10.0));
    float in_ = smoothstep(h + 1.5, h - 1.5, yb);
    vec3 bc = mix(uVisCol, hot(uVisCol2, 0.5), clamp(yb / (0.5 * uRes.y), 0.0, 1.0));
    vec3 c = bc * w * in_ * mix(0.30, 1.0, seg);
    c += uVisCol * w * 0.35 * exp(-abs(yb - h) / 5.0);            // the glowing top
    c += uVisCol * w * 0.08 * in_;
    return c;
}

// 5 — stereo waves beside her (left / right channel), a heart beating below
vec3 visScope(vec2 f, float t) {
    float cy = uRes.y * 0.62;
    float x = f.x / uRes.x;
    float s = abs(x - 0.5) * 2.0;
    float lr = x < 0.5 ? uVisLR.x : uVisLR.y;
    float band = visBand(s * 15.0);
    float env = smoothstep(0.30, 0.50, s) * smoothstep(1.02, 0.85, s);
    float amp = env * (10.0 + 95.0 * band * (0.5 + 0.7 * lr));
    float y = cy + amp * sin(f.x * 0.21 - t * 9.0) * (0.6 + 0.4 * sin(f.x * 0.047 + t * 2.3));
    float d = abs(f.y - y);
    float lineK = smoothstep(0.24, 0.40, s);
    float slope = amp * 0.21 * cos(f.x * 0.21 - t * 9.0);
    d = max(d / sqrt(1.0 + slope * slope), abs(f.y - cy) - amp);   // (steep: never past its peaks)
    vec3 c = hot(uVisCol, 0.35) * (1.2 * exp(-d * d / 6.0) + 0.35 * exp(-d / 10.0)) * (0.6 + 0.7 * band) * lineK;
    c += uVisCol * 0.10 * env * smoothstep(amp + 4.0, 0.0, abs(f.y - cy));
    float bt = lastBeat();
    float hs = 17.0 * (1.0 + 0.30 * bt);
    vec2 hp = (f - vec2(uVisC.x, uRes.y * 0.84)) / hs;
    if (abs(hp.x) < 3.0 && abs(hp.y) < 3.0) {
        hp.y = 0.55 - hp.y;
        float dh = sdHeart(hp) * hs;
        vec3 hc = mix(uVisCol, vec3(1.0, 0.30, 0.42), 0.5);
        c += hc * (smoothstep(1.5, -1.5, dh) * (0.30 + 0.6 * bt) + 0.7 * exp(-abs(dh) / 2.5)
                   + 0.25 * exp(-max(dh, 0.0) / 14.0));
    }
    return c;
}

// a note, p in pixels about its head (y down): an eighth, or two beamed
float sdNote(vec2 p, float two) {
    vec2 q = vec2(0.85 * p.x + 0.5 * p.y, -0.5 * p.x + 0.85 * p.y);
    float d = length(q / vec2(9.0, 6.5)) * 6.5 - 6.5;
    d = min(d, sdSeg(p, vec2(8.0, -2.0), vec2(8.0, -38.0)) - 1.8);
    if (two < 0.5) {
        d = min(d, sdSeg(p, vec2(8.0, -38.0), vec2(18.0, -24.0)) - 2.4);
    } else {
        vec2 p2 = p - vec2(22.0, -6.0);
        vec2 q2 = vec2(0.85 * p2.x + 0.5 * p2.y, -0.5 * p2.x + 0.85 * p2.y);
        d = min(d, length(q2 / vec2(9.0, 6.5)) * 6.5 - 6.5);
        d = min(d, sdSeg(p2, vec2(8.0, -2.0), vec2(8.0, -32.0)) - 1.8);
        d = min(d, sdSeg(p, vec2(8.0, -38.0), vec2(30.0, -38.0)) - 3.2);
    }
    return d;
}

// 6 — notes floating up either side of her (placed by visualizer.py), over
//     a staff of light
vec3 visNotes(vec2 f, float t) {
    vec3 c = vec3(0.0);
    float s = abs(f.x / uRes.x - 0.5) * 2.0;
    float band = visBand(s * 15.0);
    float y0 = uRes.y * 0.70 + (20.0 + 40.0 * band) * sin(f.x * 0.009 - t * 0.8);
    if (abs(f.y - y0 - 18.0) < 60.0) {
        for (int k = 0; k < 5; k++) {
            float fk = float(k);
            float d = abs(f.y - (y0 + fk * 9.0));
            c += uVisCol * (0.45 * exp(-d * d / 2.5) + 0.06 * exp(-d / 10.0)) * (0.4 + 0.6 * band);
        }
    }
    c += hot(uVisCol2, 0.6) * twinkle(f + vec2(t * 8.0, t * 14.0), 12.0, 0.035, t) * 0.6;
    return c;
}

vec3 oneNote(vec2 f) {
    vec4 n = uItem;
    vec4 k = uItemK;
    vec2 p = (f - n.xy) / n.z;
    p = vec2(k.x * p.x - k.y * p.y, k.y * p.x + k.x * p.y);
    float d = sdNote(p, k.z) * n.z;
    return hot(mix(uVisCol2, uVisCol, k.w), 0.25) * n.w
           * (0.9 * smoothstep(1.2, -1.2, d) + 0.5 * exp(-max(d, 0.0) / 6.0));
}

vec3 visEffect(vec2 f, float floorY) {
    float t = uVisK.w;
    float m = uVisK.x;
    if (m < 1.5) return visRibbons(f, t);
    if (m < 2.5) return visRings(f, t);
    if (m < 3.5) return visSparks(f, t);
    if (m < 4.5) return visBars(f, floorY);
    if (m < 5.5) return visScope(f, t);
    return visNotes(f, t);
}

void main() {
    vec2 f = vec2(gl_FragCoord.x, uHalf.y - gl_FragCoord.y) * (uRes / uHalf);
    float fy = uRes.y * 0.90;                      // the floor
    vec3 c;
    if (uDraw > 0.5) {                             // one spark or note, added
        c = f.y < fy ? (uDraw < 1.5 ? oneSpark(f) : oneNote(f)) : vec3(0.0);
    } else if (f.y < fy) {
        c = visEffect(f, fy);
    } else {                                       // its rippling reflection
        float k = (f.y - fy) / (uRes.y - fy);
        vec2 m = vec2(f.x + 3.0 * sin(f.y * 0.35 + uVisK.w * 3.0), 2.0 * fy - f.y);
        c = visEffect(m, fy) * 0.35 * (1.0 - k);
        float s = abs(f.x / uRes.x - 0.5) * 2.0;
        c += uVisCol * 0.30 * exp(-(f.y - fy) / 2.0) * (0.3 + uVisK.z) * (1.0 - s * s);
    }
    gl_FragColor = vec4(c * uVisK.y, 1.0);
}
"""

# the picture, stretched over the screen and added (alpha 0: premultiplied "over"
# with nothing covered)
_COMPOSE = """
uniform sampler2D uTex;
uniform vec2 uRes;
void main() {
    gl_FragColor = vec4(texture2D(uTex, gl_FragCoord.xy / uRes).rgb, 0.0);
}
"""


class VisPass:
    """Made by gl_face.GLFace on the radio's first frame; draw() each frame
    the visualizer is on, between the soft background and the shapes."""

    def __init__(self, face):
        GL = self.GL = face.GL
        self.face = face
        head = "#version 120\n" if face.glsl == "120" else "#version 100\nprecision mediump float;\n"
        from gl_face import _VERT
        self.prog = face._program(head + _VERT, head + _FRAG)
        self.comp = face._program(head + _VERT, head + _COMPOSE)
        self._loc = {}
        self.hw, self.hh = max(1, face.w // 2), max(1, face.h // 2)
        self.tex = face._texture(self.hw, self.hh, GL.GL_LINEAR)
        self.fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_2D, self.tex, 0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, face.target_fbo)
        print("[gl] radio visualizer shader ready", flush=True)

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

    def draw(self, vis, face_xy):
        """vis: visualizer.uniforms()'s dict. Leaves the face's program in use,
        its framebuffer bound, blending premultiplied."""
        GL, face = self.GL, self.face
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glViewport(0, 0, self.hw, self.hh)
        GL.glDisable(GL.GL_BLEND)
        GL.glUseProgram(self.prog)
        full = (0.0, 0.0, float(face.w), float(face.h))
        self._set(self.prog, "uRes", (face.w, face.h))
        self._set(self.prog, "uHalf", (self.hw, self.hh))
        self._set(self.prog, "uRect", full)
        self._set(self.prog, "uVisC", face_xy)
        items = []
        for k, v in vis.items():
            if k == "uPart":
                items += [(1.0, (x - r * 4 - 6, y - r * 4 - 6, x + r * 4 + 6, y + r * 4 + 6),
                           (x, y, r, b), ((i * 0.618) % 1.0, 0.0, 0.0, 0.0))
                          for i, (x, y, r, b) in enumerate(v) if b > 0.01]
            elif k == "uNote":
                items += [(2.0, (x - 35 * sc, y - 72 * sc, x + 62 * sc, y + 30 * sc),
                           (x, y, sc, b), kk)
                          for (x, y, sc, b), kk in zip(v, vis["uNoteK"]) if b > 0.01]
            elif k != "uNoteK":
                self._set(self.prog, k, v)
        self._set(self.prog, "uDraw", 0.0)
        face._quad()
        if items:                            # sparks, notes: each in its own box
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE)
            for kind, box, item, itemk in items:
                self._set(self.prog, "uDraw", kind)
                self._set(self.prog, "uRect", box)
                self._set(self.prog, "uItem", item)
                self._set(self.prog, "uItemK", itemk)
                face._quad()
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, face.target_fbo)
        GL.glViewport(0, 0, face.w, face.h)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glUseProgram(self.comp)
        self._set(self.comp, "uRes", (face.w, face.h))
        self._set(self.comp, "uRect", full)
        GL.glActiveTexture(GL.GL_TEXTURE0 + 4)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glUniform1i(self._loc_of(self.comp, "uTex"), 4)
        face._quad()
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glUseProgram(face.prog)
