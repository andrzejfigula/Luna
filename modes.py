"""
modes.py — what is waiting for the next sentence.

Two lists main.py's voice loop used to carry by hand. AWAITING: a game, a page
or a question is open, so the window stays open over the radio. TAKERS: a
mode that asked for this very sentence (a message being recorded, an SMS
being written, a child reading aloud, "zmień mój głos") takes it before any
command does. A new mode adds one line here (docs/recipes.md).
"""

import importlib

import errlog

# (module, function) → true while it waits for an answer
AWAITING = (
    ("quiz", "active"), ("twenty", "active"), ("tictac", "active"), ("memo", "active"),
    ("hangman", "active"), ("gallery", "page_open"), ("story", "active"),
    ("brain", "awaits_answer"),
    # (voicefx, messages: the sentence she just asked for, or it needed "Luna")
    ("voicefx", "armed"), ("messages", "armed"), ("phone", "active"),
)


def answer_awaited():
    """One of them waits: with the radio on the window stays open — the radio
    is ducked while she listens. (14 Oct: "zgadywanki" with jazz on —
    "dziesięć" needed "Luna".) A module that fails is passed over, not the lot."""
    for mod, fn in AWAITING:
        try:
            if getattr(importlib.import_module(mod), fn)():
                return True
        except Exception:
            errlog.once("modes")
    return False


def _message(text, speak):
    """"nagraj wiadomość" — this sentence IS the message."""
    import messages
    if not messages.armed():
        return False
    if messages.cancelled(text):
        speak("Dobrze, nie nagrywam.")
        return True
    import speech_to_text
    messages.store(speech_to_text.last_utterance_pcm, text)
    speak("Zapisałam wiadomość.")
    return True


def _phone(text, speak):
    """An SMS being written, a pairing code."""
    import phone
    return bool(phone.active() and phone.answer(text, speak))


def _reading(text, speak):
    """"posłuchaj, jak czytam": collected, answered at the end."""
    import reading
    if not reading.armed():
        return False
    r = reading.add(text)
    if r == "end":
        import commands
        commands.reading_done(*reading.take())
    elif r == "stop":
        speak("Dobrze, przestaję słuchać.")
    return True


def _voicefx(text, speak):
    """"zmień mój głos" — this sentence comes back changed."""
    import voicefx
    if voicefx.cancelled(text):
        speak("Dobrze, nie odtwarzam.")
        return True
    if not voicefx.armed():
        return False
    import speech_to_text
    from text_to_speech import play_clip
    voicefx.play(speech_to_text.last_utterance_pcm, speak, play_clip)
    return True


TAKERS = (("messages", _message), ("phone", _phone), ("reading", _reading),
          ("voicefx", _voicefx))


def take(text, speak):
    """The name of the mode that took this sentence, or None."""
    for name, fn in TAKERS:
        if fn(text, speak):
            return name
    return None
