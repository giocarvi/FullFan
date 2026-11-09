const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const url='http://127.0.0.1:5058';
const out=path.resolve(__dirname,'../outputs/revision_2026-11-09/despues');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const localChrome='C:/Program Files/Google/Chrome/Application/chrome.exe';
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE||(fs.existsSync(localChrome)?localChrome:undefined)});
 const results=[];
 for(const [role,width,height] of [['admin',1440,900],['atencion',390,844]]){
  const context=await browser.newContext({viewport:{width,height},timezoneId:'America/Guatemala',reducedMotion:'reduce'});
  await context.request.post(url+'/login',{form:{username:role==='admin'?'DEMO_ADMIN':'DEMO_ATENCION',password:'demo-local'}});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url+'/app');await page.waitForSelector('#vencer-list [data-user]');
  assert.equal(await page.locator('[data-view=migracion],#view-migracion').count(),0);
  assert.equal(await page.locator('a[href="/quiniela/admin"]').count(),0);
  assert.equal(await page.locator('#vencer-list [data-user]').count(),8);
  await page.screenshot({path:path.join(out,role+'_inicio.png')});
  const initialOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  assert.equal(initialOverflow,false,'No horizontal page overflow');
  await page.locator('.nav-btn[data-view=clientes]').click();await page.waitForSelector('#clientes-list [data-user]');
  assert.equal(await page.locator('#clientes-list [data-user]').count(),20);
  assert.equal(await page.locator('#load-more-btn').isVisible(),true);
  await page.locator('#load-more-btn').click();await page.waitForFunction(()=>document.querySelectorAll('#clientes-list [data-user]').length===40);
  await page.screenshot({path:path.join(out,role+'_clientes.png')});
  // Rapid searches must always render the latest value.
  await page.locator('#search-input').fill('DEMO_01');await page.waitForTimeout(360);await page.locator('#search-input').fill('DEMO_02');
  await page.waitForFunction(()=>document.querySelector('#clientes-list [data-user]')?.dataset.user==='DEMO_02');
  await page.evaluate(()=>openModal('DEMO_FAMILIAR'));await page.waitForSelector('#client-tab-payments');
  assert.equal(await page.locator('#client-tab-summary').getAttribute('aria-selected'),'true');
  await page.screenshot({path:path.join(out,role+'_ficha.png')});
  await page.locator('#client-tab-edit').click();
  assert.equal(await page.locator('#edit-service-devices').inputValue(),'6');
  await page.locator('#client-tab-payments').click();await page.waitForSelector('#client-panel-payments .ledger-table');
  assert.equal(await page.locator('#pago-monto').isVisible(),true);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.join(out,role+'_pago.png')});
  const before=await context.request.get(url+'/api/clientes/DEMO_FAMILIAR/pagos');const beforeCount=(await before.json()).total;
  await page.locator('#pago-monto').fill('90.50');
  await page.evaluate(()=>Promise.all([registrarPago('DEMO_FAMILIAR'),registrarPago('DEMO_FAMILIAR')]));
  const after=await context.request.get(url+'/api/clientes/DEMO_FAMILIAR/pagos');assert.equal((await after.json()).total,beforeCount+1);
  await page.evaluate(()=>openModal('DEMO_FAMILIAR'));await page.waitForSelector('#client-tab-payments');
  // Renewal button opens a visible operation view with the correct user.
  await page.locator('#client-tab-payments').click();
  await page.getByRole('button',{name:'Crear tarea de renovación',exact:false}).click();
  assert.equal(await page.locator('#view-activaciones').isVisible(),true);
  await page.waitForFunction(()=>document.querySelector('#act-username').value==='DEMO_FAMILIAR');
  assert.equal(await page.locator('#act-username').inputValue(),'DEMO_FAMILIAR');
  if(role==='admin'){
    // Never contact real XUI from UI tests; exercise the credential fallback and report with synthetic data.
    let xuiRequests=0;
    const reportRows=Array.from({length:61},(_,i)=>({key:'demo_'+i,
      fenix:[{username:i===0?'DEMO_FAMILIAR':'DEMO_XUI_'+i,name:i===0?'Familia de ejemplo':'Cliente de ejemplo '+i,service_username:'demo_'+i,expiry:'2026-12-01',devices:6,state:'activo',archived:false}],
      xui:[{id:String(i+1),username:'demo_'+i,owner:'giocarvi',expiry:'2026-11-20',devices:3,state:'activo',unlimited:false}],
      flags:i===0?['falta_tiempo_xui','dispositivos_distintos']:['dispositivos_distintos'],difference_days:-11}));
    await page.route('**/api/admin/xui-comparacion',async route=>{
      xuiRequests++;
      if(xuiRequests===1)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({code:'xui_credentials_required',error:'Conecta tu panel XUI para consultar el reporte.'})});
      assert.equal(route.request().method(),'POST');
      assert.equal(route.request().postDataJSON().password,'SYNTHETIC_PANEL_ONLY');
      assert.equal(route.request().postDataJSON().remember,true);
      return route.fulfill({contentType:'application/json',body:JSON.stringify({rows:reportRows,counts:{falta_tiempo_xui:1,dispositivos_distintos:61},total_groups:61,total_fenix:61,total_xui:61,owner:'giocarvi',generated_at:'2026-11-09T10:00:00-06:00',today:'2026-11-09'})});
    });
    await page.evaluate(()=>switchView('xui'));await page.locator('#xui-refresh').click();
    await page.locator('#xui-connect').waitFor({state:'visible'});
    await page.locator('#xui-password').fill('SYNTHETIC_PANEL_ONLY');
    await page.locator('#xui-connect button[type=submit]').click();await page.locator('#xui-list tbody tr').first().waitFor();
    assert.equal(await page.locator('#xui-list tbody tr').count(),50);
    assert.equal(await page.locator('#xui-password').inputValue(),'');
    await page.locator('#xui-next').click();assert.equal(await page.locator('#xui-list tbody tr').count(),11);
    await page.locator('#xui-category').selectOption('falta_tiempo_xui');assert.equal(await page.locator('#xui-list tbody tr').count(),1);
    await page.evaluate(()=>document.querySelectorAll('.success-toast').forEach(n=>n.remove()));
    await page.screenshot({path:path.join(out,'admin_xui_reporte.png')});
    const downloadPromise=page.waitForEvent('download');await page.locator('#xui-export').click();
    const download=await downloadPromise;assert.equal(download.suggestedFilename(),'fenix_vs_xui_giocarvi_2026-11-09.csv');
    await page.locator('#xui-category').selectOption('');await page.locator('#xui-search').fill('DEMO_FAMILIAR');
    assert.equal(await page.locator('#xui-list tbody tr').count(),1);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.locator('[data-xui-client="DEMO_FAMILIAR"]').click();await page.locator('#client-tab-summary').waitFor();await page.keyboard.press('Escape');
    assert.equal(xuiRequests,2);
    // Synthetic sources only; the cleanup routes below never reach a real provider.
    const maxRows=[
      {maxplayer:{id:'1',username:'DEMO_OLD',list_usernames:['DEMO_OLD'],state:'no_confirmado',online:null,last_connection:'Nunca'},fenix:[],flags:['sin_fenix','candidato_revision','nunca_conecto'],candidate:true,can_prepare_deletion:false,can_check_connection:true,deletion_block:'Conexión actual no confirmada'},
      {maxplayer:{id:'2',username:'DEMO_FAMILIAR',list_usernames:['DEMO_FAMILIAR'],state:'activo',online:false,last_connection:null},fenix:[{username:'DEMO_FAMILIAR',name:'Familia de ejemplo',expiry:'2026-12-01',state:'activo',days_expired:0,last_payment:'2026-11-09',recent_payment:true,pending_activation:false}],flags:['conservar_activo','pago_reciente'],candidate:false},
      {maxplayer:{id:'3',username:'DEMO_MANUAL',list_usernames:[],state:'no_confirmado',online:null,last_connection:null},fenix:[],flags:['sin_fenix','candidato_revision'],candidate:true,can_prepare_deletion:false,can_check_connection:true,deletion_block:'Conexión actual no confirmada'}
    ];
    let maxRequests=0,cleanupDeleted=false,presenceBlocked=true;const cleanupCalls=[],manualCalls=[];
    await page.route('**/api/admin/maxplayer-eliminaciones',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({csrf:'SYNTHETIC_CSRF',operations:cleanupDeleted?[{maxplayer_id:'1',username:'DEMO_OLD',actor:'DEMO_ADMIN',status:'deleted',reason:'No renovó el servicio',updated_at:'2026-11-09T10:00:00-06:00'}]:[]})}));
    await page.route('**/api/admin/maxplayer/1/**',route=>{
      cleanupCalls.push(route.request().url());assert.equal(route.request().method(),'POST');
      assert.equal(route.request().headers()['x-csrf-token'],'SYNTHETIC_CSRF');
      if(route.request().url().endsWith('/preparar-eliminacion')){
        assert.equal(route.request().postDataJSON().skip_connection_check,false);
        if(presenceBlocked)return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'Un dispositivo está conectado. No se eliminará.'})});
        return route.fulfill({contentType:'application/json',body:JSON.stringify({confirmation:'SYNTHETIC_CONFIRMATION',account:{...maxRows[0].maxplayer,online:false,presence_device_count:1},fenix:[],flags:['sin_fenix'],expires_in:180,checked_at:'2026-11-09T10:00:00-06:00',skip_connection_check:false})});
      }
      assert.ok(route.request().url().endsWith('/eliminar'));
      const body=route.request().postDataJSON();assert.equal(body.confirmation,'SYNTHETIC_CONFIRMATION');assert.equal(body.typed_username,'DEMO_OLD');assert.equal(body.acknowledged,true);assert.ok(body.reason);
      cleanupDeleted=true;return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,status:'deleted',message:'Cuenta eliminada de Max Player. Cliente y pagos Fénix conservados.'})});
    });
    await page.route('**/api/admin/maxplayer/3/**',route=>{
      manualCalls.push(route.request().url());assert.equal(route.request().method(),'POST');
      const body=route.request().postDataJSON();
      if(route.request().url().endsWith('/preparar-eliminacion')){
        assert.equal(body.skip_connection_check,true);
        return route.fulfill({contentType:'application/json',body:JSON.stringify({confirmation:'SYNTHETIC_MANUAL_CONFIRMATION',account:maxRows[2].maxplayer,fenix:[],flags:['sin_fenix'],expires_in:180,checked_at:'2026-11-09T10:00:00-06:00',skip_connection_check:true})});
      }
      assert.ok(route.request().url().endsWith('/eliminar'));assert.equal(body.connection_risk_acknowledged,true);assert.equal(body.typed_username,'DEMO_MANUAL');assert.equal(body.acknowledged,true);assert.ok(body.reason);
      return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,status:'deleted',message:'Eliminación manual simulada. Historial Fénix conservado.'})});
    });
    await page.route('**/api/admin/maxplayer-comparacion*',route=>{
      maxRequests++;assert.ok(['GET','POST'].includes(route.request().method()));
      return route.fulfill({contentType:'application/json',body:JSON.stringify({rows:maxRows,counts:{sin_fenix:2,candidato_revision:2,conservar_activo:1},total_maxplayer:3,total_fenix:48,grace_days:7,deletion_csrf:'SYNTHETIC_CSRF',source:route.request().method()==='POST'?'CSV de Max Player':'API Max Player',source_complete:route.request().method()!=='POST',exported_on:'2026-11-09',generated_at:'2026-11-09T10:00:00-06:00',today:'2026-11-09'})});
    });
    await page.evaluate(()=>switchView('maxplayer'));await page.locator('#max-refresh').click();await page.locator('#max-list tbody tr').first().waitFor();
    assert.equal(await page.locator('#max-list tbody tr').count(),2);
    assert.ok((await page.locator('#max-list').textContent()).includes('No confirmado'));
    await page.evaluate(()=>document.querySelectorAll('.success-toast').forEach(n=>n.remove()));
    await page.screenshot({path:path.join(out,'admin_maxplayer_reporte.png')});
    const maxDownloadPromise=page.waitForEvent('download');await page.locator('#max-export').click();
    assert.equal((await maxDownloadPromise).suggestedFilename(),'fenix_vs_maxplayer_2026-11-09.csv');
    assert.equal(await page.locator('[data-max-delete="1"]').isEnabled(),true);
    assert.ok((await page.locator('[data-max-delete="1"]').textContent()).includes('Comprobar conexión'));
    await page.locator('[data-max-delete="1"]').click();await page.getByRole('heading',{name:'Eliminación bloqueada',exact:true}).waitFor();
    assert.equal(cleanupCalls.length,1);assert.equal(await page.locator('#max-delete-submit').count(),0);
    await page.locator('#max-cleanup-dialog [data-cleanup-close]').click();presenceBlocked=false;
    await page.locator('[data-max-delete="1"]').click();await page.locator('#max-delete-submit').waitFor();
    assert.equal(cleanupCalls.length,2);assert.equal(await page.locator('#max-delete-submit').isDisabled(),true);
    await page.locator('#max-delete-typed').fill('wrong');await page.locator('#max-delete-ack').check();await page.locator('#max-delete-reason').selectOption({label:'No renovó el servicio'});
    assert.equal(await page.locator('#max-delete-submit').isDisabled(),true);
    await page.locator('#max-delete-typed').fill('DEMO_OLD');assert.equal(await page.locator('#max-delete-submit').isEnabled(),true);
    await page.screenshot({path:path.join(out,'admin_maxplayer_confirmacion.png')});
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.setViewportSize({width,height});
    await page.locator('#max-delete-form').evaluate(form=>{form.requestSubmit();form.requestSubmit();});
    await page.getByRole('heading',{name:'Eliminación confirmada',exact:true}).waitFor();
    assert.equal(cleanupCalls.length,3);await page.locator('#max-cleanup-dialog [data-cleanup-close]').click();
    await page.locator('#max-cleanup-history summary').click();await page.locator('#max-cleanup-history-list tbody tr').waitFor();
    assert.ok((await page.locator('#max-cleanup-history-list').textContent()).includes('Ausencia confirmada'));
    await page.locator('[data-max-skip="3"]').click();await page.locator('#max-delete-risk').waitFor();
    assert.equal(await page.locator('#max-delete-risk').isChecked(),false);
    await page.locator('#max-delete-typed').fill('DEMO_MANUAL');await page.locator('#max-delete-ack').check();await page.locator('#max-delete-reason').selectOption({label:'No renovó el servicio'});
    assert.equal(await page.locator('#max-delete-submit').isDisabled(),true);assert.equal(manualCalls.length,1);
    await page.locator('#max-delete-risk').check();assert.equal(await page.locator('#max-delete-submit').isEnabled(),true);
    assert.ok((await page.locator('#max-cleanup-dialog').textContent()).includes('podría interrumpir una sesión activa'));
    await page.screenshot({path:path.join(out,'admin_maxplayer_sin_verificar.png')});
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(out,'admin_maxplayer_sin_verificar_movil.png')});await page.setViewportSize({width,height});
    await page.locator('#max-delete-form').evaluate(form=>{form.requestSubmit();form.requestSubmit();});
    await page.getByRole('heading',{name:'Eliminación confirmada',exact:true}).waitFor();assert.equal(manualCalls.length,2);
    await page.locator('#max-cleanup-dialog [data-cleanup-close]').click();
    await page.locator('#max-category').selectOption('conservar_activo');assert.equal(await page.locator('#max-list tbody tr').count(),1);
    await page.locator('[data-max-client="DEMO_FAMILIAR"]').click();await page.locator('#client-tab-summary').waitFor();await page.keyboard.press('Escape');
    await page.locator('.max-upload summary').click();
    await page.locator('#max-csv').setInputFiles({name:'synthetic.csv',mimeType:'text/csv',buffer:Buffer.from('MaxPlayer ID,Username\n1,DEMO_OLD\n')});
    await page.locator('#max-exported-on').fill('2026-11-09');await page.locator('#max-upload-form button').click();
    await page.waitForFunction(()=>document.querySelector('#max-updated').textContent.startsWith('CSV'));
    await page.locator('#max-category').selectOption('candidato_revision');assert.equal(await page.locator('[data-max-delete="1"]').isDisabled(),true);
    assert.equal(await page.locator('[data-max-skip="3"]').isDisabled(),true);
    assert.equal(maxRequests,2);
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.setViewportSize({width,height});
    await page.locator('.nav-btn[data-view=pagos]').click();await page.waitForSelector('#payments-list .ledger-table');
    await page.screenshot({path:path.join(out,'admin_pagos.png')});
    await page.evaluate(()=>switchView('analytics'));await page.waitForSelector('#day-chart-inner .day-bar-col');
    await page.screenshot({path:path.join(out,'admin_reportes.png')});
    await page.locator('[data-report=clientes]').click();
    await page.locator('#chart-planes').waitFor({state:'visible'});
    assert.equal(await page.locator('#chart-planes').isVisible(),true);
    assert.ok(await page.locator('#chart-planes').evaluate(el=>el.getBoundingClientRect().height)<=280);
    await page.locator('[data-report=costos]').click();
    assert.equal(await page.locator('#op-tablas').isVisible(),true);
    await page.locator('[data-report=ingresos]').click();
    const initial=Number((await context.request.get(url+'/api/analytics').then(r=>r.json())).total_historico);
    await page.evaluate(()=>openModal('DEMO_FAMILIAR'));await page.waitForSelector('#client-tab-payments');await page.locator('#client-tab-payments').click();await page.locator('#pago-monto').fill('10.50');await page.evaluate(()=>registrarPago('DEMO_FAMILIAR'));
    await page.waitForFunction(value=>document.querySelector('#kpi-historico').textContent.includes(Math.round(value).toLocaleString()),initial+10.5);
  } else {
    assert.equal(await page.locator('[data-view=maxplayer],#view-maxplayer').count(),0);
    assert.equal((await context.request.get(url+'/api/admin/maxplayer-comparacion')).status(),403);
    assert.equal((await context.request.get(url+'/api/admin/maxplayer-eliminaciones')).status(),403);
    assert.equal(await page.locator('[data-view=xui],#view-xui').count(),0);
    assert.equal((await context.request.get(url+'/api/admin/xui-comparacion')).status(),403);
    assert.equal(await page.locator('.nav-btn[data-view=pagos]').count(),0);
    assert.equal((await context.request.get(url+'/api/pagos')).status(),403);
    await page.locator('.nav-more').click();assert.equal(await page.locator('#nav-overflow').isVisible(),true);
  }
  await page.evaluate(()=>openModal('DEMO_FAMILIAR'));await page.waitForSelector('#client-tab-payments');await page.keyboard.press('Escape');
  assert.equal(await page.locator('#modal-overlay').isVisible(),false);
  assert.deepEqual(errors,[]);
  results.push({role,viewport:{width,height},errors,checks:'pagination, latest search, devices, payment single-submit, history, renewal, layout, role permissions, keyboard'});
  await context.close();
 }
 await browser.close();fs.writeFileSync(path.join(out,'browser_results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exit(1);});
