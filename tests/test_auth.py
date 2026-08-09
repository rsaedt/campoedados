import pytest

from app.models.domain import Membership, Organization, User
from app.services.auth import AuthenticationError, authenticate_access_token, issue_access_token


def test_access_token_is_scoped_to_membership(session):
    org = Organization(name="Agropecuária", slug="agro-auth")
    user = User(display_name="João", email="joao@example.com")
    session.add_all([org, user])
    session.flush()
    membership = Membership(organization_id=org.id, user_id=user.id, role="operator")
    session.add(membership)
    session.flush()

    _, raw = issue_access_token(session, membership_id=membership.id, raw_token="token-operador")
    principal = authenticate_access_token(session, raw)

    assert principal.user_id == user.id
    assert principal.organization_id == org.id
    assert principal.membership.id == membership.id


def test_invalid_access_token_is_rejected(session):
    with pytest.raises(AuthenticationError):
        authenticate_access_token(session, "inexistente")
