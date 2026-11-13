"""
cmdlog.py — which of commands.handle's rules took a sentence.

handle() is one long list of rules tried in order; the log said what she did
but not which rule decided it, and nobody knew which rules are ever used.
instrument() rebuilds handle once at import so every `return` reports its
line; a line belongs to one top-level rule, named after what it tests
("moon.answer", "sleep_self"). The order and the code of the rules are
untouched. Counts go to data/rules.json (only in the running Luna).
"""

import ast
import functools
import inspect
import re
import threading

import errlog
import store

ON = [False]               # commands.start_commands(): log and count (not in tests)
_rules = []                # [(first line, last line, name)] of handle's top-level rules
_counts = None
_tl = threading.local()
_lock = threading.Lock()
_PLAIN = {"any", "all", "bool", "len", "next", "isinstance", "re", "time", "low", "text"}


def _label(expr):
    """A name for what an expression tests: its _CONSTANT, else its first call."""
    consts = [n.id for n in ast.walk(expr)
              if isinstance(n, ast.Name) and re.fullmatch(r"_[A-Z][A-Z0-9_]+", n.id)]
    if consts:
        return consts[0].strip("_").lower()
    for n in ast.walk(expr):
        if isinstance(n, ast.Call):
            f = ast.unparse(n.func)
            if f.split(".")[0] not in _PLAIN:
                return f
    return None


def _name_rules(fdef):
    """Every top-level statement of handle that can return → (lines, name)."""
    out, assigned = [], {}
    for st in fdef.body:
        if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
            assigned[st.targets[0].id] = st.value
        if not any(isinstance(n, ast.Return) for n in ast.walk(st)):
            continue
        name = _label(st.test) if isinstance(st, ast.If) else None
        if not name and isinstance(st, ast.If):
            for n in ast.walk(st.test):            # `if said:` — what said was made from
                if isinstance(n, ast.Name) and n.id in assigned:
                    name = _label(assigned[n.id])
                    break
        out.append((st.lineno, st.end_lineno, name or f"line {st.lineno}"))
    return out


def rule_at(line):
    for first, last, name in _rules:
        if first <= line <= last:
            return name
    return f"line {line}"


def _took(value, line):
    """The first return that took it counts: "proszę, zgaś lampę" is the
    lamp's rule, not the polite one that passed it on."""
    if value and not getattr(_tl, "line", 0):
        _tl.line = line
    return value


class _Returns(ast.NodeTransformer):
    """`return x` → `return _cmdlog_took(x, line)`, in handle's own body only."""

    def __init__(self, top):
        self.top = top

    def visit_FunctionDef(self, node):
        return self.generic_visit(node) if node is self.top else node

    def visit_Lambda(self, node):
        return node

    def visit_Return(self, node):
        value = node.value or ast.Constant(None)
        call = ast.Call(ast.Name("_cmdlog_took", ast.Load()), [value, ast.Constant(node.lineno)], [])
        return ast.copy_location(ast.Return(call), node)


def instrument(fn):
    """handle, reporting which rule returned. Anything going wrong: fn as it was."""
    try:
        tree = ast.parse(inspect.getsource(fn))
        ast.increment_lineno(tree, fn.__code__.co_firstlineno - 1)
        fdef = tree.body[0]
        _rules[:] = _name_rules(fdef)
        ast.fix_missing_locations(_Returns(fdef).visit(tree))
        scope = {}
        fn.__globals__["_cmdlog_took"] = _took
        exec(compile(tree, fn.__code__.co_filename, "exec"), fn.__globals__, scope)
        inner = scope[fn.__name__]
    except Exception:
        errlog.once("cmdlog")
        return fn

    @functools.wraps(fn)
    def handle(*args, **kw):
        depth = getattr(_tl, "depth", 0)
        if depth == 0:
            _tl.line = 0
        _tl.depth = depth + 1
        try:
            result = inner(*args, **kw)
        finally:
            _tl.depth = depth
        if depth == 0 and result and ON[0]:
            note(rule_at(getattr(_tl, "line", 0)), getattr(_tl, "line", 0))
        return result
    return handle


def _path():
    import os
    import config
    return os.path.join(config.DATA_DIR, "rules.json")


def note(name, line=0):
    """One sentence went to this rule: a log line, and one more in its count."""
    global _counts
    print(f"[cmd] rule: {name} (commands.py:{line})", flush=True)
    try:
        with _lock:
            if _counts is None:
                _counts = store.load(_path(), {}, "cmdlog")
            _counts[name] = int(_counts.get(name, 0)) + 1
            store.save(_path(), _counts, indent=1, sync=False)
    except Exception:
        errlog.once("cmdlog")
