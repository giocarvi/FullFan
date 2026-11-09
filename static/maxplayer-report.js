/* Admin report and individually confirmed cleanup; all decisions are checked again by the server. */
(() => {
  const $=id=>document.getElementById(id),safe=escHtml;
  if(!$('view-maxplayer'))return;
  const labels={candidato_revision:'Candidatos para revisión',conservar_activo:'Conservar: vigente en Fénix',sin_fenix:'Sin coincidencia en Fénix',vencido_fenix:'Vencidos en Fénix',archivado_fenix:'Archivados en Fénix',duplicados:'Duplicados en Max Player',coincidencia_ambigua:'Coincidencia ambigua',sin_fecha:'Sin vencimiento Fénix',activacion_pendiente:'Activación pendiente',pago_reciente:'Pago reciente (7 días)',vencido_reciente:'Vencido dentro del margen',nunca_conecto:'Nunca conectó',ya_inactivo_max:'Ya inactivo en Max Player',estado_max_no_confirmado:'Estado Max no confirmado',conectado:'Conectado: reservar'};
  const states={activo:'Activo',inactivo:'Inactivo',no_confirmado:'No confirmado',archivado:'Archivado',sin_fecha:'Sin fecha',vencido:'Vencido'};
  let report=null,page=1,busy=false,cleanupCsrf='',cleanupBusy=false,cleanupSequence=0,cleanupPlan=null;
  const dialog=document.createElement('dialog');dialog.id='max-cleanup-dialog';dialog.className='max-cleanup-dialog';dialog.setAttribute('aria-labelledby','max-cleanup-title');document.body.append(dialog);
  dialog.addEventListener('cancel',e=>{if(cleanupBusy)e.preventDefault();});
  dialog.addEventListener('close',()=>{cleanupSequence++;cleanupPlan=null;});
  const statusLabels={checking:'Revisando',sending:'Orden en proceso',verifying:'Verificando',deleted:'Ausencia confirmada',uncertain:'Resultado no confirmado',blocked:'Bloqueada',not_sent:'No enviada',rejected:'Rechazada por Max Player'};
  async function cleanupRequest(url,body){
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':cleanupCsrf},body:JSON.stringify(body)});
    if(!r.headers.get('content-type')?.includes('application/json'))throw new Error('La sesión terminó. Revisa el historial al volver a ingresar.');
    const data=await r.json();return {response:r,data};
  }
  function closeButton(){dialog.querySelector('[data-cleanup-close]').onclick=()=>{if(!cleanupBusy)dialog.close();};}
  async function prepareDeletion(account,skipConnectionCheck=false){
    if(busy||cleanupBusy||!cleanupCsrf)return;
    const sequence=++cleanupSequence;cleanupPlan=null;
    dialog.innerHTML=`<h2 id="max-cleanup-title">${skipConnectionCheck?'Eliminar sin verificar conexión':'Comprobar conexión y revisar'}</h2><p role="status">${skipConnectionCheck?'Revisando identidad y Fénix actual. No se consultará la conexión. Todavía no se está borrando nada…':'Consultando la identidad, la conexión de sus dispositivos y Fénix actual. No se está borrando nada…'}</p><button class="btn-secondary" type="button" data-cleanup-close>Cancelar</button>`;
    if(!dialog.open)dialog.showModal();closeButton();
    try{
      const {response,data}=await cleanupRequest(`/api/admin/maxplayer/${encodeURIComponent(account.id)}/preparar-eliminacion`,{username:account.username,min_dias:report.grace_days,skip_connection_check:skipConnectionCheck});
      if(sequence!==cleanupSequence||!dialog.open)return;
      if(!response.ok)throw new Error(data.error||'No se pudo verificar la cuenta.');
      if((data.skip_connection_check===true)!==skipConnectionCheck)throw new Error('El modo de revisión no coincide. Actualiza la página y prepara otra confirmación.');
      cleanupPlan=data;
      dialog.innerHTML=`<h2 id="max-cleanup-title">Eliminar solo de Max Player</h2><p><strong>${safe(data.account.username)}</strong> · ID <strong>${safe(data.account.id)}</strong></p><p class="max-delete-warning">Esta acción elimina la cuenta en Max Player y puede perder sus accesos y configuración allí. No elimina el cliente, sus pagos ni su historial en Fénix. No se puede deshacer desde este botón.</p><p class="view-note">La conexión fue informada como desconectada. Se volverá a comprobar todo al confirmar. Esta revisión vence en ${Math.round(data.expires_in/60)} minutos.</p><form id="max-delete-form"><div class="form-group"><label for="max-delete-reason">Motivo</label><select id="max-delete-reason" required><option value="">Selecciona un motivo</option><option>No renovó el servicio</option><option>Sin coincidencia en Fénix, revisado por administrador</option><option>Cliente archivado, revisado por administrador</option></select></div><div class="form-group"><label for="max-delete-typed">Escribe exactamente: ${safe(data.account.username)}</label><input id="max-delete-typed" autocomplete="off" required></div><label class="max-delete-ack"><input id="max-delete-ack" type="checkbox" required> Confirmo que revisé este usuario e ID y quiero eliminar únicamente su cuenta de Max Player.</label><p id="max-delete-state" role="status" aria-live="polite"></p><div class="max-delete-actions"><button class="btn-secondary" type="button" data-cleanup-close>Cancelar</button><button id="max-delete-submit" class="max-delete-btn" type="submit" disabled>Eliminar definitivamente de Max Player</button></div></form>`;
      if(skipConnectionCheck){
        $('max-cleanup-title').textContent='Eliminar sin verificar conexión';
        dialog.querySelector('.view-note').textContent=`No se comprobará la conexión. Se volverán a revisar identidad y Fénix. Esta confirmación vence en ${Math.round(data.expires_in/60)} minutos.`;
        $('max-delete-form').insertAdjacentHTML('afterbegin','<p class="max-delete-warning"><strong>SIN VERIFICAR CONEXIÓN.</strong> No sabemos si está conectado. Esta eliminación podría interrumpir una sesión activa.</p>');
        dialog.querySelector('.max-delete-ack').insertAdjacentHTML('afterend','<label class="max-delete-ack max-delete-risk"><input id="max-delete-risk" type="checkbox" required> Acepto eliminar sin verificar la conexión, aunque pueda interrumpir una sesión activa.</label>');
        $('max-delete-submit').textContent='Eliminar sin verificar conexión';
      }
      closeButton();
      const typed=$('max-delete-typed'),ack=$('max-delete-ack'),risk=$('max-delete-risk'),reason=$('max-delete-reason'),button=$('max-delete-submit');
      const valid=()=>{button.disabled=typed.value!==data.account.username||!ack.checked||!reason.value||(skipConnectionCheck&&!risk?.checked)||cleanupBusy;};
      typed.oninput=valid;ack.onchange=valid;reason.onchange=valid;typed.focus();
      if(risk)risk.onchange=valid;
      $('max-delete-form').onsubmit=async e=>{
        e.preventDefault();if(button.disabled||cleanupBusy||!e.currentTarget.reportValidity())return;
        cleanupBusy=true;valid();dialog.querySelector('[data-cleanup-close]').disabled=true;
        $('max-delete-state').textContent='Revalidando antes de enviar una única orden y verificando el resultado. No cierres esta ventana ni repitas la acción…';
        try{
          const result=await cleanupRequest(`/api/admin/maxplayer/${encodeURIComponent(data.account.id)}/eliminar`,{confirmation:data.confirmation,typed_username:typed.value,reason:reason.value,acknowledged:ack.checked,connection_risk_acknowledged:skipConnectionCheck&&risk.checked});
          const state=result.data.status||'uncertain';
          if(state==='deleted'&&result.response.ok){
            report.rows=report.rows.filter(row=>row.maxplayer.id!==data.account.id);report.total_maxplayer=report.rows.length;report.counts={};report.rows.forEach(row=>row.flags.forEach(flag=>report.counts[flag]=(report.counts[flag]||0)+1));summary();draw();
          }else{const row=report.rows.find(row=>row.maxplayer.id===data.account.id);if(row){row.can_prepare_deletion=false;row.can_check_connection=false;row.cleanup_status=state;row.deletion_block='Revisa el historial antes de intentar otra eliminación.';}draw();}
          dialog.innerHTML=`<h2 id="max-cleanup-title">${state==='deleted'?'Eliminación confirmada':'Resultado de la revisión'}</h2><p role="status">${safe(result.data.message||result.data.error||'No se pudo confirmar el resultado. Revisa el historial antes de repetir.')}</p><button class="btn-secondary" type="button" data-cleanup-close>Cerrar</button>`;
          $('max-message').textContent=result.data.message||result.data.error||'Revisa el historial de eliminaciones.';
        }catch(error){dialog.innerHTML=`<h2 id="max-cleanup-title">Resultado no confirmado</h2><p role="alert">${safe(error.message)} No reenvíes el borrado; revisa el historial o utiliza Verificar estado.</p><button class="btn-secondary" type="button" data-cleanup-close>Cerrar</button>`;}
        finally{cleanupBusy=false;cleanupPlan=null;closeButton();loadCleanupHistory();}
      };
    }catch(error){if(sequence===cleanupSequence&&dialog.open){dialog.innerHTML=`<h2 id="max-cleanup-title">Eliminación bloqueada</h2><p role="alert">${safe(error.message)}</p><button class="btn-secondary" type="button" data-cleanup-close>Cerrar</button>`;closeButton();}}
  }
  async function loadCleanupHistory(){
    try{const r=await fetch('/api/admin/maxplayer-eliminaciones',{cache:'no-store'});if(!r.headers.get('content-type')?.includes('application/json'))throw new Error('Vuelve a iniciar sesión.');const data=await r.json();if(!r.ok)throw new Error(data.error||'No se pudo cargar el historial.');cleanupCsrf=data.csrf;
      $('max-cleanup-history-list').innerHTML=data.operations.length?`<table class="ledger-table"><thead><tr><th>Cuenta Max Player</th><th>Resultado</th><th>Administrador / motivo</th><th>Fecha / comprobación</th></tr></thead><tbody>${data.operations.map(op=>`<tr><td data-label="Cuenta">${safe(op.username)}<small>ID ${safe(op.maxplayer_id)}</small></td><td data-label="Resultado">${safe(statusLabels[op.status]||op.status)}</td><td data-label="Administrador / motivo">${safe(op.actor)}<small>${safe(op.reason)}</small></td><td data-label="Fecha">${safe(op.updated_at)}${op.status!=='deleted'?`<button class="text-action" type="button" data-max-verify="${safe(op.maxplayer_id)}">Verificar estado (sin borrar)</button>`:''}</td></tr>`).join('')}</tbody></table>`:'<p class="view-note">No hay eliminaciones solicitadas desde Fénix.</p>';
      $('max-cleanup-history-list').querySelectorAll('[data-max-verify]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const {data}=await cleanupRequest(`/api/admin/maxplayer/${encodeURIComponent(b.dataset.maxVerify)}/verificar-eliminacion`,{});$('max-message').textContent=data.message||data.error;await loadCleanupHistory();}catch(e){$('max-message').textContent=e.message;}finally{b.disabled=false;}});
    }catch(e){$('max-cleanup-history-list').textContent=e.message;}
  }
  $('max-cleanup-history').addEventListener('toggle',()=>{if($('max-cleanup-history').open)loadCleanupHistory();});$('max-cleanup-history-refresh').onclick=loadCleanupHistory;
  $('max-exported-on').value=localDateStr();$('max-exported-on').max=localDateStr();
  Object.entries(labels).filter(([k])=>k!=='candidato_revision').forEach(([k,v])=>$('max-category').add(new Option(v,k)));
  function selected(){const q=$('max-search').value.trim().toLocaleLowerCase(),category=$('max-category').value;return report?report.rows.filter(r=>(!category||r.flags.includes(category))&&(!q||[r.maxplayer.username,...r.maxplayer.list_usernames,...r.fenix.flatMap(f=>[f.username,f.name])].some(v=>String(v).toLocaleLowerCase().includes(q)))):[];}
  function draw(){
    const rows=selected(),pages=Math.max(1,Math.ceil(rows.length/50));page=Math.min(page,pages);
    $('max-page').textContent=`${rows.length.toLocaleString()} cuentas · página ${page} de ${pages}`;$('max-prev').disabled=page<=1;$('max-next').disabled=page>=pages;$('max-export').disabled=!rows.length;
    $('max-list').innerHTML=rows.length?`<table class="ledger-table xui-table"><thead><tr><th>Max Player / listas</th><th>Estado y conexión Max</th><th>Coincidencia Fénix</th><th>Vencimiento Fénix</th><th>Último pago válido</th><th>Hallazgos / acción</th></tr></thead><tbody>${rows.slice((page-1)*50,page*50).map(r=>`<tr>
      <td data-label="Max Player"><strong>${safe(r.maxplayer.username||'Sin usuario de cuenta')}</strong>${r.maxplayer.id?`<small><a href="https://my.maxplayer.tv/customer/${encodeURIComponent(r.maxplayer.id)}" target="_blank" rel="noopener noreferrer">Abrir cuenta #${safe(r.maxplayer.id)} ↗</a></small>`:''}<small>Lista: ${safe(r.maxplayer.list_usernames.join(', ')||'No informada')}</small></td>
      <td data-label="Estado Max">${safe(states[r.maxplayer.state]||'No confirmado')}<small>${r.maxplayer.online===true?'Conectado':r.maxplayer.online===false?'Desconectado':'Conexión actual no confirmada'}</small><small>Último acceso: ${safe(r.maxplayer.last_connection||'Sin dato')}</small></td>
      <td data-label="Fénix">${r.fenix.map(f=>`<div class="xui-account"><button class="text-action" type="button" data-max-client="${safe(f.username)}">${safe(f.name)}</button><small>${safe(f.username)} · ${safe(states[f.state]||f.state)}</small></div>`).join('')||'Sin coincidencia exacta'}</td>
      <td data-label="Vence Fénix">${r.fenix.map(f=>`<div>${safe(f.expiry||'Sin fecha')}${f.days_expired?`<small>${Number(f.days_expired)} días vencido</small>`:''}</div>`).join('')||'—'}</td>
      <td data-label="Último pago">${r.fenix.map(f=>`<div>${safe(f.last_payment||'Sin pagos')}${f.recent_payment?'<small>Registro de pago reciente</small>':''}${f.pending_activation?'<small>Activación pendiente</small>':''}</div>`).join('')||'—'}</td>
      <td data-label="Hallazgos / acción"><div class="xui-flags">${r.flags.map(f=>`<span>${safe(labels[f]||f)}</span>`).join('')}</div>${r.candidate?`<button class="max-delete-btn" type="button" data-max-delete="${safe(r.maxplayer.id||'')}" ${r.can_check_connection&&report.source_complete&&report.source==='API Max Player'?'':'disabled'}>Comprobar conexión y revisar</button><button class="max-delete-btn max-delete-skip" type="button" data-max-skip="${safe(r.maxplayer.id||'')}" ${r.can_check_connection&&report.source_complete&&report.source==='API Max Player'?'':'disabled'}>Eliminar sin verificar conexión</button><small>${safe(r.can_check_connection&&report.source_complete&&report.source==='API Max Player'?'Omitir conexión puede interrumpir una sesión activa. Ambas opciones requieren confirmación.':r.deletion_block||'Actualiza la consulta antes de revisar.')}</small>`:''}</td></tr>`).join('')}</tbody></table>`:'<div class="empty-state">No hay cuentas con estos filtros. Puedes cambiar «Mostrar» para revisar las demás.</div>';
    $('max-list').querySelectorAll('[data-max-client]').forEach(b=>b.onclick=()=>openModal(b.dataset.maxClient));
    $('max-list').querySelectorAll('[data-max-delete]').forEach(b=>b.onclick=()=>{const row=report.rows.find(r=>r.maxplayer.id===b.dataset.maxDelete);if(row)prepareDeletion(row.maxplayer);});
    $('max-list').querySelectorAll('[data-max-skip]').forEach(b=>b.onclick=()=>{const row=report.rows.find(r=>r.maxplayer.id===b.dataset.maxSkip);if(row)prepareDeletion(row.maxplayer,true);});
  }
  function summary(){const cards=[['','Cuentas recibidas'],['candidato_revision','Candidatos para revisión'],['conservar_activo','Conservar: activos en Fénix'],['sin_fenix','Sin coincidencia en Fénix'],['vencido_fenix','Vencidos en Fénix'],['duplicados','Duplicados en Max Player']];$('max-summary').innerHTML=cards.map(([k,v])=>`<button class="xui-kpi" type="button" data-max-filter="${k}"><strong>${Number(k?report.counts[k]||0:report.total_maxplayer).toLocaleString()}</strong><span>${safe(v)}</span></button>`).join('');$('max-summary').querySelectorAll('button').forEach(b=>b.onclick=()=>{$('max-category').value=b.dataset.maxFilter;page=1;draw();});}
  async function consult(file){
    if(busy||!$('max-grace').reportValidity())return;busy=true;$('max-refresh').disabled=true;$('max-upload-form').querySelector('button').disabled=true;$('max-results').hidden=true;$('max-message').textContent='Consultando y comparando con Fénix actual. No se eliminarán cuentas…';
    try{
      let url='/api/admin/maxplayer-comparacion?min_dias='+encodeURIComponent($('max-grace').value),options={cache:'no-store'};
      if(file){const body=new FormData();body.append('file',file);body.append('exported_on',$('max-exported-on').value);body.append('min_dias',$('max-grace').value);options={method:'POST',body};}
      const response=await fetch(url,options);if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('La sesión terminó. Vuelve a ingresar en Fénix.');const data=await response.json();
      if(!response.ok){if(data.code?.startsWith('maxplayer_'))document.querySelector('.max-upload').open=true;throw new Error(data.error||'No se pudo comparar Max Player.');}
      report=data;cleanupCsrf=data.deletion_csrf||cleanupCsrf;page=1;$('max-results').hidden=false;
      $('max-message').textContent='Reporte listo. No se eliminó, desactivó ni modificó ninguna cuenta.';
      $('max-updated').textContent=`${data.source}. Fecha de la fuente: ${data.exported_on}. Comparado con Fénix el ${new Date(data.generated_at).toLocaleString('es-GT',{timeZone:'America/Guatemala'})}. Margen: ${data.grace_days} días. ${data.source_complete?'Recorrido completo de la API confirmado.':'Se comparan solo las cuentas recibidas; no se confirma que sean toda la cartera.'}`;
      summary();draw();
    }catch(e){$('max-message').textContent=e.message||'No se pudo generar el reporte.';}
    finally{busy=false;$('max-refresh').disabled=false;$('max-upload-form').querySelector('button').disabled=false;$('max-csv').value='';}
  }
  $('max-refresh').onclick=()=>consult();$('max-upload-form').onsubmit=e=>{e.preventDefault();if(e.currentTarget.reportValidity())consult($('max-csv').files[0]);};$('max-filters').onsubmit=e=>e.preventDefault();
  $('max-search').oninput=()=>{page=1;draw();};$('max-category').onchange=()=>{page=1;draw();};$('max-prev').onclick=()=>{page--;draw();};$('max-next').onclick=()=>{page++;draw();};
  $('max-export').onclick=()=>{
    const cell=v=>'"'+String(v??'').replace(/^[\s]*[=+@-]/,m=>"'"+m).replaceAll('"','""')+'"';
    const records=[['Max Player ID','Usuario Max','Usuarios de listas','Estado Max','Conexión actual','Último acceso','Usuario Fénix','Estado Fénix','Vencimiento Fénix','Último pago válido','Hallazgos','Fuente','Fecha fuente','Fecha comparación']];
    selected().forEach(r=>records.push([r.maxplayer.id,r.maxplayer.username,r.maxplayer.list_usernames.join(' | '),states[r.maxplayer.state],r.maxplayer.online===true?'Conectado':r.maxplayer.online===false?'Desconectado':'No confirmado',r.maxplayer.last_connection,r.fenix.map(f=>f.username).join(' | '),r.fenix.map(f=>states[f.state]).join(' | '),r.fenix.map(f=>f.expiry).join(' | '),r.fenix.map(f=>f.last_payment).join(' | '),r.flags.map(f=>labels[f]||f).join(' | '),report.source,report.exported_on,report.generated_at]));
    const blob=new Blob(['\uFEFF'+records.map(row=>row.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`fenix_vs_maxplayer_${report.today}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
})();
