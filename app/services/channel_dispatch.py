from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy.orm import Session

from app.schemas.operator import OperatorMessageRequest, OperatorMessageResponse
from app.services.channel_identity import UnknownChannelIdentityError, resolve_channel_identity
from app.services.channels.base import ChannelDispatchResult, ChannelTransport, InboundChannelMessage
from app.services.media_storage import FileSystemMediaStorage
from app.services.multimodal import process_audio_media, process_invoice_media
from app.services.openai_multimodal import MultimodalAI
from app.services.operator import handle_operator_message


UNKNOWN_CONTACT_REPLY = (
    "Este contato ainda não está vinculado a uma empresa/unidade no Campo e Dados. "
    "Peça ao administrador para concluir o cadastro antes de registrar operações."
)


def _format_decimal(value) -> str:
    if value is None:
        return ""
    d = Decimal(str(value))
    text = f"{d:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return text


def format_operator_reply(response: OperatorMessageResponse) -> str:
    if response.question:
        prefix = "⚠️ " if response.status in {"waiting_manager", "waiting_complement"} else ""
        return prefix + response.question

    if response.production:
        p = response.production
        return (
            f"✅ Produção registrada: {_format_decimal(p.batch_count)} batida(s) de {p.recipe_name}. "
            f"Produção {_format_decimal(p.output_quantity)} kg. "
            f"Custo bruto aproximado R$ {_format_decimal(p.total_material_cost)}."
        )

    if response.transfer:
        t = response.transfer
        if t.status == "in_transit":
            declared = (
                f"{_format_decimal(t.declared_quantity)} {t.declared_unit}"
                if t.declared_quantity is not None and t.declared_unit
                else f"{_format_decimal(t.dispatched_quantity)} kg"
            )
            return (
                f"✅ Transferência registrada: {declared} de {t.product_name} "
                f"de {t.source_unit_code} para {t.destination_unit_code}. "
                f"Valor transportado R$ {_format_decimal(t.total_value)}."
            )
        if t.status == "divergent":
            return (
                f"⚠️ Recebimento divergente: enviado {_format_decimal(t.dispatched_quantity)} kg "
                f"e recebido {_format_decimal(t.received_quantity)} kg. "
                "A operação foi encaminhada ao Gerencial."
            )
        return (
            f"✅ Transferência recebida em {t.destination_unit_code}: "
            f"{_format_decimal(t.received_quantity or t.dispatched_quantity)} kg de {t.product_name}."
        )

    if response.purchase:
        p = response.purchase
        return (
            f"✅ Entrada física registrada. NF {p.invoice_number}, fornecedor {p.supplier_name}. "
            f"Valor R$ {_format_decimal(p.total_amount)}. "
            "A compra está aguardando aprovação gerencial."
        )

    if response.status == "waiting_manager":
        return "⚠️ Informação registrada e encaminhada ao Gerencial para aprovação."
    if response.status == "waiting_complement":
        return response.reason or "⚠️ Informação registrada parcialmente; há dados que precisam ser complementados."
    if response.reason:
        return f"⚠️ {response.reason}"
    return "✅ Informação registrada no Campo e Dados."


def _received_hint(text: str) -> tuple[str | None, str | None]:
    normalized = text.casefold()
    match = re.search(
        r"(?:receb(?:emos|ido|eu)|cheg(?:ou|aram))\D{0,30}(\d+(?:[.,]\d+)?)\s*(kg|quilos?|t|ton|toneladas?)\b",
        normalized,
    )
    if not match:
        return None, None
    qty = match.group(1).replace(",", ".")
    unit = match.group(2)
    if unit.startswith("quilo"):
        unit = "kg"
    elif unit in {"ton", "tonelada", "toneladas"}:
        unit = "t"
    return qty, unit


def dispatch_channel_message(
    session: Session,
    *,
    inbound: InboundChannelMessage,
    transport: ChannelTransport,
    ai: MultimodalAI,
    storage: FileSystemMediaStorage,
) -> ChannelDispatchResult:
    try:
        resolved = resolve_channel_identity(
            session,
            channel=inbound.channel,
            account_key=inbound.account_key,
            external_user_id=inbound.external_user_id,
        )
    except UnknownChannelIdentityError:
        return ChannelDispatchResult(reply_text=UNKNOWN_CONTACT_REPLY, unknown_identity=True)

    principal = resolved.principal
    unit = resolved.unit

    if inbound.media is None:
        response = handle_operator_message(
            session,
            principal=principal,
            request=OperatorMessageRequest(
                text=inbound.text or "Mensagem sem texto.",
                unit_code=unit.code,
                channel=inbound.channel,
                source_type="text",
                external_id=inbound.external_id,
            ),
        )
    else:
        downloaded = transport.download_media(inbound.account_key, inbound.media)
        stored = storage.store(
            content=downloaded.content,
            filename=downloaded.filename or inbound.media.filename,
            mime_type=downloaded.mime_type,
        )
        if inbound.media.kind == "audio":
            transcript = ai.transcribe_audio(
                content=downloaded.content,
                mime_type=downloaded.mime_type,
                filename=downloaded.filename or inbound.media.filename,
            )
            if not transcript:
                raise ValueError("Não foi possível transcrever o áudio recebido.")
            response = process_audio_media(
                session,
                principal=principal,
                transcript=transcript,
                unit_code=unit.code,
                channel=inbound.channel,
                external_id=inbound.external_id,
                filename=downloaded.filename or inbound.media.filename,
                mime_type=downloaded.mime_type,
                storage_ref=stored.storage_ref,
                sha256=stored.sha256,
            )
        elif inbound.media.kind in {"image", "document"} and (
            downloaded.mime_type.startswith("image/") or downloaded.mime_type == "application/pdf"
        ):
            extraction = ai.extract_invoice(
                content=downloaded.content,
                mime_type=downloaded.mime_type,
                filename=downloaded.filename or inbound.media.filename,
            )
            received_quantity, received_unit = _received_hint(inbound.text)
            response = process_invoice_media(
                session,
                principal=principal,
                text=inbound.text or "Chegou material, segue NF.",
                unit_code=unit.code,
                channel=inbound.channel,
                external_id=inbound.external_id,
                filename=downloaded.filename or inbound.media.filename,
                mime_type=downloaded.mime_type,
                storage_ref=stored.storage_ref,
                sha256=stored.sha256,
                extraction=extraction,
                received_quantity=received_quantity,
                received_unit=received_unit,
            )
        else:
            return ChannelDispatchResult(
                reply_text="⚠️ Recebi o arquivo, mas este tipo ainda não é aceito para lançamento automático."
            )

    return ChannelDispatchResult(
        reply_text=format_operator_reply(response),
        event_id=response.event_id,
        status=response.status,
    )
