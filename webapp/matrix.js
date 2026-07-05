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

  const GLYPHS = "アカサタナハマヤラ0123456789STORYENGINE".split("");
  const STEP = 16;                       // column width / row height (px)
  let cols, drops;

  function paintBase() {
    // Lay down an OPAQUE background first so painted and never-painted regions
    // are byte-identical — otherwise the canvas alpha caps below 255 and the
    // rain band reads as a faint grey rectangle against the page.
    ctx.fillStyle = "#03060a";               // == --bg, fully opaque
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    cols = Math.ceil(canvas.width / STEP);
    drops = Array.from({length: cols}, () =>
      Math.floor(Math.random() * -50));  // stagger the start of each column
    paintBase();
  }
  resize();
  window.addEventListener("resize", resize);

  function draw() {
    // Opaque-background wash → the classic fading trail. Colour == --bg and the
    // alpha is high enough that faded glyphs actually reach the background
    // instead of lingering as a grey-green haze (measured: prior 0.16 left the
    // band at rgb 2,8,14 vs the 3,6,10 page — a visible rectangle).
    ctx.fillStyle = "rgba(3, 6, 10, 0.30)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.font = STEP + "px monospace";
    for (let i = 0; i < drops.length; i++) {
      const g = GLYPHS[(Math.random() * GLYPHS.length) | 0];
      const y = drops[i] * STEP;
      // lead glyph brighter, the rest dim green — reads as depth
      ctx.fillStyle = Math.random() > 0.94
        ? "rgba(120, 255, 140, 0.85)" : "rgba(31, 218, 37, 0.5)";
      ctx.fillText(g, i * STEP, y);
      if (y > canvas.height && Math.random() > 0.975) drops[i] = 0;
      drops[i]++;
    }
  }

  let last = 0;
  const FRAME_MS = 55;                    // ~18 fps — calm, not seizure-y
  function loop(ts) {
    if (ts - last >= FRAME_MS) { draw(); last = ts; }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})();
