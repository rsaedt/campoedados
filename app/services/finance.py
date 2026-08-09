from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import ModuleCode, PayableStatus, PurchaseStatus
from app.models.domain import AccountsPayable, Purchase, PurchaseAllocation
from app.services.inventory import d, q_money
from app.services.modules import require_module


class AllocationError(RuntimeError):
    pass


def create_purchase_with_payables(
    session: Session,
    *,
    organization_id: str,
    supplier_id: str,
    invoice_number: str,
    total_amount,
    installments: list[tuple[date, Decimal]],
    destination_unit_id: str | None = None,
    event_id: str | None = None,
    allocations: list[tuple[str, Decimal]] | None = None,
) -> Purchase:
    require_module(session, organization_id, ModuleCode.FINANCE.value)
    total = q_money(d(total_amount))
    installments_total = q_money(sum((d(amount) for _, amount in installments), Decimal("0")))
    if installments_total != total:
        raise ValueError(f"Soma das parcelas ({installments_total}) difere do total da compra ({total}).")

    allocation_rows = allocations or []
    if allocation_rows:
        allocation_total = q_money(sum((d(amount) for _, amount in allocation_rows), Decimal("0")))
        if allocation_total != total:
            raise AllocationError(f"Rateio ({allocation_total}) deve fechar o total da compra ({total}).")

    purchase = Purchase(
        organization_id=organization_id,
        supplier_id=supplier_id,
        destination_unit_id=destination_unit_id,
        event_id=event_id,
        invoice_number=invoice_number,
        total_amount=total,
        status=PurchaseStatus.WAITING_APPROVAL.value,
    )
    session.add(purchase)
    session.flush()

    for due_date, amount in installments:
        session.add(
            AccountsPayable(
                organization_id=organization_id,
                purchase_id=purchase.id,
                supplier_id=supplier_id,
                due_date=due_date,
                amount=q_money(d(amount)),
                status=PayableStatus.PENDING_APPROVAL.value,
            )
        )

    for cost_center_id, amount in allocation_rows:
        session.add(
            PurchaseAllocation(
                purchase_id=purchase.id,
                cost_center_id=cost_center_id,
                amount=q_money(d(amount)),
            )
        )

    session.flush()
    return purchase


def approve_purchase(session: Session, *, organization_id: str, purchase_id: str) -> Purchase:
    require_module(session, organization_id, ModuleCode.FINANCE.value)
    purchase = session.get(Purchase, purchase_id)
    if purchase is None or purchase.organization_id != organization_id:
        raise ValueError("Compra não encontrada para a organização.")
    if purchase.status != PurchaseStatus.WAITING_APPROVAL.value:
        raise ValueError("Somente compras aguardando aprovação podem ser aprovadas.")

    purchase.status = PurchaseStatus.APPROVED.value
    payables = session.query(AccountsPayable).filter(AccountsPayable.purchase_id == purchase.id).all()
    for payable in payables:
        if payable.status == PayableStatus.PENDING_APPROVAL.value:
            payable.status = PayableStatus.OPEN.value
    session.flush()
    return purchase
