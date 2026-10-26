"""
printer.py — printing on the home network's printer (prototype).

  "wydrukuj listę zakupów"              → the list on an A4 page, with boxes
  "wydrukuj to" / "wydrukuj ten rysunek" → the picture on her screen, else
                                          her last answer
  "wydrukuj ostatni rysunek"            → the newest drawing
  "wydrukuj przepis" (while cooking)    → the recipe; "wydrukuj przepis na
                                          naleśniki" → one written for it
  "wydrukuj kolorowankę z kotem"        → a line-art drawing (drawing.py),
                                          printed when it's ready
  "wydrukuj <coś innego>"               → the small model writes it (a poem,
                                          a times table, a worksheet)
  "… dwa razy / w trzech kopiach", "… czarno-biało"
  "czy drukarka działa?" / "ile jest tonera?" → the printer's own state
  "wydrukuj stronę testową"

Finding it: CUPS's driverless destinations (`lpstat -e`: IPP Everywhere /
AirPrint printers announced over mDNS show up there, no setup, no sudo);
settings "printer" picks one when there are several. Pages are drawn with
PIL (A4, 200 dpi), sent as one PDF with `lp`; CUPS converts it for the
printer. State and toner: `ipptool get-printer-attributes` on the address
`ippfind` gives. LUNA_PRINT_DRY=1: the PDF is kept, nothing is printed.
"""

import json
import os
import re
import subprocess
import tempfile
import threading
import time

from shared_state import state

DPI = 200
W, H = 1654, 2339                  # A4 at DPI
MARGIN = 150
MAX_COPIES = 5
MAX_PAGES = 6                      # one job
PAGES_PER_DAY = 40                 # all jobs (a child asking for 50 colourings)
CACHE_SECS = 600
FONT_DIR = "/usr/share/fonts/truetype/dejavu"

_lock = threading.Lock()
_found = {"dest": None, "uri": None, "t": 0.0}
_today = {"day": "", "pages": 0}


def _run(cmd, timeout=10):
    """A CUPS tool's stdout, or None (not installed, failed, timed out)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


# --- finding it ---------------------------------------------------------------

def destinations():
    out = _run(["lpstat", "-e"], 6)
    return [ln.strip() for ln in (out or "").splitlines() if ln.strip()]


def find(force=False):
    """(CUPS destination, ipp:// address) of the printer to use, or (None, None)."""
    with _lock:
        if not force and _found["dest"] and time.time() - _found["t"] < CACHE_SECS:
            return _found["dest"], _found["uri"]
    dests = destinations()
    if not dests:
        print("[print] no printer found (lpstat -e empty)", flush=True)
        return None, None
    import settings
    want = (settings.get("printer") or "").lower()
    dest = next((d for d in dests if want and want in d.lower()), dests[0])
    uris = (_run(["ippfind", "-T", "3"], 8) or "").split()
    tail = dest.rsplit("_", 1)[-1].lower()           # "…_SEC842519002C54" → its mDNS name
    uri = next((u for u in uris if tail in u.lower()), uris[0] if len(uris) == 1 else None)
    with _lock:
        _found.update(dest=dest, uri=uri, t=time.time())
    print(f"[print] printer: {dest} ({uri or 'no ipp address'}); all: {dests}", flush=True)
    return dest, uri


# --- its state ----------------------------------------------------------------

def status():
    """{"model", "state", "reasons", "accepting", "markers": [(name, %)]}, or None."""
    dest, uri = find()
    if not dest:
        return None
    out = _run(["ipptool", "-tv", uri, "get-printer-attributes.test"], 12) if uri else None
    if not out:
        return {"model": dest.replace("_", " "), "state": "", "reasons": [],
                "accepting": True, "markers": []}
    return parse_attributes(out, dest)


def parse_attributes(out, dest=""):
    attrs = {}
    for ln in out.splitlines():
        m = re.match(r"\s*([a-z-]+) \([^)]*\) = (.*)$", ln)
        if m:
            attrs[m.group(1)] = m.group(2).strip()
    names = attrs.get("marker-names", "").split(",")
    levels = [int(x) for x in re.findall(r"-?\d+", attrs.get("marker-levels", ""))]
    return {"model": attrs.get("printer-make-and-model") or dest.replace("_", " "),
            "state": attrs.get("printer-state", ""),
            "reasons": [r for r in attrs.get("printer-state-reasons", "none").split(",")
                        if r and r != "none"],
            "accepting": attrs.get("printer-is-accepting-jobs", "true") == "true",
            "markers": list(zip(names, levels))}


_REASONS = [                        # IPP printer-state-reasons → what to tell them
    (r"media-empty|media-needed", "nie ma papieru"),
    (r"media-jam", "zaciął się papier"),
    (r"door-open|cover-open|interlock", "jest otwarta pokrywa"),
    (r"toner-empty|marker-supply-empty", "skończył się toner"),
    (r"offline|shutdown", "jest wyłączona albo niedostępna"),
    (r"paused", "jest wstrzymana"),
]
_COLOURS = {"black": "czarnego", "cyan": "niebieskiego", "magenta": "różowego",
            "yellow": "żółtego"}


def problems(st):
    """The printer's troubles in plain Polish ("nie ma papieru"), most urgent first."""
    out = []
    for rx, said in _REASONS:
        if any(re.search(rx, r) and not r.endswith("-report") for r in st["reasons"]):
            out.append(said)
    if not st["accepting"] and not out:
        out.append("nie przyjmuje teraz wydruków")
    return out


def low_toner(st, below=10):
    low = []
    for name, level in st["markers"]:
        colour = _COLOURS.get(name.split()[0].lower() if name.split() else "")
        if colour and 0 <= level <= below:
            low.append(f"mało {colour} tonera — {level} procent")
    return low


def say_status(st=None):
    st = status() if st is None else st
    if not st:
        return "Nie widzę żadnej drukarki w sieci. Czy jest włączona?"
    name = re.sub(r"\s+Series$", "", st["model"])
    trouble = problems(st)
    first = (f"Drukarka {name}: {', '.join(trouble)}." if trouble
             else f"Drukarka {name} jest gotowa.")
    low = low_toner(st)
    return first + (" " + "; ".join(low).capitalize() + "." if low else "")


# --- pages --------------------------------------------------------------------

def _font(size, bold=False):
    from PIL import ImageFont
    for path in (os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
                 "arialbd.ttf" if bold else "arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def _wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=font) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines or [""]


def _footer(draw, n, total):
    f = _font(24)
    draw.text((MARGIN, H - 100), f"Luna · {time.strftime('%d.%m.%Y')}", font=f, fill=150)
    if total > 1:
        s = f"{n}/{total}"
        draw.text((W - MARGIN - draw.textlength(s, font=f), H - 100), s, font=f, fill=150)


def text_pages(title, lines, boxes=False):
    """A4 pages (PIL "L" images): the title big, then the lines wrapped. A line
    starting "## " is a heading; boxes: a square to tick before every line."""
    from PIL import Image, ImageDraw
    body, head, big = _font(36), _font(42, bold=True), _font(64, bold=True)
    pages, page, draw, y = [], None, None, 0

    def new_page():
        nonlocal page, draw, y
        page = Image.new("L", (W, H), 255)
        draw = ImageDraw.Draw(page)
        pages.append(page)
        y = MARGIN

    new_page()
    for ln in _wrap(draw, title, big, W - 2 * MARGIN):
        draw.text((MARGIN, y), ln, font=big, fill=0)
        y += 84
    y += 30
    indent = 70 if boxes else 0
    for raw in lines:
        raw = str(raw).rstrip()
        heading = raw.startswith("## ")
        font = head if heading else body
        text = raw[3:] if heading else raw
        wrapped = _wrap(draw, text, font, W - 2 * MARGIN - indent) if text else [""]
        step = 58 if heading else 52
        if y + step * min(2, len(wrapped)) + (24 if heading else 0) > H - MARGIN - 60:
            if len(pages) >= MAX_PAGES:
                draw.text((MARGIN, y), "…", font=body, fill=0)
                break
            new_page()
        y += 24 if heading else 0
        for i, ln in enumerate(wrapped):
            if y + step > H - MARGIN - 60:
                if len(pages) >= MAX_PAGES:
                    break
                new_page()
            if boxes and i == 0 and text and not heading:
                draw.rectangle((MARGIN, y + 6, MARGIN + 34, y + 40), outline=0, width=3)
            draw.text((MARGIN + (indent if not heading else 0), y), ln, font=font, fill=0)
            y += step
        y += 10 if text else 0
    for i, p in enumerate(pages, 1):
        _footer(ImageDraw.Draw(p), i, len(pages))
    return pages


def image_page(path, caption="", mono=False):
    """A picture fitted on an A4 page, its caption under it."""
    from PIL import Image, ImageDraw
    pic = Image.open(path)
    pic = pic.convert("L" if mono else "RGB")
    page = Image.new(pic.mode, (W, H), 255 if mono else (255, 255, 255))
    room_h = H - 2 * MARGIN - (140 if caption else 0)
    scale = min((W - 2 * MARGIN) / pic.width, room_h / pic.height)
    pic = pic.resize((int(pic.width * scale), int(pic.height * scale)), Image.LANCZOS)
    page.paste(pic, ((W - pic.width) // 2, MARGIN))
    draw = ImageDraw.Draw(page)
    if caption:
        f = _font(48, bold=True)
        cap = _wrap(draw, caption, f, W - 2 * MARGIN)[0]
        draw.text(((W - draw.textlength(cap, font=f)) / 2, MARGIN + pic.height + 50), cap,
                  font=f, fill=0)
    _footer(draw, 1, 1)
    return [page]


def save_pdf(pages, path):
    pages[0].save(path, "PDF", resolution=DPI, save_all=True, append_images=pages[1:],
                  quality=92)


# --- sending ------------------------------------------------------------------

def _room(pages, copies):
    """How many copies today's cap still allows (0: none)."""
    day = time.strftime("%Y-%m-%d")
    with _lock:
        if _today["day"] != day:
            _today.update(day=day, pages=0)
        left = PAGES_PER_DAY - _today["pages"]
        n = max(0, min(copies, left // max(1, len(pages))))
        _today["pages"] += n * len(pages)
    return n


def submit(pages, title, copies=1, mono=False):
    """Send the pages; (job id, None) or (None, what to say)."""
    if not pages:
        return None, "Nie mam czego wydrukować."
    dry = os.environ.get("LUNA_PRINT_DRY") == "1"
    dest = "dry-run" if dry else find()[0]
    if not dest:
        return None, "Nie widzę drukarki w sieci. Czy jest włączona?"
    copies = _room(pages, max(1, min(MAX_COPIES, copies)))
    if not copies:
        return None, "Na dziś wystarczy drukowania — jutro wydrukuję więcej."
    path = os.path.join(tempfile.gettempdir(), f"luna-print-{time.strftime('%H%M%S')}.pdf")
    save_pdf(pages, path)
    print(f"[print] {title!r}: {len(pages)} page(s) × {copies}"
          f"{' mono' if mono else ''} → {dest} ({path})", flush=True)
    if dry:
        return "dry-run", None
    cmd = ["lp", "-d", dest, "-n", str(copies), "-t", title[:60] or "Luna",
           "-o", "media=A4", "-o", "print-color-mode=" + ("monochrome" if mono else "color")]
    out = _run(cmd + [path], 30)
    job = re.search(r"request id is (\S+)", out or "")
    if not job:
        st = status()
        trouble = problems(st) if st else []
        return None, ("Drukarka nie przyjęła wydruku" + (f" — {trouble[0]}." if trouble else "."))
    threading.Thread(target=_watch, args=(job.group(1), path), daemon=True,
                     name="print-watch").start()
    return job.group(1), None


def _watch(job, path, secs=180):
    """Tell them if the job gets stuck (no paper, a jam); remove the file after."""
    t0, told = time.time(), False
    while time.time() - t0 < secs:
        time.sleep(5)
        queue = _run(["lpstat", "-o"], 6)
        if queue is not None and job not in queue:
            print(f"[print] {job} done in {time.time() - t0:.0f} s", flush=True)
            break
        if not told and time.time() - t0 > 30:
            st = status()
            trouble = problems(st) if st else []
            if trouble:
                told = True
                print(f"[print] {job} stuck: {trouble}", flush=True)
                _say(f"Drukarka czeka: {trouble[0]}.")
    try:
        os.remove(path)
    except OSError:
        pass


def _say(text):
    try:
        from text_to_speech import speak
        speak(text)
    except Exception as e:
        print(f"[print] couldn't say {text!r}: {e!r}", flush=True)


# --- what to print ------------------------------------------------------------

_PRINT = re.compile(
    r"^(?:luna,?\s+)?(?:(?:a\s+)?(?:czy\s+)?(?:możesz|mozesz|mogłabyś|moglabys|mogłabys)\s+"
    r"(?:mi\s+|nam\s+)?(?:proszę\s+)?(?:wydrukować|wydrukowac|drukować)|wydrukujesz|"
    r"(?:proszę\s+)?(?:wydrukuj|wydrukój|drukuj)|zrób\s+(?:mi\s+)?wydruk)"
    r"(?:\s+(?:mi|nam|proszę|prosze))*\b\s*(.*?)[\s?.!]*$", re.I)
_STATUS = re.compile(
    r"\bdrukark\w*\s+(?:działa|dziala|jest|gotowa|masz|widzisz|włączona)|"
    r"\b(?:czy|jak[aą]?)\s+(?:masz\s+|widzisz\s+|jest\s+)?(?:jak[aą]ś\s+)?drukark|"
    r"\bstan\s+drukarki|\bile\s+(?:jest\s+|mam\s+|zostało\s+)?tonera|\bco\s+z\s+drukark", re.I)
_COPIES = re.compile(r"\b(?:(\d+|dwa|dwie|trzy|cztery|pięć|piec)\s+(?:razy|kopi\w*|egzemplarz\w*|"
                     r"sztuk\w*)|w\s+(dwóch|trzech|czterech|pięciu|\d+)\s+(?:kopiach|egzemplarzach))\b",
                     re.I)
_NUM = {"dwa": 2, "dwie": 2, "dwóch": 2, "trzy": 3, "trzech": 3, "cztery": 4, "czterech": 4,
        "pięć": 5, "piec": 5, "pięciu": 5}
_MONO = re.compile(r"\b(?:czarno[\s-]?biał\w*|w\s+czerni|bez\s+kolor\w*|na\s+szaro)\b", re.I)
_PICTURE = re.compile(r"\b(?:rysun\w*|obraz\w*|zdjęci\w*|zdjęć|fotk\w*|fotograf\w*)\b", re.I)
_THIS = re.compile(r"^(?:to|ten|tę|tą|te|go|je|ją|tego|tamto|to\s+co\s+.*|to,\s+co\s+.*|"
                   r"(?:ten|to|tę|tą)\s+\w+|)$", re.I)
_LAST = re.compile(r"\bostatni\w*|\bnajnowsz\w*", re.I)
_LIST = re.compile(r"\blist[aęy]\b|\blistę\b", re.I)
_RECIPE = re.compile(r"\bprzepis\w*(?:\s+na\s+(.+))?", re.I)
_COLORING = re.compile(r"\bkolorowank\w*(?:\s+(?:z|ze|o|:)\s*(.+))?", re.I)
_TEST = re.compile(r"\bstron\w*\s+testow\w*|\btest\w*\s+drukark\w*", re.I)

COLORING_STYLE = ("Kolorowanka dla dziecka: tylko czarne, grube, czyste kontury na białym tle, "
                  "duże proste pola do pokolorowania, bez cieniowania, bez szarości, bez kolorów, "
                  "bez żadnych napisów, nic strasznego.")


def wants(text):
    return bool(_PRINT.match(text.strip()) or _STATUS.search(text))


def _copies(what):
    m = _COPIES.search(what)
    if not m:
        return 1, what
    word = (m.group(1) or m.group(2)).lower()
    n = int(word) if word.isdigit() else _NUM.get(word, 1)
    return n, (what[:m.start()] + what[m.end():]).strip(" ,")


def _list_name(what):
    import lists
    low = what.lower()
    if re.search(r"zakup", low):
        return "zakupy"
    if re.search(r"zrobieni|zadań|zadania|zadan", low):
        return "do zrobienia"
    for name in lists.get():
        if name[:4] in low:
            return name
    return "zakupy"


def _start(job, speak, title):
    """Run a slow job (a model writes it) on its own thread; job() → (title, pages, mono)."""
    def run():
        try:
            out = job()
        except Exception as e:
            print(f"[print] preparing {title!r} failed: {e!r}", flush=True)
            out = None
        if not out:
            _say("Nie udało mi się tego przygotować do druku.")
            return
        t, pages, mono, copies = out
        _, err = submit(pages, t, copies, mono)
        _say(err or "Gotowe, wydruk już idzie do drukarki.")
    threading.Thread(target=run, daemon=True, name="print-prepare").start()


def _written(what):
    """The small model writes what was asked for, for paper: (title, lines)."""
    from openai import OpenAI
    from config import OPENAI_API_KEY, OPENAI_MODEL
    c = OpenAI(api_key=OPENAI_API_KEY, timeout=30, max_retries=1)
    r = c.chat.completions.create(
        model=OPENAI_MODEL, temperature=0.5, max_tokens=1500,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content":
                   f"Ktoś w domu (rodzina z 8-letnią córką) prosi: \"wydrukuj {what}\". "
                   "Przygotuj treść do wydrukowania na 1–2 stronach A4, po polsku. Zwróć JSON "
                   '{"ok": true/false, "title": "krótki tytuł", "lines": ["linia", ...]} — '
                   'linia zaczynająca się od "## " to nagłówek, pusta linia to odstęp. '
                   "Karta pracy / zadania: z miejscem na odpowiedź (\"7 + 5 = ____\"), "
                   "bez rozwiązań. ok=false, gdy to nie nadaje się dla dziecka albo nie wiadomo, "
                   "co wydrukować."}])
    d = json.loads(r.choices[0].message.content)
    if not d.get("ok") or not d.get("lines"):
        return None
    return str(d.get("title") or what)[:80], [str(x) for x in d["lines"]][:120]


def _recipe_lines(rec):
    lines = ["## Składniki"] + [f"• {x}" for x in rec.get("ingredients", [])]
    lines += ["", "## Przygotowanie"]
    for n, s in enumerate(rec.get("steps", []), 1):
        mins = s.get("minutes") or 0
        lines.append(f"{n}. {s['text']}" + (f" ({mins} min)" if mins else ""))
    return lines


_KINDS = re.compile(r"^(?:wiersz\w*|wierszyk\w*|rymowank\w*|bajk\w*|bajeczk\w*|opowiad\w*|"
                    r"histori\w*|historyjk\w*|piosenk\w*|zagadk\w*|przepis\w*|odpowied\w*|"
                    r"list\w*|życzeni\w*|tekst\w*|jego|go|ją|je|to|ten|tę|o|z|ze|na|dla|"
                    r"tym|który|którą|co|mi|nam)$", re.I)
_NEW = re.compile(r"\b(?:now\w*|inn\w*|kolejn\w*|jeszcze\s+jed\w*)\b", re.I)


def _just_said(what):
    """Her last answer, when what they want printed is it ("wierszyk o jesieni"
    right after the poem — the model sent that, 26 Oct sweep); else None."""
    if _NEW.search(what):
        return None
    try:
        import brain
        said = re.sub(r"^\[[^\]]*\]\s*", "", brain.last_reply()).strip()
    except Exception:
        return None
    if len(said) < 60:
        return None
    words = re.findall(r"\w+", what)
    rest = [w for w in words if not _KINDS.match(w)]
    if not words or len(rest) == len(words):
        return None                                # no "wierszyk", "przepis"…: something new
    stems = {w.lower()[:5] for w in said.split() if len(w) >= 4}
    return said if all(w.lower()[:5] in stems for w in rest if len(w) >= 4) else None


def _paras(said):
    """Print lines: a poem (lines run together as "…butach, Liście…") one line
    each, else paragraphs and numbered steps."""
    if len(re.findall(r",\s+[A-ZĄĆĘŁŃÓŚŹŻ]", said)) >= 2:
        parts = re.split(r"(?<=[,.!?])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])", said)
    else:
        parts = re.split(r"\n+|(?<=[.!?:])\s+(?=\d+\.|[-•])", said)
    return [p.strip() for p in parts if p.strip()]


def handle(text, speak):
    """A print request or a question about the printer; True when it was one."""
    text = text.strip()
    if _STATUS.search(text) and not _PRINT.match(text):
        speak(say_status())
        return True
    m = _PRINT.match(text)
    if not m:
        return False
    what = m.group(1).strip(" ,")
    copies, what = _copies(what)
    mono = bool(_MONO.search(what))
    what = _MONO.sub("", what).strip(" ,")
    low = what.lower()
    print(f"[print] asked: {what!r} ×{copies}{' mono' if mono else ''}", flush=True)
    with state.lock:
        online = state.online

    if _TEST.search(low):
        st = status()
        lines = [f"Drukarka: {st['model'] if st else '?'}",
                 "Zażółć gęślą jaźń — ZAŻÓŁĆ GĘŚLĄ JAŹŃ", "0123456789", "",
                 say_status(st) if st else ""]
        return _send(speak, "Strona testowa Luny", text_pages("Strona testowa Luny", lines),
                     copies, mono, "Drukuję stronę testową.")

    m2 = _COLORING.search(low)
    if m2:
        subject = (m2.group(1) or "").strip()
        if not subject:
            speak("Jaką kolorowankę? Powiedz na przykład: wydrukuj kolorowankę z kotem.")
            return True
        import drawing

        def then(path):
            try:
                _, err = submit(image_page(path, mono=True), f"Kolorowanka: {subject}", copies,
                                True)
            except Exception as e:
                print(f"[print] colouring page failed: {e!r}", flush=True)
                err = "Kolorowanka jest na ekranie, ale nie udało się jej wydrukować."
            _say(err or "Kolorowanka gotowa, już się drukuje!")
        return drawing.draw(subject, speak, "Dobrze, rysuję kolorowankę i zaraz ją wydrukuję.",
                            style=COLORING_STYLE, then=then)

    if _LIST.search(low):
        import lists
        name = _list_name(low)
        items = lists.get(name)
        label = "zakupów" if name == "zakupy" else f"„{name}”"
        if not items:
            speak(f"Lista {label} jest pusta — nie ma czego drukować.")
            return True
        title = "Lista zakupów" if name == "zakupy" else f"Lista: {name}"
        return _send(speak, title, text_pages(title, items, boxes=True), copies, mono,
                     f"Drukuję listę {label}.")

    m3 = _RECIPE.search(low)
    if m3:
        import cooking
        c = cooking._c
        dish = (m3.group(1) or "").strip()
        if c and not dish:
            return _send(speak, c["title"], text_pages(c["title"].capitalize(), _recipe_lines(c)),
                         copies, mono, "Drukuję przepis.")
        if not dish:
            speak("Jaki przepis? Powiedz na przykład: wydrukuj przepis na naleśniki.")
            return True
        if not online:
            speak("Nie mam teraz internetu, więc nie napiszę przepisu.")
            return True
        speak(f"Dobrze, piszę przepis na {dish} i zaraz go wydrukuję.")

        def recipe():
            rec = cooking._recipe(dish)
            return rec and (rec["title"], text_pages(rec["title"].capitalize(),
                                                     _recipe_lines(rec)), mono, copies)
        _start(recipe, speak, dish)
        return True

    if _PICTURE.search(low) or _THIS.match(low):
        import gallery
        import drawing
        shown = gallery.current()
        if shown and shown.get("path") and os.path.exists(shown["path"]) \
                and not _LAST.search(low):
            cap = str(shown.get("caption") or "")
            return _send(speak, cap or "Obrazek", image_page(shown["path"], cap, mono),
                         copies, mono, "Drukuję to, co jest na ekranie.")
        if _PICTURE.search(low) and re.search(r"rysun|obraz", low) and drawing.saved():
            path = drawing.saved()[-1]
            return _send(speak, "Rysunek", image_page(path, "", mono), copies, mono,
                         "Drukuję mój ostatni rysunek.")
        if _PICTURE.search(low):
            speak("Najpierw pokaż mi to na ekranie, na przykład: pokaż zdjęcie żyrafy. "
                  "Potem powiedz: wydrukuj to.")
            return True
        import brain
        said = re.sub(r"^\[[^\]]*\]\s*", "", brain.last_reply()).strip()
        if len(said) < 60:
            speak("Nie wiem, co wydrukować. Powiedz na przykład: wydrukuj listę zakupów "
                  "albo wydrukuj kolorowankę z kotem.")
            return True
        return _send(speak, "Od Luny", text_pages("Od Luny", _paras(said)), copies, mono,
                     "Drukuję to, co przed chwilą mówiłam.")

    said = _just_said(low)
    if said:                                       # "wydrukuj wierszyk o jesieni" — the one she said
        return _send(speak, "Od Luny", text_pages("Od Luny", _paras(said)), copies, mono,
                     "Drukuję to, co przed chwilą mówiłam.")
    import webphoto
    if webphoto.NOT_FOR_KIDS.search(low):
        speak("Tego nie wydrukuję — może coś wesołego?")
        return True
    if not online:
        speak("Nie mam teraz internetu, więc tego nie przygotuję.")
        return True
    speak("Dobrze, przygotowuję i zaraz wydrukuję.")

    def written():
        got = _written(what)
        return got and (got[0], text_pages(got[0], got[1]), mono, copies)
    _start(written, speak, what)
    return True


def _send(speak, title, pages, copies, mono, said):
    _, err = submit(pages, title, copies, mono)
    if err:
        speak(err)
    else:
        n = f" {copies} razy" if copies > 1 else ""
        speak(said.rstrip(".") + n + ".")
    return True
