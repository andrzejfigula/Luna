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

    def motion(self, face, p):
        pass

    def eyes(self, face, p, e):
        pass

    def draw(self, face, surf, fcx, fcy, p):
        pass


class Eyes:
    """Mutable eye parameters a scene may bend."""
    __slots__ = ("blink_l", "blink_r", "squint", "widen", "droop")

    def __init__(self, blink, squint, widen, droop):
        self.blink_l = self.blink_r = blink
        self.squint, self.widen, self.droop = squint, widen, droop


def scene(name, duration, weight=3, night_weight=None, mood=None,
          needs_face=False, in_reply=False):
    def deco(cls):
        inst = cls()
        inst.name, inst.duration = name, duration
        inst.weight = weight
        inst.night_weight = weight if night_weight is None else night_weight
        inst.mood, inst.needs_face, inst.in_reply = mood, needs_face, in_reply
        SCENES[name] = inst
        return cls
    return deco


def reply_scenes():
    """Scene names the LLM may pick as body language for a reply."""
    return [s.name for s in SCENES.values() if s.in_reply]


def pick(night, face_present, weights_override=None, disabled=()):
    """Weighted random scene name for the current situation."""
    names, weights = [], []
    for s in SCENES.values():
        if s.name in disabled or (s.needs_face and not face_present):
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
    """A wide "aaah" that also drives the mouth (see RobotFace.update)."""
    def motion(self, face, p):
        s = math.sin(p * math.pi)
        face.target_oy  -= 10.0 * s
        face.target_tilt = -3.0 * s

    def eyes(self, face, p, e):
        s = math.sin(p * math.pi)
        e.blink_l = e.blink_r = min(e.blink_l, 1.0 - 0.85 * s)
        e.squint = max(e.squint, s)


@scene("clock", duration=6.0, weight=3, night_weight=2)
class Clock(Scene):
    """The time floats up below the eyes and sinks back."""
    def eyes(self, face, p, e):
        e.widen = max(e.widen, 0.4 * math.sin(p * math.pi))

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
