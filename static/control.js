/* Presentation and workflow upgrades. Historical records remain on the server. */
(() => {
  const $ = id => document.getElementById(id);
  const money = value => 'Q' + Number(value || 0).toLocaleString('es-GT', {minimumFractionDigits:2, maximumFractionDigits:2});
  const safe = escHtml;
  async function jsonRequest(url, options) {
    const response = await fetch(url, options);
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('La sesión terminó. Vuelve a ingresar para continuar.');
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || 'No se pudo completar la operación.');
    return data;
  }
  function errorPanel(node, error, retry) {
    node.innerHTML = `<div class="error-panel" role="alert">${safe(error.message || error)}<button class="btn-secondary" type="button">Reintentar</button></div>`;
    node.querySelector('button').onclick = retry;
  }
  localDateStr = function() {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {timeZone:'America/Guatemala', year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(p=>[p.type,p.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  };
  clienteStatus = function(expiry) {
    if (!expiry) return {cls:'gray',label:'Sin fecha'};
    const days = Math.round((Date.parse(expiry.slice(0,10)+'T12:00:00Z')-Date.parse(localDateStr()+'T12:00:00Z'))/86400000);
    if (days<0) return {cls:'red',label:'Vencido'};
    if (days===0) return {cls:'yellow',label:'Vence hoy'};
    if (days<=30) return {cls:'yellow',label:days===1?'Mañana':`En ${days} días`};
    return {cls:'green',label:'Vigente'};
  };
  showToast = function(message) {
    const toast=document.createElement('div');
    const isError=/❌|error|no se pudo/i.test(message);
    toast.className='success-toast'+(isError?' error':'');
    toast.role=isError?'alert':'status';toast.textContent=message;document.body.append(toast);
    setTimeout(()=>toast.remove(),5000);
  };

  const headings={dashboard:['Inicio','Vencimientos y actividad de tu operación.'],clientes:['Clientes','Busca, consulta el historial y registra pagos.'],analytics:['Reportes','Ingresos, clientes y estimaciones de costos.'],smartone:['Smart One','Licencias y dispositivos asociados.'],resellers:['Revendedores','Seguimiento de tu red.'],config:['Configuración','Preferencias y herramientas de administración.']};
  Object.entries(headings).forEach(([key,[title,subtitle]])=>{
    const view=$('view-'+key); if(!view)return;
    const h=document.createElement('div');h.className='page-heading'+(key==='analytics'?' report-heading':'');
    h.innerHTML=`<div><h1>${title}</h1><p>${subtitle}</p></div>`;view.prepend(h);
  });
  const nav=document.querySelector('.bottom-nav');
  const cancelledTab=document.createElement('button');cancelledTab.className='ops-tab';cancelledTab.dataset.status='cancelled';cancelledTab.textContent='Canceladas';cancelledTab.onclick=()=>{currentActivationStatus='cancelled';setActivationTabActive();loadActivationTasks();};$('activation-tabs').append(cancelledTab);
  const overflow=document.createElement('div');overflow.className='nav-overflow';overflow.id='nav-overflow';
  nav.querySelectorAll('.nav-btn').forEach(b=>{if(b.dataset.view&&!['dashboard','clientes','pagos'].includes(b.dataset.view))overflow.append(b);});
  nav.append(overflow);
  const more=document.createElement('button');more.className='nav-btn nav-more';more.type='button';more.setAttribute('aria-expanded','false');more.setAttribute('aria-controls','nav-overflow');more.innerHTML='<span class="icon">☰</span>Más';nav.append(more);
  more.onclick=()=>{const open=overflow.classList.toggle('open');more.setAttribute('aria-expanded',String(open));};
  document.addEventListener('click',e=>{if(!nav.contains(e.target)){overflow.classList.remove('open');more.setAttribute('aria-expanded','false');}});
  const oldSwitch=switchView;
  switchView=function(view,estado) {
    if(!$('view-'+view))return;
    if(view==='clientes'&&estado!==undefined){currentArchivados='';currentFecha='';currentQ='';$('fecha-filter').value='';$('search-input').value='';}
    overflow.classList.remove('open');more.setAttribute('aria-expanded','false');
    oldSwitch(view,estado);
    if(view==='clientes')document.querySelectorAll('#archive-tabs .filter-tab').forEach(b=>b.classList.toggle('active',(b.dataset.archivados||'')===currentArchivados));
    if(view==='pagos')loadPayments();
    window.scrollTo({top:0,behavior:'instant'});
  };

  loadDashboard=async function() {
    try {
      const d=await jsonRequest('/api/dashboard');
      const cards={'stat-activos':money(d.ingresos_hoy),'stat-por-vencer':d.vencen_hoy,'stat-vencidos':d.vencen_semana,'stat-ingresos':money(d.ingresos_mes)};
      Object.entries(cards).forEach(([id,val])=>{if($(id))$(id).textContent=typeof val==='number'?val.toLocaleString():val;});
      const labels=['Cobrado hoy','Vencen hoy','Vencen en 7 días','Cobrado este mes'];
      $('stats-grid')?.querySelectorAll('.lbl').forEach((label,i)=>label.textContent=labels[i]);
      let overview=$('service-overview');if($('stats-grid')&&!overview){overview=document.createElement('div');overview.id='service-overview';overview.className='service-overview';$('stats-grid').after(overview);}
      if(overview){overview.innerHTML=`<button data-state="activo">${Number(d.activos)} servicios vigentes</button><button data-state="por_vencer">${Number(d.por_vencer)} vencen en 30 días</button><button data-state="vencido">${Number(d.vencidos)} vencidos / sin fecha</button>`;overview.querySelectorAll('button').forEach(b=>b.onclick=()=>switchView('clientes',b.dataset.state));}
      const months=d.ultimos_meses||[];const maximum=Math.max(...months.map(m=>Number(m.total)),1);
      if($('chart-bars'))$('chart-bars').innerHTML=months.map(m=>`<div class="bar-wrap"><div class="bar" style="height:${Math.max(4,Math.round(Number(m.total)/maximum*56))}px" title="${money(m.total)}"></div></div>`).join('');
      if($('chart-labels'))$('chart-labels').innerHTML=months.map(m=>`<div class="bar-info"><span class="bar-label">${safe(m.m)}</span><span class="bar-val">${money(m.total)}</span><span class="bar-units">${Number(m.unidades||0)} pagos</span></div>`).join('');
      $('vencer-list').innerHTML=(d.por_vencer_lista||[]).slice(0,8).map(c=>{
        const status=clienteStatus(c.vencimiento);
        return `<button type="button" class="client-table-row dashboard-client" data-user="${safe(c.username)}"><span><strong>${safe(c.nombre||c.username)}</strong><small class="sub">${safe(c.username)}</small></span><span>${safe(c.vencimiento||'Sin fecha')}</span><span class="badge ${status.cls}">${status.label}</span></button>`;
      }).join('')||'<div class="empty-state">No hay vencimientos en los próximos 30 días.</div>';
      $('vencer-list').querySelectorAll('[data-user]').forEach(b=>b.onclick=()=>openModal(b.dataset.user));
      $('stats-grid')?.querySelectorAll('.stat-card').forEach((card,i)=>{card.tabIndex=0;card.role='button';const run=()=>{if(i===0||i===3){$('payments-from').value=i===0?localDateStr():localDateStr().slice(0,7)+'-01';$('payments-to').value=localDateStr();paymentsPage=1;switchView('pagos');}else switchView('clientes',i===1?'hoy':'semana');};card.onclick=run;card.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();run();}};});
    } catch(e) {errorPanel($('vencer-list'),e,loadDashboard);}
  };
  const refresh=document.createElement('div');refresh.className='view-refresh';refresh.innerHTML='<span id="report-updated"></span><button type="button">Actualizar datos</button>';
  $('view-analytics')?.querySelector('.page-heading')?.append(refresh);
  refresh.querySelector('button').onclick=()=>{analyticsData=null;loadAnalytics();};
  let clientsController,clientsSequence=0,clientSort='vence_asc';
  const toolbar=document.createElement('div');toolbar.className='client-toolbar';toolbar.innerHTML='<span id="client-result-count" role="status"></span><label>Ordenar <select id="client-sort"><option value="vence_asc">Vencimiento próximo</option><option value="vence_desc">Vencimiento lejano</option><option value="nombre">Nombre</option></select></label>';
  $('clientes-list').before(toolbar);
  $('client-sort').onchange=e=>{clientSort=e.target.value;loadClientes(true);};
  const rowHtml=c=>{
    const status=c.archived_at?{cls:'gray',label:'Archivado'}:clienteStatus(c.vencimiento);
    return `<button class="client-table-row" type="button" data-user="${safe(c.username)}"><span><strong>${safe(c.nombre||c.username)}</strong><small class="sub">${safe(c.username)}${c.contacto?' · '+safe(c.contacto):''}</small></span><span><span class="badge ${status.cls}">${status.label}</span></span><span class="expiry-cell"><span class="cell-label">Vencimiento</span>${safe(c.vencimiento||'Sin fecha')}</span><span class="plan-cell">${Number(c.devices||3)} dispositivos</span><span class="last-payment-cell">${safe(c.ultimo_pago||'Sin pagos')}</span><span class="inline-action row-action">Ver ficha →</span></button>`;
  };
  loadClientes=async function(reset=false) {
    const sequence=++clientsSequence;clientsController?.abort();clientsController=new AbortController();
    if(reset){currentPage=1;$('clientes-list').innerHTML='<div class="loading">Cargando clientes…</div>';}
    const page=currentPage;$('load-more-btn').disabled=true;loadingClientes=true;
    try {
      const query=new URLSearchParams({q:currentQ,estado:currentEstado,fecha:currentFecha,archivados:currentArchivados,page:String(page),sort:clientSort});
      const d=await jsonRequest('/api/clientes?'+query,{signal:clientsController.signal});if(sequence!==clientsSequence)return;
      totalClientes=d.total;
      if(reset)$('clientes-list').innerHTML='<div class="clients-head"><span>Cliente / usuario</span><span>Servicio</span><span>Vencimiento</span><span>Plan</span><span>Último pago</span><span class="row-action"></span></div>';
      $('clientes-list').insertAdjacentHTML('beforeend',d.clientes.map(rowHtml).join(''));
      if(!d.clientes.length&&reset)$('clientes-list').innerHTML='<div class="empty-state">No hay clientes con estos filtros.</div>';
      $('clientes-list').querySelectorAll('[data-user]').forEach(row=>row.onclick=()=>openModal(row.dataset.user));
      const shown=$('clientes-list').querySelectorAll('[data-user]').length;
      $('client-result-count').textContent=`${shown} de ${Number(d.total).toLocaleString()} resultados`;
      $('load-more-wrap').style.display=shown<d.total?'block':'none';
    } catch(e) {if(e.name!=='AbortError'&&sequence===clientsSequence){if(reset)errorPanel($('clientes-list'),e,()=>{currentPage=page;loadClientes(true);});else {currentPage=page-1;const retry=document.createElement('div');$('clientes-list').append(retry);errorPanel(retry,e,()=>{retry.remove();currentPage=page;loadClientes(false);});}}}
    finally {if(sequence===clientsSequence){loadingClientes=false;$('load-more-btn').disabled=false;}}
  };

  function paymentTable(rows,withClient=true) {
    if(!rows.length)return '<div class="empty-state">No hay pagos para mostrar.</div>';
    return `<table class="ledger-table"><thead><tr><th>${withClient?'Cliente':'Fecha del pago'}</th>${withClient?'<th>Fecha</th>':''}<th>Monto</th><th>Estado</th><th>Registró / comprobante</th></tr></thead><tbody>${rows.map(p=>`<tr class="${p.is_void?'void-row':''}"><td data-label="${withClient?'Cliente':'Fecha'}">${withClient?`<button class="text-action" data-payment-user="${safe(p.username)}">${safe(p.nombre||p.username)}</button><small>${safe(p.username)}</small>`:safe(p.mes)}<small>Registro #${Number(p.id)}</small></td>${withClient?`<td data-label="Fecha">${safe(p.mes)}<small>Registro: ${safe(String(p.fecha_registro||'').slice(0,16))}</small></td>`:''}<td class="amount" data-label="Monto">${money(p.monto)}</td><td data-label="Estado">${p.is_void?'Anulado':'Válido'}${p.is_void?`<small>${safe(p.void_reason||'')}</small>`:''}</td><td data-label="Registró / comprobante">${safe(p.created_by||'Sin usuario registrado')}${p.has_comprobante?`<br><button class="text-action" data-proof-id="${Number(p.id)}">Ver comprobante</button>`:''}</td></tr>`).join('')}</tbody></table>`;
  }
  function bindPaymentTable(node) {
    node.querySelectorAll('[data-payment-user]').forEach(b=>b.onclick=()=>openModal(b.dataset.paymentUser,'payments'));
    node.querySelectorAll('[data-proof-id]').forEach(b=>b.onclick=()=>openComprobante(Number(b.dataset.proofId)));
    if(IS_ADMIN)node.querySelectorAll('tbody tr').forEach(row=>{const id=Number(row.querySelector('td small')?.textContent.match(/#(\d+)/)?.[1]);if(id&&!row.classList.contains('void-row')){const b=document.createElement('button');b.type='button';b.className='text-action';b.textContent='Anular pago';b.style.display='block';b.style.marginTop='8px';b.onclick=()=>eliminarPago(id,Number(row.querySelector('.amount').textContent.replace(/[^\d.]/g,'')),node.dataset.historyUser||row.querySelector('[data-payment-user]')?.dataset.paymentUser);row.lastElementChild.append(b);}});
  }
  let paymentsPage=1,paymentsSequence=0;
  function ledgerQuery(){return new URLSearchParams({desde:$('payments-from').value,hasta:$('payments-to').value,q:$('payments-search').value,estado:$('payments-status').value,page:String(paymentsPage)});}
  async function loadPayments(){
    if(!$('payments-list'))return;const sequence=++paymentsSequence;
    if(!$('payments-from').value){$('payments-from').value=localDateStr().slice(0,7)+'-01';$('payments-to').value=localDateStr();}
    $('payments-list').innerHTML='<div class="loading">Consultando pagos…</div>';
    $('payments-prev').disabled=true;$('payments-next').disabled=true;
    try{const d=await jsonRequest('/api/pagos?'+ledgerQuery());if(sequence!==paymentsSequence)return;
      $('payments-list').innerHTML=paymentTable(d.pagos);bindPaymentTable($('payments-list'));
      $('payments-summary').innerHTML=`<div class="stat-card green"><div class="val">${money(d.cobrado)}</div><div class="lbl">Cobrado válido en el filtro</div></div><div class="stat-card"><div class="val">${Number(d.total)}</div><div class="lbl">Pagos encontrados</div></div><div class="stat-card"><div class="val">${Number(d.clientes)}</div><div class="lbl">Clientes en el filtro</div></div>`;
      const pages=Math.max(1,Math.ceil(d.total/d.per_page));$('payments-page').textContent=`Página ${d.page} de ${pages}`;$('payments-prev').disabled=paymentsPage<=1;$('payments-next').disabled=paymentsPage>=pages;
    }catch(e){if(sequence===paymentsSequence)errorPanel($('payments-list'),e,loadPayments);}
  }
  if($('payments-filters')){
    $('payments-filters').onsubmit=e=>{e.preventDefault();paymentsPage=1;loadPayments();};
    $('payments-prev').onclick=()=>{paymentsPage--;loadPayments();};$('payments-next').onclick=()=>{paymentsPage++;loadPayments();};
    $('payments-export').onclick=()=>{const q=ledgerQuery();q.set('export','csv');window.location.assign('/api/pagos?'+q);};
  }

  let modalSequence=0,returnFocus=null,activeTab='summary';
  const legacyOpen=openModal,legacyClose=closeModal;
  openModal=async function(username,preferredTab='summary') {
    const sequence=++modalSequence;returnFocus=document.activeElement;
    try {
      await legacyOpen(username);if(sequence!==modalSequence)return;
      const inner=$('modal-body-inner');if(!inner.querySelector('.modal-header'))return;
      inner.dataset.username=username;
      const header=inner.querySelector('.modal-header');const close=document.createElement('button');close.type='button';close.className='modal-close';close.textContent='×';close.setAttribute('aria-label','Cerrar ficha');close.onclick=closeModal;header.append(close);
      const summaryCards=inner.querySelectorAll('.client-summary-card');summaryCards[2].querySelector('.val').textContent=money(summaryCards[2].querySelector('.val').textContent.replace(/[^\d.]/g,''));summaryCards[3].querySelector('.lbl').textContent='Plan';const devices=Number($('edit-service-devices')?.value||3);summaryCards[3].querySelector('.val').textContent=`${devices===6?'Familiar · ':''}${devices} dispositivos`;
      const top=document.createElement('div');top.className='client-top';top.append(header,inner.querySelector('.client-summary-grid'));
      inner.querySelector('.client-quick-actions')?.remove();
      const tabs=document.createElement('div');tabs.className='client-tabs';tabs.role='tablist';tabs.setAttribute('aria-label','Secciones del cliente');
      const panels=document.createElement('div');panels.className='client-panels';
      const groups={summary:['Resumen',[]],payments:['Pagos',[]],services:['Servicios',[]],edit:['Editar',[]]};
      const body=inner.querySelector('.modal-body');body.querySelectorAll('.info-row').forEach((row,i)=>{if(i<3)row.remove();});
      groups.summary[1].push(body,$('client-associated-'+username),$('client-wa-'+username));
      groups.services[1].push($('client-portal-'+username),$('client-service-'+username),$('client-smartone-'+username));
      groups.edit[1].push($('client-edit-'+username));groups.payments[1].push($('pago-form-'+username));
      let historyLoaded=false;
      const history=document.createElement('div');history.innerHTML='<h3 class="history-heading">Historial completo de pagos</h3><div class="ledger-results"></div><div class="ledger-pagination"><button class="btn-secondary">Anterior</button><span role="status"></span><button class="btn-secondary">Siguiente</button></div>';history.querySelector('.ledger-results').dataset.historyUser=username;
      let historyPage=1;
      async function loadHistory(){const node=history.querySelector('.ledger-results');try{const d=await jsonRequest(`/api/clientes/${encodeURIComponent(username)}/pagos?page=${historyPage}`);if(sequence!==modalSequence)return;node.innerHTML=paymentTable(d.pagos,false);bindPaymentTable(node);history.querySelector('[role=status]').textContent=`${d.total} pagos · ${historyPage}/${Math.max(1,Math.ceil(d.total/d.per_page))}`;const buttons=history.querySelectorAll('.ledger-pagination button');buttons[0].disabled=historyPage<=1;buttons[1].disabled=historyPage*d.per_page>=d.total;}catch(e){errorPanel(node,e,loadHistory);}}
      const hb=history.querySelectorAll('.ledger-pagination button');hb[0].onclick=()=>{historyPage--;loadHistory();};hb[1].onclick=()=>{historyPage++;loadHistory();};groups.payments[1].push(history);
      Object.entries(groups).forEach(([id,[label,nodes]])=>{const panel=document.createElement('section');panel.id='client-panel-'+id;panel.className='client-tab-panel';panel.role='tabpanel';panel.setAttribute('aria-labelledby','client-tab-'+id);nodes.filter(Boolean).forEach(n=>panel.append(n));panels.append(panel);const b=document.createElement('button');b.id='client-tab-'+id;b.role='tab';b.type='button';b.textContent=label;b.setAttribute('aria-controls',panel.id);b.onclick=()=>selectTab(id);tabs.append(b);});
      inner.replaceChildren(top,tabs,panels);
      function selectTab(id){activeTab=id;tabs.querySelectorAll('button').forEach(b=>{const selected=b.id==='client-tab-'+id;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;});panels.querySelectorAll('.client-tab-panel').forEach(p=>p.hidden=p.id!=='client-panel-'+id);panels.scrollTop=0;if(id==='payments'&&!historyLoaded){historyLoaded=true;loadHistory();}}
      tabs.onkeydown=e=>{const buttons=[...tabs.querySelectorAll('button')];let i=buttons.indexOf(document.activeElement);if(['ArrowRight','ArrowLeft','Home','End'].includes(e.key)){e.preventDefault();i=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[i].click();buttons[i].focus();}};
      const pay=$('pago-form-'+username);pay.dataset.requestKey=crypto.randomUUID();
      const notice=document.createElement('p');notice.className='view-note';notice.textContent='Registra el cobro y el vencimiento de Fénix. La renovación en XUI se procesa por separado.';pay.querySelector('h3').after(notice);
      inner.querySelectorAll('label').forEach(label=>{if(!label.htmlFor){const input=label.parentElement.querySelector('input,select,textarea');if(input?.id)label.htmlFor=input.id;}});
      selectTab(preferredTab in groups?preferredTab:'summary');$('modal-content').focus();document.body.style.overflow='hidden';
    } catch(e){if(sequence===modalSequence)errorPanel($('modal-body-inner'),e,()=>openModal(username,preferredTab));}
  };
  closeModal=function(){modalSequence++;detailRequestVersion++;legacyClose();document.body.style.overflow='';returnFocus?.isConnected&&returnFocus.focus();};
  document.addEventListener('keydown',e=>{
    if(!$('modal-overlay').classList.contains('open'))return;
    if(e.key==='Escape'){if($('lightbox-overlay').classList.contains('open'))closeLightbox();else closeModal();}
    if($('lightbox-overlay').classList.contains('open'))return;
    if(e.key==='Tab'){const focusable=[...$('modal-content').querySelectorAll('button,a[href],input,select,textarea,[tabindex="0"]')].filter(el=>!el.disabled&&el.getClientRects().length);const first=focusable[0],last=focusable.at(-1);if(e.shiftKey&&(document.activeElement===first||document.activeElement===$('modal-content'))){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
  });
  registrarPago=async function(username) {
    const form=$('pago-form-'+username);if(!form||form.dataset.saving==='true')return;
    const amount=$('pago-monto'),date=$('pago-mes'),expiry=$('pago-vencimiento');
    if(!amount.reportValidity()||!date.reportValidity()||!expiry.reportValidity()||Number(amount.value)<=0){showToast('❌ Revisa el monto y las fechas.');return;}
    const button=$('register-payment-btn');const previousText=button.textContent;form.dataset.saving='true';button.disabled=true;button.textContent='Guardando…';
    try {
      let proof=null;const file=$('pago-comprobante').files?.[0];if(file)proof=await fileToBase64(file);
      const data=await jsonRequest('/api/pagos',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':form.dataset.requestKey},body:JSON.stringify({username,monto:amount.value,mes:date.value||localDateStr(),vencimiento:expiry.value,comprobante:proof})});
      analyticsData=null;closeModal();showToast(data.replayed?'✅ Este pago ya estaba registrado; se conservó una sola vez.':'✅ Pago registrado correctamente');loadDashboard();if($('view-clientes').classList.contains('active'))loadClientes(true);if($('view-pagos')?.classList.contains('active'))loadPayments();if($('view-analytics')?.classList.contains('active'))loadAnalytics();
    } catch(e){showToast('❌ '+e.message);}
    finally {form.dataset.saving='false';button.disabled=false;button.textContent=previousText;}
  };
  eliminarPago=async function(id,amount,username){if(!confirm(`¿Anular el pago #${id} de ${money(amount)}? El registro y su comprobante permanecerán en el historial.`))return;try{await jsonRequest(`/api/pagos/${id}`,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:'Anulado desde control de clientes'})});analyticsData=null;showToast('Pago anulado; el historial se conservó.');loadDashboard();if($('modal-overlay').classList.contains('open'))openModal(username,'payments');if($('view-pagos')?.classList.contains('active'))loadPayments();}catch(e){showToast('❌ '+e.message);}};
  const oldAnalytics=loadAnalytics;
  const reportView=$('view-analytics');
  if(reportView){
    const cards=[...reportView.children].filter(el=>el.classList.contains('analytics-chart-card'));
    [cards[0],cards[1],cards[6]].filter(Boolean).forEach(c=>c.classList.add('report-wide'));
    const navigation=document.createElement('div');navigation.className='report-navigation';
    navigation.innerHTML='<div class="report-tabs" role="tablist" aria-label="Tipo de reporte"><button role="tab" data-report="ingresos">Ingresos</button><button role="tab" data-report="clientes">Clientes</button><button role="tab" data-report="costos">Costos</button></div><p class="view-note" id="report-scope"></p>';
    $('analytics-kpis').after(navigation);
    const groups={ingresos:[1,2,3,6],clientes:[4,5],costos:[0]};
    const notes={ingresos:'Ingresos históricos por fecha guardada; el detalle diario corresponde al mes actual y anterior. Para consultar cualquier rango, utiliza Pagos.',clientes:'Altas: primer pago válido de cada usuario. Renovaciones: pagos posteriores. La distribución de planes se estima por importe.',costos:'Operación del mes actual y estimación histórica de créditos. La utilidad estimada no incluye todos los gastos del negocio.'};
    function selectReport(group){navigation.querySelectorAll('[data-report]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.report===group)));cards.forEach((c,i)=>c.hidden=!groups[group].includes(i));$('report-scope').textContent=notes[group];requestAnimationFrame(()=>reportView.querySelectorAll('canvas').forEach(c=>{if(c.getClientRects().length&&typeof Chart!=='undefined')Chart.getChart(c)?.resize();}));}
    navigation.querySelectorAll('[data-report]').forEach(b=>b.onclick=()=>selectReport(b.dataset.report));selectReport('ingresos');
  }
  document.querySelectorAll('#view-analytics canvas').forEach(canvas=>{const frame=document.createElement('div');frame.className='chart-frame';canvas.before(frame);frame.append(canvas);});
  renderTablaTrimestral=function(){const rows=analyticsData?.ventas_trimestrales||[];$('tabla-trimestral').innerHTML=`<table class="analytics-table"><thead><tr><th>Trimestre</th><th>Ingresos</th><th>Pagos</th><th>Clientes únicos</th></tr></thead><tbody>${rows.slice(-12).map(r=>`<tr><td>${safe(r.trimestre)}</td><td>${money(r.total)}</td><td>${Number(r.pagos)}</td><td>${Number(r.clientes)}</td></tr>`).join('')}</tbody></table>`;};
  loadAnalytics=async function(){try{await oldAnalytics();if($('report-updated'))$('report-updated').textContent='Actualizado '+new Date().toLocaleTimeString('es-GT',{hour:'2-digit',minute:'2-digit'});document.querySelectorAll('.analytics-chart-card canvas').forEach(c=>{const chart=Chart.getChart(c);if(chart){chart.options.maintainAspectRatio=false;chart.resize();}});}catch(e){showToast('❌ '+e.message);}};
  const noRenew=$('kpi-no-renov')?.nextElementSibling;if(noRenew)noRenew.textContent='Vencidos con pagos históricos';
  document.querySelector('#view-analytics .analytics-chart-card:nth-last-child(2) h3')?.append(' · estimado por monto');
  // Initial requests run only after role-aware functions and presentation are ready.
  loadDashboard();
})();
