"""A fictional homeowners policy for the demo (Golden Poppy Mutual does not exist), as a text PDF the Policy
agent can read. Run: uv run python -m scripts.sample_policy  ->  frontend/public/samples/"""

from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "samples" / "golden-poppy-homeowners-policy.pdf"

DECLARATIONS = [
    ("Named insured", "Elena Rivera"),
    ("Residence premises", "214 Juniper Lane, Sablewood, CA 95999"),
    ("Policy number", "GPM-HO3-4471-2026"),
    ("Policy period", "January 15, 2026 to January 15, 2027, 12:01 a.m. standard time"),
    ("Form", "HO-3 Special Form homeowners policy"),
    ("Coverage A - Dwelling", "$485,000 (extended replacement cost: up to 25% more)"),
    ("Coverage B - Other Structures", "$48,500"),
    ("Coverage C - Personal Property", "$242,500 (replacement cost)"),
    ("Coverage D - Loss of Use", "$97,000 (additional living expense, up to 24 months)"),
    ("Coverage E - Personal Liability", "$300,000 each occurrence"),
    ("Coverage F - Medical Payments", "$5,000 each person"),
    ("Deductible (all perils, including wildfire)", "$2,500"),
]

SECTIONS = [
    (
        "SECTION I - PROPERTY COVERAGES: SPECIAL LIMITS OF LIABILITY (COVERAGE C)",
        "The special limit for each category below is the total limit for each loss for all property in that "
        "category. These limits do not increase the Coverage C limit. a. $200 on money, bank notes, coins and "
        "gift cards. b. $1,500 on securities, accounts, deeds, passports and tickets. c. $1,500 on watercraft, "
        "including their trailers and outboard motors. d. $2,500 for loss of jewelry, watches, furs, precious "
        "and semiprecious stones, by any covered peril including fire. e. $2,500 for loss by theft of firearms. "
        "f. $2,500 for loss of silverware, goldware and pewterware. g. $2,500 on property used for business "
        "purposes on the residence premises. h. $1,500 on electronic apparatus while in a motor vehicle.",
    ),
    (
        "SECTION I - CONDITIONS: LOSS SETTLEMENT",
        "Covered property losses are settled as follows. Personal property is paid at replacement cost without "
        "deduction for depreciation. Until the property is actually repaired or replaced, we pay the actual cash "
        "value, and the difference when replacement is made. Following a loss related to a state of emergency, "
        "you have no less than 36 months from the first payment to repair, rebuild or replace and collect the "
        "full replacement cost. The dwelling is settled at replacement cost up to the Coverage A limit plus the "
        "extended replacement cost percentage shown in the Declarations.",
    ),
    (
        "SECTION I - CONDITIONS: DUTIES AFTER LOSS",
        "In case of a loss to covered property, you must see that the following are done: a. Give prompt notice "
        "to us or our agent. b. Protect the property from further damage. c. Prepare an inventory of damaged "
        "personal property showing the quantity, description, actual cash value and amount of loss, with bills, "
        "receipts and related documents that justify the figures. d. Send to us, within 60 days after our request, "
        "your signed, sworn proof of loss. For a total loss of the dwelling related to a state of emergency, we "
        "will accept an inventory that groups categories of personal property and will offer an advance payment "
        "for living expenses and contents without an itemized inventory.",
    ),
    (
        "SECTION I - CONDITIONS: LOSS OF USE AND SUIT AGAINST US",
        "Additional living expense is paid for the shortest time required to repair or replace the damage or, "
        "if you permanently relocate, the shortest time for your household to settle elsewhere, up to 24 months, "
        "with extensions of up to 12 more months for delays caused by a state of emergency. No action can be "
        "brought against us unless there has been full compliance with all the terms of this policy and the "
        "action is started within 24 months after the date of loss when the loss is related to a state of "
        "emergency, otherwise within 12 months after the date of loss.",
    ),
]


def build() -> bytes:
    pdf = FPDF(format="Letter")
    pdf.set_margins(20, 18, 20)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, "Golden Poppy Mutual Insurance Company", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(
        0, 5, "A fictional insurer for the Hearthline demo. This is not a real policy.", new_x="LMARGIN", new_y="NEXT"
    )
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "HOMEOWNERS POLICY DECLARATIONS", new_x="LMARGIN", new_y="NEXT")
    for label, value in DECLARATIONS:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(72, 7, label, border="B")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, value, border="B", new_x="LMARGIN", new_y="NEXT")
    for title, body in SECTIONS:
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5.2, body, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(build())
    print("wrote", OUT)
