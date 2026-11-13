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

/* Label what is on screen now and whatever a view or a modal renders later. Streaming text only adds text nodes, which are
   ignored, so a long reply costs nothing here. */
export function watchLabels(...roots) {
  for (const root of roots) {
    if (!root) continue;
    labelize(root);
    let queued = false;
    new MutationObserver(muts => {
      if (queued || !muts.some(m => [...m.addedNodes].some(n => n.nodeType === 1))) return;
      queued = true;
      // A timer, not requestAnimationFrame: a frame never comes for a tab that is in the background or a pane that is hidden,
      // and the names are for whoever is reading the page, painted or not.
      setTimeout(() => { queued = false; labelize(root); }, 30);
    }).observe(root, {childList: true, subtree: true});
  }
}
