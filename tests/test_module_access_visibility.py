from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app
from app.models.domain import (
    Event,
    EventModuleTarget,
    Membership,
    Organization,
    OrganizationModule,
    SystemModule,
    Unit,
    User,
    UserModulePermission,
)
from app.services.auth import issue_access_token


def test_dashboard_only_exposes_modules_user_can_view(session):
    org = Organization(name="Agro Visibilidade", slug="agro-visibilidade", active=True)
    user = User(display_name="Operador Racao", active=True)
    session.add_all([org, user])
    session.flush()

    modules = [
        SystemModule(code="feed_mill", name="Fábrica de Ração", active=True),
        SystemModule(code="finance", name="Financeiro", active=True),
        SystemModule(code="livestock", name="Pecuária", active=True),
    ]
    session.add_all(modules)
    session.flush()

    session.add_all(
        [
            OrganizationModule(organization_id=org.id, module_code=row.code, enabled=True)
            for row in modules
        ]
    )
    unit = Unit(organization_id=org.id, code="SH7", name="Fazenda SH7", active=True)
    membership = Membership(
        organization_id=org.id,
        user_id=user.id,
        role="operator",
        active=True,
    )
    session.add_all([unit, membership])
    session.flush()

    session.add_all(
        [
            UserModulePermission(
                membership_id=membership.id,
                module_code="feed_mill",
                can_view=True,
                can_register=True,
                can_approve=False,
                can_configure=False,
            ),
            UserModulePermission(
                membership_id=membership.id,
                module_code="finance",
                can_view=False,
                can_register=False,
                can_approve=False,
                can_configure=False,
            ),
        ]
    )

    feed_event = Event(
        organization_id=org.id,
        unit_id=unit.id,
        actor_user_id=user.id,
        channel="telegram",
        source_type="text",
        source_original="Fiz uma batida da Seca 0,1",
        event_type="feed_mill.production",
        status="processed",
    )
    finance_event = Event(
        organization_id=org.id,
        unit_id=unit.id,
        actor_user_id=user.id,
        channel="telegram",
        source_type="text",
        source_original="Paguei uma conta",
        event_type="finance.payment",
        status="processed",
    )
    session.add_all([feed_event, finance_event])
    session.flush()
    session.add_all(
        [
            EventModuleTarget(
                event_id=feed_event.id,
                module_code="feed_mill",
                status="processed",
                requires_approval=False,
            ),
            EventModuleTarget(
                event_id=finance_event.id,
                module_code="finance",
                status="processed",
                requires_approval=False,
            ),
        ]
    )
    _, raw = issue_access_token(session, membership_id=membership.id, raw_token="visibility-token")
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        response = client.get(
            "/v1/dashboard/overview",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [row["code"] for row in body["modules"]] == ["feed_mill"]
        assert body["modules"][0]["can_register"] is True
        assert body["summary"]["events"] == 1
        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "feed_mill.production"

        decision = client.get(
            "/v1/dashboard/decision-overview",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["summary"]["feed_mill_visible"] is True
    finally:
        app.dependency_overrides.clear()
