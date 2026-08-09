from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(tags=["dashboard-ui"])
DASHBOARD_FILE = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"


@router.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return FileResponse(DASHBOARD_FILE, media_type="text/html")
