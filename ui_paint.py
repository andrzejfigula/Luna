"""
ui_paint.py — the Malowanie page (paint.py): the sheet, the live stroke, the
red "Pokaż" marks, the toolbar, the picture picker, "Rysuję…" while she draws.

paint.py owns the layout (buttons(), canvas_rect(), picker_cells()), so a tap
lands where it is drawn; this only draws. The page has its own ✕ (robot_face
leaves its corner one off).
"""

import math
import os
import time

import pygame

import paint
from ui_screens import WHITE, DIM, text, fit, rrect, vgrad

_GOLD = (255, 205, 120)
_LABELS = {"talk": "Powiedz", "close": "Zamknij", "brush": "Pędzel", "eraser": "Gumka",
           "mark": "Pokaż", "undo": "Cofnij", "new": "Nowa", "open": "Otwórz",
           "save": "Zapisz", "print": "Drukuj", "rotate": "Obróć", "beautify": "Upiększ",
           "photo": "Zdjęcie"}
_VOICE = {"listening": ("Słucham", (60, 190, 110)), "thinking": ("Myślę", (230, 160, 50)),
          "speaking": ("Mówię", (150, 100, 220))}
_sheet = {"ver": -1, "surf": None}
_thumbs = {}                    # (path, mtime, w, h) → surface


def _surface(pil):
    raw = pil.tobytes()
    load = getattr(pygame.image, "frombytes", None) or pygame.image.fromstring
    return load(raw, pil.size, "RGB")


def _thumb(path, w, h, budget):
    """A picture fitted in w × h (cached); None while not loaded yet."""
    try:
        key = (path, os.path.getmtime(path), w, h)
    except OSError:
        return None
    s = _thumbs.get(key)
    if s is None and budget[0] > 0:
        budget[0] -= 1                      # a few a frame: no hitch opening the picker
        try:
            img = pygame.image.load(path)
            k = min(w / img.get_width(), h / img.get_height())
            s = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * k)),
                                                   max(1, int(img.get_height() * k))))
        except (pygame.error, OSError, ZeroDivisionError):
            s = pygame.Surface((1, 1))
        if len(_thumbs) > 64:
            _thumbs.clear()
        _thumbs[key] = s
    return s


def _wrap(s, size, width, weight="SemiBold"):
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if cur and text(t, size, WHITE, weight).get_width() > width:
            lines.append(cur)
            cur = w
        else:
            cur = t
    return lines + ([cur] if cur else [])


def _marks(surf, marks, k, ox, oy, now):
    """Red, see-through, gently pulsing: "here" for Luna, not paint."""
    a = int(70 + 30 * math.sin(now * 4))
    for m in marks:
        pts = [(ox + p[0] * k, oy + p[1] * k) for p in m["pts"]]
        r = max(4, int(m["r"] * k))
        for p in pts:
            pygame.draw.circle(surf, paint.MARK_COL + (a,), (int(p[0]), int(p[1])), r)
        if len(pts) > 1:
            pygame.draw.lines(surf, paint.MARK_COL + (a,), False, pts, 2 * r)
        for p in (pts[0], pts[-1]):
            pygame.draw.circle(surf, paint.MARK_COL + (230,), (int(p[0]), int(p[1])), r, 2)


def _bin(scr, r, armed):
    """A little bin on a picture in "Otwórz" (red: the next tap bins it)."""
    x, y, w, h = r
    c = (x + w // 2, y + h // 2)
    pygame.draw.circle(scr, (214, 52, 52) if armed else (30, 30, 44), c, w // 2 - 3)
    pygame.draw.circle(scr, WHITE, c, w // 2 - 3, 2)
    bx, by = c[0] - 7, c[1] - 6
    pygame.draw.line(scr, WHITE, (bx - 2, by), (bx + 16, by), 2)              # the lid
    pygame.draw.line(scr, WHITE, (bx + 5, by - 3), (bx + 9, by - 3), 2)       # its handle
    pygame.draw.polygon(scr, WHITE, [(bx, by + 3), (bx + 14, by + 3), (bx + 12, by + 16),
                                     (bx + 2, by + 16)], 2)                    # the can
    for dx in (5, 9):
        pygame.draw.line(scr, WHITE, (bx + dx, by + 6), (bx + dx, by + 13), 1)


def _camera(scr, count):
    """The camera's picture in the sheet's box, mirrored (as the photo will be)."""
    from shared_state import state
    with state.lock:
        frame = state.frame
    bx, by, bw, bh = paint.BOX
    if frame is not None:
        fh, fw = frame.shape[:2]
        img = pygame.image.frombuffer(frame.tobytes(), (fw, fh), "BGR")
        img = pygame.transform.flip(img, True, False)
        k = min(bw / fw, bh / fh)
        img = pygame.transform.scale(img, (int(fw * k), int(fh * k)))
        scr.blit(img, img.get_rect(center=(bx + bw // 2, by + bh // 2)))
    if count:
        n = text(count, 120, WHITE, "ExtraBold")
        sh = text(count, 120, (0, 0, 0), "ExtraBold")
        c = (bx + bw // 2, by + bh // 2)
        scr.blit(sh, sh.get_rect(center=(c[0] + 3, c[1] + 4)))
        scr.blit(n, n.get_rect(center=c))


def draw(scr, now, W, H):
    v = paint.view()
    scr.blit(vgrad(W, H, (22, 24, 40), (44, 36, 64)), (0, 0))
    x, y, w, h = v["rect"]
    k = v["k"]
    budget = [2]

    if v["camera"] is not None:                       # "Zdjęcie": the live camera, 3-2-1
        _camera(scr, v["camera"])
    elif v["picker"] is not None:                     # pictures to open
        paths = v["picker"]["paths"]
        if not paths:
            msg = text("Nie ma jeszcze obrazków do otwarcia", 22, DIM)
            bx, by, bw, bh = paint.BOX
            scr.blit(msg, msg.get_rect(center=(bx + bw // 2, by + bh // 2)))
        for path, (cx, cy, cw, ch) in zip(paths, paint.picker_cells()):
            scr.blit(rrect(cw, ch, 12, (255, 255, 255, 22)), (cx, cy))
            t = _thumb(path, cw - 12, ch - 12, budget)
            if t is not None:
                scr.blit(t, t.get_rect(center=(cx + cw // 2, cy + ch // 2)))
            armed = v["bin_ask"] == path
            if armed:                                 # "really?" over the picture
                scr.blit(rrect(cw, ch, 12, (120, 20, 30, 170)), (cx, cy))
                q = text("Usunąć?", 24, WHITE, "ExtraBold")
                scr.blit(q, q.get_rect(center=(cx + cw // 2, cy + ch // 2 - 12)))
                for i, line in enumerate(_wrap("Dotknij kosza jeszcze raz", 14, cw - 16)):
                    s = text(line, 14, WHITE, "SemiBold")
                    scr.blit(s, s.get_rect(center=(cx + cw // 2, cy + ch // 2 + 16 + i * 17)))
            _bin(scr, paint.bin_rect((cx, cy, cw, ch)), armed)
    else:
        if _sheet["ver"] != v["ver"] and v["view"] is not None:
            _sheet["surf"], _sheet["ver"] = _surface(v["view"]), v["ver"]
        scr.blit(rrect(w + 8, h + 8, 6, (0, 0, 0, 90)), (x - 2, y + 1))   # a soft shadow
        if _sheet["surf"] is not None:
            scr.blit(_sheet["surf"], (x, y))
        st = v["stroke"]
        if st and st["tool"] != "mark":               # the finger's stroke, live
            pts = [(x + p[0] * k, y + p[1] * k) for p in st["pts"]]
            lw = max(1, int(2 * st["r"] * k))
            scr.set_clip(pygame.Rect(x, y, w, h))
            if len(pts) > 1:
                pygame.draw.lines(scr, st["colour"], False, pts, lw)
            for p in pts:
                pygame.draw.circle(scr, st["colour"], (int(p[0]), int(p[1])), max(1, lw // 2))
            scr.set_clip(None)
        marks = v["marks"] + ([st] if st and st["tool"] == "mark" else [])
        if marks:
            layer = pygame.Surface((w, h), pygame.SRCALPHA)
            _marks(layer, marks, k, 0, 0, now)
            scr.blit(layer, (x, y))
        if now - v["flash_t"] < 0.3:                  # the shutter
            white = pygame.Surface((w, h))           # (not rrect: it caches every alpha)
            white.fill(WHITE)
            white.set_alpha(int(255 * (1 - (now - v["flash_t"]) / 0.3)))
            scr.blit(white, (x, y))
        if v["busy"]:                                 # she is drawing: the sheet waits
            scr.blit(rrect(w, h, 0, (20, 20, 36, 150)), (x, y))
            base = v["busy"].rstrip("…")
            full = text(base + "...", 30, WHITE, "ExtraBold")   # (the dots don't shift it)
            lab = text(base + "." * (1 + int(now * 2) % 3), 30, WHITE, "ExtraBold")
            scr.blit(lab, (x + (w - full.get_width()) // 2, y + h // 2 - lab.get_height() // 2))
            secs = int(now - v["busy_t"])
            sub = text(f"{secs} s", 18, DIM, "SemiBold")
            scr.blit(sub, sub.get_rect(center=(x + w // 2, y + h // 2 + 34)))
            c = (x + w // 2, y + h // 2 - 52)
            for i in range(8):                        # a ring of dots, turning
                a = now * 3 + i * math.pi / 4
                pygame.draw.circle(scr, (255, 255, 255, 255) if i == 0 else (180, 180, 210),
                                   (int(c[0] + 16 * math.cos(a)), int(c[1] + 16 * math.sin(a))),
                                   4 if i == 0 else 2)

    for key, (bx, by, bw, bh) in paint.buttons():     # the toolbar
        lit = (key == v["tool"]) or (key == "close" and v["picker"] is not None)
        if key.startswith("c") and key[1:].isdigit():
            i = int(key[1:])
            col = paint.COLOURS[i]
            ccx, ccy = bx + bw // 2, by + bh // 2
            if i == v["colour"] and v["tool"] == "brush":
                pygame.draw.circle(scr, WHITE, (ccx, ccy), bw // 2, 3)
            pygame.draw.circle(scr, col, (ccx, ccy), bw // 2 - 5)
            continue
        dim = (key == "undo" and not v["undo"] and not v["marks"]) or \
            (v["picker"] is not None and key in ("brush", "eraser", "mark", "undo")) or \
            key in v["running"] or (key == "print" and v["printing"])
        bg = (255, 205, 120, 95) if lit else (214, 52, 52, 200) if key == "close" else \
            (96, 170, 255, 120) if key == "talk" else \
            (170, 110, 230, 150) if key == "beautify" else (255, 255, 255, 30)
        label = _LABELS[key]
        sub = None                                    # a small second line
        if key == "talk" and v["voice"]:              # she listens / thinks / talks: seen here
            label = _VOICE[v["voice"]][0]             # (the page hides her face and the bar)
            pulse = 0.5 + 0.5 * math.sin(now * 5)
            bg = _VOICE[v["voice"]][1] + (int(150 + 90 * pulse),)
            if v["voice"] == "listening":
                sub = "dotknij: stop"
        if key == v["confirm"]:                       # "Nowa" / "Drukuj": once more to do it
            label = "Na pewno?"
            bg = (255, 205, 120, int(150 + 90 * (0.5 + 0.5 * math.sin(now * 6))))
        elif key == "print" and v["printing"]:
            label = "Drukuję…"
        if key == "undo" and v["undo_n"] and v["picker"] is None:
            sub = str(v["undo_n"])
        scr.blit(rrect(bw, bh, 12, bg), (bx, by))
        cx = bx + bw // 2
        if key == v["confirm"]:                       # (no icon: the question needs the room)
            fs = next((s for s in (16, 15, 14, 13, 12)
                       if text(label, s, WHITE, "Bold").get_width() <= bw - 6), 12)
            lab = text(fit(label, fs, bw - 6, "Bold"), fs, WHITE, "Bold")
            scr.blit(lab, lab.get_rect(center=(cx, by + bh // 2 + 2)))
            continue
        if key == "beautify":                         # a sparkle
            sx, sy = bx + 10, by + bh // 2
            pygame.draw.polygon(scr, _GOLD, [(sx, sy - 6), (sx + 1.5, sy - 1.5), (sx + 6, sy),
                                             (sx + 1.5, sy + 1.5), (sx, sy + 6),
                                             (sx - 1.5, sy + 1.5), (sx - 6, sy),
                                             (sx - 1.5, sy - 1.5)])
            cx += 6
        if key == "photo":                            # a little camera
            px, py = bx + 5, by + bh // 2 - 6
            pygame.draw.rect(scr, WHITE, (px, py + 2, 16, 11), 2, border_radius=2)
            pygame.draw.rect(scr, WHITE, (px + 5, py, 6, 3))
            pygame.draw.circle(scr, WHITE, (px + 8, py + 7), 3, 1)
            cx += 9
        if key == "rotate":                           # the paper, the way it lies now
            pw, ph = (16, 11) if v["wide"] else (11, 16)
            pygame.draw.rect(scr, WHITE, (bx + 7 + (16 - pw) // 2, by + (bh - ph) // 2, pw, ph),
                             2, border_radius=2)
            cx += 10
        if key == "open" and v["picker"] is not None and v["picker"]["pages"] > 1:
            label = "Dalej ›"
        if key == "brush":                            # its size, in its colour
            r = (2, 4, 7)[v["size"]] if v["tool"] == "brush" else 4
            pygame.draw.circle(scr, paint.COLOURS[v["colour"]], (bx + bw - 11, by + 11), r)
        if key == "eraser" and v["tool"] == "eraser":
            pygame.draw.circle(scr, WHITE, (bx + bw - 11, by + 11), (3, 5, 8)[v["size"]], 2)
        if key == "mark" and v["marks"]:
            pygame.draw.circle(scr, paint.MARK_COL, (bx + bw - 11, by + 11), 6)
        room = bw - 8 - 2 * (cx - bx - bw // 2)        # (beside an icon: less room)
        fs = next((s for s in (17, 16, 15, 14) if text(label, s, WHITE, "Bold").get_width() <= room),
                  14)
        lab = text(fit(label, fs, room, "Bold"), fs, (150, 150, 170) if dim else WHITE, "Bold")
        if sub and key == "talk":                     # two lines in the tall button
            scr.blit(lab, lab.get_rect(center=(cx, by + bh // 2 - 6)))
            s = text(fit(sub, 12, bw - 6, "SemiBold"), 12, WHITE, "SemiBold")
            scr.blit(s, s.get_rect(center=(cx, by + bh // 2 + 13)))
            continue
        scr.blit(lab, lab.get_rect(center=(cx, by + bh // 2 + 2)))
        if sub:                                       # undo: how many steps back are left
            s = text(sub, 11, DIM, "SemiBold")
            scr.blit(s, s.get_rect(topright=(bx + bw - 5, by + 2)))

    hx, hy, hw, hh = paint.HINT                       # a line of help
    hint = v["hint"]
    if v["picker"] is not None:
        p = v["picker"]
        hint = "Usunąć? Dotknij kosza jeszcze raz" if v["bin_ask"] else v["note"] or (
            "Dotknij obrazka, żeby go otworzyć" + (
                f" · strona {p['page'] + 1}/{p['pages']}" if p["pages"] > 1 else ""))
    elif v["busy"] and not v["confirm"]:
        hint = "Luna rysuje — to trwa chwilę"
    for fs, step in ((16, 21), (14, 17), (13, 15)):  # smaller rather than cut off
        lines = _wrap(hint, fs, hw)
        if len(lines) * step <= hh + 4:
            break
    for i, line in enumerate(lines[:max(1, (hh + 4) // step)]):
        img = text(line, fs, _GOLD if i == 0 and v["marks"] else DIM, "SemiBold")
        scr.blit(img, (hx, hy + i * step))
