"""The evidence pack sent to PayPal with a dispute response: Hearthline's records for the payment, as a PDF."""

from fpdf import FPDF

from app.disputes import REASONS, Records, day, money
from app.grant_pdf import EMBER, INK, LINE, SOFT, _t
from app.models import PaymentDispute, now


def build(d: PaymentDispute, rec: Records, note: str) -> bytes:
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    pdf.set_text_color(*EMBER)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, _t("HEARTHLINE  |  RECORDS FOR A PAYPAL DISPUTE"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 8, _t(rec.subject), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*SOFT)
    byline = (
        f"Dispute {d.paypal_dispute_id}  |  {REASONS.get(d.reason, d.reason)}  |  {money(d.amount)}  |  "
        f"Prepared {day(now())}"
    )
    pdf.multi_cell(0, 5, _t(byline), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*INK)
    pdf.cell(0, 8, "Our response", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10.5)
    pdf.multi_cell(0, 5.4, _t(note), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "What our records show", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*LINE)
    for label, value in rec.facts:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*SOFT)
        pdf.cell(36, 6.5, _t(label))
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 6.5, _t(value), new_x="LMARGIN", new_y="NEXT")
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())  # one rule under the whole row
    pdf.ln(3)

    if rec.timeline:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Timeline", new_x="LMARGIN", new_y="NEXT")
        for at, what in rec.timeline:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*SOFT)
            pdf.cell(36, 6, _t(day(at)))
            pdf.set_text_color(*INK)
            pdf.multi_cell(0, 6, _t(what), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    if rec.tracking:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Shipment", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for t in rec.tracking:
            pdf.cell(0, 6, _t(f"{t['carrier_name']} {t['tracking_number']}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*SOFT)
    pdf.multi_cell(
        0,
        4.5,
        _t(
            "Figures come from Hearthline's double-entry ledger and tamper-evident audit log. Families' addresses "
            "and other private details are left out on purpose."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    return bytes(pdf.output())
