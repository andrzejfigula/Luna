"""
tools/ui_preview.py — the gallery and weather pages (ui_screens.py) drawn
into PNGs, without a screen and without her photos (made-up pictures).

    venv/bin/python tools/ui_preview.py /tmp/ui     → /tmp/ui/*.png
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

W, H = 800, 480


def _fake_picture(path, size, hue):
    s = pygame.Surface(size)
    for y in range(size[1]):
        k = y / size[1]
        s.fill((int(60 + 150 * k), int(120 + 80 * hue), int(200 - 120 * k)),
               pygame.Rect(0, y, size[0], 1))
    pygame.draw.circle(s, (255, 220, 120), (size[0] // 3, size[1] // 3), size[1] // 6)
    pygame.draw.rect(s, (40, 140, 70), pygame.Rect(0, size[1] * 3 // 4, size[0], size[1] // 4))
    pygame.image.save(s, path)


def main(out):
    os.makedirs(out, exist_ok=True)
    pygame.init()
    scr = pygame.display.set_mode((W, H))
    import ui_screens
    pics = []
    for j, size in enumerate(((640, 480), (1024, 1024), (640, 480), (1600, 700))):
        p = os.path.join(out, f"pic{j}.png")
        _fake_picture(p, size, j / 4)
        pics.append(p)
    items = [{"path": p, "caption": c, "sub": s} for p, c, s in zip(
        pics, ("Maja i Andrzej", "„kotek na rowerze”", "", "Tatry"),
        ("dziś, 17:39", "wczoraj, 9:05", "3 października", ""))]
    g = {"items": items, "i": 0, "title": "Zdjęcia", "auto": True, "next": 10.0 + 3.0,
         "t_nav": 0.0, "dir": 0, "from": None}
    ui_screens.draw_gallery(scr, g, 10.0, W, H)
    pygame.image.save(scr, os.path.join(out, "gallery.png"))
    g.update(i=1, auto=False, t_nav=20.0, dir=1, **{"from": 0})
    ui_screens.draw_gallery(scr, g, 20.0 + 0.12, W, H)
    pygame.image.save(scr, os.path.join(out, "gallery_slide.png"))
    ui_screens.draw_gallery(scr, g, 21.0, W, H)
    pygame.image.save(scr, os.path.join(out, "gallery_drawing.png"))
    g.update(confirm=21.0, toast=("Usunięto · „przywróć rysunek”", 30.0))
    for it in items:
        it["kind"] = "drawing"
    ui_screens.draw_gallery(scr, g, 21.5, W, H)
    pygame.image.save(scr, os.path.join(out, "gallery_confirm.png"))
    people = [{"path": pics[0], "caption": "Maja", "sub": "córka, 8 lat · widziałam dziś, 17:39",
               "kind": "person", "name": "Maja", "round": True},
              {"path": None, "caption": "Kasia", "sub": "widziałam wczoraj, 9:05",
               "kind": "person", "name": "Kasia", "round": True}]
    pg = {"items": people, "i": 0, "title": "Kogo znam", "auto": False, "next": 0.0,
          "t_nav": 0.0, "dir": 0, "from": None, "confirm": 0.0, "toast": None}
    ui_screens.draw_gallery(scr, pg, 10.0, W, H)
    pygame.image.save(scr, os.path.join(out, "people.png"))
    pg["i"] = 1
    ui_screens.draw_gallery(scr, pg, 10.0, W, H)
    pygame.image.save(scr, os.path.join(out, "people_letter.png"))
    ui_screens.draw_photo(scr, pics[3], "Tatry · Wikipedia", W, H)
    pygame.image.save(scr, os.path.join(out, "photo.png"))
    kinds = ("partly", "rain", "clear", "storm", "snow", "fog", "drizzle")
    days = [{"label": lab, "date": f"{14 + j}.10", "kind": kinds[j], "desc": "",
             "tmin": 4 + j, "tmax": 11 + (j * 3) % 8, "rain": (0, 80, 10, 60, 30, 0, 40)[j]}
            for j, lab in enumerate(("Dziś", "Jutro", "Czwartek", "Piątek", "Sobota",
                                     "Niedziela", "Poniedziałek"))]
    for name, now in (("weather_day", {"temp": 13, "feels": 11, "wind": 14, "kind": "partly",
                                       "desc": "częściowe zachmurzenie", "day": True}),
                      ("weather_night", {"temp": 6, "feels": 3, "wind": 5, "kind": "clear",
                                         "desc": "bezchmurnie", "day": False}),
                      ("weather_rain", {"temp": 9, "feels": 7, "wind": 22, "kind": "rain",
                                        "desc": "deszcz", "day": True})):
        hours = [{"h": str(h % 24), "temp": 12 - j, "kind": ("partly", "cloud", "rain", "clear",
                                                             "clear")[j], "day": h < 18}
                 for j, h in enumerate(range(15, 30, 3))]
        data = {"place": "Wrocław", "now": now, "days": days, "t0": 0.0, "hours": hours}
        ui_screens.draw_weather(scr, data, 5.0, W, H)
        pygame.image.save(scr, os.path.join(out, f"{name}.png"))
    icons = pygame.Surface((8 * 110, 230))
    icons.fill((40, 70, 120))
    for j, k in enumerate(("clear", "partly", "cloud", "fog", "drizzle", "rain", "snow", "storm")):
        icons.blit(ui_screens.weather_icon(k, 100, True), (j * 110 + 5, 5))
        icons.blit(ui_screens.weather_icon(k, 100, False), (j * 110 + 5, 120))
    pygame.image.save(icons, os.path.join(out, "icons.png"))
    print("saved to", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ui")
