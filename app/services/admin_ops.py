from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import MembershipRole, ModuleCode, MovementType, ProductType
from app.models.domain import (
    AccessToken,
    InventoryMovement,
    Membership,
    Organization,
    Product,
    Recipe,
    RecipeIngredient,
    Unit,
)
from app.services.audit import record_audit
from app.services.auth import issue_access_token
from app.services.inventory import q_cost, q_qty, receive_stock
from app.services.modules import require_module


class AdminOperationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductSpec:
    code: str
    name: str
    product_type: str
    base_unit: str = "kg"
    package_weight: Decimal | None = None


@dataclass(frozen=True)
class IngredientSpec:
    product_code: str
    quantity_per_batch: Decimal


@dataclass(frozen=True)
class RecipeSpec:
    name: str
    output_product_code: str
    output_quantity_per_batch: Decimal
    ingredients: tuple[IngredientSpec, ...]


@dataclass(frozen=True)
class OpeningStockSpec:
    unit_code: str
    product_code: str
    quantity: Decimal
    unit_cost: Decimal


@dataclass(frozen=True)
class FeedMillSetupResult:
    organization_id: str
    recipe_id: str
    created_product_codes: tuple[str, ...]
    recipe_created: bool
    created_stock_movements: tuple[str, ...]
    setup_id: str


@dataclass(frozen=True)
class TokenRotationResult:
    organization_id: str
    membership_id: str
    revoked_token_count: int
    new_token_id: str
    raw_token: str


def _normalize_setup_id(value: str) -> str:
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise AdminOperationError("setup_id deve ser um UUID válido.") from exc
    return str(parsed)


def _organization(session: Session, slug: str) -> Organization:
    organization = session.scalar(
        select(Organization).where(
            Organization.slug == slug,
            Organization.active.is_(True),
        )
    )
    if organization is None:
        raise AdminOperationError(f"Organização ativa '{slug}' não encontrada.")
    return organization


def _single_active_admin_membership(session: Session, organization_id: str) -> Membership:
    rows = list(
        session.scalars(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.role == MembershipRole.ADMIN.value,
                Membership.active.is_(True),
            )
        )
    )
    if len(rows) != 1:
        raise AdminOperationError(
            "A organização precisa ter exatamente um admin ativo quando --membership-id não é informado."
        )
    return rows[0]


def rotate_access_token(
    session: Session,
    *,
    organization_slug: str,
    membership_id: str | None = None,
    label: str = "admin-rotation",
) -> TokenRotationResult:
    organization = _organization(session, organization_slug)
    membership = (
        session.get(Membership, membership_id)
        if membership_id is not None
        else _single_active_admin_membership(session, organization.id)
    )
    if (
        membership is None
        or membership.organization_id != organization.id
        or not membership.active
    ):
        raise AdminOperationError("Vínculo ativo não encontrado para a organização.")

    active_tokens = list(
        session.scalars(
            select(AccessToken).where(
                AccessToken.membership_id == membership.id,
                AccessToken.revoked_at.is_(None),
            )
        )
    )
    now = datetime.now(timezone.utc)
    for token in active_tokens:
        token.revoked_at = now

    token_row, raw_token = issue_access_token(
        session,
        membership_id=membership.id,
        label=label,
    )
    record_audit(
        session,
        organization_id=organization.id,
        actor_user_id=membership.user_id,
        action="access_token_rotated",
        details={
            "membership_id": membership.id,
            "revoked_token_count": len(active_tokens),
            "new_token_id": token_row.id,
            "label": label,
        },
    )
    return TokenRotationResult(
        organization_id=organization.id,
        membership_id=membership.id,
        revoked_token_count=len(active_tokens),
        new_token_id=token_row.id,
        raw_token=raw_token,
    )


def _validate_product_spec(spec: ProductSpec) -> ProductSpec:
    code = spec.code.strip()
    name = spec.name.strip()
    base_unit = spec.base_unit.strip()
    if not code or not name or not base_unit:
        raise AdminOperationError("Produto exige código, nome e unidade-base.")
    if spec.product_type not in {ProductType.RAW_MATERIAL.value, ProductType.FINISHED_GOOD.value}:
        raise AdminOperationError(f"Tipo de produto inválido para '{code}'.")
    package_weight = None if spec.package_weight is None else q_qty(Decimal(spec.package_weight))
    if package_weight is not None and package_weight <= 0:
        raise AdminOperationError(f"Peso de embalagem inválido para '{code}'.")
    return ProductSpec(
        code=code,
        name=name,
        product_type=spec.product_type,
        base_unit=base_unit,
        package_weight=package_weight,
    )


def _same_decimal(left, right, quantum: str) -> bool:
    return Decimal(str(left)).quantize(Decimal(quantum)) == Decimal(str(right)).quantize(Decimal(quantum))


def _ensure_product(session: Session, organization: Organization, spec: ProductSpec) -> tuple[Product, bool]:
    spec = _validate_product_spec(spec)
    product = session.scalar(
        select(Product).where(
            Product.organization_id == organization.id,
            Product.code == spec.code,
        )
    )
    if product is None:
        product = Product(
            organization_id=organization.id,
            code=spec.code,
            name=spec.name,
            product_type=spec.product_type,
            base_unit=spec.base_unit,
            package_weight=spec.package_weight,
            active=True,
        )
        session.add(product)
        session.flush()
        return product, True

    package_matches = (
        product.package_weight is None and spec.package_weight is None
    ) or (
        product.package_weight is not None
        and spec.package_weight is not None
        and _same_decimal(product.package_weight, spec.package_weight, "0.0001")
    )
    if not (
        product.active
        and product.name == spec.name
        and product.product_type == spec.product_type
        and product.base_unit == spec.base_unit
        and package_matches
    ):
        raise AdminOperationError(
            f"Produto '{spec.code}' já existe com configuração diferente; alteração silenciosa foi bloqueada."
        )
    return product, False


def _resolve_product(session: Session, organization_id: str, code: str) -> Product:
    product = session.scalar(
        select(Product).where(
            Product.organization_id == organization_id,
            Product.code == code,
            Product.active.is_(True),
        )
    )
    if product is None:
        raise AdminOperationError(f"Produto ativo '{code}' não encontrado.")
    return product


def _ensure_recipe(
    session: Session,
    organization: Organization,
    spec: RecipeSpec,
) -> tuple[Recipe, bool]:
    name = spec.name.strip()
    if not name:
        raise AdminOperationError("Fórmula exige nome.")
    output_qty = q_qty(Decimal(spec.output_quantity_per_batch))
    if output_qty <= 0:
        raise AdminOperationError("Produção por batida deve ser maior que zero.")
    if not spec.ingredients:
        raise AdminOperationError("Fórmula precisa de ao menos um ingrediente.")

    ingredient_codes = [row.product_code.strip() for row in spec.ingredients]
    if len(set(ingredient_codes)) != len(ingredient_codes):
        raise AdminOperationError("Ingrediente duplicado na fórmula.")

    output_product = _resolve_product(session, organization.id, spec.output_product_code.strip())
    desired_ingredients: dict[str, Decimal] = {}
    ingredient_products: dict[str, Product] = {}
    for row in spec.ingredients:
        code = row.product_code.strip()
        qty = q_qty(Decimal(row.quantity_per_batch))
        if qty <= 0:
            raise AdminOperationError(f"Quantidade inválida para ingrediente '{code}'.")
        product = _resolve_product(session, organization.id, code)
        desired_ingredients[product.id] = qty
        ingredient_products[product.id] = product

    recipe = session.scalar(
        select(Recipe).where(
            Recipe.organization_id == organization.id,
            Recipe.name == name,
        )
    )
    if recipe is None:
        recipe = Recipe(
            organization_id=organization.id,
            output_product_id=output_product.id,
            name=name,
            output_quantity_per_batch=output_qty,
            active=True,
        )
        session.add(recipe)
        session.flush()
        for product_id, qty in desired_ingredients.items():
            session.add(
                RecipeIngredient(
                    recipe_id=recipe.id,
                    product_id=product_id,
                    quantity_per_batch=qty,
                )
            )
        session.flush()
        return recipe, True

    existing_ingredients = {
        row.product_id: q_qty(Decimal(row.quantity_per_batch))
        for row in recipe.ingredients
    }
    if not (
        recipe.active
        and recipe.output_product_id == output_product.id
        and _same_decimal(recipe.output_quantity_per_batch, output_qty, "0.0001")
        and existing_ingredients == desired_ingredients
    ):
        raise AdminOperationError(
            f"Fórmula '{name}' já existe com configuração diferente; alteração silenciosa foi bloqueada."
        )
    return recipe, False


def _ensure_opening_stock(
    session: Session,
    *,
    organization: Organization,
    setup_id: str,
    spec: OpeningStockSpec,
) -> tuple[InventoryMovement, bool]:
    unit = session.scalar(
        select(Unit).where(
            Unit.organization_id == organization.id,
            Unit.code == spec.unit_code.strip(),
            Unit.active.is_(True),
        )
    )
    if unit is None:
        raise AdminOperationError(f"Unidade ativa '{spec.unit_code}' não encontrada.")
    product = _resolve_product(session, organization.id, spec.product_code.strip())
    quantity = q_qty(Decimal(spec.quantity))
    unit_cost = q_cost(Decimal(spec.unit_cost))
    if quantity <= 0:
        raise AdminOperationError("Saldo inicial precisa ser maior que zero.")
    if unit_cost < 0:
        raise AdminOperationError("Custo do saldo inicial não pode ser negativo.")

    rows = list(
        session.scalars(
            select(InventoryMovement).where(
                InventoryMovement.organization_id == organization.id,
                InventoryMovement.unit_id == unit.id,
                InventoryMovement.product_id == product.id,
                InventoryMovement.reference_type == "admin_opening_stock",
                InventoryMovement.reference_id == setup_id,
            )
        )
    )
    if len(rows) > 1:
        raise AdminOperationError(
            f"Mais de um movimento de saldo inicial encontrado para {unit.code}/{product.code}/{setup_id}."
        )
    if rows:
        movement = rows[0]
        if not (
            movement.movement_type == MovementType.ADJUSTMENT.value
            and _same_decimal(movement.quantity, quantity, "0.0001")
            and _same_decimal(movement.unit_cost, unit_cost, "0.000001")
        ):
            raise AdminOperationError(
                f"setup_id '{setup_id}' já foi usado com saldo diferente para {unit.code}/{product.code}."
            )
        return movement, False

    movement = receive_stock(
        session,
        organization_id=organization.id,
        unit_id=unit.id,
        product_id=product.id,
        quantity=quantity,
        unit_cost=unit_cost,
        movement_type=MovementType.ADJUSTMENT.value,
        reference_type="admin_opening_stock",
        reference_id=setup_id,
    )
    return movement, True


def configure_feed_mill(
    session: Session,
    *,
    organization_slug: str,
    setup_id: str,
    products: tuple[ProductSpec, ...],
    recipe: RecipeSpec,
    opening_stocks: tuple[OpeningStockSpec, ...] = (),
) -> FeedMillSetupResult:
    organization = _organization(session, organization_slug)
    require_module(session, organization.id, ModuleCode.FEED_MILL.value)
    setup_id = _normalize_setup_id(setup_id)

    codes = [spec.code.strip() for spec in products]
    if len(set(codes)) != len(codes):
        raise AdminOperationError("Código de produto duplicado na configuração.")

    created_product_codes: list[str] = []
    for spec in products:
        product, created = _ensure_product(session, organization, spec)
        if created:
            created_product_codes.append(product.code)

    recipe_row, recipe_created = _ensure_recipe(session, organization, recipe)

    created_stock_movements: list[str] = []
    for stock in opening_stocks:
        movement, created = _ensure_opening_stock(
            session,
            organization=organization,
            setup_id=setup_id,
            spec=stock,
        )
        if created:
            created_stock_movements.append(movement.id)

    if created_product_codes or recipe_created or created_stock_movements:
        record_audit(
            session,
            organization_id=organization.id,
            action="feed_mill_admin_setup_applied",
            details={
                "setup_id": setup_id,
                "created_product_codes": created_product_codes,
                "recipe_id": recipe_row.id,
                "recipe_created": recipe_created,
                "created_stock_movement_ids": created_stock_movements,
            },
        )

    return FeedMillSetupResult(
        organization_id=organization.id,
        recipe_id=recipe_row.id,
        created_product_codes=tuple(created_product_codes),
        recipe_created=recipe_created,
        created_stock_movements=tuple(created_stock_movements),
        setup_id=setup_id,
    )
