from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_db
from app.main import app
from app.models.domain import (
    AuditEntry,
    Event,
    EventModuleTarget,
    InventoryBalance,
    InventoryMovement,
    Membership,
    Organization,
    OrganizationModule,
    Product,
    SystemModule,
    Unit,
    User,
    UserModulePermission,
)
from app.services.auth import issue_access_token


def _setup_manager(session):
    org = Organization(name="Agro Gestão", slug="agro-gestao", active=True)
    user = User(display_name="Gestor", active=True)
    module = SystemModule(code="feed_mill", name="Fábrica de Ração", active=True)
    session.add_all([org, user, module])
    session.flush()
    session.add(OrganizationModule(organization_id=org.id, module_code="feed_mill", enabled=True))
    membership = Membership(organization_id=org.id, user_id=user.id, role="admin", active=True)
    unit = Unit(organization_id=org.id, code="NSG", name="Fazenda NSG", active=True)
    product = Product(
        organization_id=org.id,
        code="MILHO",
        name="Milho",
        product_type="raw_material",
        base_unit="kg",
        active=True,
    )
    session.add_all([membership, unit, product])
    session.flush()
    session.add(
        UserModulePermission(
            membership_id=membership.id,
            module_code="feed_mill",
            can_view=True,
            can_register=True,
            can_approve=True,
            can_configure=True,
        )
    )
    _, raw = issue_access_token(session, membership_id=membership.id, raw_token="management-test-token")
    session.commit()
    return org, unit, product, raw


def _client(session):
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_manager_can_correct_stock_to_physical_count_with_compensating_movement(session):
    org, unit, product, raw = _setup_manager(session)
    session.add(
        InventoryBalance(
            organization_id=org.id,
            unit_id=unit.id,
            product_id=product.id,
            quantity=Decimal("700"),
            avg_unit_cost=Decimal("1"),
        )
    )
    session.commit()

    client = _client(session)
    try:
        response = client.post(
            "/v1/dashboard/management/stock/corrections",
            headers={"Authorization": f"Bearer {raw}"},
            json={
                "unit_code": "NSG",
                "product_id": product.id,
                "target_quantity": 0,
                "reason": "Correção de saldo de homologação",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["previous_quantity"] == 700.0
    assert body["target_quantity"] == 0.0

    balance = session.scalar(
        select(InventoryBalance).where(
            InventoryBalance.organization_id == org.id,
            InventoryBalance.unit_id == unit.id,
            InventoryBalance.product_id == product.id,
        )
    )
    assert Decimal(balance.quantity) == Decimal("0")

    movement = session.scalar(
        select(InventoryMovement)
        .where(InventoryMovement.reference_type == "manager_stock_correction")
        .order_by(InventoryMovement.created_at.desc())
    )
    assert movement is not None
    assert Decimal(movement.quantity) == Decimal("-700.0000")
    assert Decimal(movement.total_value) == Decimal("-700.00")

    audit = session.scalar(
        select(AuditEntry).where(AuditEntry.action == "manager_stock_corrected")
    )
    assert audit is not None
    assert audit.details["reason"] == "Correção de saldo de homologação"


def test_increasing_empty_stock_requires_unit_cost(session):
    _org, _unit, product, raw = _setup_manager(session)
    client = _client(session)
    try:
        response = client.post(
            "/v1/dashboard/management/stock/corrections",
            headers={"Authorization": f"Bearer {raw}"},
            json={
                "unit_code": "NSG",
                "product_id": product.id,
                "target_quantity": 100,
                "reason": "Contagem física encontrou saldo",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "custo unitário" in response.json()["detail"]


def test_manager_can_close_old_waiting_complement_without_deleting_history(session):
    org, unit, _product, raw = _setup_manager(session)
    event = Event(
        organization_id=org.id,
        unit_id=unit.id,
        channel="api",
        source_type="text",
        source_original="Fiz duas batidas da Seca 0,1.",
        event_type="feed_mill.production",
        status="waiting_complement",
        requires_approval=False,
    )
    session.add(event)
    session.flush()
    target = EventModuleTarget(
        event_id=event.id,
        module_code="feed_mill",
        status="waiting_complement",
        requires_approval=False,
    )
    session.add(target)
    session.commit()

    client = _client(session)
    try:
        response = client.post(
            f"/v1/dashboard/management/events/{event.id}/close",
            headers={"Authorization": f"Bearer {raw}"},
            json={"reason": "Evento antigo de homologação"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"
    session.refresh(event)
    session.refresh(target)
    assert event.status == "rejected"
    assert target.status == "rejected"
    assert event.source_original == "Fiz duas batidas da Seca 0,1."

    audit = session.scalar(
        select(AuditEntry).where(AuditEntry.action == "manager_incomplete_event_closed")
    )
    assert audit is not None
    assert audit.event_id == event.id
    assert audit.details["reason"] == "Evento antigo de homologação"


def test_dashboard_exposes_manager_correction_controls_and_consumption_translation():
    response = TestClient(app).get(
        "/dashboard",
        cookies={"campoedados_session": "visual-test"},
    )
    assert response.status_code == 200
    assert "Correção gerencial de estoque" in response.text
    assert "Consumo na fazenda" in response.text
    assert "Encerrar pendência" in response.text
    assert "/v1/dashboard/management/stock/corrections" in response.text
