"""
Theme + typography for the Format B2 large-print racing form.

Kept track-agnostic on purpose (see project brief section 5.5): the person
running this may eventually feed in cards from tracks other than Saratoga,
so the color scheme is a swappable THEME dict rather than hardcoded values
sprinkled through the generator.
"""

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

# ---------------------------------------------------------------------------
# Theme (Saratoga green/gold/white is the default; override per-track later)
# ---------------------------------------------------------------------------

SARATOGA_THEME = {
    "name": "Saratoga",
    "primary": colors.HexColor("#0B3D2E"),   # deep racing green
    "accent": colors.HexColor("#B8860B"),    # gold
    "text_on_primary": colors.white,
    "scratch_red": colors.HexColor("#B22222"),
    "row_shade": colors.HexColor("#EAF1EC"),  # light green tint for zebra rows
    "row_shade_alt": colors.white,
    "divider_gray": colors.HexColor("#B8B8B8"),
    "body_text": colors.HexColor("#111111"),
}

# Default theme used when the caller doesn't specify one (keeps app.py simple)
THEME = SARATOGA_THEME


def get_theme(track_name: str | None = None) -> dict:
    """
    Track-agnostic hook: today only Saratoga's palette is defined, so we
    always return it, but callers should go through this function (rather
    than importing SARATOGA_THEME directly) so that adding a second track's
    theme later is a one-place change.
    """
    return SARATOGA_THEME


# ---------------------------------------------------------------------------
# Paragraph styles
# ---------------------------------------------------------------------------
# Font sizes are the values tuned by eye in the reference build (see project
# brief section 5.5) - roughly 10.5-15pt depending on element. Leading is set
# explicitly everywhere: reportlab defaults to 12pt leading regardless of font
# size, which causes large text to overflow its container if left unset.

def build_styles(theme: dict = THEME) -> dict:
    s = {}

    s["cover_title"] = ParagraphStyle(
        "cover_title", fontName="Helvetica-Bold", fontSize=28, leading=32,
        textColor=theme["text_on_primary"], alignment=TA_CENTER,
    )
    s["cover_subtitle"] = ParagraphStyle(
        # Renders below the title banner, on the page's white background -
        # theme["primary"] (not text_on_primary, which is white-on-purpose
        # for text *inside* the banner) so it's actually visible. Using
        # text_on_primary here rendered genuinely invisible white-on-white
        # text - see the 2026-08-17 bug report.
        "cover_subtitle", fontName="Helvetica", fontSize=15, leading=18,
        textColor=theme["primary"], alignment=TA_CENTER,
    )

    s["race_header_line1"] = ParagraphStyle(
        "race_header_line1", fontName="Helvetica-Bold", fontSize=15, leading=18,
        textColor=theme["text_on_primary"],
    )
    s["race_header_line1_right"] = ParagraphStyle(
        "race_header_line1_right", parent=s["race_header_line1"], alignment=TA_RIGHT,
        textColor=theme["accent"],
    )
    s["race_header_line2"] = ParagraphStyle(
        "race_header_line2", fontName="Helvetica", fontSize=11, leading=14,
        textColor=theme["text_on_primary"],
    )

    s["horse_name"] = ParagraphStyle(
        "horse_name", fontName="Helvetica-Bold", fontSize=14, leading=17,
        textColor=theme["primary"],
    )
    s["horse_ml"] = ParagraphStyle(
        "horse_ml", fontName="Helvetica-Bold", fontSize=13, leading=17,
        textColor=colors.black, alignment=TA_RIGHT,
    )
    s["connections"] = ParagraphStyle(
        "connections", fontName="Helvetica", fontSize=10.5, leading=13,
        textColor=theme["body_text"],
    )
    s["breeding"] = ParagraphStyle(
        "breeding", fontName="Helvetica", fontSize=10.5, leading=13,
        textColor=theme["body_text"],
    )
    s["stat_line"] = ParagraphStyle(
        "stat_line", fontName="Helvetica-Bold", fontSize=11, leading=14,
        textColor=theme["primary"],
    )
    s["pp_note"] = ParagraphStyle(
        "pp_note", fontName="Helvetica-Oblique", fontSize=11, leading=14,
        textColor=theme["body_text"],
    )
    s["table_header"] = ParagraphStyle(
        "table_header", fontName="Helvetica-Bold", fontSize=9.5, leading=12,
        textColor=theme["text_on_primary"],
    )
    s["table_cell"] = ParagraphStyle(
        "table_cell", fontName="Helvetica", fontSize=9.5, leading=12,
        textColor=theme["body_text"],
    )

    s["scratch_text"] = ParagraphStyle(
        "scratch_text", fontName="Helvetica-Bold", fontSize=14, leading=17,
        textColor=colors.white,
    )
    s["scratch_text_center"] = ParagraphStyle(
        "scratch_text_center", parent=s["scratch_text"], alignment=TA_CENTER,
    )
    s["scratch_text_right"] = ParagraphStyle(
        "scratch_text_right", parent=s["scratch_text"], alignment=TA_RIGHT,
    )

    return s
