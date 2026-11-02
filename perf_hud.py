"""What the Pi is doing, in a corner of the screen (Ustawienia → Ekran →
Wydajność na ekranie, or LUNA_PERF_HUD=1): frames drawn and how long they
take, the GPU's real busy time (the kernel's DRM fdinfo), the CPU per core,
Luna's busiest threads, temperature, clocks, throttling, memory.

Sampled once a second by its own thread; the frame only blits a ready panel."""
import os
import subprocess
import threading
import time

import pygame

_lock = threading.Lock()
_lines = []                 # the panel's text, the newest sample
_last_draw = [0.0]          # the thread samples only while the panel is shown
_thread = None
_panel = [None, None]       # (lines it shows, its surface)
_font = None
_asked = [0]               # the frame rate asked for


def wanted():
    if os.environ.get("LUNA_PERF_HUD") == "1":
        return True
    try:
        import settings
        return bool(settings.get("perf_hud", False))
    except Exception:
        return False


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def _cpu_times():
    """[(busy, total)] for all cores, then each."""
    out = []
    for line in _read("/proc/stat").splitlines():
        if not line.startswith("cpu"):
            break
        v = [int(x) for x in line.split()[1:]]
        idle = v[3] + (v[4] if len(v) > 4 else 0)
        out.append((sum(v) - idle, sum(v)))
    return out


def _gpu_fd():
    """Our own DRM file of the V3D (its fdinfo holds the GPU's busy ns)."""
    d = "/proc/self/fdinfo"
    try:
        for fd in os.listdir(d):
            t = _read(os.path.join(d, fd))
            if "drm-driver:\tv3d" in t and "drm-engine-render" in t:
                return os.path.join(d, fd)
    except OSError:
        pass
    return None


def _gpu_ns(path):
    ns = 0
    for line in _read(path).splitlines() if path else ():
        if line.startswith("drm-engine-"):
            try:
                ns += int(line.split(":")[1].split()[0])
            except (IndexError, ValueError):
                pass
    return ns


def _threads():
    """{name: cpu ticks} of this process's threads."""
    names = {t.native_id: t.name for t in threading.enumerate()}
    out = {}
    base = "/proc/self/task"
    try:
        tids = os.listdir(base)
    except OSError:
        return out
    for tid in tids:
        s = _read(f"{base}/{tid}/stat")
        try:
            f = s[s.rindex(")") + 2:].split()
            ticks = int(f[11]) + int(f[12])
        except (ValueError, IndexError):
            continue
        nm = names.get(int(tid)) or s[s.find("(") + 1:s.rindex(")")]
        nm = nm.replace("MainThread", "main").split(" (")[0]
        out[nm] = out.get(nm, 0) + ticks
    return out


def _vc(*args):
    try:
        return subprocess.run(["vcgencmd", *args], capture_output=True, text=True,
                              timeout=2).stdout.strip()
    except Exception:
        return ""


_THROTTLE = ((0, "za niskie napięcie"), (1, "zegar ograniczony"), (2, "dławienie"),
             (3, "limit temp."))


def _throttle_text(v):
    try:
        n = int(v.split("=")[1], 16)
    except (IndexError, ValueError):
        return None
    now = [t for b, t in _THROTTLE if n >> b & 1]
    past = [t for b, t in _THROTTLE if n >> (b + 16) & 1 and t not in now]
    if now:
        return "TERAZ: " + ", ".join(now)
    return ("było: " + ", ".join(past)) if past else "bez dławienia"


def _loop():
    import robot_face as rf
    hz = os.sysconf("SC_CLK_TCK")
    gpu = _gpu_fd()
    prev = None
    vc_t, v3d, thr = 0.0, "", None
    while True:
        time.sleep(1.0)
        now = time.monotonic()
        if now - _last_draw[0] > 3.0:          # not shown: nothing sampled
            prev = None
            continue
        gpu = gpu or _gpu_fd()                # (opened after the panel came on)
        st = rf.frame_stats
        snap = {"t": now, "cpu": _cpu_times(), "gpu": _gpu_ns(gpu), "thr": _threads(),
                "frames": st["frames"], "gl": st["gl"], "swap": st["swap"],
                "upd": st["update"] + st["face"] + st["compose"], "gaps": list(st["gaps"])}
        if now - vc_t > 5.0:                   # (a process each: not every second)
            vc_t = now
            hzv = _vc("measure_clock", "v3d")
            v3d = f"{int(hzv.split('=')[1]) // 1_000_000} MHz" if "=" in hzv else "?"
            thr = _throttle_text(_vc("get_throttled"))
        if prev:
            dt = now - prev["t"]
            nf = max(1, snap["frames"] - prev["frames"])
            fps = (snap["frames"] - prev["frames"]) / dt
            gaps = [a - b for a, b in zip(snap["gaps"], prev["gaps"])]
            ng = max(1, sum(gaps[1:]))
            gtxt = " ".join(f"{k}×{100 * g // ng}%" for k, g in enumerate(gaps) if k and g)
            cores = [100 * (b1 - b0) / max(1, t1 - t0)
                     for (b1, t1), (b0, t0) in zip(snap["cpu"], prev["cpu"])]
            busy = sorted(((v - prev["thr"].get(k, v)) / hz / dt * 100, k)
                          for k, v in snap["thr"].items())[::-1]
            mine = sum(b for b, _ in busy)
            gpu_pct = (snap["gpu"] - prev["gpu"]) / 1e9 / dt * 100 if gpu else None
            mem = {ln.split(":")[0]: int(ln.split()[1]) for ln in _read("/proc/meminfo").splitlines()
                   if ln.split(":")[0] in ("MemTotal", "MemAvailable")}
            rss = 0
            for ln in _read("/proc/self/status").splitlines():
                if ln.startswith("VmRSS:"):
                    rss = int(ln.split()[1])
            temp = int(_read("/sys/class/thermal/thermal_zone0/temp") or 0) / 1000
            arm = int(_read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq") or 0) // 1000
            fpsw = _asked[0]
            lines = [
                f"{fps:4.1f} kl/s (cel {fpsw})  odświeżeń/klatkę {gtxt}",
                f"klatka: CPU {1000 * (snap['upd'] - prev['upd']) / nf:4.1f} ms, "
                f"czeka na GPU {1000 * (snap['gl'] - prev['gl']) / nf:4.1f} ms, "
                f"flip {1000 * (snap['swap'] - prev['swap']) / nf:3.1f} ms",
                (f"GPU {gpu_pct:3.0f}% zajęte  V3D {v3d}" if gpu_pct is not None
                 else f"GPU ?  V3D {v3d}"),
                f"CPU {cores[0]:3.0f}%  [" + " ".join(f"{c:3.0f}" for c in cores[1:])
                + f"]  Luna {mine:3.0f}%",
                "wątki: " + "  ".join(f"{k} {b:.0f}%" for b, k in busy[:4] if b >= 1),
                f"{temp:.1f}°C  ARM {arm} MHz  {thr or ''}",
                f"RAM wolne {mem.get('MemAvailable', 0) / 1048576:.1f}/"
                f"{mem.get('MemTotal', 0) / 1048576:.1f} GB  Luna {rss // 1024} MB",
            ]
            with _lock:
                _lines[:] = lines
        prev = snap


def draw(surf, fps_asked):
    """The panel in the bottom-left corner, if it's on (a sample a second)."""
    global _thread, _font
    if not wanted():
        return
    _asked[0] = fps_asked
    _last_draw[0] = time.monotonic()
    if _thread is None:
        _thread = threading.Thread(target=_loop, name="perf-hud", daemon=True)
        _thread.start()
    with _lock:
        lines = list(_lines) or ["wydajność: zbieram pomiary…"]
    if _panel[0] != lines:
        if _font is None:
            _font = pygame.font.SysFont("dejavusansmono,monospace", 12)
        rows = [_font.render(t, True, (235, 230, 215)) for t in lines]
        w = max(r.get_width() for r in rows) + 12
        h = sum(r.get_height() for r in rows) + 8
        p = pygame.Surface((w, h), pygame.SRCALPHA)
        p.fill((0, 0, 0, 170))
        y = 4
        for r in rows:
            p.blit(r, (6, y))
            y += r.get_height()
        _panel[:] = [lines, p]
    p = _panel[1]
    surf.blit(p, (6, surf.get_height() - p.get_height() - 6))
