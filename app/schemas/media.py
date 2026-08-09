from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.operator import OperatorMessageResponse


class MediaProcessingResponse(BaseModel):
    source_type: str
    filename: str | None = None
    mime_type: str | None = None
    storage_ref: str
    sha256: str
    transcript: str | None = None
    extraction: dict | None = None
    event: OperatorMessageResponse


class ExtractedInvoicePreview(BaseModel):
    supplier_name: str | None = None
    supplier_document: str | None = None
    invoice_number: str | None = None
    issue_date: str | None = None
    product_name: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_cost: float | None = None
    total_amount: float | None = None
    installments: list[dict] = Field(default_factory=list)
    confidence: float | None = None
