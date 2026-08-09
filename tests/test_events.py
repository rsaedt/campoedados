from sqlalchemy import select

from app.core.enums import ModuleCode
from app.models.domain import EventModuleTarget, Organization
from app.services.events import create_event
from app.services.modules import set_module_enabled


def test_event_targets_only_modules_enabled_for_client(session):
    org = Organization(name="Agro", slug="event-agro")
    session.add(org)
    session.flush()
    set_module_enabled(session, org.id, ModuleCode.FEED_MILL.value, True)

    event = create_event(
        session,
        organization_id=org.id,
        source_original="Chegou milho, segue NF",
        target_modules=[ModuleCode.FEED_MILL.value, ModuleCode.FINANCE.value],
        event_type="material_receipt",
    )

    targets = session.scalars(select(EventModuleTarget).where(EventModuleTarget.event_id == event.id)).all()
    assert [row.module_code for row in targets] == [ModuleCode.FEED_MILL.value]
