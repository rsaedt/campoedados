from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation

from app.core.database import SessionLocal
from app.services.admin_ops import (
    AdminOperationError,
    IngredientSpec,
    OpeningStockSpec,
    ProductSpec,
    RecipeSpec,
    configure_feed_mill,
)


def _decimal(value: str, label: str) -> Decimal:
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"{label} inválido: {value}") from exc


def _product(value: str) -> ProductSpec:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) not in {4, 5}:
        raise argparse.ArgumentTypeError(
            "Use --product 'CODIGO|Nome|raw_material|kg' ou acrescente '|peso_embalagem'."
        )
    package_weight = _decimal(parts[4], "peso de embalagem") if len(parts) == 5 and parts[4] else None
    return ProductSpec(
        code=parts[0],
        name=parts[1],
        product_type=parts[2],
        base_unit=parts[3],
        package_weight=package_weight,
    )


def _ingredient(value: str) -> IngredientSpec:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Use --ingredient 'CODIGO=quantidade_por_batida'.")
    code, quantity = value.split("=", 1)
    return IngredientSpec(
        product_code=code.strip(),
        quantity_per_batch=_decimal(quantity.strip(), "quantidade do ingrediente"),
    )


def _stock(value: str) -> OpeningStockSpec:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "Use --stock 'UNIDADE|PRODUTO|quantidade|custo_unitario'."
        )
    return OpeningStockSpec(
        unit_code=parts[0],
        product_code=parts[1],
        quantity=_decimal(parts[2], "quantidade do saldo"),
        unit_cost=_decimal(parts[3], "custo unitário"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Cria ou valida dados mestres da Fábrica de Ração e registra saldo inicial "
            "sem colocar dados de cliente em ENV ou no código."
        )
    )
    parser.add_argument("--org-slug", required=True, help="Slug da organização.")
    parser.add_argument(
        "--setup-id",
        required=True,
        help="UUID único desta carga. Reutilizar o mesmo UUID não duplica saldo.",
    )
    parser.add_argument(
        "--product",
        action="append",
        type=_product,
        required=True,
        help="Produto: 'CODIGO|Nome|raw_material|kg' ou finished_good.",
    )
    parser.add_argument("--recipe-name", required=True, help="Nome da fórmula.")
    parser.add_argument("--output-product-code", required=True, help="Código do produto acabado.")
    parser.add_argument(
        "--output-quantity",
        required=True,
        type=lambda value: _decimal(value, "produção por batida"),
        help="Quantidade produzida por batida, na unidade-base do produto acabado.",
    )
    parser.add_argument(
        "--ingredient",
        action="append",
        type=_ingredient,
        required=True,
        help="Ingrediente: 'CODIGO=quantidade_por_batida'.",
    )
    parser.add_argument(
        "--stock",
        action="append",
        type=_stock,
        default=[],
        help="Saldo inicial: 'UNIDADE|PRODUTO|quantidade|custo_unitario'. Repita conforme necessário.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    recipe = RecipeSpec(
        name=args.recipe_name,
        output_product_code=args.output_product_code,
        output_quantity_per_batch=args.output_quantity,
        ingredients=tuple(args.ingredient),
    )
    with SessionLocal() as session:
        try:
            result = configure_feed_mill(
                session,
                organization_slug=args.org_slug,
                setup_id=args.setup_id,
                products=tuple(args.product),
                recipe=recipe,
                opening_stocks=tuple(args.stock),
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    print("feed mill setup: OK")
    print(f"organization_id={result.organization_id}")
    print(f"setup_id={result.setup_id}")
    print(f"recipe_id={result.recipe_id}")
    print("created_products=" + ",".join(result.created_product_codes))
    print(f"recipe_created={str(result.recipe_created).lower()}")
    print(f"created_stock_movements={len(result.created_stock_movements)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AdminOperationError, ValueError) as exc:
        print(f"feed mill setup failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
