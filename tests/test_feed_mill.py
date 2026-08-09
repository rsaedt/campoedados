from decimal import Decimal

from app.core.enums import ModuleCode, MovementType, ProductType
from app.models.domain import Organization, Product, Recipe, RecipeIngredient, Unit
from app.services.feed_mill import dispatch_transfer, produce, receive_transfer
from app.services.inventory import get_balance, receive_stock
from app.services.modules import set_module_enabled


def D(value: str) -> Decimal:
    return Decimal(value)


def setup_feed_mill(session):
    org = Organization(name="Agropecuária", slug="agro")
    session.add(org)
    session.flush()
    sh7 = Unit(organization_id=org.id, name="SH7", code="SH7")
    nsg = Unit(organization_id=org.id, name="NSG", code="NSG")
    session.add_all([sh7, nsg])
    session.flush()
    set_module_enabled(session, org.id, ModuleCode.FEED_MILL.value, True)

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
        receive_stock(
            session,
            organization_id=org.id,
            unit_id=sh7.id,
            product_id=products[code].id,
            quantity="10000",
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
    return org, sh7, nsg, products, recipe


def test_three_batches_consume_ingredients_and_build_material_cost(session):
    org, sh7, _, products, recipe = setup_feed_mill(session)

    production = produce(
        session,
        organization_id=org.id,
        unit_id=sh7.id,
        recipe_id=recipe.id,
        batch_count="3",
    )

    assert get_balance(session, org.id, sh7.id, products["MILHO"].id).quantity == D("8950.0000")
    assert get_balance(session, org.id, sh7.id, products["SAL"].id).quantity == D("9880.0000")
    assert production.output_quantity == D("1500.0000")

    expected = D("1050") * D("0.75") + D("150") * D("2.05") + D("105") * D("4.00") + D("120") * D("0.80") + D("75") * D("7.10")
    assert production.total_material_cost == expected.quantize(D("0.01"))

    finished = get_balance(session, org.id, sh7.id, products["SECA01"].id)
    assert finished.quantity == D("1500.0000")
    assert finished.total_value.quantize(D("0.01")) == production.total_material_cost


def test_transfer_carries_quantity_and_value_without_creating_new_cost(session):
    org, sh7, nsg, products, recipe = setup_feed_mill(session)
    production = produce(session, organization_id=org.id, unit_id=sh7.id, recipe_id=recipe.id, batch_count="3")

    transfer = dispatch_transfer(
        session,
        organization_id=org.id,
        source_unit_id=sh7.id,
        destination_unit_id=nsg.id,
        product_id=products["SECA01"].id,
        quantity="80",
    )

    assert transfer.total_value == (D("80") * production.output_unit_cost).quantize(D("0.01"))
    assert get_balance(session, org.id, sh7.id, products["SECA01"].id).quantity == D("1420.0000")
    assert get_balance(session, org.id, nsg.id, products["SECA01"].id, create=False) is None

    receive_transfer(session, organization_id=org.id, transfer_id=transfer.id)
    destination = get_balance(session, org.id, nsg.id, products["SECA01"].id)
    assert destination.quantity == D("80.0000")
    assert destination.avg_unit_cost == transfer.unit_cost
    assert destination.total_value.quantize(D("0.01")) == transfer.total_value


def test_production_does_not_partially_consume_when_one_ingredient_is_missing(session):
    from app.services.inventory import InsufficientStockError
    import pytest

    org, sh7, _, products, recipe = setup_feed_mill(session)
    balance = get_balance(session, org.id, sh7.id, products["NUCLEO"].id)
    balance.quantity = D("50")

    milho_before = get_balance(session, org.id, sh7.id, products["MILHO"].id).quantity
    with pytest.raises(InsufficientStockError):
        produce(session, organization_id=org.id, unit_id=sh7.id, recipe_id=recipe.id, batch_count="3")

    assert get_balance(session, org.id, sh7.id, products["MILHO"].id).quantity == milho_before
