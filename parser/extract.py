"""
Text extraction backend.

------------------------------------------------------------------------
Why this uses `pdftotext -layout` (a subprocess call) instead of pdfplumber
------------------------------------------------------------------------
The original project brief called for pdfplumber page-by-page extraction.
Tested directly against the Aug 15, 2026 Saratoga fixture, pdfplumber's
`page.extract_text()` badly scrambles the dense multi-column header box at
the top of each horse's entry (name/sire/dam/breeder/jockey-trainer/lifetime
stats grid) - it interleaves characters from adjacent columns because that
box packs several narrow columns very close together and pdfplumber's
word-sorting heuristic doesn't recover the intended reading order there.

`pdftotext -layout` (Poppler's CLI, already available on this environment)
preserves column alignment via whitespace padding and handles the same box
correctly for every field except the LIFE/2026/2025/SAR/D.Fst/Wet/Synth/
Turf/Dst stat grid, which still fragments unpredictably because its exact
column positions shift slightly per horse (driven by digit count in the
dollar figures).

Update: that remaining stat-grid fragmentation turned out to be a
pdftotext-specific text-serialization artifact, not genuinely ambiguous
data - see `parser/stat_grid.py`, which reads that one field via
pdfplumber's word bounding boxes instead (confirmed directly against the
fixture: a "Life" label and its own $earnings/speed figure sit at the
*exact same* y-position, pdftotext just emits them on different output
lines because of a row-height mismatch between two side-by-side tables).
So pdfplumber IS wired into the main pipeline as of this session, but only
for that one field - `pdftotext -layout` remains the primary extraction
backend for everything else (identity/connections/breeding/PP lines),
which it still handles better than pdfplumber's own `extract_text()` (see
above). `extract_with_pdfplumber` below (whole-page text, not word boxes)
remains available as a document-level fallback/cross-check if a future DRF
export changes format and pdftotext -layout stops working well overall.
------------------------------------------------------------------------
"""

from __future__ import annotations

import subprocess
import shutil


class ExtractionError(Exception):
    pass


def extract_layout_text(pdf_path: str) -> str:
    """
    Runs `pdftotext -layout` over the whole PDF and returns the combined
    text (page breaks preserved as form-feed \\x0c characters, which is
    Poppler's default and useful for splitting back into pages later).
    """
    if shutil.which("pdftotext") is None:
        raise ExtractionError(
            "pdftotext (Poppler) is not available in this environment. "
            "Install poppler-utils, or add a pdfplumber-based fallback."
        )
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError(f"pdftotext timed out on {pdf_path}") from exc

    if result.returncode not in (0,):
        # pdftotext can emit non-fatal warnings on stderr (seen on this
        # fixture: "Unknown compression method in flate stream") while
        # still producing usable stdout - only treat it as fatal if stdout
        # is empty.
        if not result.stdout.strip():
            raise ExtractionError(
                f"pdftotext failed on {pdf_path}: {result.stderr.strip()}"
            )
    return result.stdout


def split_pages(layout_text: str) -> list[str]:
    """Splits pdftotext's form-feed-delimited output into a list of pages."""
    return layout_text.split("\x0c")


def extract_with_pdfplumber(pdf_path: str) -> list[str]:
    """
    Fallback / cross-check path. NOT used by the main pipeline (see module
    docstring) - kept available in case a future DRF export layout works
    better with pdfplumber than with pdftotext -layout, or for spot-checking
    coordinates (e.g. to verify text centering) the way earlier iterations
    of this project used pdfplumber's bounding-box data.
    """
    import pdfplumber

    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    return pages_text
