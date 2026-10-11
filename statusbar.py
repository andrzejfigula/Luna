"""
statusbar.py — a thin bar along the top of her screen, like a Mac's menu bar.

  left:   what is going on in her — the internet, listening / thinking /
          speaking, the radio, a timer or the stopwatch, the next wake-up
          alarm and reminder, unheard voice messages, focus or quiet time,
          and the microphone or camera switched off
  right:  the date and the time ("niedz. 11 paź  20:45")

"Ukryj pasek" / "pokaż pasek" (commands.py) switch it off and on; with it
off, the old corner icons come back (robot_face.py).

What it shows is collected in items() — plain data, tested without a screen —
and drawn by StatusBar. The quiet part is rendered once per change and only
blitted per frame; just the listening / thinking / speaking slot moves.
"""

import math
import time

import pygame

from shared_state import state

HEIGHT = 30
PAD = 12               # from the screen edges
GAP = 16               # between items
ICON = 20              # an icon's box
_SLOT = 26             # the listening / thinking / speaking slot, always kept

_DAYS = ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz.")
_MONTHS = ("sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru")

TEXT = (232, 232, 240)
DIM = (150, 150, 165)
RED = (255, 110, 90)


def enabled():
    import settings
    return settings.get("status_bar", True) is not False


def clock_text(now=None):
    """The right-hand corner: "niedz. 11 paź  20:45"."""
    lt = time.localtime(now if now is not None else time.time())
    return f"{_DAYS[lt.tm_wday]} {lt.tm_mday} {_MONTHS[lt.tm_mon - 1]}   {lt.tm_hour}:{lt.tm_min:02d}"


def _hm(t):
    lt = time.localtime(t)
    return f"{lt.tm_hour}:{lt.tm_min:02d}"


def _timers(now):
    """(alarm, reminder) as "7:30" — the next ones within a day — or None."""
    import timers
    with timers._lock:
        items = list(timers._timers)
    soon = lambda kind: min((t["due"] for t in items
                             if t["kind"] == kind and 0 < t["due"] - now < 86400), default=None)
    alarm, reminder = soon("alarm"), soon("reminder")
    return (_hm(alarm) if alarm else None), (_hm(reminder) if reminder else None)


def _countdown(now):
    """The nearest running timer ("4:59") or the stopwatch ("+2:14"), or None."""
    import timers
    import counting
    with timers._lock:
        due = min((t["due"] for t in timers._timers if t["kind"] == "timer"), default=None)
    if due is not None:
        left = max(0, int(due - now))
        h, rem = divmod(left, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    return counting.stopwatch_text()


def items(now=None):
    """What the bar shows, left to right: [(kind, text or None)], plus the
    voice slot ("listening" | "thinking" | "speaking" | None)."""
    now = now if now is not None else time.time()
    with state.lock:
        online = state.online
        speaking = state.speaking
        thinking = state.luna_mode == "processing"
        listening = state.conversation_active or state.listening
        radio = state.radio
        waiting = state.messages_waiting
        muted = now < state.mic_muted_until
        cam_off = now < state.camera_off_until
        focus = now < state.focus_until
        quiet = now < state.proactive_muted_until
    voice = ("speaking" if speaking else "thinking" if thinking
             else "listening" if listening and not muted else None)
    out = [("online" if online else "offline", None)]
    if radio:
        name = radio.lstrip("♪ ").strip()
        out.append(("radio", name if len(name) <= 22 else name[:21] + "…"))
    try:
        countdown = _countdown(now)
        alarm, reminder = _timers(now)
    except Exception:
        countdown = alarm = reminder = None
    if countdown:
        out.append(("timer", countdown))
    if alarm:
        out.append(("alarm", alarm))
    if reminder:
        out.append(("reminder", reminder))
    if waiting:
        out.append(("message", str(waiting) if waiting > 1 else None))
    if focus or quiet:
        out.append(("quiet", None))
    if muted:
        out.append(("mic_off", None))
    if cam_off:
        out.append(("cam_off", None))
    return out, voice


# ── icons: drawn with pygame shapes (the fonts have no emoji) ────────────────

def _icon(kind, accent):
    s = pygame.Surface((ICON, ICON), pygame.SRCALPHA)
    c = (*TEXT, 235)
    if kind == "online":                                  # wifi: three arcs and a dot
        for r in (17, 11, 5):
            pygame.draw.arc(s, c, pygame.Rect(10 - r, 17 - r, 2 * r, 2 * r),
                            math.radians(45), math.radians(135), 2)
        pygame.draw.circle(s, c, (10, 16), 2)
    elif kind == "offline":                               # a cloud, crossed out
        for cx, cy, r in ((6, 12, 5), (11, 9, 6), (15, 12, 4)):
            pygame.draw.circle(s, (*DIM, 230), (cx, cy), r)
        pygame.draw.rect(s, (*DIM, 230), pygame.Rect(5, 12, 11, 5))
        pygame.draw.line(s, (*RED, 245), (2, 19), (18, 2), 3)
    elif kind == "radio":                                 # two beamed notes
        pygame.draw.ellipse(s, c, pygame.Rect(1, 13, 7, 6))
        pygame.draw.ellipse(s, c, pygame.Rect(11, 11, 7, 6))
        pygame.draw.line(s, c, (7, 16), (7, 3), 2)
        pygame.draw.line(s, c, (17, 14), (17, 1), 2)
        pygame.draw.polygon(s, c, [(7, 3), (17, 1), (17, 5), (7, 7)])
    elif kind == "timer":                                 # an hourglass
        pygame.draw.line(s, c, (4, 2), (16, 2), 2)
        pygame.draw.line(s, c, (4, 18), (16, 18), 2)
        pygame.draw.lines(s, c, False, [(5, 3), (10, 10), (5, 17)], 2)
        pygame.draw.lines(s, c, False, [(15, 3), (10, 10), (15, 17)], 2)
        pygame.draw.polygon(s, (*accent, 220), [(7, 16), (13, 16), (10, 12)])
    elif kind == "alarm":                                 # a bell
        pygame.draw.arc(s, c, pygame.Rect(4, 2, 12, 14), 0, math.pi, 2)
        pygame.draw.line(s, c, (4, 9), (4, 14), 2)
        pygame.draw.line(s, c, (16, 9), (16, 14), 2)
        pygame.draw.line(s, c, (2, 15), (18, 15), 2)
        pygame.draw.circle(s, c, (10, 18), 2)
    elif kind == "reminder":                              # a pin
        pygame.draw.circle(s, c, (10, 7), 5, 2)
        pygame.draw.line(s, c, (10, 12), (10, 19), 2)
    elif kind == "message":                               # an envelope
        pygame.draw.rect(s, (*accent, 240), pygame.Rect(1, 4, 18, 13), 2, border_radius=2)
        pygame.draw.lines(s, (*accent, 240), False, [(2, 5), (10, 11), (18, 5)], 2)
    elif kind == "quiet":                                 # a crescent moon
        pygame.draw.circle(s, c, (10, 10), 8)
        pygame.draw.circle(s, (0, 0, 0, 0), (14, 7), 7)
    elif kind == "mic_off":
        pygame.draw.rect(s, c, pygame.Rect(7, 1, 6, 11), 2, border_radius=3)
        pygame.draw.arc(s, c, pygame.Rect(4, 5, 12, 10), math.pi, 2 * math.pi, 2)
        pygame.draw.line(s, c, (10, 15), (10, 19), 2)
        pygame.draw.line(s, (*RED, 245), (2, 2), (18, 18), 3)
    elif kind == "cam_off":
        pygame.draw.rect(s, c, pygame.Rect(1, 6, 18, 12), 2, border_radius=3)
        pygame.draw.circle(s, c, (10, 12), 3, 2)
        pygame.draw.rect(s, c, pygame.Rect(7, 3, 6, 4), 2)
        pygame.draw.line(s, (*RED, 245), (2, 2), (18, 18), 3)
    return s


class StatusBar:
    def __init__(self):
        self._font = None
        self._left = (None, None)          # (signature, surface)
        self._right = (None, None)
        self._icons = {}
        self._items = ([], None)
        self._polled = 0.0
        self._on = (True, 0.0)

    def _text(self, text, col=TEXT):
        if self._font is None:
            pygame.font.init()
            path = pygame.font.match_font("dejavusans")
            self._font = pygame.font.Font(path, 16) if path else pygame.font.SysFont(None, 20)
        return self._font.render(text, True, col)

    def _iconof(self, kind, accent):
        ic = self._icons.get((kind, accent))
        if ic is None:
            ic = self._icons[(kind, accent)] = _icon(kind, accent)
        return ic

    def _render_left(self, its, accent):
        """Everything after the internet icon and the voice slot, as one strip."""
        parts = [(self._iconof(k, accent), self._text(t) if t else None) for k, t in its]
        w = sum(ic.get_width() + (6 + t.get_width() if t else 0) + GAP for ic, t in parts)
        surf = pygame.Surface((max(1, w), HEIGHT), pygame.SRCALPHA)
        x = 0
        for ic, t in parts:
            surf.blit(ic, (x, (HEIGHT - ICON) // 2))
            x += ic.get_width()
            if t:
                surf.blit(t, (x + 6, (HEIGHT - t.get_height()) // 2))
                x += 6 + t.get_width()
            x += GAP
        return surf

    def _voice(self, screen, kind, accent, alpha):
        """The one moving slot, at the far left (after the internet icon)."""
        x0, cy, t = PAD + ICON + GAP - 4, HEIGHT // 2, time.time()
        s = pygame.Surface((_SLOT, HEIGHT), pygame.SRCALPHA)
        a = int(alpha)
        if kind == "listening":                     # a microphone, gently breathing
            k = 0.65 + 0.35 * math.sin(t * 3.0)
            col = (*accent, int(a * k))
            pygame.draw.rect(s, col, pygame.Rect(10, 5, 7, 12), border_radius=3)
            pygame.draw.arc(s, col, pygame.Rect(6, 9, 15, 12), math.pi, 2 * math.pi, 2)
            pygame.draw.line(s, col, (13, 21), (13, 25), 2)
        elif kind == "thinking":                    # three dots, one after another
            for i in range(3):
                k = 0.3 + 0.7 * max(0.0, math.sin(t * 5.0 - i * 0.9))
                pygame.draw.circle(s, (*TEXT, int(a * k)), (5 + i * 8, cy), 3)
        elif kind == "speaking":                    # three bars, following her voice
            with state.lock:
                e = min(1.0, state.audio_energy * 1.5)
            for i in range(3):
                h = 4 + int(14 * e * (0.6 + 0.4 * abs(math.sin(t * 9 + i * 1.7))))
                pygame.draw.rect(s, (*accent, a), pygame.Rect(4 + i * 7, cy - h // 2, 4, h),
                                 border_radius=2)
        screen.blit(s, (x0, 0))

    def draw(self, screen, accent, asleep=False):
        now = time.time()
        if now - self._on[1] > 1.0:
            self._on = (enabled(), now)
        if not self._on[0]:
            return False
        if now - self._polled > 0.25:               # a few times a second is plenty
            self._polled = now
            self._items = items(now)
        its, voice = self._items
        alpha = 70 if asleep else 255               # at night: barely there

        net, rest = (its[0], its[1:]) if its else (("online", None), [])
        sig = (tuple(rest), accent)
        if self._left[0] != sig:
            self._left = (sig, self._render_left(rest, accent))
        clock = clock_text(now)
        if self._right[0] != clock:
            self._right = (clock, self._text(clock))

        # the strip itself: a faint veil, lighter than her black face
        veil = getattr(self, "_veil", None)
        if veil is None:
            veil = self._veil = pygame.Surface((screen.get_width(), HEIGHT), pygame.SRCALPHA)
            veil.fill((255, 255, 255, 16))
            pygame.draw.line(veil, (255, 255, 255, 22), (0, HEIGHT - 1),
                             (screen.get_width(), HEIGHT - 1))
        y = (HEIGHT - ICON) // 2
        for surf, pos in ((veil, (0, 0)),
                          (self._iconof(net[0], accent), (PAD, y)),
                          (self._left[1], (PAD + ICON + GAP + _SLOT + GAP, 0)),
                          (self._right[1], (screen.get_width() - PAD - self._right[1].get_width(),
                                            (HEIGHT - self._right[1].get_height()) // 2))):
            surf.set_alpha(alpha)
            screen.blit(surf, pos)
        if voice:
            self._voice(screen, voice, accent, alpha)
        return True
