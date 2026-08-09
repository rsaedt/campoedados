from __future__ import annotations


_OLD_NAV = '''    <nav>
      <button class="navbtn active" data-page="overview">Visão geral</button>
      <button class="navbtn" data-page="events">Eventos</button>
      <button class="navbtn" data-page="manager">Gerencial</button>
      <button class="navbtn" data-page="inventory">Estoque</button>
      <button class="navbtn" data-page="telegram">Telegram</button>
      <button class="navbtn" id="logoutBtn">Sair</button>
    </nav>'''

_NEW_NAV = '''    <nav>
      <div class="nav-section-label">GERAL</div>
      <button class="navbtn active" data-page="overview">Visão geral</button>
      <button class="navbtn" data-page="events">Eventos</button>

      <div class="nav-section-label">MÓDULOS</div>
      <div id="moduleNav" class="module-nav"></div>

      <div id="managementNav">
        <div class="nav-section-label">GESTÃO</div>
        <button class="navbtn" id="navManager" data-page="manager">Gerencial</button>
        <button class="navbtn" id="navTelegram" data-page="telegram">Telegram</button>
      </div>

      <div class="nav-separator"></div>
      <button class="navbtn" id="logoutBtn">Sair</button>
    </nav>'''

_MODULE_PAGE = '''
      <section class="page" id="page-module">
        <div class="module-context-strip">Módulo atual</div>
        <div class="title-row">
          <div><h1 id="modulePageTitle">Módulo</h1><p class="subtitle" id="modulePageSubtitle"></p></div>
          <button class="btn secondary" onclick="refresh()">Atualizar</button>
        </div>
        <div id="modulePageBody"></div>
      </section>
'''

_MODULE_STYLES = '''
    .nav-section-label{font-size:10px;font-weight:800;letter-spacing:.12em;color:#7a857d;margin:16px 12px 4px}.nav-section-label:first-child{margin-top:0}.module-nav{display:flex;flex-direction:column;gap:5px}.nav-separator{height:1px;background:var(--line);margin:13px 8px}.navbtn.module-btn{position:relative;padding-left:24px}.navbtn.module-btn:before{content:'';position:absolute;left:11px;top:50%;width:6px;height:6px;border-radius:999px;background:#9bae9f;transform:translateY(-50%)}.navbtn.module-btn.active:before{background:var(--brand)}
    .module-context-strip{display:inline-flex;align-items:center;gap:7px;background:#e4eee6;color:var(--brand2);font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.07em;padding:6px 10px;border-radius:999px;margin-bottom:10px}.module-home-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:18px}.module-home-card{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:16px;box-shadow:var(--shadow)}.module-home-card .value{font-size:23px;font-weight:850;margin-top:6px}.module-actions{display:flex;gap:9px;flex-wrap:wrap;margin:12px 0 18px}.permission-list{display:flex;gap:7px;flex-wrap:wrap}.permission-pill{font-size:11px;font-weight:750;padding:5px 9px;border-radius:999px;background:#edf3ee;color:#36523e}.module-chip-btn{border:0;background:#edf3ee;color:#36523e;padding:7px 11px;border-radius:999px;font-size:12px;font-weight:800;cursor:pointer}.module-chip-btn:hover{background:#dce8df}.module-inline-context{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:800;color:var(--brand2);margin:0 0 12px;padding:8px 11px;background:#e7efe8;border-radius:9px;width:max-content;max-width:100%}
    @media(max-width:900px){.module-home-grid{grid-template-columns:1fr 1fr}}@media(max-width:650px){.module-home-grid{grid-template-columns:1fr}}
'''

_MODULE_JS = r'''
const MODULE_LABELS={feed_mill:'Fábrica de Ração',finance:'Financeiro',livestock:'Pecuária'};
let currentModuleCode=null;
function moduleLabel(code,name){return name||MODULE_LABELS[code]||code}
function modulePermissionPills(m){const rows=[];if(m.can_view)rows.push('Visualizar');if(m.can_register)rows.push('Registrar');if(m.can_approve)rows.push('Aprovar');if(m.can_configure)rows.push('Configurar');return rows.map(x=>`<span class="permission-pill">${x}</span>`).join('')}
function eventMatchesModule(e,code){return String(e.event_type||'').startsWith(code+'.')}
function activateModuleButton(code){document.querySelectorAll('.navbtn').forEach(x=>x.classList.remove('active'));const b=document.querySelector(`[data-module-code="${code}"]`);if(b)b.classList.add('active')}
function showOnlyPage(pageId){document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));const page=document.getElementById('page-'+pageId);if(page)page.classList.add('active')}
function openModule(code){const m=(state.modules||[]).find(x=>x.code===code);if(!m)return;currentModuleCode=code;activateModuleButton(code);showOnlyPage('module');renderModulePage(m)}
function openModuleSection(pageId,code){const m=(state.modules||[]).find(x=>x.code===code);if(!m)return;currentModuleCode=code;activateModuleButton(code);showOnlyPage(pageId)}
function renderModulePage(m){
  const title=moduleLabel(m.code,m.name);document.getElementById('modulePageTitle').textContent=title;document.getElementById('modulePageSubtitle').textContent='Você está trabalhando neste módulo.';
  const events=(state.events||[]).filter(e=>eventMatchesModule(e,m.code));
  const recent=events.slice(0,6).map(e=>`<tr><td>${dateLabel(e.received_at)}</td><td>${esc(e.unit_code||'-')}</td><td>${esc(channelLabel(e.channel))}</td><td>${esc(eventTypeLabel(e.event_type))}</td><td>${statusBadge(e.status)}</td><td>${esc(e.source_original)}</td></tr>`);
  let body=`<div class="panel"><div class="panel-head"><h2>Acesso ao módulo</h2></div><div class="panel-body"><div class="permission-list">${modulePermissionPills(m)}</div></div></div>`;
  if(m.code==='feed_mill'){
    const stockValue=(state.decision?.summary?.inventory_value||0);const productions=(state.productions||[]).length;const stocked=(state.inventory||[]).filter(i=>Number(i.quantity)>0).length;
    body+=`<div class="module-home-grid"><div class="module-home-card"><div class="label">Valor em estoque</div><div class="value">${money.format(stockValue)}</div></div><div class="module-home-card"><div class="label">Itens com saldo</div><div class="value">${fmt.format(stocked)}</div></div><div class="module-home-card"><div class="label">Produções recentes</div><div class="value">${fmt.format(productions)}</div></div></div><div class="module-actions"><button class="btn" onclick="openModuleSection('inventory','feed_mill')">Abrir estoque</button>${m.can_approve?`<button class="btn secondary" onclick="showOnlyPage('manager');activateModuleButton('feed_mill')">Ver pendências gerenciais</button>`:''}</div>`;
  }
  body+=`<div class="panel"><div class="panel-head"><h2>Atividade recente — ${esc(title)}</h2></div><div class="table-wrap">${table(['Data','Unidade','Canal','Tipo','Status','Origem'],recent)}</div></div>`;
  document.getElementById('modulePageBody').innerHTML=body;
}
function renderModuleNavigation(){
  const modules=state.modules||[];const nav=document.getElementById('moduleNav');if(nav)nav.innerHTML=modules.length?modules.map(m=>`<button class="navbtn module-btn" data-page="module" data-module-code="${esc(m.code)}" onclick="openModule('${esc(m.code)}')">${esc(moduleLabel(m.code,m.name))}</button>`).join(''):'<div class="hint" style="padding:6px 12px">Nenhum módulo disponível.</div>';
  const chips=document.getElementById('modules');if(chips)chips.innerHTML=modules.length?modules.map(m=>`<button class="module-chip-btn" onclick="openModule('${esc(m.code)}')">${esc(moduleLabel(m.code,m.name))}</button>`).join(''):'<span class="muted">Nenhum módulo disponível.</span>';
  const manager=document.getElementById('navManager');if(manager)manager.style.display=modules.some(m=>m.can_approve)?'':'none';const telegram=document.getElementById('navTelegram');if(telegram)telegram.style.display=state.me?.role==='admin'?'':'none';const management=document.getElementById('managementNav');if(management)management.style.display=((manager&&manager.style.display!=='none')||(telegram&&telegram.style.display!=='none'))?'':'none';
}
const _campoBaseRender=render;render=function(){_campoBaseRender();renderModuleNavigation();if(currentModuleCode){const m=(state.modules||[]).find(x=>x.code===currentModuleCode);if(m&&document.getElementById('page-module')?.classList.contains('active'))renderModulePage(m)}};
document.querySelectorAll('.navbtn[data-page]').forEach(b=>b.addEventListener('click',()=>{if(b.dataset.page!=='module')currentModuleCode=null}));
'''.strip()


def enhance_dashboard_module_ui(html: str) -> str:
    html = html.replace(_OLD_NAV, _NEW_NAV, 1)
    html = html.replace("Módulos liberados", "Seus módulos")
    html = html.replace("</main>", _MODULE_PAGE + "    </main>", 1)
    html = html.replace("</style>", _MODULE_STYLES + "  </style>", 1)
    html = html.replace(
        '<section class="page" id="page-inventory">',
        '<section class="page" id="page-inventory"><div class="module-inline-context">Fábrica de Ração · Estoque</div>',
        1,
    )
    html = html.replace("</body>", f"<script>{_MODULE_JS}</script></body>", 1)
    return html
