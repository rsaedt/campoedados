from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.schemas.media import MediaProcessingResponse
from app.services.auth import Principal
from app.services.media_storage import FileSystemMediaStorage, MediaTooLargeError, get_media_storage
from app.services.multimodal import InvalidInvoiceMediaError, process_audio_media, process_invoice_media
from app.services.openai_multimodal import MultimodalAI, get_multimodal_ai
from app.services.permissions import PermissionDeniedError


router = APIRouter(prefix="/v1/operator/media", tags=["operator-media"])

INVOICE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
AUDIO_MIME_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/m4a", "audio/x-m4a",
    "audio/ogg", "audio/wav", "audio/x-wav", "audio/webm", "video/webm",
}


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    content = await file.read()
    mime_type = (file.content_type or "application/octet-stream").lower()
    return content, mime_type


@router.post("/invoice", response_model=MediaProcessingResponse)
async def post_invoice_media(
    unit_code: str = Form(...),
    file: UploadFile = File(...),
    text: str = Form(default="Chegou material, segue NF."),
    channel: str = Form(default="api"),
    external_id: str | None = Form(default=None),
    received_quantity: str | None = Form(default=None),
    received_unit: str | None = Form(default=None),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    ai: MultimodalAI = Depends(get_multimodal_ai),
    storage: FileSystemMediaStorage = Depends(get_media_storage),
):
    content, mime_type = await _read_upload(file)
    if mime_type not in INVOICE_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"Tipo de arquivo não suportado para NF: {mime_type}")
    try:
        stored = storage.store(content=content, filename=file.filename, mime_type=mime_type)
        extraction = ai.extract_invoice(content=content, mime_type=mime_type, filename=file.filename)
        event = process_invoice_media(
            session,
            principal=principal,
            text=text,
            unit_code=unit_code,
            channel=channel,
            external_id=external_id,
            filename=file.filename,
            mime_type=mime_type,
            storage_ref=stored.storage_ref,
            sha256=stored.sha256,
            extraction=extraction,
            received_quantity=received_quantity,
            received_unit=received_unit,
        )
        session.commit()
        return MediaProcessingResponse(
            source_type="invoice",
            filename=file.filename,
            mime_type=mime_type,
            storage_ref=stored.storage_ref,
            sha256=stored.sha256,
            extraction=extraction,
            event=event,
        )
    except (MediaTooLargeError, InvalidInvoiceMediaError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Falha ao processar mídia: {exc}") from exc


@router.post("/audio", response_model=MediaProcessingResponse)
async def post_audio_media(
    unit_code: str = Form(...),
    file: UploadFile = File(...),
    channel: str = Form(default="api"),
    external_id: str | None = Form(default=None),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    ai: MultimodalAI = Depends(get_multimodal_ai),
    storage: FileSystemMediaStorage = Depends(get_media_storage),
):
    content, mime_type = await _read_upload(file)
    if mime_type not in AUDIO_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"Tipo de áudio não suportado: {mime_type}")
    try:
        stored = storage.store(content=content, filename=file.filename, mime_type=mime_type)
        transcript = ai.transcribe_audio(content=content, mime_type=mime_type, filename=file.filename)
        if not transcript:
            raise ValueError("Não foi possível obter uma transcrição do áudio.")
        event = process_audio_media(
            session,
            principal=principal,
            transcript=transcript,
            unit_code=unit_code,
            channel=channel,
            external_id=external_id,
            filename=file.filename,
            mime_type=mime_type,
            storage_ref=stored.storage_ref,
            sha256=stored.sha256,
        )
        session.commit()
        return MediaProcessingResponse(
            source_type="audio",
            filename=file.filename,
            mime_type=mime_type,
            storage_ref=stored.storage_ref,
            sha256=stored.sha256,
            transcript=transcript,
            event=event,
        )
    except (MediaTooLargeError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Falha ao processar áudio: {exc}") from exc
