from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_db
from app.main import app
from app.models.consumption import ConsumptionRecord
from app.models.domain import (
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
from app.services.inventory import receive_stock


def _setup(session, *, initial_quantity="500"):
    org = Organization(name="Agro Consumo", slug="agro-consumo", active=True)
    user = User(display_name="Peão SH7", active=True)
    session.add_all([org, user])
    session.flush()

    feed = SystemModule(code="feed_mill", name="Fábrica de Ração", active=True)
    livestock = SystemModule(code="livestock", name="Pecuária", active=True)
    session.add_all([feed, livestock])
    session.flush()
    session.add_all(
        [
            OrganizationModule(organization_id=org.id, module_code="feed_mill", enabled=True),
            OrganizationModule(organization_id=org.id, module_code="livestock", enabled=True),
        ]
    )

    unit = Unit(organization_id=org.id, code="SH7", name="Fazenda SH7", active=True)
    membership = Membership(
        organization_id=org.id,
        user_id=user.id,
        role="operator",
        active=True,
    )
    milho = Product(
        organization_id=org.id,
        code="MILHO",
        name="Milho",
        product_type="raw_material",
        base_unit="kg",
        package_weight=Decimal("50"),
        active=True,
    )
    session.add_all([unit, membership, milho])
    session.flush()
    session.add_all(
        [
            UserModulePermission(
                membership_id=membership.id,
                module_code="feed_mill",
                can_view=True,
                can_register=True,
                can_approve=False,
                can_configure=False,
            ),
            UserModulePermission(
                membership_id=membership.id,
                module_code="livestock",
                can_view=True,
                can_register=True,
                can_approve=False,
                can_configure=False,
            ),
        ]
    )
    receive_stock(
        session,
        organization_id=org.id,
        unit_id=unit.id,
        product_id=milho.id,
        quantity=Decimal(initial_quantity),
        unit_cost=Decimal("2.50"),
        movement_type="receipt",
        reference_type="test",
    )
    _, raw = issue_access_token(
        session,
        membership_id=membership.id,
        raw_token=f"natural-consumption-{initial_quantity}",
    )
    session.commit()
    return org, unit, milho, raw


def _client(session):
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_telegram_consumption_decrements_farm_stock_and_classifies_livestock(session):
    org, unit, milho, raw = _setup(session)
    client = _client(session)
    try:
        response = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {raw}"},
            json={
                "text": "Tratei 50 kg de milho pros cavalos.",
                "unit_code": "SH7",
                "channel": "telegram",
                "source_type": "text",
                "external_id": "tg-consumo-1",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "processed"
    assert body["event_type"] == "inventory.consumption"
    assert body["target_modules"] == ["livestock"]
    assert body["consumption"]["product_name"] == "Milho"
    assert body["consumption"]["quantity"] == "50.0000"
    assert body["consumption"]["purpose_code"] == "livestock"
    assert body["consumption"]["purpose_label"] == "Pecuária"
    assert body["consumption"]["context_label"] == "Cavalos"
    assert body["consumption"]["remaining_quantity"] == "450.0000"

    balance = session.scalar(
        select(InventoryBalance).where(
            InventoryBalance.organization_id == org.id,
            InventoryBalance.unit_id == unit.id,
            InventoryBalance.product_id == milho.id,
        )
    )
    assert Decimal(balance.quantity) == Decimal("450.0000")

    record = session.scalar(select(ConsumptionRecord).where(ConsumptionRecord.event_id == body["event_id"]))
    assert record is not None
    assert record.purpose_code == "livestock"
    assert Decimal(record.total_value) == Decimal("125.00")

    movement = session.get(InventoryMovement, record.inventory_movement_id)
    assert movement.movement_type == "consumption"
    assert Decimal(movement.quantity) == Decimal("-50.0000")


def test_sack_is_converted_using_registered_package_weight_without_extra_question(session):
    _org, _unit, _milho, raw = _setup(session, initial_quantity="200")
    client = _client(session)
    try:
        response = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {raw}"},
            json={
                "text": "Dei um saco de milho pros cavalos.",
                "unit_code": "SH7",
                "channel": "telegram",
                "source_type": "text",
                "external_id": "tg-consumo-saco",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "processed"
    assert body["question"] is None
    assert body["consumption"]["quantity"] == "50.0000"
    assert body["consumption"]["remaining_quantity"] == "150.0000"


def test_consumption_without_explicit_destination_defaults_to_farm_use(session):
    _org, _unit, _milho, raw = _setup(session, initial_quantity="200")
    client = _client(session)
    try:
        response = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {raw}"},
            json={
                "text": "Usei 20 kg de milho.",
                "unit_code": "SH7",
                "channel": "telegram",
                "source_type": "text",
                "external_id": "tg-consumo-fazenda",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "processed"
    assert body["consumption"]["purpose_code"] == "farm_use"
    assert body["consumption"]["purpose_label"] == "Uso da fazenda"


def test_consumption_never_creates_negative_stock_and_goes_to_manager(session):
    _org, _unit, _milho, raw = _setup(session, initial_quantity="10")
    client = _client(session)
    try:
        response = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {raw}"},
            json={
                "text": "Tratei 50 kg de milho pros cavalos.",
                "unit_code": "SH7",
                "channel": "telegram",
                "source_type": "text",
                "external_id": "tg-consumo-sem-estoque",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "waiting_manager"
    assert body["consumption"] is None

    balance = session.scalar(select(InventoryBalance).where(InventoryBalance.product_id == _milho.id))
    assert Decimal(balance.quantity) == Decimal("10.0000")
