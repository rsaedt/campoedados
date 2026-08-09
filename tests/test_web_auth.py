from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_db
from app.core.enums import MembershipRole
from app.main import app
from app.models.auth import UserCredential
from app.models.domain import AccessToken, Membership, Organization, User
from app.services.web_auth import hash_password, verify_password


def setup_org(session):
    org = Organization(name="Agro Login", slug="agro-login", active=True)
    admin = User(display_name="Rafael Admin", email=None, active=True)
    session.add_all([org, admin])
    session.flush()
    membership = Membership(
        organization_id=org.id,
        user_id=admin.id,
        role=MembershipRole.ADMIN.value,
        active=True,
    )
    session.add(membership)
    session.commit()
    return org, admin, membership


def client_with(session):
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def cleanup():
    app.dependency_overrides.clear()


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("SenhaForte123")
    second = hash_password("SenhaForte123")
    assert first != second
    assert verify_password("SenhaForte123", first) is True
    assert verify_password("SenhaErrada123", first) is False


def test_first_access_creates_user_login_and_web_session(session, monkeypatch):
    setup_org(session)
    monkeypatch.setenv("CAMPOEDADOS_ENV", "development")
    client = client_with(session)
    try:
        response = client.post(
            "/v1/auth/first-access",
            json={
                "organization_slug": "agro-login",
                "admin_name": "Rafael Admin",
                "login_name": "rafael",
                "password": "SenhaForte123",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["display_name"] == "Rafael Admin"
        assert "campoedados_session=" in response.headers.get("set-cookie", "")
        assert "HttpOnly" in response.headers.get("set-cookie", "")

        current = client.get("/v1/auth/session")
        assert current.status_code == 200, current.text
        assert current.json()["organization_slug"] == "agro-login"
    finally:
        cleanup()

    credential = session.scalar(select(UserCredential).where(UserCredential.login_name == "rafael"))
    assert credential is not None
    assert verify_password("SenhaForte123", credential.password_hash)


def test_first_access_is_blocked_after_admin_has_credentials(session, monkeypatch):
    setup_org(session)
    monkeypatch.setenv("CAMPOEDADOS_ENV", "development")
    client = client_with(session)
    payload = {
        "organization_slug": "agro-login",
        "admin_name": "Rafael Admin",
        "login_name": "rafael",
        "password": "SenhaForte123",
    }
    try:
        first = client.post("/v1/auth/first-access", json=payload)
        assert first.status_code == 200
        client.post("/v1/auth/logout")
        second = client.post("/v1/auth/first-access", json={**payload, "login_name": "outro"})
        assert second.status_code == 400
        assert "já foi configurado" in second.json()["detail"]
    finally:
        cleanup()


def test_login_with_user_and_password_then_logout(session, monkeypatch):
    org, admin, _ = setup_org(session)
    session.add(UserCredential(user_id=admin.id, login_name="rafael", password_hash=hash_password("SenhaForte123")))
    session.commit()
    monkeypatch.setenv("CAMPOEDADOS_ENV", "development")
    client = client_with(session)
    try:
        wrong = client.post("/v1/auth/login", json={"login_name": "rafael", "password": "SenhaErrada123"})
        assert wrong.status_code == 401

        login = client.post("/v1/auth/login", json={"login_name": "rafael", "password": "SenhaForte123"})
        assert login.status_code == 200, login.text
        assert login.json()["organization_id"] == org.id

        current = client.get("/v1/auth/session")
        assert current.status_code == 200

        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "Agente Gerencial" in dashboard.text
        assert "Token administrativo" not in dashboard.text

        logout = client.post("/v1/auth/logout")
        assert logout.status_code == 200
        after = client.get("/v1/auth/session")
        assert after.status_code == 401
    finally:
        cleanup()

    web_tokens = list(session.scalars(select(AccessToken).where(AccessToken.label == "web-session")))
    assert len(web_tokens) == 1
    assert web_tokens[0].revoked_at is not None


def test_dashboard_shows_user_login_without_cookie():
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 200
    assert "Use seu usuário e sua senha" in response.text
    assert "Token administrativo" not in response.text


def test_login_page_has_user_and_password_not_admin_token():
    response = TestClient(app).get("/login")
    assert response.status_code == 200
    assert "Use seu usuário e sua senha" in response.text
    assert "Token administrativo" not in response.text
