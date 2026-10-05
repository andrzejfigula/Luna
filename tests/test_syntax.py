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


class UndefinedNameTest(unittest.TestCase):
    """A name used in a function that nothing defines — a typo or a missing
    import — only fails when that line runs, often on the Pi, often at night.
    symtable knows each function's globals; they must exist at module level
    or be built in."""

    def test_every_global_name_is_defined(self):
        import builtins
        import symtable
        known_builtins = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
        for path in glob.glob(os.path.join(ROOT, "*.py")):
            src = open(path, encoding="utf-8").read()
            top = symtable.symtable(src, path, "exec")
            module_names = {s.get_name() for s in top.get_symbols()
                            if s.is_assigned() or s.is_imported() or s.is_namespace()}

            def declared(table):              # `global X` + `X = …` inside a function
                for child in table.get_children():
                    module_names.update(s.get_name() for s in child.get_symbols()
                                        if s.is_declared_global() and s.is_assigned())
                    declared(child)
            declared(top)

            def walk(table):
                for child in table.get_children():
                    for s in child.get_symbols():
                        if (s.is_global() and s.is_referenced()
                                and s.get_name() not in module_names
                                and s.get_name() not in known_builtins):
                            with self.subTest(file=os.path.basename(path),
                                              scope=child.get_name()):
                                self.fail(f"'{s.get_name()}' is used in "
                                          f"{child.get_name()}() but defined nowhere")
                    walk(child)
            walk(top)


class StateFieldTest(unittest.TestCase):
    """shared_state has fixed slots: `state.radoi` or a field nobody added
    raises AttributeError only when that line runs."""

    def test_every_state_field_exists(self):
        import re
        import sys
        sys.path.insert(0, ROOT)
        from shared_state import state
        fields = set(type(state).__slots__) | {"lock"} | set(dir(state))
        for path in glob.glob(os.path.join(ROOT, "*.py")):
            src = open(path, encoding="utf-8").read()
            for name in sorted(set(re.findall(r"\bstate\.([a-zA-Z_]\w*)", src))):
                with self.subTest(file=os.path.basename(path), field=name):
                    self.assertIn(name, fields)


class LockTest(unittest.TestCase):

    def test_state_lock_is_reentrant(self):
        import sys
        sys.path.insert(0, ROOT)
        from shared_state import state
        with state.lock:
            self.assertTrue(state.lock.acquire(timeout=0.5))   # a plain Lock deadlocks
            state.lock.release()


class ShadowTest(unittest.TestCase):
    """A local variable named like an imported module breaks the module in the
    whole function ("cannot access local variable 'mood'") — it happened in
    brain.py, which the tests can't import on a dev machine."""

    def test_no_local_shadows_an_import(self):
        import ast
        for path in glob.glob(os.path.join(ROOT, "*.py")):
            tree = ast.parse(open(path, encoding="utf-8").read())
            imported = set()
            for node in tree.body:
                if isinstance(node, ast.Import):
                    imported |= {(a.asname or a.name).split(".")[0] for a in node.names}
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                local_imports = {(a.asname or a.name).split(".")[0]
                                 for n in ast.walk(fn) if isinstance(n, ast.Import)
                                 for a in n.names}
                for n in ast.walk(fn):
                    targets = []
                    if isinstance(n, ast.Assign):
                        targets = n.targets
                    elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.For)):
                        targets = [n.target]
                    for t in targets:
                        for name in ast.walk(t):
                            if (isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store)
                                    and name.id in imported
                                    and name.id not in local_imports):
                                with self.subTest(file=os.path.basename(path), fn=fn.name):
                                    self.fail(f"local '{name.id}' shadows the module "
                                              f"in {fn.name}()")


if __name__ == "__main__":
    unittest.main()
