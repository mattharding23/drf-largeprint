"""
Parses individual past-performance (PP) lines within a horse's raw text
block into the structured dicts consumed by generator/build_pdf.py.

KNOWN LIMITATIONS (all deliberately fail soft - see project brief 4.4):
- `distance` is decoded via normalize.decode_pp_distance, which handles
  furlong fractions fully (e.g. "6\u00f4f" -> "6.5f") but only two of the six
  mile-fraction glyphs seen in this fixture's PP lines (1/16, 1/2) have a
  ground-truth anchor to calibrate against - see
  normalize.MILE_FRACTION_GLYPH_MAP's docstring. The other four pass
  through as their raw glyph rather than a guessed fraction.
- `ran` (the short trip summary) is derived from the tail of the line via
  a two-pass heuristic (see _extract_trailing_comment) and can occasionally
  swallow a stray fraction like "5/16" from the tail of the real comment,
  or drop a comment entirely on unusually formatted foreign lines. Any
  line where a comment can't be isolated confidently falls back to
  normalize.summarize_trip's finish-position-based generic phrase rather
  than emitting garbage text.
- Foreign (GB/Ire/UAE/France, etc.) PP lines use a completely different
  column layout (Timeform ratings instead of DRF speed figures, no
  jockey/trainer stat parenthetical) - `parse_pp_lines` detects these via
  DATE_CODE_RE (domestic dates end in "=", foreign ones don't - see
  FOREIGN_DATE_CODE_RE's docstring) and routes them through
  `_parse_foreign_pp_line` instead, which is intentionally less ambitious
  (extracts date/track/distance/surface/finish only). An earlier version
  routed on the presence of a "3\u00ce"/"4\u00ce" class-code marker instead, but
  that marker turns out to be absent on genuine domestic Maiden Special
  Weight lines too (no claiming price/conditions to encode), which was
  silently dropping those horses' entire PP history - see the 2026-08-17
  bug report.
"""

from __future__ import annotations

import re

from parser.normalize import (
    MONTH_GLYPH_MAP, decode_pp_date, display_date,
    normalize_condition, infer_surface, summarize_trip, decode_pp_distance,
)

DATE_CODE_RE = re.compile(
    r"^\s*(\d{1,2})([" + re.escape("".join(MONTH_GLYPH_MAP.keys())) + r"])(\d{2})="
)
# Foreign lines use the same "day+month-glyph+2-digit-year" date code as
# domestic ones but WITHOUT the trailing "=" (e.g. "14Û26 Longchamp (Fr)..."
# vs domestic's "23Û26= 6Sar fst..."). A separate regex (rather than making
# DATE_CODE_RE's "=" optional) keeps the domestic/foreign line-inclusion
# check unambiguous - see parse_pp_lines.
FOREIGN_DATE_CODE_RE = re.compile(
    r"^\s*(\d{1,2})([" + re.escape("".join(MONTH_GLYPH_MAP.keys())) + r"])(\d{2})\s"
)

TRACK_COND_RE = re.compile(
    r"(?P<track>[A-Za-z]{2,5})\s*(?P<cond>fst|sly\u00f8?|my\u00f8?|gd|fm|yl|sf|hy|gs)?\s*"
    r"(?P<dist>[\d/\u00a1-\uffff.]+f|\d[\d\u00a1-\uffff/]*(?:mi)?)"
)

RESULT_NAME_RE = re.compile(r"[A-Za-z][A-Za-z\'\.]*\d[\d,]*[\u00a1-\uffff]{0,3}")

# The "final-time Beyer figure=class-rating" pair (e.g. "88=09") is a fixed
# anchor that always sits immediately before the 3-name results list and
# never appears earlier in the line - anchoring the results-list search
# here (rather than scanning the whole line for RESULT_NAME_RE) avoids
# false-positive "name" matches on the class-code ("N3L") and weight
# ("L126b") fields that appear earlier and would otherwise throw off which
# match is really the 3rd result name.
FIG_ANCHOR_RE = re.compile(r"\d+=\d+")


def _extract_trailing_comment(line: str) -> str | None:
    """
    Isolates the free-text trip comment at the end of a PP line: the
    fig=rating anchor marks where the 3-name results list starts, and the
    comment is whatever follows the 3rd (or fewer, on a short field) name.
    """
    anchor_ms = list(FIG_ANCHOR_RE.finditer(line))
    if not anchor_ms:
        return None
    search_from = anchor_ms[-1].end()

    names = list(RESULT_NAME_RE.finditer(line, search_from))
    stop_after = names[min(2, len(names) - 1)] if names else None
    tail = line[stop_after.end():].strip() if stop_after else line[search_from:].strip()
    return tail or None


def _parse_domestic_pp_line(line: str) -> dict | None:
    date_m = DATE_CODE_RE.match(line)
    if not date_m:
        return None
    day, glyph, yr = date_m.groups()
    iso = decode_pp_date(day, glyph, yr)

    rest = line[date_m.end():]
    tc_m = TRACK_COND_RE.search(rest)
    track = tc_m.group("track") if tc_m else None
    cond_raw = tc_m.group("cond") if tc_m else None
    dist_raw = tc_m.group("dist") if tc_m else None

    surface = infer_surface(cond_raw, None)
    cond = normalize_condition(cond_raw)

    # Final time: last "M:SS" or "M:SS.f" style token before the race type.
    # The trailing character (when present) is a fraction-of-a-second glyph
    # from the same embedded font as the month/distance glyphs elsewhere in
    # this document - stripped rather than decoded since the brief only
    # calls for the final time, not fractional splits (project brief 4.3).
    time_m = None
    for m in re.finditer(r"\d{1,2}:\d{2}[\u00a1-\uffff]?", rest):
        time_m = m  # keep the last (final) one
    final_time = re.sub(r"[\u00a1-\uffff]$", "", time_m.group(0)) if time_m else None

    # Race type, immediately followed by the speed figure (captured together
    # in one match, not re-searched afterward - the field-size/post-position
    # notation right after the figure, e.g. "67 7 /10", starts with its own
    # 1-3 digit number, so a second independent search past the race-type
    # match was picking that up instead of the actual figure). Searched
    # starting right after the final time rather than anchored on a
    # class-marker glyph - that glyph is sometimes preceded by a digit
    # ("3\u00ceClm..."), sometimes not ("\u00e7PeaPatchB..." on this fixture's
    # turf stakes lines), and sometimes absent entirely (Maiden Special
    # Weight lines have no claiming price/conditions to encode: "Md Sp Wt
    # 111k" with no marker at all - see the 2026-08-17 bug report). The
    # time field's end position is a reliable anchor regardless.
    # `fig` allows an optional leading "-" to catch DRF's "-0" placeholder
    # for an eased/no-figure effort (seen: Sports Hero, race 5) - without
    # it, "-0" doesn't look like a number to this pattern, so the lazy
    # `type` group swallows right past it and grabs the NEXT number in the
    # line instead - the running line's own start-call position - as if it
    # were the speed figure (see the 2026-08-17 bug report).
    search_area = rest[time_m.end():] if time_m else rest
    type_m = re.search(r"(?P<type>[A-Z][\w \$/'\-]{2,40}?)\s+(?P<fig>-?\d{1,3})\s", search_area)
    race_type = type_m.group("type").strip() if type_m else None
    fig = type_m.group("fig") if type_m else None
    if fig == "-0":
        fig = None

    # Finish: "/N" gives field size, immediately followed by the running
    # position at each point of call (start, 1st call, 2nd call, stretch,
    # finish) - a chain of "position+margin-glyph" tokens, e.g. "1\u00c7 1\u00c7 6\u00ab
    # 7\u00a6\u00ae\u00f5". This module previously assumed the very first call (the
    # start-call position) never carries a margin glyph, requiring a bare
    # digit there - true on some lines (a horse eased/pulled up: "4 10\u00aa
    # 10\u00ac\u00f4...") but false on most normal running lines, where every call
    # including the start position carries its own glyph (e.g. "7\u00ab\u00f5
    # 7\u00aa\u00f6 7\u00a9\u00f6 3\u00f4 1\u00a7\u00f5" - no bare digit anywhere) - see the 2026-08-17
    # bug report, where this left Finish blank on nearly every domestic PP
    # line. `{0,3}` (rather than requiring 1-3 glyph chars) makes the
    # margin-glyph suffix optional per call, covering both shapes with one
    # pattern instead of needing a separate bare-first-call case.
    field_size = None
    fs_m = re.search(r"/(\d{1,2})", rest)
    if fs_m:
        field_size = fs_m.group(1)
    finish_pos = None
    calls_m = re.search(r"/\d{1,2}\s+((?:\d{1,2}[\u00a1-\uffff]{0,3}\s*){1,6})", rest)
    if calls_m:
        calls = re.findall(r"(\d{1,2})[\u00a1-\uffff]{0,3}", calls_m.group(1))
        if calls:
            finish_pos = calls[-1]

    finish = None
    if finish_pos and field_size:
        suffix = {"1": "st", "2": "nd", "3": "rd"}.get(finish_pos[-1], "th")
        if finish_pos in ("11", "12", "13"):
            suffix = "th"
        finish = f"{finish_pos}{suffix} of {field_size}"

    comment = _extract_trailing_comment(line)
    ran = summarize_trip(comment, int(finish_pos) if finish_pos else None)

    return {
        "date": display_date(iso),
        "date_iso": iso,
        "track": track,
        "dist": decode_pp_distance(dist_raw),
        "race_type": race_type,
        "time": final_time,
        "fig": fig,
        "surf": surface,
        "cond": cond,
        "ran": ran,
        "finish": finish,
    }


def _parse_foreign_pp_line(line: str) -> dict | None:
    """
    Reduced-ambition parser for European-style lines (Timeform ratings,
    no DRF class marker). Extracts what's reliably present; everything
    else is left None and rendered as a blank by the generator. The date
    code uses the same glyph-encoded month as domestic lines (see
    FOREIGN_DATE_CODE_RE) - a plain 3-letter month abbreviation is kept as
    a fallback in case a different foreign-line variant uses that instead.
    """
    m = FOREIGN_DATE_CODE_RE.match(line)
    if m:
        day, mon_glyph, yr = m.groups()
        iso = decode_pp_date(day, mon_glyph, yr)
        date_display = display_date(iso)
    else:
        m = re.match(r"^\s*(\d{1,2})([A-Za-z]{3})(\d{2})", line)
        if not m:
            return None
        day, mon_abbrev, yr = m.groups()
        iso = None
        date_display = f"{day}{mon_abbrev}{yr}"

    track_m = re.search(r"\b([A-Za-z][A-Za-z .'\-]{2,20}\((?:GB|Ire|Fr|UAE|KSA)\))", line)
    track = track_m.group(1) if track_m else None
    # Finish position sits right before the jockey's name, itself followed
    # by a 3-digit weight and a decimal odds figure (e.g. "7 2\u00c7 David John
    # Egan          129    22.00") - anchoring on that fuller shape (rather
    # than "digit+glyph then any capitalized word") avoids false hits on
    # capitalized words elsewhere on the line, e.g. a stakes race's own
    # name ("Grand Prix de Paris-G1").
    finish_m = re.search(
        r"\b(\d{1,2})[\u00a1-\uffff]{1,3}\s+(?:[A-Z][a-zA-Z']*\s+){1,3}\d{3}\s+(?:[\d.]+|-)", line
    )
    finish_pos = finish_m.group(1) if finish_m else None
    return {
        "date": date_display,
        "date_iso": iso,
        "track": track,
        "dist": None,
        "race_type": "Foreign stakes (Timeform)",
        "time": None,
        "fig": None,
        "surf": "Turf",
        "cond": None,
        "ran": "European rider — trip not tabulated",
        "finish": f"{finish_pos} of ?" if finish_pos else None,
    }


def parse_pp_lines(horse_block_lines: list[str], max_lines: int = 5) -> tuple[list[dict], list[str]]:
    """
    Given the raw lines belonging to one horse (already isolated by
    horse_entry.py), returns (pp_dicts, parse_warnings). Only the first
    `max_lines` successfully-parsed PP rows are kept, most-recent-first
    (which is already the source order).

    Stops scanning once a "WORKS:" line is reached, rather than scanning
    the whole block. A WORKS: entry uses the exact same bare
    "day+month-glyph+2-digit-year" date code as a foreign PP line (no
    trailing "="), so without this cutoff a horse whose WORKS: list wraps
    onto a second physical line - common on 2yo/debut horses with many
    workouts, where that wrapped continuation line has no "WORKS:" prefix
    of its own to filter on - gets a fabricated "foreign race" appended
    from its own workout data (see the 2026-08-17 bug report: this hit
    first-time starters hardest, since a real first-time starter has zero
    genuine PP lines to hit `max_lines` before reaching WORKS: otherwise).
    """
    results = []
    warnings = []
    works_idx = next(
        (i for i, l in enumerate(horse_block_lines) if l.strip().startswith("WORKS:")),
        None,
    )
    scan_lines = horse_block_lines[:works_idx] if works_idx is not None else horse_block_lines
    for line in scan_lines:
        if len(results) >= max_lines:
            break
        stripped = line.strip()
        if not stripped or not re.match(r"^\d", stripped):
            continue
        if (
            not DATE_CODE_RE.match(stripped)
            and not FOREIGN_DATE_CODE_RE.match(stripped)
            and not re.match(r"^\d{1,2}[A-Za-z]{3}\d{2}", stripped)
        ):
            continue

        try:
            if DATE_CODE_RE.match(stripped):
                parsed = _parse_domestic_pp_line(stripped)
            else:
                parsed = _parse_foreign_pp_line(stripped)
        except Exception as exc:  # noqa: BLE001 - defensive per brief 4.4
            parsed = None
            warnings.append(f"Could not parse PP line ({exc}): {stripped[:60]}...")

        if parsed:
            results.append(parsed)

    return results, warnings
