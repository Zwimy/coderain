"""The SPA holds together (2026-07-28).

webapp/ is ~2,900 lines with no automated coverage, and it is where most of this
month's bugs actually were. Splitting it into ES modules made a new class of
mistake possible: an import that names something the other module doesn't
export, a module nothing loads, a fetch to a route that no longer exists.

Pure stdlib on purpose — no browser, no npm — so it runs everywhere the rest of
the suite does. It cannot catch a runtime ReferenceError; webapp_smoke_test.py
does that with a real browser when one is available.

Asserts:
 1) every import resolves to a file that really exports that name;
 2) no dead imports, and no module the entry point can't reach;
 3) index.html references only files that exist, and loads the SPA as a module;
 4) every /api/... path the UI calls is a route the server actually serves.
"""
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-web-")
os.environ["CODERAIN_HOME"] = HOME

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "webapp" / "js"
files = sorted(JS.glob("*.js"))
assert files, "no ES modules found in webapp/js"
src = {f.name: f.read_text(encoding="utf-8") for f in files}

# ---- parse ---------------------------------------------------------------
EXPORT = re.compile(
    r"^export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)",
    re.M)
# `export const a = 1, b = 2` — pick up the extra declarators too.
EXPORT_MULTI = re.compile(
    r"^export\s+(?:const|let|var)\s+[^;\n]*?,\s*([A-Za-z_$][\w$]*)\s*=", re.M)
IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']\./([\w.-]+)[\"']", re.S)

exports = {name: set(EXPORT.findall(t)) | set(EXPORT_MULTI.findall(t))
           for name, t in src.items()}
imports = {name: [(mod, [n.strip() for n in names.split(",") if n.strip()])
                  for names, mod in IMPORT.findall(t)]
           for name, t in src.items()}

# ---- 1) every import resolves -------------------------------------------
problems = []
for mod, entries in imports.items():
    for target, names in entries:
        if target not in src:
            problems.append(f"{mod} imports from ./{target}, which does not exist")
            continue
        for n in names:
            if n not in exports[target]:
                problems.append(f"{mod} imports {{{n}}} from ./{target}, "
                                f"which does not export it")
assert not problems, "broken imports:\n  " + "\n  ".join(problems)
total = sum(len(names) for e in imports.values() for _t, names in e)
print(f"1) {total} imports across {len(src)} modules all resolve")

# ---- 2) no dead imports, no unreachable modules -------------------------
IDENT = "(?<![\\w$.]){}(?![\\w$])"
dead = []
for mod, entries in imports.items():
    body = re.sub(r"^import\s*\{[^}]*\}[^\n]*$", "", src[mod], flags=re.M | re.S)
    for target, names in entries:
        for n in names:
            pat = (r"(?<![\w$.])\$(?![\w$])" if n == "$"
                   else IDENT.format(re.escape(n)))
            if not re.search(pat, body):
                dead.append(f"{mod} imports {n} from ./{target} but never uses it")
assert not dead, ("imports that nothing uses (a rename left them behind?):\n  "
                  + "\n  ".join(dead))

reachable, queue = {"app.js"}, ["app.js"]
while queue:
    cur = queue.pop()
    for target, _names in imports.get(cur, []):
        if target not in reachable:
            reachable.add(target)
            queue.append(target)
orphans = sorted(set(src) - reachable)
assert not orphans, f"modules nothing loads: {orphans}"
print(f"2) no dead imports; all {len(src)} modules reachable from app.js")

# ---- 3) index.html ------------------------------------------------------
html = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8")
refs = re.findall(r'(?:src|href)="([^"#:]+)"', html)
missing = [r for r in refs if not (ROOT / "webapp" / r).exists()]
assert not missing, f"index.html points at files that don't exist: {missing}"
assert re.search(r'<script\s+type="module"\s+src="js/app\.js"', html), \
    "index.html must load the SPA as a module (imports do not work otherwise)"
assert not (ROOT / "webapp" / "app.js").exists(), \
    "the old single-file app.js is back; it would shadow webapp/js/app.js"
print(f"3) index.html: {len(refs)} references, all present, SPA loads as a module")

# ---- 4) every route the UI calls actually exists -------------------------
import server  # noqa: E402

served = set(server.app.openapi()["paths"])


def _norm(p: str) -> str:
    """Both sides to a comparable shape: anything that varies becomes '*'.

    A UI path is a template literal, so `${slug}` is a hole; a route is a
    FastAPI pattern, so `{slug}` is one. A hole can also be a suffix the JS
    concatenates on (`/outline${n ? "/" + n : ""}`), which is why matching below
    is pattern-vs-pattern rather than a set lookup.
    """
    p = p.split("?")[0]                     # a query string is not part of the route
    p = re.sub(r"\$\{[^}]*\}", "*", p)      # JS template holes
    p = re.sub(r"\{[^}]*\}", "*", p)        # FastAPI path params
    p = re.sub(r"\*+", "*", p)
    return re.sub(r"/+", "/", p).rstrip("/") or "/"


def _rx(p: str) -> re.Pattern:
    # `[^/]*`, NOT `.*`: a path param never spans a slash, and a wildcard that
    # does makes /api/saves/{slug} match everything beneath it — which silently
    # accepted a call to a route that does not exist (caught by breaking it).
    return re.compile("".join("[^/]*" if part == "*" else re.escape(part)
                              for part in re.split(r"(\*)", p)) + r"/?")


served_norm = {_norm(p) for p in served}
served_rx = [(_rx(p), p) for p in served_norm]
called = set()
for text in src.values():
    for m in re.finditer(r"[\"'`](/api/[^\"'`\s]*)[\"'`]", text):
        called.add(_norm(m.group(1)))
assert called, "no API calls found in the SPA — the scan is broken, not the app"
# Both sides carry wildcards, so a call is known if its pattern and some route's
# pattern can describe the same string — checked in both directions.
unknown = []
for c in sorted(called):
    crx = _rx(c)
    probe = c.replace("*", "x")
    hit = any(rx.fullmatch(probe) or crx.fullmatch(p.replace("*", "x"))
              for rx, p in served_rx)
    # The builder holds a base URL and appends to it (`${base}/full`), so a call
    # that is a segment-prefix of a real route is a prefix, not a typo.
    hit = hit or any(p.replace("*", "x").startswith(probe + "/") for _rx_, p
                     in served_rx)
    if not hit:
        unknown.append(c)
assert not unknown, ("the UI calls routes the server does not serve:\n  "
                     + "\n  ".join(unknown))
print(f"4) all {len(called)} distinct /api paths the UI calls are real routes")

shutil.rmtree(HOME, ignore_errors=True)
print("\nWEBAPP INTEGRITY TESTS PASSED")
