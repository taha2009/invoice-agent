import os
import tempfile
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.config import settings

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm

BLUE = colors.HexColor("#1F3864")
BLACK = colors.black
LIGHT_GREY = colors.HexColor("#F2F2F2")

styles = getSampleStyleSheet()

_h1 = ParagraphStyle(
    "AdvocateName",
    fontName="Times-Bold",
    fontSize=16,
    textColor=BLUE,
    leading=20,
)
_h2 = ParagraphStyle(
    "Designation",
    fontName="Times-Roman",
    fontSize=10,
    textColor=BLACK,
    leading=14,
)
_addr = ParagraphStyle(
    "Address",
    fontName="Times-Roman",
    fontSize=9,
    textColor=BLACK,
    leading=13,
)
_invoice_title = ParagraphStyle(
    "InvoiceTitle",
    fontName="Helvetica-Bold",
    fontSize=11,
    textColor=BLACK,
    alignment=1,  # centre
    leading=14,
    spaceAfter=6,
)
_label = ParagraphStyle(
    "Label",
    fontName="Helvetica",
    fontSize=9,
    textColor=BLACK,
    leading=13,
)
_label_right = ParagraphStyle(
    "LabelRight",
    fontName="Helvetica",
    fontSize=9,
    textColor=BLACK,
    leading=13,
    alignment=0,  # left within right column so D/I start together
)
_section_heading = ParagraphStyle(
    "SectionHeading",
    fontName="Helvetica-Bold",
    fontSize=9,
    textColor=BLACK,
    leading=13,
    spaceBefore=8,
    spaceAfter=3,
)
_bank = ParagraphStyle(
    "Bank",
    fontName="Helvetica",
    fontSize=9,
    textColor=BLACK,
    leading=13,
)
_bank_bold = ParagraphStyle(
    "BankBold",
    fontName="Helvetica-Bold",
    fontSize=9,
    textColor=BLACK,
    leading=13,
    spaceAfter=2,
)
_footer = ParagraphStyle(
    "Footer",
    fontName="Helvetica",
    fontSize=8,
    textColor=BLACK,
    alignment=1,
    leading=11,
)


def _fmt(amount: float) -> str:
    """Format a number as Indian comma-separated integer string."""
    return f"{int(amount):,}"


def _money_or_dash(amount: float) -> str:
    return "-" if amount == 0 else _fmt(amount)


def _col_widths(available: float, left_frac: float = 0.75) -> list[float]:
    left = available * left_frac
    return [left, available - left]


def _table_style(total_rows: int) -> TableStyle:
    """Standard style: header row shaded, total row bold, borders."""
    return TableStyle(
        [
            # Header row
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GREY),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            # All rows
            ("FONTNAME", (0, 1), (-1, -2), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            # Total row (last row)
            ("FONTNAME", (0, total_rows - 1), (-1, total_rows - 1), "Helvetica-Bold"),
            ("TOPPADDING", (0, total_rows - 1), (-1, total_rows - 1), 4),
            # Grid
            ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ]
    )


def generate_pdf(
    *,
    invoice_number: str,
    invoice_date: str,
    client: str,
    client_address: str,
    attention: str,
    professional_fees: list[dict],
    disbursements: list[dict],
    professional_fees_total: float,
    disbursements_total: float,
    advance_paid: float,
    total_payable: float,
) -> str:
    """
    Build the invoice PDF and write it to a named temp file.
    Returns the temp file path (caller is responsible for deletion).
    """
    safe_prefix = settings.invoice_prefix.replace("/", "-")
    seq = invoice_number.split("/")[-1]
    filename = f"invoice_{safe_prefix}_{seq}.pdf"

    tmp = tempfile.NamedTemporaryFile(
        suffix=".pdf", prefix=f"invoice_{safe_prefix}_{seq}_", delete=False
    )
    tmp_path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(
        tmp_path,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    available = PAGE_W - 2 * MARGIN
    story = []

    # ── Header ──────────────────────────────────────────────────────────────
    name_col = [
        Paragraph(settings.issuer_name, _h1),
        Paragraph(settings.issuer_designation, _h2),
    ]
    addr_lines = (
        f"{settings.issuer_address.replace(chr(10), '<br/>')}<br/>"
        f"Phone: {settings.issuer_phone}<br/>"
        f'Email: <font color="blue"><u>{settings.issuer_email}</u></font>'
    )
    addr_col = [Paragraph(addr_lines, _addr)]

    header_table = Table(
        [[name_col, "", addr_col]],
        colWidths=[available * 0.45, available * 0.18, available * 0.37],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BLACK))
    story.append(Spacer(1, 4 * mm))

    # ── INVOICE title ───────────────────────────────────────────────────────
    story.append(Paragraph("INVOICE", _invoice_title))
    story.append(Spacer(1, 3 * mm))

    # ── Client / Date block ─────────────────────────────────────────────────
    client_left = (
        f"<b>Client:</b>      {client}<br/><br/>"
        f"<b>Address:</b>  {client_address.replace(chr(10), '<br/>')}<br/><br/>"
        + (f"<b>Attention:</b> {attention}" if attention else "")
    )
    try:
        display_date = datetime.strptime(invoice_date, "%Y-%m-%d").strftime("%d %B %Y")
    except ValueError:
        display_date = invoice_date
    date_right = f"Date: {display_date}<br/><br/>Invoice No. {invoice_number}"

    client_table = Table(
        [[Paragraph(client_left, _label), Paragraph(date_right, _label_right)]],
        colWidths=[available * 0.6, available * 0.4],
    )
    client_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(client_table)
    story.append(Spacer(1, 5 * mm))

    # ── Section A — Professional Fee ────────────────────────────────────────
    story.append(Paragraph("A.  PROFESSIONAL FEE", _section_heading))
    cw = _col_widths(available)
    fee_data = [["Description", "Amount (INR)"]]
    for item in professional_fees:
        fee_data.append([item["description"], _fmt(item["amount"])])
    fee_data.append(["Total Professional Fee:", _fmt(professional_fees_total)])
    fee_table = Table(fee_data, colWidths=cw)
    fee_table.setStyle(_table_style(len(fee_data)))
    story.append(fee_table)
    story.append(Spacer(1, 4 * mm))

    # ── Section B — Disbursements ───────────────────────────────────────────
    story.append(Paragraph("B.  DISBURSEMENTS", _section_heading))
    disb_data = [["Description", "Amount (INR)"]]
    for item in disbursements:
        disb_data.append([item["description"], _fmt(item["amount"])])
    disb_data.append(["Total Disbursements:", _fmt(disbursements_total)])
    disb_table = Table(disb_data, colWidths=cw)
    disb_table.setStyle(_table_style(len(disb_data)))
    story.append(disb_table)
    story.append(Spacer(1, 4 * mm))

    # ── Section C — Total Summary ───────────────────────────────────────────
    story.append(Paragraph("C.  TOTAL SUMMARY", _section_heading))
    summary_data = [
        ["Description", "Amount (INR)"],
        [
            "Subtotal (Professional Fees + Disbursement)",
            _fmt(professional_fees_total + disbursements_total),
        ],
        ["Less: Advance Paid", _money_or_dash(advance_paid)],
        ["Total Amount Payable", _fmt(total_payable)],
    ]
    summary_table = Table(summary_data, colWidths=cw)
    summary_table.setStyle(_table_style(len(summary_data)))
    story.append(summary_table)
    story.append(Spacer(1, 6 * mm))

    # ── Bank Details ────────────────────────────────────────────────────────
    bank_text = (
        f"Beneficiary Name: {settings.bank_beneficiary}<br/>"
        f"Bank Name: {settings.bank_name}<br/>"
        f"A/c. Type: {settings.bank_ac_type}<br/>"
        f"A/c. Number: {settings.bank_ac_number}<br/>"
        f"IFSC Code: {settings.bank_ifsc}"
    )

    if settings.issuer_signature_path and os.path.exists(
        settings.issuer_signature_path
    ):
        sig_img = Image(settings.issuer_signature_path, width=30 * mm, height=15 * mm)
        sig_block = [sig_img, Paragraph(settings.issuer_name, _bank)]
    else:
        sig_block = [
            Spacer(1, 15 * mm),
            Paragraph(settings.issuer_name, _bank),
        ]

    bank_sig_table = Table(
        [
            [
                [
                    Paragraph("<b>Bank Details:</b>", _bank_bold),
                    Paragraph(bank_text, _bank),
                ],
                sig_block,
            ]
        ],
        colWidths=[available * 0.6, available * 0.4],
    )
    bank_sig_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(bank_sig_table)
    story.append(Spacer(1, 8 * mm))

    # ── Footer ───────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.grey))
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            "NOTE: This invoice is exclusive of GST.  "
            "GST shall be payable by you on reverse charge basis, as applicable",
            _footer,
        )
    )

    doc.build(story)
    return tmp_path, filename
