from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.enums import EventStatus, MembershipRole, ProductType
from app.main import app
from app.models.domain import (
    AuditEntry,
    Event,
    InventoryBalance,
    Membership,
    Organization,
    Product,
    Unit,
    User,
)
from app.services.auth import issue_access_token


def test_decision_overview_summarizes_each_farm_without_mixing_product_quantities(session):
    org = Organization(name="Agro Visão", slug="agro-visao", active=True)
    user = User(display_name="Gestor", active=True)
    session.add_all([org, user])
    session.flush()

    membership = Membership(
        organization_id=org.id,
        user_id=user.id,
        role=MembershipRole.ADMIN.value,
        active=True,
    )
    sh7 = Unit(organization_id=org.id, code="SH7", name="Fazenda SH7", active=True)
    nsg = Unit(organization_id=org.id, code="NSG", name="Fazenda NSG", active=True)
    milho = Product(
        organization_id=org.id,
        code="MILHO",
        name="Milho",
        product_type=ProductType.RAW_MATERIAL.value,
        base_unit="kg",
        active=True,
    )
    seca = Product(
        organization_id=org.id,
        code="SECA_01",
        name="Seca 0,1",
        product_type=ProductType.FINISHED_GOOD.value,
        base_unit="kg",
        active=True,
    )
    session.add_all([membership, sh7, nsg, milho, seca])
    session.flush()

    session.add_all(
        [
            InventoryBalance(
                organization_id=org.id,
                unit_id=sh7.id,
                product_id=milho.id,
                quantity=Decimal("0"),
                avg_unit_cost=Decimal("0"),
            ),
            InventoryBalance(
                organization_id=org.id,
                unit_id=sh7.id,
                product_id=seca.id,
                quantity=Decimal("2000"),
                avg_unit_cost=Decimal("1"),
            ),
        ]
    )

    manager_event = Event(
        organization_id=org.id,
        unit_id=sh7.id,
        actor_user_id=user.id,
        channel="telegram",
        source_type="text",
        source_original="Fiz duas batidas da Seca 0,1",
        event_type="feed_mill.production",
        status=EventStatus.WAITING_MANAGER.value,
        requires_approval=True,
    )
    complement_event = Event(
        organization_id=org.id,
        unit_id=nsg.id,
        actor_user_id=user.id,
        channel="api",
        source_type="text",
        source_original="Movimentação incompleta",
        event_type="livestock.movement",
        status=EventStatus.WAITING_COMPLEMENT.value,
        requires_approval=False,
    )
    session.add_all([manager_event, complement_event])
    session.flush()
    session.add(
        AuditEntry(
            organization_id=org.id,
            event_id=manager_event.id,
            actor_user_id=user.id,
            action="operator_event_waiting_manager",
            details={"reason": "Estoque insuficiente para Milho: disponível=0, solicitado=700."},
        )
    )
    _, raw = issue_access_token(
        session,
        membership_id=membership.id,
        raw_token="decision-overview-token",
    )
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        response = client.get(
            "/v1/dashboard/decision-overview",
            headers={"Authorization": f"Bearer {raw}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["inventory_value"] == 2000.0
    assert body["summary"]["waiting_complement"] == 1

    farms = {row["unit_code"]: row for row in body["unit_summaries"]}
    assert farms["SH7"]["inventory_value"] == 2000.0
    assert farms["SH7"]["stocked_products"] == 1
    assert farms["SH7"]["zero_raw_material_count"] == 1
    assert farms["SH7"]["stock_items"][0]["product_name"] == "Seca 0,1"
    assert farms["SH7"]["stock_items"][0]["quantity"] == 2000.0
    assert farms["NSG"]["inventory_value"] == 0.0
    assert farms["NSG"]["zero_raw_material_count"] == 1
    assert farms["NSG"]["waiting_complement"] == 1

    detail = body["manager_details"][manager_event.id]
    assert detail["channel"] == "telegram"
    assert "Estoque insuficiente" in detail["reason"]


def test_dashboard_html_exposes_decision_sections_and_human_labels():
    response = TestClient(app).get(
        "/dashboard",
        cookies={"campoedados_session": "visual-test"},
    )
    assert response.status_code == 200
    assert "Situação por fazenda" in response.text
    assert "Pontos de atenção" in response.text
    assert "Estoque (valor)" in response.text
    assert "Produção de ração" in response.text
    assert "Aguardando complemento" in response.text
