# Project Brief: DRF Large-Print Racing Form Converter

## 1. Goal

A simple web app where the user uploads a Daily Racing Form (DRF) past-performance PDF for
a race card and downloads a reformatted, large-print PDF ("Format B2") — the same layout
validated by hand on the Saratoga 8/15/2026 card in earlier chat sessions. Primary user is a
low-vision horseplayer (grandfather); the builder (grandson) sets it up and maintains it.

**Core flow:** Upload PDF → app parses it → app generates the large-print PDF → user
downloads it. No login, no stored data beyond the current session, no batch processing needed
for v1.

## 2. Recommended architecture

- **Framework:** Streamlit (Python). A single-page app with `st.file_uploader` for the input
  PDF and `st.download_button` for the generated output.
- **PDF text extraction:** originally speced as `pdfplumber`; in practice `pdftotext -layout`
  (Poppler) works much better on this fixture — see README.md for why.
- **Parsing:** Rule-based (regex + heuristics), NOT an LLM call per PDF. Rules should be
  written defensively so minor formatting drift across different tracks'/dates' PDFs doesn't
  hard-crash the app — degrade gracefully instead.
- **PDF generation:** `reportlab` (Platypus: `Table`, `Paragraph`, `KeepTogether`), matching
  the exact visual spec in §5.
- **Hosting:** Streamlit Community Cloud (free tier), connected to a GitHub repo.

## 3. Repo structure

See README.md — the structure below was implemented as described.

```
drf-largeprint/
  app.py
  parser/
    extract.py
    race_header.py
    horse_entry.py
    past_performances.py
    normalize.py
  generator/
    build_pdf.py
    styles.py
  tests/
    fixtures/
```

## 4. Parsing requirements

### 4.1 What to extract per race
Race number, post time, distance, surface (dirt/turf), race type & conditions string, purse.

### 4.2 What to extract per horse
Post/program number, horse name, morning-line odds, weight; jockey + current-year stats;
trainer + current-year stats; sire (with damsire), dam (with broodmare sire), breeder +
state/country; condensed stat line (LIFE, current year, at today's track, and SURF matching
today's surface); scratched flag (collapsed line); first-time starters (zeros + note instead
of table).

### 4.3 What to extract per past-performance line (up to 5, most recent first)
Date, track, distance, race type/conditions, final time (not fractional splits), speed
figure, surface, condition (mapped from source abbreviation), a SHORT (2-5 word) RAN
trip/position summary (not the verbose DRF comment), and finish position.

### 4.4 Robustness expectations
Handle both US and foreign (GB, Ire, UAE, France) PP line formats gracefully, omitting fields
that aren't available (e.g. foreign lines lack DRF speed figures/trainer stats). Tolerate
missing/malformed individual fields on a single PP line without failing the whole horse or
document. Not expected to handle a fundamentally different publisher's chart format. Log/
collect unparseable entries so the app can show an "N entries had incomplete data" notice.

## 5. Output PDF spec ("Format B2")

### 5.1 Cover
Track-colored banner, white bold title ("[Track Name] — Large-Print Racing Form"), gold
divider line, subtitle with the card's date.

### 5.2 Per-race header
Line 1 (bold, large): "RACE N" left-aligned, "Post [time] ET" right-aligned. Line 2 (smaller,
white): distance · race type & conditions · surface · purse, separated by middot bullets.

### 5.3 Per-horse block
1. Name row: `#N Name` (bold, green) left; `ML X-1` (bold, black) right; thin gold rule below.
2. Connections line: Jockey — year stats | Trainer — year stats.
3. Breeding line: Sire / Dam / Breeder.
4. Condensed stats line (bold): LIFE / current-year / at-track / SURF, each s-w-p-s, earnings,
   avg speed figure.
5. Past-performances table (green header, alternating shading): DATE | TRK | DIST | RACE TYPE
   | TIME | FIG | SURF | COND | RAN | FINISH — up to 5 rows, most recent first. Italic note if
   no prior races.
6. Thin gray divider, then spacing before the next horse.

### 5.4 Scratched horses
Single red bar, white bold text: `#N Name` left, `SCRATCHED` center, `ML X-1` right.

### 5.5 General layout rules
Multiple horses per page (compact, information-dense but legible). `KeepTogether` per horse
block. Large body text (~10.5-15pt depending on element). Track-agnostic `THEME_COLOR` config
(Saratoga green #0B3D2E / gold #B8860B / white by default).

## 6. Error handling & UX details
Clear in-app message (not a stack trace) for unparseable PDFs or zero races found. Generate
the PDF for everything that did parse even if some horses/fields failed, with a warning
listing what was skipped/incomplete. Progress indicator while parsing/generating. Downloaded
filename reflects track and date when extractable, falling back to a generic name.

## 7. Testing plan
Saratoga 8/15/2026 card (12 races: maidens, claiming, allowance, a Grade I with foreign
entries, one scratch) as the primary fixture. Spot-check race header formatting, a horse with
5 PP lines, a horse with 0 PP lines, a scratched horse, a foreign-bred stakes horse. Visual QA
by rendering output to images (`pdftoppm`/`pdf2image`) and reviewing for column overflow.

## 8. Non-goals for v1
No accounts/login, no batch upload, no in-app editing of scratches/odds, no non-DRF layouts,
no mobile-specific UI tuning beyond Streamlit defaults.

## 9. Stretch goals (post-v1)
Toggle PP line count (3 vs 5) and font size from the UI. Additional track themes. A
black-and-white print-friendly mode. Cache/remember recent conversions in-session.
