"""The grant report as a PDF: numbers from code, narrative from the Funds agent (or a template)."""

from decimal import Decimal

from fpdf import FPDF

from app.impact import Narrative

INK, SOFT, EMBER, SAGE, LINE = (31, 26, 23), (91, 82, 75), (194, 65, 12), (47, 125, 79), (231, 224, 215)
# The built-in PDF fonts only cover Latin-1; swap the few typographic characters AI text tends to use.
PLAIN = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "..."})


def _t(text: str) -> str:
    return text.translate(PLAIN).encode("latin-1", "replace").decode("latin-1")


def _money(v: Decimal | float) -> str:
    return f"${Decimal(str(v)):,.0f}"


SECTIONS = [
    (
        "Households",
        [
            ("Households registered", "households_registered", "n"),
            ("Homes destroyed", "homes_destroyed", "n"),
            ("Verified for cash aid (level 2+)", "households_verified", "n"),
            ("Help received so far", "help_received_total", "$"),
            ("Still needed", "still_needed_total", "$"),
        ],
    ),
    (
        "Cash aid and gifts",
        [
            ("Cash aid paid", "cash_aid_paid", "$"),
            ("Households that received cash aid", "cash_aid_households", "n"),
            ("Batches sent (two-person approved)", "aid_batches_sent", "n"),
            ("Registry gifts", "registry_gifts", "n"),
            ("Registry gifts total", "registry_gifts_total", "$"),
            ("Items bought by the Shopper", "items_bought", "n"),
            ("Items delivered", "items_delivered", "n"),
        ],
    ),
    (
        "Safeguards",
        [
            ("Cases decided by human reviewers", "cases_reviewed", "n"),
            ("Cases rejected (fraud or not eligible)", "cases_rejected", "n"),
            ("Offers refused for price gouging", "gouging_offers_refused", "n"),
            ("Prices tracked / over the legal limit", ("prices_tracked", "prices_over_limit"), "pair"),
        ],
    ),
    (
        "Rebuild and reopen",
        [
            ("Contractor milestones paid from escrow", "contractor_milestones_paid", "n"),
            ("Reopen Funds", "reopen_funds", "n"),
            ("Raised through gift cards", "reopen_raised", "$"),
            ("Released to businesses", "reopen_released_to_businesses", "$"),
            ("Refunded to buyers (missed reopening date)", "reopen_refunded_to_buyers", "$"),
            ("Crew jobs done / scheduled", ("crew_jobs_done", "crew_jobs_scheduled"), "pair"),
        ],
    ),
]


def _value(numbers: dict, key, kind: str) -> str:
    if kind == "pair":
        a, b = key
        return f"{numbers[a]:,} / {numbers[b]:,}"
    return _money(numbers[key]) if kind == "$" else f"{numbers[key]:,}"


def build(numbers: dict, narrative: Narrative, prepared_by: str, by_ai: bool) -> bytes:
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    pdf.set_text_color(*EMBER)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, _t("HEARTHLINE  |  RESPONSE REPORT"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 20)
    pdf.multi_cell(0, 9, _t(narrative.headline), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*SOFT)
    byline = (
        f"{numbers['disaster']}, declared {numbers['declared']}  |  "
        f"Report date {numbers['report_date']}  |  Prepared by {prepared_by}"
    )
    pdf.cell(0, 6, _t(byline), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "", 11)
    for paragraph in narrative.paragraphs:
        pdf.multi_cell(0, 5.6, _t(paragraph), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*SOFT)
    pdf.multi_cell(
        0,
        4.5,
        _t(
            (
                "Narrative drafted by Hearthline's Funds agent from the figures below and reviewed by staff. "
                if by_ai
                else ""
            )
            + "Every figure is computed from Hearthline's double-entry ledger and records."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    # Help by source, as simple bars.
    sources = [
        ("Cash aid", numbers["cash_aid_paid"]),
        ("Registry gifts", numbers["registry_gifts_total"]),
        ("Reopen gift cards", numbers["reopen_raised"]),
    ]
    top = max([float(v) for _, v in sources] + [1.0])
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*INK)
    pdf.cell(0, 8, "Money raised and paid, by channel", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for label, value in sources:
        y = pdf.get_y()
        pdf.set_text_color(*SOFT)
        pdf.cell(42, 7, _t(label))
        width = max(1.0, 110 * float(value) / top)
        pdf.set_fill_color(*EMBER)
        pdf.rect(pdf.get_x(), y + 1.5, width, 4, style="F")
        pdf.set_x(pdf.get_x() + width + 2)
        pdf.set_text_color(*INK)
        pdf.cell(0, 7, _money(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    for title, rows in SECTIONS:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*INK)
        pdf.cell(0, 8, _t(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*LINE)
        for label, key, kind in rows:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*SOFT)
            pdf.cell(120, 6.5, _t(label), border="B")
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*INK)
            pdf.cell(0, 6.5, _t(_value(numbers, key, kind)), border="B", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    if numbers.get("fictional_demo_data"):
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*SAGE)
        pdf.multi_cell(
            0,
            4.5,
            _t("Fictional town, people and figures (demo). Payments ran in the PayPal sandbox."),
            new_x="LMARGIN",
            new_y="NEXT",
        )
    return bytes(pdf.output())
