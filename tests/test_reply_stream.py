import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reply_stream import ReplyStream


def run(payload, piece=1):
    """Feed `payload` (a dict, JSON-encoded) in pieces of `piece` characters."""
    raw = json.dumps(payload, ensure_ascii=False)
    heads, sentences = [], []
    rs = ReplyStream(lambda e, g: heads.append((e, g)), sentences.append)
    for i in range(0, len(raw), piece):
        rs.feed(raw[i:i + piece])
    rs.finish()
    return heads, sentences


def answer(reply, emotion="happy", gesture="wink"):
    return {"user_mood": "neutral", "emotion": emotion, "gesture": gesture,
            "reply": reply, "mood_comment": False, "actions": []}


class ReplyStreamTest(unittest.TestCase):

    def test_said_to_someone_else_stays_quiet(self):
        payload = {"to_luna": False, **answer("Ten pasek brzmi ciekawie. Opowiesz więcej?")}
        for piece in (1, 7, 1000):
            heads, sentences = run(payload, piece)
            self.assertEqual((heads, sentences), ([], []))
        heads, sentences = run({"to_luna": True, **answer("Cześć!")})
        self.assertEqual(heads, [("happy", "wink")])

    def test_head_arrives_once_with_emotion_and_gesture(self):
        heads, _ = run(answer("Cześć!"))
        self.assertEqual(heads, [("happy", "wink")])

    def test_first_sentence_then_the_rest(self):
        reply = ("Mars jest czerwony przez rdzę na powierzchni. "
                 "Tlenek żelaza odbija czerwone światło. Dlatego tak wygląda.")
        _, s = run(answer(reply))
        self.assertEqual(s, ["Mars jest czerwony przez rdzę na powierzchni.",
                             "Tlenek żelaza odbija czerwone światło. Dlatego tak wygląda."])

    def test_same_result_whatever_the_chunking(self):
        reply = "To jest pierwsze zdanie, dość długie. A to drugie! I trzecie?"
        expected = run(answer(reply), piece=1)
        for piece in (2, 3, 7, 50, 10000):
            self.assertEqual(run(answer(reply), piece=piece), expected, piece)

    def test_short_first_sentence_is_not_split(self):
        _, s = run(answer("Tak. Masz całkowitą rację w tej sprawie."))
        self.assertEqual(s, ["Tak. Masz całkowitą rację w tej sprawie."])

    def test_long_first_sentence_starts_at_a_comma(self):
        reply = ("Dzisiaj w Kątach Wrocławskich będzie pochmurno, temperatura od ośmiu "
                 "do dwudziestu dwóch stopni. Bez deszczu.")
        for piece in (1, 5, 10000):
            _, s = run(answer(reply), piece)
            self.assertEqual(s, ["Dzisiaj w Kątach Wrocławskich będzie pochmurno,",
                                 "temperatura od ośmiu do dwudziestu dwóch stopni. Bez deszczu."])
        _, s = run(answer("Dobrze, już włączam radio. Miłego słuchania!"))
        self.assertEqual(s[0], "Dobrze, już włączam radio.")     # short clause: no split

    def test_single_sentence(self):
        _, s = run(answer("Jest dokładnie piętnasta."))
        self.assertEqual(s, ["Jest dokładnie piętnasta."])

    def test_escapes_and_unicode(self):
        reply = 'Powiedziała: "zażółć gęślą jaźń" — i poszła.\nKoniec\\tego.'
        _, s = run(answer(reply), piece=1)
        joined = " ".join(s)
        self.assertIn('"zażółć gęślą jaźń"', joined)
        self.assertIn("Koniec\\tego.", joined)       # backslash survives
        self.assertNotIn("\n", joined)              # newlines become spaces

    def test_ascii_escaped_json(self):
        raw = json.dumps(answer("Zażółć gęślą jaźń, to długie zdanie testowe. Drugie."),
                         ensure_ascii=True)            # \\u0105 style escapes
        out = []
        rs = ReplyStream(lambda e, g: None, out.append)
        for ch in raw:
            rs.feed(ch)
        rs.finish()
        self.assertEqual(out, ["Zażółć gęślą jaźń, to długie zdanie testowe.", "Drugie."])

    def test_a_long_story_flows_in_pieces(self):
        story = " ".join(f"To jest zdanie numer {i} w długiej bajce o smoku i rycerzu."
                         for i in range(1, 13))
        _, s = run(answer(story), piece=5)
        self.assertGreaterEqual(len(s), 4)                  # not one huge chunk
        self.assertEqual(" ".join(s), story)                # nothing lost
        for piece in s:
            self.assertTrue(piece.endswith("."), piece)     # whole sentences

    def test_nothing_before_the_reply_key(self):
        heads, s = run({"user_mood": "neutral", "emotion": "sad"})
        self.assertEqual((heads, s), ([], []))


if __name__ == "__main__":
    unittest.main()
