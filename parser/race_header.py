"""
Parses the race-level header block (race number, post time, distance,
surface, race type/conditions string, purse) that appears once per race,
before that race's horses.

Input is the raw text slice for one race (see extract.split_pages /
app.py's page-walking loop for how that slice gets isolated - in practice
"one race" spans from the line matching RACE_NUM_TRACK_RE up to (but not
including) the next race's matching line, or end of document).
"""

from __future__ import annotations

import re

from parser.normalize import decode_distance

# The race-number+track line is sometimes alone on its line (races 1-9 in
# the fixture) and sometimes has the distance/purse text appended to the
# same line with a wide whitespace gap (races 10-12 in the fixture, e.g.
# "10 Saratoga            5ôf Furlongs (Turf)..."). The trailing lookahead
# requires that gap-separated tail (when present) to actually start with a
# distance-shaped token ("5ôf Furlongs", "1 MILE", ...) rather than just
# making any trailing text optional - otherwise this also matches horse
# rows like "10     Vukota    B. c. 2 (Feb)" (post position + horse name
# followed, much further right, by an unrelated foaling-info column).
RACE_NUM_TRACK_RE = re.compile(
    r"^\s*(\d{1,2})\s+([A-Z][A-Za-z .]+?)"
    r"(?:\s{2,}(?=[\d¡-￿]+\s*(?:Furlongs?|Miles?)).*)?\s*$",
    re.IGNORECASE,
)
# "Furlongs"/"Miles" render in title case for sprints (races 1-3, 6-8, 10
# in the fixture) but ALL CAPS for route races - "1 MILE", "1 MILES" (races
# 4, 5, 9, 11, 12) - `(?i:...)` scopes case-insensitivity to just that
# alternation rather than the whole pattern, so `race_type`'s own
# `[A-Z]`-starts-with-a-capital requirement isn't loosened too.
# The turf marker is "(Turf)" on its own but "(Inner Turf)" or similar on
# card-specific turf courses - matched by "ends with Turf)" rather than an
# exact literal.
# Originally required the race-type text to end in a period immediately
# before "Purse $" - true for stakes headers (race 9 in the 2026-08-16
# fixture: "...(Turf). (:59\u2074) Mahony-G3 THE MAHONY. Grade III. Purse
# $225,000...", where a period genuinely does sit right before "Purse $").
# False for ordinary-race headers (races 1, 10, etc. in that same fixture:
# "...MILES (1:46\u00a8) \u00d0Alw 105000N1X Purse $105,000 For Three Year
# Olds And Upward...Two Races. Three Year Olds, 121 lbs...."), where "Purse
# $" comes immediately after the bare race-class code and the conditions
# paragraph's own first period doesn't appear until much later - see the
# 2026-08-17 bug report. `(?:\([^)]*\)\s*)*` skips over the par-time /
# grade parenthetical(s) that sit between the distance and the race-class
# code (e.g. "(1:46\u00a8)") without requiring a trailing period on either
# side of them; race_type is then just "whatever comes next, up to Purse
# $" - lazy and unanchored on punctuation, so it works for both formats.
DISTANCE_LINE_RE = re.compile(
    r"(?P<distance>[\d\u00a1-\uffff/ ]+(?i:Furlongs?|Miles?))\s*"
    r"(?P<turf>\([A-Za-z ]*Turf\))?\.?\s*"
    r"(?:\([^)]*\)\s*)*"
    r"(?P<race_type>[^\n]*?)\s*"
    r"Purse\s*\$(?P<purse>[\d,]+)",
    re.IGNORECASE,
)
POST_TIME_RE = re.compile(r"Post time:\s*([\d:]+\s*[AP]?M?\s*ET)")

# A race number that sits completely alone on its own line, with the track
# name/distance starting on a LATER line rather than the same one - see
# HEADER_ANCHOR_RE's docstring below for why this format needs its own
# detection path.
STANDALONE_RACE_NUM_RE = re.compile(r"^\s*(\d{1,2})\s*$")
# Recovers the track name independently of the race-number line, for the
# same split-line format - matches the word right before the distance
# ("Saratoga" in "Saratoga 6\u00f4 Furlongs...").
TRACK_NAME_RE = re.compile(
    r"([A-Z][A-Za-z]+)\s+[\d\u00a1-\uffff/ .]+(?:Furlongs?|MILES?|Miles?)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Race-boundary detection (used by app.py to slice the whole document into
# per-race chunks BEFORE calling parse_race_header on each one)
# ---------------------------------------------------------------------------
# Previously, app.py found race starts by scanning for RACE_NUM_TRACK_RE
# matches directly - i.e. "race number + track name on one line" - the same
# assumption this module's own num/track lookup below made. That format
# does NOT hold on every DRF export: the 2026-08-16 Saratoga card (see the
# 2026-08-17 bug report this whole block traces back to) always prints the
# race number alone on its own line, with "Saratoga <dist> ...
# Furlongs/Miles ... Purse $..." starting a few lines later - never on the
# same line. Because RACE_NUM_TRACK_RE never matched a genuine race header
# on that fixture, app.py's old boundary-detection loop fell through to
# matching the only other thing with a similar "digit + capitalized word"
# shape in the document: a horse's own post-number + name line (e.g.
# " 7  Stradale", a horse entered in race 9) - producing a false-positive
# race start that silently dropped every race before it and mislabeled the
# one race it did produce.
#
# HEADER_ANCHOR_RE fixes this by anchoring on the race header's only truly
# unambiguous content instead: the "Saratoga ... Furlongs/Miles ... Purse
# $NNN" text itself, which never appears inside a horse's own block.
# `.{0,400}?` bridges the wrapped conditions-paragraph lines between the
# distance and the purse figure - 400 chars comfortably covers the longest
# conditions paragraph seen in this fixture while stopping well short of
# the (much larger) gap to a neighboring race's own header.
HEADER_ANCHOR_RE = re.compile(
    r"Saratoga\s+[\d\u00a1-\uffff/ .]+(?:Furlongs?|MILES?|Miles?)\b.{0,400}?Purse\s*\$[\d,]+",
    re.IGNORECASE | re.DOTALL,
)


def find_race_block_starts(full_text: str) -> list[int]:
    """
    Returns the line indices where each race's block should start, scanning
    the WHOLE document text at once (never per-page - see extract.py's
    docstring on why a race's header can print on the page before its
    horses do). For each HEADER_ANCHOR_RE match, looks up to 5 lines
    backward for the race-number line - either combined with the track
    name on one line (RACE_NUM_TRACK_RE, the format this app was originally
    built against) or standing alone on its own line
    (STANDALONE_RACE_NUM_RE, this fixture's format) - so a race block
    starts at the NUMBER, not at the anchor text itself. Falls back to the
    anchor's own line if neither is found nearby, so a race block still
    gets created (parse_race_header will warn about the missing number
    rather than the race silently vanishing).
    """
    import bisect

    lines = full_text.split("\n")
    offsets = []
    pos = 0
    for l in lines:
        offsets.append(pos)
        pos += len(l) + 1

    starts = []
    for m in HEADER_ANCHOR_RE.finditer(full_text):
        anchor_idx = bisect.bisect_right(offsets, m.start()) - 1
        found = None
        for back in range(0, 6):
            i = anchor_idx - back
            if i < 0:
                break
            if STANDALONE_RACE_NUM_RE.match(lines[i]) or RACE_NUM_TRACK_RE.match(lines[i]):
                found = i
                break
        starts.append(found if found is not None else anchor_idx)

    seen = set()
    ordered = []
    for s in sorted(starts):
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered

# Conditions text can run across a couple of wrapped lines before "Post
# time:" - captured separately so it can be condensed into the compact
# "conditions string" the brief describes (e.g. "Claiming $30,000-$35,000
# (N3L) \u00b7 3YO & Up").
CLAIMING_PRICE_RE = re.compile(r"Claiming Price\s*\$([\d,]+)")
AGE_RESTRICTION_RE = re.compile(r"(Two|Three|Four)\s+Year\s+Olds?(\s+And\s+Upward)?")
NEVER_WON_RE = re.compile(r"Which Have Never Won ([\w \$,]+?)\.")


def _condense_conditions(race_type_label: str, body_text: str) -> str:
    bits = [race_type_label.strip().title() if race_type_label else None]

    claim = CLAIMING_PRICE_RE.search(body_text)
    if claim and "claiming" in (race_type_label or "").lower():
        # crude range detection: two claiming-price mentions -> a range
        prices = CLAIMING_PRICE_RE.findall(body_text)
        if len(prices) >= 2 and prices[0] != prices[-1]:
            bits[0] = f"Claiming ${prices[0]}-${prices[-1]}"
        else:
            bits[0] = f"Claiming ${claim.group(1)}"

    never_won = NEVER_WON_RE.search(body_text)
    if never_won:
        bits.append(f"(N{never_won.group(1).split()[0]})" if never_won.group(1)[0].isdigit() else None)

    age = AGE_RESTRICTION_RE.search(body_text)
    if age:
        yo = {"Two": "2", "Three": "3", "Four": "4"}[age.group(1)]
        bits.append(f"{yo}YO & Up" if age.group(2) else f"{yo}YO")

    return " \u00b7 ".join(b for b in bits if b)


def parse_race_header(race_block_text: str) -> tuple[dict, list[str]]:
    """
    Returns (race_dict_partial, warnings). `race_dict_partial` has the
    header fields filled in; `horses` is left as an empty list for the
    caller (app.py / horse_entry.py) to populate.
    """
    warnings: list[str] = []
    lines = race_block_text.splitlines()

    race_num = None
    track_name = None
    for line in lines[:6]:
        m = RACE_NUM_TRACK_RE.match(line)
        if m:
            race_num = int(m.group(1))
            track_name = m.group(2).strip()
            break

    if race_num is None:
        # Split-line format (race number alone, track name a few lines
        # later with the distance) - see HEADER_ANCHOR_RE's docstring
        # above. Recovered independently since neither piece reliably sits
        # next to the other in this layout.
        for line in lines[:6]:
            m = STANDALONE_RACE_NUM_RE.match(line)
            if m:
                race_num = int(m.group(1))
                break
        tm = TRACK_NAME_RE.search(race_block_text)
        if tm:
            track_name = tm.group(1).strip()

    if race_num is None:
        warnings.append("Could not find race number/track line for this race block.")

    dist_m = DISTANCE_LINE_RE.search(race_block_text)
    distance = None
    surface = "Dirt"
    race_type_label = None
    purse = None
    if dist_m:
        distance_raw = re.sub(r"\s+", " ", dist_m.group("distance")).strip()
        distance = decode_distance(distance_raw)
        surface = "Turf" if dist_m.group("turf") else "Dirt"
        race_type_label = dist_m.group("race_type").strip()
        purse = f"${dist_m.group('purse')}"
    else:
        warnings.append("Could not parse distance/race-type/purse line for this race block.")

    post_m = POST_TIME_RE.search(race_block_text)
    post_time = post_m.group(1).strip() if post_m else None
    if not post_time:
        warnings.append("Could not find post time for this race block.")

    conditions = _condense_conditions(race_type_label, race_block_text) if race_type_label else None

    race = {
        "num": race_num,
        "track_name": track_name,
        "post_time": post_time,
        "distance": distance,
        "surface": surface,
        "race_type": conditions,
        "purse": purse,
        "horses": [],
    }
    return race, warnings
