from __future__ import annotations

import base64
import io
import json
import os
from typing import Protocol

from openai import OpenAI


class MultimodalAI(Protocol):
    def extract_invoice(self, *, content: bytes, mime_type: str, filename: str | None = None) -> dict: ...
    def transcribe_audio(self, *, content: bytes, mime_type: str, filename: str | None = None) -> str: ...


INVOICE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "document_kind": {"type": "string", "enum": ["invoice", "other"]},
        "supplier_name": {"type": ["string", "null"]},
        "supplier_document": {"type": ["string", "null"]},
        "invoice_number": {"type": ["string", "null"]},
        "issue_date": {"type": ["string", "null"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "product_name": {"type": ["string", "null"]},
                    "quantity": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "unit_cost": {"type": ["number", "null"]},
                    "total_amount": {"type": ["number", "null"]},
                },
                "required": ["product_name", "quantity", "unit", "unit_cost", "total_amount"],
            },
        },
        "invoice_total": {"type": ["number", "null"]},
        "installments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "due_date": {"type": ["string", "null"]},
                    "amount": {"type": ["number", "null"]},
                },
                "required": ["due_date", "amount"],
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "notes": {"type": ["string", "null"]},
    },
    "required": [
        "document_kind", "supplier_name", "supplier_document", "invoice_number", "issue_date",
        "items", "invoice_total", "installments", "confidence", "notes"
    ],
}


class OpenAIMultimodalAI:
    def __init__(self, client: OpenAI | None = None):
        self.client = client or OpenAI()
        self.vision_model = os.getenv("CAMPOEDADOS_OPENAI_VISION_MODEL", "gpt-5-mini")
        self.transcribe_model = os.getenv("CAMPOEDADOS_OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")

    def extract_invoice(self, *, content: bytes, mime_type: str, filename: str | None = None) -> dict:
        encoded = base64.b64encode(content).decode("ascii")
        instructions = (
            "Leia este documento fiscal brasileiro. Extraia somente informações visíveis no documento. "
            "Não invente vencimentos, parcelas, quantidades, valores, CNPJ/CPF ou nomes. "
            "Para itens, mantenha a unidade como impressa (kg, t, sc, saco, un etc.). "
            "Se algo não estiver legível ou não existir, retorne null ou lista vazia."
        )

        if mime_type == "application/pdf":
            media_part = {
                "type": "input_file",
                "filename": filename or "nota.pdf",
                "file_data": f"data:application/pdf;base64,{encoded}",
            }
        else:
            media_part = {
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{encoded}",
                "detail": "high",
            }

        response = self.client.responses.create(
            model=self.vision_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": instructions},
                        media_part,
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "campoedados_invoice_extraction",
                    "strict": True,
                    "schema": INVOICE_SCHEMA,
                }
            },
        )
        return json.loads(response.output_text)

    def transcribe_audio(self, *, content: bytes, mime_type: str, filename: str | None = None) -> str:
        audio_file = io.BytesIO(content)
        audio_file.name = filename or "audio.webm"
        transcript = self.client.audio.transcriptions.create(
            model=self.transcribe_model,
            file=audio_file,
            language="pt",
            prompt="Contexto rural e agropecuário brasileiro. Termos possíveis: ração, batida, milho, farelo, ureia, núcleo, fazenda, lote, saco, NSG, SH7.",
        )
        return transcript.text.strip()


def get_multimodal_ai() -> MultimodalAI:
    return OpenAIMultimodalAI()
