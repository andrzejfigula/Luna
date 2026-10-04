"""
reply_stream.py — pulls the "reply" text out of the model's JSON answer
while it is still streaming (brain.py), so Luna can start speaking the first
sentence before the model has finished writing. Plain Python: tested in
tests/test_reply_stream.py without a Pi or a network.
"""

import re

# A sentence ends at . ! ? … (maybe followed by a closing quote) and a space.
_SENTENCE_END = re.compile(r"[.!?…]+[\"”»)]?\s")
_FIRST_MIN_CHARS = 20          # don't send "Tak." alone — it sounds clipped
_CHUNK_CHARS = 180             # after the first sentence, speak in pieces of
                               # about this much (whole sentences) — a long
                               # story must not wait for its last word


class ReplyStream:
    """Pulls the "reply" string out of the model's JSON while it is still
    streaming. on_head(emotion, gesture) fires when the reply starts (both
    come before it in the schema); on_sentence(text) gets the first sentence
    as soon as it is complete, then whole sentences in pieces of about
    _CHUNK_CHARS — a usual 2-3 sentence answer is just two TTS calls (keeps
    the intonation natural), a story keeps flowing while it is written."""

    _ESC = {"n": " ", "t": " ", "r": "", "b": "", "f": "", "/": "/",
            '"': '"', "\\": "\\"}

    def __init__(self, on_head, on_sentence):
        self.on_head, self.on_sentence = on_head, on_sentence
        self.raw = ""
        self.pos = None            # where the reply string's content starts
        self.text = ""             # the reply decoded so far
        self.closed = False        # the reply string's closing quote seen
        self.sent = 0              # characters of text already handed out

    def feed(self, piece):
        self.raw += piece
        if self.pos is None:
            m = re.search(r'"reply"\s*:\s*"', self.raw)
            if not m:
                return
            self.pos = m.end()
            emo = re.search(r'"emotion"\s*:\s*"(\w+)"', self.raw)
            ges = re.search(r'"gesture"\s*:\s*"(\w+)"', self.raw)
            self.on_head(emo.group(1) if emo else "neutral",
                         ges.group(1) if ges else "none")
        if not self.closed:
            self._decode()
        if self.sent == 0:
            m = _SENTENCE_END.search(self.text, _FIRST_MIN_CHARS)
            if m:
                self._out(m.end())
        elif len(self.text) - self.sent >= _CHUNK_CHARS:
            # the last sentence end at least _CHUNK_CHARS into the pending text
            last = None
            for m in _SENTENCE_END.finditer(self.text, self.sent + _CHUNK_CHARS - 1):
                last = m
                break
            if last:
                self._out(last.end())
        if self.closed:
            self.finish()

    def _decode(self):
        s, i, out = self.raw, self.pos, []
        while i < len(s):
            c = s[i]
            if c == "\\":
                if i + 1 >= len(s):
                    break                              # escape split across chunks
                n = s[i + 1]
                if n == "u":
                    if i + 6 > len(s):
                        break
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                    i += 6
                    continue
                out.append(self._ESC.get(n, n))
                i += 2
                continue
            if c == '"':
                self.closed = True
                i += 1
                break
            out.append(c)
            i += 1
        self.text += "".join(out)
        self.pos = i

    def _out(self, upto):
        piece = self.text[self.sent:upto].strip()
        self.sent = upto
        if piece:
            self.on_sentence(piece)

    def finish(self):
        if self.pos is not None and self.sent < len(self.text):
            self._out(len(self.text))
