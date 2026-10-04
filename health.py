"""
health.py — is Luna's cloud reachable, and how is she doing?

  • state.online goes False when a model call fails and back True after the
    next success, or when a cheap TCP probe to the API succeeds (every
    HEALTH_PROBE_SECS while offline). robot_face shows a small "no cloud"
    icon while offline, and brain plays a pre-recorded apology instead of
    going silent (TTS needs the network too).
  • Once an hour a "[health]" line in the log: temperature, load, memory,
    answers and their average time, failures.
"""

import socket
import threading
import time

import body
from shared_state import state
from config import HEALTH_PROBE_SECS, HEALTH_LOG_SECS

_lock = threading.Lock()
_stats = {"replies": 0, "secs": 0.0, "failures": 0}
_api = {}                    # API calls this hour, by kind (cost at a glance)
_API_KINDS = (("/chat/completions", "chat"), ("/audio/speech", "tts"),
              ("/audio/transcriptions", "stt"), ("/models", "ping"))


def _count_api_calls():
    """Every OpenAI client talks through one HTTP library (httpx2 in the SDK
    on the Pi, httpx in older ones); counting there sees all of them —
    brain, TTS, STT, memory, sounds — without touching any call site."""
    import importlib
    for name in ("httpx2", "httpx"):
        try:
            lib = importlib.import_module(name)
        except ImportError:
            continue
        send = lib.Client.send
        if getattr(send, "_luna_counted", False):
            continue

        def counted(self, request, *a, _send=send, **kw):
            path = str(request.url.path)
            kind = next((k for p, k in _API_KINDS if path.endswith(p)), None)
            if kind and "openai" in str(request.url.host):
                with _lock:
                    _api[kind] = _api.get(kind, 0) + 1
            return _send(self, request, *a, **kw)

        counted._luna_counted = True
        lib.Client.send = counted


def note_reply(ok, secs=0.0):
    """brain.process reports every answer (ok) or failure."""
    with _lock:
        if ok:
            _stats["replies"] += 1
            _stats["secs"] += secs
        else:
            _stats["failures"] += 1
    _set_online(ok)


def _set_online(ok):
    with state.lock:
        was = state.online
        state.online = ok
    if was != ok:
        print(f"[health] cloud {'reachable again' if ok else 'UNREACHABLE'}", flush=True)


def _probe():
    try:
        with socket.create_connection(("api.openai.com", 443), timeout=4):
            return True
    except OSError:
        return False


def _mem_used():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0])
        return round(100 * (1 - info["MemAvailable"] / info["MemTotal"]))
    except (OSError, KeyError, ValueError):
        return None


def _log():
    with _lock:
        s = dict(_stats)
        _stats.update(replies=0, secs=0.0, failures=0)
        api = ", ".join(f"{k} {v}" for k, v in sorted(_api.items())) or "none"
        _api.clear()
    avg = f"{s['secs'] / s['replies']:.1f}s" if s["replies"] else "-"
    t = body.cpu_temp()
    audio = ""
    try:
        from openai_tts import tts
        if tts._out:
            u, m = tts._out.stats()
            audio = f", audio: {u} underruns, max stall {m * 1000:.0f} ms"
    except Exception:
        pass
    with state.lock:
        light = state.light
    if light is not None:
        audio += f", light {light:.2f}"
    print(f"[health] {time.strftime('%H:%M')} CPU {t:.0f}°C, load {body.load_percent()}%, "
          f"RAM {_mem_used()}%, last hour: {s['replies']} answers (avg {avg}), "
          f"{s['failures']} failures{audio}; API calls: {api}", flush=True)


def _loop():
    last_log = time.time()
    while True:
        try:
            with state.lock:
                online = state.online
            if not online and _probe():
                _set_online(True)
            if time.time() - last_log >= HEALTH_LOG_SECS:
                last_log = time.time()
                _log()
        except Exception as e:
            print(f"[health] loop error: {e}")
        time.sleep(HEALTH_PROBE_SECS)


def _warm_up():
    """The first OpenAI call in a process costs ~2 s extra on the Pi (the
    SDK loads its modules lazily, plus the TLS handshake) — measured: first
    TTS byte 2.5 s cold vs 0.4-0.7 s warm. Pay that at start-up instead of on
    your first question: one free request per client, and touch the API
    resources each module uses."""
    t0 = time.time()
    clients = []
    try:
        import brain
        clients.append(("brain", brain._client))
    except Exception:
        pass
    try:
        from openai_tts import tts
        clients.append(("tts", tts._client))
    except Exception:
        pass
    try:
        import speech_to_text
        clients.append(("stt", speech_to_text._cloud))
    except Exception:
        pass
    from config import OPENAI_MODEL
    for name, c in clients:
        if c is None:
            continue
        try:
            c.models.retrieve(OPENAI_MODEL)
            _ = (c.chat.completions, c.audio.speech, c.audio.transcriptions)
        except Exception as e:
            print(f"[health] warm-up {name}: {e}")
    print(f"[health] cloud clients warmed up in {time.time() - t0:.1f}s", flush=True)


def start_health():
    _count_api_calls()
    threading.Thread(target=_warm_up, daemon=True, name="warm-up").start()
    threading.Thread(target=_loop, daemon=True, name="health").start()
