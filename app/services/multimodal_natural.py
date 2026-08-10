from sqlalchemy.orm import Session

from app.schemas.operator import OperatorDocumentInput, OperatorMessageRequest, OperatorMessageResponse
from app.services.auth import Principal
from app.services.multimodal import _duplicate_by_sha
from app.services.operator import _existing_event_response
from app.services.operator_natural import handle_operator_message_natural


def process_audio_media_natural(
    session: Session,
    *,
    principal: Principal,
    transcript: str,
    unit_code: str,
    channel: str,
    external_id: str | None,
    filename: str | None,
    mime_type: str,
    storage_ref: str,
    sha256: str,
) -> OperatorMessageResponse:
    duplicate = _duplicate_by_sha(session, principal.organization_id, sha256)
    if duplicate is not None:
        return _existing_event_response(session, duplicate)
    return handle_operator_message_natural(
        session,
        principal=principal,
        request=OperatorMessageRequest(
            text=transcript,
            unit_code=unit_code,
            channel=channel,
            source_type="audio",
            external_id=external_id,
            document=OperatorDocumentInput(
                document_type="audio",
                filename=filename,
                mime_type=mime_type,
                storage_ref=storage_ref,
                sha256=sha256,
                extracted_data={"transcript": transcript},
            ),
        ),
    )
