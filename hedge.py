"""
hedge.py — a second request when the first one is slow to start.

The cloud services usually answer quickly, but now and then one sits silent
for seconds — and every such stall is a moment Luna "hangs" mid-conversation
(6 Oct). hedged(open_stream, after) starts the stream; if it has produced
nothing after `after` seconds (or failed before producing anything), the same
request is started again, and whichever produces its first item first is the
one that is read — the other stops at its next item.
"""

import queue
import threading


def hedged(open_stream, after, label="request", total=90.0):
    """Yield the items of open_stream() — from a second call of it when the
    first is slow to start. Raises the error when neither produced anything,
    and TimeoutError when the whole stream takes longer than `total` seconds:
    the client's timeout is per read, and a stream that stays open (10 Oct
    20:20 — the answer was spoken, the call never returned) blocked Luna for
    good."""
    import time
    deadline = time.time() + total
    q = queue.Queue()
    lock = threading.Lock()
    owner = [None]

    def attempt(n):
        try:
            for item in open_stream():
                with lock:
                    if owner[0] is None:
                        owner[0] = n
                    mine = owner[0] == n
                if not mine:
                    break                        # the other one was faster
                q.put(("item", item))
        except Exception as e:
            q.put(("error", (n, e)))
        finally:
            q.put(("end", n))

    def start(n):
        threading.Thread(target=attempt, args=(n,), daemon=True,
                         name=f"hedge-{label}-{n}").start()

    start(0)
    started, ended, errors = 1, 0, []
    while True:
        left = deadline - time.time()
        if left <= 0:
            print(f"[hedge] {label}: still open after {total:.0f}s — given up", flush=True)
            raise TimeoutError(f"{label} stream took over {total:.0f} s")
        hedge_wait = started == 1 and owner[0] is None
        try:
            kind, val = q.get(timeout=min(after, left) if hedge_wait else min(left, 5.0))
        except queue.Empty:
            if hedge_wait and time.time() < deadline:
                print(f"[hedge] {label}: nothing after {after:.1f}s — asking again", flush=True)
                start(1)
                started = 2
            continue
        if kind == "item":
            yield val
        elif kind == "error":
            n, e = val
            if owner[0] == n:
                raise e                          # the stream being read broke off
            errors.append(e)
            if started == 1 and owner[0] is None:
                start(1)                         # failed before anything came: retry
                started = 2
        else:
            ended += 1
            if owner[0] is not None and owner[0] == val:
                break                            # the winner is done
            if ended >= started and owner[0] is None:
                break                            # nobody produced anything
    if owner[0] == 1:
        print(f"[hedge] {label}: the second request won", flush=True)
    if owner[0] is None and errors:
        raise errors[-1]
