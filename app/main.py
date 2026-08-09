import os

from fastapi import FastAPI, Response, status

from app.api.admin_channel_accounts import router as admin_channel_accounts_router
from app.api.admin_channels import router as admin_channels_router
from app.api.channels import router as channels_router
from app.api.manager import router as manager_router
from app.api.media import router as media_router
from app.api.me import router as me_router
from app.api.operator import router as operator_router
from app.core.database import database_is_ready
from app.services.media_storage import media_storage_backend, media_storage_is_configured

app = FastAPI(title="Campo e Dados", version="0.6.1")
app.include_router(me_router)
app.include_router(operator_router)
app.include_router(media_router)
app.include_router(manager_router)
app.include_router(admin_channels_router)
app.include_router(admin_channel_accounts_router)
app.include_router(channels_router)


@app.get("/health")
def health():
    """Liveness: confirma apenas que o processo HTTP está vivo."""
    return {"status": "ok", "service": "campoedados", "version": "0.6.1"}


@app.get("/ready")
def ready(response: Response):
    """Readiness: só libera tráfego quando banco e storage obrigatório estão prontos."""
    db_ready = database_is_ready()
    storage_ready = media_storage_is_configured()
    is_ready = db_ready and storage_ready
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if is_ready else "not_ready",
        "service": "campoedados",
        "version": "0.6.1",
        "environment": os.getenv("CAMPOEDADOS_ENV", "development"),
        "database": "ready" if db_ready else "unavailable",
        "media_storage": {
            "backend": media_storage_backend(),
            "status": "ready" if storage_ready else "misconfigured",
        },
        "modules": ["livestock", "feed_mill", "finance"],
        "module_contract": "independent",
        "operator_api": True,
        "manager_api": True,
        "transfer_flow": True,
        "invoice_receipt_flow": True,
        "multimodal_input": ["text", "image", "pdf", "audio"],
        "invoice_ai_extraction": True,
        "audio_transcription": True,
        "channel_webhooks": ["whatsapp", "telegram"],
        "channel_identity_mapping": True,
        "channel_accounts_in_database": True,
    }
