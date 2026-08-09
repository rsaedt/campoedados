from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_db
from app.core.enums import MembershipRole
from app.main import app
from app.models.channel import ChannelIdentity
from app.models.domain import AuditEntry, Membership, Organization, Unit, User
from app.services.auth import issue_access_token


def test_admin_can_correct_linked_telegram_contact_unit(session):
    org = Organization(name="Agro Link", slug="agro-link", active=True)
    admin = User(display_name="Rafael Admin", active=True)
    session.add_all([org, admin])
    session.flush()

    membership = Membership(
        organization_id=org.id,
        user_id=admin.id,
        role=MembershipRole.ADMIN.value,
        active=True,
    )
    sh7 = Unit(organization_id=org.id, code="SH7", name="Fazenda SH7", active=True)
    nsg = Unit(organization_id=org.id, code="NSG", name="Fazenda NSG", active=True)
    session.add_all([membership, sh7, nsg])
    session.flush()

    identity = ChannelIdentity(
        membership_id=membership.id,
        default_unit_id=nsg.id,
        channel="telegram",
        account_key="agro-homolog",
        external_user_id="1090659217",
        external_chat_id="1090659217",
        display_name="Rafael Saedt",
        active=True,
    )
    session.add(identity)
    session.flush()
    _, raw = issue_access_token(session, membership_id=membership.id, raw_token="linked-contact-admin-token")
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        listed = client.get(
            "/v1/dashboard/contacts/linked",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()[0]["default_unit_code"] == "NSG"

        changed = client.post(
            f"/v1/dashboard/contacts/linked/{identity.id}",
            headers={"Authorization": f"Bearer {raw}"},
            json={"membership_id": membership.id, "default_unit_code": "SH7"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["default_unit_code"] == "SH7"
    finally:
        app.dependency_overrides.clear()

    session.refresh(identity)
    assert identity.default_unit_id == sh7.id
    audit = session.scalar(
        select(AuditEntry).where(AuditEntry.action == "channel_contact_link_updated")
    )
    assert audit is not None
    assert audit.details["old_unit_code"] == "NSG"
    assert audit.details["new_unit_code"] == "SH7"
