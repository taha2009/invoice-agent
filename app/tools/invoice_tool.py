import logging
from datetime import datetime, timezone
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.pdf_generator import generate_pdf
from app.tools.sheets_ledger import add_remark as _add_remark
from app.tools.sheets_ledger import get_invoice as _get_invoice
from app.tools.sheets_ledger import get_sheet, next_invoice_number
from app.tools.sheets_ledger import record_payment as _record_payment
from app.tools.sheets_ledger import upsert_invoice

log = logging.getLogger(__name__)


class FeeItem(BaseModel):
    description: str
    amount: float


class InvoiceInput(BaseModel):
    client: str = Field(description="Company or firm name being billed.")
    client_address: str = Field(description="Full postal address of the client.")
    attention: str = Field(
        description="Individual contact name at the client's organisation.",
    )
    invoice_date: str = Field(
        description="Must be a fully resolved date in YYYY-MM-DD format, e.g. '2026-05-23'. Never pass 'today' or any relative term — always convert to the actual calendar date before calling this tool."
    )
    professional_fees: list[FeeItem] = Field(
        description="At least one fee line item with description and amount."
    )
    disbursements: list[FeeItem] = Field(
        default=[],
        description="Out-of-pocket expenses passed on to the client. Can be empty.",
    )
    advance_paid: float = Field(
        default=0.0,
        description="Amount already paid in advance. Default 0 if not mentioned.",
    )
    invoice_number: Optional[str] = Field(
        default=None,
        description="Reuse an existing invoice number when correcting a previously generated invoice. Leave blank for new invoices.",
    )


@tool("generate_invoice", args_schema=InvoiceInput)
def generate_invoice(
    client: str,
    client_address: str,
    attention: str,
    invoice_date: str,
    professional_fees: list[FeeItem],
    disbursements: list[FeeItem],
    advance_paid: float,
    invoice_number: Optional[str] = None,
) -> dict:
    """Generate a PDF invoice and record it in Google Sheets.
    Call only when every required field has been confirmed by the user.
    Pass invoice_number to correct an existing invoice without creating a new one."""

    professional_fees_total = sum(item.amount for item in professional_fees)
    disbursements_total = sum(item.amount for item in disbursements)
    total_payable = professional_fees_total + disbursements_total - advance_paid

    sheet = None
    sheet_error = None
    try:
        sheet = get_sheet()
        if not invoice_number:
            invoice_number = next_invoice_number(sheet)
    except Exception as exc:
        log.warning("Sheet access failed: %s", exc)
        sheet_error = str(exc)
        if not invoice_number:
            invoice_number = (
                f"DRAFT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            )

    pdf_path, pdf_filename = generate_pdf(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        client=client,
        client_address=client_address,
        attention=attention,
        professional_fees=[f.model_dump() for f in professional_fees],
        disbursements=[f.model_dump() for f in disbursements],
        professional_fees_total=professional_fees_total,
        disbursements_total=disbursements_total,
        advance_paid=advance_paid,
        total_payable=total_payable,
    )

    if sheet is not None:
        try:
            upsert_invoice(
                sheet,
                {
                    "invoice_number": invoice_number,
                    "invoice_date": invoice_date,
                    "client": client,
                    "attention": attention,
                    "client_address": client_address,
                    "professional_fees": [f.model_dump() for f in professional_fees],
                    "professional_fees_total": professional_fees_total,
                    "disbursements": [f.model_dump() for f in disbursements],
                    "disbursements_total": disbursements_total,
                    "advance_paid": advance_paid,
                    "total_payable": total_payable,
                    "remarks": "",
                },
            )
        except Exception as exc:
            log.warning("Sheet write failed: %s", exc)
            sheet_error = str(exc)

    result = {
        "invoice_number": invoice_number,
        "total_payable": total_payable,
        "pdf_path": pdf_path,
        "pdf_filename": pdf_filename,
    }
    if sheet_error:
        result["sheet_error"] = sheet_error
    return result


class GetInvoiceInput(BaseModel):
    invoice_number: str = Field(
        description="Invoice number to look up, e.g. 2026-27/3."
    )


@tool("get_invoice_info", args_schema=GetInvoiceInput)
def get_invoice_info(invoice_number: str) -> dict:
    """Fetch the recorded details of an existing invoice from Google Sheets."""
    sheet = get_sheet()
    data = _get_invoice(sheet, invoice_number)
    if data is None:
        return {"error": f"Invoice {invoice_number} not found."}
    return data


class RecordPaymentInput(BaseModel):
    invoice_number: str = Field(
        description="Invoice number to record payment against, e.g. 2026-27/3."
    )
    payment_date: str = Field(
        description="Date payment was received, in YYYY-MM-DD format."
    )
    payment_mode: str = Field(
        description="Payment method, e.g. 'NEFT', 'RTGS', 'Cheque', 'Cash', 'UPI'."
    )


class AddRemarkInput(BaseModel):
    invoice_number: str = Field(
        description="Invoice number to add a remark to, e.g. 2026-27/3."
    )
    remarks: str = Field(
        description="Internal remark or note to record against this invoice."
    )


@tool("add_remark", args_schema=AddRemarkInput)
def add_remark(invoice_number: str, remarks: str) -> dict:
    """Add or update an internal remark on an existing invoice in Google Sheets."""
    sheet = get_sheet()
    try:
        _add_remark(sheet, invoice_number, remarks)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"invoice_number": invoice_number, "remarks": remarks}


@tool("record_payment", args_schema=RecordPaymentInput)
def record_payment(
    invoice_number: str,
    payment_date: str,
    payment_mode: str,
) -> dict:
    """Record payment received for an invoice. The amount paid is taken from the invoice's Total Payable."""
    sheet = get_sheet()
    try:
        result = _record_payment(sheet, invoice_number, payment_date, payment_mode)
    except ValueError as exc:
        return {"error": str(exc)}
    return result
