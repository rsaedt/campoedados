from fastapi import FastAPI

from app.api.manager import router as manager_router
from app.api.me import router as me_router
from app.api.operator import router as operator_router

app = FastAPI(title="Campo e Dados", version="0.3.0")
app.include_router(me_router)
app.include_router(operator_router)
app.include_router(manager_router)


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
    }
