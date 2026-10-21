"""
openai_client.py — the OpenAI client, built on first use.

Importing the openai SDK takes ~6.5 s on the Pi; every test process paid it
at import time (memory, brain, sounds, openai_tts), and so did each restart.
LazyOpenAI(...) stands in for openai.OpenAI(...): it is not None, so the
"_client is None" checks still work, and the SDK loads on the first
attribute access. main.py calls warm() so a first reply never waits for it.
"""
import threading

_lock = threading.Lock()


class LazyOpenAI:
    def __init__(self, **kwargs):
        self._kwargs = kwargs
        self._real = None

    def __getattr__(self, name):
        # only reached for names not set in __init__ (chat, audio, …)
        if self._real is None:
            with _lock:
                if self._real is None:
                    from openai import OpenAI
                    self._real = OpenAI(**self._kwargs)
        return getattr(self._real, name)


def warm():
    """Load the SDK in the background (Luna's start, not the tests)."""
    def load():
        try:
            import openai  # noqa: F401
        except ImportError:
            pass
    threading.Thread(target=load, name="openai-import", daemon=True).start()
