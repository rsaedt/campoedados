from decimal import Decimal

from pydantic import BaseModel, Field


class OperatorMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    unit_code: str = Field(min_length=1, max_length=40)
    channel: str = Field(default="api", min_length=1, max_length=40)
    source_type: str = Field(default="text", min_length=1, max_length=30)
    external_id: str | None = Field(default=None, min_length=1, max_length=80)


class ProductionResult(BaseModel):
    production_batch_id: str
    recipe_name: str
    batch_count: Decimal
    output_quantity: Decimal
    total_material_cost: Decimal
    output_unit_cost: Decimal


class OperatorMessageResponse(BaseModel):
    event_id: str
    status: str
    event_type: str
    target_modules: list[str]
    confidence: Decimal | None = None
    question: str | None = None
    reason: str | None = None
    production: ProductionResult | None = None
