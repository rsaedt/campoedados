from fastapi import FastAPI

app = FastAPI(title="Campo e Dados", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "campoedados"}


@app.get("/ready")
def ready():
    return {
        "status": "ready",
        "modules": ["livestock", "feed_mill", "finance"],
        "module_contract": "independent",
    }
