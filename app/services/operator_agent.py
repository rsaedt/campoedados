from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ModuleCode, TransferStatus
from app.models.domain import Product, Recipe, Transfer, Unit
from app.services.modules import module_enabled


NUMBER_WORDS = {
    "um": Decimal("1"), "uma": Decimal("1"),
    "dois": Decimal("2"), "duas": Decimal("2"),
    "tres": Decimal("3"), "quatro": Decimal("4"), "cinco": Decimal("5"),
    "seis": Decimal("6"), "sete": Decimal("7"), "oito": Decimal("8"),
    "nove": Decimal("9"), "dez": Decimal("10"),
}


@dataclass(frozen=True)
class OperatorInterpretation:
    intent: str
    event_type: str
    target_modules: list[str]
    permission_modules: list[str]
    confidence: Decimal
    data: dict
    missing_fields: list[str]
    question: str | None = None


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", no_marks).strip()


def _number_token(token: str) -> Decimal:
    normalized = normalize_text(token)
    if normalized in NUMBER_WORDS:
        return NUMBER_WORDS[normalized]
    return Decimal(normalized.replace(",", "."))


def _parse_batch_count(text: str) -> Decimal | None:
    normalized = normalize_text(text)
    match = re.search(
        r"\b(\d+(?:[.,]\d+)?|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)\s+batidas?\b",
        normalized,
    )
    return _number_token(match.group(1)) if match else None


def _parse_quantity(text: str) -> tuple[Decimal | None, str | None]:
    normalized = normalize_text(text)
    match = re.search(
        r"\b(\d+(?:[.,]\d+)?|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)\s*"
        r"(sacos?|kg|quilos?|quilogramas?|t|ton|tons|toneladas?)\b",
        normalized,
    )
    if not match:
        return None, None
    qty = _number_token(match.group(1))
    unit = match.group(2)
    if unit.startswith("saco"):
        return qty, "sack"
    if unit in {"t", "ton", "tons"} or unit.startswith("tonelada"):
        return qty, "t"
    return qty, "kg"


def _resolve_recipe(session: Session, organization_id: str, text: str) -> Recipe | None:
    normalized = normalize_text(text)
    recipes = list(
        session.scalars(
            select(Recipe).where(
                Recipe.organization_id == organization_id,
                Recipe.active.is_(True),
            )
        )
    )
    matches = [recipe for recipe in recipes if normalize_text(recipe.name) in normalized]
    if not matches:
        return None
    matches.sort(key=lambda recipe: len(normalize_text(recipe.name)), reverse=True)
    return matches[0]


def _resolve_product(session: Session, organization_id: str, text: str, *, explicit_name: str | None = None) -> Product | None:
    haystack = normalize_text(explicit_name or text)
    products = list(
        session.scalars(
            select(Product).where(
                Product.organization_id == organization_id,
                Product.active.is_(True),
            )
        )
    )
    matches = []
    for product in products:
        name = normalize_text(product.name)
        code = normalize_text(product.code)
        if (name and name in haystack) or (code and code in haystack):
            matches.append(product)
    if not matches:
        return None
    matches.sort(key=lambda product: len(normalize_text(product.name)), reverse=True)
    return matches[0]


def _resolve_destination_unit(session: Session, organization_id: str, text: str, source_unit_id: str) -> Unit | None:
    normalized = normalize_text(text)
    units = list(
        session.scalars(
            select(Unit).where(
                Unit.organization_id == organization_id,
                Unit.active.is_(True),
                Unit.id != source_unit_id,
            )
        )
    )
    matches = [
        unit for unit in units
        if normalize_text(unit.code) in normalized or normalize_text(unit.name) in normalized
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _to_base_quantity(product: Product | None, quantity: Decimal | None, unit: str | None) -> tuple[Decimal | None, str | None]:
    if quantity is None or unit is None:
        return None, None
    if unit == "kg":
        return quantity, None
    if unit == "t":
        return quantity * Decimal("1000"), None
    if unit == "sack":
        if product is None or product.package_weight is None:
            return None, "package_weight"
        return quantity * Decimal(product.package_weight), None
    return None, "quantity_unit"


def _interpret_production(session: Session, organization_id: str, text: str) -> OperatorInterpretation:
    recipe = _resolve_recipe(session, organization_id, text)
    batch_count = _parse_batch_count(text)
    missing = []
    if recipe is None:
        missing.append("recipe")
    if batch_count is None:
        missing.append("batch_count")
    if missing == ["recipe"]:
        question = "Qual foi a fórmula/ração produzida?"
    elif missing == ["batch_count"]:
        question = "Quantas batidas foram feitas?"
    elif missing:
        question = "Qual fórmula foi produzida e quantas batidas foram feitas?"
    else:
        question = None
    return OperatorInterpretation(
        intent="feed_mill_production",
        event_type="feed_mill.production",
        target_modules=[ModuleCode.FEED_MILL.value],
        permission_modules=[ModuleCode.FEED_MILL.value],
        confidence=Decimal("0.9900") if not missing else Decimal("0.7000"),
        data={
            "recipe_id": recipe.id if recipe else None,
            "recipe_name": recipe.name if recipe else None,
            "batch_count": str(batch_count) if batch_count is not None else None,
        },
        missing_fields=missing,
        question=question,
    )


def _interpret_transfer_dispatch(session: Session, organization_id: str, unit_id: str, text: str) -> OperatorInterpretation:
    product = _resolve_product(session, organization_id, text)
    destination = _resolve_destination_unit(session, organization_id, text, unit_id)
    qty, qty_unit = _parse_quantity(text)
    base_qty, conversion_error = _to_base_quantity(product, qty, qty_unit)
    missing = []
    if product is None:
        missing.append("product")
    if qty is None:
        missing.append("quantity")
    if conversion_error:
        missing.append(conversion_error)
    if destination is None:
        missing.append("destination_unit")
    question = None
    if missing:
        questions = {
            "product": "Qual produto foi carregado?",
            "quantity": "Qual quantidade foi carregada?",
            "package_weight": "Qual é o peso de cada saco desse produto?",
            "destination_unit": "Para qual fazenda/unidade foi carregado?",
        }
        if len(missing) == 1:
            question = questions.get(missing[0], "Qual informação está faltando na transferência?")
        else:
            question = "Preciso do produto, quantidade e destino da transferência."
    return OperatorInterpretation(
        intent="feed_mill_transfer_dispatch",
        event_type="feed_mill.transfer_dispatch",
        target_modules=[ModuleCode.FEED_MILL.value],
        permission_modules=[ModuleCode.FEED_MILL.value],
        confidence=Decimal("0.9800") if not missing else Decimal("0.6800"),
        data={
            "product_id": product.id if product else None,
            "product_name": product.name if product else None,
            "quantity_input": str(qty) if qty is not None else None,
            "quantity_unit": qty_unit,
            "base_quantity": str(base_qty) if base_qty is not None else None,
            "destination_unit_id": destination.id if destination else None,
            "destination_unit_code": destination.code if destination else None,
        },
        missing_fields=missing,
        question=question,
    )


def _interpret_transfer_receipt(session: Session, organization_id: str, unit_id: str, text: str) -> OperatorInterpretation | None:
    candidates = list(
        session.scalars(
            select(Transfer).where(
                Transfer.organization_id == organization_id,
                Transfer.destination_unit_id == unit_id,
                Transfer.status.in_([TransferStatus.IN_TRANSIT.value, TransferStatus.DIVERGENT.value]),
            )
        )
    )
    if not candidates:
        return None
    product = _resolve_product(session, organization_id, text)
    qty, qty_unit = _parse_quantity(text)
    filtered = candidates
    if product is not None:
        filtered = [row for row in filtered if row.product_id == product.id]
    if len(filtered) == 1:
        transfer = filtered[0]
        transfer_product = session.get(Product, transfer.product_id)
        base_qty, conversion_error = _to_base_quantity(transfer_product, qty, qty_unit) if qty else (Decimal(transfer.quantity), None)
        missing = [conversion_error] if conversion_error else []
        return OperatorInterpretation(
            intent="feed_mill_transfer_receipt",
            event_type="feed_mill.transfer_receipt",
            target_modules=[ModuleCode.FEED_MILL.value],
            permission_modules=[ModuleCode.FEED_MILL.value],
            confidence=Decimal("0.9700") if not missing else Decimal("0.6800"),
            data={
                "transfer_id": transfer.id,
                "product_id": transfer.product_id,
                "product_name": transfer_product.name if transfer_product else None,
                "received_quantity": str(base_qty) if base_qty is not None else None,
                "quantity_input": str(qty) if qty is not None else None,
                "quantity_unit": qty_unit,
            },
            missing_fields=missing,
            question="Qual é o peso de cada saco desse produto?" if missing else None,
        )
    return OperatorInterpretation(
        intent="feed_mill_transfer_receipt",
        event_type="feed_mill.transfer_receipt",
        target_modules=[ModuleCode.FEED_MILL.value],
        permission_modules=[ModuleCode.FEED_MILL.value],
        confidence=Decimal("0.6000"),
        data={},
        missing_fields=["transfer"],
        question="Qual produto/transferência chegou? Há mais de uma carga em trânsito para esta unidade.",
    )


def _interpret_invoice_receipt(
    session: Session,
    organization_id: str,
    text: str,
    document_data: dict,
) -> OperatorInterpretation:
    product = _resolve_product(
        session,
        organization_id,
        text,
        explicit_name=document_data.get("product_name"),
    )
    invoice_qty_raw = document_data.get("quantity")
    received_qty_raw = document_data.get("received_quantity", invoice_qty_raw)
    unit = document_data.get("unit", "kg") if received_qty_raw is not None else None
    try:
        received_qty = Decimal(str(received_qty_raw).replace(",", ".")) if received_qty_raw is not None else None
        invoice_qty = Decimal(str(invoice_qty_raw).replace(",", ".")) if invoice_qty_raw is not None else None
    except Exception:
        received_qty = None
        invoice_qty = None
    normalized_unit = normalize_text(str(unit)) if unit else None
    base_qty, conversion_error = _to_base_quantity(product, received_qty, normalized_unit)
    invoice_base_qty, _ = _to_base_quantity(product, invoice_qty, normalized_unit) if invoice_qty is not None else (None, None)
    unit_cost_raw = document_data.get("unit_cost")
    total_raw = document_data.get("total_amount")
    unit_cost = Decimal(str(unit_cost_raw).replace(",", ".")) if unit_cost_raw is not None else None
    total = Decimal(str(total_raw).replace(",", ".")) if total_raw is not None else None
    if unit_cost is None and total is not None and base_qty:
        unit_cost = total / base_qty
    if total is None and unit_cost is not None and base_qty:
        total = unit_cost * base_qty

    finance_enabled = module_enabled(session, organization_id, ModuleCode.FINANCE.value)
    missing = []
    if product is None:
        missing.append("product")
    if base_qty is None:
        missing.append(conversion_error or "quantity")
    if unit_cost is None:
        missing.append("unit_cost")
    if finance_enabled:
        for key in ("supplier_name", "invoice_number"):
            if not document_data.get(key):
                missing.append(key)
        installments = document_data.get("installments") or []
        if not installments:
            missing.append("installments")
        elif total is not None:
            try:
                installment_total = sum(
                    (Decimal(str(row.get("amount", "0")).replace(",", ".")) for row in installments),
                    Decimal("0"),
                )
                if installment_total.quantize(Decimal("0.01")) != total.quantize(Decimal("0.01")):
                    missing.append("installment_total")
            except Exception:
                missing.append("installment_total")

    if len(missing) == 1:
        qmap = {
            "product": "Qual produto consta na nota?",
            "quantity": "Qual quantidade foi recebida?",
            "package_weight": "Qual é o peso de cada saco desse produto?",
            "unit_cost": "Qual é o valor unitário do produto na nota?",
            "supplier_name": "Qual é o fornecedor da nota?",
            "invoice_number": "Qual é o número da nota fiscal?",
            "installments": "Quais são os vencimentos/parcelas desta compra?",
            "installment_total": "A soma das parcelas não fecha com o total da nota. Qual é o parcelamento correto?",
        }
        question = qmap.get(missing[0], "Preciso de uma informação adicional da nota fiscal.")
    elif missing:
        question = "A leitura da nota está incompleta. Preciso complementar os dados da compra antes de processar."
    else:
        question = None

    targets = [ModuleCode.FEED_MILL.value]
    if finance_enabled:
        targets.append(ModuleCode.FINANCE.value)
    discrepancy = None
    if invoice_base_qty is not None and base_qty is not None:
        discrepancy = base_qty - invoice_base_qty

    return OperatorInterpretation(
        intent="feed_mill_material_receipt",
        event_type="feed_mill.material_receipt",
        target_modules=targets,
        permission_modules=[ModuleCode.FEED_MILL.value],
        confidence=Decimal("0.9900") if not missing else Decimal("0.6500"),
        data={
            "product_id": product.id if product else None,
            "product_name": product.name if product else document_data.get("product_name"),
            "quantity": str(base_qty) if base_qty is not None else None,
            "unit_cost": str(unit_cost) if unit_cost is not None else None,
            "total_amount": str(total) if total is not None else None,
            "supplier_name": document_data.get("supplier_name"),
            "supplier_document": document_data.get("supplier_document"),
            "invoice_number": document_data.get("invoice_number"),
            "issue_date": document_data.get("issue_date"),
            "installments": document_data.get("installments") or [],
            "invoice_quantity": str(invoice_base_qty) if invoice_base_qty is not None else None,
            "received_quantity": str(base_qty) if base_qty is not None else None,
            "quantity_discrepancy": str(discrepancy) if discrepancy is not None else None,
            "has_nonconformity": bool(discrepancy is not None and discrepancy != 0),
        },
        missing_fields=missing,
        question=question,
    )


def interpret_operator_message(
    session: Session,
    organization_id: str,
    unit_id: str,
    text: str,
    *,
    document_data: dict | None = None,
    document_type: str | None = None,
) -> OperatorInterpretation:
    normalized = normalize_text(text)
    document_data = document_data or {}

    invoice_markers = ("segue nf", "nota fiscal", "segue nota", "nf ", "nf.")
    if document_type == "invoice" or any(marker in normalized for marker in invoice_markers):
        return _interpret_invoice_receipt(session, organization_id, text, document_data)

    dispatch_markers = ("carreguei", "carregamos", "enviei", "enviamos", "mandei", "transferi", "carregado")
    if any(marker in normalized for marker in dispatch_markers):
        return _interpret_transfer_dispatch(session, organization_id, unit_id, text)

    receipt_markers = ("chegou", "chegaram", "recebi", "recebemos", "descarregou", "descarregamos")
    if any(marker in normalized for marker in receipt_markers):
        receipt = _interpret_transfer_receipt(session, organization_id, unit_id, text)
        if receipt is not None:
            return receipt

    production_markers = ("batida", "producao", "produzi", "fabricamos", "fizemos")
    if any(marker in normalized for marker in production_markers):
        return _interpret_production(session, organization_id, text)

    return OperatorInterpretation(
        intent="unknown",
        event_type="unclassified",
        target_modules=[],
        permission_modules=[],
        confidence=Decimal("0.2000"),
        data={},
        missing_fields=["intent"],
        question="Não consegui identificar a operação. O que aconteceu no campo?",
    )
