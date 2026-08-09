import hashlib
import hmac
import json
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import channels as channel_api
from app.core.database import Base, get_db
from app.core.enums import MembershipRole, ModuleCode, MovementType, ProductType
from app.main import app
from app.models.channel import ChannelIdentity
from app.models.domain import (
    AccountsPayable,
    Event,
    Membership,
    Organization,
    Product,
    ProductionBatch,
    Recipe,
    RecipeIngredient,
    Unit,
    User,
    UserModulePermission,
)
from app.services.auth import issue_access_token
from app.services.channels.base import DownloadedMedia
from app.services.channels.whatsapp import WhatsAppConfig, WhatsAppTransport
from app.services.inventory import get_balance, receive_stock
from app.services.media_storage import FileSystemMediaStorage, get_media_storage
from app.services.modules import set_module_enabled
from app.services.openai_multimodal import get_multimodal_ai


D = Decimal


class FakeAI:
    def __init__(self, *, invoice=None, transcript="Fiz 3 batidas da Seca 0,1"):
        self.invoice = invoice or {
            "document_kind": "invoice",
            "supplier_name": "Cerealista Teste",
            "supplier_document": "12345678000199",
            "invoice_number": "NF-500",
            "issue_date": "2026-08-09",
            "invoice_total": "22500.00",
            "items": [
                {
                    "product_name": "Milho",
                    "quantity": "30000",
                    "unit": "kg",
                    "unit_cost": "0.75",
                    "total_amount": "22500.00",
                }
            ],
            "installments": [{"due_date": "2026-09-10", "amount": "22500.00"}],
            "confidence": 0.99,
        }
        self.transcript = transcript

    def extract_invoice(self, *, content, mime_type, filename=None):
        return self.invoice

    def transcribe_audio(self, *, content, mime_type, filename=None):
        return self.transcript


class FakeWhatsAppTransport:
    def __init__(self, media=None):
        self.config = SimpleNamespace(verify_token="verify-me")
        self.sent = []
        self.media = media or DownloadedMedia(
            content=b"fake-image",
            mime_type="image/jpeg",
            filename="nf.jpg",
        )

    def verify_signature(self, raw_body, signature_header):
        return signature_header == "sha256=valid"

    def download_media(self, account_key, media):
        return self.media

    def send_text(self, account_key, target, text):
        self.sent.append((account_key, target, text))


class FakeTelegramTransport:
    def __init__(self, media=None):
        self.sent = []
        self.media = media or DownloadedMedia(
            content=b"fake-audio",
            mime_type="audio/ogg",
            filename="voice.ogg",
        )

    def verify_secret(self, supplied):
        return supplied == "telegram-secret"

    def download_media(self, account_key, media):
        return self.media

    def send_text(self, account_key, target, text):
        self.sent.append((account_key, target, text))


def make_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return Session()


def setup_context(session, *, finance=False):
    org = Organization(name="Agropecuária Teste", slug=f"agro-{id(session)}")
    operator = User(display_name="João Operador", email=f"op-{id(session)}@test.local")
    admin = User(display_name="Admin", email=f"admin-{id(session)}@test.local")
    session.add_all([org, operator, admin])
    session.flush()

    sh7 = Unit(organization_id=org.id, name="SH7", code="SH7")
    nsg = Unit(organization_id=org.id, name="NSG", code="NSG")
    session.add_all([sh7, nsg])
    session.flush()

    op_membership = Membership(
        organization_id=org.id,
        user_id=operator.id,
        role=MembershipRole.OPERATOR.value,
    )
    admin_membership = Membership(
        organization_id=org.id,
        user_id=admin.id,
        role=MembershipRole.ADMIN.value,
    )
    session.add_all([op_membership, admin_membership])
    session.flush()

    set_module_enabled(session, org.id, ModuleCode.FEED_MILL.value, True)
    if finance:
        set_module_enabled(session, org.id, ModuleCode.FINANCE.value, True)

    session.add(
        UserModulePermission(
            membership_id=op_membership.id,
            module_code=ModuleCode.FEED_MILL.value,
            can_view=True,
            can_register=True,
        )
    )

    products = {}
    for code, name, kind in [
        ("MILHO", "Milho", ProductType.RAW_MATERIAL.value),
        ("FARELO", "Farelo de soja", ProductType.RAW_MATERIAL.value),
        ("UREIA", "Ureia", ProductType.RAW_MATERIAL.value),
        ("SAL", "Sal branco", ProductType.RAW_MATERIAL.value),
        ("NUCLEO", "Núcleo", ProductType.RAW_MATERIAL.value),
        ("SECA01", "Seca 0,1", ProductType.FINISHED_GOOD.value),
    ]:
        row = Product(
            organization_id=org.id,
            code=code,
            name=name,
            product_type=kind,
            base_unit="kg",
            package_weight=D("40") if code == "SECA01" else None,
        )
        products[code] = row
        session.add(row)
    session.flush()

    for code, cost in {
        "MILHO": "0.75",
        "FARELO": "2.05",
        "UREIA": "4.00",
        "SAL": "0.80",
        "NUCLEO": "7.10",
    }.items():
        receive_stock(
            session,
            organization_id=org.id,
            unit_id=sh7.id,
            product_id=products[code].id,
            quantity="100000",
            unit_cost=cost,
            movement_type=MovementType.RECEIPT.value,
        )

    recipe = Recipe(
        organization_id=org.id,
        output_product_id=products["SECA01"].id,
        name="Seca 0,1",
        output_quantity_per_batch=D("500"),
    )
    recipe.ingredients = [
        RecipeIngredient(product_id=products["MILHO"].id, quantity_per_batch=D("350")),
        RecipeIngredient(product_id=products["FARELO"].id, quantity_per_batch=D("50")),
        RecipeIngredient(product_id=products["UREIA"].id, quantity_per_batch=D("35")),
        RecipeIngredient(product_id=products["SAL"].id, quantity_per_batch=D("40")),
        RecipeIngredient(product_id=products["NUCLEO"].id, quantity_per_batch=D("25")),
    ]
    session.add(recipe)
    session.flush()

    session.add_all([
        ChannelIdentity(
            membership_id=op_membership.id,
            default_unit_id=sh7.id,
            channel="whatsapp",
            account_key="wa-phone-1",
            external_user_id="556699999999",
            external_chat_id="556699999999",
        ),
        ChannelIdentity(
            membership_id=op_membership.id,
            default_unit_id=sh7.id,
            channel="telegram",
            account_key="farm-bot",
            external_user_id="1001",
            external_chat_id="1001",
        ),
    ])
    _, admin_token = issue_access_token(
        session,
        membership_id=admin_membership.id,
        raw_token=f"admin-token-{id(session)}",
    )
    session.commit()
    return {
        "org": org,
        "op_membership": op_membership,
        "admin_token": admin_token,
        "sh7": sh7,
        "nsg": nsg,
        "products": products,
    }


def client_with(session, tmp_path, ai):
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_multimodal_ai] = lambda: ai
    app.dependency_overrides[get_media_storage] = lambda: FileSystemMediaStorage(
        base_dir=tmp_path, max_bytes=20 * 1024 * 1024
    )
    return TestClient(app)


def cleanup():
    app.dependency_overrides.clear()


def whatsapp_payload(text="Fiz 3 batidas da Seca 0,1", *, msg_type="text"):
    message = {
        "from": "556699999999",
        "id": "wamid.001",
        "timestamp": "1786240000",
        "type": msg_type,
    }
    if msg_type == "text":
        message["text"] = {"body": text}
    elif msg_type == "image":
        message["image"] = {"id": "media-1", "mime_type": "image/jpeg", "caption": text}
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"display_phone_number": "+55 66 0000-0000", "phone_number_id": "wa-phone-1"},
                    "contacts": [{"wa_id": "556699999999", "profile": {"name": "João"}}],
                    "messages": [message],
                },
            }],
        }],
    }


def test_whatsapp_text_routes_to_operator_and_deduplicates(tmp_path, monkeypatch):
    session = make_session()
    ctx = setup_context(session)
    fake = FakeWhatsAppTransport()
    client = client_with(session, tmp_path, FakeAI())
    monkeypatch.setattr(channel_api, "whatsapp_transport_factory", lambda: fake)
    payload = whatsapp_payload()
    try:
        first = client.post(
            "/v1/channels/webhooks/whatsapp",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json", "X-Hub-Signature-256": "sha256=valid"},
        )
        second = client.post(
            "/v1/channels/webhooks/whatsapp",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json", "X-Hub-Signature-256": "sha256=valid"},
        )
    finally:
        cleanup()

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert session.scalar(select(func.count(Event.id))) == 1
    assert session.scalar(select(func.count(ProductionBatch.id))) == 1
    assert "Produção registrada" in fake.sent[0][2]
    balance = get_balance(session, ctx["org"].id, ctx["sh7"].id, ctx["products"]["SECA01"].id)
    assert balance.quantity == D("1500.0000")


def test_whatsapp_unknown_contact_is_not_written(tmp_path, monkeypatch):
    session = make_session()
    setup_context(session)
    fake = FakeWhatsAppTransport()
    client = client_with(session, tmp_path, FakeAI())
    monkeypatch.setattr(channel_api, "whatsapp_transport_factory", lambda: fake)
    payload = whatsapp_payload()
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "550000000000"
    try:
        response = client.post(
            "/v1/channels/webhooks/whatsapp",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json", "X-Hub-Signature-256": "sha256=valid"},
        )
    finally:
        cleanup()
    assert response.status_code == 200
    assert session.scalar(select(func.count(Event.id))) == 0
    assert "ainda não está vinculado" in fake.sent[0][2]


def test_whatsapp_invoice_image_enters_stock_and_finance(tmp_path, monkeypatch):
    session = make_session()
    ctx = setup_context(session, finance=True)
    fake = FakeWhatsAppTransport()
    client = client_with(session, tmp_path, FakeAI())
    monkeypatch.setattr(channel_api, "whatsapp_transport_factory", lambda: fake)
    payload = whatsapp_payload("Chegou milho, segue NF.", msg_type="image")
    try:
        response = client.post(
            "/v1/channels/webhooks/whatsapp",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json", "X-Hub-Signature-256": "sha256=valid"},
        )
    finally:
        cleanup()
    assert response.status_code == 200, response.text
    assert get_balance(session, ctx["org"].id, ctx["sh7"].id, ctx["products"]["MILHO"].id).quantity == D("130000.0000")
    assert session.scalar(select(func.count(AccountsPayable.id))) == 1
    assert "aguardando aprovação gerencial" in fake.sent[-1][2].casefold()


def test_telegram_text_and_audio_share_same_operator_flow(tmp_path, monkeypatch):
    session = make_session()
    ctx = setup_context(session)
    fake = FakeTelegramTransport()
    client = client_with(session, tmp_path, FakeAI())
    monkeypatch.setattr(channel_api, "telegram_transport_factory", lambda key: fake)

    text_update = {
        "update_id": 100,
        "message": {
            "message_id": 5,
            "from": {"id": 1001, "first_name": "João"},
            "chat": {"id": 1001, "type": "private"},
            "text": "Fiz 3 batidas da Seca 0,1",
        },
    }
    audio_update = {
        "update_id": 101,
        "message": {
            "message_id": 6,
            "from": {"id": 1001, "first_name": "João"},
            "chat": {"id": 1001, "type": "private"},
            "voice": {"file_id": "voice-1", "mime_type": "audio/ogg"},
        },
    }
    try:
        text_response = client.post(
            "/v1/channels/webhooks/telegram/farm-bot",
            json=text_update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-secret"},
        )
        audio_response = client.post(
            "/v1/channels/webhooks/telegram/farm-bot",
            json=audio_update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-secret"},
        )
    finally:
        cleanup()

    assert text_response.status_code == 200, text_response.text
    assert audio_response.status_code == 200, audio_response.text
    assert session.scalar(select(func.count(ProductionBatch.id))) == 2
    balance = get_balance(session, ctx["org"].id, ctx["sh7"].id, ctx["products"]["SECA01"].id)
    assert balance.quantity == D("3000.0000")
    assert len(fake.sent) == 2


def test_telegram_rejects_wrong_secret(tmp_path, monkeypatch):
    session = make_session()
    setup_context(session)
    fake = FakeTelegramTransport()
    client = client_with(session, tmp_path, FakeAI())
    monkeypatch.setattr(channel_api, "telegram_transport_factory", lambda key: fake)
    try:
        response = client.post(
            "/v1/channels/webhooks/telegram/farm-bot",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
    finally:
        cleanup()
    assert response.status_code == 401


def test_real_whatsapp_signature_verification():
    config = WhatsAppConfig(
        access_token="token",
        phone_number_id="phone",
        app_secret="app-secret",
        verify_token="verify",
        graph_version="v-test",
    )
    transport = WhatsAppTransport(config)
    raw = b'{"hello":"world"}'
    digest = hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    assert transport.verify_signature(raw, f"sha256={digest}") is True
    assert transport.verify_signature(raw, "sha256=bad") is False


def test_admin_can_bind_channel_identity(tmp_path):
    session = make_session()
    ctx = setup_context(session)
    client = client_with(session, tmp_path, FakeAI())
    try:
        response = client.post(
            "/v1/admin/channel-identities",
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
            json={
                "membership_id": ctx["op_membership"].id,
                "default_unit_code": "NSG",
                "channel": "telegram",
                "account_key": "second-bot",
                "external_user_id": "1001",
                "external_chat_id": "1001",
                "display_name": "João",
            },
        )
        listing = client.get(
            "/v1/admin/channel-identities",
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
    finally:
        cleanup()
    assert response.status_code == 201, response.text
    assert response.json()["default_unit_code"] == "NSG"
    assert listing.status_code == 200
    assert len(listing.json()) == 3
