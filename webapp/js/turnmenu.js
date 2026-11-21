/* The per-turn menu: what you can do with one turn (edit it, copy it, branch the story from it, regenerate it) in one place, on a
   "..." button at the turn and on a long press of a touch screen.

   This module owns the menu: building it, putting it on screen, the keyboard (arrows, Home and End, Escape, Tab) and closing it
   whenever the reader moves on. What each item DOES belongs to the play view, which knows the story, so it is handed in as
   `itemsFor(turn)` -> [{label, run, disabled, why}].

   The menu goes on <body>, never into #transcript: the pen and retry address a turn by its position among the children of
   #transcript, so nothing may be added there. */
const HOLD_MS = 550;           // a touch held this long opens the menu
const SLOP = 10;               // a finger that moves more than this is scrolling, not holding

export function createTurnMenu({transcript, itemsFor}) {
  let current = null;          // {menu, trigger, off: [fn]} while a menu is on screen

  const closeMenu = (restoreFocus = true) => {
    if (!current) return;
    const {menu, trigger, off} = current;
    current = null;
    off.forEach(fn => fn());
    menu.remove();
    if (trigger) {
      trigger.setAttribute("aria-expanded", "false");
      if (restoreFocus) trigger.focus();
    }
  };

  const openMenu = (turn, trigger, point) => {
    closeMenu(false);
    const menu = document.createElement("div");
    menu.className = "turn-menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", turn.classList.contains("player") ? "Your action" : "This reply");
    for (const item of itemsFor(turn)) {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "menuitem");
      b.textContent = item.label;
      if (item.disabled) { b.disabled = true; b.title = item.why || ""; }
      b.addEventListener("click", () => { closeMenu(false); item.run(); });
      menu.append(b);
    }
    document.body.append(menu);

    // Below the button (or at the finger), moved back inside the window when it would not fit.
    const at = trigger ? trigger.getBoundingClientRect() : {left: point.x, right: point.x, top: point.y, bottom: point.y};
    const w = menu.offsetWidth, h = menu.offsetHeight;
    const left = trigger ? at.right - w : at.left;
    menu.style.left = `${Math.max(8, Math.min(left, innerWidth - w - 8))}px`;
    menu.style.top = `${at.bottom + h + 8 > innerHeight ? Math.max(8, at.top - h - 4) : at.bottom + 4}px`;

    const enabled = () => [...menu.querySelectorAll("button:not([disabled])")];
    const onKey = ev => {
      const items = enabled();
      const i = items.indexOf(document.activeElement);
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); closeMenu(true); }
      else if (ev.key === "Tab") closeMenu(false);                       // focus moves on from where it is
      else if (ev.key === "ArrowDown" || ev.key === "ArrowUp" || ev.key === "Home" || ev.key === "End") {
        ev.preventDefault();
        if (!items.length) return;
        const next = ev.key === "Home" ? 0 : ev.key === "End" ? items.length - 1
          : (i + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items[next].focus();
      }
    };
    const onPointer = ev => {
      if (menu.contains(ev.target) || (trigger && trigger.contains(ev.target))) return;
      closeMenu(false);
    };
    const onLeave = () => closeMenu(false);
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer, true);
    transcript.addEventListener("scroll", onLeave);
    window.addEventListener("hashchange", onLeave);
    current = {menu, trigger, off: [
      () => document.removeEventListener("keydown", onKey, true),
      () => document.removeEventListener("pointerdown", onPointer, true),
      () => transcript.removeEventListener("scroll", onLeave),
      () => window.removeEventListener("hashchange", onLeave),
    ]};
    if (trigger) trigger.setAttribute("aria-expanded", "true");
    const first = enabled()[0];
    if (first) first.focus();
  };

  // A long press on a turn (touch only: a mouse has the button, and holding the mouse button is selecting text).
  let hold = null;
  const cancelHold = () => { if (hold) { clearTimeout(hold.timer); hold = null; } };
  transcript.addEventListener("pointerdown", ev => {
    if (ev.pointerType !== "touch" || ev.target.closest("button, textarea, .swipebar, .turn-editbar")) return;
    const turn = ev.target.closest(".turn");
    if (!turn) return;
    cancelHold();
    const start = {x: ev.clientX, y: ev.clientY};
    hold = {...start, timer: setTimeout(() => { hold = null; openMenu(turn, null, start); }, HOLD_MS)};
  });
  transcript.addEventListener("pointermove", ev => {
    if (hold && Math.hypot(ev.clientX - hold.x, ev.clientY - hold.y) > SLOP) cancelHold();
  });
  for (const type of ["pointerup", "pointercancel", "pointerleave"]) transcript.addEventListener(type, cancelHold);

  /* The "..." button for one turn. */
  const trigger = turn => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "turn-more";
    b.textContent = "⋯";
    b.title = "more";
    b.setAttribute("aria-label", turn.classList.contains("player") ? "More for your action" : "More for this reply");
    b.setAttribute("aria-haspopup", "menu");
    b.setAttribute("aria-expanded", "false");
    b.addEventListener("click", ev => {
      ev.stopPropagation();
      if (current && current.trigger === b) closeMenu(true);
      else openMenu(turn, b);
    });
    return b;
  };

  return {trigger, close: closeMenu};
}
