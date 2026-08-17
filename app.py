"""
DRF Large-Print Racing Form Converter — Streamlit entrypoint.

Upload a Daily Racing Form past-performance PDF -> get back a large-print
"Format B2" PDF. See README.md for the current state of the parser and
known limitations; see generator/build_pdf.py's docstring for the exact
output layout spec.
"""

from __future__ import annotations

import re
import tempfile
import traceback
from pathlib import Path

import streamlit as st

from parser.extract import extract_layout_text, ExtractionError
from parser.race_header import parse_race_header, RACE_NUM_TRACK_RE
from parser.horse_entry import split_horse_blocks, parse_horse
from parser.stat_grid import extract_stat_rows
from generator.build_pdf import build_pdf

STAT_GRID_TRACK_ABBREV = "Sar"  # see normalize.py's module docstring on recalibrating per-fixture

st.set_page_config(page_title="DRF Large-Print Racing Form", page_icon="🏇", layout="centered")


def _apply_stat_grid_cross_check(
    pdf_path: str, current_year: str | None, horse_pages: list[tuple[dict, int, str]]
) -> None:
    """
    Overwrites each horse's life/year/track_stat/surf_stat fields with the
    pdfplumber-coordinate-based reading (parser/stat_grid.py) where one was
    found, on top of whatever horse_entry.parse_horse already guessed from
    pdftotext -layout text. Mutates the horse dicts in place. Degrades
    gracefully per project brief 4.4: a horse gets no update (keeping its
    pdftotext-based guess) if its page yields nothing usable, or if the
    card's date - and therefore current_year - couldn't be determined.
    """
    if not current_year or not horse_pages:
        return

    by_page: dict[int, list[tuple[dict, str]]] = {}
    for horse, page_idx, surf_key in horse_pages:
        by_page.setdefault(page_idx, []).append((horse, surf_key))

    for page_idx, entries in by_page.items():
        try:
            rows = extract_stat_rows(pdf_path, page_idx, current_year, STAT_GRID_TRACK_ABBREV)
        except Exception:  # noqa: BLE001 - defensive per brief 4.4; keep the pdftotext guess
            continue
        for (horse, surf_key), row in zip(entries, rows):
            for field in ("life", "year", "track_stat"):
                if row.get(field):
                    horse[field] = row[field]
            surf_val = row.get("surf_dfst" if surf_key == "D.Fst" else "surf_turf")
            if surf_val:
                horse["surf_stat"] = surf_val


def _reconcile_pp_gaps(races: list[dict]) -> list[str]:
    """
    Reconciles `first_time_starter` (set early in horse_entry.py, from a
    literal "Life 0 M 0 0" text match that can miss when that row's 4th
    count fragments onto a different text line - see FIRST_TIME_MARKER_RE)
    against `life` (set later, from the more reliable pdfplumber-coordinate
    reading in stat_grid.py - see _apply_stat_grid_cross_check, which runs
    before this). Only meaningful once both fields are final, which is why
    this runs as a separate pass after that cross-check rather than inline
    in horse_entry.parse_horse.

    For any horse with an empty PP table that isn't already flagged as a
    first-time starter:
    - if LIFE genuinely shows 0 starts, it IS one - the text-marker match
      just missed it (seen: Hooked, race 8) - so `first_time_starter` is
      corrected to True, which also fixes build_pdf.py's rendered note.
    - if LIFE shows starts > 0, this is a real parsing gap, not a
      first-time starter, and a materially wrong claim if rendered as one
      (seen: Decimation, race 8, in the 2026-08-17 bug report this all
      traces back to) - build_pdf.py renders these as "Past performance
      data unavailable" rather than "First-time starter", and a warning is
      returned here so it surfaces per project brief 4.4 rather than
      silently understating the horse's record.
    """
    warnings = []
    for race in races:
        for horse in race["horses"]:
            if horse.get("scratched") or horse.get("first_time_starter") or horse.get("pp_lines"):
                continue
            life = horse.get("life")
            starts_m = re.match(r"(\d+)-", life) if life else None
            if not starts_m:
                continue
            if int(starts_m.group(1)) == 0:
                horse["first_time_starter"] = True
            else:
                warnings.append(
                    f"#{horse.get('num')} {horse.get('name')}: LIFE record shows "
                    f"{starts_m.group(1)} start(s) but no past-performance lines could be parsed"
                )
    return warnings


def parse_card(pdf_path: str) -> tuple[dict | None, list[str], list[str]]:
    """
    Returns (card_dict_or_None, warnings, errors).
    A None card means parsing failed hard (unparseable PDF / zero races
    found) - see project brief section 6.
    """
    warnings: list[str] = []

    try:
        text = extract_layout_text(pdf_path)
    except ExtractionError as exc:
        return None, warnings, [str(exc)]

    lines = text.split("\n")
    race_start_idxs = [
        i for i, l in enumerate(lines)
        if RACE_NUM_TRACK_RE.match(l) and re.search(r"[A-Za-z]{3,}", l)
    ]
    # De-dupe / filter: real race-header lines are followed reasonably soon
    # by a "Post time:" line; index-page "N  Name" listings never are.
    confirmed = []
    for idx in race_start_idxs:
        window = "\n".join(lines[idx: idx + 40])
        if "Post time:" in window:
            confirmed.append(idx)
    race_start_idxs = confirmed

    if not race_start_idxs:
        return None, warnings, [
            "Could not find any races in this PDF. It may not be a "
            "DRF-style past-performance export, or the export format has "
            "changed enough that the header pattern this app looks for "
            "no longer matches."
        ]

    track_name = None
    m = RACE_NUM_TRACK_RE.match(lines[race_start_idxs[0]])
    if m:
        track_name = m.group(2).strip()

    date_m = re.search(r"Saratoga\s*\((\d{1,2})/(\d{1,2})/(\d{4})\)", text)
    date_str = None
    date_iso = None
    if date_m:
        mo, da, yr = date_m.groups()
        date_iso = f"{yr}-{int(mo):02d}-{int(da):02d}"
        months = ["", "January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        date_str = f"{months[int(mo)]} {int(da)}, {yr}"

    # Line -> page index, for the pdfplumber-based stat-grid cross-check
    # below (extract_layout_text preserves pdftotext's form-feed page
    # breaks - see extract.split_pages).
    page_idx_of_line = []
    p = 0
    for l in lines:
        if l.startswith("\x0c"):
            p += 1
        page_idx_of_line.append(p)
    current_year = date_iso.split("-")[0] if date_iso else None

    races = []
    # (horse_dict, page_idx, surf_key) for the stat-grid pass below.
    horse_pages: list[tuple[dict, int, str]] = []
    for n, idx in enumerate(race_start_idxs):
        end = race_start_idxs[n + 1] if n + 1 < len(race_start_idxs) else len(lines)
        race_block = lines[idx:end]
        race_block_page_idxs = page_idx_of_line[idx:end]

        race, race_warnings = parse_race_header("\n".join(race_block))
        warnings.extend(f"Race {race.get('num', '?')}: {w}" for w in race_warnings)

        post_idxs = [i for i, l in enumerate(race_block) if "Post time:" in l]
        body_offset = post_idxs[0] + 1 if post_idxs else 0
        body = race_block[body_offset:]
        body_page_idxs = race_block_page_idxs[body_offset:]

        horse_blocks = split_horse_blocks(body)
        surf_key = "D.Fst" if (race.get("surface") or "Dirt") == "Dirt" else "Turf"

        # Horse blocks partition `body` contiguously (see
        # horse_entry.split_horse_blocks), so only the first block's
        # position needs locating by search - later ones follow directly.
        cursor = 0
        if horse_blocks:
            first_len = len(horse_blocks[0])
            cursor = next(
                (k for k in range(len(body) - first_len + 1)
                 if body[k:k + first_len] == horse_blocks[0]),
                0,
            )
        for hb in horse_blocks:
            horse, horse_warnings = parse_horse(hb, race.get("surface") or "Dirt")
            warnings.extend(horse_warnings)
            race["horses"].append(horse)
            if current_year and cursor < len(body_page_idxs):
                horse_pages.append((horse, body_page_idxs[cursor], surf_key))
            cursor += len(hb)

        races.append(race)

    _apply_stat_grid_cross_check(pdf_path, current_year, horse_pages)
    warnings.extend(_reconcile_pp_gaps(races))

    if not any(r["horses"] for r in races):
        return None, warnings, [
            "Found race headers but could not parse any horses out of them. "
            "The PDF's internal layout may differ enough from the reference "
            "fixture that the horse-block detection regex needs adjusting."
        ]

    card = {
        "track_name": track_name or "Track",
        "date_str": date_str or "",
        "date_iso": date_iso,
        "races": races,
    }
    return card, warnings, []


def output_filename(card: dict) -> str:
    track = re.sub(r"[^A-Za-z0-9]+", "", card.get("track_name") or "Track")
    date_iso = card.get("date_iso")
    if track and date_iso:
        return f"{track}_{date_iso}_LargePrint.pdf"
    return "LargePrint_RacingForm.pdf"


def main():
    st.title("🏇 DRF Large-Print Racing Form Converter")
    st.write(
        "Upload a Daily Racing Form past-performance PDF for a race card. "
        "You'll get back a reformatted, large-print PDF (Format B2) to "
        "download."
    )

    uploaded = st.file_uploader("Upload DRF PDF", type=["pdf"])
    if uploaded is None:
        st.info("Waiting for a PDF upload.")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = str(Path(tmpdir) / "input.pdf")
        with open(in_path, "wb") as f:
            f.write(uploaded.getbuffer())

        with st.spinner("Parsing the racing form… this can take a few seconds for a full card."):
            try:
                card, warnings, errors = parse_card(in_path)
            except Exception:  # noqa: BLE001 - last-resort guard, see brief section 6
                st.error(
                    "Something went wrong reading this PDF. Here's the technical "
                    "detail, in case it's useful for debugging:"
                )
                st.code(traceback.format_exc())
                return

        if errors:
            st.error(errors[0])
            return

        n_races = len(card["races"])
        n_horses = sum(len(r["horses"]) for r in card["races"])
        st.success(f"Parsed {n_races} race(s), {n_horses} horse(s).")

        if warnings:
            with st.expander(f"⚠️ {len(warnings)} entries had incomplete data — details"):
                for w in warnings:
                    st.write(f"- {w}")

        with st.spinner("Building the large-print PDF…"):
            out_path = str(Path(tmpdir) / "output.pdf")
            try:
                build_pdf(card, out_path)
            except Exception:  # noqa: BLE001
                st.error(
                    "Parsing succeeded but building the PDF failed. Technical "
                    "detail:"
                )
                st.code(traceback.format_exc())
                return

        with open(out_path, "rb") as f:
            pdf_bytes = f.read()

        st.download_button(
            label="Download large-print PDF",
            data=pdf_bytes,
            file_name=output_filename(card),
            mime="application/pdf",
        )


if __name__ == "__main__":
    main()
