"""
codemap.py — find your way in the code without reading it (Python's ast; no
imports run, so it works on the PC for Pi-only modules too).

    python -X utf8 tools/codemap.py                  # every module: lines, what it is
    python -X utf8 tools/codemap.py radio            # radio.py: defs and constants with line numbers
    python -X utf8 tools/codemap.py tools/sweep tests/smoke_pi
    python -X utf8 tools/codemap.py -f wake brain    # defs and constants named *wake*
                                                     # (in those modules, or everywhere)
Then read just those lines: Read with offset/limit, or sed -n 120,160p radio.py.
"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUT = 70


def parse(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    return ast.parse(src), src.count("\n") + 1


def first_line(node):
    doc = ast.get_docstring(node) or ""
    # (a file's docstring often opens with "name.py — what it does")
    line = doc.strip().split("\n")[0] if doc.strip() else ""
    return re.sub(r"^[\w./]+\.py\s*[—:-]\s*", "", line)


def args_of(fn):
    names = [a.arg for a in fn.args.posonlyargs + fn.args.args if a.arg not in ("self", "cls")]
    if fn.args.vararg:
        names.append("*" + fn.args.vararg.arg)
    names += [a.arg for a in fn.args.kwonlyargs]
    return ", ".join(names)


def symbols(tree):
    """(line, indent, text, name) of each class, def and UPPER_CASE constant."""
    out = []

    def visit_def(node, indent):
        doc = first_line(node)
        if isinstance(node, ast.ClassDef):
            text = f"class {node.name}"
        else:
            text = f"{node.name}({args_of(node)})"
        out.append((node.lineno, indent, text + (f"  # {doc[:CUT]}" if doc else ""), node.name))
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_def(child, indent + 1)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            visit_def(node, 0)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and re.fullmatch(r"_?[A-Z][A-Z0-9_]*", t.id):
                    out.append((node.lineno, 0, t.id, t.id))
    return out


def resolve(name):
    """'radio', 'radio.py' or 'tools/sweep' → the file, or None."""
    name = name.replace("\\", "/")
    path = name if name.endswith(".py") else name + ".py"
    path = os.path.join(ROOT, path)
    return path if os.path.isfile(path) else None


def all_modules():
    return sorted(glob.glob(os.path.join(ROOT, "*.py")))


def overview():
    for path in all_modules():
        tree, lines = parse(path)
        print(f"{os.path.basename(path)[:-3]:18s} {lines:5d}  {first_line(tree)[:90]}")


def outline(path):
    tree, lines = parse(path)
    print(f"{os.path.relpath(path, ROOT)} — {lines} lines — {first_line(tree)[:100]}")
    plain = []
    for line, indent, text, _ in symbols(tree):
        if text.isupper() or re.fullmatch(r"_?[A-Z][A-Z0-9_]*", text):
            plain.append(f"{text}:{line}")
        else:
            print(f"{line:5d} {'  ' * indent}{text}")
    if plain:
        print("constants: " + " ".join(plain))


def find(word, paths):
    word = word.lower()
    hits = 0
    for path in paths:
        tree, _ = parse(path)
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        for line, _, text, name in symbols(tree):
            if word in name.lower():
                print(f"{rel}:{line}  {text}")
                hits += 1
    if not hits:
        print(f"no def or constant named *{word}* — it may still be in the text: grep -n")


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv[:1] == ["-f"]:
        if len(argv) < 2:
            print(__doc__.strip())
            return 2
        paths = [resolve(a) for a in argv[2:]]
        if None in paths:
            print(f"no such module: {argv[2:][paths.index(None)]}")
            return 2
        find(argv[1], paths or all_modules())
        return 0
    if not argv:
        overview()
        return 0
    for name in argv:
        path = resolve(name)
        if not path:
            print(f"no such module: {name}")
            return 2
        outline(path)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")   # the Windows console is cp1252
    sys.exit(main(sys.argv[1:]))
