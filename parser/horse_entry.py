"""
Parses one horse's block of raw text into the dict shape build_pdf.py
expects (see generator/build_pdf.py's module docstring for the full
target shape).

------------------------------------------------------------------------
STATUS: identity/connections/breeding fields are solid. The condensed
LIFE/2026/TRACK/SURF stat line computed here (_find_counts_row /
_find_dollars_and_speed_near) is a pdftotext-text-only best-effort guess -
app.py now overwrites it, per horse, with a more reliable
pdfplumber-coordinate-based reading from parser/stat_grid.py when one is
found (see that module's docstring for why the coordinate approach is more
reliable). The functions here remain as the fallback for whenever that
lookup comes back empty, per project brief section 4.4's instruction to
degrade gracefully rather than guess.
------------------------------------------------------------------------
"""

from __future__ import annotations

import re

from parser.past_performances import parse_pp_lines

# The gap between post number and name varies a lot (0 spaces for some
# short names, 1-3 for most, up to ~6 when a birth-info column happens to
# share the same text row further right - see "10     Vukota ... B. c. 2
# (Feb)" in the fixture) - \s{0,10} covers all of these without needing a
# separate case per width. Parens are allowed in the name so foreign
# entries' country suffix ("Ancient Egypt (Ire)") comes through intact.
HORSE_START_RE = re.compile(r"^\s{0,3}(\d{1,2})\s{0,10}([A-Z][A-Za-z\u2019\'\.\-\(\) ]+?)(?:\s{2,}|\s*$)")
_ML = r"\*?\d+\s*-\s*\d+|\*?\d+\s*/\s*\d+|Even"
ML_LINE_RE = re.compile(rf"^\s{{0,4}}({_ML})\s{{0,4}}(\$[\d,]+)?\s{{2,}}\S|^\s{{0,4}}({_ML})\s*$")
# Some horses (seen on first-time-starters with short names, e.g. "2Equilibrate")
# render with the post number, ML odds, and name all packed onto one line with
# no reliable whitespace gap between the post number and the ML odds' first
# digit (pdftotext -layout has no column boundary to preserve there once the
# two cells' text runs together) - e.g. "28 - 1 Equilibrate" is post #2 + ML
# "8-1" + name, not post #28. HORSE_START_RE can't tell these apart from a
# plain name line, so this is tried as a fallback in parse_horse.
COMBINED_START_RE = re.compile(
    rf"^\s{{0,4}}(\d{{1,2}}?)({_ML})\s+([A-Z][A-Za-z\u2019\'\.\- ]+?)\s*$"
)
# This fixture's export never actually prints the word "SCRATCHED" on a
# scratched horse's entry (checked directly - L'Eclair, race 10, is the
# fixture's one scratch and the literal text doesn't appear anywhere in
# the document). Instead, the horse's full identity/breeding/stats/PP
# history still prints normally, but "NO RIDER" replaces the jockey
# name+stats line where JOCKEY_RE would otherwise match (a real jockey
# obviously isn't assigned to a horse that isn't running). "SCRATCHED"/
# "Scratched" is kept as an alternate match in case a different DRF export
# does print it literally - see project brief 4.4 on defensive parsing.
SCRATCHED_RE = re.compile(r"\bSCRATCHED\b|\bScratched\b|\bNO RIDER\b", re.IGNORECASE)
OWN_LINE_RE = re.compile(r"\bOwn:")

JOCKEY_RE = re.compile(
    r"([A-Z][A-Za-z\s]+?)\s*\(\d+\s+\d+\s+\d+\s+\d+\s+\.\d+\)\s*2026:\s*\((\d+)\s+(\d+)\s+\.(\d+)\)"
)
TRAINER_RE = re.compile(
    r"Tr:\s*([A-Za-z][A-Za-z\s\.]+?)\((\d+)\s+\d+\s+\d+\s+\d+\s+\.\d+\)\s*2026:\s*\((\d+)\s+(\d+)\s+\.(\d+)\)"
)
SIRE_RE = re.compile(r"Sire:\s*([^\n]+?)\s*\$")
# Dam:/Br: lines can share a text row with an unrelated stat-grid cell (see
# module docstring) - cutting at the first 2+-space gap keeps just the
# intended column instead of swallowing whatever sits to its right.
DAM_RE = re.compile(r"Dam:\s*([^\n]+?)(?:\s{2,}|$)")
BREEDER_RE = re.compile(r"Br:\s*([^\n]+?)(?:\s{2,}|$)")

FIRST_TIME_MARKER_RE = re.compile(r"\bLife\s+0\s+M\s+0\s+0\b")

# Track abbreviation used in the condensed stat line, e.g. "Sar" -> "SAR"
TRACK_STAT_LABEL_RE = re.compile(r"\bSar\b")


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    return re.sub(r"\s+", " ", text).strip() or None


def _find_counts_row(block_text: str, label: str) -> tuple[str, str] | None:
    """
    Finds "<label> S W P S" (starts/wins/places/shows) as four consecutive
    integers right after the label. This part is reliable because
    pdftotext -layout keeps each stat-grid ROW's leftmost cells (the
    label + 4 small integers) together even when the row's rightmost
    cells (dollar figure + speed figure) get reordered relative to the
    row above/below it.

    Returns "S-W-P-S" as a display string, or None if not found.
    """
    m = re.search(rf"\b{label}\b\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", block_text)
    if not m:
        return None
    return "-".join(m.groups())


def _find_dollars_and_speed_near(block_text: str, label: str) -> str | None:
    """
    Best-effort $earnings + speed-figure lookup for a stat row. Searches a
    generous window after the label for the first "$N spd" pair. This can
    occasionally pick up a neighboring row's figures on badly fragmented
    blocks (see module docstring) - callers should treat a wrong-looking
    figure here as a known soft spot, not a parser bug to chase blindly.
    """
    idx = block_text.find(label)
    if idx == -1:
        return None
    window = block_text[idx: idx + 400]
    m = re.search(r"\$([\d,]+)\s+(\d{1,3}|-)", window)
    if not m:
        return None
    dollars, spd = m.groups()
    return f"${dollars}, spd {spd}"


def _parse_stat_line(block_text: str, surface_today: str) -> dict:
    out = {}
    life_counts = _find_counts_row(block_text, "Life")
    life_money = _find_dollars_and_speed_near(block_text, "Life")
    out["life"] = f"{life_counts}, {life_money}" if life_counts and life_money else life_counts

    year_counts = _find_counts_row(block_text, "2026")
    year_money = _find_dollars_and_speed_near(block_text, "2026")
    out["year"] = f"{year_counts}, {year_money}" if year_counts and year_money else year_counts

    track_counts = _find_counts_row(block_text, "Sar")
    track_money = _find_dollars_and_speed_near(block_text, "Sar")
    out["track_stat"] = f"{track_counts}, {track_money}" if track_counts and track_money else track_counts
    out["track_label"] = "SAR"

    surf_key = "D.Fst" if surface_today == "Dirt" else "Turf"
    surf_counts = _find_counts_row(block_text, re.escape(surf_key))
    surf_money = _find_dollars_and_speed_near(block_text, surf_key)
    out["surf_stat"] = f"{surf_counts}, {surf_money}" if surf_counts and surf_money else surf_counts
    out["surf_label"] = surface_today

    return out


_OWN_LOOKBACK = 5  # max lines to search backward from "Own:" for the horse-start line


def split_horse_blocks(race_body_lines: list[str]) -> list[list[str]]:
    """
    Splits a race's body lines (everything after the race header) into
    one list-of-lines per horse.

    Anchored on "Own:" lines rather than the horse-number/name line
    itself: every horse entry (identity, first-time starter, scratched,
    or foreign) has exactly one "Own:" line, one per horse with no
    exceptions found in the fixture - it's a far more reliable per-horse
    marker than the number+name line, whose exact shape varies (see
    COMBINED_START_RE's docstring for one such variant) in ways that are
    easy to miss with a single regex. For each "Own:" line, the true
    block-start line is found by searching a small window immediately
    above it for the nearest line that itself parses as a horse identity
    line (HORSE_START_RE or its combined-format sibling
    COMBINED_START_RE) rather than an ML-odds-only line or a stat-grid
    fragment - reusing the real parsing regexes here (instead of a
    separate loose heuristic) keeps this in sync with whatever shapes
    parse_horse actually knows how to read.
    """
    own_idxs = [i for i, l in enumerate(race_body_lines) if OWN_LINE_RE.search(l)]
    if not own_idxs:
        return []

    start_idxs = []
    prev_boundary = 0
    for own_idx in own_idxs:
        window_start = max(prev_boundary, own_idx - _OWN_LOOKBACK)
        candidates = [
            i for i in range(window_start, own_idx)
            if HORSE_START_RE.match(race_body_lines[i]) or COMBINED_START_RE.match(race_body_lines[i])
        ]
        start_idxs.append(candidates[0] if candidates else own_idx)
        prev_boundary = own_idx + 1

    blocks = []
    for n, start in enumerate(start_idxs):
        end = start_idxs[n + 1] if n + 1 < len(start_idxs) else len(race_body_lines)
        blocks.append(race_body_lines[start:end])
    return blocks


def parse_horse(block_lines: list[str], surface_today: str) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    text = "\n".join(block_lines)
    flat = " ".join(block_lines)

    start_m = HORSE_START_RE.match(block_lines[0]) if block_lines else None
    combined_m = None if start_m else (COMBINED_START_RE.match(block_lines[0]) if block_lines else None)

    if start_m:
        num = int(start_m.group(1))
        name = _clean(start_m.group(2))
    elif combined_m:
        num = int(combined_m.group(1))
        name = _clean(combined_m.group(3))
    else:
        num = None
        name = None

    ml = None
    if combined_m:
        ml = re.sub(r"\s+", "", combined_m.group(2))
    else:
        for line in block_lines[1:8]:
            m = ML_LINE_RE.match(line)
            if m:
                ml = re.sub(r"\s+", "", m.group(1) or m.group(3))
                break

    horse: dict = {"num": num, "name": name, "ml": ml}

    if SCRATCHED_RE.search(flat):
        horse["scratched"] = True
        return horse, warnings
    horse["scratched"] = False

    # Searched only in the text before "Tr:", not the whole block - a
    # foreign-connections jockey's stats sometimes render as an unparseable
    # "(>)" placeholder (see JOCKEY_RE's docstring below) instead of the
    # usual 5 numbers, and JOCKEY_RE's un-anchored .search() would then
    # happily match the TRAINER's own same-shaped "Name(n n n n .nn)
    # 2026:(n n .nn)" stat blob instead, misattributing the trainer's name
    # and record to the jockey field (seen: Damavand, race 8 - see the
    # 2026-08-17 bug report).
    jm = JOCKEY_RE.search(flat.split("Tr:", 1)[0])
    if jm:
        horse["jockey"] = _clean(jm.group(1))
        horse["jockey_stats"] = f"2026: {jm.group(2)} starts, {jm.group(3)} wins ({jm.group(4)}%)"
    else:
        horse["jockey"] = None
        horse["jockey_stats"] = None  # generator renders the "European rider" fallback
        warnings.append(f"#{num} {name}: could not parse jockey stats")

    tm = TRAINER_RE.search(flat)
    if tm:
        horse["trainer"] = _clean(tm.group(1))
        horse["trainer_stats"] = f"2026: {tm.group(3)} starts, {tm.group(4)} wins ({tm.group(5)}%)"
    else:
        horse["trainer"] = None
        horse["trainer_stats"] = None
        warnings.append(f"#{num} {name}: could not parse trainer stats")

    sm, dm, bm = SIRE_RE.search(text), DAM_RE.search(text), BREEDER_RE.search(text)
    horse["sire"] = _clean(sm.group(1)) if sm else None
    horse["dam"] = _clean(dm.group(1)) if dm else None
    horse["breeder"] = _clean(bm.group(1)) if bm else None
    if not (sm and dm and bm):
        warnings.append(f"#{num} {name}: incomplete breeding line")

    horse["first_time_starter"] = bool(FIRST_TIME_MARKER_RE.search(flat))

    horse.update(_parse_stat_line(flat, surface_today))

    pp_lines, pp_warnings = ([], []) if horse["first_time_starter"] else parse_pp_lines(block_lines)
    horse["pp_lines"] = pp_lines
    warnings.extend(f"#{num} {name}: {w}" for w in pp_warnings)

    return horse, warnings
