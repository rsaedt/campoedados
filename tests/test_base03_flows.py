from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_db
from app.core.enums import EventStatus, ModuleCode, MovementType, PayableStatus, ProductType, PurchaseStatus, TransferStatus
from app.main import app
from app.models.domain import (
    AccountsPayable,
    Event,
    EventDocument,
    Membership,
    Organization,
    Product,
    Purchase,
    Transfer,
    Unit,
    User,
    UserModulePermission,
)
from app.services.auth import issue_access_token
from app.services.inventory import get_balance, receive_stock
from app.services.modules import set_module_enabled


D = Decimal


def client_for_session(session):
    def override_db():
        yield session
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def teardown_client():
    app.dependency_overrides.clear()


def setup_context(session, *, finance=True, initial_finished="3000"):
    org = Organization(name="Agropecuária", slug=f"agro-b03-{finance}")
    operator = User(display_name="João Operador", email=f"op-{finance}@agro.test")
    manager = User(display_name="Maria Gerente", email=f"mgr-{finance}@agro.test")
    session.add_all([org, operator, manager])
    session.flush()

    sh7 = Unit(organization_id=org.id, name="SH7", code="SH7")
    nsg = Unit(organization_id=org.id, name="NSG", code="NSG")
    session.add_all([sh7, nsg])
    session.flush()

    op_membership = Membership(organization_id=org.id, user_id=operator.id, role="operator")
    mgr_membership = Membership(organization_id=org.id, user_id=manager.id, role="manager")
    session.add_all([op_membership, mgr_membership])
    session.flush()

    set_module_enabled(session, org.id, ModuleCode.FEED_MILL.value, True)
    if finance:
        set_module_enabled(session, org.id, ModuleCode.FINANCE.value, True)

    session.add_all([
        UserModulePermission(
            membership_id=op_membership.id,
            module_code=ModuleCode.FEED_MILL.value,
            can_view=True,
            can_register=True,
        ),
        UserModulePermission(
            membership_id=mgr_membership.id,
            module_code=ModuleCode.FEED_MILL.value,
            can_view=True,
            can_approve=True,
        ),
    ])
    if finance:
        session.add(
            UserModulePermission(
                membership_id=mgr_membership.id,
                module_code=ModuleCode.FINANCE.value,
                can_view=True,
                can_approve=True,
            )
        )

    seca = Product(
        organization_id=org.id,
        code="SECA01",
        name="Seca 0,1",
        product_type=ProductType.FINISHED_GOOD.value,
        base_unit="kg",
        package_weight=D("30"),
    )
    milho = Product(
        organization_id=org.id,
        code="MILHO",
        name="Milho",
        product_type=ProductType.RAW_MATERIAL.value,
        base_unit="kg",
    )
    session.add_all([seca, milho])
    session.flush()

    receive_stock(
        session,
        organization_id=org.id,
        unit_id=sh7.id,
        product_id=seca.id,
        quantity=initial_finished,
        unit_cost="2.50",
        movement_type=MovementType.RECEIPT.value,
    )

    _, op_token = issue_access_token(session, membership_id=op_membership.id, raw_token=f"op-b03-{finance}")
    _, mgr_token = issue_access_token(session, membership_id=mgr_membership.id, raw_token=f"mgr-b03-{finance}")
    session.commit()
    return org, sh7, nsg, seca, milho, op_token, mgr_token


def post_message(client, token, payload):
    return client.post(
        "/v1/operator/messages",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


def invoice_document(*, quantity="30000", received_quantity=None, invoice_number="NF-001"):
    extracted = {
        "supplier_name": "Cerealista Brasil",
        "supplier_document": "12345678000199",
        "invoice_number": invoice_number,
        "product_name": "Milho",
        "quantity": quantity,
        "unit": "kg",
        "unit_cost": "0.75",
        "total_amount": "22500.00",
        "issue_date": "2026-08-08",
        "installments": [{"due_date": "2026-09-08", "amount": "22500.00"}],
    }
    if received_quantity is not None:
        extracted["received_quantity"] = received_quantity
    return {
        "document_type": "invoice",
        "filename": "nf-001.jpg",
        "mime_type": "image/jpeg",
        "storage_ref": "incoming/nf-001.jpg",
        "extracted_data": extracted,
    }


def test_operator_dispatches_80_sacks_preserving_declared_quantity_and_value(session):
    org, sh7, nsg, seca, _, op_token, _ = setup_context(session)
    client = client_for_session(session)
    try:
        response = post_message(client, op_token, {
            "text": "Carreguei 80 sacos de Seca 0,1 para NSG",
            "unit_code": "SH7",
            "channel": "whatsapp",
            "external_id": "wamid.transfer.1",
        })
    finally:
        teardown_client()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == EventStatus.PROCESSED.value
    assert body["transfer"]["declared_quantity"] == "80.0000"
    assert body["transfer"]["declared_unit"] == "sack"
    assert body["transfer"]["dispatched_quantity"] == "2400.0000"
    assert body["transfer"]["total_value"] == "6000.00"
    assert get_balance(session, org.id, sh7.id, seca.id).quantity == D("600.0000")
    assert get_balance(session, org.id, nsg.id, seca.id, create=False) is None


def test_exact_transfer_receipt_moves_same_cost_to_destination(session):
    org, _, nsg, seca, _, op_token, _ = setup_context(session)
    client = client_for_session(session)
    try:
        dispatched = post_message(client, op_token, {
            "text": "Carreguei 80 sacos de Seca 0,1 para NSG",
            "unit_code": "SH7",
        })
        received = post_message(client, op_token, {
            "text": "Chegaram os 80 sacos na NSG",
            "unit_code": "NSG",
        })
    finally:
        teardown_client()

    assert dispatched.status_code == 200
    assert received.status_code == 200, received.text
    body = received.json()
    assert body["status"] == EventStatus.PROCESSED.value
    assert body["transfer"]["status"] == TransferStatus.RECEIVED.value
    balance = get_balance(session, org.id, nsg.id, seca.id)
    assert balance.quantity == D("2400.0000")
    assert balance.avg_unit_cost == D("2.500000")
    assert balance.total_value == D("6000.0000000000")


def test_divergent_transfer_waits_for_manager_and_manager_accepts_physical_quantity(session):
    org, _, nsg, seca, _, op_token, mgr_token = setup_context(session)
    client = client_for_session(session)
    try:
        post_message(client, op_token, {
            "text": "Carreguei 80 sacos de Seca 0,1 para NSG",
            "unit_code": "SH7",
        })
        received = post_message(client, op_token, {
            "text": "Chegaram 78 sacos na NSG",
            "unit_code": "NSG",
        })
        event_id = received.json()["event_id"]
        balance_before_decision = get_balance(session, org.id, nsg.id, seca.id, create=False)
        pending = client.get(
            "/v1/manager/pending",
            headers={"Authorization": f"Bearer {mgr_token}"},
        )
        decision = client.post(
            f"/v1/manager/events/{event_id}/decision",
            headers={"Authorization": f"Bearer {mgr_token}"},
            json={"decision": "approve", "notes": "Aceita diferença física"},
        )
    finally:
        teardown_client()

    assert received.status_code == 200
    assert received.json()["status"] == EventStatus.WAITING_MANAGER.value
    assert received.json()["transfer"]["status"] == TransferStatus.DIVERGENT.value
    assert balance_before_decision is None
    assert pending.status_code == 200
    assert any(item["event_id"] == event_id for item in pending.json())
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == EventStatus.PROCESSED.value
    destination = get_balance(session, org.id, nsg.id, seca.id)
    assert destination.quantity == D("2340.0000")
    transfer = session.scalar(select(Transfer).where(Transfer.receipt_event_id == event_id))
    assert transfer.status == TransferStatus.RECEIVED.value
    assert transfer.divergence_quantity == D("-60.0000")


def test_invoice_receipt_posts_physical_stock_and_finance_waits_for_manager(session):
    org, sh7, _, _, milho, op_token, mgr_token = setup_context(session, finance=True)
    client = client_for_session(session)
    try:
        response = post_message(client, op_token, {
            "text": "Chegou milho, segue NF",
            "unit_code": "SH7",
            "channel": "whatsapp",
            "external_id": "wamid.nf.1",
            "source_type": "image",
            "document": invoice_document(),
        })
        event_id = response.json()["event_id"]
        body_before_decision = response.json()
        purchase_before = session.get(Purchase, body_before_decision["purchase"]["purchase_id"])
        purchase_status_before = purchase_before.status
        payable_before = session.scalar(select(AccountsPayable).where(AccountsPayable.purchase_id == purchase_before.id))
        payable_status_before = payable_before.status
        decision = client.post(
            f"/v1/manager/events/{event_id}/decision",
            headers={"Authorization": f"Bearer {mgr_token}"},
            json={"decision": "approve", "notes": "Compra conferida"},
        )
    finally:
        teardown_client()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == EventStatus.WAITING_MANAGER.value
    states = {row["module_code"]: row for row in body["module_states"]}
    assert states[ModuleCode.FEED_MILL.value]["status"] == EventStatus.PROCESSED.value
    assert states[ModuleCode.FINANCE.value]["status"] == EventStatus.WAITING_MANAGER.value
    assert get_balance(session, org.id, sh7.id, milho.id).quantity == D("30000.0000")
    purchase = session.get(Purchase, body["purchase"]["purchase_id"])
    assert purchase.organization_id == org.id
    assert purchase_status_before == PurchaseStatus.WAITING_APPROVAL.value
    payable = session.scalar(select(AccountsPayable).where(AccountsPayable.purchase_id == purchase.id))
    assert payable_status_before == PayableStatus.PENDING_APPROVAL.value
    assert session.scalar(select(EventDocument).where(EventDocument.event_id == event_id)) is not None
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == EventStatus.PROCESSED.value
    assert purchase.status == PurchaseStatus.APPROVED.value
    assert payable.status == PayableStatus.OPEN.value


def test_invoice_receipt_works_without_finance_module(session):
    org, sh7, _, _, milho, op_token, _ = setup_context(session, finance=False)
    doc = invoice_document()
    doc["extracted_data"] = {
        "product_name": "Milho",
        "quantity": "10000",
        "unit": "kg",
        "unit_cost": "0.80",
        "total_amount": "8000.00",
    }
    client = client_for_session(session)
    try:
        response = post_message(client, op_token, {
            "text": "Chegou milho, segue NF",
            "unit_code": "SH7",
            "document": doc,
        })
    finally:
        teardown_client()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == EventStatus.PROCESSED.value
    assert body["target_modules"] == [ModuleCode.FEED_MILL.value]
    assert body["purchase"] is None
    assert get_balance(session, org.id, sh7.id, milho.id).quantity == D("10000.0000")
    assert session.scalar(select(Purchase)) is None


def test_invoice_physical_difference_flags_feed_mill_nonconformity(session):
    org, sh7, _, _, milho, op_token, mgr_token = setup_context(session, finance=True)
    client = client_for_session(session)
    try:
        response = post_message(client, op_token, {
            "text": "Chegou milho, segue NF",
            "unit_code": "SH7",
            "document": invoice_document(quantity="30000", received_quantity="29400", invoice_number="NF-DIF"),
        })
        event_id = response.json()["event_id"]
        decision = client.post(
            f"/v1/manager/events/{event_id}/decision",
            headers={"Authorization": f"Bearer {mgr_token}"},
            json={"decision": "approve", "notes": "Diferença reconhecida no recebimento"},
        )
    finally:
        teardown_client()

    assert response.status_code == 200
    states = {row["module_code"]: row for row in response.json()["module_states"]}
    assert states[ModuleCode.FEED_MILL.value]["status"] == EventStatus.WAITING_MANAGER.value
    assert states[ModuleCode.FINANCE.value]["status"] == EventStatus.WAITING_MANAGER.value
    assert get_balance(session, org.id, sh7.id, milho.id).quantity == D("29400.0000")
    event = session.get(Event, event_id)
    assert event.interpretation["data"]["quantity_discrepancy"] == "-600"
    assert decision.status_code == 200
    assert decision.json()["status"] == EventStatus.PROCESSED.value


def test_duplicate_invoice_is_blocked_before_second_stock_entry(session):
    org, sh7, _, _, milho, op_token, _ = setup_context(session, finance=True)
    client = client_for_session(session)
    payload = {
        "text": "Chegou milho, segue NF",
        "unit_code": "SH7",
        "document": invoice_document(invoice_number="NF-DUP"),
    }
    try:
        first = post_message(client, op_token, {**payload, "external_id": "one"})
        second = post_message(client, op_token, {**payload, "external_id": "two"})
    finally:
        teardown_client()

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == EventStatus.WAITING_MANAGER.value
    assert "já registrada" in second.json()["reason"]
    assert get_balance(session, org.id, sh7.id, milho.id).quantity == D("30000.0000")
    assert len(list(session.scalars(select(Purchase)))) == 1
