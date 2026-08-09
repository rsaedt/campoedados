from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.database import Base
from app.core.enums import MembershipRole
from app.models.domain import Membership, Organization, User
from app.services.auth import Principal
from app.services.channel_accounts import (
    ChannelAccountError,
    CredentialCipher,
    create_channel_account,
    load_channel_credentials,
)


def make_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    org = Organization(name="Agro Teste", slug="agro-config")
    user = User(display_name="Admin", email="admin@config.test")
    session.add_all([org, user])
    session.flush()
    membership = Membership(
        organization_id=org.id,
        user_id=user.id,
        role=MembershipRole.ADMIN.value,
        active=True,
    )
    session.add(membership)
    session.flush()
    principal = Principal(
        token_id="test-token",
        user=user,
        membership=membership,
        organization=org,
    )
    return session, principal


def test_telegram_account_credentials_are_encrypted_in_database():
    session, principal = make_context()
    cipher = CredentialCipher(Fernet.generate_key())
    row = create_channel_account(
        session,
        principal=principal,
        channel="telegram",
        account_key="agro-config-bot",
        credential="123456:telegram-token",
        webhook_secret="webhook-secret",
        display_name="Bot Agro Config",
        cipher=cipher,
    )
    session.commit()

    assert "telegram-token" not in row.credential_ciphertext
    assert "webhook-secret" not in row.webhook_secret_ciphertext

    loaded, credentials = load_channel_credentials(
        session,
        channel="telegram",
        account_key="agro-config-bot",
        cipher=cipher,
    )
    assert loaded.organization_id == principal.organization_id
    assert credentials.credential == "123456:telegram-token"
    assert credentials.webhook_secret == "webhook-secret"


def test_channel_account_key_is_globally_unique_for_webhook_routing():
    session, principal = make_context()
    cipher = CredentialCipher(Fernet.generate_key())
    create_channel_account(
        session,
        principal=principal,
        channel="telegram",
        account_key="unique-webhook-key",
        credential="token-a",
        webhook_secret="secret-a",
        cipher=cipher,
    )
    session.commit()

    with pytest.raises(ChannelAccountError, match="Já existe"):
        create_channel_account(
            session,
            principal=principal,
            channel="telegram",
            account_key="unique-webhook-key",
            credential="token-b",
            webhook_secret="secret-b",
            cipher=cipher,
        )


def test_render_blueprint_contains_only_infrastructure_secrets():
    content = Path("render.yaml").read_text(encoding="utf-8")
    assert "bootstrap_staging" not in content
    assert "CAMPOEDADOS_BOOTSTRAP_" not in content
    assert "CAMPOEDADOS_TELEGRAM_BOTS_JSON" not in content
    assert "CAMPOEDADOS_TELEGRAM_BOT_TOKEN" not in content
    assert "CAMPOEDADOS_TELEGRAM_SECRET_TOKEN" not in content

    secret_keys = []
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("- key:"):
            key = line.split(":", 1)[1].strip()
            next_lines = "\n".join(lines[index + 1 : index + 3])
            if "sync: false" in next_lines:
                secret_keys.append(key)

    assert set(secret_keys) == {
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "OPENAI_API_KEY",
    }
