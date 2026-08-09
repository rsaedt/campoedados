from fastapi import FastAPI

from app.api.admin_channels import router as admin_channels_router
from app.api.channels import router as channels_router
from app.api.manager import router as manager_router
from app.api.media import router as media_router
from app.api.me import router as me_router
from app.api.operator import router as operator_router

app = FastAPI(title="Campo e Dados", version="0.5.0")
app.include_router(me_router)
app.include_router(operator_router)
app.include_router(media_router)
app.include_router(manager_router)
app.include_router(admin_channels_router)
app.include_router(channels_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "campoedados"}


@app.get("/ready")
def ready():
    return {
        "status": "ready",
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
    }
