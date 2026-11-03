"""The tools Claude works with: backlog.py, codemap.py, run_unit.py — and the
docs staying true (the .md files aren't copied to the Pi: skipped there)."""
import ast
import glob
import io
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import backlog  # noqa: E402
import claude_usage  # noqa: E402
import codemap  # noqa: E402
import perf_report  # noqa: E402
import run_unit  # noqa: E402

CLAUDE_MD = os.path.join(ROOT, "CLAUDE.md")


def quiet(fn, *args, **kw):
    out = io.StringIO()
    with redirect_stdout(out):
        code = fn(*args, **kw)
    return code, out.getvalue()


class BacklogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.mkdir(os.path.join(self.root, "docs"))
        self.write("BACKLOG.md", "# open\n\n| # | Item | Why | Status |\n|---|---|---|---|\n")
        self.write("docs/backlog-done.md",
                   "| 1 | **Radio** — stacje | bo tak | ✅ |\n"
                   "| 2 | **Piosenka w radiu** — co gra | 'co to za piosenka' | ✅ real model: ok |\n"
                   "| 3 | 💤 **Parked long ago** — x | y | parked |\n")
        self.write("CO_NOWEGO.md", "Radio gra.\nMinutnik też.\n")
        self.write("radio.py", "# radio radio\nx = 1\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.root, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def read(self, name):
        with open(os.path.join(self.root, name), encoding="utf-8") as f:
            return f.read()

    def cli(self, *args):
        return quiet(backlog.main, list(args), root=self.root)

    def test_a_finished_row_goes_to_the_done_file(self):
        code, out = self.cli("add", "**New** — a|b", "why\nnow")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "| 4 | **New** — a/b | why now | ✅ |")
        self.assertIn("| 4 |", self.read("docs/backlog-done.md"))
        self.assertNotIn("| 4 |", self.read("BACKLOG.md"))

    def test_an_open_row_stays_open_until_done(self):
        self.cli("add", "**Next**", "later", "⏳")
        self.assertIn("| 4 | **Next** | later | ⏳ |", self.read("BACKLOG.md"))
        code, _ = self.cli("done", "4", "shipped")
        self.assertEqual(code, 0)
        self.assertNotIn("| 4 |", self.read("BACKLOG.md"))
        self.assertIn("| 4 | **Next** | later | ✅ shipped |", self.read("docs/backlog-done.md"))
        self.assertEqual(self.cli("done", "4")[0], 1)

    def test_numbers_continue_across_both_files(self):
        self.cli("add", "**Open**", "w", "🚧")
        self.assertIn("| 5 |", self.cli("add", "**Done**", "w")[1])

    def test_find_ignores_case_and_polish_letters(self):
        _, out = self.cli("find", "PIOSENKĄ")
        self.assertIn("#2 ✅ Piosenka w radiu", out)
        self.assertNotIn("#1 ", out)

    def test_find_ranks_by_words_and_lists_the_code(self):
        _, out = self.cli("find", "radio", "piosenka", "nothing-like-it")
        self.assertLess(out.index("#2 "), out.index("#1 "))
        self.assertIn("radio.py 1", out)
        self.assertIn("1: Radio gra.", out)

    def test_show_recent_and_status_in_the_item(self):
        self.assertIn("real model", self.cli("show", "2")[1])
        self.assertEqual(self.cli("show", "99")[0], 1)
        self.assertIn("#3 💤 Parked long ago", self.cli("recent", "1")[1])

    def test_check_finds_a_duplicate_and_a_finished_row_left_open(self):
        self.assertEqual(self.cli("check")[0], 0)
        self.write("BACKLOG.md", "| 2 | **Dup** | w | ✅ |\n")
        code, out = self.cli("check")
        self.assertEqual(code, 1)
        self.assertIn("#2 twice", out)
        self.assertIn("#2 is finished", out)


class CodemapTest(unittest.TestCase):
    def test_symbols(self):
        tree = ast.parse('LIMIT = 3\n_RX = 1\nx = 2\nclass A:\n    """Doc."""\n    def m(self, a, *b): pass\n'
                         'def f(p, k=1):\n    """One.\n\n    Two."""\n')
        found = {s[3]: s for s in codemap.symbols(tree)}
        self.assertEqual(set(found), {"LIMIT", "_RX", "A", "m", "f"})
        self.assertEqual(found["m"][1:3], (1, "m(a, *b)"))
        self.assertEqual(found["f"][2], "f(p, k)  # One.")

    def test_docstring_prefix_is_dropped(self):
        self.assertEqual(codemap.first_line(ast.parse('"""radio.py — stations."""')), "stations.")

    def test_cli(self):
        code, out = quiet(codemap.main, ["-f", "first_line", "tools/codemap"])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"tools/codemap\.py:\d+  first_line\(node\)")
        self.assertEqual(quiet(codemap.main, ["no_such_module"])[0], 2)


class PerfReportTest(unittest.TestCase):
    LOG = """===== restart 2026-11-02 08:00:00 =====
[latency] end of speech → her voice 1.00s (text 0.50, model 0.60)
[latency] end of speech → her voice 3.00s
[health] 09:00 CPU 70°C, load 50%, RAM 50%, last hour: 2 answers (avg 2.0s), 1 failures, audio: 1 underruns, 2 rebuffers (late TTS), max stall 300 ms, clock nudges 5, PipeWire xruns 9 (since start), light 0.1, throttled 0x0; API calls: chat 2
===== restart 2026-11-03 08:00:00 =====
[gl] 14 faces warmed up in 2.5 s
[health] cloud clients warmed up in 7.0s
[latency] end of speech → her voice 2.00s (text 1.00)
[health] 09:00 CPU 80°C, load 70%, RAM 50%, last hour: 1 answers (avg 2.0s), 0 failures, audio: 0 underruns, 0 rebuffers (late TTS), max stall 100 ms, clock nudges 5, PipeWire xruns 4 (since start), light 0.1, throttled 0x80000; API calls: chat 1
"""

    def test_by_day(self):
        days = perf_report.by_day(self.LOG.split("\n"))
        self.assertEqual(list(days), ["2026-11-02", "2026-11-03"])
        self.assertEqual(days["2026-11-02"]["latency"], [1.0, 3.0])
        self.assertEqual(days["2026-11-02"]["stages"]["text"], [0.5])
        self.assertEqual(days["2026-11-03"]["temp"], [80])
        self.assertEqual(days["2026-11-02"]["underruns"], 1)
        self.assertEqual(days["2026-11-03"]["throttled"], 0x80000)
        self.assertEqual(days["2026-11-03"]["faces"], [2.5])

    def test_a_new_day_with_nothing_measured_says_nothing_about_it(self):
        days = perf_report.by_day((self.LOG + "===== restart 2026-11-04 00:10:00 =====\n").split("\n"))
        self.assertIsNone(days["2026-11-04"]["throttled"])
        out = quiet(perf_report.report, days)[1]
        self.assertIn("throttling, 2026-11-03: ", out)
        self.assertIn("soft temperature limit", out)
        self.assertIn("speech, 2026-11-03: text 1.00", out)

    def test_throttle_bits(self):
        self.assertEqual(perf_report.throttle_text(0), "never")
        self.assertEqual(perf_report.throttle_text(None), "no health line yet")
        self.assertIn("soft temperature limit since boot", perf_report.throttle_text(0x80000))
        self.assertIn("under-voltage now", perf_report.throttle_text(0x1))

    def test_percentile(self):
        self.assertEqual(perf_report.percentile([1.0, 2.0, 3.0], 50), 2.0)
        self.assertEqual(perf_report.percentile(list(range(1, 11)), 90), 9)


class ClaudeUsageTest(unittest.TestCase):
    def test_tool_kind(self):
        self.assertEqual(claude_usage.tool_kind("Bash", {"command": "cd x && sed -n 1,2p a"}), "Bash sed")
        self.assertEqual(claude_usage.tool_kind("Read", {"file_path": "a/b/gl_face.py"}), "Read gl_face.py")
        self.assertEqual(claude_usage.tool_kind("Grep", {"pattern": "x"}), "Grep")

    def test_tool_results(self):
        lines = ['not json',
                 '{"message": {"content": [{"type": "tool_use", "id": "a", "name": "Grep"}]}}',
                 '{"message": {"content": [{"type": "tool_result", "tool_use_id": "a", '
                 '"content": [{"text": "12345"}]}]}}',
                 '{"message": {"content": "plain"}}']
        self.assertEqual(list(claude_usage.tool_results(lines)), [("Grep", 5)])


class ShipListsTest(unittest.TestCase):
    """A file check_pi passes but deploy never copies: restart.sh tested it all again
    on every ship (27 Oct – 4 Nov)."""

    def excluded(self, script):
        with open(os.path.join(ROOT, "tools", script), encoding="utf-8") as f:
            return re.search(r"^files=\$\(git ls-files \| grep -v -E '([^']+)'", f.read(), re.M).group(1)

    def test_check_and_deploy_list_the_same_files(self):
        checked, deployed = re.compile(self.excluded("check_pi.sh")), re.compile(self.excluded("deploy.sh"))
        for name in (".claude/settings.json", ".gitattributes", "BACKLOG.md", "main.py",
                     "tools/ship.sh", "data/persona.txt"):
            self.assertEqual(bool(checked.search(name)), bool(deployed.search(name)), name)


class RunUnitTest(unittest.TestCase):
    def test_shares_keep_a_class_whole(self):
        ids = [f"m.A.t{i}" for i in range(5)] + ["m.B.t1", "m.B.t2", "m.C.t1"]
        bins = run_unit.shares(ids, 2)
        self.assertEqual(sorted(i for b in bins for i in b), sorted(ids))
        self.assertEqual(bins[0], [f"m.A.t{i}" for i in range(5)])
        self.assertEqual(bins[1], ["m.B.t1", "m.B.t2", "m.C.t1"])

    def test_no_empty_share(self):
        self.assertEqual(len(run_unit.shares(["m.A.t"], 8)), 1)


class DocsTest(unittest.TestCase):
    """A map that lies costs more than none (3 Nov: 20 modules were missing from it)."""

    def modules(self):
        names = [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.py"))]
        return sorted(n for n in names if not n.startswith("test_"))

    def test_every_module_says_what_it_is(self):
        missing = []
        for name in self.modules():
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                if not ast.get_docstring(ast.parse(f.read())):
                    missing.append(name)
        self.assertEqual(missing, [], "these need a docstring, for tools/codemap.py")

    @unittest.skipUnless(os.path.exists(CLAUDE_MD), "the .md files stay on the PC")
    def test_the_module_map_names_every_module(self):
        with open(CLAUDE_MD, encoding="utf-8") as f:
            text = f.read()
        missing = [n for n in self.modules() if f"`{n}`" not in text and f"`{n[:-3]}`" not in text
                   and not re.search(rf"[`/]{re.escape(n)}`", text)]
        self.assertEqual(missing, [], "add these to the module map in CLAUDE.md")

    @unittest.skipUnless(os.path.exists(CLAUDE_MD), "the .md files stay on the PC")
    def test_files_the_docs_name_exist(self):
        docs = ["CLAUDE.md", "BACKLOG.md", "docs/recipes.md", "docs/performance.md"]
        pattern = re.compile(r"`((?:tools|tests|docs|pi)/[\w./-]+\.\w+|[\w-]+\.(?:py|sh|md))`")
        missing = []
        for doc in docs:
            with open(os.path.join(ROOT, doc), encoding="utf-8") as f:
                for name in pattern.findall(f.read()):
                    if not os.path.exists(os.path.join(ROOT, name)):
                        missing.append(f"{doc}: {name}")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
