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
DISTANCE_LINE_RE = re.compile(
    r"(?P<distance>[\d\u00a1-\uffff/ ]+(?i:Furlongs?|Miles?))\s*(?P<turf>\([A-Za-z ]*Turf\))?"
    r".*?(?P<race_type>[A-Z][A-Za-z /]+)\.\s*Purse\s*\$(?P<purse>[\d,]+)"
)
POST_TIME_RE = re.compile(r"Post time:\s*([\d:]+\s*[AP]?M?\s*ET)")

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
    for line in lines[:5]:
        m = RACE_NUM_TRACK_RE.match(line)
        if m:
            race_num = int(m.group(1))
            track_name = m.group(2).strip()
            break
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
        "post_time": post_time,
        "distance": distance,
        "surface": surface,
        "race_type": conditions,
        "purse": purse,
        "horses": [],
    }
    return race, warnings
