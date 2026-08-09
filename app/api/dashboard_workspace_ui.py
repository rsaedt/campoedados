from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.api.dashboard_ui import dashboard_page as base_dashboard_page
from app.api.dashboard_ui import login_page as base_login_page
from app.services.dashboard_module_ui import enhance_dashboard_module_ui


router = APIRouter(tags=["dashboard-ui"])


@router.get("/login", include_in_schema=False)
def login_page():
    return base_login_page()


@router.get("/dashboard", include_in_schema=False)
def dashboard_page(request: Request):
    response = base_dashboard_page(request)
    if isinstance(response, HTMLResponse):
        html = response.body.decode("utf-8")
        return HTMLResponse(
            enhance_dashboard_module_ui(html),
            status_code=response.status_code,
        )
    return response
