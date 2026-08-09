from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.services.web_auth import SESSION_COOKIE


router = APIRouter(tags=["dashboard-ui"])
DASHBOARD_FILE = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"
LOGIN_FILE = Path(__file__).resolve().parents[1] / "dashboard" / "login.html"


@router.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(LOGIN_FILE, media_type="text/html")


@router.get("/dashboard", include_in_schema=False)
def dashboard_page(request: Request):
    if not request.cookies.get(SESSION_COOKIE):
        return RedirectResponse(url="/login", status_code=303)

    html = DASHBOARD_FILE.read_text(encoding="utf-8")
    html = html.replace(
        "</head>",
        "<style>#loginCover{display:none!important}</style></head>",
        1,
    )
    html = html.replace(
        "function token(){return sessionStorage.getItem('campoedados_token')||''}",
        "function token(){return ''}",
        1,
    )
    html = html.replace(
        "async function api(path,options={}){const headers={...(options.headers||{}),'Authorization':'Bearer '+token()};if(options.body&&!headers['Content-Type'])headers['Content-Type']='application/json';const r=await fetch(path,{...options,headers});let body=null;try{body=await r.json()}catch{}if(!r.ok)throw new Error(body?.detail||('Erro HTTP '+r.status));return body}",
        "async function api(path,options={}){const headers={...(options.headers||{})};if(options.body&&!headers['Content-Type'])headers['Content-Type']='application/json';const r=await fetch(path,{...options,headers,credentials:'same-origin'});let body=null;try{body=await r.json()}catch{}if(!r.ok){if(r.status===401){location.replace('/login');throw new Error('Sessão encerrada.')}throw new Error(body?.detail||('Erro HTTP '+r.status))}return body}",
        1,
    )
    html = html.replace(
        "function logout(){sessionStorage.removeItem('campoedados_token');location.reload()}",
        "async function logout(){try{await fetch('/v1/auth/logout',{method:'POST',credentials:'same-origin'})}finally{sessionStorage.removeItem('campoedados_token');location.replace('/login')}}",
        1,
    )
    html = html.replace(
        "async function refresh(){try{state=await api('/v1/dashboard/overview');render()}catch(e){if(/Token|401|autent/i.test(e.message)){sessionStorage.removeItem('campoedados_token');location.reload();return}showAlert(e.message,'err')}}",
        "async function refresh(){try{state=await api('/v1/dashboard/overview');render()}catch(e){if(/Sessão|401|autent/i.test(e.message)){location.replace('/login');return}showAlert(e.message,'err')}}",
        1,
    )
    html = html.replace(
        "</body>",
        "<script>sessionStorage.removeItem('campoedados_token');window.addEventListener('load',()=>refresh());</script></body>",
        1,
    )
    return HTMLResponse(html)
