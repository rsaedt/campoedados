from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.services.web_auth import SESSION_COOKIE


router = APIRouter(tags=["dashboard-ui"])
DASHBOARD_FILE = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"
LOGIN_FILE = Path(__file__).resolve().parents[1] / "dashboard" / "login.html"

_OLD_LOGIN_BLOCK = '''  <div class="login-cover" id="loginCover">
    <div class="login-card" id="loginCard">
      <h1>Campo & Dados</h1>
      <p>Dashboard de homologação. Informe o token administrativo. Ele fica somente nesta sessão do navegador.</p>
      <div id="loginAlert" class="alert err"></div>
      <div class="field"><label>Token administrativo</label><input id="tokenInput" type="password" autocomplete="off" placeholder="Cole o token" /></div>
      <div style="margin-top:14px"><button class="btn" id="loginBtn">Entrar</button></div>
    </div>
  </div>

'''

_OLD_LOGIN_FUNCTION = "async function login(){const t=document.getElementById('tokenInput').value.trim();if(!t)return;sessionStorage.setItem('campoedados_token',t);try{await api('/v1/me');document.getElementById('loginCover').style.display='none';await refresh()}catch(e){sessionStorage.removeItem('campoedados_token');const a=document.getElementById('loginAlert');a.textContent=e.message;a.className='alert err show'}}"

_OLD_BINDINGS = "document.getElementById('loginBtn').onclick=login;document.getElementById('tokenInput').addEventListener('keydown',e=>{if(e.key==='Enter')login()});document.getElementById('logoutBtn').onclick=logout;document.getElementById('adjustBtn').onclick=adjustInventory;document.getElementById('connectTelegramBtn').onclick=connectTelegram;"

_NEW_BINDINGS = "document.getElementById('logoutBtn').onclick=logout;document.getElementById('adjustBtn').onclick=adjustInventory;document.getElementById('connectTelegramBtn').onclick=connectTelegram;"

_PENDING_CONTACT_PANEL = '<div class="panel"><div class="panel-head"><h2>Contatos aguardando vínculo</h2><span class="hint">Envie uma mensagem ao bot para aparecer aqui.</span></div><div class="panel-body" id="pendingContacts"></div></div>'
_LINKED_CONTACT_PANEL = _PENDING_CONTACT_PANEL + '\n        <div class="panel"><div class="panel-head"><h2>Contatos vinculados</h2><span class="hint">Corrija usuário ou unidade padrão sem intervenção técnica.</span></div><div class="panel-body" id="linkedContacts"></div></div>'

_LINKED_CONTACT_JS = r'''
function renderLinkedContacts(){const el=document.getElementById('linkedContacts');if(!el)return;const rows=state.linked_contacts||[];if(!rows.length){el.innerHTML='<div class="empty">Nenhum contato vinculado.</div>';return}el.innerHTML=rows.map(c=>`<div class="contact"><div class="contact-top"><div><div class="contact-name">${esc(c.display_name||c.user_name)}</div><div class="hint">${esc(c.channel)} · Bot: ${esc(c.account_key)}</div></div><div class="hint">Unidade atual: <b>${esc(c.default_unit_code)}</b></div></div><div class="form-grid"><div class="field"><label>Usuário</label><select id="linked-member-${c.id}">${state.memberships.map(m=>`<option value="${esc(m.id)}" ${m.id===c.membership_id?'selected':''}>${esc(m.display_name)} — ${esc(m.role)}</option>`).join('')}</select></div><div class="field"><label>Unidade padrão</label><select id="linked-unit-${c.id}">${state.units.map(u=>`<option value="${esc(u.code)}" ${u.code===c.default_unit_code?'selected':''}>${esc(u.code)} — ${esc(u.name)}</option>`).join('')}</select></div></div><div style="margin-top:10px"><button class="btn small secondary" onclick="updateLinkedContact('${c.id}')">Salvar alteração</button></div></div>`).join('')}
async function updateLinkedContact(id){const payload={membership_id:document.getElementById('linked-member-'+id).value,default_unit_code:document.getElementById('linked-unit-'+id).value};try{await api(`/v1/dashboard/contacts/linked/${id}`,{method:'POST',body:JSON.stringify(payload)});showAlert('Vínculo atualizado. As próximas mensagens usarão a nova unidade.');await refresh()}catch(e){showAlert(e.message,'err')}}
'''.strip()


@router.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(LOGIN_FILE, media_type="text/html")


@router.get("/dashboard", include_in_schema=False)
def dashboard_page(request: Request):
    if not request.cookies.get(SESSION_COOKIE):
        return FileResponse(LOGIN_FILE, media_type="text/html")

    html = DASHBOARD_FILE.read_text(encoding="utf-8")
    html = html.replace(_OLD_LOGIN_BLOCK, "", 1)
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
    html = html.replace(_OLD_LOGIN_FUNCTION, "", 1)
    html = html.replace(
        "function logout(){sessionStorage.removeItem('campoedados_token');location.reload()}",
        "async function logout(){try{await fetch('/v1/auth/logout',{method:'POST',credentials:'same-origin'})}finally{sessionStorage.removeItem('campoedados_token');location.replace('/login')}}",
        1,
    )
    html = html.replace(
        "async function refresh(){try{state=await api('/v1/dashboard/overview');render()}catch(e){if(/Token|401|autent/i.test(e.message)){sessionStorage.removeItem('campoedados_token');location.reload();return}showAlert(e.message,'err')}}",
        "async function refresh(){try{state=await api('/v1/dashboard/overview');state.linked_contacts=state.me.role==='admin'?await api('/v1/dashboard/contacts/linked'):[];render()}catch(e){if(/Sessão|401|autent/i.test(e.message)){location.replace('/login');return}showAlert(e.message,'err')}}",
        1,
    )
    html = html.replace(_PENDING_CONTACT_PANEL, _LINKED_CONTACT_PANEL, 1)
    html = html.replace("  renderContacts();\n}", "  renderContacts();renderLinkedContacts();\n}", 1)
    html = html.replace(
        "async function managerDecision",
        _LINKED_CONTACT_JS + "\nasync function managerDecision",
        1,
    )
    html = html.replace(_OLD_BINDINGS, _NEW_BINDINGS, 1)
    html = html.replace(
        "if(token()){document.getElementById('loginCover').style.display='none';refresh()}",
        "refresh()",
        1,
    )
    html = html.replace(
        "</body>",
        "<script>sessionStorage.removeItem('campoedados_token');</script></body>",
        1,
    )
    return HTMLResponse(html)
