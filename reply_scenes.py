"""
reply_scenes.py — Luna's body language while she answers.

The model picks one of these per reply (the "gesture" field, see brain.py)
and robot_face.py plays it while she talks. Each scene is a small class
registered with @scene(name, duration, mood=None). It may implement:

    motion(face, p)          head / pupil movement       (called from update)
    eyes(face, p, e)         blink, squint, widen        (e is mutable)
    hands(face, p, h)        hand targets and poses      (h is mutable)
    draw(face, surf, cx, cy, p)   props drawn over the face
    post(face, screen, p)    effects on the finished frame

`p` is the scene's progress, 0.0 → 1.0; `mood` is the face it wears for its
duration. Adding a gesture means writing one class here and naming it in the
gesture vocabulary in brain.py.
"""

import math
import random

import pygame

import robot_face as rf          # used at call time only (circular by design)

SCENES = {}


class Scene:
    """Defaults, so a scene only implements what it actually uses."""
    name = ""
    duration = 4.0
    mood = None

    def motion(self, face, p):
        pass

    def eyes(self, face, p, e):
        pass

    def hands(self, face, p, h):
        pass

    def draw(self, face, surf, fcx, fcy, p):
        pass

    def post(self, face, screen, p):
        """Applied to the finished frame — glitches and screen effects."""
        pass


class Hands:
    """Mutable hand targets: (x, y, angle) relative to the face centre, plus
    the pose each hand holds. Resting hands sit below the screen edge."""
    __slots__ = ("l", "r", "pose_l", "pose_r")

    def __init__(self, l, r, pose_l, pose_r):
        self.l, self.r = l, r
        self.pose_l, self.pose_r = pose_l, pose_r


class Eyes:
    """Mutable eye parameters a scene may bend."""
    __slots__ = ("blink_l", "blink_r", "squint", "widen", "droop")

    def __init__(self, blink, squint, widen, droop):
        self.blink_l = self.blink_r = blink
        self.squint, self.widen, self.droop = squint, widen, droop


def scene(name, duration, mood=None):
    def deco(cls):
        inst = cls()
        inst.name, inst.duration, inst.mood = name, duration, mood
        SCENES[name] = inst
        return cls
    return deco


# ══ Eyes only — cheap, and what makes her look alive ═════════════════════════

@scene("wink", duration=1.1)
class Wink(Scene):
    """One eye closes fast and opens with a soft curve."""
    def eyes(self, face, p, e):
        w = math.sin(p * math.pi) ** 0.5
        shut = max(0.0, 1.0 - w * 1.25)
        if face._wink_side == "R":
            e.blink_r = min(e.blink_r, shut)
        else:
            e.blink_l = min(e.blink_l, shut)


@scene("double_blink", duration=0.9)
class DoubleBlink(Scene):
    """Two quick blinks in a row — a very human little tic."""
    def eyes(self, face, p, e):
        for centre in (0.25, 0.65):
            d = abs(p - centre)
            if d < 0.13:
                shut = 1.0 - (1.0 - d / 0.13) ** 0.6
                e.blink_l = e.blink_r = min(e.blink_l, shut)


@scene("slow_blink", duration=2.0, mood="happy")
class SlowBlink(Scene):
    """A long, lazy blink — the cat-like sign of being content."""
    def eyes(self, face, p, e):
        s = math.sin(p * math.pi) ** 0.7
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.95 * s)
        e.squint = max(e.squint, 0.4 * s)


@scene("cross_eyes", duration=1.8)
class CrossEyes(Scene):
    """Pupils converge on her own nose — confusion, or just being silly."""
    def motion(self, face, p):
        s = math.sin(p * math.pi)
        face._pupil_converge = 58.0 * s
        face.target_tilt = 4.0 * math.sin(p * math.pi * 3)

    def eyes(self, face, p, e):
        e.widen = max(e.widen, 0.4 * math.sin(p * math.pi))


@scene("eye_roll", duration=1.5)
class EyeRoll(Scene):
    """A full, theatrical roll of the eyes."""
    def motion(self, face, p):
        a = p * math.pi * 2 - math.pi / 2
        r = math.sin(p * math.pi)
        face.pupil_ox = 26.0 * math.cos(a) * r
        face.pupil_oy = -22.0 * math.sin(a) * r - 8.0 * r


@scene("eye_twitch", duration=1.3)
class EyeTwitch(Scene):
    """A nervous tic in one eye."""
    def eyes(self, face, p, e):
        if p < 0.75:
            t = abs(math.sin(p * math.pi * 9))
            if face._wink_side == "R":
                e.blink_r = min(e.blink_r, 1.0 - 0.8 * t)
                e.squint = max(e.squint, 0.45 * t)
            else:
                e.blink_l = min(e.blink_l, 1.0 - 0.8 * t)
                e.squint = max(e.squint, 0.45 * t)


@scene("remember", duration=3.0)
class Remember(Scene):
    """Eyes up and to the side, digging something out of memory."""
    def motion(self, face, p):
        s = math.sin(min(1.0, p * 1.3) * math.pi)
        face.pupil_ox = rf.lerp(face.pupil_ox, -24.0 * s, 0.12)
        face.pupil_oy = rf.lerp(face.pupil_oy, -26.0 * s, 0.12)
        face.target_tilt = -5.0 * s

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.3 * math.sin(p * math.pi))


@scene("smirk", duration=2.2)
class Smirk(Scene):
    """One corner of the mouth up, one brow raised — she knows something."""
    def motion(self, face, p):
        s = math.sin(p * math.pi)
        face.target_tilt = -6.0 * s
        face.pupil_ox = rf.lerp(face.pupil_ox, 16.0 * s, 0.15)

    def eyes(self, face, p, e):
        s = math.sin(p * math.pi)
        e.squint = max(e.squint, 0.5 * s)
        e.blink_r = min(e.blink_r, 1.0 - 0.25 * s)

    def draw(self, face, surf, fcx, fcy, p):
        s = math.sin(p * math.pi)
        if s < 0.05:
            return
        w, h = 190, 90
        ms = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.arc(ms, (*rf.MOUTH_COL, int(235 * s)),
                        pygame.Rect(0, -26, w, h + 26),
                        math.radians(205), math.radians(285), 16)
        surf.blit(ms, (int(fcx - w // 2 + 10), int(fcy + 112)))


# ── Drawing INTO the eyes ───────────────────────────────────────────────────
# The scenes below paint over the eye blocks (spirals, hearts, static…). They
# need to know where each eye is on this frame, which is what Eye.draw works
# out from its size, blink, squint and glance — mirrored here.

def _eye_rect(eye, fcx, fcy):
    """Screen rect of an eye as drawn this frame."""
    cx, cy = fcx + eye.rel_x, fcy + eye.rel_y
    w = int(eye.w)
    h_mod = eye.h * (1.0 - eye.squint * 0.4) * (1.0 + eye.widen * 0.2)
    vis_h = max(4, int(h_mod * eye.blink_t))
    r = pygame.Rect(cx - w // 2, cy - vis_h // 2, w, vis_h)
    if rf.EYE_MODE == "block":
        r = r.move(int(eye.pupil_ox * 0.55), int(eye.pupil_oy * 0.55))
        max_w = rf.EYE_SPREAD * 2 - 44
        if r.w > max_w:
            r = pygame.Rect(r.centerx - max_w // 2, r.y, max_w, r.h)
        if eye.squint > 0.05:
            clip = int(vis_h * eye.squint * 0.5)
            r = pygame.Rect(r.x, r.y + clip, r.w, max(4, r.h - clip))
    return r


def _eye_rects(face, fcx, fcy):
    return [(e, _eye_rect(e, fcx, fcy)) for e in (face.left_eye, face.right_eye)]


def _pupil_at(eye, rect):
    """Where the pupil sits inside an eye rect."""
    k = 0.45 if rf.EYE_MODE == "block" else 1.0
    return (rect.centerx + int(eye.pupil_ox * k), rect.centery + int(eye.pupil_oy * k))


def _eye_clip(layer):
    """Cut a layer the size of an eye down to the eye's rounded shape."""
    m = pygame.Surface(layer.get_size(), pygame.SRCALPHA)
    pygame.draw.rect(m, (255, 255, 255, 255), m.get_rect(),
                     border_radius=min(rf.EYE_RADIUS, min(m.get_size()) // 2))
    layer.blit(m, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return layer


def _dim(col, k):
    """A colour faded toward the black background. The face canvas has no
    alpha channel, so (r, g, b, a) drawn straight onto it comes out opaque."""
    return rf._lerp_col((0, 0, 0), col, rf.clamp(k, 0.0, 1.0))


def _star4(surf, x, y, r, col, alpha):
    """A four-pointed twinkle."""
    if r < 2 or alpha <= 4:
        return
    pts = []
    for i in range(8):
        a = i * math.pi / 4
        rr = r if i % 2 == 0 else r * 0.28
        pts.append((x + math.cos(a) * rr, y + math.sin(a) * rr))
    s = pygame.Surface((int(r * 2 + 4), int(r * 2 + 4)), pygame.SRCALPHA)
    pygame.draw.polygon(s, (*col, alpha), [(px - x + r + 2, py - y + r + 2) for px, py in pts])
    surf.blit(s, (int(x - r - 2), int(y - r - 2)))


@scene("dizzy", duration=3.4)
class Dizzy(Scene):
    """Spirals for eyes, head going round — then she shakes it off."""
    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.12, 0.2)
        t = p * self.duration
        face._pupil_mul = 1.0 - hold
        if p < 0.82:
            face.target_ox += 16.0 * math.cos(t * 5.5) * hold
            face.target_oy += 9.0 * math.sin(t * 5.5) * hold
            face.target_tilt = 7.0 * math.sin(t * 2.7) * hold
        else:                                     # shakes it off
            face.target_ox += 18.0 * math.sin(t * 30.0) * (1.0 - p) / 0.18

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.12, 0.2)
        if hold < 0.05:
            return
        t = p * self.duration
        for i, (eye, rect) in enumerate(_eye_rects(face, fcx, fcy)):
            R = min(rect.w, rect.h) / 2 - 8
            if R < 12:
                continue
            spin = t * 7.0 * (1 if i == 0 else -1)
            lw, lh = rect.w + 16, rect.h + 16      # small layer: the fade needs
            pts = []                                # alpha, a full-screen one is slow
            for j in range(80):
                k = j / 79
                a = spin + k * 3.2 * math.tau
                pts.append((lw / 2 + math.cos(a) * R * k * 1.15,
                            lh / 2 + math.sin(a) * R * k))
            layer = pygame.Surface((lw, lh), pygame.SRCALPHA)
            pygame.draw.lines(layer, (*rf.PUPIL_DARK, int(235 * hold)), False, pts, 7)
            surf.blit(layer, (rect.x - 8, rect.y - 8))
        for k in range(3):                        # little stars circling above
            a = t * 3.0 + k * math.tau / 3
            x = fcx + math.cos(a) * 150
            y = fcy - 150 + math.sin(a) * 26
            _star4(surf, x, y, 16, rf.STAR_COL, int(230 * hold))


@scene("big_pupils", duration=3.4)
class BigPupils(Scene):
    """Huge, shiny puppy-dog pupils. Hard to say no to."""
    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        face._pupil_mul = 1.0 + 1.1 * hold
        face.target_tilt = 7.0 * hold
        face.pupil_oy = rf.lerp(face.pupil_oy, -8.0 * hold, 0.1)

    def eyes(self, face, p, e):
        e.widen = max(e.widen, 0.6 * rf._prop_hold(p, 0.2, 0.2))

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.3, 0.2)
        if hold < 0.05:
            return
        t = p * self.duration
        for eye, rect in _eye_rects(face, fcx, fcy):
            if rect.h < 40:
                continue
            px, py = _pupil_at(eye, rect)
            r = min(rect.w, rect.h) * 0.2 * eye.pupil_scale
            a = int(220 * hold)                   # extra catch-lights = "wet" eyes
            pygame.draw.circle(surf, rf.IRIS_SHINE,
                               (int(px + r * 0.35), int(py + r * 0.4)), max(2, int(r * 0.12)))
            _star4(surf, px - r * 0.35, py - r * 0.4,
                   r * (0.3 + 0.05 * math.sin(t * 6)), rf.IRIS_SHINE, a)


@scene("flutter", duration=2.4, mood="love")
class Flutter(Scene):
    """Bats her eyelashes at you."""
    def _flap(self, p):
        if 0.1 < p < 0.8:
            return abs(math.sin((p - 0.1) / 0.7 * math.pi * 5))
        return 0.0

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.15, 0.2)
        face.target_tilt = 8.0 * hold
        face.pupil_oy = rf.lerp(face.pupil_oy, -10.0 * hold, 0.12)

    def eyes(self, face, p, e):
        f = self._flap(p)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.85 * f)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.1, 0.15)
        if hold < 0.05:
            return
        for i, (eye, rect) in enumerate(_eye_rects(face, fcx, fcy)):
            out = -1 if i == 0 else 1             # lashes sweep outward
            for k in range(3):
                x = rect.centerx + out * (rect.w * (0.18 + 0.16 * k))
                y = rect.top + 4 + 6 * k
                ang = math.radians(-90 + out * (25 + 18 * k))
                ln = 22 + 4 * k
                pygame.draw.line(surf, rf.EYE_MID, (x, y),
                                 (x + math.cos(ang) * ln, y + math.sin(ang) * ln), 7)


@scene("heart_eyes", duration=4.0)
class HeartEyes(Scene):
    """Her pupils turn into beating hearts."""
    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.15, 0.15)
        t = p * self.duration
        face._pupil_mul = 1.0 - hold
        face.target_oy += 5.0 * math.sin(t * 9.0) * hold
        face.target_tilt = 5.0 * math.sin(t * 2.0) * hold

    def eyes(self, face, p, e):
        e.widen = max(e.widen, 0.4 * rf._prop_hold(p, 0.15, 0.15))

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.15, 0.15)
        if hold < 0.05:
            return
        t = p * self.duration
        beat = 1.0 + 0.14 * max(0.0, math.sin(t * 9.0)) ** 3
        for eye, rect in _eye_rects(face, fcx, fcy):
            if rect.h < 30:
                continue
            px, py = _pupil_at(eye, rect)
            size = int(min(rect.w, rect.h) * 0.36 * beat * hold)
            if size > 6:
                rf.draw_heart(surf, px, py - int(size * 0.45), size, 245)
        for k in range(3):                        # small hearts floating up
            u = (t * 0.45 + k / 3) % 1.0
            a = int(220 * hold * (1.0 - u))
            if a > 8:
                rf.draw_heart(surf, int(fcx + (k - 1) * 170 + 20 * math.sin(t * 2 + k)),
                              int(fcy - 110 - u * 110), 16, a)


@scene("suspicious", duration=3.6)
class Suspicious(Scene):
    """Narrowed eyes sliding sideways: hmm, really?"""
    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.15, 0.2)
        look = -1.0 if p < 0.5 else 1.0
        face.pupil_ox = rf.lerp(face.pupil_ox, 30.0 * look * hold, 0.05)
        face.target_ox += 12.0 * look * hold
        face.target_tilt = -5.0 * look * hold

    def eyes(self, face, p, e):
        hold = rf._prop_hold(p, 0.15, 0.2)
        e.squint = max(e.squint, 0.8 * hold)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.2 * hold)


@scene("sparkle_eyes", duration=3.0)
class SparkleEyes(Scene):
    """Stars in her eyes — delighted, dazzled."""
    SPOTS = ((-0.28, -0.22, 0.0), (0.24, 0.18, 1.9), (0.05, -0.05, 3.7))

    def motion(self, face, p):
        face._pupil_mul = 1.0 + 0.3 * rf._prop_hold(p, 0.15, 0.2)

    def eyes(self, face, p, e):
        e.widen = max(e.widen, 0.7 * rf._prop_hold(p, 0.15, 0.2))

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.15, 0.2)
        if hold < 0.05:
            return
        t = p * self.duration
        for eye, rect in _eye_rects(face, fcx, fcy):
            if rect.h < 40:
                continue
            for dx, dy, ph in self.SPOTS:
                tw = max(0.0, math.sin(t * 5.0 + ph))
                r = min(rect.w, rect.h) * 0.2 * tw
                _star4(surf, rect.centerx + dx * rect.w, rect.centery + dy * rect.h,
                       r, rf.IRIS_SHINE, int(250 * hold))


@scene("lost_signal", duration=4.0)
class LostSignal(Scene):
    """Her eyes lose the signal and dissolve into static for a moment."""
    def _level(self, p):
        """0 clear … 1 pure static, with a flickery way in and out."""
        if p < 0.12 or p > 0.9:
            return 0.0
        rnd = random.Random(int(p * self.duration * 12))
        if p < 0.3 or p > 0.75:
            return 1.0 if rnd.random() < 0.45 else 0.0
        return 1.0

    def motion(self, face, p):
        if self._level(p) > 0.5:
            face._pupil_mul = 0.0

    def draw(self, face, surf, fcx, fcy, p):
        lvl = self._level(p)
        if lvl <= 0:
            return
        t = p * self.duration
        rnd = random.Random(int(t * 20))
        for eye, rect in _eye_rects(face, fcx, fcy):
            if rect.h < 20:
                continue
            w, h = rect.size
            layer = pygame.Surface((w, h), pygame.SRCALPHA)
            layer.fill((*rf.PUPIL_DARK, 245))
            for _ in range(110):
                x = rnd.randint(0, w - 1)
                y = rnd.randint(0, h - 1)
                c = rf.TEETH_COL if rnd.random() < 0.6 else rf.EYE_INNER
                pygame.draw.rect(layer, (*c, rnd.randint(60, 230)),
                                 pygame.Rect(x, y, rnd.randint(3, 14), 3))
            band = int((t * 90) % (h + 30)) - 15      # the rolling bar
            pygame.draw.rect(layer, (*rf.TEETH_COL, 60), pygame.Rect(0, band, w, 14))
            surf.blit(_eye_clip(layer), rect.topleft)

# ══ Hands ═══════════════════════════════════════════════════════════════════

@scene("clap", duration=2.8, mood="happy")
class Clap(Scene):
    """Applause: both hands come together, again and again."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.15, 0.15)
        near = abs(math.sin(p * self.duration * 3.4))     # 0 apart, 1 together
        x = 165 - 120 * near
        h.l = (-x * hold - 330 * (1 - hold), 120, 22 - 12 * near)
        h.r = ( x * hold + 330 * (1 - hold), 120, -22 + 12 * near)

    def motion(self, face, p):
        near = abs(math.sin(p * self.duration * 3.4))
        face.target_oy += 6.0 * near * rf._prop_hold(p, 0.15, 0.15)


@scene("wave_both", duration=3.0, mood="happy")
class WaveBoth(Scene):
    """Waves with both hands — unmistakably pleased to see you."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.18, 0.18)
        rock = 26.0 * math.sin(p * self.duration * 6.0)
        h.l = (-290, 60 + 320 * (1 - hold), -rock)
        h.r = ( 290, 60 + 320 * (1 - hold),  rock)

    def motion(self, face, p):
        face.target_tilt = 4.0 * math.sin(p * self.duration * 6.0)


@scene("scratch_head", duration=3.0)
class ScratchHead(Scene):
    """Scratches the top of her head — puzzled."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.2, 0.2)
        a = p * self.duration * 5.0
        h.r = (215, -155 + 6 * math.sin(a) + 420 * (1 - hold), -28)

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        face.target_tilt = -7.0 * hold
        face.pupil_ox = rf.lerp(face.pupil_ox, 18.0 * hold, 0.12)
        face.pupil_oy = rf.lerp(face.pupil_oy, -14.0 * hold, 0.12)

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.35 * rf._prop_hold(p, 0.2, 0.2))


@scene("chin_rest", duration=5.0)
class ChinRest(Scene):
    """Props her chin on one hand and thinks about it."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.15, 0.15)
        h.r = (105, 188 + 260 * (1 - hold), -18)

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.15, 0.15)
        face.target_tilt = 6.0 * hold
        face.target_oy  += 6.0 * hold
        face.pupil_ox = rf.lerp(face.pupil_ox, -20.0 * hold, 0.08)
        face.pupil_oy = rf.lerp(face.pupil_oy, -12.0 * hold, 0.08)

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.3 * rf._prop_hold(p, 0.15, 0.15))


@scene("salute", duration=2.6, mood="happy")
class Salute(Scene):
    """Hand to the brow, held, then dropped. At your service."""
    def hands(self, face, p, h):
        if p < 0.22:
            k = p / 0.22
        elif p < 0.7:
            k = 1.0
        else:
            k = max(0.0, 1.0 - (p - 0.7) / 0.3)
        h.r = (rf.lerp(330, 190, k), rf.lerp(420, -150, k), rf.lerp(0, 34, k))

    def motion(self, face, p):
        if 0.22 < p < 0.75:
            face.target_tilt = -4.0
            face.target_oy -= 5.0


@scene("please", duration=3.2, mood="love")
class Please(Scene):
    """Palms together, big pleading eyes."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.18, 0.18)
        beg = 6.0 * math.sin(p * self.duration * 3.0)
        h.l = (-40, 190 + beg + 300 * (1 - hold),  26)
        h.r = ( 40, 190 + beg + 300 * (1 - hold), -26)

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.18, 0.18)
        face.target_tilt = 5.0 * math.sin(p * math.pi * 2) * hold
        face.pupil_oy = rf.lerp(face.pupil_oy, -10.0 * hold, 0.1)

    def eyes(self, face, p, e):
        e.widen = max(e.widen, 0.85 * rf._prop_hold(p, 0.18, 0.18))


# Offsets from a hand's centre to its fingertip, right-hand image unrotated
# (see robot_face.hand_surface): the raised index finger of "point", and the
# pinched ring of "ok".
_POINT_TIP = (-26, -74)
_PINCH = (-38, -11)


@scene("thumbs_down", duration=2.6)
class ThumbsDown(Scene):
    """Thumb down, a little shake of the head. Meh."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.2, 0.2)
        bob = 6.0 * math.sin(p * self.duration * 4.0)
        h.pose_r = "thumb_down"
        h.r = (290, 135 + bob + 360 * (1 - hold), 6)

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        face.target_ox += 8.0 * math.sin(p * self.duration * 7.0) * hold
        face.target_tilt = -4.0 * hold

    def eyes(self, face, p, e):
        hold = rf._prop_hold(p, 0.2, 0.2)
        e.squint = max(e.squint, 0.5 * hold)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.25 * hold)


@scene("snap", duration=2.4)
class Snap(Scene):
    """Snaps her fingers — got it!"""
    SNAP = 0.5
    _font = None

    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.2, 0.2)
        before = p < self.SNAP
        h.pose_r = "ok" if before else "point"
        wind = -10.0 * math.sin(min(1.0, p / self.SNAP) * math.pi) if before else 0.0
        jolt = 14.0 if self.SNAP <= p < self.SNAP + 0.05 else 0.0
        h.r = (250, 20 + jolt + 380 * (1 - hold), wind)

    def motion(self, face, p):
        if self.SNAP <= p < self.SNAP + 0.1:
            face.target_oy -= 10.0

    def eyes(self, face, p, e):
        d = p - self.SNAP
        if 0 <= d < 0.05:
            e.blink_l = e.blink_r = min(e.blink_l, 0.2)
        elif 0.05 <= d < 0.35:
            e.widen = max(e.widen, 0.8)

    def draw(self, face, surf, fcx, fcy, p):
        d = (p - self.SNAP) / 0.25
        if not 0.0 <= d <= 1.0:
            return
        if Snap._font is None:
            Snap._font = rf._get_font(34)
        x = fcx + 250 + _PINCH[0]
        y = fcy + 20 + _PINCH[1]
        a = int(250 * (1.0 - d))
        for k in range(7):                      # a spark off the fingers
            ang = -math.pi / 2 + (k - 3) * 0.42
            r0, r1 = 26 + 30 * d, 46 + 52 * d
            pygame.draw.line(surf, _dim(rf.STAR_COL, 1.0 - d),
                             (x + math.cos(ang) * r0, y + math.sin(ang) * r0),
                             (x + math.cos(ang) * r1, y + math.sin(ang) * r1), 5)
        txt = Snap._font.render("pstryk!", True, rf.EYE_INNER)
        txt.set_alpha(a)
        surf.blit(txt, txt.get_rect(center=(int(x + 70), int(y - 150 - 20 * d))))


@scene("ok_sign", duration=2.8, mood="happy")
class OkSign(Scene):
    """Thumb and finger in a ring, and a wink: all good."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.2, 0.2)
        h.pose_r = "ok"
        h.r = (262, 40 + 4 * math.sin(p * self.duration * 4.0) + 380 * (1 - hold), -6)

    def motion(self, face, p):
        face.target_tilt = -5.0 * rf._prop_hold(p, 0.2, 0.2)

    def eyes(self, face, p, e):
        if 0.35 < p < 0.65:                      # the wink that goes with it
            w = math.sin((p - 0.35) / 0.3 * math.pi)
            e.blink_r = min(e.blink_r, 1.0 - 0.95 * w)


@scene("air_heart", duration=4.6, mood="love")
class AirHeart(Scene):
    """Draws a glowing heart in the air with one finger."""
    DRAW_FROM, DRAW_TO = 0.15, 0.72
    CX, CY, SCALE = 0, 70, 5.6

    def _pt(self, a):
        x = 16 * math.sin(a) ** 3
        y = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
        return self.CX + x * self.SCALE, self.CY - y * self.SCALE

    def _drawn(self, p):
        """How far round the heart the finger has got, 0..1."""
        return rf.clamp((p - self.DRAW_FROM) / (self.DRAW_TO - self.DRAW_FROM), 0, 1)

    def hands(self, face, p, h):
        h.pose_r = "point"
        if p < self.DRAW_FROM:                     # up to the starting point
            k = p / self.DRAW_FROM
            tx, ty = self._pt(0.0)
            h.r = (rf.lerp(330, tx - _POINT_TIP[0], k), rf.lerp(420, ty - _POINT_TIP[1], k), 0)
        elif p < self.DRAW_TO:
            tx, ty = self._pt(self._drawn(p) * math.tau)
            h.r = (tx - _POINT_TIP[0], ty - _POINT_TIP[1], 0)
        else:                                      # and away again
            k = min(1.0, (p - self.DRAW_TO) / 0.15)
            tx, ty = self._pt(0.0)
            h.r = (rf.lerp(tx - _POINT_TIP[0], 330, k), rf.lerp(ty - _POINT_TIP[1], 420, k), 0)

    def motion(self, face, p):
        tx, ty = self._pt(self._drawn(p) * math.tau)
        if self.DRAW_FROM < p < self.DRAW_TO:     # watches her own finger
            face.pupil_ox = rf.lerp(face.pupil_ox, tx * 0.2, 0.2)
            face.pupil_oy = rf.lerp(face.pupil_oy, rf.clamp((ty - 20) * 0.2, -20, 26), 0.2)

    def draw(self, face, surf, fcx, fcy, p):
        d = self._drawn(p)
        if d <= 0.0 or p > 0.97:
            return
        fade = 1.0 if p < 0.85 else max(0.0, 1.0 - (p - 0.85) / 0.12)
        n = max(2, int(80 * d))
        pts = [(fcx + x, fcy + y)
               for x, y in (self._pt(i / 79 * math.tau) for i in range(n))]
        layer = pygame.Surface((340, 300), pygame.SRCALPHA)
        ox, oy = fcx - 170, fcy - 60
        local = [(x - ox, y - oy) for x, y in pts]
        if d >= 1.0:                               # finished: it fills and beats
            beat = 0.5 + 0.5 * math.sin(p * self.duration * 9.0)
            pygame.draw.polygon(layer, (*rf.HEART_COL, int((90 + 70 * beat) * fade)), local)
        if len(local) > 1:
            pygame.draw.lines(layer, (*rf.HEART_COL, int(245 * fade)), d >= 1.0, local, 8)
        glow = layer.copy()
        glow.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
        rf.bloom(surf, glow, (ox, oy), radius=8, passes=1, max_alpha=int(90 * fade))
        surf.blit(layer, (ox, oy))

# ══ The screen itself ═══════════════════════════════════════════════════════


@scene("glitch", duration=2.6)
class Glitch(Scene):
    """Her picture tears for a moment — a hiccup in the machine."""
    def eyes(self, face, p, e):
        if 0.2 < p < 0.75:
            e.widen = max(e.widen, 0.5)

    def post(self, face, screen, p):
        if not (0.12 < p < 0.82):
            return
        rnd = random.Random(int(p * 24))
        w, h = screen.get_size()
        for _ in range(rnd.randint(2, 5)):
            y = rnd.randint(0, h - 20)
            bh = rnd.randint(8, 46)
            dx = rnd.randint(-42, 42)
            band = screen.subsurface(pygame.Rect(0, y, w, min(bh, h - y))).copy()
            screen.blit(band, (dx, y))
        if rnd.random() < 0.5:                      # a colour-split ghost
            ghost = screen.copy()
            ghost.set_alpha(60)
            screen.blit(ghost, (rnd.randint(-6, 6), rnd.randint(-3, 3)))


# ══ Emotions playing out ════════════════════════════════════════════════════
# Mostly eyes, head and the particle systems the face already has: a scene
# that wears mood="sad" gets tears for free, "angry" gets steam, "excited"
# gets the starburst, "love" gets hearts.

def _puff(surf, x, y, t, hold, n=5, spread=1.0, col=None):
    """A little cloud of breath drifting up and out."""
    col = col or rf.TEETH_COL
    for i in range(n):
        k = ((t * 0.9 + i * 0.21) % 1.0)
        a = int(170 * hold * (1.0 - k))
        if a <= 4:
            continue
        dx = (i - n / 2) * 15 * spread * (0.4 + k)
        dy = -k * 70
        r = int(6 + k * 13)
        pygame.draw.circle(surf, (*col, a), (int(x + dx), int(y + dy)), r)


@scene("laugh", duration=3.4, mood="happy")
class Laugh(Scene):
    """Shakes with laughter, mouth going, eyes screwed shut."""
    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.12, 0.2)
        shake = math.sin(p * self.duration * 13.0)
        face.target_oy  += 13.0 * shake * hold
        face.target_tilt = 6.0 * math.sin(p * self.duration * 6.5) * hold
        face._mouth_drive = (0.5 + 0.45 * abs(shake)) * hold

    def eyes(self, face, p, e):
        hold = rf._prop_hold(p, 0.12, 0.2)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.75 * hold)
        e.squint = max(e.squint, 0.9 * hold)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        if hold < 0.05:
            return
        for side in (-1, 1):                       # tears of laughter
            k = (p * 2.2 + (0 if side < 0 else 0.5)) % 1.0
            a = int(220 * hold * (1.0 - k))
            if a <= 6:
                continue
            x = fcx + side * 250
            y = fcy - 20 + k * 120
            pygame.draw.circle(surf, (*rf.TEAR_COL, a), (int(x), int(y)), 9)


@scene("sigh", duration=3.2)
class Sigh(Scene):
    """A long breath out; her whole face sinks with it."""
    def motion(self, face, p):
        out = math.sin(min(1.0, p * 1.2) * math.pi)
        face.target_oy += 22.0 * (p if p < 0.5 else 1.0 - (p - 0.5) * 0.7)
        face._mouth_drive = 0.35 * out
        face.target_tilt = 3.0 * out

    def eyes(self, face, p, e):
        e.droop = max(e.droop, 0.9 * math.sin(min(1.0, p * 1.2) * math.pi))
        e.squint = max(e.squint, 0.5)

    def draw(self, face, surf, fcx, fcy, p):
        if 0.25 < p < 0.8:
            _puff(surf, fcx, fcy + 190, p * self.duration,
                  math.sin((p - 0.25) / 0.55 * math.pi))


@scene("impatient", duration=4.0)
class Impatient(Scene):
    """Drums her fingers and glances away. Any day now."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.15, 0.15)
        tap = abs(math.sin(p * self.duration * 7.0))
        h.r = (250, 210 - 26 * tap + 300 * (1 - hold), -8)

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.15, 0.15)
        face.pupil_ox = rf.lerp(face.pupil_ox,
                                26.0 * math.sin(p * math.pi * 2.5) * hold, 0.1)
        face.target_tilt = 5.0 * hold

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.55 * rf._prop_hold(p, 0.15, 0.15))


@scene("think_bubble", duration=4.5)
class ThinkBubble(Scene):
    """Three dots rise above her head while she works something out."""
    def motion(self, face, p):
        hold = rf._prop_hold(p)
        face.pupil_oy = rf.lerp(face.pupil_oy, -24.0 * hold, 0.1)
        face.pupil_ox = rf.lerp(face.pupil_ox, 16.0 * hold, 0.08)
        face.target_tilt = -4.0 * hold

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.3 * rf._prop_hold(p))

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p)
        if hold < 0.03:
            return
        for i, (dx, dy, r) in enumerate(((-96, -148, 9), (-66, -182, 14),
                                         (-16, -226, 22))):
            k = rf.clamp(p * 3.4 - i * 0.55, 0.0, 1.0)
            if k <= 0:
                continue
            a = int(235 * hold * k)
            pygame.draw.circle(surf, (*rf.EYE_MID, a),
                               (int(fcx + dx), int(fcy + dy)), int(r * k), 4)


@scene("proud", duration=3.2, mood="excited")
class Proud(Scene):
    """Chin up, chest out — she is quite pleased with herself."""
    def motion(self, face, p):
        s = math.sin(min(1.0, p * 1.3) * math.pi)
        face.target_oy  -= 20.0 * s
        face.target_tilt = -3.0 * s

    def eyes(self, face, p, e):
        s = math.sin(min(1.0, p * 1.3) * math.pi)
        e.squint = max(e.squint, 0.5 * s)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.25 * s)


@scene("shy", duration=3.6, mood="love")
class Shy(Scene):
    """Looks away, blushing, half hiding behind a hand."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.2, 0.2)
        h.l = (-215, -20 + 400 * (1 - hold), 14)

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        face.pupil_ox = rf.lerp(face.pupil_ox, 26.0 * hold, 0.08)
        face.pupil_oy = rf.lerp(face.pupil_oy, 14.0 * hold, 0.08)
        face.target_tilt = 8.0 * hold
        face.target_ox += 14.0 * hold

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.55 * rf._prop_hold(p, 0.2, 0.2))


@scene("scared", duration=3.0)
class Scared(Scene):
    """Trembling, small eyes, a bead of sweat."""
    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.1, 0.25)
        t = p * self.duration
        face.target_ox  += 9.0 * math.sin(t * 34.0) * hold
        face.target_oy  += 6.0 * math.sin(t * 27.0) * hold + 12.0 * hold
        face.target_tilt = 4.0 * math.sin(t * 19.0) * hold

    def eyes(self, face, p, e):
        hold = rf._prop_hold(p, 0.1, 0.25)
        e.squint = max(e.squint, 0.5 * hold)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.2 * hold)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.15, 0.2)
        if hold < 0.05:
            return
        k = (p * 1.6) % 1.0                         # a drop running down
        a = int(230 * hold * (1.0 - k * 0.6))
        pygame.draw.circle(surf, (*rf.TEAR_COL, a),
                           (int(fcx + 268), int(fcy - 130 + k * 150)), 11)


@scene("dance", duration=6.0, mood="happy")
class Dance(Scene):
    """A little dance, hands up, the whole face swinging."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.15, 0.15)
        beat = p * self.duration * 2.1
        h.l = (-270, 30 - 30 * math.sin(beat * math.pi) + 400 * (1 - hold),
               -24 * math.sin(beat * math.pi))
        h.r = ( 270, 30 + 30 * math.sin(beat * math.pi) + 400 * (1 - hold),
                24 * math.sin(beat * math.pi))

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.15, 0.15)
        beat = p * self.duration * 2.1
        face.target_ox  += 34.0 * math.sin(beat * math.pi) * hold
        face.target_oy  += 14.0 * math.sin(beat * 2 * math.pi) * hold
        face.target_tilt = 10.0 * math.sin(beat * math.pi) * hold

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.45 * rf._prop_hold(p, 0.15, 0.15))


@scene("tear_wipe", duration=5.0, mood="sad")
class TearWipe(Scene):
    """A tear rolls down; after a moment she wipes it away."""
    WIPE = 0.55

    def hands(self, face, p, h):
        if self.WIPE - 0.1 < p < self.WIPE + 0.25:
            k = math.sin((p - self.WIPE + 0.1) / 0.35 * math.pi)
            h.l = (-160, rf.lerp(420, -10, k), 10)

    def motion(self, face, p):
        face.target_oy += 12.0 * rf._prop_hold(p, 0.15, 0.2)
        if p > self.WIPE + 0.3:
            face.target_tilt = -3.0

    def eyes(self, face, p, e):
        e.droop = max(e.droop, 0.85)
        if self.WIPE - 0.05 < p < self.WIPE + 0.2:
            e.blink_l = min(e.blink_l, 0.15)


@scene("relief", duration=3.4, mood="happy")
class Relief(Scene):
    """Lets out the breath she was holding."""
    def motion(self, face, p):
        out = math.sin(min(1.0, p * 1.4) * math.pi)
        face.target_oy += 26.0 * out
        face._mouth_drive = 0.4 * out

    def eyes(self, face, p, e):
        out = math.sin(min(1.0, p * 1.4) * math.pi)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.7 * out)
        e.squint = max(e.squint, 0.6 * out)

    def draw(self, face, surf, fcx, fcy, p):
        if 0.15 < p < 0.75:
            _puff(surf, fcx, fcy + 185, p * self.duration,
                  math.sin((p - 0.15) / 0.6 * math.pi), n=6, spread=1.3)


@scene("curious", duration=3.6)
class Curious(Scene):
    """Head right over to one side, with a question mark to match."""
    _font = None

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.18, 0.18)
        face.target_tilt = 14.0 * hold
        face.target_ox  += 18.0 * hold
        face.pupil_oy = rf.lerp(face.pupil_oy, -8.0 * hold, 0.1)

    def eyes(self, face, p, e):
        hold = rf._prop_hold(p, 0.18, 0.18)
        e.widen = max(e.widen, 0.7 * hold)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.18, 0.18)
        if hold < 0.04:
            return
        if Curious._font is None:
            Curious._font = rf._get_font(96)
        img = Curious._font.render("?", True, rf.EYE_MID)
        img = pygame.transform.rotate(img, 12 * math.sin(p * math.pi * 3))
        img.set_alpha(int(255 * hold))
        # kept well inside the frame: the 14 degree head tilt rotates the
        # whole canvas, which pushes anything near an edge off screen
        rect = img.get_rect(center=(int(fcx + 208), int(fcy - 92)))
        glow = img.copy()
        glow.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
        glow.set_alpha(int(120 * hold))
        rf.bloom(surf, glow, rect.topleft, radius=8, passes=1, max_alpha=90)
        surf.blit(img, rect)


# ══ Showing what she talks about ════════════════════════════════════════════
# Small props for the topic of a reply — the weather, an idea, a song. They
# sit above her head on the right, clear of the eyes, and fade in and out.

_PROP_X, _PROP_Y = 215, -128           # relative to the face centre


def _cloud(w, col, alpha):
    """A soft cartoon cloud on its own layer (w px wide)."""
    h = int(w * 0.62)
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    c = (*col, alpha)
    r = w // 5
    for fx, fy, fr in ((0.28, 0.62, 1.0), (0.5, 0.42, 1.35), (0.72, 0.62, 1.0),
                       (0.5, 0.68, 1.1)):
        pygame.draw.circle(s, c, (int(w * fx), int(h * fy)), int(r * fr))
    return s


def _blit_glow(surf, img, center, hold, glow=110):
    rect = img.get_rect(center=(int(center[0]), int(center[1])))
    g = img.copy()
    g.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
    rf.bloom(surf, g, rect.topleft, radius=8, passes=1, max_alpha=int(glow * hold))
    surf.blit(img, rect)


@scene("sunny", duration=3.6, mood="happy")
class Sunny(Scene):
    """A little sun with turning rays; she squints happily into it."""
    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.45 * rf._prop_hold(p, 0.2, 0.2))

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        face.pupil_ox = rf.lerp(face.pupil_ox, 18.0 * hold, 0.1)
        face.pupil_oy = rf.lerp(face.pupil_oy, -16.0 * hold, 0.1)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        if hold < 0.04:
            return
        t = p * self.duration
        size = 150
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        c = size // 2
        for i in range(10):
            a = t * 0.9 + i * math.tau / 10
            r0, r1 = 34, 52 + 6 * math.sin(t * 4 + i)
            pygame.draw.line(s, (*rf.STAR_COL, 235),
                             (c + math.cos(a) * r0, c + math.sin(a) * r0),
                             (c + math.cos(a) * r1, c + math.sin(a) * r1), 6)
        pygame.draw.circle(s, (*rf.STAR_COL, 255), (c, c), 27)
        s.set_alpha(int(255 * hold))
        _blit_glow(surf, s, (fcx + _PROP_X, fcy + _PROP_Y), hold, 140)


@scene("cloudy", duration=3.6)
class Cloudy(Scene):
    """Two clouds drift past above her head."""
    def motion(self, face, p):
        face.pupil_oy = rf.lerp(face.pupil_oy, -14.0 * rf._prop_hold(p, 0.2, 0.2), 0.1)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        if hold < 0.04:
            return
        drift = (p - 0.5) * 60
        for dx, dy, w, a in ((-40, 14, 110, 170), (30, -6, 150, 235)):
            c = _cloud(w, rf.TEETH_COL, int(a * hold))
            surf.blit(c, c.get_rect(center=(int(fcx + _PROP_X + dx + drift * (w / 150)),
                                            int(fcy + _PROP_Y + dy))))


@scene("rainy", duration=3.8, mood="sad")
class Rainy(Scene):
    """A small cloud right above her, raining on her head."""
    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.3 * rf._prop_hold(p, 0.2, 0.2))

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        face.pupil_oy = rf.lerp(face.pupil_oy, -18.0 * hold, 0.1)
        face.target_oy += 6.0 * hold                 # ducks a little

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        if hold < 0.04:
            return
        t = p * self.duration
        cx, cy = fcx + 30, fcy - 150
        layer = pygame.Surface((300, 230), pygame.SRCALPHA)
        for i in range(14):                           # the drops
            k = (t * 1.6 + i * 0.37) % 1.0
            x = 40 + (i * 47) % 220
            y = 50 + k * 170
            pygame.draw.line(layer, (*rf.TEAR_COL, int(220 * (1 - k * 0.6))),
                             (x, y), (x - 3, y + 14), 4)
        layer.set_alpha(int(255 * hold))
        surf.blit(layer, (int(cx - 150), int(cy - 10)))
        c = _cloud(190, (150, 160, 175), int(240 * hold))
        surf.blit(c, c.get_rect(center=(int(cx), int(cy))))


@scene("snowy", duration=4.0)
class Snowy(Scene):
    """Snowflakes swirl down past her face."""
    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        face.pupil_oy = rf.lerp(face.pupil_oy, 14.0 * math.sin(p * math.pi * 3) * hold, 0.08)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.2, 0.2)
        if hold < 0.04:
            return
        t = p * self.duration
        layer = pygame.Surface((rf.WIDTH, rf.HEIGHT), pygame.SRCALPHA)
        rnd = random.Random(7)
        for i in range(26):
            x0, speed, ph = rnd.random(), rnd.uniform(0.18, 0.35), rnd.uniform(0, 6.3)
            y = ((rnd.random() + t * speed) % 1.1) * rf.HEIGHT - 20
            x = x0 * rf.WIDTH + 18 * math.sin(t * 1.5 + ph)
            r = 3 + (i % 3) * 2
            pygame.draw.circle(layer, (*rf.TEETH_COL, 225), (int(x), int(y)), r)
        layer.set_alpha(int(255 * hold))
        surf.blit(layer, (0, 0))


@scene("lightbulb", duration=3.0, mood="happy")
class Lightbulb(Scene):
    """A bulb above her head flickers on: she has an idea."""
    ON = 0.3

    def eyes(self, face, p, e):
        if p > self.ON:
            e.widen = max(e.widen, 0.7 * rf._prop_hold(p, 0.2, 0.2))

    def motion(self, face, p):
        if self.ON < p < self.ON + 0.1:
            face.target_oy -= 10.0

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.15, 0.2)
        if hold < 0.04:
            return
        # flickers on: off, on, off, ON
        lit = p > self.ON and not (self.ON + 0.04 < p < self.ON + 0.08)
        s = pygame.Surface((110, 150), pygame.SRCALPHA)
        glass = (*(rf.STAR_COL if lit else (120, 110, 90)), 245)
        pygame.draw.circle(s, glass, (55, 52), 40)
        pygame.draw.polygon(s, glass, [(30, 70), (80, 70), (70, 100), (40, 100)])
        for i in range(3):                                   # the screw base
            pygame.draw.rect(s, (*rf.EYE_MID, 245), pygame.Rect(38, 102 + i * 11, 34, 8),
                             border_radius=3)
        if lit:
            pygame.draw.circle(s, (*rf.IRIS_SHINE, 230), (42, 40), 9)
        s = pygame.transform.smoothscale(s, (82, 112))
        s.set_alpha(int(255 * hold))
        bx, by = fcx, fcy - 150                     # right above her head
        _blit_glow(surf, s, (bx, by), hold, 170 if lit else 0)
        if lit:
            t = p * self.duration
            for i in range(8):                               # rays
                a = i * math.tau / 8 + t * 0.5
                r0, r1 = 46, 58 + 4 * math.sin(t * 8 + i)
                x, y = bx, by - 14
                pygame.draw.line(surf, _dim(rf.STAR_COL, hold),
                                 (x + math.cos(a) * r0, y + math.sin(a) * r0),
                                 (x + math.cos(a) * r1, y + math.sin(a) * r1), 4)


def _note(size, col):
    """A quaver: head, stem and flag."""
    w, h = size, int(size * 2.1)
    s = pygame.Surface((w + 8, h + 6), pygame.SRCALPHA)
    hr = size // 2
    sx = w - 4
    pygame.draw.rect(s, col, pygame.Rect(sx - 3, 3, 6, h - hr - 2), border_radius=2)
    pygame.draw.polygon(s, col, [(sx + 2, 5), (sx + 2 + size // 2, size // 2), (sx + 2, size - 2)])
    pygame.draw.ellipse(s, col, pygame.Rect(sx - hr * 2 + 2, h - hr * 2 + 2, int(hr * 2.3), hr * 2))
    return s


@scene("music_notes", duration=4.0, mood="happy")
class MusicNotes(Scene):
    """Notes float up while she sways — for songs and anything musical."""
    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.15, 0.2)
        face.target_tilt = 7.0 * math.sin(p * self.duration * 3.0) * hold
        face.target_ox += 10.0 * math.sin(p * self.duration * 3.0) * hold

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.5 * rf._prop_hold(p, 0.15, 0.2))

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.15, 0.2)
        if hold < 0.04:
            return
        t = p * self.duration
        for i in range(5):
            k = (t * 0.45 + i / 5) % 1.0
            a = int(235 * hold * math.sin(k * math.pi))
            if a <= 8:
                continue
            side = 1 if i % 2 else -1
            x = fcx + side * (230 + 30 * math.sin(t * 2 + i))
            y = fcy + 60 - k * 230
            n = _note(26 + (i % 2) * 8, (*rf.EYE_INNER, 255))
            n = pygame.transform.rotate(n, 14 * math.sin(t * 3 + i))
            n.set_alpha(a)
            surf.blit(n, n.get_rect(center=(int(x), int(y))))
