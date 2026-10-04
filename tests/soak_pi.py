"""Soak test ON THE PI: 40 mixed utterances through the real pipeline (model,
TTS, persistent audio, renderer) while the face renders. Uses scratch files
for memory/timers/lists/settings; restores the volume. Costs a few cents of
API calls. Not picked up by unittest discovery (no test_ prefix).

    ./stop.sh && nice -n 10 ./venv/bin/python -u tests/soak_pi.py; ./run.sh &
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import os, sys, time, threading, traceback, resource, random
os.environ.update(XDG_RUNTIME_DIR="/run/user/1000", WAYLAND_DISPLAY="wayland-0",
                  SDL_VIDEODRIVER="wayland")
import tempfile
os.environ["LUNA_DATA_DIR"] = tempfile.mkdtemp(prefix="luna-soak-")  # never the real data
import memory
memory.consolidate = lambda: None                 # no extra API calls

import sounds; sounds._warm()
import brain, commands, idle_engine
from text_to_speech import speak, play_sound
from openai_tts import tts
from shared_state import state
brain.THINK_SOUND_CHANCE = 0.3

vol0 = commands.get_volume()
U = [
    "Cześć Luna, jak się masz?", "Ile to jest siedemnaście razy trzy?",
    "Ciszej", "Głośniej", "Dopisz jajka i masło do listy zakupów.",
    "Co mam na liście zakupów?", "Nastaw minutnik na 15 minut na herbatę.",
    "Ile zostało na minutniku?", "Pokaż zegar", "Opowiedz mi krótką bajkę o kocie.",
    "Powtórz", "Mów wolniej", "Jaka jest stolica Australii?", "Mów normalnie",
    "Pokaż przypomnienia", "Wyłącz minutnik.", "Co potrafisz?",
    "Jaka będzie jutro pogoda?", "Skreśl masło.", "Opowiedz dowcip.",
    "Co widzisz?", "Jak się czujesz?", "Przypomnij mi o 23:50 żeby iść spać.",
    "Usuń to przypomnienie.", "Dzięki, to wszystko", "Luna, o czym rozmawialiśmy?",
    "Zaproponuj imię dla kota.", "Wyjaśnij krótko, czym jest fotosynteza.",
    "Pokaż listę zakupów", "Wyczyść listę zakupów.", "Która godzina?",
    "Czy lubisz muzykę?", "Mów szybciej", "Mów normalnie", "Co to jest pomodoro?",
    "Jak masz na imię?", "Co powiedziałaś?", "Opowiedz coś ciekawego o morzu.",
    "Dobra, dzięki", "Pa!",
]
errors, times, rss = [], [], []
done = threading.Event()


def route(text):
    if idle_engine.check_mute(text):
        return
    if memory.check_forget(text):
        return
    if commands.handle(text, speak, play_sound):
        return
    brain.process(text)


def worker():
    tts._out.stats()
    for i, u in enumerate(U):
        with state.lock:
            state.conversation_active = True
            state.last_activity_time = time.time()
        t0 = time.time()
        try:
            route(u)
        except Exception:
            errors.append((u, traceback.format_exc()))
        times.append(time.time() - t0)
        with state.lock:
            state.overlay = None
        if i % 10 == 9:
            r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
            rss.append(r)
            u_, m_ = tts._out.stats()
            print(f"--- {i + 1} done, max RSS {r} MB, underruns {u_}, max stall {m_ * 1000:.0f} ms",
                  flush=True)
        time.sleep(0.5)
    done.set()


threading.Thread(target=worker, daemon=True).start()
from robot_face import RobotFace
face = RobotFace()
from face_renderer import EMOTION_MAP
while not done.is_set():
    with state.lock:
        emo, ov = state.emotion, state.face_override
    face.set_state(ov or EMOTION_MAP.get(emo, "neutral"))
    try:
        face.draw()
    except Exception:
        errors.append(("render", traceback.format_exc()))
        time.sleep(0.2)

commands.set_volume(vol0)
print(f"utterances {len(U)}, errors {len(errors)}, avg {sum(times) / len(times):.1f}s, "
      f"max {max(times):.1f}s, RSS {rss}", flush=True)
for u, tb in errors[:5]:
    print("ERROR in", u, tb[-600:], flush=True)
print("SOAK DONE")
