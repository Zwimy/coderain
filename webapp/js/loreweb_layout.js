/* Where the lore web's entries sit: a small force layout (Fruchterman-Reingold). No DOM here, so Node can test it.

   Deterministic: no random numbers, so the same web draws the same picture. `start` holds positions already on screen; with it the
   layout only settles gently, so adding a tie does not throw the whole picture around. */

export const MARGIN = 28;           // top and bottom; a label sits above its node
export const SIDE = 56;             // left and right; a label is centred on its node, so it needs room either side

export function layout(ids, links, width, height, start = {}) {
  const n = ids.length;
  const pos = {};
  if (!n) return pos;
  const side = Math.min(SIDE, width / 5);
  const known = ids.filter(id => start[id]).length;
  ids.forEach((id, i) => {
    const a = (2 * Math.PI * i) / n;
    pos[id] = start[id] ? {x: start[id].x, y: start[id].y}
      : {x: width / 2 + Math.cos(a) * width * 0.35, y: height / 2 + Math.sin(a) * height * 0.35};
  });
  const edges = links.filter(([a, b]) => pos[a] && pos[b] && a !== b);
  const k = Math.sqrt((width * height) / n) * 0.75;
  // Gravity grows with the number of entries: their push apart does too, and a fixed pull left a web with few connections as a ring
  // along the walls. This size holds an unconnected crowd in a loose cluster about two thirds of the way out, wider than it is tall.
  const reach = Math.min(width, height) * 0.46;
  const pull = (n * k * k) / (reach * reach);
  const settled = known > n / 2;
  let temp = settled ? width / 60 : width / 8;
  const rounds = settled ? 60 : 260;
  for (let round = 0; round < rounds; round++) {
    const move = {};
    ids.forEach(id => { move[id] = {x: 0, y: 0}; });
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = ids[i], b = ids[j];
        let dx = pos[a].x - pos[b].x, dy = pos[a].y - pos[b].y;
        if (!dx && !dy) { dx = 0.01 * (i - j); dy = 0.01 * (j % 3 - 1) || 0.01; }
        const d = Math.hypot(dx, dy), f = (k * k) / d;
        move[a].x += (dx / d) * f; move[a].y += (dy / d) * f;
        move[b].x -= (dx / d) * f; move[b].y -= (dy / d) * f;
      }
    }
    for (const [a, b] of edges) {
      const dx = pos[a].x - pos[b].x, dy = pos[a].y - pos[b].y;
      const d = Math.hypot(dx, dy) || 0.01, f = (d * d) / k;
      move[a].x -= (dx / d) * f; move[a].y -= (dy / d) * f;
      move[b].x += (dx / d) * f; move[b].y += (dy / d) * f;
    }
    for (const id of ids) {
      move[id].x += (width / 2 - pos[id].x) * pull * Math.min(1, height / width);
      move[id].y += (height / 2 - pos[id].y) * pull * Math.min(1, width / height);
      const len = Math.hypot(move[id].x, move[id].y) || 0.01;
      const step = Math.min(len, temp);
      pos[id].x = Math.min(width - side, Math.max(side, pos[id].x + (move[id].x / len) * step));
      pos[id].y = Math.min(height - MARGIN / 2, Math.max(MARGIN, pos[id].y + (move[id].y / len) * step));
    }
    temp *= 0.975;
  }
  return pos;
}
