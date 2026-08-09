from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app
from app.models.domain import (
    InventoryBalance,
    InventoryMovement,
    Membership,
    Organization,
    OrganizationModule,
    Product,
    ProductionBatch,
    Recipe,
    RecipeIngredient,
    SystemModule,
    Unit,
    User,
    UserModulePermission,
)
from app.services.auth import issue_access_token


def _feed_mill_principal(session, *, can_view: bool = True):
    org = Organization(name="Agro Fábrica", slug="agro-fabrica", active=True)
    user = User(display_name="Gestor Fábrica", active=True)
    module = SystemModule(code="feed_mill", name="Fábrica de Ração", active=True)
    session.add_all([org, user, module])
    session.flush()
    session.add(OrganizationModule(organization_id=org.id, module_code="feed_mill", enabled=True))
    membership = Membership(organization_id=org.id, user_id=user.id, role="manager", active=True)
    unit = Unit(organization_id=org.id, code="SH7", name="Fazenda SH7", active=True)
    session.add_all([membership, unit])
    session.flush()
    session.add(
        UserModulePermission(
            membership_id=membership.id,
            module_code="feed_mill",
            can_view=can_view,
            can_register=True,
            can_approve=True,
            can_configure=True,
        )
    )
    return org, membership, unit


def test_feed_mill_workspace_returns_stock_recipes_productions_and_entries(session):
    org, membership, unit = _feed_mill_principal(session)
    milho = Product(
        organization_id=org.id,
        code="MILHO",
        name="Milho",
        product_type="raw_material",
        base_unit="kg",
        active=True,
    )
    seca = Product(
        organization_id=org.id,
        code="SECA_01",
        name="Seca 0,1",
        product_type="finished_good",
        base_unit="kg",
        active=True,
    )
    session.add_all([milho, seca])
    session.flush()
    recipe = Recipe(
        organization_id=org.id,
        output_product_id=seca.id,
        name="Seca 0,1",
        output_quantity_per_batch=Decimal("500"),
        active=True,
    )
    session.add(recipe)
    session.flush()
    session.add(
        RecipeIngredient(
            recipe_id=recipe.id,
            product_id=milho.id,
            quantity_per_batch=Decimal("350"),
        )
    )
    session.add_all(
        [
            InventoryBalance(
                organization_id=org.id,
                unit_id=unit.id,
                product_id=milho.id,
                quantity=Decimal("700"),
                avg_unit_cost=Decimal("1.25"),
            ),
            InventoryBalance(
                organization_id=org.id,
                unit_id=unit.id,
                product_id=seca.id,
                quantity=Decimal("1000"),
                avg_unit_cost=Decimal("1.10"),
            ),
        ]
    )
    production = ProductionBatch(
        organization_id=org.id,
        unit_id=unit.id,
        recipe_id=recipe.id,
        batch_count=Decimal("2"),
        output_quantity=Decimal("1000"),
        total_material_cost=Decimal("1100"),
        output_unit_cost=Decimal("1.10"),
    )
    entry = InventoryMovement(
        organization_id=org.id,
        unit_id=unit.id,
        product_id=milho.id,
        movement_type="receipt",
        quantity=Decimal("700"),
        unit_cost=Decimal("1.25"),
        total_value=Decimal("875"),
        reference_type="invoice",
    )
    session.add_all([production, entry])
    _, raw = issue_access_token(session, membership_id=membership.id, raw_token="feed-mill-workspace-token")
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        response = client.get(
            "/v1/dashboard/feed-mill",
            headers={"Authorization": f"Bearer {raw}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["inventory_value"] == 1975.0
    assert body["summary"]["raw_material_value"] == 875.0
    assert body["summary"]["finished_good_value"] == 1100.0
    assert body["summary"]["active_recipes"] == 1
    assert body["recipes"][0]["name"] == "Seca 0,1"
    assert body["recipes"][0]["ingredients"][0]["product_name"] == "Milho"
    assert body["recipes"][0]["ingredients"][0]["quantity_per_batch"] == 350.0
    assert body["productions"][0]["output_quantity"] == 1000.0
    assert body["entries"][0]["movement_type"] == "receipt"


def test_feed_mill_workspace_is_forbidden_without_view_permission(session):
    _, membership, _ = _feed_mill_principal(session, can_view=False)
    _, raw = issue_access_token(session, membership_id=membership.id, raw_token="no-feed-view-token")
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        response = client.get(
            "/v1/dashboard/feed-mill",
            headers={"Authorization": f"Bearer {raw}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_dashboard_contains_feed_mill_workspace_sections():
    response = TestClient(app).get(
        "/dashboard",
        cookies={"campoedados_session": "visual-test"},
    )
    assert response.status_code == 200
    assert "Visão da fábrica" in response.text
    assert "Fórmulas" in response.text
    assert "Transferências" in response.text
    assert "Entradas" in response.text
    assert "/v1/dashboard/feed-mill" in response.text
