from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.enums import EventStatus, MembershipRole, ModuleCode, ProductType
from app.models.domain import (
    Approval,
    Event,
    EventModuleTarget,
    InventoryBalance,
    InventoryMovement,
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
from app.services.auth import Principal
from app.services.manager import ManagerEventError, decide_event
from app.services.modules import set_module_enabled


def _pending_production(session, *, stock_quantity: Decimal | None):
    organization = Organization(name="Agro Teste", slug="agro-teste", active=True)
    user = User(display_name="Gestor", active=True)
    session.add_all([organization, user])
    session.flush()

    membership = Membership(
        organization_id=organization.id,
        user_id=user.id,
        role=MembershipRole.ADMIN.value,
        active=True,
    )
    unit = Unit(
        organization_id=organization.id,
        code="SH7",
        name="Fazenda SH7",
        active=True,
    )
    session.add_all([membership, unit])
    session.flush()

    set_module_enabled(session, organization.id, ModuleCode.FEED_MILL.value, True)
    session.add(
        UserModulePermission(
            membership_id=membership.id,
            module_code=ModuleCode.FEED_MILL.value,
            can_view=True,
            can_register=True,
            can_approve=True,
            can_configure=True,
        )
    )

    milho = Product(
        organization_id=organization.id,
        code="MILHO",
        name="Milho",
        product_type=ProductType.RAW_MATERIAL.value,
        base_unit="kg",
        active=True,
    )
    seca = Product(
        organization_id=organization.id,
        code="SECA-01",
        name="Seca 0,1",
        product_type=ProductType.FINISHED_GOOD.value,
        base_unit="kg",
        active=True,
    )
    session.add_all([milho, seca])
    session.flush()

    recipe = Recipe(
        organization_id=organization.id,
        output_product_id=seca.id,
        name="Seca 0,1",
        output_quantity_per_batch=Decimal("500"),
        active=True,
    )
    session.add(recipe)
    session.flush()
    recipe.ingredients.append(
        RecipeIngredient(
            product_id=milho.id,
            quantity_per_batch=Decimal("350"),
        )
    )
    session.flush()

    if stock_quantity is not None:
        session.add(
            InventoryBalance(
                organization_id=organization.id,
                unit_id=unit.id,
                product_id=milho.id,
                quantity=stock_quantity,
                avg_unit_cost=Decimal("1.25"),
            )
        )

    event = Event(
        organization_id=organization.id,
        unit_id=unit.id,
        actor_user_id=user.id,
        channel="api",
        source_type="text",
        source_original="Fiz duas batidas da Seca 0,1.",
        event_type="feed_mill.production",
        interpretation={
            "intent": "feed_mill_production",
            "data": {
                "recipe_id": recipe.id,
                "recipe_name": recipe.name,
                "batch_count": "2",
            },
            "missing_fields": [],
        },
        status=EventStatus.WAITING_MANAGER.value,
        requires_approval=True,
    )
    session.add(event)
    session.flush()
    session.add(
        EventModuleTarget(
            event_id=event.id,
            module_code=ModuleCode.FEED_MILL.value,
            status=EventStatus.WAITING_MANAGER.value,
            requires_approval=True,
        )
    )
    session.flush()

    principal = Principal(
        token_id="test-token",
        user=user,
        membership=membership,
        organization=organization,
    )
    # Espelha a API real: o evento pendente já existe em uma transação concluída
    # antes da tentativa posterior de decisão gerencial.
    session.commit()
    return principal, event, milho, seca, unit


def test_manager_cannot_close_production_while_stock_is_still_insufficient(session):
    principal, event, _milho, _seca, _unit = _pending_production(
        session,
        stock_quantity=None,
    )
    event_id = event.id

    with pytest.raises(ManagerEventError, match="continua bloqueada por estoque insuficiente"):
        decide_event(
            session,
            principal=principal,
            event_id=event_id,
            decision="approve",
            notes="Tentar novamente",
        )

    session.rollback()
    persisted = session.get(Event, event_id)
    target = session.scalar(
        select(EventModuleTarget).where(EventModuleTarget.event_id == event_id)
    )
    assert persisted.status == EventStatus.WAITING_MANAGER.value
    assert persisted.requires_approval is True
    assert target.status == EventStatus.WAITING_MANAGER.value
    assert target.requires_approval is True
    assert session.scalar(
        select(func.count()).select_from(ProductionBatch).where(ProductionBatch.event_id == event_id)
    ) == 0
    assert session.scalar(
        select(func.count()).select_from(InventoryMovement).where(InventoryMovement.event_id == event_id)
    ) == 0
    assert session.scalar(
        select(func.count()).select_from(Approval).where(Approval.event_id == event_id)
    ) == 0


def test_manager_approve_retries_and_processes_production_after_stock_exists(session):
    principal, event, milho, seca, unit = _pending_production(
        session,
        stock_quantity=Decimal("700"),
    )

    result = decide_event(
        session,
        principal=principal,
        event_id=event.id,
        decision="approve",
        notes="Estoque regularizado",
    )
    session.commit()

    assert result.status == EventStatus.PROCESSED.value
    assert result.processed_modules == [ModuleCode.FEED_MILL.value]

    production = session.scalar(
        select(ProductionBatch).where(ProductionBatch.event_id == event.id)
    )
    assert production is not None
    assert production.batch_count == Decimal("2.0000")
    assert production.output_quantity == Decimal("1000.0000")

    milho_balance = session.scalar(
        select(InventoryBalance).where(
            InventoryBalance.organization_id == principal.organization_id,
            InventoryBalance.unit_id == unit.id,
            InventoryBalance.product_id == milho.id,
        )
    )
    seca_balance = session.scalar(
        select(InventoryBalance).where(
            InventoryBalance.organization_id == principal.organization_id,
            InventoryBalance.unit_id == unit.id,
            InventoryBalance.product_id == seca.id,
        )
    )
    assert milho_balance.quantity == Decimal("0.0000")
    assert seca_balance.quantity == Decimal("1000.0000")
    assert session.scalar(
        select(func.count()).select_from(Approval).where(
            Approval.event_id == event.id,
            Approval.decision == "approve",
        )
    ) == 1
