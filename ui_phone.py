"""
ui_phone.py — the phone's pages: pairing, the list of SMS, one SMS, "Wysłać?"
(phone.py is the logic and owns the layout, so taps and tests need no pygame).
"""

import time

import pygame

import contacts
import phone
import ui_contacts
from ui_contacts import DARK, DIM, GOLD, SOFT
from ui_screens import WHITE, _wrap, fit, rrect, text, vgrad


def _when(t, now):
    a, b = time.localtime(t), time.localtime(now)
    hm = time.strftime("%H:%M", a)
    if a.tm_yday == b.tm_yday and a.tm_year == b.tm_year:
        return hm
    if now - t < 2 * 86400 and (b.tm_yday - a.tm_yday) % 365 == 1:
        return f"wczoraj {hm}"
    return f"{a.tm_mday}.{a.tm_mon:02d} {hm}"


def _title(scr, s, W):
    t = text(fit(s, 30, W - 130, "ExtraBold"), 30, WHITE, "ExtraBold")
    scr.blit(t, (28, 26))
    return 28 + t.get_width()


def _buttons(scr, view, data, W, H):
    for _key, label, r, gold in phone.buttons(view, W, H, data):
        rect = pygame.Rect(r)
        scr.blit(rrect(rect.w, rect.h, 16, (255, 196, 110, 235) if gold else (255, 255, 255, 34)), rect)
        t = text(label, 24, DARK if gold else WHITE, "ExtraBold" if gold else "Bold")
        scr.blit(t, t.get_rect(center=rect.center))


def _paragraphs(scr, s, x, y, width, bottom, size=25, col=WHITE):
    """Wrapped lines, as many as fit (the last one cut with …)."""
    line_h = int(size * 1.34)
    lines = max(1, (bottom - y) // line_h)
    for line in _wrap(" ".join(s.split()), size, width, "SemiBold", lines=lines):
        scr.blit(text(line, size, col, "SemiBold"), (x, y))
        y += line_h


def _draw_pair(scr, W, H):
    pair = phone.pair_info()
    _title(scr, "Parowanie telefonu", W)
    if pair and pair.get("code"):
        who = pair.get("name") or "telefon"
        head = text(fit(f"Czy {who} pokazuje ten kod?", 24, W - 60, "Bold"), 24, SOFT, "Bold")
        scr.blit(head, head.get_rect(center=(W // 2, 118)))
        code = pair["code"]
        big = text(f"{code[:3]} {code[3:]}", 92, GOLD, "ExtraBold")
        scr.blit(big, big.get_rect(center=(W // 2, 225)))
        return
    lines = ("1. Na telefonie otwórz Ustawienia, potem Bluetooth.",
             "2. Wybierz z listy „Luna”.",
             "3. Sprawdź, czy kod się zgadza, tu i na telefonie.",
             "4. Zezwól na dostęp do wiadomości i kontaktów.")
    y = 112
    for line in lines:
        scr.blit(text(fit(line, 26, W - 70, "SemiBold"), 26, WHITE, "SemiBold"), (34, y))
        y += 56
    if pair:
        left = max(0, int(pair["until"] - time.time()))
        t = text(f"Czekam jeszcze {left // 60}:{left % 60:02d}", 22, DIM, "SemiBold")
        scr.blit(t, t.get_rect(center=(W // 2, H - 44)))


def _draw_inbox(scr, data, now, W, H):
    msgs, page, pages = phone.page_of(data)
    only = data.get("only")
    end = _title(scr, f"SMS-y od: {only[0]}" if only else "SMS-y", W)
    state_word = {"on": "", "connecting": "łączę się…", "no_obex": "brakuje bluez-obexd",
                  "no_dbus": "brakuje python3-dbus"}.get(phone.status(), "telefon poza zasięgiem")
    if state_word:
        t = text(state_word, 19, DIM, "SemiBold")
        scr.blit(t, (end + 18, 38))
    if not msgs:
        t = text("Nie ma tu jeszcze żadnych SMS-ów", 26, SOFT, "Bold")
        scr.blit(t, t.get_rect(center=(W // 2, H // 2)))
    for m, r in zip(msgs, phone.row_rects(W, H)):
        rect = pygame.Rect(r)
        scr.blit(rrect(rect.w, rect.h, 14, (255, 255, 255, 40 if not m["read"] else 20)), rect)
        if not m["read"]:
            pygame.draw.circle(scr, GOLD, (rect.x + 16, rect.y + 20), 6)
        when = text(_when(m["when"], now), 17, DIM, "SemiBold")
        scr.blit(when, (rect.right - when.get_width() - 12, rect.y + 7))
        room = rect.w - when.get_width() - 56
        who = text(fit(m["who"], 22, room, "ExtraBold" if not m["read"] else "Bold"), 22, WHITE,
                   "ExtraBold" if not m["read"] else "Bold")
        scr.blit(who, (rect.x + 32, rect.y + 4))
        line = " ".join(m["text"].split()) or "(bez tekstu)"
        scr.blit(text(fit(line, 19, rect.w - 46, "SemiBold"), 19, SOFT, "SemiBold"), (rect.x + 32, rect.y + 32))
    _buttons(scr, "inbox", data, W, H)
    if pages > 1:
        t = text(f"{page + 1} / {pages}", 18, DIM, "SemiBold")
        scr.blit(t, t.get_rect(center=(W // 2, 74)))


def _draw_read(scr, data, now, W, H):
    m = phone._message(data.get("id"))
    if not m:
        _title(scr, "Tej wiadomości już nie ma", W)
        _buttons(scr, "read", data, W, H)
        return
    _title(scr, m["who"], W)
    sub = _when(m["when"], now)
    if m["number"] and m["number"] != m["who"]:
        sub += f"  ·  {m['number']}"
    scr.blit(text(fit(sub, 19, W - 130, "SemiBold"), 19, DIM, "SemiBold"), (30, 66))
    _paragraphs(scr, m["text"] or "Pusta wiadomość, może zdjęcie.", 30, 104, W - 60, H - 88)
    _buttons(scr, "read", data, W, H)


def _draw_confirm(scr, data, W, H):
    d = phone.draft()
    _title(scr, "Wysłać tego SMS-a?", W)
    if not d:
        return
    who = d["to"] or ""
    if d["number"] and d["number"] != who:
        who += f"  ·  {d['number']}"
    scr.blit(text(fit(f"Do: {who}", 23, W - 130, "Bold"), 23, GOLD, "Bold"), (30, 72))
    _paragraphs(scr, d["text"], 30, 116, W - 60, H - 88)
    _buttons(scr, "confirm", data, W, H)


def _draw_new(scr, data, now, W, H):
    m = phone._message(data.get("id"))
    _title(scr, "Nowy SMS", W)
    _buttons(scr, "new", data, W, H)
    if not m or data.get("private"):
        return
    who = text(fit(f"Od: {m['who']}", 30, W - 60, "ExtraBold"), 30, GOLD, "ExtraBold")
    scr.blit(who, (30, 94))
    _paragraphs(scr, m["text"], 30, 146, W - 60, H - 90)


def _draw_keyboard(scr, data, W, H):
    e = data["edit"]
    d = phone.draft()
    box = pygame.Rect(contacts.box_rect(W))
    scr.blit(rrect(box.w, box.h, 14, (255, 255, 255, 30)), box)
    head = f"SMS do: {d['to']}" if d else "SMS"
    scr.blit(text(fit(head, 15, box.w - 90, "SemiBold"), 15, GOLD, "SemiBold"), (box.x + 14, box.y + 4))
    ui_contacts.draw_typed(scr, e["text"], "", box)
    ui_contacts.draw_keys(scr, "text", e, W, H, save="Dalej")


def draw(scr, data, now, W, H):
    scr.blit(vgrad(W, H, (18, 20, 38), (40, 32, 66)), (0, 0))
    view = data.get("view")
    if data.get("edit"):
        _draw_keyboard(scr, data, W, H)
    elif view == "pair":
        _draw_pair(scr, W, H)
        _buttons(scr, "pair", data, W, H)
    elif view == "read":
        _draw_read(scr, data, now, W, H)
    elif view == "confirm":
        _draw_confirm(scr, data, W, H)
    elif view == "new":
        _draw_new(scr, data, now, W, H)
    else:
        _draw_inbox(scr, data, now, W, H)
    ui_contacts._toast(scr, data, now, W // 2, 100)
