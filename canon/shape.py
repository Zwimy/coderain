"""Does the quoted evidence really describe THIS slot of a person?

The real-save gate (D-022) found that most identity values the Scribe proposed were
about something else: "anchor ink" for hair (a tattoo), "violet" for hair (the
quote was "her violet eyes"), "glass beads" for hair (an ornament), "dark, sharp,
utterly unimpressed" for eyes (an expression). Identity is first write wins, so the
first wrong value locked the slot and blocked the real one for the rest of the story.

The cheapest honest defence is a check in plain code on the Scribe's own quote. The
slot's noun has to be in it ("hair", "eyes"), and the value has to be the words
attached to that noun, not to some other one. "platinum hair, violet eyes" says
platinum about hair and violet about eyes, and a claim of violet hair is refused.

How a value is attached is a small chunker, not a parser. A run of descriptor words
(colours, lengths, textures, the small words between them) belongs to
  * the noun right AFTER it, if there is one ("violet eyes"), else
  * the noun right BEFORE it, but only after "is/was/..." or a comma or dash, and only
    if the run is then followed by punctuation, the end of the quote, or a word like
    "like" or "but" ("eyes, green like yours" yes; "hair, dark coat" no, dark is the
    coat's).
A run stops at any word that is not a descriptor, so "green beads click in her hair"
attaches nothing to hair, and neither does "hair is still damp" (damp is a condition
of the moment, not what the hair is).

This is deliberately strict. A rejected true claim costs a little recall, because the
real value is narrated again and again. An accepted wrong one costs the slot for the
rest of the story. The vocabulary is general English (colours, gems, hair styles,
builds), not this story's words. See D-022 for what was measured.

Marks (D-026) are the one list slot in identity, and they had no check at all: 54 of the
87 marks the second gate held were not marks (a way of gripping, a figure of speech, an
object, a bare colour). A mark never ages off the card, so each of those would have been
shown to the Writer for the rest of the story.
The test is the same kind as the others, a vocabulary: the value has to name a mark
(a scar, a tattoo, ink, a sigil...). A word that is only sometimes a mark ("mark",
"line", "scale") or an adjective ("scarred") counts only when a part of the body is
named in the value or the quote. Eyes now need a colour: "cold" and "wild" are how
eyes look in a moment, not their colour.

Pure code: no model, no file, no state. `problem()` returns None when the claim is
about its slot, else a short reason.
"""
from __future__ import annotations

import re

from canon import wardrobe

# --- vocabulary --------------------------------------------------------------------
_COLOURS = frozenset("""
black white grey gray silver red crimson scarlet ruby maroon burgundy wine orange
copper ginger auburn rust rusty amber gold golden yellow blond blonde flaxen platinum
straw honey brown chestnut chocolate hazel brunette tan tawny bronze caramel russet
mahogany ebony raven jet onyx obsidian charcoal ash ashen pewter steel slate ivory
cream pearl opal green emerald jade olive mint teal turquoise aqua blue azure cobalt
sapphire navy indigo cyan violet purple amethyst lavender lilac mauve plum magenta
pink rose fuchsia veridian viridian iron smoke smoky bone sand sandy dun fawn peach
salmon coral lemon silvery
""".split())

# Words that describe a colour or a head of hair without being a colour.
_MODS = frozenset("""
pale dark light deep bright soft thick thin long short cropped close shoulder length
waist hip tight loose severe messy tousled sleek cold warm cool electric neon almost
nearly faint faintly slightly streaked flecked tipped rich vivid old bleached dyed
natural sun faded curly wavy straight kinky coiled shaved buzzed grizzled thinning
receding tangled matted disheveled dishevelled glossy shiny lustrous unruly wild
iridescent vibrant muted dull dusky milky frosty icy ice
""".split())

# Said of eyes alone, these are a colour: "dark eyes", "pale eyes", "milky eyes".
_EYE_SHADES = frozenset("dark pale light deep milky icy ice".split())

# Small words that may sit inside a run or between a noun and its value.
_SKIP = frozenset("""
the a an of and or his her their its my your is are was were be been being very so
still now just quite rather colour color colours colors shade shades hue tint
""".split())
_CONNECT = frozenset("is are was were be been looked looks seemed seems".split())
_COMPARE = frozenset("like as than but though yet".split())

_STYLE = {                       # nouns that are a hair style by themselves
    "identity.hair": frozenset("""
        bob braid braids braided ponytail ponytails pigtails bun topknot undercut mohawk
        buzzcut crop dreads dreadlocks locs curls bangs fringe afro mullet pompadour quiff
        bald""".split())}
_GENERIC = {                     # the slot's own noun: it names the trait, tells nothing
    "identity.hair": frozenset("hair haired hairs locks tresses mane".split()),
    "identity.eyes": frozenset("eyes eyed iris irises".split())}

_BUILD = frozenset("""
tall short tiny small big large huge massive towering lean wiry lanky rangy slender
slim thin skinny gaunt petite stocky stout heavyset burly brawny broad shouldered
muscular muscle muscled athletic built fit toned compact curvy plump heavy squat
willowy sinewy ripped hulking
""".split())
# What a build word has to be attached to: the person's body, or the person ("she's
# tall"). "the windows are small and high" and "a rangy stride" say nothing of the build.
_BODY = frozenset("""frame build physique figure body form stature shoulders back chest
arms legs torso woman man girl boy fighter""".split())
_PERSON = frozenset("she he they you i".split())
_VERB_AFTER = frozenset("in on over against forward back toward towards into closer away up down out".split())
_AMBIGUOUS_BUILD = frozenset({"lean", "fit", "built"})      # also verbs: "she leans in"

# What a mark is. The first group names a mark by itself. The second is an adjective and
# the third a word with other meanings ("a mark", "the line", "bathroom scales", "a brand",
# "a mole"), so both need the body in the value or the quote. "ink" is in the first group:
# a person's ink is a tattoo. Singular forms only: a token is also tried without its
# final "s".
_MARK_NOUNS = frozenset("""scar tattoo birthmark piercing freckle ink sigil glyph rune
mandala""".split())
_MARK_ADJECTIVES = frozenset("scarred scarring tattooed inked pierced freckled branded".split())
_MARK_AMBIGUOUS = frozenset("mark brand mole line scale burn".split())
_SITES = frozenset("""
head face temple scalp skull brow eyebrow eye cheek cheekbone jaw chin nose lip ear neck
throat nape collarbone shoulder arm forearm elbow wrist hand palm knuckle finger thumb chest
breast sternum rib back spine torso stomach belly abdomen navel waist hip thigh leg knee shin
calf ankle foot toe skin flank feature bicep
""".split())

_NUM = (r"(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
        r"forty|fifty|sixty|seventy|eighty|ninety)(?:[- ](?:one|two|three|four|five|six|"
        r"seven|eight|nine))?")
_DECADE = r"(?:teens|twenties|thirties|forties|fifties|sixties|seventies|eighties|nineties)"
_AGE_FORM = re.compile(
    rf"^(?:(?:about|around|roughly|barely|nearly|almost|just|maybe|over|under) )?"
    rf"(?:{_NUM}(?:[- ]years?[- ]old)?|(?:(?:early|mid|late)[- ])?{_DECADE}|"
    rf"(?:{_NUM}|thirty)[- ]something|teenage|teenager|elderly|middle[- ]aged)$")
# A bare number is an age only when the quote says it is about age. "twenty-three and
# zero" is a fight record, and "three years" is how long something lasted.
_AGE_CUE = frozenset("""old older young younger age aged barely nearly almost maybe
turned about around roughly""".split())
# "about twelve feet" has the cue "about" and is not an age.
_UNITS = frozenset("""feet foot inches meters metres centimeters centimetres minutes hours
days weeks months seconds miles pounds kilos kilograms times""".split())


# What a held item can be: a concrete thing a person picks up. The real-save gate's held
# lists were full of thumbs, fingers, a current, a glow, a feeling and a referee, so
# the rule is a vocabulary of objects, not a list of what to refuse. A holding verb is no
# good as the test (real quotes say "palmed", "scoops up", "pull it from the rack"), and a
# thing in the scene that is not in a hand ("the jar on the counter") still gets through:
# the short life of a held item on the card (scene.FRESH_TURNS) is what limits that.
_OBJECTS = frozenset("""
cup mug glass bottle flask jug can bowl plate dish teapot kettle pot pan tray chopsticks fork
spoon knife dagger blade sword katana staff stick bat club gun pistol rifle revolver shotgun
taser baton whip chain rope cord wire hammer wrench screwdriver axe spear bow arrow shield
phone datapad tablet slate laptop radio remote camera drone scanner badge card cards key
keys keycard token coin coins chip drive disk disc tube vial syringe injector cigarette
cigar pipe lighter match matches book scroll letter note paper pen pencil brush towel cloth
rag bag duffel backpack satchel purse case box crate package packet parcel envelope folder
file map ball dice flower lantern torch candle lamp umbrella cane crutch rosary amulet charm
beads ring keyring wallet purse bundle bandage cloth blanket pillow mirror phone helmet
mask glasses goggles sack tool tools wrench pliers rod pole flag banner trophy medal
photo photograph picture sign jar jars food snack sandwich apple bread pastry fruit cookie
cake candy burger
""".split())
_NOT_PLURAL = frozenset({"balls"})
# A wound or an ailment. "swollen", "sore" and "throbbing" are left out of the first group
# because the gate found them in sentences about everything but injury, and scars and
# tattoos are marks (identity), not injuries.
_WOUND = frozenset("""
wound wounds wounded bruise bruises bruised bruising laceration lacerations gash gashes
gashed scraped grazed blister blisters sprain sprained strain strained fracture fractured
dislocated bleeding bled bandage bandaged stitches stitched splint concussion concussed
injured injury injuries sling cast crutch crutches limping headache migraine fever nausea
cramp cramps
""".split())
# Words that are an injury only OF a body part: "broken nose", "burn on her wrist". On
# their own they were a broken line of ink, a cracked screen, "goes limp", and a verb
# ("lines that cut across her chest").
_WEAK_WOUND = frozenset("cut cuts burn burns burned burnt broken cracked".split())
# "swollen" and "sore" are injuries on a limb, a joint or the face, and the same words
# were found in sentences about nothing of the kind on other parts of a body.
_QUALIFIER = frozenset("swollen swelling sore aching numb stiff purple".split())
_JOINTS = frozenset("""ankle ankles knee knees wrist wrists elbow elbows jaw lip lips eye eyes
cheek cheekbone nose rib ribs shin calf forearm shoulder neck back""".split())
_BODY_PARTS = _JOINTS | frozenset("""arm arms hand hands finger fingers thumb leg legs thigh thighs
hip hips chest stomach abdomen head face temple temples scalp skull brow eyebrow shoulders""".split())

# --- text --------------------------------------------------------------------------
_SOFT, _HARD = ",", "."
_ARE_CONTRACTED = frozenset("you they we".split())


def _tokens(text: str) -> list[str]:
    """Lower-cased words and two punctuation marks: "," for a comma, dash, colon or
    bracket (a run may cross it) and "." for a sentence end (a run may not)."""
    t = text.lower().replace("’", "'").replace("‘", "'")
    t = re.sub(r"(?<=[a-z0-9])-(?=[a-z0-9])", " ", t)
    out = []
    for m in re.finditer(r"[a-z0-9']+|[,;:()—–-]|[.!?…]", t):
        w = m.group()
        if w[0] in ",;:()—–-":
            out.append(_SOFT)
        elif w[0] in ".!?…":
            out.append(_HARD)
        else:
            if w[:-3] in _ARE_CONTRACTED and w.endswith("'re"):
                out += [w[:-3], "are"]           # "they're lean": the subject is "they"
            else:
                w = w[:-2] if w.endswith("'s") else w.strip("'")
                if w:
                    out.append(w)
    return out


def _descriptor(w: str) -> bool:
    return w in _COLOURS or w in _MODS


def _body_descriptor(w: str) -> bool:
    # A measurement sits between the verb and the word ("is 200cm tall").
    return w in _BUILD or w in _MODS or re.fullmatch(r"\d+(?:cm|m|ft)?", w) is not None


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def _same_word(a: str, b: str) -> bool:
    return a == b or _stem(a) == _stem(b)


# --- who does a descriptor belong to ------------------------------------------------
def _owners(toks: list[str], nouns: dict[str, str], desc) -> dict[int, int]:
    """token index -> index of the noun it describes, for descriptor tokens only.

    `nouns` maps a noun to a label (its slot); `desc` says which words are descriptors.
    Nouns of several slots can be given together so that a word between two of them
    goes to the right one. A noun is found by its word or its singular."""
    kind = {i: nouns.get(w) or nouns.get(_stem(w)) for i, w in enumerate(toks)}
    found = [i for i, k in kind.items() if k]
    own: dict[int, int] = {}
    for a in found:                                   # before the noun: "violet eyes"
        j = a - 1
        while j >= 0 and (toks[j] == _SOFT or toks[j] in _SKIP or desc(toks[j])):
            if desc(toks[j]):
                own.setdefault(j, a)
            j -= 1
        # A hair style takes one free word right before it ("tactical crop"): the
        # vocabulary cannot list every adjective a story will put there.
        free = toks[a - 1] if a else ""
        if (toks[a] in _STYLE.get(kind[a], ()) and free
                and free not in (_SOFT, _HARD) and free not in _SKIP and not desc(free)):
            own.setdefault(a - 1, a)
    for a in found:                                   # after the noun: "eyes, green like"
        j = a + 1
        while j < len(toks) and (toks[j] in _CONNECT or toks[j] == _SOFT
                                 or toks[j] in _SKIP):
            j += 1
        run = []
        while j < len(toks) and (desc(toks[j]) or toks[j] in _SKIP or toks[j] == _SOFT):
            run.append(j)
            j += 1
        closed = bool(run) and toks[run[-1]] == _SOFT
        if not (closed or j >= len(toks) or toks[j] == _HARD or toks[j] in _COMPARE):
            continue                                  # the run goes on to another noun
        for k in run:
            if desc(toks[k]):
                own.setdefault(k, a)
    return own


# --- the check ---------------------------------------------------------------------
def _on_noun(slot: str, value: str, evidence: str) -> str | None:
    generic, style = _GENERIC[slot], _STYLE.get(slot, frozenset())
    nouns = {w: s for s, ws in _GENERIC.items() for w in ws}
    nouns.update({w: s for s, ws in _STYLE.items() for w in ws})
    ev = _tokens(evidence)
    # "crop top" is a garment, not a haircut.
    mine = [i for i, w in enumerate(ev) if nouns.get(w) == slot
            and not (w == "crop" and ev[i + 1:i + 2] in (["top"], ["tops"]))]
    if not mine:
        return "slot_not_in_evidence"
    own = _owners(ev, nouns, _descriptor)
    owned = {ev[i] for i, a in own.items() if nouns.get(ev[a]) == slot}
    informative = False
    for w in _tokens(value):
        if w in (_SOFT, _HARD) or w in _SKIP or w in generic:
            continue
        if w in style:
            if not any(_same_word(w, ev[i]) for i in mine):
                return "value_not_on_slot"
            informative = True
        elif any(_same_word(w, o) for o in owned):
            # Eyes are a colour or a shade of one ("dark eyes", "pale eyes"). "cold" and
            # "wild" sit on the quote's eyes and are how they look in a moment, and as a
            # first write they would lock the slot for good.
            informative = (informative or slot != "identity.eyes"
                           or w in _COLOURS or w in _EYE_SHADES)
        else:
            return "value_not_on_slot"
    return None if informative else "value_not_on_slot"


def _is_body(w: str) -> bool:
    return w in _BODY or _stem(w) in _BODY


def _on_body(ev: list[str], i: int) -> bool:
    """Is the build word at `i` right beside the person's body or the person?

    Left: "her body lean", "she is tall". Right: "lean frame", "broad swimmer's
    shoulders" (one free word may sit between). Only skip words, commas and other
    descriptors may intervene, so "the windows are small" and "a rangy stride" fail."""
    j = i - 1
    while j >= 0 and (ev[j] in _SKIP or ev[j] in _CONNECT or ev[j] == _SOFT
                      or _body_descriptor(ev[j])):
        j -= 1
    if j >= 0 and (_is_body(ev[j]) or ev[j] in _PERSON):
        return True
    j, free = i + 1, False
    while j < len(ev):
        w = ev[j]
        if w in _SKIP or w == _SOFT or _body_descriptor(w):
            j += 1
        elif not free and w != _HARD and not _is_body(w) and w not in _PERSON:
            free, j = True, j + 1
        else:
            break
    return j < len(ev) and _is_body(ev[j])


def _build(value: str, evidence: str) -> str | None:
    """A build word of the value that the quote attaches to the body or the person."""
    ev = _tokens(evidence)
    wanted = [w for w in _tokens(value) if w in _BUILD]
    for i, e in enumerate(ev):
        if e not in _BUILD or not any(_same_word(w, e) for w in wanted):
            continue
        nxt = ev[i + 1] if i + 1 < len(ev) else ""
        if e in _AMBIGUOUS_BUILD and nxt in _VERB_AFTER:
            continue                                  # "she leans in", "fit into"
        if _on_body(ev, i):
            return None
    return "value_not_on_slot"


def _age(value: str, evidence: str) -> str | None:
    v = " ".join(t for t in _tokens(value) if t not in (_SOFT, _HARD))
    if not _AGE_FORM.match(v):
        return "value_not_on_slot"
    bare = re.fullmatch(rf"(?:(?:about|around|roughly|barely|nearly|almost|just|maybe|"
                        rf"over|under) )?{_NUM}", v)
    if not bare:
        return None
    ev = _tokens(evidence)
    last = _tokens(value)[-1:]
    follows = {ev[i + 1] for i, w in enumerate(ev[:-1]) if last and w == last[0]}
    if not _AGE_CUE & set(ev) or follows & _UNITS:
        return "value_not_on_slot"
    return None


def _marks(value: str, evidence: str) -> str | None:
    """A value that names a mark, and for the words that are only sometimes one, a body
    to put it on (in the value or in the quote)."""
    def forms(text: str) -> set[str]:
        toks = _tokens(text)
        return set(toks) | {_stem(w) for w in toks}

    words = forms(value)
    if words & _MARK_NOUNS:
        return None
    if words & (_MARK_ADJECTIVES | _MARK_AMBIGUOUS) and (words | forms(evidence)) & _SITES:
        return None
    return "not_a_mark"


def _outfit(value: str) -> str | None:
    return None if wardrobe.category(value) else "not_a_garment"


def _held(value: str) -> str | None:
    word = wardrobe.last_of(value, _OBJECTS)
    # The plural "balls" is refused outright: in the gate's lists it never named a toy.
    return None if word and word not in _NOT_PLURAL else "not_an_object"


def _injury(value: str) -> str | None:
    toks = set(_tokens(value))
    if (_WOUND & toks or (_WEAK_WOUND & toks and _BODY_PARTS & toks)
            or (_QUALIFIER & toks and _JOINTS & toks)):
        return None
    return "not_a_wound"


def problem(slot: str, value: str, evidence: str) -> str | None:
    """None when `evidence` really says `value` about `slot`; else the reason.

    Slots this module has no rule for (location, mood) are not its business and pass. A
    state list is checked on what is ADDED to it."""
    if slot in _GENERIC:
        return _on_noun(slot, value, evidence)
    if slot == "identity.marks":
        return _marks(value, evidence)
    if slot == "state.outfit":
        return _outfit(value)
    if slot == "state.held":
        return _held(value)
    if slot == "state.injury":
        return _injury(value)
    if slot == "identity.build":
        return _build(value, evidence)
    if slot == "identity.age":
        return _age(value, evidence)
    return None
