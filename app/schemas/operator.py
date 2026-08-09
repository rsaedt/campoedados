from decimal import Decimal

from pydantic import BaseModel, Field


class OperatorDocumentInput(BaseModel):
    document_type: str = Field(default="attachment", min_length=1, max_length=40)
    filename: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=120)
    storage_ref: str | None = Field(default=None, max_length=500)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    extracted_data: dict = Field(default_factory=dict)


class OperatorMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    unit_code: str = Field(min_length=1, max_length=40)
    channel: str = Field(default="api", min_length=1, max_length=40)
    source_type: str = Field(default="text", min_length=1, max_length=30)
    external_id: str | None = Field(default=None, min_length=1, max_length=80)
    document: OperatorDocumentInput | None = None


class ProductionResult(BaseModel):
    production_batch_id: str
    recipe_name: str
    batch_count: Decimal
    output_quantity: Decimal
    total_material_cost: Decimal
    output_unit_cost: Decimal


class TransferResult(BaseModel):
    transfer_id: str
    product_name: str
    source_unit_code: str
    destination_unit_code: str
    dispatched_quantity: Decimal
    declared_quantity: Decimal | None = None
    declared_unit: str | None = None
    received_quantity: Decimal | None = None
    unit_cost: Decimal
    total_value: Decimal
    status: str


class PurchaseResult(BaseModel):
    purchase_id: str
    supplier_name: str
    invoice_number: str
    total_amount: Decimal
    status: str


class ModuleStateResult(BaseModel):
    module_code: str
    status: str
    requires_approval: bool


class OperatorMessageResponse(BaseModel):
    event_id: str
    status: str
    event_type: str
    target_modules: list[str]
    module_states: list[ModuleStateResult] = Field(default_factory=list)
    confidence: Decimal | None = None
    question: str | None = None
    reason: str | None = None
    production: ProductionResult | None = None
    transfer: TransferResult | None = None
    purchase: PurchaseResult | None = None
