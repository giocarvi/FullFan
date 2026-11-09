/* Admin review only: this file has no customer DELETE, PUT or activation calls. */
(() => {
  const $=id=>document.getElementById(id),safe=escHtml;
  if(!$('view-maxplayer'))return;
  const labels={candidato_revision:'Candidatos para revisión',conservar_activo:'Conservar: vigente en Fénix',sin_fenix:'Sin coincidencia en Fénix',vencido_fenix:'Vencidos en Fénix',archivado_fenix:'Archivados en Fénix',duplicados:'Duplicados en Max Player',coincidencia_ambigua:'Coincidencia ambigua',sin_fecha:'Sin vencimiento Fénix',activacion_pendiente:'Activación pendiente',pago_reciente:'Pago reciente (7 días)',vencido_reciente:'Vencido dentro del margen',nunca_conecto:'Nunca conectó',ya_inactivo_max:'Ya inactivo en Max Player',estado_max_no_confirmado:'Estado Max no confirmado',conectado:'Conectado: reservar'};
  const states={activo:'Activo',inactivo:'Inactivo',no_confirmado:'No confirmado',archivado:'Archivado',sin_fecha:'Sin fecha',vencido:'Vencido'};
  let report=null,page=1,busy=false;
  $('max-exported-on').value=localDateStr();$('max-exported-on').max=localDateStr();
  Object.entries(labels).filter(([k])=>k!=='candidato_revision').forEach(([k,v])=>$('max-category').add(new Option(v,k)));
  function selected(){const q=$('max-search').value.trim().toLocaleLowerCase(),category=$('max-category').value;return report?report.rows.filter(r=>(!category||r.flags.includes(category))&&(!q||[r.maxplayer.username,...r.maxplayer.list_usernames,...r.fenix.flatMap(f=>[f.username,f.name])].some(v=>String(v).toLocaleLowerCase().includes(q)))):[];}
  function draw(){
    const rows=selected(),pages=Math.max(1,Math.ceil(rows.length/50));page=Math.min(page,pages);
    $('max-page').textContent=`${rows.length.toLocaleString()} cuentas · página ${page} de ${pages}`;$('max-prev').disabled=page<=1;$('max-next').disabled=page>=pages;$('max-export').disabled=!rows.length;
    $('max-list').innerHTML=rows.length?`<table class="ledger-table xui-table"><thead><tr><th>Max Player / listas</th><th>Estado y conexión Max</th><th>Coincidencia Fénix</th><th>Vencimiento Fénix</th><th>Último pago válido</th><th>Hallazgos</th></tr></thead><tbody>${rows.slice((page-1)*50,page*50).map(r=>`<tr>
      <td data-label="Max Player"><strong>${safe(r.maxplayer.username||'Sin usuario de cuenta')}</strong>${r.maxplayer.id?`<small><a href="https://my.maxplayer.tv/customer/${encodeURIComponent(r.maxplayer.id)}" target="_blank" rel="noopener noreferrer">Abrir cuenta #${safe(r.maxplayer.id)} ↗</a></small>`:''}<small>Lista: ${safe(r.maxplayer.list_usernames.join(', ')||'No informada')}</small></td>
      <td data-label="Estado Max">${safe(states[r.maxplayer.state]||'No confirmado')}<small>${r.maxplayer.online===true?'Conectado':r.maxplayer.online===false?'Desconectado':'Conexión actual no confirmada'}</small><small>Último acceso: ${safe(r.maxplayer.last_connection||'Sin dato')}</small></td>
      <td data-label="Fénix">${r.fenix.map(f=>`<div class="xui-account"><button class="text-action" type="button" data-max-client="${safe(f.username)}">${safe(f.name)}</button><small>${safe(f.username)} · ${safe(states[f.state]||f.state)}</small></div>`).join('')||'Sin coincidencia exacta'}</td>
      <td data-label="Vence Fénix">${r.fenix.map(f=>`<div>${safe(f.expiry||'Sin fecha')}${f.days_expired?`<small>${Number(f.days_expired)} días vencido</small>`:''}</div>`).join('')||'—'}</td>
      <td data-label="Último pago">${r.fenix.map(f=>`<div>${safe(f.last_payment||'Sin pagos')}${f.recent_payment?'<small>Registro de pago reciente</small>':''}${f.pending_activation?'<small>Activación pendiente</small>':''}</div>`).join('')||'—'}</td>
      <td data-label="Hallazgos"><div class="xui-flags">${r.flags.map(f=>`<span>${safe(labels[f]||f)}</span>`).join('')}</div></td></tr>`).join('')}</tbody></table>`:'<div class="empty-state">No hay cuentas con estos filtros. Puedes cambiar «Mostrar» para revisar las demás.</div>';
    $('max-list').querySelectorAll('[data-max-client]').forEach(b=>b.onclick=()=>openModal(b.dataset.maxClient));
  }
  function summary(){const cards=[['','Cuentas recibidas'],['candidato_revision','Candidatos para revisión'],['conservar_activo','Conservar: activos en Fénix'],['sin_fenix','Sin coincidencia en Fénix'],['vencido_fenix','Vencidos en Fénix'],['duplicados','Duplicados en Max Player']];$('max-summary').innerHTML=cards.map(([k,v])=>`<button class="xui-kpi" type="button" data-max-filter="${k}"><strong>${Number(k?report.counts[k]||0:report.total_maxplayer).toLocaleString()}</strong><span>${safe(v)}</span></button>`).join('');$('max-summary').querySelectorAll('button').forEach(b=>b.onclick=()=>{$('max-category').value=b.dataset.maxFilter;page=1;draw();});}
  async function consult(file){
    if(busy||!$('max-grace').reportValidity())return;busy=true;$('max-refresh').disabled=true;$('max-upload-form').querySelector('button').disabled=true;$('max-results').hidden=true;$('max-message').textContent='Consultando y comparando con Fénix actual. No se eliminarán cuentas…';
    try{
      let url='/api/admin/maxplayer-comparacion?min_dias='+encodeURIComponent($('max-grace').value),options={cache:'no-store'};
      if(file){const body=new FormData();body.append('file',file);body.append('exported_on',$('max-exported-on').value);body.append('min_dias',$('max-grace').value);options={method:'POST',body};}
      const response=await fetch(url,options);if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('La sesión terminó. Vuelve a ingresar en Fénix.');const data=await response.json();
      if(!response.ok){if(data.code?.startsWith('maxplayer_'))document.querySelector('.max-upload').open=true;throw new Error(data.error||'No se pudo comparar Max Player.');}
      report=data;page=1;$('max-results').hidden=false;
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
