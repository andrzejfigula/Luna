"""The tools Claude works with: backlog.py, codemap.py, run_unit.py — and the
docs staying true (the .md files aren't copied to the Pi: skipped there)."""
import ast
import glob
import io
import json
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
import ideas  # noqa: E402
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

    def test_find_lists_ideas_too_with_their_own_numbers(self):
        self.assertNotIn("ideas", self.cli("find", "wisielec")[1])
        self.write("docs/ideas.md", "| 7 | ✗ | games | maja | S | 2 | new | - | **Wisielec** — gra | bo |\n")
        out = self.cli("find", "WISIELEC")[1]
        self.assertIn("idea 7 ✗ Wisielec", out)
        self.assertIn("backlog: 0 rows", out)

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


class IdeasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.mkdir(os.path.join(self.root, "docs"))
        self.path = os.path.join(self.root, "docs", "ideas.md")
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# ideas\n\n| # | Mark | Area | For | Size | Value | Kind | Needs | Idea | Why |\n"
                    "|---|---|---|---|---|---|---|---|---|---|\n"
                    "| 1 | · | games | maja | S | 2 | new | - | **Wisielec** — litery | klasyka |\n"
                    "| 2 | · | games | all | M | 3 | new | model | **Kalambury** — hasła | rodzina |\n"
                    "| 3 | · | hw | all | L | 1 | new | hw,sudo | **Szyja** — serwa | obecność |\n")

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        return quiet(ideas.main, list(args), root=self.root)

    def shown(self, *args):
        return [line.split()[0] for line in self.cli(*args)[1].splitlines()[:-1]]

    def test_filters_add_up_and_the_best_comes_first(self):
        self.assertEqual(self.shown(), ["2", "1", "3"])
        self.assertEqual(self.shown("area=games", "size=S"), ["1"])
        self.assertEqual(self.shown("size=S,L"), ["1", "3"])

    def test_a_combined_need_matches_either_part_and_a_dash_means_none(self):
        self.assertEqual(self.shown("needs=sudo"), ["3"])
        self.assertEqual(self.shown("needs=-"), ["1"])

    def test_words_ignore_case_and_polish_letters(self):
        self.assertEqual(self.shown("OBECNOSC"), ["3"])
        self.assertEqual(self.shown("maja"), ["1"])

    def test_a_dropped_idea_stays_in_the_file_but_is_hidden(self):
        self.assertEqual(self.cli("drop", "1")[0], 0)
        self.assertEqual(self.shown(), ["2", "3"])
        self.assertEqual(self.shown("mark=drop"), ["1"])
        self.assertEqual(self.shown("mark=all"), ["2", "1", "3"])
        self.assertEqual(self.cli("undo", "1")[0], 0)
        self.assertEqual(self.shown("mark=keep,drop"), [])

    def test_a_filter_marks_the_undecided_only_and_undo_reaches_the_rest(self):
        self.cli("keep", "1")
        self.assertIn("2 ideas: 2 3", self.cli("drop", "size=M,L")[1])
        self.assertEqual(self.shown("mark=keep"), ["1"])
        self.cli("drop", "area=games")
        self.assertEqual(self.shown("mark=keep"), ["1"])
        self.assertIn("3 ideas", self.cli("undo", "mark=all")[1])
        self.cli("drop", "2")
        self.assertIn("1 ideas: 2", self.cli("undo", "area=games", "kalambury")[1])

    def test_a_bad_number_or_filter_changes_nothing(self):
        with open(self.path, encoding="utf-8") as f:
            before = f.read()
        self.assertEqual(self.cli("drop", "1", "99")[0], 1)
        self.assertEqual(self.cli("drop", "colour=red")[0], 2)
        self.assertEqual(self.cli("drop")[0], 2)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_show_and_stats(self):
        self.assertIn("Why: rodzina", self.cli("show", "2")[1])
        self.assertEqual(self.cli("show", "99")[0], 1)
        out = self.cli("stats", "area=games")[1]
        self.assertIn("2 ideas (0 kept", out)
        self.assertIn("size: ", out)

    def test_the_page_holds_every_idea_and_cannot_end_its_script(self):
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write("| 4 | ✗ | games | all | S | 1 | new | - | **Znacznik** — </script> w tekście | bo |\n")
        self.assertEqual(self.cli("page")[0], 0)
        with open(os.path.join(self.root, ideas.PAGE_FILE), encoding="utf-8") as f:
            page = f.read()
        self.assertNotIn("/*DATA*/", page)
        self.assertEqual(page.count("</script>"), 1)
        rows = re.search(r"const IDEAS = (\[.*?\]);\n", page).group(1)
        found = json.loads(rows.replace("<\\/", "</"))
        self.assertEqual([r["num"] for r in found], [1, 2, 3, 4])
        self.assertEqual((found[0]["title"], found[0]["what"]), ("Wisielec", "litery"))
        self.assertEqual(found[3]["mark"], "✗")

    @unittest.skipUnless(os.path.exists(os.path.join(ROOT, ideas.IDEAS_FILE)), "the .md files stay on the PC")
    def test_the_real_file_is_well_formed(self):
        path = os.path.join(ROOT, ideas.IDEAS_FILE)
        with open(path, encoding="utf-8") as f:
            lines = [line for line in f if ideas.ROW.match(line)]
        rows = [ideas.parse(line) for line in lines]
        self.assertGreaterEqual(len(rows), 100)
        self.assertEqual([r["num"] for r in rows], list(range(1, len(rows) + 1)))
        allowed = {"mark": set(ideas.MARKS.values()), "size": set("SML"), "value": set("123"),
                   "kind": {"new", "better"}, "for": {"maja", "grown", "all", "dev"},
                   "area": {"learn", "games", "play", "music", "home", "family", "her", "face",
                            "voice", "info", "health", "privacy", "robust", "cost", "dev", "hw"}}
        for r, line in zip(rows, lines):
            self.assertEqual(line.count("|"), 11, line)
            for field, values in allowed.items():
                self.assertIn(r[field], values, line)
            self.assertLessEqual(set(r["needs"].split(",")), {"-", "model", "net", "hw", "sudo"}, line)


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


class WakeMissesTest(unittest.TestCase):
    LOG = """\
[STT] heard="no pokaż pogodę" conf=0.87 peak_rms=3518 gate=2279 mouth talking 0%
[Luna heard] 12:06:10 no pokaż pogodę
[STT] Wake? name Vosk: no, general: "luna aż po go" (yes)
[Luna heard] 12:06:15 luna aż po go
[STT] cloud (0.8s): "Luna, pokaż pogodę."
[wake] ACCEPT request src=vosk conf=1.00 mode=idle radio=1 tts_ago=337s words=3 ms=1198
[STT] Wake word — conversation active
[STT] heard="a jutro" conf=0.90 peak_rms=3518 gate=2279
[Luna heard] 12:06:25 a jutro
[STT] cloud (0.8s): "A jutro?"
[STT] 12:06:40 Conversation timed out — waiting for wake word
[STT] heard="to wina" conf=0.71 peak_rms=4717 gate=721
[Luna heard] 18:48:36 to wina
[STT] cloud (0.9s): ""
[Luna heard] 18:48:41 molo
[STT] cloud (1.1s): "Luna."
[wake] ACCEPT bare src=vosk-name conf=0.59 mode=idle radio=0 tts_ago=- words=1 ms=2222
[STT] Wake word — conversation active
[STT] 18:49:00 Conversation timed out — waiting for wake word
[Luna heard] 19:30:00 luna która godzina
[wake] ACCEPT request src=vosk conf=1.00 mode=idle radio=0 tts_ago=- words=3 ms=900
""".splitlines()

    def test_a_call_said_twice_is_a_miss(self):
        import wake_misses
        rx = re.compile(r"(?<!\w)(luna)(?!\w)", re.I)
        utts = wake_misses.utterances(self.LOG)
        self.assertEqual([u["vosk"] for u in utts],
                         ["no pokaż pogodę", "luna aż po go", "a jutro", "to wina", "molo",
                          "luna która godzina"])
        self.assertTrue(utts[2]["window"])                   # a follow-up: not a call
        found = [(p["vosk"], wake_misses.kind(p, rx), u["vosk"])
                 for p, u in wake_misses.misses(utts, rx)]
        self.assertEqual(found, [("no pokaż pogodę", "not sent", "luna aż po go"),
                                 ("to wina", "cloud: nothing", "molo")])
        out = wake_misses.report(self.LOG, verbose=True, name_rx=rx)
        self.assertIn("3 calls answered from idle, 2 of them after 2 unanswered", out[0])
        self.assertIn("(66 % said twice)", out[0])
        self.assertTrue(any("not sent: 1 (1 with the radio on)" in ln for ln in out))


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
