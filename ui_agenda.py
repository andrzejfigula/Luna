"""
ui_agenda.py — the calendar's page (agenda.py): drawing only; the taps and the
layout are there, so what's drawn is what's tapped.

  the month: ‹ Listopad 2026 ›, the days with a dot in each person's colour,
             gold for a birthday, red numerals for Sundays and days off
  the day:   what's on it (events, the week's plan, reminders, birthdays,
             holidays), whose (a chip), "Najbliższe", "+ Dodaj", "Wpisz", "Z kartki"
  an event:  the day, the time, whose, how often, the reminders, a note, "Usuń"
"""

import calendar
import time
from datetime import date

import pygame

import agenda
import contacts
import ui_contacts
from ui_screens import WHITE, DIM, text, fit, shrink, rrect, vgrad, circle_button, _avatar_col

_GOLD = (255, 205, 120)
_RED = (255, 118, 118)
_DEEP_RED = (214, 52, 52)
_HOUSE = (150, 165, 205)
_LABEL = (190, 192, 214)
_KIND_COL = {"plan": (140, 200, 255), "reminder": (255, 180, 120), "birthday": _GOLD,
             "nameday": _GOLD, "feast": _RED}
_KIND_TAG = {"plan": "plan", "reminder": "przypomnienie"}


def _R(r):
    return pygame.Rect(r)


def _pill(scr, r, label, size=19, on=False, col=None, weight="Bold"):
    r = _R(r)
    bg = col or ((255, 205, 120, 80) if on else (255, 255, 255, 26))
    scr.blit(rrect(r.w, r.h, min(r.h // 2, 22), bg), r)
    img = text(fit(label, size, r.w - 16, weight), size, WHITE, weight)
    scr.blit(img, img.get_rect(center=r.center))


def _dot_col(who):
    return _avatar_col(who) if who else _HOUSE


def _draw_month(scr, d, today, W, H):
    y, m = d["y"], d["m"]
    L = agenda.layout(W, H, d)
    for key, kind in (("prev", "prev"), ("next", "next")):
        b = circle_button(kind, 22)
        scr.blit(b, b.get_rect(center=_R(L[key]).center))
    head = text(f"{agenda.MONTHS[m - 1]} {y}", 28, WHITE, "ExtraBold")
    scr.blit(head, head.get_rect(center=(229, 34)))
    for k, name in enumerate(agenda.DAYS_SHORT):
        img = text(name, 16, _RED if k == 6 else DIM, "SemiBold")
        scr.blit(img, img.get_rect(center=(agenda.GRID_X + k * agenda.CELL_W + (agenda.CELL_W - 4) // 2, 72)))
    marks = agenda.month_marks(y, m, d.get("who"))
    sel = agenda._d(d["day"])
    for n in range(1, calendar.monthrange(y, m)[1] + 1):
        _draw_cell(scr, agenda.cell_rect(y, m, n, H), date(y, m, n), marks.get(n), sel, today)


def _draw_cell(scr, r, day, mark, sel, today):
    r = _R(r)
    if day == sel:
        scr.blit(rrect(r.w, r.h, 10, (255, 205, 120, 70)), r)
    elif mark and (mark["who"] or mark["people"]):
        scr.blit(rrect(r.w, r.h, 10, (255, 255, 255, 18)), r)
    if day == today:
        pygame.draw.rect(scr, _GOLD, r, width=2, border_radius=10)
    red = day.weekday() == 6 or (mark and mark["off"])
    col = _RED if red else WHITE
    num = text(str(day.day), 21, col, "Bold" if day == today or day == sel else "SemiBold")
    scr.blit(num, num.get_rect(center=(r.centerx, r.y + min(r.h // 2 - 4, 22))))
    if not mark:
        return
    dots = [_dot_col(w) for w in dict.fromkeys(mark["who"])][:3]
    if mark["people"]:
        dots = (dots + [_GOLD])[-3:]
    x = r.centerx - (len(dots) - 1) * 5
    for k, c in enumerate(dots):
        pygame.draw.circle(scr, c, (x + k * 10, r.bottom - 9), 4)


def _day_head(d, today):
    if d.get("view") == "next":
        return "Najbliższe", ""
    day = agenda._d(d["day"])
    name = agenda.DAYS_NOM[day.weekday()]
    head = f"{name[:1].upper()}{name[1:]}, {day.day} {agenda.MONTHS_GEN[day.month - 1]}"
    left = agenda.in_days(day, today)
    return head, "" if left == "minęło" else left


def _draw_row(scr, r, day, it, d, today):
    r = _R(r)
    kind = it["kind"]
    scr.blit(rrect(r.w, r.h, 12, (255, 255, 255, 30 if kind == "event" else 16)), r)
    pygame.draw.rect(scr, _dot_col(it["who"]) if kind == "event" else _KIND_COL.get(kind, _HOUSE),
                     (r.x + 6, r.y + 8, 5, r.h - 16), border_radius=3)
    x = r.x + 20
    if d.get("view") == "next":
        when = f"{agenda.DAYS_SHORT[day.weekday()]} {day.day:02d}.{day.month:02d}"
        img = text(when, 16, _GOLD, "Bold")
        scr.blit(img, (x, r.y + 5))
        if it["at"]:
            scr.blit(text(it["at"], 16, DIM, "SemiBold"), (x, r.y + 26))
        x += 86
    elif it["at"]:
        img = text(it["at"], 19, _GOLD, "Bold")
        scr.blit(img, img.get_rect(midleft=(x, r.centery)))
        x += 62
    room = r.right - x - 8
    title = it["title"][:1].upper() + it["title"][1:]
    sub = _KIND_TAG.get(kind) or (it["who"] if kind == "event" else "")
    if kind == "plan" and it["who"]:
        sub = f"plan · {it['who']}"
    if sub:
        scr.blit(text(fit(title, 19, room, "SemiBold"), 19, WHITE, "SemiBold"), (x, r.y + 4))
        scr.blit(text(fit(sub, 15, room, "Medium"), 15, DIM, "Medium"), (x, r.y + 27))
    else:
        img = text(fit(title, 19, room, "SemiBold"), 19, WHITE, "SemiBold")
        scr.blit(img, img.get_rect(midleft=(x, r.centery)))


def _draw_panel(scr, d, today, W, H):
    L = agenda.layout(W, H, d)
    head, left = _day_head(d, today)
    img = text(fit(head, 23, 258, "ExtraBold"), 23, WHITE, "ExtraBold")
    scr.blit(img, (agenda.PANEL_X, 12))
    if left:
        scr.blit(text(left, 16, _GOLD, "SemiBold"), (agenda.PANEL_X, 40))
    _pill(scr, L["who"], d.get("who") or "Wszyscy", 18, on=bool(d.get("who")))
    _pill(scr, L["view"], "Dzień" if d.get("view") == "next" else "Najbliższe", 18,
          on=d.get("view") == "next")
    for r, (day, it) in L["rows"]:
        _draw_row(scr, r, day, it, d, today)
    if not L["rows"]:
        msg = "Nic nie czeka" if d.get("view") == "next" else "Nic zapisanego"
        img = text(msg, 20, DIM, "Medium")
        scr.blit(img, img.get_rect(center=(agenda.PANEL_X + (W - agenda.PANEL_X - 12) // 2, 170)))
        hint = text("Dotknij „+ Dodaj” i powiedz, co wpisać", 15, DIM, "Medium")
        scr.blit(hint, hint.get_rect(center=(agenda.PANEL_X + (W - agenda.PANEL_X - 12) // 2, 198)))
    if L["more"]:
        _pill(scr, L["more"], f"Więcej ({d.get('page', 0) + 1}/{L['pages']})", 15)
    _pill(scr, L["add"], "+ Dodaj", 18, col=(92, 150, 110, 230))
    _pill(scr, L["type"], "Wpisz", 18)
    _pill(scr, L["paper"], "Z kartki", 18)


def _label(scr, s, r):
    img = text(s, 17, _LABEL, "SemiBold")
    scr.blit(img, img.get_rect(midright=(134, _R(r).centery)))


def _value(scr, s, r):
    r = _R(r)
    img = text(s, 20, WHITE, "Bold")
    scr.blit(img, img.get_rect(center=r.center))


def _lead_chip(lead, at):
    if lead == 0:
        return "O czasie" if at else "Rano"
    if lead < agenda.HOUR:
        return f"{lead} min"
    if lead < agenda.DAY:
        return f"{lead // agenda.HOUR} godz."
    if lead == agenda.WEEK:
        return "Tydzień"
    return f"{lead // agenda.DAY} " + ("dzień" if lead == agenda.DAY else "dni")


def _draw_card(scr, d, e, now, W, H):
    L = agenda.layout(W, H, d)
    b = circle_button("prev", 24)
    scr.blit(b, b.get_rect(center=_R(L["back"]).center))
    t = e["title"][:1].upper() + e["title"][1:]
    size = shrink(t, 28, _R(L["title"]).w - 14, "ExtraBold", 18)
    scr.blit(text(fit(t, size, _R(L["title"]).w - 14, "ExtraBold"), size, WHITE, "ExtraBold"),
             (_R(L["title"]).x + 6, 24))
    day = agenda._d(e["date"])
    _label(scr, "Kiedy", L["w-"])
    _pill(scr, L["w-"], "−tydz.", 15)
    _pill(scr, L["d-"], "−1", 18)
    name = agenda.DAYS_SHORT[day.weekday()]
    _value(scr, f"{name}, {day.day} {agenda.MONTHS_GEN[day.month - 1]} {day.year}",
           (_R(L["d-"]).right, _R(L["d-"]).y, _R(L["d+"]).x - _R(L["d-"]).right, 44))
    _pill(scr, L["d+"], "+1", 18)
    _pill(scr, L["w+"], "+tydz.", 15)
    _label(scr, "Godzina" if e.get("at") else "Ile dni", L["at-"])
    a, b_ = _R(L["at-"]), _R(L["at+"])
    e1, e2 = _R(L["end-"]), _R(L["end+"])
    if e.get("at"):
        _pill(scr, a, "−", 24)
        _value(scr, e["at"], (a.right, a.y, b_.x - a.right, 44))
        _pill(scr, b_, "+", 24)
        img = text("do", 17, _LABEL, "SemiBold")
        scr.blit(img, img.get_rect(center=((b_.right + e1.x) // 2, a.centery)))
        _pill(scr, e1, "−", 24)
        _value(scr, e.get("end") or "—", (e1.right, e1.y, e2.x - e1.right, 44))
        _pill(scr, e2, "+", 24)
    else:
        _pill(scr, e1, "−", 24)
        _value(scr, str(agenda._span(e) + 1), (e1.right, e1.y, e2.x - e1.right, 44))
        _pill(scr, e2, "+", 24)
    _pill(scr, L["allday"], "Cały dzień", 16, on=not e.get("at"))
    _label(scr, "Czyje", L["who"])
    _pill(scr, L["who"], e.get("who") or "Cały dom", 18, col=None)
    img = text("Powtórz", 17, _LABEL, "SemiBold")
    scr.blit(img, img.get_rect(midright=(_R(L["repeat"]).x - 8, _R(L["repeat"]).centery)))
    _pill(scr, L["repeat"], agenda.REPEAT_SAID[e.get("repeat") or "none"], 15,
          on=(e.get("repeat") or "none") != "none")
    _label(scr, "Przypomnij", L["leads"][0][0])
    for r, lead in L["leads"]:
        off = not e.get("at") and 0 < lead < agenda.DAY
        if off:
            r_ = _R(r)
            scr.blit(rrect(r_.w, r_.h, 16, (255, 255, 255, 8)), r_)
            continue
        _pill(scr, r, _lead_chip(lead, e.get("at")), 15, on=lead in (e.get("remind") or []))
    _label(scr, "Gdy cicho", L["always"])
    _pill(scr, L["always"], "Powiedz głośno, nawet gdy nikogo nie ma" if e.get("always")
          else "Przypomnij, gdy ktoś jest", 16, on=bool(e.get("always")))
    _label(scr, "Notatka", L["note"])
    r = _R(L["note"])
    scr.blit(rrect(r.w, r.h, 12, (255, 255, 255, 22)), r)
    img = text(fit(e.get("note") or "dotknij, by dopisać", 17, r.w - 20, "Medium"), 17,
               WHITE if e.get("note") else DIM, "Medium")
    scr.blit(img, img.get_rect(midleft=(r.x + 12, r.centery)))
    sure = now - d.get("confirm", 0.0) < 4.0
    _pill(scr, L["delete"], "Na pewno usunąć?" if sure else "Usuń", 18,
          col=(*_DEEP_RED, 240) if sure else (255, 255, 255, 26))


def _draw_keyboard(scr, d, W, H):
    e = d["edit"]
    box = pygame.Rect(contacts.box_rect(W))
    scr.blit(rrect(box.w, box.h, 14, (255, 255, 255, 30)), box)
    head = {"new": "Nowe wydarzenie", "title": "Nazwa", "note": "Notatka"}.get(e["field"], "")
    scr.blit(text(fit(head, 15, box.w - 90, "SemiBold"), 15, _GOLD, "SemiBold"), (box.x + 14, box.y + 4))
    ui_contacts.draw_typed(scr, e["text"], "", box)
    ui_contacts.draw_keys(scr, "text", e, W, H, save="Zapisz")


def _toast(scr, d, now, W, H):
    t = d.get("toast")
    if t and now < t[1]:
        img = text(t[0], 19, WHITE, "Bold")
        pill = rrect(img.get_width() + 36, 40, 20, (20, 22, 34, 235))
        r = pill.get_rect(center=(W // 2, H - 76))
        scr.blit(pill, r)
        scr.blit(img, img.get_rect(center=r.center))


def draw(scr, d, now, W, H):
    scr.blit(vgrad(W, H, (18, 22, 40), (38, 34, 70)), (0, 0))
    if d.get("edit"):
        _draw_keyboard(scr, d, W, H)
        return
    today = date.fromtimestamp(now if now else time.time())
    e = agenda.get(d["sel"]) if d.get("sel") else None
    if e is not None:
        _draw_card(scr, d, e, now, W, H)
    else:
        d["sel"] = None
        _draw_month(scr, d, today, W, H)
        _draw_panel(scr, d, today, W, H)
    _toast(scr, d, now, W, H)
