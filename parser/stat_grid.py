"""
Coordinate-based extraction of the condensed LIFE/current-year/at-track/SURF
stat grid, using pdfplumber word bounding boxes instead of pdftotext -layout
text.

------------------------------------------------------------------------
WHY THIS EXISTS (see horse_entry.py's module docstring and README "What
needs work" #2 for the fuller story)
------------------------------------------------------------------------
Each horse's identity block actually contains TWO side-by-side tables that
happen to start at the same page height but have different row heights (the
left table - LIFE/current-year/prior-year/at-track - has 4 rows; the right
table - dirt-fast/wet/synthetic/turf/at-distance - has 5 rows in the same
vertical span). `pdftotext -layout` renders both by y-position band, so by
a few rows down the two tables' rows have drifted out of alignment and it
concatenates fragments from unrelated rows onto one output line, or splits
one logical row's own count/earnings/speed-figure across adjacent output
lines. horse_entry.py's `_find_dollars_and_speed_near` was a best-effort
guess at reassembling this from the mangled text and admits it can pick up
a neighboring row's numbers.

pdfplumber's raw word coordinates don't have this problem - verified
against the fixture, a horse's "Life" label and its own $earnings/speed
figure sit at the *exact same* `top` value, they just get serialized onto
different output lines by pdftotext's column-band heuristic. So: find the
label word by text, collect every other word on the same `top` (within a
tight tolerance) to its right in the same table (left table x0 in
~[376,392], right table x0 in ~[474,500] for the label; data columns start
around x0 396 / 507 respectively - both empirically stable across every
page checked in the fixture), and read off S-W-P-Show counts, $earnings,
and speed figure directly. `x_tolerance=2, y_tolerance=2` on
`extract_words` is required - pdfplumber's defaults leave "$11,850" split
into "$11,8" + "5" + "0" word fragments on this document's embedded font.

Per-horse row search is bounded between one horse's "Life" occurrence and
the next (or page bottom for the last horse on a page), so a row that's
sometimes missing (e.g. no "Sar" row when a horse has no starts to report
at that specific label) doesn't shift alignment for subsequent horses -
unlike a fixed "chunk every 4 rows into one horse" scheme would.

This is used as a cross-check / primary source layered on top of
horse_entry.py's counts-only extraction (which stays reliable per its own
docstring); when a row can't be found here the caller falls back to the
pdftotext-based guess rather than emitting nothing (project brief 4.4).
------------------------------------------------------------------------
"""

from __future__ import annotations

import functools

LEFT_LABEL_X = (374.0, 392.0)
LEFT_DATA_X_MIN = 394.0
RIGHT_LABEL_X = (472.0, 500.0)
RIGHT_DATA_X_MIN = 502.0
ROW_TOP_TOL = 1.5


@functools.lru_cache(maxsize=4)
def _load_pages(pdf_path: str):
    import pdfplumber

    pdf = pdfplumber.open(pdf_path)
    return [
        page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False)
        for page in pdf.pages
    ]


def _cluster_rows(words: list[dict]) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: w["top"]):
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= ROW_TOP_TOL:
            rows[-1].append(w)
        else:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    return rows


def _row_stats(row: list[dict], data_x_min: float) -> str | None:
    """
    Turns a row's data words (after the label) into 'S-W-P-S, $earnings,
    spd F'. The first 4 data tokens are the starts/wins/places/shows
    counts positionally - taken by position rather than "all digit-looking
    tokens in the row" so a horse with 0 wins (DRF prints "M", for Maiden,
    in the wins slot instead of "0") doesn't shift the speed figure into
    the count group by accident.
    """
    data = [w for w in row if w["x0"] >= data_x_min]
    if len(data) < 6:
        return None
    counts = []
    for w in data[:4]:
        if w["text"] == "M":
            counts.append("0")
        elif w["text"].isdigit():
            counts.append(w["text"])
        else:
            return None
    dollars, spd = data[4]["text"], data[5]["text"]
    if not dollars.startswith("$"):
        return None
    if spd == "-":
        spd = "—"  # em dash, matching the rest of the app's "no data" convention
    counts_str = "-".join(counts)
    return f"{counts_str}, {dollars}, spd {spd}"


def extract_stat_rows(
    pdf_path: str, page_index: int, current_year: str, track_abbrev: str
) -> list[dict]:
    """
    Returns a list of per-horse stat dicts (keys: life, year, track_stat,
    surf_dfst, surf_turf - each a formatted 'S-W-P-S, $earnings, spd F'
    string or None) for every horse whose identity block starts on the
    given page, in top-to-bottom document order. Callers zip this against
    the horses already known (via the pdftotext-based split) to be on that
    page, and pick surf_dfst or surf_turf per horse based on that horse's
    own race's surface - a page can contain horses from two different
    races (and therefore two different "today's surface" values) when a
    race boundary falls mid-page, so the surface key can't be fixed for
    the whole page.
    """
    pages = _load_pages(pdf_path)
    if page_index >= len(pages):
        return []
    words = pages[page_index]

    life_words = [w for w in words if LEFT_LABEL_X[0] <= w["x0"] <= LEFT_LABEL_X[1] and w["text"] == "Life"]
    life_words.sort(key=lambda w: w["top"])
    if not life_words:
        return []

    # Full row span (label + its data columns), not just the label column -
    # the label-only x-range above is for locating "Life" itself as an
    # anchor, but a row's counts/$/spd live further right.
    left_words = [w for w in words if LEFT_LABEL_X[0] <= w["x0"] < RIGHT_LABEL_X[0]]
    right_words = [w for w in words if w["x0"] >= RIGHT_LABEL_X[0]]

    results = []
    for i, life_w in enumerate(life_words):
        top = life_w["top"]
        # Window boundaries are the midpoints to the neighboring horses'
        # own "Life" anchors, not `top` +/- a fixed fudge - the right
        # table's rows sit ~0.2pt *above* their own horse's Life row (an
        # alignment quirk of the source PDF), so a fixed-offset window
        # start wide enough to catch that also overlaps the tail end of
        # the previous horse's window and double-counts its last row
        # (e.g. its own D.Fst row getting attributed to both horses).
        # Midpoints partition the page with no overlap.
        # The stat grid's own rows all fall within ~35pt below its Life
        # anchor - capping the window there (rather than at the midpoint to
        # the next horse, which can be 100+pt away) keeps unrelated content
        # in the same x-range - a previous/next horse's PP-line trailing
        # comment/speed-figure text lands in this same x0 band on some
        # pages - from being mistaken for a row.
        window_start = max(top - 3.0, (life_words[i - 1]["top"] + top) / 2 if i > 0 else top - 3.0)
        window_end = min(top + 40.0, (top + life_words[i + 1]["top"]) / 2 if i + 1 < len(life_words) else top + 40.0)

        left_rows = _cluster_rows([w for w in left_words if window_start <= w["top"] < window_end])
        right_rows = _cluster_rows([w for w in right_words if window_start <= w["top"] < window_end])

        # Matched by label text, not "first row in the window", since a wide
        # window can also catch unrelated content that happens to fall in
        # this x-range above the true Life row (e.g. the previous horse's
        # PP-line speed-figure/comment column lands in the same x0 band on
        # some pages).
        life_row = next((r for r in left_rows if r[0]["text"] == "Life"), [])
        year_row = next((r for r in left_rows if r[0]["text"] == current_year), None)
        track_row = next((r for r in left_rows if r[0]["text"].startswith(track_abbrev)), None)
        dfst_row = next((r for r in right_rows if r[0]["text"].startswith("D.Fst")), None)
        turf_row = next((r for r in right_rows if r[0]["text"].startswith("Turf")), None)

        results.append({
            "life": _row_stats(life_row, LEFT_DATA_X_MIN) if life_row else None,
            "year": _row_stats(year_row, LEFT_DATA_X_MIN) if year_row else None,
            "track_stat": _row_stats(track_row, LEFT_DATA_X_MIN) if track_row else None,
            "surf_dfst": _row_stats(dfst_row, RIGHT_DATA_X_MIN) if dfst_row else None,
            "surf_turf": _row_stats(turf_row, RIGHT_DATA_X_MIN) if turf_row else None,
        })
    return results
