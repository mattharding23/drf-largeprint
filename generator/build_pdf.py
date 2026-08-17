"""
Format B2 generator.

This module knows nothing about parsing DRF PDFs — it only knows how to
turn already-structured data into the large-print PDF laid out in project
brief section 5. Keeping it decoupled from parser/ means it can be built
and tested (and rendered to images for visual QA per section 7) without a
working parser.

------------------------------------------------------------------------
Expected input shape
------------------------------------------------------------------------
card = {
    "track_name": "Saratoga",
    "date_str": "August 15, 2026",
    "races": [ race, ... ],
    "incomplete_notes": [ "Race 3 #7: could not parse trainer stats", ... ],
}

race = {
    "num": 1,
    "post_time": "12:30 ET",
    "distance": "6 Furlongs",
    "race_type": "Claiming $30,000-$35,000 (N3L) \u00b7 3YO & Up",
    "surface": "Dirt",
    "purse": "$54,000",
    "horses": [ horse, ... ],
}

horse = {
    "num": 1,
    "name": "Epitaph",
    "ml": "8-1",
    "scratched": False,
    "first_time_starter": False,

    "jockey": "Zayas E J",
    "jockey_stats": "2026: 573 starts, 76 wins (13%)",   # or None
    "trainer": "Potts Wayne",
    "trainer_stats": "2026: 195 starts, 23 wins (12%)",  # or None

    "sire": "Country House (Lookin At Lucky)",
    "dam": "Barb's On Edge (Into Mischief)",
    "breeder": "NK Racing (NY)",

    "life": "20-2-4-2, $137,245, spd 74",
    "year": "6-0-2-0, $22,275, spd 71",
    "track_stat": "1-0-1-0, $8,600, spd 67",
    "track_label": "SAR",
    "surf_label": "Dirt",
    "surf_stat": "8-1-3-0, $39,070, spd 71",

    "pp_lines": [
        {
            "date": "23Jul26", "track": "Sar", "dist": "6f",
            "race_type": "Clm 25000N3L", "time": "1:10", "fig": "67",
            "surf": "Dirt", "cond": "Fast",
            "ran": "Pressed pace, led, caught late",
            "finish": "2nd of 10",
        },
        ...
    ],
}

Any field can be missing/None; missing display fields render as blanks or
graceful fallback text rather than raising.
"""

from __future__ import annotations

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    KeepTogether, HRFlowable, PageBreak, NextPageTemplate,
)
from reportlab.lib import colors

from generator.styles import get_theme, build_styles

PAGE_MARGIN = 0.55 * inch
CONTENT_WIDTH = LETTER[0] - 2 * PAGE_MARGIN

PP_COL_LABELS = ["DATE", "TRK", "DIST", "RACE TYPE", "TIME", "FIG", "SURF", "COND", "RAN", "FINISH"]
# Widths sum to CONTENT_WIDTH; RAN and RACE TYPE get the most room since
# they carry the longest text. TRK was originally sized for short US
# abbreviations (Sar, BAQ, Aqu) - too narrow for foreign PP lines' "Name
# (Country)" tracks (e.g. "Longchamp (Fr)", "Newmarket (GB)"), which
# doesn't just wrap sooner but wraps *mid-word* (ReportLab falls back to
# character-level breaking when a single space-delimited word can't fit
# the column at all - see the 2026-08-17 bug report). Widened enough for
# "Longchamp"/"Newmarket" (the two longest single words seen in this
# fixture, ~50pt at this font size) to fit as one unbroken word, borrowing
# a bit of slack from DATE/TIME/FINISH/RAN, none of which are anywhere
# near their own longest-content width at their current allocation.
PP_COL_WIDTHS_FRACTION = [0.09, 0.115, 0.06, 0.13, 0.06, 0.05, 0.07, 0.08, 0.245, 0.11]


def _safe(v, fallback="—"):
    if v is None or v == "":
        return fallback
    return str(v)


def _pp_table(pp_lines, styles, theme):
    widths = [f * CONTENT_WIDTH for f in PP_COL_WIDTHS_FRACTION]
    header = [Paragraph(h, styles["table_header"]) for h in PP_COL_LABELS]
    rows = [header]
    for pp in pp_lines[:5]:  # up to 5 most recent, most recent first
        rows.append([
            Paragraph(_safe(pp.get("date")), styles["table_cell"]),
            Paragraph(_safe(pp.get("track")), styles["table_cell"]),
            Paragraph(_safe(pp.get("dist")), styles["table_cell"]),
            Paragraph(_safe(pp.get("race_type")), styles["table_cell"]),
            Paragraph(_safe(pp.get("time")), styles["table_cell"]),
            Paragraph(_safe(pp.get("fig")), styles["table_cell"]),
            Paragraph(_safe(pp.get("surf")), styles["table_cell"]),
            Paragraph(_safe(pp.get("cond")), styles["table_cell"]),
            Paragraph(_safe(pp.get("ran")), styles["table_cell"]),
            Paragraph(_safe(pp.get("finish")), styles["table_cell"]),
        ])

    t = Table(rows, colWidths=widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), theme["primary"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), theme["text_on_primary"]),
        ("GRID", (0, 0), (-1, -1), 0.5, theme["divider_gray"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), theme["row_shade"]))
        else:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), theme["row_shade_alt"]))
    t.setStyle(TableStyle(style_cmds))
    return t


def _horse_block(horse, styles, theme):
    flowables = []

    if horse.get("scratched"):
        bar = Table(
            [[
                Paragraph(f"#{horse.get('num', '?')} {_safe(horse.get('name'))}", styles["scratch_text"]),
                Paragraph("SCRATCHED", styles["scratch_text_center"]),
                Paragraph(f"ML {_safe(horse.get('ml'))}", styles["scratch_text_right"]),
            ]],
            colWidths=[CONTENT_WIDTH * 0.4, CONTENT_WIDTH * 0.3, CONTENT_WIDTH * 0.3],
        )
        bar.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), theme["scratch_red"]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        flowables.append(bar)
        flowables.append(Spacer(1, 10))
        return KeepTogether(flowables)

    # 1. Name row
    name_row = Table(
        [[
            Paragraph(f"#{horse.get('num', '?')} {_safe(horse.get('name'))}", styles["horse_name"]),
            Paragraph(f"ML {_safe(horse.get('ml'))}", styles["horse_ml"]),
        ]],
        colWidths=[CONTENT_WIDTH * 0.7, CONTENT_WIDTH * 0.3],
    )
    name_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    flowables.append(name_row)
    flowables.append(HRFlowable(width="100%", thickness=1.2, color=theme["accent"], spaceBefore=2, spaceAfter=5))

    # 2. Connections line
    jockey_stats = horse.get("jockey_stats") or "European rider — record not tabulated"
    trainer_stats = horse.get("trainer_stats") or "European stable — record not tabulated"
    connections = (
        f"Jockey: {_safe(horse.get('jockey'))} — {jockey_stats}"
        f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
        f"Trainer: {_safe(horse.get('trainer'))} — {trainer_stats}"
    )
    flowables.append(Paragraph(connections, styles["connections"]))

    # 3. Breeding line
    breeding = (
        f"Sire: {_safe(horse.get('sire'))}&nbsp;&nbsp;&nbsp;"
        f"Dam: {_safe(horse.get('dam'))}&nbsp;&nbsp;&nbsp;"
        f"Br: {_safe(horse.get('breeder'))}"
    )
    flowables.append(Paragraph(breeding, styles["breeding"]))
    flowables.append(Spacer(1, 3))

    # 4. Condensed stats line
    surf_label = horse.get("surf_label") or "Surf"
    track_label = horse.get("track_label") or "TRK"
    stats = (
        f"LIFE {_safe(horse.get('life'))}&nbsp;&nbsp;&nbsp;"
        f"2026 {_safe(horse.get('year'))}&nbsp;&nbsp;&nbsp;"
        f"{track_label} {_safe(horse.get('track_stat'))}&nbsp;&nbsp;&nbsp;"
        f"SURF {surf_label}: {_safe(horse.get('surf_stat'))}"
    )
    flowables.append(Paragraph(stats, styles["stat_line"]))
    flowables.append(Spacer(1, 4))

    # 5. Past performances table (or first-time-starter / data-gap note)
    pp_lines = horse.get("pp_lines") or []
    if horse.get("first_time_starter"):
        flowables.append(Paragraph("First-time starter — no prior races", styles["pp_note"]))
    elif not pp_lines:
        # Not actually a first-time starter (the LIFE line above may show
        # real prior starts) - the PP table just failed to parse. Saying
        # "first-time starter" here would be an actively wrong claim about
        # this horse's history, not just a missing field - see the
        # 2026-08-17 bug report (Decimation, race 8) for why this was
        # split out from the branch above. app.py's consistency check logs
        # a warning for this case when the LIFE line shows starts > 0.
        flowables.append(Paragraph("Past performance data unavailable", styles["pp_note"]))
    else:
        flowables.append(_pp_table(pp_lines, styles, theme))

    # 6. Divider + spacing before next horse
    flowables.append(Spacer(1, 6))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=theme["divider_gray"]))
    flowables.append(Spacer(1, 10))

    return KeepTogether(flowables)


def _race_header(race, styles, theme):
    line1 = Table(
        [[
            Paragraph(f"RACE {race.get('num', '?')}", styles["race_header_line1"]),
            Paragraph(f"Post {_safe(race.get('post_time'))}", styles["race_header_line1_right"]),
        ]],
        colWidths=[CONTENT_WIDTH * 0.5, CONTENT_WIDTH * 0.5],
    )
    line1.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    detail_bits = [b for b in [
        _safe(race.get("distance"), ""),
        _safe(race.get("race_type"), ""),
        _safe(race.get("surface"), ""),
        f"Purse {_safe(race.get('purse'), '')}" if race.get("purse") else "",
    ] if b]
    line2 = Paragraph(" &middot; ".join(detail_bits), styles["race_header_line2"])

    banner = Table([[line1], [line2]], colWidths=[CONTENT_WIDTH])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), theme["primary"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return banner


def _cover_page(card, styles, theme):
    flowables = []
    flowables.append(Spacer(1, 2.2 * inch))
    title = Table(
        [[Paragraph(f"{card.get('track_name', 'Track')} — Large-Print Racing Form", styles["cover_title"])]],
        colWidths=[CONTENT_WIDTH],
    )
    title.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), theme["primary"]),
        ("TOPPADDING", (0, 0), (-1, -1), 28),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    flowables.append(title)
    flowables.append(HRFlowable(width="100%", thickness=2, color=theme["accent"], spaceBefore=0, spaceAfter=14))
    flowables.append(Paragraph(_safe(card.get("date_str"), ""), styles["cover_subtitle"]))
    flowables.append(PageBreak())
    return flowables


def build_pdf(card: dict, output_path: str) -> str:
    """
    Renders `card` (see module docstring for shape) to a PDF at
    `output_path` and returns that path.
    """
    theme = get_theme(card.get("track_name"))
    styles = build_styles(theme)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=LETTER,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN,
        title=f"{card.get('track_name', 'Track')} Large-Print Racing Form",
    )

    story = []
    story.extend(_cover_page(card, styles, theme))

    for race in card.get("races", []):
        story.append(_race_header(race, styles, theme))
        story.append(Spacer(1, 8))
        for horse in race.get("horses", []):
            story.append(_horse_block(horse, styles, theme))
        story.append(Spacer(1, 4))

    doc.build(story)
    return output_path
