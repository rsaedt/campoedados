from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool

import app.main as main_module
from app.core.database import build_engine, normalize_database_url
from app.main import app
from app.services import media_storage as storage_module
from app.services.channel_accounts import CredentialCipher
from app.services.media_storage import SupabaseMediaStorage, media_storage_is_configured


def test_normalize_supabase_postgres_url_uses_psycopg():
    assert normalize_database_url("postgres://u:p@db.example:5432/postgres") == (
        "postgresql+psycopg://u:p@db.example:5432/postgres"
    )
    assert normalize_database_url("postgresql://u:p@db.example:5432/postgres") == (
        "postgresql+psycopg://u:p@db.example:5432/postgres"
    )


def test_transaction_pooler_uses_nullpool():
    engine = build_engine("postgresql://u:p@localhost:6543/postgres")
    assert isinstance(engine.pool, NullPool)
    engine.dispose()


def test_supabase_storage_requires_server_side_configuration(monkeypatch):
    monkeypatch.setenv("CAMPOEDADOS_MEDIA_STORAGE", "supabase")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("CAMPOEDADOS_SUPABASE_STORAGE_BUCKET", "private-media")
    assert media_storage_is_configured() is False


class _FakeResponse:
    status_code = 200


class _FakeClient:
    last_url = None
    last_headers = None
    last_content = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, headers, content):
        type(self).last_url = url
        type(self).last_headers = headers
        type(self).last_content = content
        return _FakeResponse()


def test_supabase_secret_key_uses_apikey_header_without_bearer(monkeypatch):
    monkeypatch.setattr(storage_module.httpx, "Client", _FakeClient)
    storage = SupabaseMediaStorage(
        supabase_url="https://project.supabase.co",
        secret_key="sb_secret_example",
        bucket="campoedados-staging-media",
    )
    stored = storage.store(content=b"nota-fiscal", filename="nf.pdf", mime_type="application/pdf")

    assert stored.storage_ref.startswith("supabase://campoedados-staging-media/sha256/")
    assert _FakeClient.last_headers["apikey"] == "sb_secret_example"
    assert "Authorization" not in _FakeClient.last_headers
    assert _FakeClient.last_headers["x-upsert"] == "true"
    assert _FakeClient.last_content == b"nota-fiscal"


def test_legacy_service_role_remains_compatible(monkeypatch):
    monkeypatch.setattr(storage_module.httpx, "Client", _FakeClient)
    storage = SupabaseMediaStorage(
        supabase_url="https://project.supabase.co",
        secret_key="legacy-jwt",
        bucket="campoedados-staging-media",
    )
    storage.store(content=b"legacy", filename="nf.pdf", mime_type="application/pdf")
    assert _FakeClient.last_headers["apikey"] == "legacy-jwt"
    assert _FakeClient.last_headers["Authorization"] == "Bearer legacy-jwt"


def test_render_blueprint_generates_channel_encryption_secret():
    blueprint = Path("render.yaml").read_text(encoding="utf-8")
    assert "CAMPOEDADOS_CREDENTIAL_ENCRYPTION_KEY" in blueprint
    assert "generateValue: true" in blueprint


def test_render_generated_256_bit_base64_is_fernet_compatible():
    cipher = CredentialCipher("B0jrphAPOY7pg92AN0c9MN4yecczLMdwnx4OkA1KFUk=")
    encrypted = cipher.encrypt("telegram-secret")
    assert cipher.decrypt(encrypted) == "telegram-secret"


def test_ready_returns_503_when_database_is_unavailable(monkeypatch):
    monkeypatch.setattr(main_module, "database_is_ready", lambda: False)
    monkeypatch.setenv("CAMPOEDADOS_MEDIA_STORAGE", "filesystem")
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_ready_returns_200_when_required_dependencies_are_ready(monkeypatch):
    monkeypatch.setattr(main_module, "database_is_ready", lambda: True)
    monkeypatch.setenv("CAMPOEDADOS_MEDIA_STORAGE", "filesystem")
    monkeypatch.setenv("CAMPOEDADOS_ENV", "staging")
    response = TestClient(app).get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["environment"] == "staging"
    assert body["version"] == "0.7.5"
    assert body["dashboard"] is True
    assert body["decision_overview"] is True
    assert body["permission_aware_module_navigation"] is True
    assert body["hidden_unavailable_modules"] is True
    assert body["web_user_login"] is True
    assert body["web_session_cookie"] is True
    assert body["telegram_dashboard_connect"] is True
    assert body["telegram_contact_linking"] is True
    assert body["telegram_contact_relinking"] is True
    assert body["channel_credential_encryption"] is True
    assert body["channel_accounts_in_database"] is True
    assert body["controlled_onboarding"] is True
    assert body["controlled_admin_ops"] is True
