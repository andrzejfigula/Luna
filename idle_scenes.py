"""
idle_scenes.py — the catalogue of things Luna does on her own.

Each scene is a small class registered with @scene(...). It may implement:

    motion(face, p)          head / pupil movement       (called from update)
    eyes(face, p, e)         blink, squint, widen        (e is mutable)
    draw(face, surf, cx, cy, p)   props drawn over the face

`p` is the scene's progress, 0.0 → 1.0. The registry carries the metadata the
rest of the app needs: how long it runs, how often it comes up (day and
night), the mood it wears, whether it needs someone in front of the camera,
and whether the LLM may use it as body language in a spoken reply.

Adding a behaviour means writing one self-contained class here — nothing else
in the app has to change.
"""

import math
import random
import time

import pygame

import robot_face as rf          # used at call time only (circular by design)

SCENES = {}


class Scene:
    """Defaults, so a scene only implements what it actually uses."""
    name = ""
    duration = 4.0
    weight = 3
    night_weight = None
    mood = None
    needs_face = False
    in_reply = False
    hours = None            # ("from", "to") hour window, e.g. (5, 18)
    dates = None            # ("MM-DD", "MM-DD") window; wraps the new year
    forced = False          # play as soon as available(), without waiting
                            # for the random scene timer (calendar moments)

    def available(self):
        """Extra condition beyond hours/dates — the top of the hour, a
        birthday in the config, that sort of thing."""
        return True

    def motion(self, face, p):
        pass

    def eyes(self, face, p, e):
        pass

    def hands(self, face, p, h):
        pass

    def draw_bg(self, face, surf, fcx, fcy, p):
        """Drawn BEHIND her face — weather, starfields, backdrops."""
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


def scene(name, duration, weight=3, night_weight=None, mood=None,
          needs_face=False, in_reply=False, hours=None, dates=None,
          forced=False):
    def deco(cls):
        inst = cls()
        inst.name, inst.duration = name, duration
        inst.weight = weight
        inst.night_weight = weight if night_weight is None else night_weight
        inst.mood, inst.needs_face, inst.in_reply = mood, needs_face, in_reply
        inst.hours, inst.dates, inst.forced = hours, dates, forced
        SCENES[name] = inst
        return cls
    return deco


def _in_dates(window):
    """True when today falls inside ("MM-DD", "MM-DD"); wraps the new year."""
    if not window:
        return True
    a, b = window
    today = time.strftime("%m-%d")
    return a <= today <= b if a <= b else (today >= a or today <= b)


def usable(s, face_present):
    """Everything except the weights: is this scene allowed right now?"""
    return (_in_hours(s.hours) and _in_dates(s.dates) and s.available()
            and not (s.needs_face and not face_present))


def forced_scene(face_present, disabled=()):
    """A calendar moment that should play now, rather than wait its turn."""
    for s in SCENES.values():
        if s.forced and s.name not in disabled and usable(s, face_present):
            return s.name
    return None


def _in_hours(window):
    """True when the local hour is inside (from, to); wraps past midnight."""
    if not window:
        return True
    h = time.localtime().tm_hour
    a, b = window
    return a <= h < b if a <= b else (h >= a or h < b)


def reply_scenes():
    """Scene names the LLM may pick as body language for a reply."""
    return [s.name for s in SCENES.values() if s.in_reply]


def pick(night, face_present, weights_override=None, disabled=()):
    """Weighted random scene name for the current situation."""
    names, weights = [], []
    for s in SCENES.values():
        if s.name in disabled or s.forced or not usable(s, face_present):
            continue
        w = (weights_override or {}).get(
            s.name, s.night_weight if night else s.weight)
        if w > 0:
            names.append(s.name)
            weights.append(w)
    return random.choices(names, weights=weights)[0] if names else None


# ══ Eyes only — cheap, and what makes her look alive ═════════════════════════

@scene("wink", duration=1.1, weight=3, night_weight=1, needs_face=True,
       in_reply=True)
class Wink(Scene):
    """One eye closes fast and opens with a soft curve."""
    def eyes(self, face, p, e):
        w = math.sin(p * math.pi) ** 0.5
        shut = max(0.0, 1.0 - w * 1.25)
        if face._wink_side == "R":
            e.blink_r = min(e.blink_r, shut)
        else:
            e.blink_l = min(e.blink_l, shut)


@scene("double_blink", duration=0.9, weight=4, in_reply=True)
class DoubleBlink(Scene):
    """Two quick blinks in a row — a very human little tic."""
    def eyes(self, face, p, e):
        for centre in (0.25, 0.65):
            d = abs(p - centre)
            if d < 0.13:
                shut = 1.0 - (1.0 - d / 0.13) ** 0.6
                e.blink_l = e.blink_r = min(e.blink_l, shut)


@scene("slow_blink", duration=2.0, weight=3, night_weight=5, needs_face=True,
       mood="happy", in_reply=True)
class SlowBlink(Scene):
    """A long, lazy blink — the cat-like sign of being content."""
    def eyes(self, face, p, e):
        s = math.sin(p * math.pi) ** 0.7
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.95 * s)
        e.squint = max(e.squint, 0.4 * s)


@scene("cross_eyes", duration=1.8, weight=2, in_reply=True)
class CrossEyes(Scene):
    """Pupils converge on her own nose — confusion, or just being silly."""
    def motion(self, face, p):
        s = math.sin(p * math.pi)
        face._pupil_converge = 58.0 * s
        face.target_tilt = 4.0 * math.sin(p * math.pi * 3)

    def eyes(self, face, p, e):
        e.widen = max(e.widen, 0.4 * math.sin(p * math.pi))


@scene("eye_roll", duration=1.5, weight=2, in_reply=True)
class EyeRoll(Scene):
    """A full, theatrical roll of the eyes."""
    def motion(self, face, p):
        a = p * math.pi * 2 - math.pi / 2
        r = math.sin(p * math.pi)
        face.pupil_ox = 26.0 * math.cos(a) * r
        face.pupil_oy = -22.0 * math.sin(a) * r - 8.0 * r


@scene("eye_twitch", duration=1.3, weight=2, in_reply=True)
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


@scene("remember", duration=3.0, weight=3, in_reply=True)
class Remember(Scene):
    """Eyes up and to the side, digging something out of memory."""
    def motion(self, face, p):
        s = math.sin(min(1.0, p * 1.3) * math.pi)
        face.pupil_ox = rf.lerp(face.pupil_ox, -24.0 * s, 0.12)
        face.pupil_oy = rf.lerp(face.pupil_oy, -26.0 * s, 0.12)
        face.target_tilt = -5.0 * s

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.3 * math.sin(p * math.pi))


@scene("peek", duration=2.6, weight=3, needs_face=True)
class Peek(Scene):
    """A sneaky glance left and right — is anyone actually watching?"""
    def motion(self, face, p):
        seq = [(-30, 0.30), (30, 0.62), (0, 1.0)]
        target = 0.0
        for val, until in seq:
            if p <= until:
                target = val
                break
        face.pupil_ox = rf.lerp(face.pupil_ox, target, 0.16)
        face.target_ox += target * 0.35

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.45)


@scene("staring", duration=4.5, weight=2, needs_face=True)
class Staring(Scene):
    """Holds your gaze without blinking, then gives in with a big blink."""
    def eyes(self, face, p, e):
        if p < 0.82:
            e.blink_l = e.blink_r = 1.0          # refuses to blink
            e.widen = max(e.widen, 0.5)
        else:
            s = math.sin((p - 0.82) / 0.18 * math.pi)
            e.blink_l = e.blink_r = min(e.blink_l, 1.0 - s)


@scene("bored", duration=5.0, weight=3, mood="sad")
class Bored(Scene):
    """Gaze wanders, head slowly sinks, then she catches herself."""
    def motion(self, face, p):
        sink = math.sin(min(1.0, p * 1.15) * math.pi)
        face.target_oy += 26.0 * sink
        face.target_tilt = 7.0 * math.sin(p * math.pi * 1.5)
        face.pupil_ox = rf.lerp(face.pupil_ox, 22.0 * math.sin(p * math.pi * 2.2), 0.06)
        face.pupil_oy = rf.lerp(face.pupil_oy, 12.0 * sink, 0.06)

    def eyes(self, face, p, e):
        e.droop = max(e.droop, 0.8 * math.sin(min(1.0, p * 1.15) * math.pi))
        e.squint = max(e.squint, 0.35)


@scene("smirk", duration=2.2, weight=3, in_reply=True)
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


@scene("fly", duration=6.0, weight=3, night_weight=1)
class Fly(Scene):
    """A fly buzzes around and she follows it, then it lands on her eye."""
    def _pos(self, face, p):
        t = p * self.duration
        x = face.face_cx + 250 * math.sin(t * 1.3) * math.cos(t * 0.45)
        y = face.face_cy - 40 + 120 * math.sin(t * 2.1)
        if p > 0.78:                                  # settles on her eye
            k = (p - 0.78) / 0.22
            x = rf.lerp(x, face.face_cx - 150, k)
            y = rf.lerp(y, face.face_cy - 30, k)
        return x, y

    def motion(self, face, p):
        fx, fy = self._pos(face, p)
        face.pupil_ox = rf.lerp(face.pupil_ox,
                                rf.clamp((fx - face.face_cx) * 0.11, -32, 32), 0.3)
        face.pupil_oy = rf.lerp(face.pupil_oy,
                                rf.clamp((fy - face.face_cy) * 0.14, -26, 26), 0.3)
        face.target_tilt = rf.clamp((fx - face.face_cx) * 0.012, -5, 5)

    def eyes(self, face, p, e):
        if p > 0.88:                                  # blinks it away
            e.blink_l = min(e.blink_l, 1.0 - abs(math.sin((p - 0.88) * 18)))
        e.squint = max(e.squint, 0.25)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.05, 0.05)
        if hold < 0.02:
            return
        x, y = self._pos(face, p)
        buzz = 2.5 * math.sin(p * self.duration * 40)
        body = pygame.Surface((32, 24), pygame.SRCALPHA)
        pygame.draw.ellipse(body, (*rf.PUPIL_DARK, int(255 * hold)),
                            pygame.Rect(7, 6, 18, 13))
        pygame.draw.ellipse(body, (*rf.EYE_INNER, int(150 * hold)),
                            pygame.Rect(0, 0, 15, 11))
        pygame.draw.ellipse(body, (*rf.EYE_INNER, int(150 * hold)),
                            pygame.Rect(17, 0, 15, 11))
        surf.blit(body, body.get_rect(center=(int(x), int(y + buzz))))


# ══ Bigger scenes with props ════════════════════════════════════════════════

@scene("look_around", duration=4.0, weight=4, night_weight=2)
class LookAround(Scene):
    """Glances around the room."""
    def motion(self, face, p):
        ph = p * math.pi * 2
        face.target_ox  += 46.0 * math.sin(ph)
        face.target_oy  += 12.0 * math.sin(ph * 2)
        face.pupil_ox    = rf.lerp(face.pupil_ox, 30.0 * math.sin(ph), 0.18)
        face.target_tilt = 5.0 * math.sin(ph)


@scene("stretch", duration=2.2, weight=2)
class Stretch(Scene):
    """Squeezes her eyes and stretches upward."""
    def motion(self, face, p):
        s = math.sin(p * math.pi)
        face.target_oy  -= 26.0 * s
        face.target_tilt = 6.0 * math.sin(p * math.pi * 2)

    def eyes(self, face, p, e):
        s = math.sin(p * math.pi)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.5 * s)
        e.squint = max(e.squint, 0.8 * s)


@scene("yawn", duration=3.0, weight=1, night_weight=5)
class Yawn(Scene):
    """A wide "aaah" that opens her mouth as speech would."""
    def motion(self, face, p):
        s = math.sin(p * math.pi)
        face.target_oy  -= 10.0 * s
        face.target_tilt = -3.0 * s
        face._mouth_drive = s ** 0.7

    def eyes(self, face, p, e):
        s = math.sin(p * math.pi)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.85 * s)
        e.squint = max(e.squint, s)


@scene("clock", duration=6.0, weight=3, night_weight=2)
class Clock(Scene):
    """The time floats up below the eyes and sinks back."""
    def eyes(self, face, p, e):
        e.widen = max(e.widen, 0.4 * math.sin(p * math.pi))

    def draw(self, face, surf, fcx, fcy, p):
        """Idle scene: the time floats up between the eyes, wobbles, sinks."""
        p    = p
        rise = math.sin(min(1.0, p * 1.4) * math.pi / 2)      # ease in
        fade = 1.0 if p < 0.75 else max(0.0, (1.0 - p) / 0.25)
        font = rf._get_font(84)
        txt  = time.strftime("%H:%M")
        img  = font.render(txt, True, rf.EYE_INNER)
        img.set_alpha(int(235 * fade))
        ang  = 9.0 * math.sin(p * math.pi * 4)
        img  = pygame.transform.rotate(img, ang)
        # settles below the eyes, well clear of them
        y    = fcy + 215 - 105 * rise + 8 * math.sin(p * math.pi * 6)
        rect = img.get_rect(center=(int(fcx), int(y)))
        # glow that follows the digits (a glow RECT would look like a card)
        glow = img.copy()
        glow.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
        glow.set_alpha(int(150 * fade))
        rf.bloom(surf, glow, rect.topleft, radius=7, passes=1, max_alpha=110)
        surf.blit(img, rect)


@scene("read_book", duration=11.0, weight=4, night_weight=3)
class ReadBook(Scene):
    """Reads a book, eyes scanning each line, one page flipping over."""
    def motion(self, face, p):
        hold = rf._prop_hold(p)
        line = (p * self.duration) % 2.4 / 2.4
        face.pupil_ox = rf.lerp(face.pupil_ox, (-22 + 44 * line) * hold, 0.25)
        face.pupil_oy = rf.lerp(face.pupil_oy, 30.0 * hold, 0.10)
        face.target_oy  += 10.0 * hold
        face.target_tilt = -2.0 * hold

    def draw(self, face, surf, fcx, fcy, p):
        """Idle scene: an open book at the bottom, one page turning."""
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        pw, ph = 156, 116
        y = rf.HEIGHT - 26 - (ph // 2) * hold + (1 - hold) * 90
        turn = p * self.duration % 4.5 / 4.5
        for side in (-1, 1):
            w = pw
            if side == 1 and 0.55 < turn < 0.8:        # right page flips over
                w = max(12, int(pw * abs(math.cos((turn - 0.55) / 0.25 * math.pi))))
            page = rf.gradient_block(w, ph, 9, rf.HAND_GRAD_TOP, rf.HAND_GRAD_BOTTOM)
            page = page.copy()
            for i in range(4):                          # lines of text
                ly = 22 + i * 21
                pygame.draw.rect(page, (*rf.PUPIL_DARK, 120),
                                 pygame.Rect(14, ly, max(4, w - 34), 5),
                                 border_radius=2)
            img  = pygame.transform.rotate(page, -7 * side)
            img.set_alpha(int(255 * hold))
            rect = img.get_rect(center=(int(fcx + side * (pw // 2 + 3)), int(y)))
            glow = img.copy()
            glow.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
            glow.set_alpha(int(90 * hold))
            rf.bloom(surf, glow, rect.topleft, radius=10, passes=1, max_alpha=80)
            surf.blit(img, rect)


@scene("phone", duration=9.0, weight=3, night_weight=2)
class Phone(Scene):
    """Scrolls something on a little handset."""
    def motion(self, face, p):
        hold = rf._prop_hold(p)
        scroll = math.sin(p * math.pi * 5) * 6
        face.pupil_ox = rf.lerp(face.pupil_ox, 20.0 * hold, 0.12)
        face.pupil_oy = rf.lerp(face.pupil_oy, (30.0 + scroll) * hold, 0.12)
        face.target_oy  += 8.0 * hold
        face.target_tilt = 3.0 * hold

    def draw(self, face, surf, fcx, fcy, p):
        """Idle scene: a little phone she scrolls through."""
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        bw, bh = 96, 168
        x = fcx + 120
        y = rf.HEIGHT - 20 - (bh // 2) * hold + (1 - hold) * 110
        body = pygame.Surface((bw, bh), pygame.SRCALPHA)
        pygame.draw.rect(body, (*rf.PUPIL_DARK, 255), body.get_rect(), border_radius=16)
        pygame.draw.rect(body, (*rf.EYE_MID, 220), body.get_rect(), 3, border_radius=16)
        scr  = rf.gradient_block(bw - 18, bh - 30, 8, rf.HAND_GRAD_TOP, rf.HAND_GRAD_BOTTOM)
        body.blit(scr, (9, 15))
        offset = int((p * self.duration * 34) % 26)
        for i in range(-1, 6):                          # content scrolling by
            ly = 22 + i * 26 + offset
            if 18 < ly < bh - 22:
                pygame.draw.rect(body, (*rf.PUPIL_DARK, 110),
                                 pygame.Rect(18, ly, bw - 36, 7), border_radius=3)
        body = pygame.transform.rotate(body, -12)
        body.set_alpha(int(255 * hold))
        rect = body.get_rect(center=(int(x), int(y)))
        glow = body.copy()
        glow.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
        glow.set_alpha(int(80 * hold))
        rf.bloom(surf, glow, rect.topleft, radius=10, passes=1, max_alpha=70)
        surf.blit(body, rect)


@scene("ball", duration=8.0, weight=4, night_weight=1)
class Ball(Scene):
    """Bounces a ball below her face and follows it with eyes and head."""
    def _xy(self, face, p):
        """Where the bouncing ball is right now (screen coords)."""
        t = p * self.duration
        hold = rf._prop_hold(p)
        x = face.face_cx + 250 * math.sin(t * 1.9) * hold
        # stays below the eyes so it never covers her face
        y = (rf.HEIGHT - 38) - abs(math.sin(t * 3.4)) * 110 * hold
        return x, y

    def motion(self, face, p):
        bx, by = self._xy(face, p)
        face.pupil_ox = rf.lerp(face.pupil_ox,
                                rf.clamp((bx - face.face_cx) * 0.10, -30, 30), 0.35)
        face.pupil_oy = rf.lerp(face.pupil_oy,
                                rf.clamp((by - face.face_cy) * 0.12, -22, 30), 0.35)
        face.target_ox  += rf.clamp((bx - face.face_cx) * 0.05, -20, 20)
        face.target_tilt = rf.clamp((face.face_cx - bx) * 0.02, -6, 6)

    def draw(self, face, surf, fcx, fcy, p):
        """Idle scene: a ball she bounces and follows with her eyes."""
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        x, y = self._xy(face, p)
        r = 36
        squash = 1.0 + 0.25 * max(0.0, (y - (rf.HEIGHT - 90)) / 45.0)   # flattens on impact
        ball = rf.gradient_block(int(r * 2 / squash), int(r * 2 * squash), r,
                              rf.EYE_GRAD_TOP, rf.EYE_GRAD_BOTTOM)
        ball = ball.copy()
        ball.set_alpha(int(255 * hold))
        rect = ball.get_rect(center=(int(x), int(y)))
        rf.draw_glow_circle(surf, rf.GLOW_COL, (int(x), int(y)), r, layers=3, max_alpha=45)
        surf.blit(ball, rect)


@scene("music", duration=11.0, weight=4, night_weight=3, mood="happy")
class Music(Scene):
    """Headphones on, notes drifting up, head bobbing to the beat."""
    def motion(self, face, p):
        hold = rf._prop_hold(p)
        beat = p * self.duration * 1.9                 # ~114 bpm
        face.target_oy  += 11.0 * math.sin(beat * 2 * math.pi) * hold
        face.target_tilt = 8.0 * math.sin(beat * math.pi) * hold
        face.pupil_ox = rf.lerp(face.pupil_ox,
                                14.0 * math.sin(beat * math.pi) * hold, 0.2)
        face.pupil_oy = rf.lerp(face.pupil_oy, -4.0 * hold, 0.1)

    def eyes(self, face, p, e):
        beat = p * self.duration * 1.9
        e.squint = max(e.squint, 0.45 + 0.25 * abs(math.sin(beat * math.pi)))

    def draw(self, face, surf, fcx, fcy, p):
        """Idle scene: headphones on, notes drifting up, bobbing to the beat."""
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        t    = p * self.duration
        drop = int((1.0 - hold) * 120)          # slides on from above

        # ── headband ──────────────────────────────────────────────────────
        # an ellipse arc whose ends meet the ear cups: centre (fcx, fcy-40),
        # semi-axes 310 x 110, so it peaks at fcy-150 and stays on screen
        band = pygame.Surface((640, 260), pygame.SRCALPHA)
        pygame.draw.arc(band, (*rf.EYE_MID, 255), pygame.Rect(10, 10, 620, 220),
                        0.0, math.pi, 17)
        band.set_alpha(int(255 * hold))
        brect = band.get_rect(center=(int(fcx), int(fcy) - 40 - drop))
        bglow = band.copy()
        bglow.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
        bglow.set_alpha(int(70 * hold))
        rf.bloom(surf, bglow, brect.topleft, radius=9, passes=1, max_alpha=70)
        surf.blit(band, brect)

        # ── ear cups ──────────────────────────────────────────────────────
        for side in (-1, 1):
            cw, ch = 74, 118
            cup = rf.gradient_block(cw, ch, 26, rf.HAND_GRAD_TOP, rf.HAND_GRAD_BOTTOM)
            cup = cup.copy()
            pygame.draw.rect(cup, (*rf.PUPIL_DARK, 90),
                             pygame.Rect(12, 20, cw - 24, ch - 40), border_radius=16)
            cup.set_alpha(int(255 * hold))
            rect = cup.get_rect(center=(int(fcx + side * 300),
                                        int(fcy) - 16 - drop))
            glow = cup.copy()
            glow.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
            glow.set_alpha(int(90 * hold))
            rf.bloom(surf, glow, rect.topleft, radius=10, passes=1, max_alpha=80)
            surf.blit(cup, rect)

        # ── notes drifting up beside her ──────────────────────────────────
        for i in range(6):
            side = -1 if i % 2 else 1
            ph   = (t * 0.55 + i * 0.37) % 1.0          # 0 → 1, then respawn
            if ph > 0.92:
                continue
            a = int(235 * hold * min(1.0, ph * 5) * (1.0 - ph))
            if a <= 6:
                continue
            nx = fcx + side * (232 + 46 * math.sin(ph * math.pi * 2 + i))
            ny = fcy + 50 - ph * 250
            note = rf._note_surface(24 + (i % 2) * 8)
            note = pygame.transform.rotate(note, 12 * math.sin(ph * 4 + i))
            note.set_alpha(a)
            surf.blit(note, note.get_rect(center=(int(nx), int(ny))))


# ══ Hands ═══════════════════════════════════════════════════════════════════

@scene("clap", duration=2.8, weight=3, mood="happy", needs_face=True,
       in_reply=True)
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


@scene("wave_both", duration=3.0, weight=2, mood="happy", needs_face=True,
       in_reply=True)
class WaveBoth(Scene):
    """Waves with both hands — unmistakably pleased to see you."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.18, 0.18)
        rock = 26.0 * math.sin(p * self.duration * 6.0)
        h.l = (-290, 60 + 320 * (1 - hold), -rock)
        h.r = ( 290, 60 + 320 * (1 - hold),  rock)

    def motion(self, face, p):
        face.target_tilt = 4.0 * math.sin(p * self.duration * 6.0)


@scene("peekaboo", duration=3.4, weight=3, mood="happy", needs_face=True)
class Peekaboo(Scene):
    """Hides behind her hands, then throws them open: a kuku!"""
    def hands(self, face, p, h):
        if p < 0.45:                       # covering
            k = min(1.0, p / 0.18)
        elif p < 0.62:                     # peeking through
            k = 1.0
        else:                              # thrown open
            k = max(0.0, 1.0 - (p - 0.62) / 0.28)
        h.l = (rf.lerp(-330, -150, k), rf.lerp(420, -30, k), rf.lerp(0, -8, k))
        h.r = (rf.lerp( 330,  150, k), rf.lerp(420, -30, k), rf.lerp(0,  8, k))

    def eyes(self, face, p, e):
        # the hands only half cover an eye this size, so she shuts them
        # while hidden — that is what sells it — and pops them open wide
        if 0.2 < p < 0.62:
            e.blink_l = e.blink_r = 0.0
        elif 0.62 <= p < 0.85:
            k = (p - 0.62) / 0.23
            e.blink_l = e.blink_r = min(1.0, k * 1.6)
            e.widen = max(e.widen, 0.95 * (1.0 - k))


@scene("rub_eyes", duration=3.2, weight=3, night_weight=5)
class RubEyes(Scene):
    """Rubs her eyes with both fists — sleepy, or just woke up."""
    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.2, 0.2)
        a = p * self.duration * 4.0
        h.pose_l = h.pose_r = "fist"
        h.l = (-150 + 16 * math.cos(a), -20 + 14 * math.sin(a) + 400 * (1 - hold), 0)
        h.r = ( 150 - 16 * math.cos(a), -20 + 14 * math.sin(a) + 400 * (1 - hold), 0)

    def eyes(self, face, p, e):
        hold = rf._prop_hold(p, 0.2, 0.2)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.8 * hold)
        e.squint = max(e.squint, 0.7 * hold)


@scene("scratch_head", duration=3.0, weight=3, in_reply=True)
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


@scene("chin_rest", duration=5.0, weight=3, in_reply=True)
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


@scene("salute", duration=2.6, weight=2, mood="happy", needs_face=True,
       in_reply=True)
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


@scene("please", duration=3.2, weight=2, mood="love", needs_face=True,
       in_reply=True)
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


# ══ The screen itself as a medium ═══════════════════════════════════════════
# Ambient, wallpaper-like scenes. They run longer than the others and are
# weighted up at night, when the room is dark and the panel is the only
# thing giving light.

def _fade(p, rise=0.1, fall=0.15):
    return rf._prop_hold(p, rise, fall)


@scene("rain", duration=13.0, weight=2, night_weight=4)
class Rain(Scene):
    """Rain running down the glass; she watches a drop now and then."""
    N = 44

    def __init__(self):
        rnd = random.Random(7)
        self.drops = [(rnd.random(), rnd.random(), rnd.uniform(0.7, 1.6),
                       rnd.uniform(10, 26)) for _ in range(self.N)]

    def motion(self, face, p):
        hold = _fade(p)
        # eyes wander up after the drops
        face.pupil_oy = rf.lerp(face.pupil_oy, -14.0 * hold, 0.04)
        face.pupil_ox = rf.lerp(face.pupil_ox,
                                20.0 * math.sin(p * math.pi * 1.5) * hold, 0.04)

    def draw(self, face, surf, fcx, fcy, p):
        hold = _fade(p)
        if hold < 0.02:
            return
        t = p * self.duration
        col = rf.TEAR_COL
        for x0, y0, speed, length in self.drops:
            y = ((y0 + t * speed * 0.42) % 1.25) * rf.HEIGHT - 60
            x = x0 * rf.WIDTH
            a = int(190 * hold)
            line = pygame.Surface((3, int(length)), pygame.SRCALPHA)
            line.fill((*col, a))
            surf.blit(line, (int(x), int(y)))
            pygame.draw.circle(surf, (*col, a), (int(x) + 1, int(y + length)), 2)


@scene("snow", duration=14.0, weight=2, night_weight=4)
class Snow(Scene):
    """Big soft flakes drifting down past her."""
    N = 60

    def __init__(self):
        rnd = random.Random(11)
        self.flakes = [(rnd.random(), rnd.random(), rnd.uniform(0.18, 0.5),
                        rnd.uniform(2.5, 6.0), rnd.uniform(0, 6.3))
                       for _ in range(self.N)]

    def motion(self, face, p):
        hold = _fade(p)
        face.pupil_oy = rf.lerp(face.pupil_oy, -8.0 * hold, 0.03)
        face.target_tilt = 3.0 * math.sin(p * math.pi * 2) * hold

    def draw(self, face, surf, fcx, fcy, p):
        hold = _fade(p)
        if hold < 0.02:
            return
        t = p * self.duration
        for x0, y0, speed, r, ph in self.flakes:
            y = ((y0 + t * speed * 0.14) % 1.15) * rf.HEIGHT - 30
            x = (x0 * rf.WIDTH + 26 * math.sin(t * 0.7 + ph)) % rf.WIDTH
            a = int(200 * hold * (0.5 + 0.5 * math.sin(ph + t)))
            fl = pygame.Surface((int(r * 2) + 2, int(r * 2) + 2), pygame.SRCALPHA)
            pygame.draw.circle(fl, (*rf.TEETH_COL, a), (int(r) + 1, int(r) + 1), int(r))
            surf.blit(fl, (int(x), int(y)))


@scene("leaves", duration=13.0, weight=2, night_weight=1)
class Leaves(Scene):
    """Autumn leaves tumbling across the screen."""
    N = 16

    def __init__(self):
        rnd = random.Random(23)
        self.leaves = [(rnd.random(), rnd.random(), rnd.uniform(0.3, 0.7),
                        rnd.uniform(10, 17), rnd.uniform(0, 6.3),
                        rnd.uniform(1.5, 4.0)) for _ in range(self.N)]

    def draw(self, face, surf, fcx, fcy, p):
        hold = _fade(p)
        if hold < 0.02:
            return
        t = p * self.duration
        for x0, y0, speed, size, ph, spin in self.leaves:
            y = ((y0 + t * speed * 0.14) % 1.2) * rf.HEIGHT - 40
            x = (x0 * rf.WIDTH + 70 * math.sin(t * 0.5 + ph)) % rf.WIDTH
            leaf = pygame.Surface((int(size * 2), int(size * 2)), pygame.SRCALPHA)
            pygame.draw.ellipse(leaf, (*rf.EYE_OUTER, int(220 * hold)),
                                pygame.Rect(0, int(size * 0.5), int(size * 2), int(size)))
            pygame.draw.line(leaf, (*rf.PUPIL_DARK, int(160 * hold)),
                             (2, int(size)), (int(size * 2) - 2, int(size)), 2)
            leaf = pygame.transform.rotate(leaf, math.degrees(t * spin + ph))
            surf.blit(leaf, leaf.get_rect(center=(int(x), int(y))))


@scene("dvd_logo", duration=14.0, weight=2, night_weight=3)
class DvdLogo(Scene):
    """The screensaver everyone has waited to see hit the corner."""
    _font = None

    def _pos(self, p):
        w, h = 168, 76
        sx, sy = 168.0, 121.0                      # px per second
        t = p * self.duration
        span_x, span_y = rf.WIDTH - w, rf.HEIGHT - h
        x = abs(((t * sx + 40) % (2 * span_x)) - span_x)
        y = abs(((t * sy + 30) % (2 * span_y)) - span_y)
        bounces = int((t * sx + 40) // span_x) + int((t * sy + 30) // span_y)
        return x, y, w, h, bounces

    def draw(self, face, surf, fcx, fcy, p):
        hold = _fade(p, 0.08, 0.1)
        if hold < 0.02:
            return
        if DvdLogo._font is None:
            DvdLogo._font = rf._get_font(46)
        x, y, w, h, bounces = self._pos(p)
        palette = (rf.EYE_INNER, rf.EYE_MID, rf.TEAR_COL, rf.HEART_COL,
                   rf.STAR_COL)
        col = palette[bounces % len(palette)]
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(box, (*col, int(70 * hold)), box.get_rect(), border_radius=14)
        pygame.draw.rect(box, (*col, int(230 * hold)), box.get_rect(), 3,
                         border_radius=14)
        txt = DvdLogo._font.render("LUNA", True, col)
        txt.set_alpha(int(255 * hold))
        box.blit(txt, txt.get_rect(center=(w // 2, h // 2)))
        surf.blit(box, (int(x), int(y)))

    def motion(self, face, p):
        x, y, w, h, _ = self._pos(p)
        hold = _fade(p, 0.08, 0.1)
        face.pupil_ox = rf.lerp(face.pupil_ox,
                                rf.clamp((x + w / 2 - face.face_cx) * 0.09,
                                         -30, 30) * hold, 0.3)
        face.pupil_oy = rf.lerp(face.pupil_oy,
                                rf.clamp((y + h / 2 - face.face_cy) * 0.09,
                                         -24, 24) * hold, 0.3)


@scene("matrix", duration=12.0, weight=2, night_weight=4)
class Matrix(Scene):
    """Glyphs raining down the background, green-screen style."""
    COLS = 16
    _glyphs = None

    def __init__(self):
        rnd = random.Random(5)
        self.cols = [(rnd.random(), rnd.uniform(0.5, 1.4), rnd.randint(6, 12))
                     for _ in range(self.COLS)]

    def _build(self):
        font = rf._get_font(26)
        # plain ASCII only: the system font has no katakana and renders
        # missing glyphs as empty boxes
        chars = "01234567890ABCDEFGHJKLMNPQRSTUVWXYZ<>*+=/%#"
        Matrix._glyphs = [font.render(c, True, rf.EYE_INNER) for c in chars]

    def draw_bg(self, face, surf, fcx, fcy, p):
        hold = _fade(p)
        if hold < 0.02:
            return
        if Matrix._glyphs is None:
            self._build()
        t = p * self.duration
        step = rf.WIDTH // self.COLS
        for i, (y0, speed, length) in enumerate(self.cols):
            head = ((y0 + t * speed * 0.22) % 1.3) * rf.HEIGHT
            x = i * step + 6
            for j in range(length):
                y = head - j * 28
                if y < -28 or y > rf.HEIGHT:
                    continue
                g = Matrix._glyphs[(i * 7 + j + int(t * 3)) % len(Matrix._glyphs)]
                # set_alpha on the cached surface — copying ~190 glyphs per
                # frame was the expensive part
                g.set_alpha(int(hold * 235 * (1.0 - j / length) ** 1.5))
                surf.blit(g, (x, int(y)))


@scene("hyperspace", duration=11.0, weight=2, night_weight=3)
class Hyperspace(Scene):
    """Stars streaming past — she is going somewhere, apparently."""
    N = 70

    def __init__(self):
        rnd = random.Random(3)
        self.stars = [(rnd.uniform(0, 6.283), rnd.random(), rnd.uniform(0.6, 1.5))
                      for _ in range(self.N)]

    def draw_bg(self, face, surf, fcx, fcy, p):
        hold = _fade(p)
        if hold < 0.02:
            return
        t = p * self.duration
        cx, cy = rf.WIDTH // 2, rf.HEIGHT // 2
        for ang, phase, speed in self.stars:
            d = ((phase + t * speed * 0.22) % 1.0)
            r0 = 26 + d * d * 620
            r1 = r0 + 12 + d * 52
            a = int(230 * hold * min(1.0, d * 3) * (1.0 - d))
            if a <= 5:
                continue
            ca, sa = math.cos(ang), math.sin(ang)
            pygame.draw.line(surf, (*rf.EYE_INNER, a),
                             (cx + ca * r0, cy + sa * r0),
                             (cx + ca * r1, cy + sa * r1), 2)


@scene("glitch", duration=2.6, weight=2, night_weight=2, in_reply=True)
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


# ══ Everyday props ══════════════════════════════════════════════════════════

@scene("coffee", duration=10.0, weight=4, night_weight=1, mood="happy",
       hours=(5, 18))
class Coffee(Scene):
    """A mug of something hot: steam curls up, and she takes a sip."""
    def _sip(self, p):
        """0 → resting, 1 → mug at her lips."""
        if 0.35 < p < 0.62:
            return math.sin((p - 0.35) / 0.27 * math.pi)
        return 0.0

    def hands(self, face, p, h):
        hold = rf._prop_hold(p)
        sip = self._sip(p)
        h.r = (120, rf.lerp(230, 130, sip) + 300 * (1 - hold), -14 - 10 * sip)

    def motion(self, face, p):
        sip = self._sip(p)
        face.target_oy += 8.0 * sip
        face.pupil_oy = rf.lerp(face.pupil_oy, 16.0 * rf._prop_hold(p), 0.08)

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.7 * self._sip(p))

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        sip = self._sip(p)
        mw, mh = 96, 92
        x = fcx + 28
        y = fcy + rf.lerp(198, 104, sip) + 300 * (1 - hold)
        mug = rf.gradient_block(mw, mh, 14, rf.HAND_GRAD_TOP, rf.HAND_GRAD_BOTTOM)
        mug = mug.copy()
        pygame.draw.ellipse(mug, (*rf.PUPIL_DARK, 210),
                            pygame.Rect(10, 4, mw - 20, 18))       # the drink
        img = pygame.transform.rotate(mug, -22 * sip)
        rect = img.get_rect(center=(int(x), int(y)))
        pygame.draw.arc(surf, rf.EYE_MID,
                        pygame.Rect(rect.right - 12, rect.y + 22, 40, 46),
                        math.radians(-70), math.radians(70), 8)    # handle
        glow = img.copy()
        glow.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
        glow.set_alpha(int(80 * hold))
        rf.bloom(surf, glow, rect.topleft, radius=10, passes=1, max_alpha=70)
        surf.blit(img, rect)

        t = p * self.duration
        for i in range(3):                                          # steam
            for j in range(5):
                sy = rect.top - 14 - j * 17 - (t * 26 + i * 40) % 30
                if sy < fcy - 40:
                    continue
                a = int(150 * hold * (1.0 - j / 5.0))
                sx = rect.centerx - 26 + i * 26 + 11 * math.sin(t * 2.2 + j * 0.9 + i)
                pygame.draw.circle(surf, (*rf.TEETH_COL, a), (int(sx), int(sy)), 5)


@scene("camera", duration=6.5, weight=3, night_weight=2, mood="happy",
       needs_face=True)
class Camera(Scene):
    """Takes your picture — and the flash goes off in your face."""
    FLASH = 0.62

    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.15, 0.15)
        h.l = (-150, 20 + 400 * (1 - hold), 18)
        h.r = ( 150, 20 + 400 * (1 - hold), -18)

    def eyes(self, face, p, e):
        d = p - self.FLASH
        if -0.06 < d < 0.16:                       # blinks at her own flash
            e.blink_l = e.blink_r = min(e.blink_l, abs(d) / 0.16)
        e.widen = max(e.widen, 0.4 * rf._prop_hold(p, 0.15, 0.15))

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.15, 0.15)
        if hold < 0.02:
            return
        bw, bh = 250, 150
        y = fcy - 10 + 320 * (1 - hold)
        body = pygame.Surface((bw, bh), pygame.SRCALPHA)
        pygame.draw.rect(body, (*rf.PUPIL_DARK, 245), body.get_rect(),
                         border_radius=18)
        pygame.draw.rect(body, (*rf.EYE_MID, 235), body.get_rect(), 4,
                         border_radius=18)
        pygame.draw.circle(body, (*rf.EYE_MID, 235), (bw // 2, bh // 2), 46, 5)
        pygame.draw.circle(body, (*rf.EYE_INNER, 150), (bw // 2, bh // 2), 30)
        pygame.draw.circle(body, (*rf.PUPIL_DARK, 255), (bw // 2, bh // 2), 18)
        # the flash bulb lights up just before it fires
        lit = 255 if abs(p - self.FLASH) < 0.05 else 110
        pygame.draw.rect(body, (*rf.TEETH_COL, lit),
                         pygame.Rect(bw - 62, 16, 34, 20), border_radius=6)
        body.set_alpha(int(255 * hold))
        surf.blit(body, body.get_rect(center=(int(fcx), int(y))))

    def post(self, face, screen, p):
        d = abs(p - self.FLASH)
        if d < 0.055:                              # the flash itself
            ov = pygame.Surface(screen.get_size())
            ov.fill((255, 255, 255))
            ov.set_alpha(int(235 * (1.0 - d / 0.055)))
            screen.blit(ov, (0, 0))


@scene("binoculars", duration=8.0, weight=3, night_weight=2)
class Binoculars(Scene):
    """Scans the room through a pair of binoculars."""
    def _pan(self, p):
        return math.sin(p * math.pi * 2.2)

    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.15, 0.15)
        pan = self._pan(p) * 26
        h.l = (-232 + pan, 70 + 360 * (1 - hold), 30)
        h.r = ( 232 + pan, 70 + 360 * (1 - hold), -30)

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.15, 0.15)
        pan = self._pan(p)
        face.target_ox += 26.0 * pan * hold
        face.target_tilt = 4.0 * pan * hold
        face.pupil_ox = rf.lerp(face.pupil_ox, 18.0 * pan * hold, 0.2)

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.3 * rf._prop_hold(p, 0.15, 0.15))

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.15, 0.15)
        if hold < 0.02:
            return
        pan = self._pan(p) * 26
        y = int(fcy - 30 + 340 * (1 - hold))
        r = 118
        for side in (-1, 1):
            x = int(fcx + side * 150 + pan)
            lens = pygame.Surface((r * 2 + 12, r * 2 + 12), pygame.SRCALPHA)
            c = (r + 6, r + 6)
            pygame.draw.circle(lens, (*rf.PUPIL_DARK, 70), c, r)       # tinted glass
            pygame.draw.circle(lens, (*rf.EYE_MID, 240), c, r, 12)     # rim
            pygame.draw.circle(lens, (*rf.TEETH_COL, 90), c, r - 16, 3)
            lens.set_alpha(int(255 * hold))
            surf.blit(lens, lens.get_rect(center=(x, y)))
        pygame.draw.rect(surf, rf.EYE_MID,
                         pygame.Rect(int(fcx - 34 + pan), y - 13, 68, 26),
                         border_radius=8)                              # bridge


@scene("spinner", duration=7.5, weight=3, night_weight=2)
class Spinner(Scene):
    """A fidget spinner, spinning down. Hypnotic."""
    def motion(self, face, p):
        hold = rf._prop_hold(p)
        face.pupil_oy = rf.lerp(face.pupil_oy, 26.0 * hold, 0.1)

    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.25 * rf._prop_hold(p))

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        t = p * self.duration
        speed = 14.0 * (1.0 - p * 0.65)                # spins down over time
        ang = t * speed
        cx, cy = int(fcx), int(fcy + 148 + 300 * (1 - hold))
        lobe_r, arm = 40, 66
        body = pygame.Surface((240, 240), pygame.SRCALPHA)
        bc = (120, 120)
        for i in range(3):
            a = ang + i * 2.0944
            lx = bc[0] + math.cos(a) * arm
            ly = bc[1] + math.sin(a) * arm
            pygame.draw.line(body, (*rf.EYE_MID, 235), bc, (lx, ly), 26)
            pygame.draw.circle(body, (*rf.EYE_OUTER, 245), (int(lx), int(ly)), lobe_r)
            pygame.draw.circle(body, (*rf.EYE_INNER, 200), (int(lx), int(ly)),
                               lobe_r - 12)
        pygame.draw.circle(body, (*rf.EYE_MID, 255), bc, 26)
        pygame.draw.circle(body, (*rf.PUPIL_DARK, 255), bc, 13)
        body.set_alpha(int(255 * hold))
        surf.blit(body, body.get_rect(center=(cx, cy)))


@scene("yoyo", duration=8.0, weight=3, night_weight=2)
class Yoyo(Scene):
    """Walks the dog with a yo-yo; her eyes go up and down with it."""
    def _drop(self, p):
        return abs(math.sin(p * self.duration * 1.15))

    def hands(self, face, p, h):
        hold = rf._prop_hold(p, 0.12, 0.12)
        h.r = (150, -60 + 420 * (1 - hold), -16)

    def motion(self, face, p):
        hold = rf._prop_hold(p, 0.12, 0.12)
        face.pupil_oy = rf.lerp(face.pupil_oy,
                                (-14 + 42 * self._drop(p)) * hold, 0.3)
        face.pupil_ox = rf.lerp(face.pupil_ox, 16.0 * hold, 0.1)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.12, 0.12)
        if hold < 0.02:
            return
        top = (int(fcx + 150), int(fcy - 10 + 420 * (1 - hold)))
        y = top[1] + 40 + self._drop(p) * 300
        pygame.draw.line(surf, (*rf.TEETH_COL, int(200 * hold)),
                         top, (top[0], int(y)), 3)
        r = 40
        disc = rf.gradient_block(r * 2, r * 2, r, rf.EYE_GRAD_TOP, rf.EYE_GRAD_BOTTOM)
        disc = disc.copy()
        pygame.draw.circle(disc, (*rf.PUPIL_DARK, 220), (r, r), 9)
        disc.set_alpha(int(255 * hold))
        rf.draw_glow_circle(surf, rf.GLOW_COL, (top[0], int(y)), r,
                            layers=3, max_alpha=40)
        surf.blit(disc, disc.get_rect(center=(top[0], int(y))))


@scene("hourglass", duration=10.0, weight=3, night_weight=3)
class Hourglass(Scene):
    """Watches the sand run out, then flips it over."""
    FLIP = 0.62

    def _phase(self, p):
        """(fill 0..1 of the top bulb, flip angle)."""
        if p < self.FLIP:
            return 1.0 - p / self.FLIP, 0.0
        if p < self.FLIP + 0.12:                    # flipping
            k = (p - self.FLIP) / 0.12
            return k, 180.0 * k
        k = (p - self.FLIP - 0.12) / max(0.01, 1.0 - self.FLIP - 0.12)
        return 1.0 - k, 180.0

    def motion(self, face, p):
        hold = rf._prop_hold(p)
        face.pupil_oy = rf.lerp(face.pupil_oy, 22.0 * hold, 0.08)

    def hands(self, face, p, h):
        if self.FLIP - 0.06 < p < self.FLIP + 0.18:
            h.r = (95, 150, -20)

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        fill, flip = self._phase(p)
        w, h = 124, 172
        glass = pygame.Surface((w, h), pygame.SRCALPHA)
        top = [(8, 8), (w - 8, 8), (w // 2 + 8, h // 2), (w // 2 - 8, h // 2)]
        bot = [(8, h - 8), (w - 8, h - 8), (w // 2 + 8, h // 2), (w // 2 - 8, h // 2)]
        # sand in the upper bulb, drawn as a shrinking wedge
        if fill > 0.02:
            k = fill
            pygame.draw.polygon(glass, (*rf.EYE_OUTER, 235), [
                (w // 2 - (w // 2 - 8) * k, h // 2 - (h // 2 - 8) * k),
                (w // 2 + (w // 2 - 8) * k, h // 2 - (h // 2 - 8) * k),
                (w // 2 + 8, h // 2), (w // 2 - 8, h // 2)])
        # and the pile below
        if fill < 0.98:
            k = 1.0 - fill
            pygame.draw.polygon(glass, (*rf.EYE_OUTER, 235), [
                (w // 2 - (w // 2 - 10) * k, h - 10),
                (w // 2 + (w // 2 - 10) * k, h - 10),
                (w // 2, h - 10 - 62 * k)])
        pygame.draw.polygon(glass, (*rf.EYE_MID, 245), top, 5)
        pygame.draw.polygon(glass, (*rf.EYE_MID, 245), bot, 5)
        pygame.draw.rect(glass, (*rf.EYE_MID, 245), pygame.Rect(0, 0, w, 10),
                         border_radius=5)
        pygame.draw.rect(glass, (*rf.EYE_MID, 245), pygame.Rect(0, h - 10, w, 10),
                         border_radius=5)
        if 0.03 < fill < 0.97:                       # the trickle
            t = p * self.duration
            for i in range(5):
                gy = h // 2 + ((t * 170 + i * 21) % 80)
                pygame.draw.rect(glass, (*rf.EYE_INNER, 230),
                                 pygame.Rect(w // 2 - 2, int(gy), 4, 7))
        img = pygame.transform.rotate(glass, flip)
        img.set_alpha(int(255 * hold))
        surf.blit(img, img.get_rect(center=(int(fcx), int(fcy + 152 + 320 * (1 - hold)))))


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


@scene("laugh", duration=3.4, weight=3, mood="happy", needs_face=True,
       in_reply=True)
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


@scene("sigh", duration=3.2, weight=3, in_reply=True)
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


@scene("impatient", duration=4.0, weight=3, in_reply=True)
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


@scene("think_bubble", duration=4.5, weight=3, in_reply=True)
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


@scene("proud", duration=3.2, weight=2, mood="excited", needs_face=True,
       in_reply=True)
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


@scene("shy", duration=3.6, weight=3, mood="love", needs_face=True,
       in_reply=True)
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


@scene("behind_you", duration=3.0, weight=2, needs_face=True)
class BehindYou(Scene):
    """Something moved over there — she snaps round to look."""
    def motion(self, face, p):
        if p < 0.14:
            k = p / 0.14
        elif p < 0.62:
            k = 1.0
        else:
            k = max(0.0, 1.0 - (p - 0.62) / 0.38)
        face.target_ox  += 64.0 * k
        face.target_tilt = -11.0 * k
        face.pupil_ox = rf.lerp(face.pupil_ox, 32.0 * k, 0.4)

    def eyes(self, face, p, e):
        if 0.1 < p < 0.55:
            e.widen = max(e.widen, 0.95)


@scene("scared", duration=3.0, weight=2, in_reply=True)
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


@scene("anger_cools", duration=4.2, weight=2, mood="angry")
class AngerCools(Scene):
    """Fumes, then lets it go."""
    def motion(self, face, p):
        heat = max(0.0, 1.0 - p * 1.45)             # dies down over the scene
        t = p * self.duration
        face.target_ox  += 16.0 * math.sin(t * 16.0) * heat
        face.target_tilt = 7.0 * math.sin(t * 11.0) * heat
        if p > 0.72:
            face._mouth_drive = 0.3 * math.sin((p - 0.72) / 0.28 * math.pi)

    def eyes(self, face, p, e):
        heat = max(0.0, 1.0 - p * 1.45)
        e.squint = max(e.squint, 0.8 * heat)

    def draw(self, face, surf, fcx, fcy, p):
        if p > 0.72:                                # the relieved breath out
            _puff(surf, fcx, fcy + 180, p * self.duration,
                  math.sin((p - 0.72) / 0.28 * math.pi), spread=1.4)


@scene("dance", duration=6.0, weight=3, mood="happy", needs_face=True,
       in_reply=True)
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


@scene("tear_wipe", duration=5.0, weight=2, mood="sad", in_reply=True)
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


@scene("relief", duration=3.4, weight=2, mood="happy", in_reply=True)
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


@scene("curious", duration=3.6, weight=4, needs_face=True, in_reply=True)
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


# ══ Occasions: the calendar and the clock ═══════════════════════════════════
# These need no interaction at all — they simply happen on the right day or
# at the right hour, which is most of their charm.

from config import BIRTHDAYS


def _burst(surf, cx, cy, t, hue, hold, n=18, spread=150):
    """One firework: a ring of sparks falling away."""
    if t < 0 or t > 1:
        return
    for i in range(n):
        a = i * (6.283 / n)
        d = t ** 0.6
        x = cx + math.cos(a) * spread * d
        y = cy + math.sin(a) * spread * d + 70 * t * t
        al = int(240 * hold * (1.0 - t))
        if al <= 5:
            continue
        pygame.draw.circle(surf, (*hue, al), (int(x), int(y)), max(2, int(6 * (1 - t))))


@scene("morning", duration=8.0, weight=5, hours=(5, 10), mood="happy")
class Morning(Scene):
    """The sun comes up at the bottom of the screen and she wakes with it."""
    def motion(self, face, p):
        wake = rf.clamp(p * 2.2, 0, 1)
        face.target_oy -= 14.0 * wake
        if p < 0.3:
            face.target_tilt = 6.0 * (1 - p / 0.3)

    def eyes(self, face, p, e):
        wake = rf.clamp(p * 2.4, 0, 1)
        e.blink_l = e.blink_r = min(e.blink_l, 0.15 + 0.85 * wake)
        e.squint = max(e.squint, 0.7 * (1 - wake))

    def draw_bg(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.1, 0.15)
        if hold < 0.02:
            return
        rise = rf.clamp(p * 1.6, 0, 1)
        cy = rf.HEIGHT + 90 - 150 * rise
        for i in range(7):                        # rays
            a = (i / 7.0) * math.pi + p * 0.25
            x2 = rf.WIDTH // 2 + math.cos(a) * 520
            y2 = cy - math.sin(a) * 520
            pygame.draw.line(surf, (*rf.EYE_OUTER, int(45 * hold)),
                             (rf.WIDTH // 2, int(cy)), (int(x2), int(y2)), 16)
        pygame.draw.circle(surf, (*rf.EYE_MID, int(200 * hold)),
                           (rf.WIDTH // 2, int(cy)), 130)
        pygame.draw.circle(surf, (*rf.EYE_INNER, int(235 * hold)),
                           (rf.WIDTH // 2, int(cy)), 104)


@scene("sunset", duration=9.0, weight=5, hours=(18, 21))
class Sunset(Scene):
    """Warm bands of evening sky behind her, the sun going down."""
    def eyes(self, face, p, e):
        e.squint = max(e.squint, 0.35 * rf._prop_hold(p))

    def draw_bg(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.12, 0.15)
        if hold < 0.02:
            return
        sink = rf.clamp(p * 1.2, 0, 1)
        cy = rf.HEIGHT - 40 + 120 * sink
        for i in range(6):                        # sky bands
            a = int(26 * hold * (1.0 - i / 7.0))
            band = pygame.Surface((rf.WIDTH, 34), pygame.SRCALPHA)
            band.fill((*rf.EYE_OUTER, a))
            surf.blit(band, (0, int(cy) - 200 + i * 36))
        pygame.draw.circle(surf, (*rf.EYE_OUTER, int(210 * hold)),
                           (rf.WIDTH // 2, int(cy)), 118)


@scene("night_sky", duration=12.0, weight=4, hours=(21, 5))
class NightSky(Scene):
    """A moon and a sky full of stars, quietly twinkling."""
    def __init__(self):
        rnd = random.Random(31)
        self.stars = [(rnd.random(), rnd.random() * 0.75, rnd.uniform(0, 6.3),
                       rnd.uniform(1.5, 3.4)) for _ in range(46)]

    def motion(self, face, p):
        face.pupil_oy = rf.lerp(face.pupil_oy, -16.0 * rf._prop_hold(p), 0.05)

    def draw_bg(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        t = p * self.duration
        for x, y, ph, r in self.stars:
            a = int(210 * hold * (0.45 + 0.55 * math.sin(t * 1.7 + ph)))
            if a <= 5:
                continue
            pygame.draw.circle(surf, (*rf.TEETH_COL, a),
                               (int(x * rf.WIDTH), int(y * rf.HEIGHT)), int(r))
        mx, my = rf.WIDTH - 120, 92
        pygame.draw.circle(surf, (*rf.EYE_INNER, int(225 * hold)), (mx, my), 52)
        pygame.draw.circle(surf, (0, 0, 0), (mx - 24, my - 12), 48)   # crescent


@scene("season", duration=8.0, weight=2)
class Season(Scene):
    """A small emblem of the time of year, drifting past."""
    def _motif(self):
        m = time.localtime().tm_mon
        if m in (12, 1, 2):
            return "snow"
        if m in (3, 4, 5):
            return "flower"
        if m in (6, 7, 8):
            return "sun"
        return "leaf"

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        kind = self._motif()
        x = 90 + p * (rf.WIDTH - 180)
        y = 90 + 30 * math.sin(p * math.pi * 3)
        a = int(235 * hold)
        t = p * self.duration
        if kind == "snow":
            for i in range(3):
                ang = t * 0.8 + i * (math.pi / 3)
                dx, dy = math.cos(ang) * 30, math.sin(ang) * 30
                pygame.draw.line(surf, (*rf.TEETH_COL, a),
                                 (x - dx, y - dy), (x + dx, y + dy), 5)
        elif kind == "flower":
            for i in range(6):
                ang = t * 0.5 + i * (math.pi / 3)
                pygame.draw.circle(surf, (*rf.HEART_COL, a),
                                   (int(x + math.cos(ang) * 22),
                                    int(y + math.sin(ang) * 22)), 13)
            pygame.draw.circle(surf, (*rf.STAR_COL, a), (int(x), int(y)), 11)
        elif kind == "sun":
            for i in range(8):
                ang = t * 0.6 + i * (math.pi / 4)
                pygame.draw.line(surf, (*rf.STAR_COL, a), (x, y),
                                 (x + math.cos(ang) * 38, y + math.sin(ang) * 38), 5)
            pygame.draw.circle(surf, (*rf.STAR_COL, a), (int(x), int(y)), 20)
        else:
            leaf = pygame.Surface((54, 30), pygame.SRCALPHA)
            pygame.draw.ellipse(leaf, (*rf.EYE_OUTER, a), leaf.get_rect())
            pygame.draw.line(leaf, (*rf.PUPIL_DARK, a), (3, 15), (51, 15), 3)
            leaf = pygame.transform.rotate(leaf, math.degrees(t * 1.6))
            surf.blit(leaf, leaf.get_rect(center=(int(x), int(y))))


@scene("hour_chime", duration=9.0, weight=0, forced=True, mood="happy")
class HourChime(Scene):
    """Counts the last seconds down to the full hour, then announces it."""
    _font = None

    def available(self):
        secs = 3600 - (time.time() % 3600)
        return 5.0 < secs < 9.0          # so the countdown lands on the hour

    def motion(self, face, p):
        if p > 0.45:
            face.target_oy += 10.0 * math.sin((p - 0.45) * 22)

    def draw(self, face, surf, fcx, fcy, p):
        if HourChime._font is None:
            HourChime._font = rf._get_font(120)
        # 3-2-1 over the first ~45 % of the scene, then the new hour holds
        # for the rest of it (it used to appear only in the last moment)
        left = 3.2 - p * self.duration * 0.80
        if left > 0:                               # 3 … 2 … 1
            n = int(left) + 1
            k = left - int(left)
            txt = HourChime._font.render(str(min(3, n)), True, rf.EYE_INNER)
            txt.set_alpha(int(235 * k))
            surf.blit(txt, txt.get_rect(center=(int(fcx), int(fcy - 140))))
        else:                                      # the new hour itself
            k = rf.clamp(-left * 2.5, 0, 1)      # fades IN once the count ends
            txt = HourChime._font.render(time.strftime("%H:00"), True, rf.EYE_MID)
            txt.set_alpha(int(235 * k))
            rect = txt.get_rect(center=(int(fcx), int(fcy - 140)))
            glow = txt.copy()
            glow.fill((*rf.GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
            glow.set_alpha(int(140 * k))
            rf.bloom(surf, glow, rect.topleft, radius=8, passes=1, max_alpha=90)
            surf.blit(txt, rect)


@scene("birthday", duration=11.0, weight=0, forced=True, mood="excited")
class Birthday(Scene):
    """A cake with candles — she even blows them out."""
    BLOW = 0.62

    def available(self):
        return time.strftime("%m-%d") in BIRTHDAYS

    def motion(self, face, p):
        if self.BLOW - 0.08 < p < self.BLOW + 0.12:
            face._mouth_drive = 0.85
            face.target_oy += 14.0

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.1, 0.12)
        if hold < 0.02:
            return
        y = fcy + 170 + 300 * (1 - hold)
        cake = rf.gradient_block(230, 96, 14, rf.HAND_GRAD_TOP, rf.HAND_GRAD_BOTTOM)
        cake = cake.copy()
        pygame.draw.rect(cake, (*rf.HEART_COL, 220),
                         pygame.Rect(0, 0, 230, 20), border_radius=8)
        cake.set_alpha(int(255 * hold))
        surf.blit(cake, cake.get_rect(center=(int(fcx), int(y))))
        lit = p < self.BLOW
        t = p * self.duration
        for i in (-70, 0, 70):                     # candles
            cx = int(fcx + i)
            pygame.draw.rect(surf, (*rf.TEETH_COL, int(240 * hold)),
                             pygame.Rect(cx - 5, int(y) - 86, 10, 44),
                             border_radius=3)
            if lit:
                fl = 7 + 3 * math.sin(t * 9 + i)
                pygame.draw.circle(surf, (*rf.STAR_COL, int(245 * hold)),
                                   (cx, int(y) - 94), int(fl))
            elif p < self.BLOW + 0.25:             # a wisp of smoke
                k = (p - self.BLOW) / 0.25
                pygame.draw.circle(surf, (*rf.TEETH_COL, int(120 * hold * (1 - k))),
                                   (cx + int(10 * k), int(y) - 100 - int(40 * k)),
                                   int(4 + 8 * k))


@scene("santa_hat", duration=9.0, weight=5, dates=("12-01", "12-31"),
       mood="happy")
class SantaHat(Scene):
    """A red hat drops onto her head for the season."""
    def _drop(self, p):
        return rf.clamp(p * 4.0, 0, 1) * (1.0 if p < 0.85 else (1 - p) / 0.15)

    def motion(self, face, p):
        if 0.2 < p < 0.32:                          # the little bump of landing
            face.target_oy += 9.0 * math.sin((p - 0.2) / 0.12 * math.pi)

    def draw(self, face, surf, fcx, fcy, p):
        k = self._drop(p)
        if k < 0.02:
            return
        y = int(fcy - 168 - (1 - k) * 260)
        hat = pygame.Surface((300, 170), pygame.SRCALPHA)
        pygame.draw.polygon(hat, (*rf.ANGRY_COL, 245),
                            [(20, 150), (280, 150), (210, 16)])
        pygame.draw.rect(hat, (*rf.TEETH_COL, 250),
                         pygame.Rect(6, 138, 288, 30), border_radius=14)
        pygame.draw.circle(hat, (*rf.TEETH_COL, 250), (212, 14), 24)
        hat.set_alpha(int(255 * min(1.0, k * 1.4)))
        surf.blit(hat, hat.get_rect(center=(int(fcx), y)))


@scene("pumpkin", duration=9.0, weight=5, dates=("10-24", "10-31"))
class Pumpkin(Scene):
    """A jack-o'-lantern keeps her company, flickering."""
    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        t = p * self.duration
        flicker = 0.75 + 0.25 * math.sin(t * 11) * math.sin(t * 3.1)
        x, y = int(fcx + 250), int(fcy + 150 + 300 * (1 - hold))
        body = pygame.Surface((190, 170), pygame.SRCALPHA)
        for dx, w in ((0, 180), (-34, 120), (34, 120)):
            pygame.draw.ellipse(body, (*rf.EYE_OUTER, 245),
                                pygame.Rect(95 + dx - w // 2, 20, w, 140))
        pygame.draw.rect(body, (*rf.EYE_MID, 245), pygame.Rect(86, 0, 18, 30),
                         border_radius=6)
        a = int(250 * flicker)
        for ex in (60, 120):                        # eyes
            pygame.draw.polygon(body, (*rf.STAR_COL, a),
                                [(ex - 18, 78), (ex + 18, 78), (ex, 48)])
        pygame.draw.polygon(body, (*rf.STAR_COL, a),
                            [(56, 112), (134, 112), (120, 134), (100, 116),
                             (80, 134)])
        body.set_alpha(int(255 * hold))
        surf.blit(body, body.get_rect(center=(x, y)))


@scene("fireworks", duration=12.0, weight=6, forced=True,
       dates=("12-31", "01-01"), hours=(20, 3), mood="excited")
class Fireworks(Scene):
    """New Year: the sky goes off behind her."""
    def __init__(self):
        rnd = random.Random(77)
        self.shots = [(rnd.uniform(0.08, 0.85), rnd.uniform(0.1, 0.55),
                       rnd.uniform(0.0, 0.8), rnd.randint(0, 4))
                      for _ in range(9)]

    def motion(self, face, p):
        face.pupil_oy = rf.lerp(face.pupil_oy, -18.0 * rf._prop_hold(p), 0.06)

    def draw_bg(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p, 0.08, 0.12)
        if hold < 0.02:
            return
        palette = (rf.STAR_COL, rf.HEART_COL, rf.TEAR_COL, rf.EYE_INNER,
                   rf.TEETH_COL)
        for x, y, start, hue in self.shots:
            k = (p - start) / 0.42
            _burst(surf, x * rf.WIDTH, y * rf.HEIGHT, k, palette[hue], hold)


@scene("valentine", duration=10.0, weight=5, dates=("02-13", "02-14"),
       mood="love")
class Valentine(Scene):
    """Hearts everywhere, and she is entirely fine with that."""
    def __init__(self):
        rnd = random.Random(14)
        self.hearts = [(rnd.random(), rnd.random(), rnd.uniform(0.25, 0.6),
                        rnd.uniform(14, 26), rnd.uniform(0, 6.3))
                       for _ in range(14)]

    def draw(self, face, surf, fcx, fcy, p):
        hold = rf._prop_hold(p)
        if hold < 0.02:
            return
        t = p * self.duration
        for x0, y0, speed, size, ph in self.hearts:
            k = (y0 + t * speed * 0.16) % 1.1
            y = rf.HEIGHT - k * (rf.HEIGHT + 60)
            x = x0 * rf.WIDTH + 34 * math.sin(t * 0.9 + ph)
            a = int(235 * hold * min(1.0, k * 4) * (1.0 - k * 0.8))
            if a <= 6:
                continue
            rf.draw_heart(surf, int(x), int(y), int(size), a)
