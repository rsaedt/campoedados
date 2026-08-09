from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.enums import MembershipRole, ModuleCode, ProductType
from app.models.domain import (
    AccessToken,
    AuditEntry,
    InventoryBalance,
    InventoryMovement,
    Membership,
    Organization,
    Product,
    Recipe,
    Unit,
    User,
)
from app.services.admin_ops import (
    AdminOperationError,
    IngredientSpec,
    OpeningStockSpec,
    ProductSpec,
    RecipeSpec,
    configure_feed_mill,
    rotate_access_token,
)
from app.services.auth import AuthenticationError, authenticate_access_token, issue_access_token
from app.services.modules import set_module_enabled


def _organization_with_admin(session):
    organization = Organization(name="Agro Teste", slug="agro-teste", active=True)
    user = User(display_name="Gestor", email="gestor@example.com", active=True)
    session.add_all([organization, user])
    session.flush()
    membership = Membership(
        organization_id=organization.id,
        user_id=user.id,
        role=MembershipRole.ADMIN.value,
        active=True,
    )
    session.add(membership)
    session.flush()
    return organization, user, membership


def test_rotate_access_token_revokes_previous_tokens_and_audits(session):
    organization, user, membership = _organization_with_admin(session)
    old_row, old_raw = issue_access_token(
        session,
        membership_id=membership.id,
        label="old",
    )

    result = rotate_access_token(
        session,
        organization_slug=organization.slug,
        label="rotated",
    )
    session.flush()

    assert result.membership_id == membership.id
    assert result.revoked_token_count == 1
    assert old_row.revoked_at is not None
    with pytest.raises(AuthenticationError, match="inválido ou revogado"):
        authenticate_access_token(session, old_raw)

    principal = authenticate_access_token(session, result.raw_token)
    assert principal.user_id == user.id
    assert principal.organization_id == organization.id

    audit = session.scalar(
        select(AuditEntry).where(
            AuditEntry.organization_id == organization.id,
            AuditEntry.action == "access_token_rotated",
        )
    )
    assert audit is not None
    assert audit.actor_user_id == user.id
    assert audit.details["new_token_id"] == result.new_token_id


def _feed_setup_specs():
    products = (
        ProductSpec(
            code="MILHO",
            name="Milho",
            product_type=ProductType.RAW_MATERIAL.value,
            base_unit="kg",
        ),
        ProductSpec(
            code="SECA-01",
            name="Seca 0,1",
            product_type=ProductType.FINISHED_GOOD.value,
            base_unit="kg",
        ),
    )
    recipe = RecipeSpec(
        name="Seca 0,1",
        output_product_code="SECA-01",
        output_quantity_per_batch=Decimal("500"),
        ingredients=(IngredientSpec(product_code="MILHO", quantity_per_batch=Decimal("350")),),
    )
    stock = (
        OpeningStockSpec(
            unit_code="SH7",
            product_code="MILHO",
            quantity=Decimal("1000"),
            unit_cost=Decimal("1.25"),
        ),
    )
    return products, recipe, stock


def _feed_organization(session):
    organization, _user, _membership = _organization_with_admin(session)
    unit = Unit(
        organization_id=organization.id,
        code="SH7",
        name="Fazenda SH7",
        active=True,
    )
    session.add(unit)
    session.flush()
    set_module_enabled(session, organization.id, ModuleCode.FEED_MILL.value, True)
    return organization, unit


def test_feed_mill_setup_is_idempotent_for_same_setup_id(session):
    organization, unit = _feed_organization(session)
    products, recipe_spec, stock = _feed_setup_specs()
    setup_id = "2f720ba0-5207-4680-b35d-45b6801881d9"

    first = configure_feed_mill(
        session,
        organization_slug=organization.slug,
        setup_id=setup_id,
        products=products,
        recipe=recipe_spec,
        opening_stocks=stock,
    )
    second = configure_feed_mill(
        session,
        organization_slug=organization.slug,
        setup_id=setup_id,
        products=products,
        recipe=recipe_spec,
        opening_stocks=stock,
    )
    session.flush()

    assert set(first.created_product_codes) == {"MILHO", "SECA-01"}
    assert first.recipe_created is True
    assert len(first.created_stock_movements) == 1
    assert second.created_product_codes == ()
    assert second.recipe_created is False
    assert second.created_stock_movements == ()

    milho = session.scalar(
        select(Product).where(
            Product.organization_id == organization.id,
            Product.code == "MILHO",
        )
    )
    balance = session.scalar(
        select(InventoryBalance).where(
            InventoryBalance.organization_id == organization.id,
            InventoryBalance.unit_id == unit.id,
            InventoryBalance.product_id == milho.id,
        )
    )
    assert balance.quantity == Decimal("1000.0000")
    assert balance.avg_unit_cost == Decimal("1.250000")
    assert session.scalar(
        select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.organization_id == organization.id,
            InventoryMovement.reference_type == "admin_opening_stock",
            InventoryMovement.reference_id == setup_id,
        )
    ) == 1
    assert session.scalar(
        select(func.count()).select_from(AuditEntry).where(
            AuditEntry.organization_id == organization.id,
            AuditEntry.action == "feed_mill_admin_setup_applied",
        )
    ) == 1

    recipe = session.scalar(
        select(Recipe).where(
            Recipe.organization_id == organization.id,
            Recipe.name == "Seca 0,1",
        )
    )
    assert recipe.output_quantity_per_batch == Decimal("500.0000")
    assert len(recipe.ingredients) == 1
    assert recipe.ingredients[0].quantity_per_batch == Decimal("350.0000")


def test_feed_mill_setup_blocks_reuse_of_setup_id_with_different_stock(session):
    organization, _unit = _feed_organization(session)
    products, recipe_spec, stock = _feed_setup_specs()
    setup_id = "c6dd7e6f-f6a2-499c-b247-fbdab7f744cc"

    configure_feed_mill(
        session,
        organization_slug=organization.slug,
        setup_id=setup_id,
        products=products,
        recipe=recipe_spec,
        opening_stocks=stock,
    )

    changed_stock = (
        OpeningStockSpec(
            unit_code="SH7",
            product_code="MILHO",
            quantity=Decimal("2000"),
            unit_cost=Decimal("1.25"),
        ),
    )
    with pytest.raises(AdminOperationError, match="já foi usado com saldo diferente"):
        configure_feed_mill(
            session,
            organization_slug=organization.slug,
            setup_id=setup_id,
            products=products,
            recipe=recipe_spec,
            opening_stocks=changed_stock,
        )


def test_feed_mill_setup_blocks_silent_product_reconfiguration(session):
    organization, _unit = _feed_organization(session)
    products, recipe_spec, _stock = _feed_setup_specs()
    setup_id = "55dadfc7-9ee9-4ed2-b136-ab19f050c0c9"

    configure_feed_mill(
        session,
        organization_slug=organization.slug,
        setup_id=setup_id,
        products=products,
        recipe=recipe_spec,
    )

    changed_products = (
        ProductSpec(
            code="MILHO",
            name="Milho alterado",
            product_type=ProductType.RAW_MATERIAL.value,
            base_unit="kg",
        ),
        products[1],
    )
    with pytest.raises(AdminOperationError, match="alteração silenciosa foi bloqueada"):
        configure_feed_mill(
            session,
            organization_slug=organization.slug,
            setup_id="2e4c085b-5c75-4ab6-9106-693cb80bb80d",
            products=changed_products,
            recipe=recipe_spec,
        )


def test_rotate_access_token_requires_membership_when_multiple_admins(session):
    organization, _user, _membership = _organization_with_admin(session)
    second_user = User(display_name="Segundo admin", email="segundo@example.com", active=True)
    session.add(second_user)
    session.flush()
    session.add(
        Membership(
            organization_id=organization.id,
            user_id=second_user.id,
            role=MembershipRole.ADMIN.value,
            active=True,
        )
    )
    session.flush()

    with pytest.raises(AdminOperationError, match="exatamente um admin ativo"):
        rotate_access_token(
            session,
            organization_slug=organization.slug,
        )

    assert session.scalar(select(func.count()).select_from(AccessToken)) == 0
