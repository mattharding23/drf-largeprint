# Visual QA Bug Report — Format B2 Rendered Output

**Date:** 2026-08-17
**Source file spot-checked:** `full_pipeline_test.pdf` (40 pages, Saratoga 8/15/2026 fixture, 12/12 races, 105/105 horses)
**Method:** Rasterized pages 1, 2, 6, 25, 26, 32 at 150 DPI and visually reviewed against the Format B2 spec (PROJECT_BRIEF.md §5), targeting: cover page, a 5-PP horse, a first-time starter, a scratched horse, and a foreign stakes horse with Timeform-style lines.

This is the deferred "visual spot-check of the rendered PDF at the field level" task from the 08/16 session summary. Verdict: **layout/spec compliance is strong**, but two data-correctness bugs and two lower-severity rendering issues need fixing before this goes further.

---

## Priority 1 — Data correctness bugs (fix first)

These produce *wrong information* in the output, not just cosmetic issues, so they matter most for a low-vision bettor relying on this sheet.

### Bug 1: Decimation (Race 8, #7) — contradicts its own stat line

**Page 25.** The condensed stats line renders real career numbers:

```
LIFE 2-0-1-0, $26,600, spd 64   2026 2-0-1-0, $26,600, spd 64   SAR 1-0-1-0, $23,000, spd 64   SURF Dirt: 2-0-1-0, $26,600, spd 64
```

...meaning this horse has raced before. But directly below it, the body renders:

```
First-time starter — no prior races
```

instead of a past-performance table. The horse clearly has ≥1 prior race (per its own stats), so the "0 PP rows found → first-time starter" fallback in the generator is firing incorrectly. This means the PP line(s) for Decimation are being lost somewhere between stat-grid extraction (`stat_grid.py`, which is working — the numbers are right) and past-performance table extraction (`past_performances.py`, which is producing zero rows).

**Suggested fix approach:** Add a validation check in the generator (or a QA step in the pipeline): if a horse's LIFE starts count is > 0 but the parser found 0 PP rows, flag it as an inconsistency rather than silently rendering the "first-time starter" branch. That turns this class of bug into a visible warning ("N entries had incomplete data," per §4.4 of the brief) instead of a silent wrong answer. Then debug why Decimation's PP line specifically didn't parse — worth checking whether its horse-block boundary (anchored on `Own:`, per the 08/16 fix) is landing in the wrong place, possibly related to it being immediately followed by Damavand (Bug 2) — two adjacent horses both showing corruption suggests a shared root cause in that stretch of the source PDF.

### Bug 2: Damavand (Race 8, #8) — jockey field shows the trainer's name

**Page 25.** Renders:

```
Jockey: Pletcher Todd A — 2026: 373 starts, 68 wins (18%)   |   Trainer: Pletcher Todd A — 2026: 373 starts, 68 wins (18%)
```

Both fields show the same person and the same stat line. "Pletcher Todd A" is a trainer name (format matches other trainer entries throughout the doc — e.g. Dallas Star's trainer, same race, same horse block). The actual jockey for Damavand is missing/unparsed, and something in horse-block parsing is falling back to duplicating the trainer field into the jockey slot rather than leaving it blank or flagging it.

**Suggested fix approach:** Same root-cause investigation as Bug 1 — Damavand is adjacent to Decimation in the same race, so check whether both trace back to one malformed or unusually-shaped horse block in the source PDF (e.g. a missing/misplaced jockey line, or an `Own:` anchor collision). Also add a guard: if jockey-name extraction ever resolves to the same string as the trainer name, treat it as a parse failure and blank/flag it rather than accept the duplicate.

---

## Priority 2 — Rendering issues

### Bug 3: Foreign track names word-wrap mid-word in the TRK column

**Page 26 (Race 9, Ancient Egypt (Ire), foreign stakes lines).** Longer foreign track names break across lines mid-word inside the narrow TRK column:

- "Longchamp (Fr)" → renders as "Long / cham / p (Fr)"
- "Newmarket (GB)" → renders as "New / mark / et (GB)"
- "Epsom (GB)" → renders as "Epso / m (GB)"

The TRK column width was sized for short US abbreviations (Sar, BAQ, Aqu) and isn't wide enough for longer foreign names, which also don't appear to have `wordWrap='CJK'`-style character-break protection turned off.

**Suggested fix:** Either widen the TRK column slightly (borrow space from a column with more headroom, e.g. RACE TYPE or FINISH) or set the cell style to avoid breaking within a track name — e.g. keep the parenthetical country code as a non-breaking unit, or reduce font size specifically for TRK cells with long foreign names. Since this only affects foreign-track PP lines, a targeted fix (rather than a global column resize) is probably cleanest.

### Bug 4: Cover page is missing the date subtitle

**Page 1.** Spec (§5.1) calls for: green banner, white bold title, gold divider line, **and a subtitle with the card's date**. The banner, title, and gold divider all render correctly, but no subtitle appears below the divider — the rest of the page is blank.

**Suggested fix:** Add the missing subtitle Paragraph/Flowable after the divider line in the cover-page builder — likely a one-line omission in `build_pdf.py`, not a parsing issue, since the date (August 15, 2026) is already being parsed correctly and used elsewhere (e.g. presumably in the filename).

---

## What's confirmed working (no action needed)

Spot-checked and matches spec exactly:
- **5-PP horse** (Epitaph, Race 1, page 2): name/ML/rule, connections line, breeding line, condensed stats line, and a full 5-row table with RAN correctly rendered as short trip summaries ("Bumped start," "Stalked, weakened," etc.) — not verbose corner-by-corner commentary.
- **First-time starters** (Race 2, page 6): zero stat line + italic "First-time starter — no prior races" note, no table shown. Correct for multiple horses checked.
- **Scratch handling** (L'Eclair, Race 10, page 32): single red bar, `#9 L'Eclair` left / `SCRATCHED` center / `ML 4-1` right, no stats/breeding/table rendered below it. Matches §5.4 exactly.
- **Foreign stakes horse, non-wrapping fields** (Ancient Egypt, Race 9, page 26): "European rider/stable — record not tabulated" fallback text, Timeform-style rows with `—` for missing FIG/TIME/COND, and RAN correctly showing "European rider — trip not tabulated." The graceful-degradation behavior from §4.4 is working as designed — only the TRK column wrapping (Bug 3) needs a fix.

---

## Recommended order of work

1. Fix Bugs 1 & 2 together — likely one shared root cause in horse-block parsing around Decimation/Damavand in Race 8. Add the "stats say raced, but 0 PP rows found" validation guard while in there, since it'll catch future instances of this same failure mode elsewhere in the doc (or in future tracks) even if the root cause isn't fully squashed.
2. Fix Bug 4 (cover subtitle) — quick, isolated, no parsing involved.
3. Fix Bug 3 (TRK column wrapping) — isolated to `generator/styles.py` / table column widths.
4. Re-render the full 12-race, 105-horse fixture and re-run a full visual pass (all pages, not just the spot-check sample) to confirm no other horses share the Decimation/Damavand failure mode.
5. Once clean, move to the two remaining deferred items: git push + Streamlit Community Cloud connection, and testing against a second track's PDF.
