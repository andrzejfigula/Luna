"""
ui_schedule.py — the "plan tygodnia" page (schedule.py): drawing and taps.

  the week:   person chips (Wszyscy, Maja…), the seven days, that day's
              entries (time, whose, what, the reminder), "+ Dodaj"
  an entry:   its days to toggle, the time and the end ± 15 min, the
              reminder (how long before · to whom · even when nobody is
              there) and "Usuń" (tapped twice)

layout() is shared by draw() and hit(), so a tap lands where it is drawn.
The ✕ (robot_face) closes the page; keep clear of its corner.
"""

import time

import pygame

import schedule
from ui_screens import (WHITE, DIM, text, fit, shrink, rrect, vgrad, circle_button,
                        _avatar_col, _LABEL)

ROWS = 5                        # entries on a page of the week view
_GOLD = (255, 205, 120)
_RED = (214, 52, 52)


def _chips_people(d):
    return [None] + schedule.people()


def layout(W, H, d):
    """{"who": [(rect, name)], "days": [rect]*7, "rows": [(rect, id)],
    "add", "more"} for the week; for an entry: "back", "edays", "at-"…"""
    L = {}
    if d.get("sel"):
        L["back"] = pygame.Rect(14, 14, 48, 48)
        x0, w = 190, (W - 190 - 24 - 6 * 8) // 7
        L["edays"] = [pygame.Rect(x0 + k * (w + 8), 102, w, 46) for k in range(7)]
        L["at-"] = pygame.Rect(190, 160, 50, 46)
        L["at+"] = pygame.Rect(350, 160, 50, 46)
        L["end-"] = pygame.Rect(500, 160, 50, 46)
        L["end+"] = pygame.Rect(660, 160, 50, 46)
        L["before"] = pygame.Rect(190, 228, 300, 46)
        L["to"] = pygame.Rect(190, 296, 300, 46)
        L["always"] = pygame.Rect(190, 364, 300, 46)
        L["delete"] = pygame.Rect(W - 24 - 200, H - 24 - 50, 200, 50)
        return L
    x, chips = 250, []
    room = W - 96 - x
    names = _chips_people(d)
    fs = 20
    while fs > 15 and sum(text(n or "Wszyscy", fs).get_width() + 34 for n in names) > room:
        fs -= 1
    for n in names:
        w = text(n or "Wszyscy", fs).get_width() + 26
        if x + w > W - 96:
            break
        chips.append((pygame.Rect(x, 16, w, 40), n))
        x += w + 8
    L["who"], L["chip_fs"] = chips, fs
    w = (W - 32 - 6 * 6) // 7
    L["days"] = [pygame.Rect(16 + k * (w + 6), 100, w, 44) for k in range(7)]
    evs = schedule.on_day(d["day"], d.get("who"))
    pages = max(1, -(-len(evs) // ROWS))
    d["page"] = d.get("page", 0) % pages
    shown = evs[d["page"] * ROWS:(d["page"] + 1) * ROWS]
    L["rows"] = [(pygame.Rect(16, 152 + k * 55, W - 32, 50), e) for k, e in enumerate(shown)]
    L["add"] = pygame.Rect(W - 16 - 170, H - 52, 170, 44)
    L["more"] = pygame.Rect(16, H - 52, 150, 44) if pages > 1 else None
    L["pages"] = pages
    return L


def hit(x, y, W, H, d):
    """("day", k) | ("who", name) | ("row", id) | ("add",) | ("more",) | ("back",)
    | ("eday", k) | ("at-",) … | ("delete",) | None — a tap at (x, y) px."""
    L = layout(W, H, d)
    if d.get("sel"):
        if L["back"].inflate(10, 10).collidepoint(x, y):
            return ("back",)
        for k, r in enumerate(L["edays"]):
            if r.collidepoint(x, y):
                return ("eday", k)
        for key in ("at-", "at+", "end-", "end+", "before", "to", "always", "delete"):
            if L[key].inflate(6, 6).collidepoint(x, y):
                return (key,)
        return None
    for r, n in L["who"]:
        if r.inflate(4, 6).collidepoint(x, y):
            return ("who", n)
    for k, r in enumerate(L["days"]):
        if r.collidepoint(x, y):
            return ("day", k)
    if L["add"].inflate(6, 6).collidepoint(x, y):
        return ("add",)
    if L["more"] and L["more"].collidepoint(x, y):
        return ("more",)
    for r, e in L["rows"]:
        if r.collidepoint(x, y):
            return ("row", e["id"])
    return None


def _pill(scr, r, label, size=20, on=False, col=None, weight="Bold"):
    bg = col or ((255, 205, 120, 80) if on else (255, 255, 255, 26))
    scr.blit(rrect(r.w, r.h, min(r.h // 2, 22), bg), r)
    img = text(fit(label, size, r.w - 20, weight), size, WHITE, weight)
    scr.blit(img, img.get_rect(center=r.center))


def _avatar(scr, cx, cy, name, R=19):
    col = _avatar_col(name) if name else (120, 120, 150)
    pygame.draw.circle(scr, col, (cx, cy), R)
    img = text((name[:1] if name else "D").upper(), 20, WHITE, "ExtraBold")
    scr.blit(img, img.get_rect(center=(cx, cy + 1)))


def _toast(scr, d, now, W, H):
    t = d.get("toast")
    if t and now < t[1]:
        img = text(t[0], 20, WHITE, "Bold")
        pill = rrect(img.get_width() + 36, 40, 20, (20, 22, 34, 235))
        pr = pill.get_rect(center=(W // 2, H - 30))
        scr.blit(pill, pr)
        scr.blit(img, img.get_rect(center=pr.center))


def draw(scr, d, now, W, H):
    scr.blit(vgrad(W, H, (18, 22, 40), (38, 34, 70)), (0, 0))
    L = layout(W, H, d)
    if d.get("sel"):
        e = schedule.get(d["sel"])
        if e is None:
            d["sel"] = None
            return draw(scr, d, now, W, H)
        return _draw_entry(scr, d, e, L, now, W, H)
    title = text("Plan tygodnia", 30, WHITE, "ExtraBold")
    scr.blit(title, (24, 36 - title.get_height() // 2))
    for r, n in L["who"]:
        _pill(scr, r, n or "Wszyscy", L["chip_fs"], on=n == d.get("who"))
    today = time.localtime(now).tm_wday
    sub = schedule.DAYS[d["day"]].capitalize() + (" · dziś" if d["day"] == today else "") +         (f" · {d['who']}" if d.get("who") else "")
    sb = text(sub, 18, DIM, "SemiBold")
    scr.blit(sb, (26, 64))
    for k, r in enumerate(L["days"]):
        sel = k == d["day"]
        scr.blit(rrect(r.w, r.h, 14, (255, 205, 120, 90) if sel else (255, 255, 255, 18)), r)
        n = len(schedule.on_day(k, d.get("who")))
        lab = text(schedule.DAYS_SHORT[k], 22, WHITE if sel else (225, 225, 240),
                   "ExtraBold" if sel else "Bold")
        scr.blit(lab, lab.get_rect(center=(r.centerx - (8 if n else 0), r.centery)))
        if n:
            c = text(str(n), 15, _GOLD if not sel else WHITE, "Bold")
            scr.blit(c, (r.centerx + 10, r.centery - c.get_height() // 2))
        if k == today:
            scr.blit(rrect(22, 4, 2, _GOLD + (255,)), (r.centerx - 11, r.bottom - 7))
    if not L["rows"]:
        msg = (f"{schedule.DAYS[d['day']].capitalize()}: nic w planie"
               + (f" — {d['who']}" if d.get("who") else ""))
        img = text(msg, 24, DIM, "SemiBold")
        scr.blit(img, img.get_rect(center=(W // 2, 250)))
        hint = text("Dotknij „+ Dodaj” i powiedz, np. „Maja, angielski, Pn–Pt o 17”", 18,
                    DIM, "SemiBold")
        scr.blit(hint, hint.get_rect(center=(W // 2, 290)))
    for r, e in L["rows"]:
        scr.blit(rrect(r.w, r.h, 16, (255, 255, 255, 22)), r)
        at = text(e["at"], 22, _LABEL, "ExtraBold")
        scr.blit(at, (r.x + 14, r.y + (1 if e.get("end") else r.h // 2 - at.get_height() // 2)))
        if e.get("end"):
            en = text("do " + e["end"], 13, DIM, "SemiBold")
            scr.blit(en, (r.x + 16, r.bottom - en.get_height() - 1))
        _avatar(scr, r.x + 116, r.centery, e.get("who"))
        room = r.w - 150 - 230
        nm = text(fit(e["title"][:1].upper() + e["title"][1:], 20, room, "ExtraBold"), 20,
                  WHITE, "ExtraBold")
        scr.blit(nm, (r.x + 146, r.y + 2))
        sub = (e.get("who") or "cały dom") + " · " + schedule.days_short(e["days"])
        sb = text(fit(sub, 14, room, "SemiBold"), 14, DIM, "SemiBold")
        scr.blit(sb, (r.x + 146, r.bottom - sb.get_height() - 2))
        rm = schedule.remind_short(e)
        on = not rm.startswith("bez")
        ri = text(fit(rm, 16, 220, "SemiBold"), 16,
                  _GOLD if on else (150, 150, 170), "SemiBold")
        scr.blit(ri, (r.right - 14 - ri.get_width(), r.centery - ri.get_height() // 2))
    _pill(scr, L["add"], "+ Dodaj", 22, col=(80, 170, 120, 220), weight="ExtraBold")
    if L["more"]:
        _pill(scr, L["more"], f"więcej ({d['page'] + 1}/{L['pages']})", 18)
    _toast(scr, d, now, W, H)


def _draw_entry(scr, d, e, L, now, W, H):
    b = circle_button("prev", 24)
    scr.blit(b, b.get_rect(center=L["back"].center))
    t = e["title"][:1].upper() + e["title"][1:]
    ts = shrink(t, 30, W - 200, "ExtraBold", 20)
    title = text(fit(t, ts, W - 200, "ExtraBold"), ts, WHITE, "ExtraBold")
    scr.blit(title, (80, 26 - title.get_height() // 2 + 4))
    who = text(e.get("who") or "cały dom", 18, DIM, "SemiBold")
    scr.blit(who, (82, 52))

    def label(s, y):
        img = text(s, 19, _LABEL, "Bold")
        scr.blit(img, (24, y - img.get_height() // 2))
    label("Dni", L["edays"][0].centery)
    for k, r in enumerate(L["edays"]):
        _pill(scr, r, schedule.DAYS_SHORT[k], 20, on=k in e["days"])
    label("Godzina", L["at-"].centery)
    for key, sign in (("at-", "−"), ("at+", "+"), ("end-", "−"), ("end+", "+")):
        _pill(scr, L[key], sign, 26, weight="ExtraBold")
    v = text(e["at"], 26, WHITE, "ExtraBold")
    scr.blit(v, v.get_rect(center=((L["at-"].right + L["at+"].x) // 2, L["at-"].centery)))
    dl = text("do", 18, DIM, "SemiBold")
    scr.blit(dl, dl.get_rect(midright=(L["end-"].x - 10, L["end-"].centery)))
    v = text(e.get("end") or "—", 26, WHITE, "ExtraBold")
    scr.blit(v, v.get_rect(center=((L["end-"].right + L["end+"].x) // 2, L["end-"].centery)))
    r = e.get("remind") or {}
    b4 = r.get("before")
    label("Przypomnienie", L["before"].centery)
    _pill(scr, L["before"], "nie przypominaj" if b4 is None else "o czasie" if b4 == 0
          else f"{b4} min wcześniej", 20, on=b4 is not None)
    to = r.get("to") or "owner"
    label("Komu", L["to"].centery)
    _pill(scr, L["to"], ((e.get("who") + " (czyje to)") if e.get("who") else "wszystkim")
          if to == "owner" else "wszystkim, kto jest" if to == "everyone" else to, 20,
          on=b4 is not None)
    label("Gdy nikogo nie ma", L["always"].centery)
    _pill(scr, L["always"], "i tak powiedz na głos" if r.get("always")
          else "poczekaj, aż kogoś zobaczysz", 18, on=bool(r.get("always")))
    hint = text("dotknij, żeby zmienić", 15, DIM, "SemiBold")
    scr.blit(hint, (L["before"].right + 14, L["before"].centery - hint.get_height() // 2))
    sure = now - d.get("confirm", 0.0) < 4.0
    _pill(scr, L["delete"], "Na pewno? Dotknij" if sure else "Usuń", 20,
          col=(_RED + (255,)) if sure else (_RED + (150,)), weight="ExtraBold")
    _toast(scr, d, now, W, H)
