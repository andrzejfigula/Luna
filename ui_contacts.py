"""
ui_contacts.py — the contact card and its keyboard (contacts.py is the logic and
owns the layout, so taps and tests need no pygame).
"""

import os

import pygame

import contacts
import faces
from ui_screens import WHITE, _load, _round_card, fit, font, rrect, text, vgrad

GOLD = (255, 205, 120)
SOFT = (200, 200, 220)
DIM = (150, 150, 175)
DARK = (40, 32, 66)
_portraits = {}              # name → (file's mtime, the round picture)


def _portrait(name, D):
    path = faces.portrait(name)
    stamp = os.path.getmtime(path) if path else None
    got = _portraits.get(name)
    if not got or got[0] != stamp:
        got = (stamp, _round_card(_load(path) if path else None, name, D))
        _portraits[name] = got
    return got[1]


def _rect(r):
    return pygame.Rect(*r)


def _toast(scr, data, now, x, y):
    toast = data.get("toast")
    if toast and now < toast[1]:
        img = text(toast[0], 20, WHITE, "Bold")
        pill = rrect(img.get_width() + 36, 40, 20, (20, 22, 34, 235))
        pr = pill.get_rect(center=(x, y))
        scr.blit(pill, pr)
        scr.blit(img, img.get_rect(center=pr.center))


def _draw_card(scr, data, now, W, H):
    name = data["name"]
    c = contacts.card(name)
    if c is None:                                  # forgotten while it was open
        t = text("Nie znam tej osoby", 26, SOFT, "Bold")
        scr.blit(t, t.get_rect(center=(W // 2, H // 2)))
        return
    pic = _portrait(name, 150)
    scr.blit(pic, pic.get_rect(center=(118, 104)))
    nm = text(fit(name, 30, 212, "ExtraBold"), 30, WHITE, "ExtraBold")
    scr.blit(nm, nm.get_rect(center=(118, 208)))
    who = (c.get("note") or "").split("—")[0].strip(" ,")
    who = who or ("rodzina" if faces.is_family(name) else "gość")
    sub = text(fit(who, 17, 212, "SemiBold"), 17, SOFT, "SemiBold")
    scr.blit(sub, sub.get_rect(center=(118, 240)))
    title = text("Karta kontaktowa", 26, WHITE, "ExtraBold")
    scr.blit(title, (236, 42 - title.get_height() // 2))
    L = contacts.card_layout(W, H)
    for (field, label, _), r in zip(contacts.FIELDS, L["rows"]):
        r = _rect(r)
        scr.blit(rrect(r.w, r.h, 14, (255, 255, 255, 22)), r)
        lab = text(label, 15, SOFT, "SemiBold")
        scr.blit(lab, (r.x + 14, r.y + 5))
        v = contacts.shown(c, field)
        val = (text(fit(v, 21, r.w - 58, "Bold"), 21, WHITE, "Bold") if v
               else text("dotknij, by dopisać", 18, DIM, "SemiBold"))
        scr.blit(val, (r.x + 14, r.bottom - val.get_height() - 4))
        ch = text("›", 24, GOLD, "ExtraBold")
        scr.blit(ch, ch.get_rect(center=(r.right - 20, r.centery - 2)))
    if len(contacts.people()) > 1:                 # ‹ › to the next person (or a swipe)
        for key, glyph in (("prev", "‹"), ("next", "›")):
            b = _rect(L[key])
            scr.blit(rrect(b.w, b.h, 18, (255, 255, 255, 34)), b)
            t = text(glyph, 32, WHITE, "ExtraBold")
            scr.blit(t, t.get_rect(center=(b.centerx, b.centery - 3)))
    _toast(scr, data, now, 596, 42)                # beside the title: no row under it


def _key_look(key, e, save="Zapisz"):
    """(label, its background, its colour); no label: drawn by hand."""
    plain, lit = (255, 255, 255, 34), (255, 255, 255, 60)
    if key == "save":
        return save, (255, 196, 110, 235), DARK
    if key == "back":
        return "", lit, WHITE
    if key == "clear":
        return "×" if e["text"] else "", (255, 255, 255, 30 if e["text"] else 0), WHITE
    if key == "shift":
        return "Aa", (255, 196, 110, 235) if e["shift"] else lit, DARK if e["shift"] else WHITE
    if key.startswith("layer:"):
        return {"abc": "abc", "123": "123", "pl": "ąę"}[key.split(":", 1)[1]], lit, WHITE
    if key == " ":
        return "spacja", plain, SOFT
    return key.upper() if e["shift"] else key, plain, WHITE


def _draw_editor(scr, data, now, W, H):
    e = data["edit"]
    field = e["field"]
    kind = dict((f, k) for f, _, k in contacts.FIELDS)[field]
    label = dict((f, lb) for f, lb, _ in contacts.FIELDS)[field]
    box = _rect(contacts.box_rect(W))
    scr.blit(rrect(box.w, box.h, 14, (255, 255, 255, 30)), box)
    head = text(fit(f"{label} — {data['name']}", 15, box.w - 90, "SemiBold"), 15, GOLD, "SemiBold")
    scr.blit(head, (box.x + 14, box.y + 4))
    draw_typed(scr, e["text"], contacts.HINT[field], box)
    draw_keys(scr, kind, e, W, H)
    _toast(scr, data, now, W // 2, 100)


def draw_typed(scr, typed, hint, box):
    """What's being typed, in the box; the end of a long one."""
    if typed:
        s = typed + "|"
        f = font(25, "Bold")
        while f.size(s)[0] > box.w - 90:
            s = s[1:]
        val = text(s, 25, WHITE, "Bold")
    else:
        val = text(hint or "|", 21, DIM, "SemiBold")
    scr.blit(val, (box.x + 14, box.bottom - val.get_height() - 3))


def draw_keys(scr, kind, e, W, H, save="Zapisz"):
    for key, r in contacts.key_layout(kind, e["layer"], W, H):
        r = _rect(r)
        lab, bg, col = _key_look(key, e, save)
        scr.blit(rrect(r.w, r.h, 12, bg), r)
        if lab:
            size = 30 if len(lab) == 1 else 22
            if kind != "text" and len(lab) == 1:
                size = 38
            t = text(lab, size, col, "ExtraBold" if key == "save" else "Bold")
            scr.blit(t, t.get_rect(center=r.center))
        elif key == "back":                        # ⌫ (not in the font)
            cx, cy = r.center
            pygame.draw.lines(scr, WHITE, False, [(cx + 15, cy), (cx - 13, cy)], 3)
            pygame.draw.lines(scr, WHITE, False, [(cx - 3, cy - 10), (cx - 14, cy), (cx - 3, cy + 10)], 3)


def draw(scr, data, now, W, H):
    scr.blit(vgrad(W, H, (18, 20, 38), (40, 32, 66)), (0, 0))
    if data.get("edit"):
        _draw_editor(scr, data, now, W, H)
    else:
        _draw_card(scr, data, now, W, H)
