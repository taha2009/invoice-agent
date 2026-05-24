import gspread
from google.auth import default

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADERS = [
    "Invoice No.",
    "Invoice Date",
    "Client",
    "Client Address",
    "Attention",
    "Matter",
    "Professional Fees",
    "Disbursements Breakdown",
    "Disbursements",
    "Advance Paid",
    "Total",
    "Payment Date",
    "Payment Mode",
    "Amount Paid",
    "Remarks",
]


def get_sheet() -> gspread.Worksheet:
    creds, _ = default(scopes=SCOPES)
    client = gspread.Client(auth=creds)
    spreadsheet = client.open_by_key(settings.google_sheet_id)
    tab = settings.invoice_prefix
    try:
        return spreadsheet.worksheet(tab)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=tab, rows=1000, cols=len(HEADERS))


def _breakdown(items: list[dict]) -> str:
    return "\n".join(f"{i['description']}: {i['amount']}" for i in items)


def _to_row(data: dict) -> list:
    return [
        data["invoice_number"],
        data["invoice_date"],
        data["client"],
        data["client_address"],
        data["attention"],
        _breakdown(data.get("professional_fees", [])),
        data["professional_fees_total"],
        _breakdown(data.get("disbursements", [])),
        data["disbursements_total"],
        data["advance_paid"],
        data["total_payable"],
        "",  # Payment Date
        "",  # Payment Mode
        "",  # Amount Paid
        data.get("remarks", ""),
    ]


def _ensure_headers(sheet: gspread.Worksheet) -> None:
    """Write header row if the sheet is blank."""
    if not sheet.row_values(1):
        sheet.append_row(HEADERS)


def next_invoice_number(sheet: gspread.Worksheet) -> str:
    _ensure_headers(sheet)
    prefix = settings.invoice_prefix
    col_a = sheet.col_values(1)[1:]  # skip header
    matching = [v for v in col_a if v.startswith(f"{prefix}/")]
    seq = int(matching[-1].split("/")[-1]) + 1 if matching else 1
    return f"{prefix}/{seq}"


def get_invoice(sheet: gspread.Worksheet, invoice_number: str) -> dict | None:
    """Return the row for invoice_number as a dict, or None if not found."""
    col_a = sheet.col_values(1)
    try:
        row_idx = col_a.index(invoice_number) + 1
    except ValueError:
        return None
    row = sheet.row_values(row_idx)
    row += [""] * (len(HEADERS) - len(row))
    return dict(zip(HEADERS, row))


def upsert_invoice(sheet: gspread.Worksheet, data: dict) -> None:
    """Insert or update an invoice row, keyed on invoice_number."""
    _ensure_headers(sheet)
    row_values = _to_row(data)
    col_a = sheet.col_values(1)
    end_col = chr(ord("A") + len(row_values) - 1)
    try:
        row_idx = col_a.index(data["invoice_number"]) + 1  # 1-based
        sheet.update(f"A{row_idx}:{end_col}{row_idx}", [row_values])
    except ValueError:
        sheet.append_row(row_values)


def record_payment(
    sheet: gspread.Worksheet,
    invoice_number: str,
    payment_date: str,
    payment_mode: str,
) -> dict:
    """Record payment for an invoice. Returns the amount paid (total_payable from the row)."""
    col_a = sheet.col_values(1)
    try:
        row_idx = col_a.index(invoice_number) + 1
    except ValueError:
        raise ValueError(f"Invoice {invoice_number} not found.")

    row = sheet.row_values(row_idx)
    row += [""] * (len(HEADERS) - len(row))
    data = dict(zip(HEADERS, row))

    total_payable_str = data.get("Total", "0").replace(",", "")
    try:
        amount_paid = float(total_payable_str)
    except ValueError:
        amount_paid = 0.0

    payment_end_col = chr(ord("A") + HEADERS.index("Amount Paid"))
    payment_start_col = chr(ord("A") + HEADERS.index("Payment Date"))

    sheet.update(
        f"{payment_start_col}{row_idx}:{payment_end_col}{row_idx}",
        [[payment_date, payment_mode, int(amount_paid)]],
    )
    return {"invoice_number": invoice_number, "amount_paid": amount_paid}


def add_remark(sheet: gspread.Worksheet, invoice_number: str, remarks: str) -> None:
    col_a = sheet.col_values(1)
    try:
        row_idx = col_a.index(invoice_number) + 1
    except ValueError:
        raise ValueError(f"Invoice {invoice_number} not found.")
    remarks_col = chr(ord("A") + HEADERS.index("Remarks"))
    sheet.update(f"{remarks_col}{row_idx}", [[remarks]])
