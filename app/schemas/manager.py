from decimal import Decimal

from pydantic import BaseModel, Field


class ManagerDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    notes: str | None = Field(default=None, max_length=2000)
    accepted_quantity: Decimal | None = Field(default=None, gt=0)


class PendingEventItem(BaseModel):
    event_id: str
    event_type: str
    status: str
    unit_code: str | None = None
    source_original: str
    requires_approval: bool
    module_states: list[dict]


class ManagerDecisionResponse(BaseModel):
    event_id: str
    status: str
    decision: str
    processed_modules: list[str]
