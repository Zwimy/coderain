"""The lore web's layout (webapp/js/loreweb_layout.js), run in Node: no DOM, no random numbers.

 1) every entry gets a position inside the box, no two on top of each other, also for 1 entry, none, and 120
 2) the same web gives the same picture
 3) connected entries end up closer to each other than unconnected ones on average
 4) a start position keeps the picture nearly where it was when one tie is added
 5) a connection to an entry that is not there, or to itself, is ignored
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: node is not installed; the lore web layout is not checked here")
    print("\nLORE WEB LAYOUT TESTS PASSED (skipped)")
    sys.exit(0)

SCRIPT = r"""
import {layout, MARGIN, SIDE} from %s;
const W = 640, H = 420, out = {margin: MARGIN, side: SIDE};
const ids = n => Array.from({length: n}, (_, i) => "e" + i);
const check = (p, list) => {
  const pts = list.map(i => p[i]);
  let inside = pts.every(q => q && q.x >= SIDE && q.x <= W - SIDE && q.y >= MARGIN && q.y <= H - MARGIN / 2);
  let closest = Infinity;
  for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++)
    closest = Math.min(closest, Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y));
  return {inside, closest};
};
out.none = Object.keys(layout([], [], W, H)).length;
out.one = check(layout(ids(1), [], W, H), ids(1));
const pairs = [["e0","e1"],["e1","e2"],["e2","e0"],["e3","e4"],["e4","e5"],["e5","e3"]];
const a = layout(ids(12), pairs, W, H), b = layout(ids(12), pairs, W, H);
out.twelve = check(a, ids(12));
out.same = JSON.stringify(a) === JSON.stringify(b);
const dist = (p, x, y) => Math.hypot(p[x].x - p[y].x, p[x].y - p[y].y);
const linked = pairs.reduce((s, [x, y]) => s + dist(a, x, y), 0) / pairs.length;
let un = 0, k = 0;
for (let i = 0; i < 12; i++) for (let j = i + 1; j < 12; j++) {
  if (pairs.some(([x, y]) => (x === "e"+i && y === "e"+j) || (x === "e"+j && y === "e"+i))) continue;
  un += dist(a, "e"+i, "e"+j); k++;
}
out.linked = linked; out.unlinked = un / k;
const again = layout(ids(12), [...pairs, ["e6","e7"]], W, H, a);
out.moved = ids(12).reduce((s, i) => s + Math.hypot(again[i].x - a[i].x, again[i].y - a[i].y), 0) / 12;
out.many = check(layout(ids(120), pairs, W, H), ids(120));
const loose = layout(ids(15), [], W, H);
out.walls = ids(15).filter(i => loose[i].x <= SIDE + 1 || loose[i].x >= W - SIDE - 1 || loose[i].y <= MARGIN + 1 || loose[i].y >= H - MARGIN / 2 - 1).length;
out.loose = check(loose, ids(15));
const junk = layout(ids(3), [["e0","ghost"],["ghost","e1"],["e2","e2"]], W, H);
out.junk = check(junk, ids(3));
console.log(JSON.stringify(out));
""" % json.dumps((ROOT / "webapp" / "js" / "loreweb_layout.js").as_uri())

r = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT], capture_output=True, text=True, timeout=120)
assert r.returncode == 0, r.stderr[-800:]
o = json.loads(r.stdout.strip().splitlines()[-1])
assert o["none"] == 0 and o["one"]["inside"], o
assert o["twelve"]["inside"] and o["twelve"]["closest"] > 25, o["twelve"]
assert o["many"]["inside"] and o["many"]["closest"] > 2, o["many"]
assert o["walls"] <= 2 and o["loose"]["closest"] > 25, ("unconnected entries ring the walls", o["walls"], o["loose"])
print("1. every entry gets a place inside the box, apart from the others, for none, 1, 12 and 120; unconnected ones do not ring the walls")
assert o["same"]
print("2. the same web draws the same picture")
assert o["linked"] < o["unlinked"] * 0.75, (o["linked"], o["unlinked"])
print(f"3. connected entries sit closer ({o['linked']:.0f}) than unconnected ones ({o['unlinked']:.0f})")
assert o["moved"] < 40, o["moved"]
print(f"4. adding a tie moves the picture little ({o['moved']:.0f} units on average)")
assert o["junk"]["inside"] and o["junk"]["closest"] > 25, o["junk"]
print("5. a connection to nothing or to itself is ignored")
print("\nLORE WEB LAYOUT TESTS PASSED")
