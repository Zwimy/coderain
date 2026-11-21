/* Accessible names for the markup the views build as strings.

   The views write `<label>Name</label><input id="b-title">` as plain siblings: the label is not tied to the input, so a screen
   reader announced "edit text" with no name (108 labels and not one `for`, found by an audit and confirmed in a browser: 10 of
   the 11 fields of the world builder, and the box you type your action into, had no name). Wiring every template by hand would
   touch every module and rot again, so this observes the places the views render into and ties each label to the control it
   sits beside, once, whenever markup is added. It only ever ADDS attributes, never changes the DOM tree, so it cannot retrigger
   itself. */
const CONTROL = "input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea, select";
let counter = 0;

/* The control a bare label belongs to: the next control among its siblings, or one inside a sibling wrapper that holds no label
   of its own (the chip inputs are wrapped), stopping at the next label so two fields never share a name. */
function controlFor(label) {
  for (let el = label.nextElementSibling; el; el = el.nextElementSibling) {
    if (el.matches("label")) return null;
    if (el.matches(CONTROL)) return el;
    const inner = el.querySelector(CONTROL);
    if (inner && !el.querySelector("label")) return inner;
  }
  return null;
}

export function labelize(root) {
  for (const label of root.querySelectorAll("label:not([for])")) {
    if (label.querySelector("input, textarea, select")) continue;        // a label that wraps its control already names it
    const control = controlFor(label);
    if (!control || (control.labels && control.labels.length)) continue;
    if (!control.id) control.id = `auto-field-${++counter}`;
    label.htmlFor = control.id;
  }
  // What is still unnamed but says what it is for in its placeholder or title (the action box) is named by that.
  for (const el of root.querySelectorAll(CONTROL)) {
    if ((el.labels && el.labels.length) || el.hasAttribute("aria-label") || el.hasAttribute("aria-labelledby")) continue;
    const hint = el.getAttribute("placeholder") || el.getAttribute("title");
    if (hint) el.setAttribute("aria-label", hint);
  }
}

/* The choice a segmented control (`.seg`) has made is the button with class "on", which is only a colour: a screen reader
   announced six or so buttons and never which one was current. Mirror the class into aria-pressed so it says "pressed" or "not
   pressed". Read from the class, so no view has to remember to set it and the six places that toggle "on" stay as they are. */
export function syncPressed(root) {
  for (const b of root.querySelectorAll(".seg button")) {
    const on = String(b.classList.contains("on"));
    if (b.getAttribute("aria-pressed") !== on) b.setAttribute("aria-pressed", on);
  }
}

/* Label what is on screen now and whatever a view or a modal renders later. Streaming text only adds text nodes, which are
   ignored, so a long reply costs nothing here. */
export function watchLabels(...roots) {
  for (const root of roots) {
    if (!root) continue;
    labelize(root);
    syncPressed(root);
    let queued = false;
    // New elements are labelled; a class change on a segmented button re-reads which one is pressed. The class filter keeps
    // the observer quiet (it does not see the aria-pressed it writes, so it cannot retrigger itself).
    const relevant = m => m.type === "attributes"
      ? m.target.matches && m.target.matches(".seg button")
      : [...m.addedNodes].some(n => n.nodeType === 1);
    new MutationObserver(muts => {
      if (queued || !muts.some(relevant)) return;
      queued = true;
      // A timer, not requestAnimationFrame: a frame never comes for a tab that is in the background or a pane that is hidden,
      // and the names are for whoever is reading the page, painted or not.
      setTimeout(() => { queued = false; labelize(root); syncPressed(root); }, 30);
    }).observe(root, {childList: true, subtree: true, attributes: true, attributeFilter: ["class"]});
  }
}
