/* Admin-only read-only report. No credentials are saved in browser storage. */
(() => {
  const $=id=>document.getElementById(id), safe=escHtml;
  if(!$('view-xui'))return;
  const labels={fenix_activo_xui_no:'Fénix activo / XUI no activo',falta_tiempo_xui:'Falta tiempo en XUI',
    xui_activo_fenix_vencido:'XUI activo / Fénix vencido',fechas_distintas:'Fechas distintas',
    dispositivos_distintos:'Dispositivos distintos',solo_fenix:'Solo en Fénix',solo_xui:'Solo en XUI (giocarvi)',
    duplicados:'Duplicados / coincidencia ambigua',activos_ambos:'Activos en ambos',vencidos_ambos:'Vencidos en ambos',
    datos_incompletos:'Datos incompletos',archivados:'Archivados de Fénix',coinciden:'Sin diferencias detectadas',
    estados_distintos:'Estados distintos',sin_vencimiento_xui:'XUI sin vencimiento',
    vencido_fenix:'Vencidos en Fénix',vencido_xui:'Vencidos en XUI',tiempo_extra_xui:'Más tiempo en XUI que en Fénix'};
  const states={activo:'Activo',vencido:'Vencido',bloqueado:'Bloqueado',inactivo:'Inactivo',sin_fecha:'Sin fecha',desconocido:'No confirmado',archivado:'Archivado'};
  let report=null,page=1,busy=false;
  const pageSize=50;
  const selected=()=>report?report.rows.filter(r=>(!r.fenix.length||$('xui-archived').checked||r.fenix.some(f=>!f.archived))
    &&(!$('xui-category').value||r.flags.includes($('xui-category').value))
    &&(!search()||[...r.fenix.flatMap(f=>[f.username,f.name,f.service_username]),...r.xui.map(x=>x.username)].some(v=>String(v).toLocaleLowerCase().includes(search())))):[];
  const search=()=>$('xui-search').value.trim().toLocaleLowerCase();
  const badge=state=>`<span class="badge ${state==='activo'?'green':state==='vencido'||state==='bloqueado'?'red':'gray'}">${safe(states[state]||state)}</span>`;
  function draw(){
    if(!report)return;
    const rows=selected(),pages=Math.max(1,Math.ceil(rows.length/pageSize));page=Math.min(page,pages);
    $('xui-page').textContent=`${rows.length.toLocaleString()} grupos · página ${page} de ${pages}`;
    $('xui-prev').disabled=page<=1;$('xui-next').disabled=page>=pages;$('xui-export').disabled=!rows.length;
    $('xui-list').innerHTML=rows.length?`<table class="ledger-table xui-table"><thead><tr><th>Cliente / usuario Fénix</th><th>Usuario XUI</th><th>Vencimiento Fénix</th><th>Vencimiento XUI</th><th>Diferencia</th><th>Dispositivos Fénix / XUI</th><th>Hallazgos</th></tr></thead><tbody>${rows.slice((page-1)*pageSize,page*pageSize).map(r=>`<tr>
      <td data-label="Fénix">${r.fenix.map(f=>`<div class="xui-account"><button type="button" class="text-action" data-xui-client="${safe(f.username)}">${safe(f.name)}</button><small>${safe(f.username)}</small>${badge(f.state)}</div>`).join('')||'No encontrado'}</td>
      <td data-label="XUI">${r.xui.map(x=>`<div class="xui-account"><strong>${safe(x.username)}</strong><small>Línea #${safe(x.id)}</small>${badge(x.state)}</div>`).join('')||'No encontrado en giocarvi'}</td>
      <td data-label="Vence Fénix">${r.fenix.map(f=>`<div>${safe(f.expiry||'Sin fecha')}</div>`).join('')||'—'}</td>
      <td data-label="Vence XUI">${r.xui.map(x=>`<div>${safe(x.expiry||(x.unlimited?'Sin vencimiento':'Sin fecha'))}</div>`).join('')||'—'}</td>
      <td data-label="Diferencia">${r.difference_days===null?'No comparable':r.difference_days===0?'Misma fecha':`${r.difference_days>0?'+':''}${Number(r.difference_days)} días en XUI`}</td>
      <td data-label="Dispositivos">${r.fenix.map(f=>f.devices??'?').join(', ')||'—'} / ${r.xui.map(x=>x.devices??'?').join(', ')||'—'}</td>
      <td data-label="Hallazgos"><div class="xui-flags">${r.flags.map(f=>`<span>${safe(labels[f]||f)}</span>`).join('')}</div></td></tr>`).join('')}</tbody></table>`:'<div class="empty-state">No hay resultados con estos filtros.</div>';
    $('xui-list').querySelectorAll('[data-xui-client]').forEach(b=>b.onclick=()=>openModal(b.dataset.xuiClient));
  }
  function summarize(){
    const cards=[['','Todos los grupos'],['falta_tiempo_xui',labels.falta_tiempo_xui],['xui_activo_fenix_vencido',labels.xui_activo_fenix_vencido],['fenix_activo_xui_no',labels.fenix_activo_xui_no],['dispositivos_distintos',labels.dispositivos_distintos],['duplicados',labels.duplicados]];
    $('xui-summary').innerHTML=cards.map(([key,label])=>`<button type="button" class="xui-kpi" data-xui-filter="${key}"><strong>${Number(key?report.counts[key]||0:report.total_groups).toLocaleString()}</strong><span>${safe(label)}</span></button>`).join('');
    $('xui-summary').querySelectorAll('button').forEach(b=>b.onclick=()=>{$('xui-category').value=b.dataset.xuiFilter;page=1;draw();});
    $('xui-updated').textContent=`Consultado ${new Date(report.generated_at).toLocaleString('es-GT',{timeZone:'America/Guatemala'})} (Guatemala). Fénix: ${report.total_fenix.toLocaleString()} clientes, incluidos archivados. XUI: ${report.total_xui.toLocaleString()} líneas de giocarvi. Las tarjetas cuentan grupos e incluyen archivados; la tabla respeta tus filtros.`;
  }
  async function consult(credentials){
    if(busy)return;busy=true;
    $('xui-refresh').disabled=true;$('xui-connect').querySelector('button').disabled=true;
    $('xui-message').textContent='Consultando todas las páginas de XUI y comparando con Fénix. Puede tardar un momento…';
    // Never leave a previous successful snapshot visible as if a failed refresh were current.
    $('xui-results').hidden=true;
    try{
      const response=await fetch('/api/admin/xui-comparacion',credentials?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(credentials)}:{cache:'no-store'});
      if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('La sesión terminó. Vuelve a ingresar en Fénix.');
      const data=await response.json();
      if(!response.ok){
        if(data.code==='xui_credentials_required'||credentials)$('xui-connect').hidden=false;
        throw new Error(data.error||'No se pudo consultar XUI.');
      }
      report=data;page=1;$('xui-connect').hidden=true;$('xui-results').hidden=false;
      $('xui-message').textContent='Consulta completa. No se modificó ningún usuario ni pago.';
      summarize();draw();
    }catch(error){$('xui-message').textContent=error.message||'No se pudo consultar XUI.';}
    finally{busy=false;$('xui-password').value='';$('xui-refresh').disabled=false;$('xui-connect').querySelector('button').disabled=false;}
  }
  $('xui-refresh').onclick=()=>consult();
  $('xui-connect').onsubmit=e=>{e.preventDefault();if(e.currentTarget.reportValidity())consult({username:$('xui-username').value.trim(),password:$('xui-password').value});};
  Object.entries(labels).forEach(([value,label])=>{$('xui-category').add(new Option(label,value));});
  $('xui-filters').onsubmit=e=>e.preventDefault();
  ['xui-search','xui-category','xui-archived'].forEach(id=>$(id).addEventListener(id==='xui-search'?'input':'change',()=>{page=1;draw();}));
  $('xui-prev').onclick=()=>{page--;draw();};$('xui-next').onclick=()=>{page++;draw();};
  $('xui-export').onclick=()=>{
    const csvCell=v=>'"'+String(v??'').replace(/^[\s]*[=+@-]/,m=>"'"+m).replaceAll('"','""')+'"';
    const records=[['Usuario Fénix','Nombre Fénix','Estado Fénix','Vence Fénix','Dispositivos Fénix','Usuario XUI','Línea XUI','Estado XUI','Vence XUI','Dispositivos XUI','Diferencia días XUI','Hallazgos','Consulta Guatemala']];
    selected().forEach(r=>records.push([r.fenix.map(f=>f.username).join(' | '),r.fenix.map(f=>f.name).join(' | '),r.fenix.map(f=>states[f.state]).join(' | '),r.fenix.map(f=>f.expiry||'Sin fecha').join(' | '),r.fenix.map(f=>f.devices??'?').join(' | '),r.xui.map(x=>x.username).join(' | '),r.xui.map(x=>x.id).join(' | '),r.xui.map(x=>states[x.state]).join(' | '),r.xui.map(x=>x.expiry||(x.unlimited?'Sin vencimiento':'Sin fecha')).join(' | '),r.xui.map(x=>x.devices??'?').join(' | '),r.difference_days,r.flags.map(f=>labels[f]||f).join(' | '),report.generated_at]));
    const blob=new Blob(['\uFEFF'+records.map(r=>r.map(csvCell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'});
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`fenix_vs_xui_giocarvi_${report.today}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
})();
