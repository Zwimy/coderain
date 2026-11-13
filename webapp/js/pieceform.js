/* The piece editor's field table and the merge an AI result goes through. No DOM here, so Node can test it.

   Why this exists. "Improve with AI" and "Seed from idea" used to write only some of a form's fields back (never a
   character's wants, motivation, traits or links, the activation controls, or the four trait fields of D-032), and
   collect() then re-merged the OLD attributes over whatever the AI had said, so the AI's answer was silently
   dropped for every field the form did not set and the author got no undo. One table now drives both directions:
   collect() reads every field in it, fill() writes every field in it, and the merge decides what an AI answer
   changes (everything it states; anything it leaves out stays as the author had it). */

/* kind: text | check | num. `only` limits a field to a kind of piece (characters, events, items, threads). */
export const FIELDS = [
  {attr: "weight", id: "p-weight", kind: "text"},
  {attr: "triggers", id: "p-triggers", kind: "text"},
  {attr: "pinned", id: "p-pinned", kind: "check"},
  {attr: "hidden", id: "p-hidden", kind: "check"},
  {attr: "group", id: "p-group", kind: "text"},
  {attr: "chance", id: "p-chance", kind: "text"},
  {attr: "delay", id: "p-delay", kind: "text"},
  {attr: "sticky", id: "p-sticky", kind: "text"},
  {attr: "cooldown", id: "p-cooldown", kind: "text"},
  {attr: "triggers_all", id: "p-triggers-all", kind: "text"},
  {attr: "triggers_not", id: "p-triggers-not", kind: "text"},
  {attr: "semantic", id: "p-semantic", kind: "check"},
  {attr: "recurse", id: "p-recurse", kind: "check"},
  {attr: "playable", id: "p-playable", kind: "check", only: "characters.md"},
  {attr: "stats", id: "p-stats", kind: "text", only: "characters.md"},
  {attr: "skills", id: "p-skills", kind: "text", only: "characters.md"},
  {attr: "wants", id: "p-wants", kind: "text", only: "characters.md"},
  {attr: "motivation", id: "p-motivation", kind: "text", only: "characters.md"},
  {attr: "strengths", id: "p-strengths", kind: "text", only: "characters.md"},
  {attr: "weaknesses", id: "p-weaknesses", kind: "text", only: "characters.md"},
  {attr: "personality", id: "p-personality", kind: "text", only: "characters.md"},
  {attr: "goals", id: "p-goals", kind: "text", only: "characters.md"},
  {attr: "once", id: "p-once", kind: "check", only: "events.md"},
  {attr: "rarity", id: "p-rarity", kind: "text", only: "items.md"},
  {attr: "objectives", id: "p-objectives", kind: "text", only: "threads.md"},
];
/* The two chip inputs (comma lists in the file). */
export const CHIPS = ["traits", "links"];

/* The character trait fields of D-032, shared with the Characters screen. */
export const TRAIT_LABEL = {strengths: "Strengths", weaknesses: "Weaknesses", personality: "Personality type", goals: "Goals"};
export const TRAIT_HINT = {
  strengths: "What they are good at. The writer lets it decide a scene when it matters.",
  weaknesses: "What costs them. The writer makes it cost something real.",
  personality: "A type or a few words, for example ISTJ, Enneagram 6, or a stoic who keeps promises.",
  goals: "What they want over the whole story. The planner moves chapters toward or against it.",
};
export const TRAIT_LIMIT = {strengths: 300, weaknesses: 300, personality: 80, goals: 300};

export const csv = s => String(s ?? "").split(",").map(x => x.trim()).filter(Boolean);

export const fieldsFor = rel => FIELDS.filter(f => !f.only || f.only === rel);

/* Attributes the form does not manage: carried through unchanged, so an entry's extra header lines survive an edit. */
export function unmanaged(attrs, rel) {
  const managed = new Set([...FIELDS.map(f => f.attr), ...CHIPS]);
  const out = {};
  for (const [k, v] of Object.entries(attrs || {})) if (!managed.has(k)) out[k] = v;
  return out;
}

const present = v => v !== undefined && v !== null;

/* What the form holds after an AI result: `current` is collect()'s entry, `entry` the model's. The model's title,
   importance, aliases and body replace the form's, as before. Every attribute it states replaces the form's, the
   managed ones and the unmanaged ones alike; an attribute it leaves out keeps the author's value. Lists
   (traits, links) arrive as comma text and are kept as text, the form splits them. A flag the model sets to
   "true" is on, anything else it states is off. */
export function mergeFill(current, entry) {
  const ea = (entry && entry.attrs) || {};
  const attrs = {...((current && current.attrs) || {})};
  for (const [k, v] of Object.entries(ea)) {
    if (present(v)) attrs[k] = typeof v === "string" ? v : Array.isArray(v) ? v.join(", ") : String(v);
  }
  return {
    title: present(entry && entry.title) ? entry.title : (current && current.title) || "",
    slug: (current && current.slug) || "",
    importance: Number(entry && entry.importance) || (current && current.importance) || 3,
    aliases: Array.isArray(entry && entry.aliases) ? entry.aliases.slice() : ((current && current.aliases) || []),
    body: present(entry && entry.body) ? entry.body : (current && current.body) || "",
    attrs,
  };
}
