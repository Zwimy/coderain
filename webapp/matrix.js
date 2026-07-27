/* Matrix digital rain — a fixed full-screen canvas behind all content.
   Kept dim + short-trailed so story prose over it stays readable; the topbar,
   page margins, and card gutters are where it reads most. */
(function () {
  const canvas = document.createElement("canvas");
  canvas.id = "matrix-rain";
  canvas.setAttribute("aria-hidden", "true");
  Object.assign(canvas.style, {
    position: "fixed", inset: "0", zIndex: "-1", pointerEvents: "none",
  });
  document.body.prepend(canvas);
  const ctx = canvas.getContext("2d");

  const GLYPHS = "アカサタナハマヤラ0123456789CODERAIN".split("");
  const STEP = 16;                       // column width / row height (px)
  const FADE = 0.7;                      // per-row falloff behind the lead glyph
  const TAIL = 14;                       // rows still bright enough to matter
  let cols, rows, drops, glyph, lead;

  function paintBase() {
    // EXACTLY transparent — clearRect writes literal zeros, so the page's own
    // html{background:var(--bg)} shows through untouched.
    //
    // This used to fill an opaque copy of --bg and fade it with an alpha wash,
    // which cannot converge: compositing rgba(3,6,10,0.30) over a pixel already
    // at rgb(3,6,10) rounds to rgb(3,6,9) and then stays there. The whole
    // viewport settled one step off the page and read as a faint dark rectangle.
    // Raising the wash alpha only moved the resting point. Drawing the trail
    // explicitly (below) removes the rounding loop entirely, and as a bonus the
    // backdrop now follows the active theme instead of a hardcoded #03060a.
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    cols = Math.ceil(canvas.width / STEP);
    rows = Math.ceil(canvas.height / STEP) + 1;
    drops = Array.from({length: cols}, () =>
      Math.floor(Math.random() * -50));  // stagger the start of each column
    // A cell keeps the glyph and brightness it was born with, so the tail fades
    // in place instead of re-randomising into static every frame.
    glyph = Array.from({length: cols}, () => new Array(rows).fill(""));
    lead = Array.from({length: cols}, () => new Uint8Array(rows));
    paintBase();
  }
  resize();
  window.addEventListener("resize", resize);

  function draw() {
    paintBase();
    ctx.font = STEP + "px monospace";
    for (let i = 0; i < cols; i++) {
      const head = drops[i];
      if (head >= 0 && head < rows && !glyph[i][head]) {
        glyph[i][head] = GLYPHS[(Math.random() * GLYPHS.length) | 0];
        lead[i][head] = Math.random() > 0.94 ? 1 : 0;   // occasional bright one
      }
      // Same falloff the wash produced (alpha x0.7 per frame, head moves one row
      // per frame), so the look is unchanged — only the residue is gone.
      for (let k = 0; k < TAIL; k++) {
        const row = head - k;
        if (row < 0 || row >= rows || !glyph[i][row]) continue;
        const f = Math.pow(FADE, k);
        ctx.fillStyle = lead[i][row]
          ? `rgba(120, 255, 140, ${0.85 * f})`
          : `rgba(31, 218, 37, ${0.5 * f})`;
        ctx.fillText(glyph[i][row], i * STEP, row * STEP);
      }
      if (head * STEP > canvas.height && Math.random() > 0.975) {
        drops[i] = 0;
        glyph[i].fill("");
      }
      drops[i]++;
    }
  }

  let last = 0;
  const FRAME_MS = 55;                    // ~18 fps — calm, not seizure-y
  let running = false;
  let rafId = 0;
  function loop(ts) {
    if (!running) return;
    if (ts - last >= FRAME_MS) { draw(); last = ts; }
    rafId = requestAnimationFrame(loop);
  }

  /* WCAG 2.2.2 (Level A) applies to auto-updating content and allows NO grace
     period, so a full-screen animation needs a real stop — the OS preference
     alone is not enough. `prefers-reduced-motion` is honoured automatically and
     Settings can override either way; the choice persists. */
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  const stored = () => {
    try { return localStorage.getItem("coderain_motion"); } catch (_e) { return null; }
  };
  const wanted = () => {
    const s = stored();
    if (s === "off") return false;
    if (s === "on") return true;
    return !mq.matches;                   // no explicit choice: follow the OS
  };

  function apply() {
    const on = wanted();
    document.documentElement.dataset.motion = on ? "on" : "off";
    if (on && !running) {
      running = true;
      last = 0;
      rafId = requestAnimationFrame(loop);
    } else if (!on && running) {
      running = false;
      cancelAnimationFrame(rafId);
      paintBase();                        // leave a clean static backdrop
    } else if (!on) {
      paintBase();
    }
  }

  /* Settings toggle calls this; `null` clears the override back to the OS. */
  window.setRain = function (on) {
    try {
      if (on === null) localStorage.removeItem("coderain_motion");
      else localStorage.setItem("coderain_motion", on ? "on" : "off");
    } catch (_e) { /* private mode: session-only */ }
    apply();
  };
  window.rainOn = wanted;

  mq.addEventListener("change", () => { if (!stored()) apply(); });
  apply();
})();
