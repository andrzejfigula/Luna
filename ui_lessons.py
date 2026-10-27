"""
ui_lessons.py — the "plan lekcji" page (schedule.show_lessons): one person's
school week, Monday to Friday, as a grid — lesson hours down the side, the
five days across, today's column and the lesson now lit.

  person chips (only those with lessons) · "+ Dodaj" (whose plan: picked from
  the family, a chip until the page closes) · "Plan tygodnia" · "Wyczyść" (a
  dialog: "Tak, wyczyść" / "Anuluj") · "Wczytaj z kartki" (the camera reads a
  new timetable; once read, it replaces all the old lessons) — each subject in
  its own colour (schedule.subject_colours)
  a lesson: tapped → the week page's editor for it (back returns here)
  an empty cell in a row: "Jaka lekcja…?" — said by voice

layout() is shared by draw() and hit(), so a tap lands where it is drawn.
"""

import time

import pygame

import schedule
from ui_schedule import chip_row, _pill, _toast, _GOLD
from ui_screens import WHITE, DIM, text, fit, rrect, vgrad

TOP = 92                       # the day headers
TIME_W = 84                    # the hours column
ADD = "+ Dodaj"


def _dialog(W, H, d):
    """The picker / the clear question: {"dialog", "no", "yes" | "picks": [(rect, name)]}."""
    D = {}
    if d.get("pick"):
        names = schedule.lesson_candidates(d)
        dw, x, y, rows = 560, 0, 0, []
        for n in names:                      # chips in rows, wrapped
            w = text(n, 20, WHITE, "Bold").get_width() + 34
            if x and x + w > dw - 60:
                x, y = 0, y + 54
            if y > 54:
                break
            rows.append((x, y, w, n))
            x += w + 10
        dh = 200 + (rows[-1][1] + 54 if rows else 30)
        D["dialog"] = dg = pygame.Rect((W - dw) // 2, (H - dh) // 2, dw, dh)
        D["picks"] = [(pygame.Rect(dg.x + 30 + cx, dg.y + 92 + cy, w, 46), n)
                      for cx, cy, w, n in rows]
        D["no"] = pygame.Rect(dg.centerx - 90, dg.bottom - 70, 180, 50)
    elif d.get("ask"):
        D["dialog"] = dg = pygame.Rect((W - 480) // 2, (H - 230) // 2, 480, 230)
        D["no"] = pygame.Rect(dg.x + 30, dg.bottom - 74, 180, 50)
        D["yes"] = pygame.Rect(dg.right - 30 - 210, dg.bottom - 74, 210, 50)
    return D


def layout(W, H, d):
    """{"who": [(rect, name)], "heads": [rect]*5, "cells": {(row, wd): rect},
    "times": [rect], "week", "paper", "clear" (with lessons), "add", "dialog"…}."""
    L = {}
    chips, L["chip_fs"] = chip_row(W, schedule.page_people(d) + [ADD])
    L["who"] = [(r, n) for r, n in chips if n != ADD]
    L["add"] = next((r for r, n in chips if n == ADD), None)
    L.update(_dialog(W, H, d))
    rows, cells, spare = schedule.lesson_slots(d.get("who"))
    x0, gap = 16 + TIME_W, 6
    w = (W - 16 - x0 - 4 * gap) // 5
    L["heads"] = [pygame.Rect(x0 + k * (w + gap), TOP, w, 30) for k in range(5)]
    n = max(1, len(rows))
    top, bottom = TOP + 36, H - 62
    rh = min(46, (bottom - top) // n)
    L["row_h"] = rh
    L["times"] = [pygame.Rect(16, top + r * rh, TIME_W - 6, rh - 4) for r in range(len(rows))]
    L["cells"] = {(r, k): pygame.Rect(x0 + k * (w + gap), top + r * rh, w, rh - 4)
                  for r in range(len(rows)) for k in range(5)}
    L["rows"], L["grid"], L["spare"] = rows, cells, spare
    L["week"] = pygame.Rect(16, H - 52, 170, 44)
    L["paper"] = pygame.Rect(W - 16 - 220, H - 52, 220, 44)
    L["clear"] = pygame.Rect(L["paper"].x - 10 - 170, H - 52, 170, 44) if rows else None
    return L


def hit(x, y, W, H, d):
    """("who", name) | ("cell", row, weekday) | ("week",) | ("paper",) | ("clear",)
    | ("add",) | ("pick", name) | ("yes",) | ("no",) | None."""
    L = layout(W, H, d)
    if L.get("dialog"):                      # only the dialog's buttons; beside it: cancel
        for r, n in L.get("picks") or ():
            if r.inflate(4, 6).collidepoint(x, y):
                return ("pick", n)
        for key in ("yes", "no"):
            if L.get(key) and L[key].inflate(6, 6).collidepoint(x, y):
                return (key,)
        return None if L["dialog"].collidepoint(x, y) else ("no",)
    for r, n in L["who"]:
        if r.inflate(4, 6).collidepoint(x, y):
            return ("who", n)
    for key in ("week", "paper", "clear", "add"):
        if L[key] and L[key].inflate(6, 6).collidepoint(x, y):
            return (key,)
    for (row, k), r in L["cells"].items():
        if r.inflate(4, 4).collidepoint(x, y):
            return ("cell", row, k)
    return None


def _hm(s):
    return s.lstrip("0") if s and not s.startswith("00") else s


def draw(scr, d, now, W, H):
    scr.blit(vgrad(W, H, (18, 22, 40), (38, 34, 70)), (0, 0))
    L = layout(W, H, d)
    title = text("Plan lekcji", 30, WHITE, "ExtraBold")
    scr.blit(title, (24, 36 - title.get_height() // 2))
    for r, n in L["who"]:
        _pill(scr, r, n, L["chip_fs"], on=n == d.get("who"))
    if L["add"]:
        _pill(scr, L["add"], ADD, L["chip_fs"], col=(70, 120, 200, 160))
    who = d.get("who")
    sub = text(fit((who or "dotknij „+ Dodaj”, żeby dodać plan lekcji") + (" · dotknij lekcji, żeby ją zmienić"
                                                  if L["rows"] else ""), 17, 520, "SemiBold"),
               17, DIM, "SemiBold")
    scr.blit(sub, (26, 64))
    lt = time.localtime(now)
    today = lt.tm_wday
    mins = lt.tm_hour * 60 + lt.tm_min
    for k, r in enumerate(L["heads"]):
        lit = k == today
        scr.blit(rrect(r.w, r.h, 12, (255, 205, 120, 90) if lit else (255, 255, 255, 18)), r)
        lab = text(schedule.DAYS[k].capitalize(), 18 if r.w > 110 else 16,
                   WHITE if lit else (225, 225, 240), "ExtraBold" if lit else "Bold")
        scr.blit(lab, lab.get_rect(center=r.center))
    if not L["rows"]:
        msg = f"{who} nie ma jeszcze planu lekcji" if who else "Nie ma jeszcze planu lekcji"
        img = text(msg, 24, DIM, "SemiBold")
        scr.blit(img, img.get_rect(center=(W // 2, 230)))
        for i, line in enumerate(("Potrzymaj kartkę z planem przed kamerą",
                                  "i dotknij „Wczytaj z kartki”") if who else
                                 ("Dotknij „+ Dodaj” i wybierz osobę,",
                                  "potem pokaż jej plan kamerze")):
            hint = text(line, 18, DIM, "SemiBold")
            scr.blit(hint, hint.get_rect(center=(W // 2, 272 + i * 26)))
    rh = L["row_h"]
    fs = 18 if rh >= 38 else 16 if rh >= 32 else 14
    first_spare = len(L["rows"]) - L["spare"]
    for i, ((at, end), r) in enumerate(zip(L["rows"], L["times"])):
        spare = i >= first_spare                  # an empty row to add to: its hours a guess
        no = text(str(i + 1), fs - 2, (150, 130, 95) if spare else _GOLD, "ExtraBold")
        scr.blit(no, (r.x, r.centery - no.get_height() // 2))
        tm = text(_hm(at), fs, (130, 136, 156) if spare else (215, 220, 235), "Bold")
        if end and rh >= 34:
            en = text("–" + _hm(end), 12, DIM, "SemiBold")
            scr.blit(tm, (r.x + 20, r.y + 1))
            scr.blit(en, (r.x + 20, r.bottom - en.get_height()))
        else:
            scr.blit(tm, (r.x + 20, r.centery - tm.get_height() // 2))
    cols = schedule.subject_colours({e["title"] for es in L["grid"].values() for e in es})
    for (row, k), r in L["cells"].items():
        es = L["grid"].get((row, k))
        if not es:
            scr.blit(rrect(r.w, r.h, 10, (255, 255, 255, 8)), r)
            continue
        at, end = L["rows"][row]
        stop = schedule._mins(end) if end else schedule._mins(at) + schedule.LESSON_MINS
        now_on = k == today and schedule._mins(at) <= mins < stop
        col = cols[es[0]["title"]]
        scr.blit(rrect(r.w, r.h, 10, col + ((235,) if now_on else (165,))), r)
        if now_on:
            pygame.draw.rect(scr, _GOLD, r, 2, border_radius=10)
        t = " / ".join(e["title"] for e in es)
        t = t[:1].upper() + t[1:]
        img = text(fit(t, fs, r.w - 12, "Bold"), fs, WHITE, "Bold")
        scr.blit(img, img.get_rect(center=r.center))
    _pill(scr, L["week"], "Plan tygodnia", 19)
    if L["clear"]:
        _pill(scr, L["clear"], "Wyczyść", 20, col=(214, 52, 52, 120), weight="ExtraBold")
    _pill(scr, L["paper"], "Wczytaj z kartki", 20, col=(70, 120, 200, 220), weight="ExtraBold")
    if L.get("dialog"):
        _draw_dialog(scr, d, L, W, H)
    _toast(scr, d, now, W, H)


def _draw_dialog(scr, d, L, W, H):
    shade = pygame.Surface((W, H), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 150))
    scr.blit(shade, (0, 0))
    dg = L["dialog"]
    scr.blit(rrect(dg.w, dg.h, 22, (34, 30, 54, 250)), dg)
    if d.get("pick"):
        q = text("Czyj plan lekcji dodać?", 26, WHITE, "ExtraBold")
        scr.blit(q, q.get_rect(center=(dg.centerx, dg.y + 46)))
        for r, n in L["picks"]:
            _pill(scr, r, n, 20)
        if not L["picks"]:
            t = text("Wszyscy z rodziny już tu są.", 19, DIM, "SemiBold")
            scr.blit(t, t.get_rect(center=(dg.centerx, dg.y + 100)))
    else:
        who = schedule.genitive(d.get("who"))
        q = text(fit(f"Wyczyścić plan lekcji {who}?", 26, dg.w - 40, "ExtraBold"), 26, WHITE,
                 "ExtraBold")
        scr.blit(q, q.get_rect(center=(dg.centerx, dg.y + 44)))
        for j, ln in enumerate(("Wszystkie lekcje znikną.", "Reszta planu tygodnia zostaje.")):
            t = text(ln, 19, DIM, "SemiBold")
            scr.blit(t, t.get_rect(center=(dg.centerx, dg.y + 88 + j * 26)))
    for key, lab, col in (("no", "Anuluj", (255, 255, 255, 40)),
                          ("yes", "Tak, wyczyść", (214, 52, 52, 240))):
        if L.get(key):
            b = L[key]
            scr.blit(rrect(b.w, b.h, 24, col), b)
            t = text(lab, 21, WHITE, "ExtraBold")
            scr.blit(t, t.get_rect(center=b.center))
