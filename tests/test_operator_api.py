from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_db
from app.core.enums import EventStatus, ModuleCode, MovementType, ProductType
from app.main import app
from app.models.domain import (
    AuditEntry,
    Event,
    Membership,
    Organization,
    Product,
    ProductionBatch,
    Recipe,
    RecipeIngredient,
    Unit,
    User,
    UserModulePermission,
)
from app.services.auth import issue_access_token
from app.services.inventory import get_balance, receive_stock
from app.services.modules import set_module_enabled


D = Decimal


def setup_operator_context(session, *, can_register=True, nucleus_qty="10000"):
    org = Organization(name="Agropecuária", slug="agro-operator")
    user = User(display_name="João Operador", email="operador@agro.test")
    session.add_all([org, user])
    session.flush()
    sh7 = Unit(organization_id=org.id, name="SH7", code="SH7")
    session.add(sh7)
    membership = Membership(organization_id=org.id, user_id=user.id, role="operator")
    session.add(membership)
    session.flush()
    set_module_enabled(session, org.id, ModuleCode.FEED_MILL.value, True)
    session.add(
        UserModulePermission(
            membership_id=membership.id,
            module_code=ModuleCode.FEED_MILL.value,
            can_view=True,
            can_register=can_register,
        )
    )

    products = {}
    for code, name, kind in [
        ("MILHO", "Milho", ProductType.RAW_MATERIAL.value),
        ("FARELO", "Farelo de soja", ProductType.RAW_MATERIAL.value),
        ("UREIA", "Ureia", ProductType.RAW_MATERIAL.value),
        ("SAL", "Sal branco", ProductType.RAW_MATERIAL.value),
        ("NUCLEO", "Núcleo", ProductType.RAW_MATERIAL.value),
        ("SECA01", "Seca 0,1", ProductType.FINISHED_GOOD.value),
    ]:
        p = Product(organization_id=org.id, code=code, name=name, product_type=kind, base_unit="kg")
        session.add(p)
        products[code] = p
    session.flush()

    costs = {"MILHO": "0.75", "FARELO": "2.05", "UREIA": "4.00", "SAL": "0.80", "NUCLEO": "7.10"}
    for code, cost in costs.items():
        qty = nucleus_qty if code == "NUCLEO" else "10000"
        receive_stock(
            session,
            organization_id=org.id,
            unit_id=sh7.id,
            product_id=products[code].id,
            quantity=qty,
            unit_cost=cost,
            movement_type=MovementType.RECEIPT.value,
        )

    recipe = Recipe(
        organization_id=org.id,
        output_product_id=products["SECA01"].id,
        name="Seca 0,1",
        output_quantity_per_batch=D("500"),
    )
    recipe.ingredients = [
        RecipeIngredient(product_id=products["MILHO"].id, quantity_per_batch=D("350")),
        RecipeIngredient(product_id=products["FARELO"].id, quantity_per_batch=D("50")),
        RecipeIngredient(product_id=products["UREIA"].id, quantity_per_batch=D("35")),
        RecipeIngredient(product_id=products["SAL"].id, quantity_per_batch=D("40")),
        RecipeIngredient(product_id=products["NUCLEO"].id, quantity_per_batch=D("25")),
    ]
    session.add(recipe)
    session.flush()
    _, raw = issue_access_token(session, membership_id=membership.id, raw_token="operator-test-token")
    session.commit()
    return org, user, sh7, products, recipe, raw


def client_for_session(session):
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def teardown_client():
    app.dependency_overrides.clear()


def test_operator_message_produces_three_batches_and_audits(session):
    org, user, sh7, products, _, token = setup_operator_context(session)
    client = client_for_session(session)
    try:
        response = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Fiz 3 batidas da Seca 0,1", "unit_code": "SH7"},
        )
    finally:
        teardown_client()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == EventStatus.PROCESSED.value
    assert body["event_type"] == "feed_mill.production"
    assert body["production"]["output_quantity"] == "1500.0000"

    event = session.get(Event, body["event_id"])
    assert event.source_original == "Fiz 3 batidas da Seca 0,1"
    assert event.actor_user_id == user.id
    assert event.unit_id == sh7.id
    assert session.scalar(select(ProductionBatch).where(ProductionBatch.event_id == event.id)) is not None
    assert session.scalar(select(AuditEntry).where(AuditEntry.event_id == event.id)) is not None
    assert get_balance(session, org.id, sh7.id, products["SAL"].id).quantity == D("9880.0000")


def test_operator_without_register_permission_is_forbidden(session):
    _, _, _, _, _, token = setup_operator_context(session, can_register=False)
    client = client_for_session(session)
    try:
        response = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Fiz 3 batidas da Seca 0,1", "unit_code": "SH7"},
        )
    finally:
        teardown_client()
    assert response.status_code == 403


def test_insufficient_stock_becomes_manager_pending_without_partial_consumption(session):
    org, _, sh7, products, _, token = setup_operator_context(session, nucleus_qty="50")
    milho_before = get_balance(session, org.id, sh7.id, products["MILHO"].id).quantity
    client = client_for_session(session)
    try:
        response = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Fiz 3 batidas da Seca 0,1", "unit_code": "SH7"},
        )
    finally:
        teardown_client()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == EventStatus.WAITING_MANAGER.value
    event = session.get(Event, body["event_id"])
    assert event.requires_approval is True
    assert get_balance(session, org.id, sh7.id, products["MILHO"].id).quantity == milho_before
    production = session.scalar(select(ProductionBatch).where(ProductionBatch.event_id == event.id))
    assert production is None


def test_incomplete_production_message_asks_only_for_missing_batch_count(session):
    _, _, _, _, _, token = setup_operator_context(session)
    client = client_for_session(session)
    try:
        response = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Fiz uma produção da Seca 0,1", "unit_code": "SH7"},
        )
    finally:
        teardown_client()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == EventStatus.WAITING_COMPLEMENT.value
    assert body["question"] == "Quantas batidas foram feitas?"


def test_operator_endpoint_requires_authentication(session):
    client = client_for_session(session)
    try:
        response = client.post(
            "/v1/operator/messages",
            json={"text": "Fiz 3 batidas da Seca 0,1", "unit_code": "SH7"},
        )
    finally:
        teardown_client()
    assert response.status_code == 401


def test_duplicate_external_id_does_not_produce_twice(session):
    org, _, sh7, products, _, token = setup_operator_context(session)
    client = client_for_session(session)
    payload = {
        "text": "Fiz 3 batidas da Seca 0,1",
        "unit_code": "SH7",
        "channel": "whatsapp",
        "external_id": "wamid.001",
    }
    try:
        first = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        second = client.post(
            "/v1/operator/messages",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    finally:
        teardown_client()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["event_id"] == second.json()["event_id"]
    assert second.json()["reason"] == "duplicate_event"
    assert get_balance(session, org.id, sh7.id, products["MILHO"].id).quantity == D("8950.0000")
    assert len(list(session.scalars(select(ProductionBatch)))) == 1
