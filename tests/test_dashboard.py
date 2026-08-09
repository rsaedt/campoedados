from decimal import Decimal
from types import SimpleNamespace

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import channels as channel_api
from app.core.database import get_db
from app.core.enums import MembershipRole, ModuleCode, ProductType
from app.main import app
from app.models.channel import ChannelAccount, ChannelContactRequest, ChannelIdentity
from app.models.domain import AuditEntry, InventoryBalance, InventoryMovement, Membership, Organization, Product, Unit, User, UserModulePermission
from app.services.auth import Principal, issue_access_token
from app.services.modules import set_module_enabled
from app.services.telegram_admin import connect_telegram_bot


class FakeTelegramTransport:
    def __init__(self):
        self.sent = []

    def verify_secret(self, supplied):
        return supplied == "secret"

    def send_text(self, account_key, target, text):
        self.sent.append((account_key, target, text))

    def download_media(self, account_key, media):
        raise AssertionError("não esperado")


class FakeTelegramResponse:
    def __init__(self, body):
        self.body = body
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeTelegramClient:
    def __init__(self):
        self.calls = []

    def get(self, url):
        self.calls.append(("GET", url, None))
        return FakeTelegramResponse({"ok": True, "result": {"id": 12345, "username": "campo_teste_bot", "first_name": "Campo Teste"}})

    def post(self, url, json):
        self.calls.append(("POST", url, json))
        return FakeTelegramResponse({"ok": True, "result": True})

    def close(self):
        pass


def setup_admin(session):
    org = Organization(name="Agro Dashboard", slug=f"agro-dashboard-{id(session)}")
    admin = User(display_name="Admin Dashboard", email=f"dash-{id(session)}@test.local")
    operator = User(display_name="João Operador", email=f"joao-{id(session)}@test.local")
    session.add_all([org, admin, operator])
    session.flush()
    unit = Unit(organization_id=org.id, code="SH7", name="Fazenda SH7", active=True)
    session.add(unit)
    session.flush()
    admin_membership = Membership(organization_id=org.id, user_id=admin.id, role=MembershipRole.ADMIN.value, active=True)
    operator_membership = Membership(organization_id=org.id, user_id=operator.id, role=MembershipRole.OPERATOR.value, active=True)
    session.add_all([admin_membership, operator_membership])
    session.flush()
    set_module_enabled(session, org.id, ModuleCode.FEED_MILL.value, True)
    session.add_all([
        UserModulePermission(
            membership_id=admin_membership.id,
            module_code=ModuleCode.FEED_MILL.value,
            can_view=True,
            can_register=True,
            can_approve=True,
            can_configure=True,
        ),
        UserModulePermission(
            membership_id=operator_membership.id,
            module_code=ModuleCode.FEED_MILL.value,
            can_view=True,
            can_register=True,
            can_approve=False,
            can_configure=False,
        ),
    ])
    product = Product(
        organization_id=org.id,
        code="MILHO",
        name="Milho",
        product_type=ProductType.RAW_MATERIAL.value,
        base_unit="kg",
        active=True,
    )
    session.add(product)
    session.flush()
    _, raw = issue_access_token(session, membership_id=admin_membership.id, raw_token=f"dashboard-token-{id(session)}")
    session.commit()
    return org, admin, admin_membership, operator_membership, unit, product, raw


def test_dashboard_page_is_real_ui():
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 200
    assert "Campo &amp; Dados" in response.text or "Campo & Dados" in response.text
    assert "Telegram" in response.text
    assert "Agente Gerencial" in response.text


def test_telegram_admin_validates_bot_and_sets_webhook(session, monkeypatch):
    org, admin, admin_membership, _, _, _, _ = setup_admin(session)
    monkeypatch.setenv("CAMPOEDADOS_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    client = FakeTelegramClient()
    principal = Principal(token_id="test", user=admin, membership=admin_membership, organization=org)

    result = connect_telegram_bot(
        session,
        principal=principal,
        account_key="agro-test",
        bot_token="123456:telegram-token-test",
        public_base_url="https://campo.example",
        client=client,
    )
    session.commit()

    assert result.bot_username == "campo_teste_bot"
    assert result.webhook_url == "https://campo.example/v1/channels/webhooks/telegram/agro-test"
    account = session.scalar(select(ChannelAccount).where(ChannelAccount.account_key == "agro-test"))
    assert account is not None
    set_webhook = [call for call in client.calls if call[0] == "POST"][0]
    assert set_webhook[2]["url"] == result.webhook_url
    assert set_webhook[2]["secret_token"]


def test_unknown_telegram_contact_appears_and_can_be_linked(session, tmp_path, monkeypatch):
    org, _, _, operator_membership, unit, _, token = setup_admin(session)
    session.add(ChannelAccount(
        organization_id=org.id,
        channel="telegram",
        account_key="farm-bot",
        display_name="@farm_bot",
        external_account_id="999",
        credential_ciphertext="x",
        webhook_secret_ciphertext="y",
        active=True,
    ))
    session.commit()
    transport = FakeTelegramTransport()
    monkeypatch.setattr(channel_api, "telegram_transport_factory", lambda key: transport)

    def override_db():
        yield session
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    update = {
        "update_id": 10,
        "message": {
            "message_id": 1,
            "from": {"id": 555, "first_name": "João"},
            "chat": {"id": 555, "type": "private"},
            "text": "Fiz duas batidas da Seca 0,1",
        },
    }
    try:
        response = client.post(
            "/v1/channels/webhooks/telegram/farm-bot",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )
        assert response.status_code == 200, response.text
        pending = session.scalar(select(ChannelContactRequest).where(ChannelContactRequest.external_user_id == "555"))
        assert pending is not None
        assert pending.status == "pending"
        assert "dashboard" in transport.sent[0][2].casefold()

        overview = client.get("/v1/dashboard/overview", headers={"Authorization": f"Bearer {token}"})
        assert overview.status_code == 200, overview.text
        contacts = overview.json()["pending_contacts"]
        assert contacts[0]["external_user_id"] == "555"

        linked = client.post(
            f"/v1/dashboard/contacts/{pending.id}/link",
            headers={"Authorization": f"Bearer {token}"},
            json={"membership_id": operator_membership.id, "default_unit_code": unit.code},
        )
        assert linked.status_code == 200, linked.text
    finally:
        app.dependency_overrides.clear()

    identity = session.scalar(select(ChannelIdentity).where(ChannelIdentity.external_user_id == "555"))
    assert identity is not None
    assert identity.membership_id == operator_membership.id
    assert session.get(ChannelContactRequest, pending.id).status == "linked"


def test_dashboard_inventory_adjustment_uses_inventory_ledger(session):
    org, _, _, _, unit, product, token = setup_admin(session)

    def override_db():
        yield session
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        response = client.post(
            "/v1/dashboard/inventory/adjustments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "unit_code": unit.code,
                "product_id": product.id,
                "quantity": "1000",
                "unit_cost": "0.75",
                "note": "Saldo inicial homologação",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    balance = session.scalar(select(InventoryBalance).where(
        InventoryBalance.organization_id == org.id,
        InventoryBalance.unit_id == unit.id,
        InventoryBalance.product_id == product.id,
    ))
    assert balance.quantity == Decimal("1000.0000")
    assert session.scalar(select(func.count()).select_from(InventoryMovement)) == 1
    assert session.scalar(select(func.count()).select_from(AuditEntry).where(AuditEntry.action == "inventory_adjustment")) == 1
