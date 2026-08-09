from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_db
from app.core.enums import EventStatus, ModuleCode, MovementType, ProductType
from app.main import app
from app.models.domain import (
    AccountsPayable,
    Event,
    EventDocument,
    EventModuleTarget,
    Membership,
    Organization,
    Product,
    Purchase,
    Recipe,
    RecipeIngredient,
    Unit,
    User,
    UserModulePermission,
)
from app.services.auth import issue_access_token
from app.services.inventory import get_balance, receive_stock
from app.services.media_storage import FileSystemMediaStorage, get_media_storage
from app.services.modules import set_module_enabled
from app.services.openai_multimodal import get_multimodal_ai


D = Decimal


class FakeAI:
    def __init__(self, extraction=None, transcript=""):
        self.extraction = extraction or {}
        self.transcript = transcript

    def extract_invoice(self, *, content: bytes, mime_type: str, filename: str | None = None) -> dict:
        return self.extraction

    def transcribe_audio(self, *, content: bytes, mime_type: str, filename: str | None = None) -> str:
        return self.transcript


def _context(session, *, finance=True):
    org = Organization(name="Agropecuária Multimodal", slug="agro-multimodal")
    user = User(display_name="João Operador", email="multi@agro.test")
    session.add_all([org, user])
    session.flush()
    sh7 = Unit(organization_id=org.id, name="SH7", code="SH7")
    nsg = Unit(organization_id=org.id, name="NSG", code="NSG")
    session.add_all([sh7, nsg])
    membership = Membership(organization_id=org.id, user_id=user.id, role="operator")
    session.add(membership)
    session.flush()
    set_module_enabled(session, org.id, ModuleCode.FEED_MILL.value, True)
    session.add(UserModulePermission(
        membership_id=membership.id,
        module_code=ModuleCode.FEED_MILL.value,
        can_view=True,
        can_register=True,
    ))
    if finance:
        set_module_enabled(session, org.id, ModuleCode.FINANCE.value, True)

    milho = Product(
        organization_id=org.id, code="MILHO", name="Milho",
        product_type=ProductType.RAW_MATERIAL.value, base_unit="kg",
    )
    seca = Product(
        organization_id=org.id, code="SECA01", name="Seca 0,1",
        product_type=ProductType.FINISHED_GOOD.value, base_unit="kg",
    )
    farelo = Product(organization_id=org.id, code="FARELO", name="Farelo de soja", product_type=ProductType.RAW_MATERIAL.value, base_unit="kg")
    ureia = Product(organization_id=org.id, code="UREIA", name="Ureia", product_type=ProductType.RAW_MATERIAL.value, base_unit="kg")
    sal = Product(organization_id=org.id, code="SAL", name="Sal branco", product_type=ProductType.RAW_MATERIAL.value, base_unit="kg")
    nucleo = Product(organization_id=org.id, code="NUCLEO", name="Núcleo", product_type=ProductType.RAW_MATERIAL.value, base_unit="kg")
    session.add_all([milho, seca, farelo, ureia, sal, nucleo])
    session.flush()

    for product, cost in [(milho, "0.75"), (farelo, "2.05"), (ureia, "4.00"), (sal, "0.80"), (nucleo, "7.10")]:
        receive_stock(
            session,
            organization_id=org.id,
            unit_id=sh7.id,
            product_id=product.id,
            quantity="10000",
            unit_cost=cost,
            movement_type=MovementType.RECEIPT.value,
        )

    recipe = Recipe(
        organization_id=org.id,
        output_product_id=seca.id,
        name="Seca 0,1",
        output_quantity_per_batch=D("500"),
    )
    recipe.ingredients = [
        RecipeIngredient(product_id=milho.id, quantity_per_batch=D("350")),
        RecipeIngredient(product_id=farelo.id, quantity_per_batch=D("50")),
        RecipeIngredient(product_id=ureia.id, quantity_per_batch=D("35")),
        RecipeIngredient(product_id=sal.id, quantity_per_batch=D("40")),
        RecipeIngredient(product_id=nucleo.id, quantity_per_batch=D("25")),
    ]
    session.add(recipe)
    session.flush()
    _, token = issue_access_token(session, membership_id=membership.id, raw_token="multimodal-test-token")
    session.commit()
    return org, sh7, milho, token


def _client(session, tmp_path, fake_ai):
    def override_db():
        yield session
    def override_ai():
        return fake_ai
    def override_storage():
        return FileSystemMediaStorage(base_dir=tmp_path / "uploads")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_multimodal_ai] = override_ai
    app.dependency_overrides[get_media_storage] = override_storage
    return TestClient(app)


def _clear():
    app.dependency_overrides.clear()


def _invoice(*, installments=True):
    return {
        "document_kind": "invoice",
        "supplier_name": "Cerealista Boa Safra",
        "supplier_document": "12345678000190",
        "invoice_number": "NF-1001",
        "issue_date": "2026-08-08",
        "items": [{
            "product_name": "Milho em grãos",
            "quantity": 30000,
            "unit": "kg",
            "unit_cost": 0.80,
            "total_amount": 24000.00,
        }],
        "invoice_total": 24000.00,
        "installments": ([{"due_date": "2026-09-08", "amount": 24000.00}] if installments else []),
        "confidence": 0.98,
        "notes": None,
    }


def test_invoice_image_real_flow_creates_stock_purchase_and_document(session, tmp_path):
    org, sh7, milho, token = _context(session, finance=True)
    client = _client(session, tmp_path, FakeAI(extraction=_invoice()))
    try:
        response = client.post(
            "/v1/operator/media/invoice",
            headers={"Authorization": f"Bearer {token}"},
            data={"unit_code": "SH7", "text": "Chegou milho, segue NF", "external_id": "wa-nf-1"},
            files={"file": ("nf.jpg", b"fake-jpeg-content", "image/jpeg")},
        )
    finally:
        _clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_type"] == "invoice"
    assert body["event"]["status"] == EventStatus.WAITING_MANAGER.value
    assert get_balance(session, org.id, sh7.id, milho.id).quantity == D("40000.0000")
    event_id = body["event"]["event_id"]
    assert session.scalar(select(EventDocument).where(EventDocument.event_id == event_id)) is not None
    purchase = session.scalar(select(Purchase).where(Purchase.event_id == event_id))
    assert purchase is not None
    assert session.scalar(select(AccountsPayable).where(AccountsPayable.purchase_id == purchase.id)) is not None


def test_invoice_without_installments_processes_physical_and_waits_finance_complement(session, tmp_path):
    org, sh7, milho, token = _context(session, finance=True)
    client = _client(session, tmp_path, FakeAI(extraction=_invoice(installments=False)))
    try:
        response = client.post(
            "/v1/operator/media/invoice",
            headers={"Authorization": f"Bearer {token}"},
            data={"unit_code": "SH7", "text": "Chegou milho, segue NF", "external_id": "wa-nf-2"},
            files={"file": ("nf-sem-parcela.png", b"invoice-no-installments", "image/png")},
        )
    finally:
        _clear()

    assert response.status_code == 200, response.text
    body = response.json()["event"]
    assert body["status"] == EventStatus.WAITING_COMPLEMENT.value
    states = {row["module_code"]: row for row in body["module_states"]}
    assert states[ModuleCode.FEED_MILL.value]["status"] == EventStatus.PROCESSED.value
    assert states[ModuleCode.FINANCE.value]["status"] == EventStatus.WAITING_COMPLEMENT.value
    assert get_balance(session, org.id, sh7.id, milho.id).quantity == D("40000.0000")
    assert session.scalar(select(Purchase).where(Purchase.event_id == body["event_id"])) is None


def test_received_quantity_overrides_invoice_quantity_and_creates_nonconformity(session, tmp_path):
    org, sh7, milho, token = _context(session, finance=True)
    client = _client(session, tmp_path, FakeAI(extraction=_invoice()))
    try:
        response = client.post(
            "/v1/operator/media/invoice",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "unit_code": "SH7", "text": "Chegou milho, segue NF",
                "received_quantity": "29400", "received_unit": "kg", "external_id": "wa-nf-3",
            },
            files={"file": ("nf.webp", b"invoice-different-qty", "image/webp")},
        )
    finally:
        _clear()

    assert response.status_code == 200, response.text
    body = response.json()["event"]
    assert body["status"] == EventStatus.WAITING_MANAGER.value
    assert get_balance(session, org.id, sh7.id, milho.id).quantity == D("39400.0000")


def test_same_file_sha_does_not_duplicate_inventory(session, tmp_path):
    org, sh7, milho, token = _context(session, finance=False)
    fake = FakeAI(extraction=_invoice(installments=False))
    client = _client(session, tmp_path, fake)
    payload = b"same-invoice-photo"
    try:
        first = client.post(
            "/v1/operator/media/invoice",
            headers={"Authorization": f"Bearer {token}"},
            data={"unit_code": "SH7", "external_id": "msg-a"},
            files={"file": ("nf.jpg", payload, "image/jpeg")},
        )
        second = client.post(
            "/v1/operator/media/invoice",
            headers={"Authorization": f"Bearer {token}"},
            data={"unit_code": "SH7", "external_id": "msg-b"},
            files={"file": ("nf.jpg", payload, "image/jpeg")},
        )
    finally:
        _clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["event"]["event_id"] == second.json()["event"]["event_id"]
    assert get_balance(session, org.id, sh7.id, milho.id).quantity == D("40000.0000")


def test_audio_is_transcribed_and_runs_same_operator_flow(session, tmp_path):
    org, sh7, milho, token = _context(session, finance=False)
    client = _client(session, tmp_path, FakeAI(transcript="Fiz 3 batidas da Seca 0,1"))
    try:
        response = client.post(
            "/v1/operator/media/audio",
            headers={"Authorization": f"Bearer {token}"},
            data={"unit_code": "SH7", "external_id": "voice-1"},
            files={"file": ("voz.ogg", b"fake-audio", "audio/ogg")},
        )
    finally:
        _clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == "Fiz 3 batidas da Seca 0,1"
    assert body["event"]["event_type"] == "feed_mill.production"
    assert body["event"]["production"]["output_quantity"] == "1500.0000"
    assert get_balance(session, org.id, sh7.id, milho.id).quantity == D("8950.0000")


def test_invoice_rejects_unsupported_mime_type(session, tmp_path):
    _, _, _, token = _context(session, finance=False)
    client = _client(session, tmp_path, FakeAI(extraction=_invoice()))
    try:
        response = client.post(
            "/v1/operator/media/invoice",
            headers={"Authorization": f"Bearer {token}"},
            data={"unit_code": "SH7"},
            files={"file": ("nf.txt", b"not-an-image", "text/plain")},
        )
    finally:
        _clear()
    assert response.status_code == 415
