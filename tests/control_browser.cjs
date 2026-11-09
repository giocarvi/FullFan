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
