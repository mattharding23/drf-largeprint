"""
Shared normalization helpers used across the parser modules.

------------------------------------------------------------------------
THE MONTH-GLYPH PROBLEM (read this before touching date parsing)
------------------------------------------------------------------------
This DRF PDF export embeds a custom font for the little calendar-style
date codes in each past-performance line (e.g. what prints as "24Jul26"
on the page extracts, via pdftotext, as "24\u00db26"). The month is not
text - it is a single glyph from a substitution font. Every "DDglyphYY="
uses a consistent glyph per month (12 distinct glyphs = 12 months), but
the glyph is NOT letter-abbreviation-shaped ("J" doesn't mean January) and
pdftotext just gives you whatever Latin-1-ish character sits at that glyph's
code point, so the mapping is opaque and MUST be derived per-document (or at
least verified against a new sample if DRF changes their PDF export).

How this mapping was derived for the Aug 15, 2026 Saratoga fixture:
1. Anchor a handful of glyphs using plain-digit dates that appear elsewhere
   in the same document for the same event, e.g. claiming lines
   ("Claimed from X for $20,000, Trainer 2026(as of 7/24)") that follow
   directly after a PP line dated "24\u00db26=" - the plain "7/24" tells you
   day 24, month 7, which pins glyph \u00db (in that position) to July.
2. For the glyphs that don't have a nearby plain-digit anchor, use the fact
   that each horse's PP lines are printed most-recent-race-first. That means
   within a single horse's block, the (month, day) sequence for any given
   year must be non-increasing. Brute-force the remaining glyph-to-month
   assignments and keep only the assignment(s) that produce zero ordering
   violations across every horse in the document.
3. Where step 2 leaves more than one zero-violation assignment (this WILL
   happen for months close to the PDF's own "today" date, since there's
   little/no year-26 data to order against for a month that hasn't
   happened yet), fall back to relative frequency inside the WORKS: lines
   (workout dates cluster tightly around the card's date, so the glyph
   that appears third-most inside WORKS: lines, right behind the two most
   recent full months, is a good proxy for "the current partial month").

Steps 1 and 2 produced a confident, unique answer for 9 of the 12 glyphs.
Step 3 gives medium confidence for a 10th. The remaining two (Sep/Oct) are
a genuine coin flip from a single day's fixture - there just isn't enough
year-26 September/October data yet for August 2026 to disambiguate them.
Confidence is annotated per entry below.

If/when this app is pointed at a different DRF export (different date,
different track), RE-DERIVE this map rather than assuming it's stable -
re-run the calibration approach above against the new fixture. It is cheap
(a few dozen lines of regex + a permutation search) and safer than trusting
a hardcoded table indefinitely.
"""

import re

# glyph -> month number (1-12). Confidence noted per entry.
MONTH_GLYPH_MAP = {
    "\u00db": 7,   # Û = Jul   (confidence: high - direct plain-digit anchor)
    "\u00de": 6,   # Þ = Jun   (confidence: high - direct plain-digit anchor)
    "\u00dc": 5,   # Ü = May   (confidence: high - direct plain-digit anchor)
    "\u00df": 4,   # ß = Apr   (confidence: high - direct plain-digit anchor)
    "\u00e4": 11,  # ä = Nov   (confidence: high - direct plain-digit anchor)
    "\u00e3": 12,  # ã = Dec   (confidence: high - direct plain-digit anchor)
    "\u00e2": 1,   # â = Jan   (confidence: high - unique zero-violation ordering solve)
    "\u00e1": 2,   # á = Feb   (confidence: high - unique zero-violation ordering solve)
    "\u00e0": 3,   # à = Mar   (confidence: high - unique zero-violation ordering solve)
    "\u00dd": 8,   # Ý = Aug   (confidence: medium - inferred from WORKS: frequency;
                   #            3rd-most-common workout glyph behind Jul/Jun, consistent
                   #            with "today" being ~mid-August with a partial month of data)
    "\u00e5": 10,  # å = Oct   (confidence: LOW - unresolved by ordering constraint,
                   #            no plain-digit anchor found; verify against another fixture)
    "\u00e6": 9,   # æ = Sep   (confidence: LOW - same caveat as å; å/æ could be swapped)
}

DATE_CODE_RE_MONTH_CHARS = "".join(MONTH_GLYPH_MAP.keys())


def decode_pp_date(day: str, month_glyph: str, year_2digit: str) -> str | None:
    """
    Turns ('24', 'Û', '26') into '2026-07-24'. Returns None (rather than
    raising) for unrecognized glyphs so a single bad date doesn't take down
    the whole horse - see project brief section 4.4 on defensive parsing.
    """
    month = MONTH_GLYPH_MAP.get(month_glyph)
    if month is None:
        return None
    try:
        day_i = int(day)
        year_i = 2000 + int(year_2digit)
    except ValueError:
        return None
    return f"{year_i:04d}-{month:02d}-{day_i:02d}"


def display_date(iso_date: str | None) -> str:
    """'2026-07-24' -> '24Jul26' for the compact DATE column."""
    if not iso_date:
        return "—"
    months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    y, m, d = iso_date.split("-")
    return f"{int(d)}{months[int(m)]}{y[2:]}"


# ---------------------------------------------------------------------------
# THE DISTANCE-FRACTION-GLYPH PROBLEM (README "What needs work" #3)
# ---------------------------------------------------------------------------
# Same underlying issue as MONTH_GLYPH_MAP above: this PDF's embedded font
# renders fraction characters (1/2, 1/16, ...) as single glyphs rather than
# "1/2" text, and the mapping is opaque per document. Unlike the month
# glyphs, this fixture's race headers only exercise two of the mile
# fractions actually present in the document's PP lines (1/16 and 1/2 -
# calibrated directly against this project's own approved reference output,
# tests/fixtures/saratoga_2026-08-15_expected_output.pdf, which already
# spells these out in full: "1 1/16 Miles", "1 1/2 Miles"). Four more mile
# glyphs appear in PP lines (´ x6, ± x1, ° x28, ² x9)
# but never in a race header in this fixture, and the PP table's own DIST
# column collapses every mile distance to a bare "Nmi" regardless of
# fraction (see decode_pp_distance) - so there's no ground truth anywhere
# in this fixture to anchor them against. Left uncalibrated rather than
# guessed, same rationale as MONTH_GLYPH_MAP's Sep/Oct entries: re-run this
# same direct-comparison approach against a second fixture whose race
# headers happen to use one of these fractions.
FURLONG_FRACTION_GLYPH_MAP = {
    "ô": "1/2",  # ô - confidence: high - direct match against reference output ("6ôf" -> "6.5f")
}

MILE_FRACTION_GLYPH_MAP = {
    "Â": "1/16",  # Â - confidence: high - direct match (races 5 & 12 header: "1 1/16 Miles")
    "¶": "1/2",   # ¶ - confidence: high - direct match (race 9 header: "1 1/2 Miles")
    # ´, ±, °, ² - seen in PP lines, no ground truth in
    # this fixture to calibrate against (see module note above).
}

_FURLONG_DIST_RE = re.compile(r"^(\d+)\s*([^\d\sfF]?)\s*(?:f|F(?:url\w*)?)\b")
_MILE_DIST_RE = re.compile(r"^(\d+)\s*([^\d\sMm]?)\s*(?:MILES?|Miles?|mi)\b")


def decode_distance(raw: str | None) -> str | None:
    """
    Full fraction decode for the race-header distance line, e.g. "5ô
    Furlongs" -> "5 1/2 Furlongs", "1Â MILES" -> "1 1/16 Miles", "1 MILE"
    -> "1 Mile" (spelled out in full, per this app's own Format B2 header
    - contrast decode_pp_distance's abbreviated "5.5f" for the narrow PP
    table column). Falls back to returning `raw` unchanged if there's a
    fraction glyph present but it isn't one of the calibrated ones above -
    a wrong distance is worse than an undecoded one (project brief 4.4).
    """
    if not raw:
        return raw

    m = _FURLONG_DIST_RE.match(raw)
    if m:
        whole, glyph = m.group(1), m.group(2)
        if not glyph:
            return f"{whole} Furlongs"
        frac = FURLONG_FRACTION_GLYPH_MAP.get(glyph)
        return f"{whole} {frac} Furlongs" if frac else raw

    m = _MILE_DIST_RE.match(raw)
    if m:
        whole, glyph = m.group(1), m.group(2)
        if not glyph:
            return f"{whole} Mile" if whole == "1" else f"{whole} Miles"
        frac = MILE_FRACTION_GLYPH_MAP.get(glyph)
        return f"{whole} {frac} Miles" if frac else raw

    return raw


def decode_pp_distance(raw: str | None) -> str | None:
    """
    Distance decode for the past-performances table's narrow DIST column.
    Furlongs get the same full fraction decode as decode_distance (e.g.
    "6ôf" -> "6.5f"). Miles collapse to a bare "Nmi" with any fraction
    dropped - verified against this project's own approved reference
    output, where even a 1 1/2-mile race's PP row reads "1mi", not
    "1.5mi": the column's too narrow for the fraction and the race
    type/conditions column usually names the added distance anyway.

    Unlike the race-header distance line, a PP line's raw dist token never
    spells out a "mi"/"MILES" unit word (past_performances.TRACK_COND_RE
    only captures a bare "1" or "1Â" for mile trips) - so any token that
    isn't furlong-shaped is treated as mile-based by elimination, not by
    matching a unit word.
    """
    if not raw:
        return raw

    m = _FURLONG_DIST_RE.match(raw)
    if m:
        whole, glyph = m.group(1), m.group(2)
        if not glyph:
            return f"{whole}f"
        frac = FURLONG_FRACTION_GLYPH_MAP.get(glyph)
        return f"{whole}.5f" if frac == "1/2" else raw

    m = re.match(r"^(\d+)", raw)
    if m:
        return f"{m.group(1)}mi"

    return raw


# ---------------------------------------------------------------------------
# Track condition codes -> display labels (project brief section 4.3)
# ---------------------------------------------------------------------------
CONDITION_MAP = {
    # Dirt
    "fst": "Fast", "fast": "Fast",
    "sly": "Sloppy", "slyø": "Sloppy",
    "my": "Muddy", "myø": "Muddy",
    "gd": "Good",
    # Turf
    "fm": "Firm",
    "yl": "Yielding",
    "sf": "Soft",
    "hy": "Heavy",
    "gs": "Good-Soft",  # composite code seen on European lines
}


def normalize_condition(code: str | None) -> str | None:
    if not code:
        return None
    key = code.strip().lower().rstrip("\u00f8")  # trailing 'ø' glyph is decorative on some dirt codes
    return CONDITION_MAP.get(key) or CONDITION_MAP.get(code.strip().lower())


# ---------------------------------------------------------------------------
# Surface inference (track-condition code + course indicator -> Dirt/Turf)
# ---------------------------------------------------------------------------
def infer_surface(cond_code: str | None, course_marker: str | None) -> str | None:
    """
    DRF marks turf-course races with a small course-indicator glyph after the
    distance (rendered as things like 'ê' in this export) and/or a condition
    code drawn from the turf set (fm/yl/sf/hy) rather than the dirt set
    (fst/sly/my/gd). `course_marker` is whatever non-alphanumeric marker (if
    any) pdftotext left behind next to the distance field.
    """
    if cond_code:
        key = cond_code.strip().lower().rstrip("\u00f8")
        if key in ("fst", "sly", "my", "gd"):
            return "Dirt"
        if key in ("fm", "yl", "sf", "hy", "gs"):
            return "Turf"
    if course_marker:
        return "Turf"
    return None


# ---------------------------------------------------------------------------
# Trip-comment -> short RAN phrase (project brief section 4.3)
# ---------------------------------------------------------------------------
# DRF's trip comments are themselves already a condensed shorthand (e.g.
# "Bmp brk,svd grnd,empty", "3-5path turn,no rally") built from a WHERE
# component (position/trip trouble) and a HOW-IT-ENDED component (outcome),
# in that order. Rather than one flat table of whole-phrase patterns keyed
# to a handful of exact keywords (which this fixture's actual comment
# vocabulary - see the two tables below, tuned against it directly -
# turned out to be far richer than), each half is matched independently
# and the two are composed - "Bumped start" + "no rally" -> "Bumped start,
# no rally". This covers far more of the source vocabulary than a single
# whole-phrase table could without an entry per exact wording.
_POSITION_PATTERNS = [
    (("bmp st", "bumped st", "stumbled", "awkwrd", "awkward st",
      "fractious gate", "hit gate", "bobbld brk", "veer out brk"), "Bumped start"),
    (("wire to wire", "wire-to-wire"), "Wire to wire"),
    (("vied", "dueled", " duel", ",duel"), "Dueled"),
    (("press", "prompt"), "Pressed pace"),
    (("stalk", "track", "chased", "chsd"), "Stalked"),
    (("in hand",), "In hand"),
    (("rail", " ins,", " ins ", "ins turn", "ins-", "svd grnd", "saved ground"), "Inside trip"),
    (("wide", re.compile(r"\b\d[-\s]?w\b")), "Wide trip"),
    (("led", "lead"), "Led"),
]

_OUTCOME_PATTERNS = [
    (("drew off", "drew clear", "drew clr", "handily", "ridden out", "clear"), "drew clear"),
    (("caught", "outfinish", "outfnshd"), "caught late"),
    (("no rally", "no factor", "no threat", "no response", "no match",
      "no kick", "no bid", "no impact", "miss place"), "no rally"),
    (("kept on", "ran on", "up for place"), "kept on"),
    (("rally", "rallied", "late gain", "improved", "rail rally"), "rallied late"),
    (("empty",), "weakened late"),
    (("tired", "wknd", "wkn", "weaken", "faded"), "weakened"),
    (("game", "gamely", "fought"), "gamely"),
    (("mild kick",), "mild kick"),
    (("no kick",), "no kick"),
]


def _match_pattern(text: str, patterns: list[tuple[tuple, str]]) -> str | None:
    for keys, phrase in patterns:
        for k in keys:
            if (k.search(text) if hasattr(k, "search") else k in text):
                return phrase
    return None


def summarize_trip(raw_comment: str | None, finish_position: int | None = None) -> str:
    """
    Best-effort short RAN summary from the verbose DRF trip comment,
    composed from a trip/position half (_POSITION_PATTERNS) and an outcome
    half (_OUTCOME_PATTERNS) - see the module note above. Falls back to a
    generic phrase keyed off finish position when neither half matches
    anything, rather than guessing at unfamiliar phrasing - a
    wrong-but-confident-sounding summary is worse than a bland one here
    (project brief 4.4).
    """
    if not raw_comment:
        if finish_position == 1:
            return "Led, drew clear"
        return "Mid-pack"

    text = raw_comment.lower()
    position = _match_pattern(text, _POSITION_PATTERNS)
    outcome = _match_pattern(text, _OUTCOME_PATTERNS)

    if position and outcome:
        return f"{position}, {outcome}"
    if position:
        return position
    if outcome:
        return outcome[0].upper() + outcome[1:]

    return "Mid-pack"
