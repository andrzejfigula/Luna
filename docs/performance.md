# Performance — how to measure, and the numbers to compare with

Measure first, on the Pi, beside Luna. All of these are silent.

| Question | Tool |
|---|---|
| Slower than last week? Answers, temperature, audio, by day | `ssh raspberry@raspberrypi.local 'cd ~/luna && python3 tools/perf_report.py'` (`--old` adds the rotated logs) |
| Where did this answer's time go? | `[latency]` lines from `timing.py`: `bash tools/lastlog.sh 40 all 'latency'` |
| A day's exchanges with their times | `tools/log_report.py` (`latency_summary`) |
| What a face frame costs; did my change alter it? | `tools/render_bench.py`, below |
| What the Pi is doing right now, on the screen | `perf_hud.py` (Ustawienia → Ekran) |
| Which thread is eating the CPU | `kill -USR1 <pid>` logs per-thread CPU; `kill -USR2 <pid>` the stacks of a hung Luna |
| Why is this Claude session expensive | `python -X utf8 tools/claude_usage.py [--tools]` |

Comparing two versions of the face (same fake clock, same pixels):

    cd <a luna copy> && ~/luna/venv/bin/python -X utf8 tools/render_bench.py --secs 24 --save /tmp/a
    python3 tools/render_bench.py --diff /tmp/a /tmp/b

Start it with `nice -n 10` and a scratch data dir (it defaults to one): Luna keeps
running beside it, and takes a share of the GPU, so compare runs made under similar
load.

## Baselines

Answers, end of speech to her voice, `tools/perf_report.py` (22 Oct – 3 Nov):

- p50 2.2–4.3 s, p90 3.9–6.6 s. Few answers on a day make these jumpy.
- Stages, median from the end of speech (3 Nov): text 1.26, model 1.29, reply 2.83,
  first sentence 3.05, TTS 1.48, audio 3.65 s.
- Warm-up: faces 1.9 s, cloud clients 7.0 s.

The Pi, from the hourly `[health]` line:

- CPU 56–63 °C on average, 71–78 °C at worst; load 15–28%, peaks 70–104%.
- Longest stall per day ~300–350 ms.
- Audio: no underruns; rebuffers only on 22–23 Oct; PipeWire xruns 0–168 a day.
- `throttled 0x80000`: the soft temperature limit was hit since boot. Only that bit:
  no under-voltage, no frequency capping or throttling flagged.

A face frame, `tools/render_bench.py --secs 12` at 30 fps beside the running Luna
(4 Nov, load ~2.9, the niced bench):

- CPU median 13.8 ms, 90% 27.4 ms. GPU after it: median 40.1 ms, 90% 47.5 ms.
- Per frame: update 0.54, face 0.15, compose 4.03, gl 16.78 ms.
- 10 Nov, after the system upgrade (Mesa 26.2.6, kernel 6.18.60, labwc 0.20.2), 74 °C:
  CPU median 15.9 ms, 90% 28.0; GPU median 22.7 ms, 90% 27.5; gl 24.05 ms per frame.
  The first start after a Mesa upgrade rebuilds the shader cache: a black screen
  for ~2 min (`6 faces warmed up in 116.7 s`), 2.7 s from the next start on.

## The build (`tools/check_pi.sh`)

Where the time goes (4 Nov):

| Step | Before | Now |
|---|---|---|
| Unit tests on the PC | 15.7 s, one process | 8 s, 8 workers (`tests/run_unit.py --jobs 8`) |
| Whole check, default | 41 s | 34 s |
| The same code again | 41 s | 4 s: it already passed (`LUNA_CHECK_AGAIN=1` runs it anyway) |
| `quick` | not measured | 31 s |
| `full`, all four on the Pi | not measured | 1 min 45 s – 2 min 15 s (unit alone 97–128 s) |
| `tools/ship.sh`, code changed | 78 s | 50 s (`restart.sh` tested it all again, below) |
| `tools/ship.sh --restart`, code already passed | 44 s | 20 s |
| `tools/ship.sh`, the Pi already runs this code | restarted | 8 s, no restart |

From 27 Oct `.claude/settings.json` was in the list of files that passed but never
reached the Pi, so `restart.sh --tested` found a difference on every ship and re-ran
the tests. Its line says which it did: "no second test run" is the good one.

The critical path is now PC unit (8 s) then the Pi's share of them (17–20 s, the ones
that need cv2 and pygame), beside dialog (20 s). The Pi stays one process: the face
renders at the same nice level as the tests, so workers there would compete with her.
Every check prints `times:` per gate and `unit times:`.
