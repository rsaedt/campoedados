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

_OLD_OVERVIEW = '''      <section class="page active" id="page-overview">
        <div class="title-row"><div><h1>Visão geral</h1><p class="subtitle">Situação atual da operação.</p></div><button class="btn secondary" onclick="refresh()">Atualizar</button></div>
        <div class="cards" id="summaryCards"></div>
        <div class="grid2">
          <div class="panel"><div class="panel-head"><h2>Módulos liberados</h2></div><div class="panel-body"><div class="modules" id="modules"></div></div></div>
          <div class="panel"><div class="panel-head"><h2>Unidades</h2></div><div class="panel-body" id="unitsOverview"></div></div>
        </div>
        <div class="panel"><div class="panel-head"><h2>Últimos eventos</h2></div><div class="table-wrap" id="overviewEvents"></div></div>
      </section>'''

_NEW_OVERVIEW = '''      <section class="page active" id="page-overview">
        <div class="title-row"><div><h1>Visão geral</h1><p class="subtitle">A operação inteira em uma tela: estoque, fazendas, pendências e últimos acontecimentos.</p></div><button class="btn secondary" onclick="refresh()">Atualizar</button></div>
        <div class="cards" id="summaryCards"></div>
        <div class="panel"><div class="panel-head"><h2>Situação por fazenda</h2><span class="hint">Estoque e atenção operacional de cada unidade.</span></div><div class="panel-body"><div class="farm-grid" id="farmOverview"></div></div></div>
        <div class="grid2">
          <div class="panel"><div class="panel-head"><h2>Pontos de atenção</h2></div><div class="panel-body" id="attentionOverview"></div></div>
          <div class="panel"><div class="panel-head"><h2>Módulos liberados</h2></div><div class="panel-body"><div class="modules" id="modules"></div></div></div>
        </div>
        <div class="panel"><div class="panel-head"><h2>Últimos acontecimentos</h2></div><div class="table-wrap" id="overviewEvents"></div></div>
      </section>'''

_DECISION_STYLES = '''
    .farm-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.farm-card{border:1px solid var(--line);border-radius:13px;padding:16px;background:#fbfcfb}.farm-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:13px}.farm-code{font-size:19px;font-weight:850;color:var(--brand2)}.farm-name{font-size:12px;color:var(--muted);margin-top:2px}.farm-value{text-align:right}.farm-value strong{display:block;font-size:20px}.farm-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}.farm-metric{background:#f1f5f2;border-radius:9px;padding:9px}.farm-metric b{display:block;font-size:16px}.farm-metric span{font-size:10px;color:var(--muted);text-transform:uppercase}.stock-list{border-top:1px solid var(--line);padding-top:10px}.stock-row{display:flex;justify-content:space-between;gap:12px;padding:5px 0;font-size:12px}.stock-row span:last-child{font-weight:750;white-space:nowrap}.farm-foot{margin-top:9px;font-size:11px;color:var(--muted)}.attention-item{padding:11px 0;border-bottom:1px solid #edf0ed}.attention-item:last-child{border-bottom:0}.attention-title{font-weight:800;font-size:13px}.attention-meta{font-size:11px;color:var(--muted);margin-top:3px}.attention-text{font-size:12px;margin-top:5px;line-height:1.4}.attention-manager .attention-title{color:#7d5100}.attention-complement .attention-title{color:#7c4b13}.ok-state{padding:18px;border-radius:10px;background:#e7f5ea;color:#235f35;text-align:center;font-weight:700}.neutral-note{font-size:11px;color:var(--muted);margin-top:7px}.status-label{white-space:nowrap}
    @media(max-width:900px){.farm-grid{grid-template-columns:1fr}}@media(max-width:650px){.farm-metrics{grid-template-columns:1fr 1fr}.farm-head{flex-direction:column}.farm-value{text-align:left}}
'''

_LINKED_CONTACT_JS = r'''
function renderLinkedContacts(){const el=document.getElementById('linkedContacts');if(!el)return;const rows=state.linked_contacts||[];if(!rows.length){el.innerHTML='<div class="empty">Nenhum contato vinculado.</div>';return}el.innerHTML=rows.map(c=>`<div class="contact"><div class="contact-top"><div><div class="contact-name">${esc(c.display_name||c.user_name)}</div><div class="hint">${esc(c.channel)} · Bot: ${esc(c.account_key)}</div></div><div class="hint">Unidade atual: <b>${esc(c.default_unit_code)}</b></div></div><div class="form-grid"><div class="field"><label>Usuário</label><select id="linked-member-${c.id}">${state.memberships.map(m=>`<option value="${esc(m.id)}" ${m.id===c.membership_id?'selected':''}>${esc(m.display_name)} — ${esc(m.role)}</option>`).join('')}</select></div><div class="field"><label>Unidade padrão</label><select id="linked-unit-${c.id}">${state.units.map(u=>`<option value="${esc(u.code)}" ${u.code===c.default_unit_code?'selected':''}>${esc(u.code)} — ${esc(u.name)}</option>`).join('')}</select></div></div><div style="margin-top:10px"><button class="btn small secondary" onclick="updateLinkedContact('${c.id}')">Salvar alteração</button></div></div>`).join('')}
async function updateLinkedContact(id){const payload={membership_id:document.getElementById('linked-member-'+id).value,default_unit_code:document.getElementById('linked-unit-'+id).value};try{await api(`/v1/dashboard/contacts/linked/${id}`,{method:'POST',body:JSON.stringify(payload)});showAlert('Vínculo atualizado. As próximas mensagens usarão a nova unidade.');await refresh()}catch(e){showAlert(e.message,'err')}}
'''.strip()

_DECISION_JS = r'''
const STATUS_LABELS={processed:'Processado',waiting_manager:'Aguardando gerencial',waiting_complement:'Aguardando complemento',rejected:'Rejeitado',received:'Recebido',interpreted:'Interpretado',approved:'Aprovado'};
const EVENT_TYPE_LABELS={'feed_mill.production':'Produção de ração','feed_mill.transfer_dispatch':'Transferência de ração','feed_mill.transfer_receipt':'Recebimento de transferência','feed_mill.purchase_receipt':'Recebimento de insumo','finance.purchase':'Compra / financeiro','livestock.movement':'Movimentação pecuária'};
const CHANNEL_LABELS={telegram:'Telegram',whatsapp:'WhatsApp',api:'API',internal:'Interno'};
function statusLabel(v){return STATUS_LABELS[v]||String(v||'-').replaceAll('_',' ')}
function eventTypeLabel(v){return EVENT_TYPE_LABELS[v]||String(v||'-').replaceAll('_',' ').replaceAll('.',' · ')}
function channelLabel(v){return CHANNEL_LABELS[v]||String(v||'-')}
function dateLabel(v){return v?new Date(v).toLocaleString('pt-BR'):'-'}
function renderDecisionOverview(){
  const d=state.decision||{summary:{},unit_summaries:[],attention_items:[],manager_details:{}};
  const s=state.summary;const metrics=[['Estoque (valor)',money.format(d.summary.inventory_value||0),true],['Pend. gerencial',fmt.format(s.pending_manager||0)],['Aguard. complemento',fmt.format(d.summary.waiting_complement||0)],['Produções',fmt.format(d.summary.production_count||0)],['Unidades',fmt.format(s.units||0)],['Eventos',fmt.format(s.events||0)]];
  document.getElementById('summaryCards').innerHTML=metrics.map(x=>`<div class="card"><div class="label">${x[0]}</div><div class="metric ${x[2]?'money-metric':''}">${x[1]}</div></div>`).join('');
  const farms=document.getElementById('farmOverview');
  farms.innerHTML=d.unit_summaries.length?d.unit_summaries.map(u=>{const pending=(u.pending_manager||0)+(u.waiting_complement||0);const stock=u.stock_items?.length?`<div class="stock-list">${u.stock_items.map(i=>`<div class="stock-row"><span>${esc(i.product_name)}</span><span>${fmt.format(i.quantity)} ${esc(i.base_unit)} · ${money.format(i.total_value)}</span></div>`).join('')}</div>`:'<div class="neutral-note">Nenhum produto com saldo nesta unidade.</div>';return `<div class="farm-card"><div class="farm-head"><div><div class="farm-code">${esc(u.unit_code)}</div><div class="farm-name">${esc(u.unit_name)}</div></div><div class="farm-value"><span class="label">Valor em estoque</span><strong>${money.format(u.inventory_value||0)}</strong></div></div><div class="farm-metrics"><div class="farm-metric"><b>${fmt.format(u.stocked_products||0)}</b><span>Itens com saldo</span></div><div class="farm-metric"><b>${fmt.format(u.zero_raw_material_count||0)}</b><span>Matérias-primas sem saldo</span></div><div class="farm-metric"><b>${fmt.format(pending)}</b><span>Pendências</span></div></div>${stock}<div class="farm-foot">Último evento: ${dateLabel(u.latest_event_at)}${u.latest_production_at?' · Última produção: '+dateLabel(u.latest_production_at):''}</div></div>`}).join(''):'<div class="empty">Nenhuma unidade cadastrada.</div>';
  const attention=[...(d.attention_items||[])];if((s.pending_contacts||0)>0)attention.push({kind:'contact',source_original:`${s.pending_contacts} contato(s) do Telegram aguardando vínculo.`});
  const attentionEl=document.getElementById('attentionOverview');
  attentionEl.innerHTML=attention.length?attention.map(a=>{const title=a.kind==='manager'?'Aguardando decisão gerencial':a.kind==='complement'?'Aguardando complemento':'Contato aguardando vínculo';const cls=a.kind==='manager'?'attention-manager':a.kind==='complement'?'attention-complement':'';const text=a.reason||a.source_original||'';return `<div class="attention-item ${cls}"><div class="attention-title">${title}</div><div class="attention-meta">${esc(a.unit_code||'')} ${a.channel?'· '+esc(channelLabel(a.channel)):''} ${a.received_at?'· '+dateLabel(a.received_at):''}</div><div class="attention-text">${esc(text)}</div></div>`}).join(''):'<div class="ok-state">Nenhuma pendência operacional neste momento.</div>';
}
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
    html = html.replace(_OLD_OVERVIEW, _NEW_OVERVIEW, 1)
    html = html.replace("</style>", _DECISION_STYLES + "  </style>", 1)
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
        "function statusBadge(s){return `<span class=\"status ${esc(s)}\">${esc(s)}</span>`}",
        _DECISION_JS + "\nfunction statusBadge(s){return `<span class=\"status ${esc(s)} status-label\">${esc(statusLabel(s))}</span>`}",
        1,
    )
    html = html.replace(
        "async function refresh(){try{state=await api('/v1/dashboard/overview');render()}catch(e){if(/Token|401|autent/i.test(e.message)){sessionStorage.removeItem('campoedados_token');location.reload();return}showAlert(e.message,'err')}}",
        "async function refresh(){try{state=await api('/v1/dashboard/overview');state.decision=await api('/v1/dashboard/decision-overview');state.linked_contacts=state.me.role==='admin'?await api('/v1/dashboard/contacts/linked'):[];render()}catch(e){if(/Sessão|401|autent/i.test(e.message)){location.replace('/login');return}showAlert(e.message,'err')}}",
        1,
    )
    html = html.replace(
        "  const s=state.summary;const metrics=[['Eventos',s.events],['Processados',s.processed],['Pend. gerencial',s.pending_manager],['Contatos Telegram',s.pending_contacts],['Unidades',s.units],['Produtos',s.products]];\n  document.getElementById('summaryCards').innerHTML=metrics.map(x=>`<div class=\"card\"><div class=\"label\">${x[0]}</div><div class=\"metric\">${fmt.format(x[1])}</div></div>`).join('');\n  document.getElementById('modules').innerHTML=state.modules.map(m=>`<span class=\"module\">${esc(m.name)}</span>`).join('')||'<span class=\"muted\">Nenhum módulo.</span>';\n  document.getElementById('unitsOverview').innerHTML=state.units.map(u=>`<div><b>${esc(u.code)}</b> — ${esc(u.name)}</div>`).join('');",
        "  document.getElementById('modules').innerHTML=state.modules.map(m=>`<span class=\"module\">${esc(m.name)}</span>`).join('')||'<span class=\"muted\">Nenhum módulo.</span>';\n  renderDecisionOverview();",
        1,
    )
    html = html.replace(
        "  const eventRows=state.events.map(e=>`<tr><td class=\"nowrap\">${new Date(e.received_at).toLocaleString('pt-BR')}</td><td>${esc(e.unit_code||'-')}</td><td>${esc(e.channel)}</td><td>${esc(e.event_type||'-')}</td><td>${statusBadge(e.status)}</td><td class=\"source\">${esc(e.source_original)}</td></tr>`);\n  const eventHtml=table(['Data','Unidade','Canal','Tipo','Status','Origem'],eventRows);document.getElementById('eventsTable').innerHTML=eventHtml;document.getElementById('overviewEvents').innerHTML=table(['Data','Unidade','Tipo','Status','Origem'],eventRows.slice(0,8).map(r=>r.replace(/<td>[^<]*<\\/td><td>/,'<td>')));",
        "  const eventRows=state.events.map(e=>`<tr><td class=\"nowrap\">${dateLabel(e.received_at)}</td><td>${esc(e.unit_code||'-')}</td><td>${esc(channelLabel(e.channel))}</td><td>${esc(eventTypeLabel(e.event_type))}</td><td>${statusBadge(e.status)}</td><td class=\"source\">${esc(e.source_original)}</td></tr>`);\n  const eventHtml=table(['Data','Unidade','Canal','Tipo','Status','Origem'],eventRows);document.getElementById('eventsTable').innerHTML=eventHtml;const overviewRows=state.events.slice(0,8).map(e=>`<tr><td class=\"nowrap\">${dateLabel(e.received_at)}</td><td>${esc(e.unit_code||'-')}</td><td>${esc(channelLabel(e.channel))}</td><td>${esc(eventTypeLabel(e.event_type))}</td><td>${statusBadge(e.status)}</td><td class=\"source\">${esc(e.source_original)}</td></tr>`);document.getElementById('overviewEvents').innerHTML=table(['Data','Unidade','Canal','Tipo','Status','Origem'],overviewRows);",
        1,
    )
    html = html.replace(
        "  const managerRows=state.pending_manager.map(e=>`<tr><td>${esc(e.unit_code||'-')}</td><td>${esc(e.event_type)}</td><td class=\"source\">${esc(e.source_original)}</td><td>${statusBadge(e.status)}</td><td><div class=\"actions\"><button class=\"btn small\" onclick=\"managerDecision('${e.event_id}','approve')\">Aprovar</button><button class=\"btn danger small\" onclick=\"managerDecision('${e.event_id}','reject')\">Rejeitar</button></div></td></tr>`);document.getElementById('managerTable').innerHTML=table(['Unidade','Tipo','Origem','Status','Ação'],managerRows);",
        "  const managerRows=state.pending_manager.map(e=>{const d=(state.decision?.manager_details||{})[e.event_id]||{};return `<tr><td class=\"nowrap\">${dateLabel(d.received_at)}</td><td>${esc(e.unit_code||'-')}</td><td>${esc(channelLabel(d.channel))}</td><td>${esc(eventTypeLabel(e.event_type))}</td><td>${esc(d.reason||'-')}</td><td class=\"source\">${esc(e.source_original)}</td><td>${statusBadge(e.status)}</td><td><div class=\"actions\"><button class=\"btn small\" onclick=\"managerDecision('${e.event_id}','approve')\">Aprovar</button><button class=\"btn danger small\" onclick=\"managerDecision('${e.event_id}','reject')\">Rejeitar</button></div></td></tr>`});document.getElementById('managerTable').innerHTML=table(['Data','Unidade','Canal','Tipo','Motivo','Origem','Status','Ação'],managerRows);",
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
