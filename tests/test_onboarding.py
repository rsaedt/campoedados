from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.database import Base
from app.models.domain import (
    AccessToken,
    AuditEntry,
    Membership,
    Organization,
    OrganizationModule,
    Unit,
    UserModulePermission,
)
from app.services.auth import authenticate_access_token
from app.services.onboarding import OnboardingError, OnboardingUnit, onboard_organization


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


def test_onboarding_creates_org_admin_units_entitlements_permissions_and_token():
    session = make_session()
    result = onboard_organization(
        session,
        organization_name="Agro Homologação",
        organization_slug="agro-homolog",
        admin_name="Administrador",
        admin_email=None,
        units=[
            OnboardingUnit(code="sh7", name="Fazenda SH7"),
            OnboardingUnit(code="NSG", name="Fazenda NSG"),
        ],
        modules=["feed_mill", "finance"],
    )
    session.commit()

    assert result.organization.slug == "agro-homolog"
    assert [unit.code for unit in result.units] == ["SH7", "NSG"]
    assert result.enabled_modules == ("feed_mill", "finance")

    entitlements = session.scalars(
        select(OrganizationModule).where(
            OrganizationModule.organization_id == result.organization.id
        )
    ).all()
    enabled = {row.module_code for row in entitlements if row.enabled}
    disabled = {row.module_code for row in entitlements if not row.enabled}
    assert enabled == {"feed_mill", "finance"}
    assert disabled == {"livestock"}

    permissions = session.scalars(
        select(UserModulePermission).where(
            UserModulePermission.membership_id == result.admin_membership.id
        )
    ).all()
    by_module = {row.module_code: row for row in permissions}
    assert by_module["feed_mill"].can_view is True
    assert by_module["finance"].can_approve is True
    assert by_module["livestock"].can_view is False
    assert by_module["livestock"].can_register is False

    principal = authenticate_access_token(session, result.raw_admin_token)
    assert principal.organization_id == result.organization.id
    assert principal.membership.role == "admin"

    stored_token = session.scalar(
        select(AccessToken).where(AccessToken.membership_id == result.admin_membership.id)
    )
    assert stored_token is not None
    assert stored_token.token_hash != result.raw_admin_token

    audit = session.scalar(
        select(AuditEntry).where(
            AuditEntry.organization_id == result.organization.id,
            AuditEntry.action == "organization_onboarded",
        )
    )
    assert audit is not None
    assert audit.details["unit_codes"] == ["SH7", "NSG"]


def test_onboarding_refuses_existing_slug_without_silent_customer_update():
    session = make_session()
    first = onboard_organization(
        session,
        organization_name="Primeira",
        organization_slug="cliente-um",
        admin_name="Admin",
        admin_email="admin@example.test",
        units=[OnboardingUnit(code="U1", name="Unidade 1")],
        modules=["livestock"],
    )
    session.commit()

    try:
        onboard_organization(
            session,
            organization_name="Nome Alterado",
            organization_slug="cliente-um",
            admin_name="Outro",
            admin_email=None,
            units=[OnboardingUnit(code="U2", name="Unidade 2")],
            modules=["finance"],
        )
        raise AssertionError("Onboarding deveria recusar slug existente")
    except OnboardingError as exc:
        assert "Já existe organização" in str(exc)
        session.rollback()

    assert session.scalar(select(Organization).where(Organization.id == first.organization.id)).name == "Primeira"
    assert len(session.scalars(select(Unit)).all()) == 1
    assert len(session.scalars(select(Membership)).all()) == 1
