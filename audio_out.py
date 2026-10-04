"""
audio_out.py — one long-lived player, fed with silence between utterances.

Starting a pw-play per reply costs time twice: the process and its PipeWire
node have to start, and the Pi's 3.5 mm output pops when a stream opens, so
every reply began with TTS_LEADIN_SECS of silence. Here the player is started
once and a writer thread keeps it fed at real-time pace — silence when there
is nothing to say, speech when there is. A reply (or a giggle) then starts
almost at once, and there is never a stream-open pop.

Timing: the writer keeps `target` seconds of audio ahead of the playback
position (wall clock since the player started, corrected after any
underrun), so it knows when each byte will be heard — that is what lines
the lip-sync envelope up with the sound.
"""

import collections
import subprocess
import threading
import time

import numpy as np

RATE = 24000                    # s16 mono, the TTS PCM rate
BPS  = RATE * 2                 # bytes per second
CHUNK = int(0.04 * RATE) * 2    # writer granularity: 40 ms

# A wake-up alarm must not be whispered just because 7:00 is still inside the
# quiet hours: timers.py sets this while an alarm rings.
full_volume_until = 0.0

IDLE_AHEAD = 0.08               # seconds of silence queued between utterances
REBUFFER   = 0.25               # the network fell behind mid-utterance: wait for
                                # this much before going on — one clean pause
                                # instead of syllables chopped up by silence


class AudioOut:

    def __init__(self, cmd, envelope, target_ahead=0.25):
        self.cmd = cmd
        self.env = envelope
        self.target = target_ahead
        self.lock = threading.Lock()
        self.q = collections.deque()       # pending speech chunks (bytes)
        self.q_bytes = 0
        self.proc = None
        self.t_start = 0.0                 # wall time byte 0 of the stream plays
        self.written = 0                   # bytes handed to the player
        # the utterance being played
        self.active = False
        self.holding = False               # prebuffering: speech waits
        self.prebuf = 0
        self.closed = False                # no more speech will be added
        self.on_start = None
        self.started = False
        self.last_speech_end = 0           # stream byte where speech ends
        self.recording = False             # keep this utterance for "powtórz"
        self._rec = []
        self.last_utterance = b""          # her last spoken answer, as played
        # health
        self.underruns = 0
        self.rebuffers = 0
        self.max_stall = 0.0
        threading.Thread(target=self._run, daemon=True, name="audio-out").start()

    # ── player process ────────────────────────────────────────────────────
    def _spawn(self):
        if self.proc is not None:
            for close in (self.proc.kill, self.proc.stdin.close):
                try:
                    close()
                except Exception:
                    pass                     # a dead pipe: nothing to flush
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
        # a fresh stream: count it as just ahead, not as already late
        self.t_start = time.time() + 0.05
        self.written = 0

    def _ahead(self):
        return self.written / BPS - (time.time() - self.t_start)

    # ── writer: real-time pace, speech if there is any, else silence ─────
    def _run(self):
        self._spawn()
        silence = bytes(CHUNK)
        last = time.time()
        while True:
            now = time.time()
            stall = now - last
            last = now
            self.max_stall = max(self.max_stall, stall)
            ahead = self._ahead()
            if ahead < 0:
                # the player ran dry (we were late): it played everything
                # we gave it and waited, so move the clock to match
                if self.active and self.started:
                    self.underruns += 1          # gaps in silence don't count
                if self.active and self.started:
                    print(f"[audio] underrun during speech (writer late "
                          f"{stall * 1000:.0f} ms) — raise AUDIO_AHEAD_SECS "
                          f"if this repeats", flush=True)
                self.t_start = now - self.written / BPS
                ahead = 0.0
            # until speech flows keep only a sliver of silence queued, so a
            # reply isn't stuck behind 0.4 s of it (a gap in silence is
            # inaudible); once she speaks: the full jitter margin
            target = self.target if (self.active and self.started) else IDLE_AHEAD
            if ahead >= target:
                # sleep exactly as long as the margin allows: waking 100+
                # times a second cost ~10 % of a core for nothing
                time.sleep(min(0.06, ahead - target + 0.01))
                continue
            data, speech = silence, False
            with self.lock:
                if (self.active and self.started and not self.holding
                        and not self.q and not self.closed):
                    # speech ran out but more is coming: the TTS stream is late
                    self.holding, self.prebuf = True, int(REBUFFER * BPS)
                    self.rebuffers += 1
                    print("[audio] TTS stream late — rebuffering", flush=True)
                if self.active and self.holding:
                    if self.q_bytes >= self.prebuf or self.closed:
                        self.holding = False
                if self.active and not self.holding and self.q:
                    data = self.q.popleft()
                    if len(data) > CHUNK:
                        self.q.appendleft(data[CHUNK:])
                        data = data[:CHUNK]
                    self.q_bytes -= len(data)
                    speech = True
                feeding = self.active and self.started
                if speech and not self.started:
                    # first speech byte: it plays when everything already
                    # written has played
                    self.started = True
                    feeding = True
                    self.env.reset()
                    self.env.start_at(self.t_start + self.written / BPS)
                    if self.on_start:
                        # synchronously: it only sets a flag, and run late in
                        # its own thread it could land after the utterance
                        # ended and leave the mouth flapping
                        try:
                            self.on_start()
                        except Exception as e:
                            print(f"[audio] on_start: {e}")
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
                self._fails = 0
            except Exception:
                # back off if it keeps dying (PipeWire down), and say so once
                # a minute instead of five times a second
                self._fails = getattr(self, "_fails", 0) + 1
                if time.time() - getattr(self, "_fail_logged", 0) > 60:
                    self._fail_logged = time.time()
                    print(f"[audio] player died — restarting it "
                          f"(attempt {self._fails})", flush=True)
                time.sleep(min(5.0, 0.2 * self._fails))
                with self.lock:
                    self._spawn()
                    # the new stream's clock starts at 0: whatever the old
                    # one still owed is gone, so an utterance in progress
                    # must not wait for the old stream's end time
                    self.last_speech_end = 0
                continue
            self.written += len(data)
            if feeding:
                self.env.feed(data)          # silence gaps too: keeps sync
            if speech:
                self.last_speech_end = self.written

    # ── an utterance ──────────────────────────────────────────────────────
    def begin(self, on_start=None, prebuffer=0.15, record=False):
        """record=True: keep the audio of this utterance as last_utterance
        (answers, not sounds) so "powtórz" can replay it without a request."""
        with self.lock:
            self.recording, self._rec = record, []
            self.q.clear()
            self.q_bytes = 0
            self.active, self.holding, self.closed = True, True, False
            self.prebuf = int(prebuffer * BPS)
            self.on_start, self.started = on_start, False
            self.last_speech_end = 0

    def _gain(self):
        """Quieter at night (the quiet hours): NIGHT_VOICE_GAIN."""
        from config import NIGHT_VOICE_GAIN, PROACTIVE_QUIET_FROM as a, PROACTIVE_QUIET_TO as b
        if NIGHT_VOICE_GAIN >= 1.0 or time.time() < full_volume_until:
            return 1.0
        h = time.localtime().tm_hour
        night = a <= h < b if a <= b else (h >= a or h < b)
        return NIGHT_VOICE_GAIN if night else 1.0

    def write(self, pcm):
        if not pcm:
            return
        if self.recording:
            self._rec.append(pcm)
        g = self._gain()
        if g != 1.0 and len(pcm) >= 2:
            pcm = pcm[:len(pcm) // 2 * 2]
            pcm = (np.frombuffer(pcm, np.int16) * g).astype(np.int16).tobytes()
        with self.lock:
            self.q.append(pcm)
            self.q_bytes += len(pcm)

    def finish(self, cut_event=None):
        """No more audio for this utterance; block until it has been heard
        (or cut_event is set). Returns True if anything was played."""
        with self.lock:
            self.closed = True
        while True:
            if cut_event is not None and cut_event.is_set():
                self.cut()
                break
            with self.lock:
                pending = self.q_bytes > 0 or (self.holding and self.q)
                started = self.started
                end = self.t_start + self.last_speech_end / BPS
            if not pending:
                if not started:
                    break
                if time.time() >= end:
                    break
            time.sleep(0.01)
        with self.lock:
            played = self.started
            self.active = False
            if self.recording and played and not (cut_event is not None and cut_event.is_set()):
                self.last_utterance = b"".join(self._rec)
            self.recording, self._rec = False, []
        self.env.reset()
        return played

    def cut(self):
        """Drop what hasn't been written yet (the ~target already in the
        player still plays — a quarter of a second)."""
        with self.lock:
            self.q.clear()
            self.q_bytes = 0
            self.last_speech_end = self.written

    def stats(self):
        s = (self.underruns, self.max_stall, self.rebuffers)
        self.underruns, self.max_stall, self.rebuffers = 0, 0.0, 0
        return s
