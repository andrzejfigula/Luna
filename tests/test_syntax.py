"""Every module must at least compile — brain.py, speech_to_text.py and others
can't be imported on a dev machine (cv2, Vosk, the OpenAI SDK), so a typo
there would otherwise only show up on the Pi, as a crash at start."""

import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SyntaxTest(unittest.TestCase):

    def test_every_module_compiles(self):
        files = glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "tests", "*.py"))
        self.assertGreater(len(files), 30)
        for path in files:
            with self.subTest(path=os.path.basename(path)):
                with open(path, encoding="utf-8") as f:
                    src = f.read()
                compile(src, path, "exec")
                # a backspace or a raw newline inside a string literal is what
                # mangled escapes ("\b", "\n") turn into — never intended
                self.assertNotIn("\x08", src)


if __name__ == "__main__":
    unittest.main()
