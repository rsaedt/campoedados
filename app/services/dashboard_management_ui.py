from __future__ import annotations


_MANAGEMENT_STYLES = r'''
    .mgmt-box{border:1px solid var(--line);border-radius:12px;padding:15px;background:#fbfcfb;margin-top:16px}.mgmt-box h3{font-size:14px;margin:0 0 5px}.mgmt-box .hint{margin-bottom:12px}.mgmt-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}.mgmt-current{font-size:12px;color:var(--muted);margin-top:6px}.attention-action{margin-top:8px}.attention-action .btn{font-size:11px;padding:5px 8px}
'''.strip()


_MANAGEMENT_JS = r'''
const _campoEventTypeLabel=eventTypeLabel;
eventTypeLabel=function(v){if(v==='inventory.consumption')return 'Consumo na fazenda';return _campoEventTypeLabel(v)};

function canManageStock(){const m=(state?.modules||[]).find(x=>x.code==='feed_mill');return !!m?.can_configure}
function canCloseIncomplete(){return (state?.modules||[]).some(m=>m.can_approve)}
function correctionCurrent(){const unit=document.getElementById('mgmtCorrectionUnit')?.value;const product=document.getElementById('mgmtCorrectionProduct')?.value;return (feedMillWorkspace?.inventory||[]).find(x=>x.unit_code===unit&&x.product_id===product)}
function updateCorrectionCurrent(){const el=document.getElementById('mgmtCorrectionCurrent');if(!el)return;const row=correctionCurrent();el.textContent=row?`Saldo atual: ${fmt.format(row.quantity)} ${row.base_unit} · custo médio ${money.format(row.avg_unit_cost)}`:'Saldo atual: 0'}
function correctionForm(){if(!canManageStock())return '';const units=(state?.units||[]).map(u=>`<option value="${esc(u.code)}">${esc(u.code)} — ${esc(u.name)}</option>`).join('');const products=(state?.products||[]).map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');return `<div class="mgmt-box"><h3>Correção gerencial de estoque</h3><div class="hint">Use somente para corrigir a realidade física encontrada. O lançamento original não é apagado; o Campo e Dados cria um movimento compensatório auditado.</div><div class="form-grid"><div class="field"><label>Fazenda</label><select id="mgmtCorrectionUnit" onchange="updateCorrectionCurrent()">${units}</select></div><div class="field"><label>Produto</label><select id="mgmtCorrectionProduct" onchange="updateCorrectionCurrent()">${products}</select></div><div class="field"><label>Saldo físico correto</label><input id="mgmtCorrectionQty" type="number" min="0" step="0.0001" placeholder="Ex.: 0" /></div><div class="field"><label>Custo unitário</label><input id="mgmtCorrectionCost" type="number" min="0" step="0.000001" placeholder="Só se aumentar estoque sem saldo" /></div><div class="field full"><label>Motivo da correção</label><input id="mgmtCorrectionReason" maxlength="500" placeholder="Ex.: correção de saldo de homologação" /></div></div><div class="mgmt-current" id="mgmtCorrectionCurrent"></div><div class="mgmt-actions"><button class="btn secondary" onclick="submitStockCorrection()">Corrigir saldo</button></div></div>`}

async function submitStockCorrection(){const unit=document.getElementById('mgmtCorrectionUnit')?.value;const product=document.getElementById('mgmtCorrectionProduct')?.value;const qty=document.getElementById('mgmtCorrectionQty')?.value;const cost=document.getElementById('mgmtCorrectionCost')?.value;const reason=document.getElementById('mgmtCorrectionReason')?.value?.trim();if(qty===''||!reason){showAlert('Informe o saldo físico correto e o motivo da correção.','err');return}const payload={unit_code:unit,product_id:product,target_quantity:Number(qty),reason};if(cost!=='')payload.unit_cost=Number(cost);try{const r=await api('/v1/dashboard/management/stock/corrections',{method:'POST',body:JSON.stringify(payload)});showAlert(`Saldo corrigido: ${r.product_name} em ${r.unit_code}.`);feedMillWorkspace=null;await refresh();const m=(state.modules||[]).find(x=>x.code==='feed_mill');if(m)await renderFeedMillPage(m,true)}catch(e){showAlert(e.message,'err')}}

const _campoRenderFeedMillInventory=renderFeedMillInventory;
renderFeedMillInventory=function(d){const html=_campoRenderFeedMillInventory(d);setTimeout(updateCorrectionCurrent,0);return html+correctionForm()};

async function closeIncompleteEvent(id){const reason=window.prompt('Motivo para encerrar esta ocorrência sem processamento:','Evento antigo de homologação');if(!reason||reason.trim().length<3)return;try{await api(`/v1/dashboard/management/events/${id}/close`,{method:'POST',body:JSON.stringify({reason:reason.trim()})});showAlert('Ocorrência encerrada e preservada no histórico.');await refresh()}catch(e){showAlert(e.message,'err')}}

function renderManagementAttention(){const d=state.decision||{attention_items:[]};const s=state.summary||{};const attention=[...(d.attention_items||[])];if((s.pending_contacts||0)>0)attention.push({kind:'contact',source_original:`${s.pending_contacts} contato(s) do Telegram aguardando vínculo.`});const el=document.getElementById('attentionOverview');if(!el)return;el.innerHTML=attention.length?attention.map(a=>{const title=a.kind==='manager'?'Aguardando decisão gerencial':a.kind==='complement'?'Aguardando complemento':'Contato aguardando vínculo';const cls=a.kind==='manager'?'attention-manager':a.kind==='complement'?'attention-complement':'';const text=a.reason||a.source_original||'';const action=a.kind==='complement'&&a.event_id&&canCloseIncomplete()?`<div class="attention-action"><button class="btn secondary" onclick="closeIncompleteEvent('${a.event_id}')">Encerrar pendência</button></div>`:'';return `<div class="attention-item ${cls}"><div class="attention-title">${title}</div><div class="attention-meta">${esc(a.unit_code||'')} ${a.channel?'· '+esc(channelLabel(a.channel)):''} ${a.received_at?'· '+dateLabel(a.received_at):''}</div><div class="attention-text">${esc(text)}</div>${action}</div>`}).join(''):'<div class="ok-state">Nenhuma pendência operacional neste momento.</div>'}

const _campoRenderDecisionOverview=renderDecisionOverview;
renderDecisionOverview=function(){_campoRenderDecisionOverview();renderManagementAttention()};
'''.strip()


def enhance_dashboard_management_ui(html: str) -> str:
    html = html.replace("</style>", _MANAGEMENT_STYLES + "\n  </style>", 1)
    html = html.replace("</body>", f"<script>{_MANAGEMENT_JS}</script></body>", 1)
    return html
