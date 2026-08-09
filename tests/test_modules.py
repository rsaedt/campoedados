from app.core.enums import ModuleCode
from app.models.domain import Organization
from app.services.modules import module_enabled, set_module_enabled


def test_client_can_enable_only_one_module(session):
    org = Organization(name="Agropecuária Exemplo", slug="agro-exemplo")
    session.add(org)
    session.flush()

    set_module_enabled(session, org.id, ModuleCode.FEED_MILL.value, True)

    assert module_enabled(session, org.id, ModuleCode.FEED_MILL.value) is True
    assert module_enabled(session, org.id, ModuleCode.LIVESTOCK.value) is False
    assert module_enabled(session, org.id, ModuleCode.FINANCE.value) is False


def test_client_can_enable_any_combination(session):
    org = Organization(name="Agropecuária Completa", slug="agro-completa")
    session.add(org)
    session.flush()

    set_module_enabled(session, org.id, ModuleCode.LIVESTOCK.value, True)
    set_module_enabled(session, org.id, ModuleCode.FINANCE.value, True)

    assert module_enabled(session, org.id, ModuleCode.LIVESTOCK.value) is True
    assert module_enabled(session, org.id, ModuleCode.FEED_MILL.value) is False
    assert module_enabled(session, org.id, ModuleCode.FINANCE.value) is True
