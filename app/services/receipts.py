from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.enums import ModuleCode, MovementType
from app.models.domain import CostCenter, Purchase, Supplier
from app.services.finance import create_purchase_with_payables
from app.services.inventory import receive_stock
from app.services.modules import module_enabled


class DuplicateInvoiceError(RuntimeError):
    pass


def _resolve_or_create_supplier(
    session: Session,
    *,
    organization_id: str,
    name: str,
    document_number: str | None,
) -> Supplier:
    conditions = []
    if document_number:
        conditions.append(Supplier.document_number == document_number)
    if name:
        conditions.append(Supplier.name == name)
    supplier = None
    if conditions:
        supplier = session.scalar(
            select(Supplier).where(
                Supplier.organization_id == organization_id,
                or_(*conditions),
            )
        )
    if supplier is None:
        supplier = Supplier(
            organization_id=organization_id,
            name=name,
            document_number=document_number,
        )
        session.add(supplier)
        session.flush()
    return supplier


def _parse_installments(rows: list[dict]) -> list[tuple[date, Decimal]]:
    parsed = []
    for row in rows:
        due = row.get("due_date")
        amount = row.get("amount")
        if due is None or amount is None:
            raise ValueError("Cada parcela precisa de due_date e amount.")
        parsed.append((date.fromisoformat(str(due)), Decimal(str(amount).replace(",", "."))))
    return parsed


def process_material_receipt(
    session: Session,
    *,
    organization_id: str,
    unit_id: str,
    event_id: str,
    data: dict,
):
    """Registra a realidade física imediatamente e, quando contratado, prepara a compra financeira."""
    finance_enabled = module_enabled(session, organization_id, ModuleCode.FINANCE.value)
    purchase = None
    supplier = None

    if finance_enabled:
        supplier = _resolve_or_create_supplier(
            session,
            organization_id=organization_id,
            name=data["supplier_name"],
            document_number=data.get("supplier_document"),
        )
        existing = session.scalar(
            select(Purchase).where(
                Purchase.organization_id == organization_id,
                Purchase.supplier_id == supplier.id,
                Purchase.invoice_number == data["invoice_number"],
            )
        )
        if existing is not None:
            raise DuplicateInvoiceError(
                f"Nota fiscal {data['invoice_number']} já registrada para este fornecedor."
            )

    movement = receive_stock(
        session,
        organization_id=organization_id,
        unit_id=unit_id,
        product_id=data["product_id"],
        quantity=data["quantity"],
        unit_cost=data["unit_cost"],
        movement_type=MovementType.RECEIPT.value,
        event_id=event_id,
        reference_type="material_receipt",
        reference_id=event_id,
    )

    if finance_enabled:
        allocations = None
        cost_center = session.scalar(
            select(CostCenter).where(
                CostCenter.organization_id == organization_id,
                CostCenter.unit_id == unit_id,
                CostCenter.active.is_(True),
            )
        )
        if cost_center is not None:
            allocations = [(cost_center.id, Decimal(data["total_amount"]))]

        issue_date = date.fromisoformat(data["issue_date"]) if data.get("issue_date") else None
        purchase = create_purchase_with_payables(
            session,
            organization_id=organization_id,
            supplier_id=supplier.id,
            invoice_number=data["invoice_number"],
            total_amount=data["total_amount"],
            installments=_parse_installments(data["installments"]),
            destination_unit_id=unit_id,
            event_id=event_id,
            allocations=allocations,
            issue_date=issue_date,
        )

    session.flush()
    return movement, purchase, supplier
