from fastapi import APIRouter, Depends

from app.api.deps import get_current_principal
from app.services.auth import Principal


router = APIRouter(prefix="/v1", tags=["identity"])


@router.get("/me")
def me(principal: Principal = Depends(get_current_principal)):
    return {
        "user_id": principal.user_id,
        "display_name": principal.user.display_name,
        "organization_id": principal.organization_id,
        "organization": principal.organization.name,
        "role": principal.membership.role,
    }
