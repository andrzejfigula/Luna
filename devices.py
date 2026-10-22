"""
devices.py — the speaker, microphone and camera: what's plugged in now, and
which one she uses.

The settings page (tab "Urządzenia") picks one; data/settings.json keys
"speaker" / "mic" / "camera" win over .env (LUNA_SPEAKER / LUNA_MIC /
LUNA_CAMERA). A pick that's unplugged falls back to .env's choice, and
LUNA_SPEAKER may list fallbacks itself: LUNA_SPEAKER=pebble,jack (the first
present wins). openai_tts re-checks the speaker every few seconds, so pulling
the USB speaker moves her to the jack and plugging it back moves her back.
"""

import glob
import json
import os
import re
import subprocess
import threading
import time

import settings
from config import AUDIO_OUTPUT_DEVICE, AUDIO_INPUT_DEVICE, CAMERA_ID

# LUNA_SPEAKER aliases → substrings of the PipeWire sink's node.name
SINK_ALIASES = {
    "jack":       ["mailbox", "headphones"],   # Pi's 3.5 mm output
    "headphones": ["mailbox", "headphones"],
    "hdmi":       ["hdmi"],
    "bluetooth":  ["bluez_output"],
    "bt":         ["bluez_output"],
}

speaker_changed = threading.Event()     # the page picked one: re-check now
LIST_SECS = 3.0                         # the page redraws every frame; lists are cached
_lists = {}


def _cached(kind, fn):
    hit = _lists.get(kind)
    if hit and time.time() - hit[0] < LIST_SECS:
        return hit[1]
    out = fn()
    _lists[kind] = (time.time(), out)
    return out


def _pw_dump():
    return json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True,
                                     timeout=5).stdout or "[]")


# ── speaker ───────────────────────────────────────────────────────────────────

def _sinks(dump=None):
    dump = _pw_dump() if dump is None else dump
    return [o["info"]["props"] for o in dump
            if o.get("info", {}).get("props", {}).get("media.class") == "Audio/Sink"]


def sink_label(props):
    name = props.get("node.name", "")
    if "mailbox" in name or "headphones" in name.lower():
        return "Gniazdo słuchawkowe"
    if "hdmi" in name:
        return "HDMI"
    desc = props.get("node.description") or name
    return re.sub(r"\s+(Analog|Digital)?\s*Stereo$", "", desc)


def speakers():
    """[(node.name, label)] of the PipeWire sinks now."""
    def read():
        try:
            return [(s.get("node.name", ""), sink_label(s)) for s in _sinks()]
        except Exception:
            return []
    return _cached("speakers", read)


def speaker_chain():
    """The specs to try, in order: the page's pick, then .env's list."""
    chain = [settings.get("speaker")] if settings.get("speaker") else []
    return chain + [s.strip() for s in str(AUDIO_OUTPUT_DEVICE or "default").split(",")
                    if s.strip()]


def match_sink(spec, sinks):
    names = [s.get("node.name", "") for s in sinks]
    if spec in names:
        return spec
    for needle in SINK_ALIASES.get(spec.lower(), [spec.lower()]):
        for s in sinks:
            hay = (s.get("node.name", "") + " " + s.get("node.description", "")).lower()
            if needle in hay:
                return s["node.name"]
    return None


def resolve_sink(chain=None, sinks=None):
    """The node name for pw-play --target, or None (the default output)."""
    chain = speaker_chain() if chain is None else chain
    if sinks is None:
        try:
            sinks = _sinks()
        except Exception:
            return None                    # PipeWire not up yet: re-checked soon
    for spec in chain:
        if spec.lower() == "default":
            return None
        hit = match_sink(spec, sinks)
        if hit:
            return hit
    return None


AUDIBLE_FLOOR = 0.25    # wpctl's cubic scale: 0.10 is -60 dB, silent in practice
LIFT_TO = 0.50

# Her volume is remembered (settings "volume": a voice command, the settings
# page, the knob) and put back whenever the speaker (re)appears. 22 Oct: the
# Pebble drops off USB now and then (and comes back over Bluetooth, or USB);
# WirePlumber then restores the level it saved for that route — 0.25, once
# 0.10 — and she stayed quiet: the same node.name, so nothing re-checked it.


def remembered_volume():
    v = settings.get("volume")
    return float(v) if isinstance(v, (int, float)) else None


def remember_volume(v):
    settings.put("volume", round(float(v), 2))


def node_id(sink, dump=None):
    """The PipeWire node id of a sink (changes when it reconnects), or None."""
    try:
        dump = _pw_dump() if dump is None else dump
    except Exception:
        return None
    return next((str(o["id"]) for o in dump
                 if o.get("info", {}).get("props", {}).get("node.name") == sink), None)


def get_volume(node):
    """(volume, muted) of a node ("@DEFAULT_AUDIO_SINK@" works), or (None, False)."""
    try:
        out = subprocess.run(["wpctl", "get-volume", str(node)], capture_output=True,
                             text=True, timeout=5).stdout
        m = re.search(r"([\d.]+)", out)
        return (float(m[1]) if m else None), "MUTED" in out
    except Exception:
        return None, False


def set_volume(node, v):
    subprocess.run(["wpctl", "set-volume", str(node), f"{v:.2f}"], capture_output=True,
                   timeout=5)


def make_default(sink):
    """Make her speaker PipeWire's default too — the Pebble's knob (USB HID
    volume keys → labwc → panel) and the panel slider turn the default — and
    give it her remembered volume (or lift it if it was left near silent, if
    none is remembered yet). Returns the volume it set, or None."""
    if not sink:
        return None
    try:
        node = node_id(sink)
        if node is None:
            return None
        subprocess.run(["wpctl", "set-default", node], capture_output=True, timeout=5)
        return restore_volume(node, sink)
    except Exception as e:
        print(f"[TTS] default speaker not set ({e})", flush=True)
    return None


def restore_volume(node, sink=""):
    """Put her remembered volume back on a node (unmuted). The level set, or None."""
    cur, muted = get_volume(node)
    if muted:
        subprocess.run(["wpctl", "set-mute", str(node), "0"], capture_output=True, timeout=5)
        print(f"[vol] {sink or node} was muted — unmuted", flush=True)
    want = remembered_volume()
    if want is None:
        want = LIFT_TO if cur is not None and cur < AUDIBLE_FLOOR else None
    if want is None or cur is None or abs(cur - want) < 0.015:
        return want if muted else None
    set_volume(node, want)
    print(f"[vol] {sink or node} was at {cur:.2f} — back to {want:.2f}", flush=True)
    return want


class VolumeWatch:
    """Every speaker check (openai_tts, ~10 s): the speaker came back as a
    new node → her volume put back; its volume moved and it wasn't her →
    the knob or the panel: kept (remembered) — unless it fell near silent,
    which is undone. Every change is logged ("[vol]")."""

    def __init__(self):
        self.node = None
        self.seen = None

    def check(self, sink, dump=None):
        node = node_id(sink, dump) if sink else "@DEFAULT_AUDIO_SINK@"
        if node is None:
            return
        if node != self.node:
            if self.node is not None:
                print(f"[vol] {sink} reconnected (node {self.node} → {node})", flush=True)
                restore_volume(node, sink)
            self.node = node
            self.seen = get_volume(node)[0]
            return
        cur, muted = get_volume(node)
        if cur is None:
            return
        mine = remembered_volume()
        if muted or (cur < AUDIBLE_FLOOR and (mine is None or mine >= AUDIBLE_FLOOR)):
            print(f"[vol] {sink or 'speaker'} fell to {cur:.2f}{' (muted)' if muted else ''},"
                  " not by her — undone", flush=True)
            restore_volume(node, sink)
            self.seen = get_volume(node)[0]
            return
        if self.seen is not None and abs(cur - self.seen) >= 0.015 and (
                mine is None or abs(cur - mine) >= 0.015):
            print(f"[vol] {sink or 'speaker'} turned {self.seen:.2f} → {cur:.2f} "
                  "(the knob or the panel) — kept", flush=True)
            remember_volume(cur)
        self.seen = cur


def move_our_streams(sink):
    """Move the pw-play streams Luna has open (radio, sleep sounds, her voice)
    to the sink — no restart of what's playing."""
    if not sink:
        return 0
    try:
        dump = _pw_dump()
    except Exception:
        return 0
    mine, moved = str(os.getpid()), 0
    for o in dump:
        p = o.get("info", {}).get("props", {})
        if p.get("media.class") != "Stream/Output/Audio":
            continue
        try:
            with open(f"/proc/{p.get('application.process.id')}/stat") as f:
                ppid = f.read().rsplit(")", 1)[1].split()[1]
        except (OSError, IndexError):
            continue
        if ppid == mine:
            subprocess.run(["pw-metadata", str(o["id"]), "target.object", sink],
                           capture_output=True, timeout=5)
            moved += 1
    return moved


# ── microphone ────────────────────────────────────────────────────────────────

def mics():
    """[(name, name)] of the sound cards with a capture device (/proc/asound);
    the name is what sounddevice's device names start with."""
    def read():
        out = []
        try:
            with open("/proc/asound/cards") as f:
                lines = f.read().splitlines()
        except OSError:
            return out
        for line in lines:
            m = re.match(r"\s*(\d+) \[[^\]]*\]: \S+ - (.+)$", line)
            if m and glob.glob(f"/proc/asound/card{m[1]}/pcm*c"):
                out.append((m[2].strip(), m[2].strip()))
        return out
    return _cached("mics", read)


def mic_specs():
    """The microphones to try, in order: the page's pick, then .env's."""
    pick = settings.get("mic")
    return [s for s in (pick, AUDIO_INPUT_DEVICE) if s is not None and s != ""]


# ── camera ────────────────────────────────────────────────────────────────────

def _num(path):
    m = re.search(r"(\d+)$", path)
    return int(m[1]) if m else 0


def cameras():
    """[(name, name)] of the video capture devices (not the Pi's codec / ISP nodes)."""
    def read():
        out = []
        for d in sorted(glob.glob("/sys/class/video4linux/video*"), key=_num):
            try:
                with open(d + "/name") as f:
                    name = f.read().strip()
                with open(d + "/index") as f:
                    idx = f.read().strip()
            except OSError:
                continue
            if idx == "0" and not name.startswith(("bcm2835-", "rpi-", "pispbe")):
                out.append((name, name))
        return out
    return _cached("cameras", read)


def camera_path(name):
    """/dev/videoN of the camera called name (numbers change on a replug)."""
    for d in sorted(glob.glob("/sys/class/video4linux/video*"), key=_num):
        try:
            with open(d + "/name") as f:
                n = f.read().strip()
            with open(d + "/index") as f:
                idx = f.read().strip()
        except OSError:
            continue
        if n == name and idx == "0":
            return "/dev/" + os.path.basename(d)
    return None


def camera_ids():
    """The cameras to try, in order: the page's pick, .env's, then 0-2."""
    pick = settings.get("camera")
    out = [camera_path(pick)] if pick else []
    for c in (CAMERA_ID, 0, 1, 2):
        if c is not None and c != "" and c not in out:
            out.append(c)
    return [c for c in out if c is not None]


# ── the settings page's rows ─────────────────────────────────────────────────

AUTO = "Automatycznie"


def options(kind):
    """[(key, label)] for the page: "" (automatic: .env's choice) first."""
    found = {"speaker": speakers, "mic": mics, "camera": cameras}[kind]()
    pick = settings.get(kind)
    if pick and pick not in [k for k, _ in found]:
        found = found + [(pick, f"{pick} (odłączony)")]
    return [("", AUTO)] + found


def pick_next(kind):
    """A tap: the next device. Returns its label."""
    opts = options(kind)
    keys = [k for k, _ in opts]
    cur = settings.get(kind) or ""
    i = keys.index(cur) if cur in keys else 0
    key, label = opts[(i + 1) % len(opts)]
    settings.put(kind, key or None)
    if kind == "speaker":
        speaker_changed.set()
    return label


def now_label(kind):
    """What she uses right now (the page's "teraz: …")."""
    import sys
    if kind == "speaker":
        tts = getattr(sys.modules.get("openai_tts"), "tts", None)
        sink = getattr(tts, "_sink", None)
        return dict(speakers()).get(sink, sink) if sink else "domyślne wyjście"
    if kind == "mic":
        name = getattr(sys.modules.get("speech_to_text"), "_mic_name", [None])[0]
        return name.split(":")[0] if name else "brak"
    cam = getattr(sys.modules.get("camera_thread"), "_opened", [None])[0]
    if cam is None:
        return "brak"
    path = cam if isinstance(cam, str) else f"/dev/video{cam}"
    try:
        with open(f"/sys/class/video4linux/{os.path.basename(path)}/name") as f:
            return f.read().strip()
    except OSError:
        return path
