from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.enums import ModuleCode
from app.models.domain import AccountsPayable, CostCenter, Organization, Supplier, Unit
from app.services.finance import approve_purchase, create_purchase_with_payables
from app.services.modules import set_module_enabled


def test_accounts_payable_belongs_to_organization_and_can_be_allocated_to_farms(session):
    org = Organization(name="Agropecuária", slug="agro-fin")
    session.add(org)
    session.flush()
    sh7 = Unit(organization_id=org.id, name="SH7", code="SH7")
    nsg = Unit(organization_id=org.id, name="NSG", code="NSG")
    supplier = Supplier(organization_id=org.id, name="Fornecedor A", document_number="123")
    session.add_all([sh7, nsg, supplier])
    session.flush()
    set_module_enabled(session, org.id, ModuleCode.FINANCE.value, True)

    cc_sh7 = CostCenter(organization_id=org.id, unit_id=sh7.id, code="SH7", name="Fazenda SH7")
    cc_nsg = CostCenter(organization_id=org.id, unit_id=nsg.id, code="NSG", name="Fazenda NSG")
    session.add_all([cc_sh7, cc_nsg])
    session.flush()

    purchase = create_purchase_with_payables(
        session,
        organization_id=org.id,
        supplier_id=supplier.id,
        invoice_number="NF-100",
        total_amount=Decimal("10000.00"),
        installments=[(date(2026, 9, 15), Decimal("5000")), (date(2026, 10, 15), Decimal("5000"))],
        destination_unit_id=sh7.id,
        allocations=[(cc_sh7.id, Decimal("6000")), (cc_nsg.id, Decimal("4000"))],
    )

    payables = session.scalars(select(AccountsPayable).where(AccountsPayable.purchase_id == purchase.id)).all()
    assert len(payables) == 2
    assert all(row.organization_id == org.id for row in payables)
    assert sum((row.amount for row in payables), Decimal("0")) == Decimal("10000.00")
    assert all(row.status == "pending_approval" for row in payables)

    approve_purchase(session, organization_id=org.id, purchase_id=purchase.id)
    assert purchase.status == "approved"
    assert all(row.status == "open" for row in payables)
