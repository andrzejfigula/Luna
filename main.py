import os
import sys
import time
import signal
import threading

from config import PI_MODEL

if PI_MODEL:
    print(f"[Luna] Running on Raspberry Pi {PI_MODEL} "
          f"(started {time.strftime('%H:%M:%S')})", flush=True)

from camera_thread import start_camera
start_camera()
time.sleep(0.5)

from vision_module import start_vision
start_vision()
time.sleep(1.0)

from gesture_module import start_gesture
start_gesture()

from behavior_engine import start_behavior
start_behavior()

from touch_module import start_touch
start_touch()

from idle_engine import start_idle, check_mute
start_idle()

from memory import start_memory, check_forget
start_memory()

import brain as _brain               # a conversation cut by a restart goes on
if _brain.load_history():
    print(f"[brain] {len(_brain._history)} recent turns back from before the restart",
          flush=True)

from sounds import start_sounds
start_sounds()

import commands
commands.start_commands()

import messages
messages.refresh()

from display import start_display
start_display()

from timers import start_timers
start_timers()

from weather import start_weather
start_weather()

from health import start_health
start_health()

from watchdog import start_watchdog    # a freeze ends in a restart, with the stacks logged
start_watchdog()

from backup import start_backup        # a copy a day of what she has learned
start_backup()

import random

from speech_to_text import listen, WAKE_ACK
from text_to_speech import speak, play_sound
from brain import process, note_local
from shared_state import state
from config import (WAKE_REPLIES, ECHO_GUARD_WINDOW,
                    ECHO_RUN_THRESH, ECHO_OVERLAP_THRESH,
                    WAKE_SOUND_CHANCE)


def _is_self_echo(text):
    """Her own voice coming back through the mic? (echo.py)"""
    import echo
    with state.lock:
        last      = state.last_spoken_text
        last_time = state.last_spoken_time
    if not last or (time.time() - last_time) > ECHO_GUARD_WINDOW:
        return False
    return echo.is_echo(text, last, ECHO_RUN_THRESH, ECHO_OVERLAP_THRESH)


def _stamp_activity():
    """restart.sh waits until nobody has talked to her for a while."""
    try:
        with open("/tmp/luna_last_activity", "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def _logged(said):
    """speak() that also remembers what was said (for note_local)."""
    def say(text, **kw):
        said.append(text)
        return speak(text, **kw)
    return say


_last_oops = 0.0      # when she last said something went wrong


def voice_loop():
    while True:
        try:
            text = listen()
            try:
                if text == WAKE_ACK:
                    commands.wake_up("wake word")
                    # wake word alone ("Luna!") — short acknowledgement; a
                    # quick "hm?" is instant, a sentence needs a TTS round trip
                    if not (random.random() < WAKE_SOUND_CHANCE
                            and play_sound("huh", can_drop=False)):
                        speak(random.choice(WAKE_REPLIES))
                elif text:
                    with state.lock:                     # subtitles: what she heard
                        state.caption = ("you", text, time.time() + 6.0)
                    _stamp_activity()
                    if messages.armed():
                        # "nagraj wiadomość" — this sentence IS the message
                        import speech_to_text
                        messages.store(speech_to_text.last_utterance_pcm, text)
                        speak("Zapisałam wiadomość.")
                        continue
                    import voicefx
                    if voicefx.armed():
                        # "zmień mój głos" — this sentence comes back changed
                        import speech_to_text
                        from text_to_speech import play_clip
                        voicefx.play(speech_to_text.last_utterance_pcm, speak, play_clip)
                        continue
                    if check_mute(text):
                        pass          # "Luna, cicho" — handled, nothing to ask
                    elif forget_reply := check_forget(text):
                        speak(forget_reply)   # never goes near the model
                    elif handled := commands.handle(text, _logged(said := []), play_sound):
                        if handled != "recorded":
                            note_local(text, said)   # the model learns what happened
                    elif _is_self_echo(text):
                        print(f"[Luna] Ignoring self-echo: \"{text}\"")
                    else:
                        # speak() serializes internally — an answer is never
                        # dropped
                        process(text)
            finally:
                # never leave the mode stuck on "processing" (e.g. empty input)
                with state.lock:
                    if not state.speaking and state.luna_mode == "processing":
                        state.luna_mode = "idle"
                # radio on: no open window after an answer — the next thing
                # she hears is the radio, so every command needs "Luna"
                if text and text != WAKE_ACK:
                    import radio
                    if radio.playing():
                        with state.lock:
                            state.conversation_active = False
                            state.convo_closed_hard = True
                            state.listening = False
                        print("[Luna] radio on — window closed, say \"Luna\" next time",
                              flush=True)
        except Exception as e:
            # an unexpected error must never kill the voice thread — that
            # would leave Luna permanently deaf until restart
            import traceback
            print(f"[Luna] voice loop error (recovering): {e}", flush=True)
            traceback.print_exc()
            with state.lock:
                state.speaking  = False
                state.listening = False
                state.luna_mode = "idle"
            # say so (at most once a minute) — silence looked like she hadn't heard
            global _last_oops
            if time.time() - _last_oops > 60:
                _last_oops = time.time()
                try:
                    speak("Ups, coś mi się pomieszało. Spróbuj jeszcze raz.")
                except Exception:
                    pass
            time.sleep(1.0)
        time.sleep(0.05)


threading.Thread(target=voice_loop, daemon=True).start()


def _shutdown(*args):
    # say WHY: a signal from outside, or the renderer loop ending (a QUIT
    # event or ESC). Without this an unexplained restart looks identical
    # either way in the log.
    why = f"signal {args[0]}" if args and isinstance(args[0], int) else "renderer stopped"
    print(f"\n[Luna] Shutting down ({why}) at {time.strftime('%H:%M:%S')}",
          flush=True)
    # whatever hangs below, she is gone in 2 s: on 4 Oct a process stuck in
    # here (a lock, after "Shutting down") lived on beside the new one and kept
    # the microphone — the new Luna came up deaf
    threading.Timer(2.0, lambda: os._exit(0)).start()
    try:
        import health
        health.flush_usage()   # today's API count survives a restart
    except Exception:
        pass
    try:                       # the radio's ffmpeg / pw-play must not outlive her
        import radio
        import ambience
        radio.stop()
        ambience.stop()
    except Exception:
        pass
    try:
        import pygame
        pygame.quit()
    except Exception:
        pass
    # hard exit: the daemon camera/mic threads hold native handles (OpenCV,
    # PortAudio) that don't like being torn down by interpreter shutdown
    os._exit(0)


def _dump_threads(*_):
    """kill -USR1 <pid>: each thread's name, nice and CPU seconds — which
    part of her is eating the Pi."""
    tick = os.sysconf("SC_CLK_TCK")
    rows = []
    for t in threading.enumerate():
        try:
            with open(f"/proc/self/task/{t.native_id}/stat") as f:
                st = f.read().rsplit(")", 1)[1].split()
            cpu = (int(st[11]) + int(st[12])) / tick
            rows.append((cpu, t.native_id, int(st[16]), t.name))
        except Exception:
            pass
    try:
        import vision_module as v
        s = v.stats
        print(f"[threads] vision: {s['frames']} frames, {s['face']} with a face; "
              f"full {s['full']}× avg {1000 * s['t_full'] / max(1, s['full']):.0f} ms, "
              f"near {s['near']}× avg {1000 * s['t_near'] / max(1, s['near']):.0f} ms", flush=True)
    except Exception as e:
        print(f"[threads] vision stats: {e}", flush=True)
    try:
        import robot_face as rf
        f = rf.frame_stats
        n = max(1, f["frames"])
        print(f"[threads] face: {f['frames']} frames ({f['tilted']} tilted), per frame "
              f"update {1000 * f['update'] / n:.1f} ms, face {1000 * f['face'] / n:.1f} ms, "
              f"compose {1000 * f['compose'] / n:.1f} ms, flip {1000 * f['flip'] / n:.1f} ms",
              flush=True)
    except Exception as e:
        print(f"[threads] face stats: {e}", flush=True)
    print("[threads] cpu-s  tid  nice  name", flush=True)
    for cpu, tid, ni, name in sorted(rows, reverse=True):
        print(f"[threads] {cpu:7.1f} {tid} {ni:3d}  {name}", flush=True)


signal.signal(signal.SIGUSR1, _dump_threads)
signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

from face_renderer import renderer_loop

try:
    renderer_loop()
except SystemExit:
    pass                      # QUIT event or ESC — a deliberate exit
except BaseException:
    # _shutdown() ends the process with os._exit(), which would kill the
    # interpreter before it could print this. Any renderer bug used to look
    # like a silent, unexplained restart.
    import traceback
    print("[Luna] renderer crashed:", flush=True)
    traceback.print_exc()
    sys.stdout.flush()
    sys.stderr.flush()
finally:
    _shutdown()
