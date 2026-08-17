# DRF Large-Print Racing Form Converter

Upload a Daily Racing Form past-performance PDF → get back a large-print
"Format B2" PDF. See `PROJECT_BRIEF.md` (the original spec) for full
background; this file tracks the current build state.

## Status: working end-to-end, all six tracked issues resolved

The **generator is done and visually validated** against the approved
Format B2 spec. The parser has been through a full iterative tuning pass
against the real Aug 15, 2026 Saratoga fixture, validated field-by-field
against `tests/fixtures/saratoga_2026-08-15_expected_output.pdf` (which
turns out to already contain fully-decoded reference values for almost
every field — extremely useful as a calibration oracle, though not
infallible; see "A note on the reference output" below).

Last full-pipeline test: **12 of 12 races detected, 105 of 105 horses
parsed** (matches the fixture's true horse count exactly, confirmed against
the reference), PDF builds successfully (`tests/full_pipeline_test.pdf` if
you regenerate it — not committed).

Along the way, two bugs turned out to be bigger than their original
description: the "races 4 and 5 don't match the header regex" issue
(item 5 below) actually affected races 4, 5, 9, 11, and 12; and there was
an entirely separate, previously-undiagnosed bug dropping races 10-12 (29
horses) from the output completely, because their race-number/track header
line has the distance/purse text appended on the same line, which
`RACE_NUM_TRACK_RE` didn't anticipate. Both are fixed.

## Quick start

```bash
pip install -r requirements.txt --break-system-packages   # or use a venv
streamlit run app.py
```

Upload `tests/fixtures/saratoga_2026-08-15_source.pdf` to try it against
the reference fixture. Compare against
`tests/fixtures/saratoga_2026-08-15_expected_output.pdf` for the target
visual style (note: that file matches Format B2's layout at a glance, but
wasn't re-diffed field-by-field against this parser's output — worth doing
as a first task).

## Architecture

```
app.py                    Streamlit entrypoint: upload → parse → build → download
parser/
  extract.py               pdftotext -layout wrapper (see below for why)
  race_header.py            race number/post time/distance/conditions/purse
  horse_entry.py            per-horse identity/connections/breeding/stat line
  past_performances.py      up to 5 PP lines per horse
  normalize.py               month-glyph decoder, distance-fraction decoder, condition map, trip-phrase map
  stat_grid.py               pdfplumber coordinate-based reader for the LIFE/2026/SAR/SURF stat line
generator/
  build_pdf.py               Format B2 layout (reportlab) — decoupled from parser
  styles.py                  theme colors + paragraph styles
tests/
  fixtures/                  the Aug 15, 2026 Saratoga source PDF + reference output
```

`generator/build_pdf.py` takes a plain nested-dict structure (documented in
its module docstring) and knows nothing about DRF PDFs — you can hand it
hand-written test data and it'll render correctly, which is how it was
built and validated before the parser existed.

## Key finding: pdfplumber vs. pdftotext -layout

The brief specified `pdfplumber` for extraction. Tested directly against
the real fixture, `pdfplumber.page.extract_text()` badly scrambles the
dense header box at the top of each horse's entry (interleaves characters
from adjacent columns). **`pdftotext -layout` (Poppler CLI, already on
this box) works much better** and is what `parser/extract.py` actually
uses — pdfplumber is kept available as a documented fallback but isn't
wired into the pipeline. Full reasoning is in `extract.py`'s module
docstring.

## What works well right now

- Race header parsing: number, post time, distance (now fully decoded,
  see #3 below), purse, condensed conditions string — all 12/12 races,
  zero warnings.
- Horse identity: number, name, morning line, scratched flag —
  105/105 horses across all 12 races, matching the fixture's true
  horse count exactly (`horse_entry.split_horse_blocks` was rewritten;
  see #1 below).
- Jockey/trainer names + current-year stats.
- Sire/dam/breeder.
- The condensed LIFE/2026/SAR/SURF stat line — 104/104 (life/year/track),
  103/104 (surf) fields verified against the reference (see #2 below).
- PP line count, dates (see the month-glyph section below), tracks,
  distances (99.6% verified), race types, time/speed-figure (91%
  verified), finish position (94%+ where present), and a RAN summary with
  a substantially broadened trip-phrase vocabulary.
- First-time starters, scratches (detected via "NO RIDER" in place of the
  jockey line — this fixture's export never actually prints the word
  "SCRATCHED"), and foreign (GB/Ire/UAE/France) PP lines, all verified
  against real examples in the fixture (Race 10's scratch, Race 9's
  foreign trio).

## What was fixed this session (previously "What needs work")

1. **Horse block detection.** Rewritten to anchor on each horse's "Own:"
   line (present exactly once per horse, scratched/FTS/foreign included)
   rather than trying to match the number+name line directly, whose exact
   shape turned out to have at least four distinct variants in this one
   fixture (see `horse_entry.py`'s docstrings for `HORSE_START_RE` and
   `COMBINED_START_RE`). Now 105/105 horses, exactly matching the ground
   truth, with correct sequential numbering.

2. **The condensed LIFE/2026/SAR/SURF stat line.** Rewired onto a
   pdfplumber coordinate-based reader (`parser/stat_grid.py`) layered on
   top of the original pdftotext-based guess as a fallback. Confirmed
   directly against the fixture: a horse's "Life" label and its own
   $earnings/speed figure sit at the *exact same* y-position — pdftotext
   -layout was serializing them onto different output lines because of a
   row-height mismatch between two side-by-side tables, not because the
   data was actually ambiguous. 104/104 (life/year/track), 103/104 (surf)
   verified; the one remaining mismatch (Mythical, race 10) appears to be
   an error in the reference file itself, not this parser (its raw D.Fst
   row exactly equals its LIFE totals — meaning all its starts were on
   dirt — yet the reference labels that row "SURF Dirt" in a turf race).

3. **Distance fraction glyphs.** Calibrated directly against the
   reference output (`normalize.FURLONG_FRACTION_GLYPH_MAP`,
   `MILE_FRACTION_GLYPH_MAP`) rather than re-deriving from scratch: "ô" =
   1/2 (furlongs), "Â" = 1/16 and "¶" = 1/2 (miles). Four more mile-
   fraction glyphs appear in PP lines but never in a race header in this
   fixture, so there's no ground truth to anchor them against yet — left
   uncalibrated (pass through as-is) rather than guessed, same rationale
   as `MONTH_GLYPH_MAP`'s Sep/Oct caveat. 265/266 (99.6%) of PP distance
   tokens now verified matching the reference.

4. **RAN comment extraction and trip-phrase table.**
   `_extract_trailing_comment` was rewritten to anchor on the fixed
   "Beyer-figure=class-rating" token (e.g. "88=09") that always
   immediately precedes the 3-name results list, instead of a
   whitespace-gap heuristic that broke whenever a horse's name happened to
   be long enough to close the gap — this was the actual reason so many
   rows fell back to the generic "Mid-pack" phrase. `normalize.
   summarize_trip` is now a two-part composer (trip/position half +
   outcome half, e.g. "Bumped start" + "no rally") built from this
   fixture's real comment vocabulary, instead of a handful of whole-phrase
   patterns — the generic fallback rate dropped from 50% to ~22%.

5. **Race header regex.** Fixed for all races, not just 4 and 5 — the
   real cause was `DISTANCE_LINE_RE` requiring lowercase-ish "Furlongs"/
   "Miles" text, which route races render as "1 MILE"/"1Â MILES" (all
   caps); the turf-course marker was also hardcoded to literal "(Turf)"
   and missed "(Inner Turf)". Both fixed; all 12 races now parse
   distance/surface/purse with zero warnings.

6. **Scratches, first-time-starters, and foreign lines**, verified against
   the fixture's real examples. L'Eclair (Race 10) is detected as
   scratched via "NO RIDER" (this export never prints the literal word
   "SCRATCHED" anywhere). Ancient Egypt, Fort George, and Survie (Race 9)
   now correctly show their full foreign PP history — their date code
   turned out to use the same glyph-encoded month as domestic lines but
   without the trailing "=", so it wasn't being recognized as a PP line at
   all; `_parse_foreign_pp_line`'s finish-position regex was also
   loosened to require the fuller "position+jockey-name+weight+odds"
   shape rather than "any digit followed by a capitalized word", which
   was matching random capitalized text elsewhere in the line (e.g. a
   stakes race's own name).

### A note on the reference output

`tests/fixtures/saratoga_2026-08-15_expected_output.pdf` turned out to
already contain fully-decoded values for nearly every field this parser
extracts (jockey/trainer stats, decoded distances, RAN summaries, finish
positions), which made it an excellent calibration oracle throughout this
session — used the same way the month-glyph mapping was originally
calibrated (direct ground-truth comparison, not guessing). It is not
perfectly authoritative, though: at least one field (Mythical's SURF label
in race 10, see #2 above) appears to be wrong in the reference itself, and
the README's own prior note ("matches Format B2's layout at a glance, but
wasn't re-diffed field-by-field") suggests it may have been built by a
process that didn't always parse the *source* PDF exactly right either.
Treat mismatches against it as a strong signal worth investigating, not
an automatic verdict against this parser's output.

## Remaining known gaps

- Four of six mile-fraction distance glyphs are uncalibrated (see #3
  above) — re-run the same direct-comparison calibration against a second
  fixture whose race headers happen to use one of them.
- Time+speed-figure fields verify at ~91% against the reference and
  finish position at ~94% where a value is produced; the remaining gaps
  are mostly unusual PP-line layouts (e.g. margin-glyph tokens of unusual
  length) that fall back to a blank field rather than a guess.
- Stakes race names get shortened to whatever text sits directly before
  ". Purse $" (e.g. "Grade I" rather than "The Christophe Clement Turf,
  Grade I" for race 9) — the condensed conditions string is functionally
  fine but loses the actual stakes name on graded/black-type races.

## The month-glyph decoder (already solved — don't redo this)

`parser/normalize.py`'s `MONTH_GLYPH_MAP` was reverse-engineered from the
fixture (12 distinct glyphs = 12 months, calibrated via plain-digit date
anchors elsewhere in the same document, plus a zero-violation
chronological-ordering constraint solve for the rest). Full methodology
and per-glyph confidence levels are documented at the top of that file.
Two glyphs (Sep/Oct) are a low-confidence coin flip from this single
fixture — if a second race-day PDF becomes available, re-run the same
calibration against it to firm those two up (or swap them if the
constraint solve disagrees).

## Testing plan (from the original brief, still the right plan)

Use the Saratoga fixture pair in `tests/fixtures/` — it already exercises
first-time starters, a scratch, foreign past performances, and both
surfaces. Spot-check: race header formatting, a horse with 5 PP lines, a
maiden with 0 PP lines, the scratched horse, a foreign-bred stakes horse.
Render output to PNGs with `pdftoppm -png -r 100` for visual QA the same
way this session did (see `tests/` for example output from this session —
not committed, regenerate as needed).

## Non-goals (unchanged from the original brief)

No login, no batch upload, no in-app scratch/odds editing, no non-DRF
layouts, no mobile-specific tuning beyond Streamlit defaults.
# drf-largeprint
