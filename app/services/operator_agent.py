from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ModuleCode
from app.models.domain import Recipe


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
    confidence: Decimal
    data: dict
    missing_fields: list[str]
    question: str | None = None


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", no_marks).strip()


def _parse_batch_count(text: str) -> Decimal | None:
    normalized = normalize_text(text)
    match = re.search(
        r"\b(\d+(?:[.,]\d+)?|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)\s+batidas?\b",
        normalized,
    )
    if not match:
        return None
    token = match.group(1)
    if token in NUMBER_WORDS:
        return NUMBER_WORDS[token]
    return Decimal(token.replace(",", "."))


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


def interpret_operator_message(session: Session, organization_id: str, text: str) -> OperatorInterpretation:
    normalized = normalize_text(text)
    production_markers = ("batida", "producao", "produzi", "fabricamos", "fizemos")
    looks_like_production = any(marker in normalized for marker in production_markers)

    if not looks_like_production:
        return OperatorInterpretation(
            intent="unknown",
            event_type="unclassified",
            target_modules=[],
            confidence=Decimal("0.2000"),
            data={},
            missing_fields=["intent"],
            question="Não consegui identificar a operação. O que aconteceu no campo?",
        )

    recipe = _resolve_recipe(session, organization_id, text)
    batch_count = _parse_batch_count(text)
    missing = []
    if recipe is None:
        missing.append("recipe")
    if batch_count is None:
        missing.append("batch_count")

    question = None
    if missing == ["recipe"]:
        question = "Qual foi a fórmula/ração produzida?"
    elif missing == ["batch_count"]:
        question = "Quantas batidas foram feitas?"
    elif missing:
        question = "Qual fórmula foi produzida e quantas batidas foram feitas?"

    data = {
        "recipe_id": recipe.id if recipe else None,
        "recipe_name": recipe.name if recipe else None,
        "batch_count": str(batch_count) if batch_count is not None else None,
    }
    return OperatorInterpretation(
        intent="feed_mill_production",
        event_type="feed_mill.production",
        target_modules=[ModuleCode.FEED_MILL.value],
        confidence=Decimal("0.9900") if not missing else Decimal("0.7000"),
        data=data,
        missing_fields=missing,
        question=question,
    )
