"""Regression tests and a synthetic, local-only preview (never a production DB)."""
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='fenix-control-')
os.environ.update(SECRET_KEY='local-fixture-only-not-for-production', DATABASE_URL='',
                  SQLITE_DB_PATH=str(Path(TEMP.name)/'fixture.db'))
import app as module
module.app.config.update(TESTING=True)


def initialize():
    with patch.object(module, '_migrate_from_excel'):
        module.init_db()


def seed():
    db=module.get_db()
    db.execute("DELETE FROM configuracion WHERE clave LIKE 'integration_credentials.%'")
    for table in ['payment_submissions','pagos','activation_tasks','orders','client_service_credentials',
                  'client_portal_accounts','smartone_records','smartone_inventory','clientes','usuarios','audit_log']:
        db.execute('DELETE FROM '+table)
    db.executemany('INSERT INTO usuarios(username,password,rol) VALUES(?,?,?)',[
        ('DEMO_ADMIN',module.hash_password('demo-local'),'admin'),
        ('DEMO_ATENCION',module.hash_password('demo-local'),'atencion')])
    db.execute('''INSERT INTO clientes(username,nombre,vencimiento,total_pagado,notas)
                  VALUES('DEMO_FAMILIAR','Familia de ejemplo','2026-12-01',90,'Datos ficticios de revisión')''')
    db.execute('''INSERT INTO client_service_credentials(username,service_username,service_password,devices)
                  VALUES('DEMO_FAMILIAR','DEMO_FAMILIAR','EJEMPLO',6)''')
    db.execute("INSERT INTO pagos(id,username,mes,monto,comprobante,created_by) VALUES(100,'DEMO_FAMILIAR','2026-10-09',90,'data:image/png;base64,DEMO','DEMO_ADMIN')")
    db.execute("INSERT INTO pagos(id,username,mes,monto,is_void,void_reason) VALUES(101,'DEMO_FAMILIAR','2026-10-10',150,1,'Anulación histórica de ejemplo')")
    db.commit();db.close()


def client(role='admin'):
    c=module.app.test_client()
    with c.session_transaction() as s:
        s['user']='DEMO_ADMIN' if role=='admin' else 'DEMO_ATENCION'
        s['rol']=role
    return c


def rows(query, params=()):
    db=module.get_db()
    try:return [dict(r) for r in db.execute(query,params)]
    finally:db.close()


class ControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):initialize()
    def setUp(self):seed();self.client=client()
    def pay(self,key='request_1234567890',**overrides):
        data=dict(username='DEMO_FAMILIAR',monto='90.50',mes='2026-11-09',vencimiento='2026-12-09')
        data.update(overrides)
        return self.client.post('/api/pagos',json=data,headers={'Idempotency-Key':key})

    def test_schema_upgrade_preserves_history_exactly(self):
        tables=['clientes','pagos','client_service_credentials']
        before={t:rows('SELECT * FROM '+t) for t in tables}
        initialize()
        self.assertEqual(before,{t:rows('SELECT * FROM '+t) for t in tables})

    def test_readonly_history_verifier_detects_changes_and_allows_new_rows(self):
        from scripts.snapshot_payment_history import capture,compare
        db=module.get_db();before=capture(db)
        db.execute("INSERT INTO pagos(username,mes,monto) VALUES('DEMO_FAMILIAR','2026-11-09',10)")
        after=capture(db,baseline=before)
        diff=compare(before,after)
        self.assertEqual(diff['pagos']['faltantes'],0);self.assertEqual(diff['pagos']['modificados'],0);self.assertEqual(diff['pagos']['nuevos'],1)
        db.execute('UPDATE pagos SET monto=1 WHERE id=100')
        self.assertEqual(compare(before,capture(db,baseline=before))['pagos']['modificados'],1)
        db.rollback();db.close()

    def test_payment_retries_return_same_id_and_preserve_receipts(self):
        before=rows('SELECT * FROM pagos WHERE id IN (100,101)')
        a=self.pay();b=self.pay()
        self.assertEqual(a.status_code,200)
        self.assertEqual(a.json['payment_id'],b.json['payment_id'])
        self.assertTrue(b.json['replayed'])
        self.assertEqual(rows('SELECT COUNT(*) AS n FROM pagos')[0]['n'],3)
        self.assertEqual(rows("SELECT total_pagado FROM clientes WHERE username='DEMO_FAMILIAR'")[0]['total_pagado'],180.5)
        self.assertEqual(before,rows('SELECT * FROM pagos WHERE id IN (100,101)'))

    def test_idempotency_conflict_rejected(self):
        self.pay();response=self.pay(monto='100')
        self.assertEqual(response.status_code,409)

    def test_distinct_real_payments_same_amount_allowed(self):
        self.pay();self.pay(key='request_abcdefghij')
        self.assertEqual(len(rows('SELECT * FROM pagos')),4)

    def test_concurrent_retries_insert_once(self):
        payload=dict(username='DEMO_FAMILIAR',monto=90,mes='2026-11-09')
        def send(_):return client().post('/api/pagos',json=payload,headers={'Idempotency-Key':'concurrent_request_123'}).json
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(send,range(2)))
        self.assertEqual(responses[0]['payment_id'],responses[1]['payment_id'])
        self.assertEqual(len(rows('SELECT * FROM pagos')),3)

    def test_invalid_payment_does_not_change_history(self):
        before=rows('SELECT * FROM pagos')
        for invalid in [dict(monto='NaN'),dict(monto=-1),dict(monto='1.001'),dict(mes='2026-02-30')]:
            self.assertEqual(self.pay(**invalid).status_code,400)
        self.assertEqual(before,rows('SELECT * FROM pagos'))

    def test_missing_customer_does_not_claim_payment_key(self):
        self.assertEqual(self.pay(username='MISSING').status_code,404)
        self.assertEqual(rows('SELECT * FROM payment_submissions'),[])

    def test_expiry_crosses_month_and_month_end(self):
        for day in [date(2026,11,9),date(2026,11,29)]:
            with patch.object(module,'today_gt',return_value=day):
                self.assertEqual(self.client.get('/api/dashboard').json['por_vencer'],1)
                self.assertEqual(self.client.get('/api/clientes?estado=por_vencer').json['total'],1)

    def test_family_detail_and_edits_preserve_devices(self):
        self.assertEqual(self.client.get('/api/clientes/DEMO_FAMILIAR').json['service']['devices'],6)
        for endpoint,method,payload in [('/api/clientes/DEMO_FAMILIAR','put',{'nombre':'Nuevo nombre','vencimiento':'2026-12-02'}),('/api/clientes/DEMO_FAMILIAR/portal','post',{'service_username':'DEMO_FAMILIAR','enabled':True})]:
            self.assertEqual(getattr(self.client,method)(endpoint,json=payload).status_code,200)
            self.assertEqual(rows('SELECT devices FROM client_service_credentials')[0]['devices'],6)

    def test_full_history_pagination_preserves_voids(self):
        db=module.get_db()
        db.executemany("INSERT INTO pagos(username,mes,monto) VALUES('DEMO_FAMILIAR',?,90)",[('2026-09-01',)]*30);db.commit();db.close()
        a=self.client.get('/api/clientes/DEMO_FAMILIAR/pagos').json
        b=self.client.get('/api/clientes/DEMO_FAMILIAR/pagos?page=2').json
        self.assertEqual(a['total'],32);self.assertEqual(len(a['pagos'])+len(b['pagos']),32)
        self.assertIn(101,[p['id'] for p in a['pagos']+b['pagos']])

    def test_ledger_total_excludes_void_but_keeps_record(self):
        response=self.client.get('/api/pagos?desde=2026-10-01&hasta=2026-10-31&estado=todos').json
        self.assertEqual(response['total'],2);self.assertEqual(response['cobrado'],90)

    def test_staff_permissions(self):
        c=client('atencion')
        self.assertEqual(c.get('/api/pagos').status_code,403)
        self.assertEqual(c.get('/api/analytics').status_code,403)
        self.assertEqual(c.get('/api/clientes/DEMO_FAMILIAR/pagos').status_code,200)
        self.assertEqual(c.delete('/api/pagos/100').status_code,403)
        self.assertEqual(c.get('/app').status_code,200)

    def test_migration_section_removed_for_both_roles(self):
        before=rows('SELECT * FROM pagos')
        for role in ['admin','atencion']:
            html=client(role).get('/app').get_data(as_text=True)
            self.assertNotIn('id="view-migracion"',html)
            self.assertNotIn('data-view="migracion"',html)
        self.assertEqual(before,rows('SELECT * FROM pagos'))

    def test_quiniela_link_removed_from_control_for_both_roles(self):
        for role in ['admin','atencion']:
            html=client(role).get('/app').get_data(as_text=True)
            self.assertNotIn('href="/quiniela/admin"',html)

    def test_annulment_keeps_original_payment_and_receipt(self):
        self.assertEqual(self.client.delete('/api/pagos/100',json={'reason':'Prueba'}).status_code,200)
        p=rows('SELECT * FROM pagos WHERE id=100')[0]
        self.assertEqual(p['monto'],90);self.assertTrue(p['is_void']);self.assertEqual(p['comprobante'],'data:image/png;base64,DEMO')

    def test_reports_count_first_payment_once_and_distinct_quarter_clients(self):
        db=module.get_db()
        db.execute("INSERT INTO pagos(username,mes,monto) VALUES('DEMO_FAMILIAR','2026-10-09',90)")
        db.commit();db.close()
        d=self.client.get('/api/analytics').json
        self.assertEqual(next(r['nuevos'] for r in d['nuevos_por_mes'] if r['m']=='2026-10'),1)
        self.assertEqual(next(r['renovaciones'] for r in d['renovaciones_por_mes'] if r['m']=='2026-10'),1)
        self.assertEqual(d['ventas_trimestrales'][0]['clientes'],1)

    def test_csv_filters_escape_formula(self):
        db=module.get_db();db.execute("UPDATE clientes SET nombre='=SUM(1,2)' WHERE username='DEMO_FAMILIAR'");db.commit();db.close()
        r=self.client.get('/api/pagos?export=csv&desde=2026-10-09&hasta=2026-10-09')
        self.assertEqual(r.status_code,200);self.assertIn("'=SUM",r.get_data(as_text=True))
        self.assertEqual(self.client.get('/api/pagos?desde=2026-12-01&hasta=2026-10-01').status_code,400)

    def test_create_and_complete_family_renewal_without_external_requests(self):
        plan=rows("SELECT id FROM plans WHERE slug='familiar-1m'")[0]['id']
        r=self.client.post('/api/activation-tasks',json={'username':'DEMO_FAMILIAR','plan_id':plan,'type':'renewal','amount':0})
        self.assertEqual(r.status_code,200,r.get_data(as_text=True))
        task=rows('SELECT id FROM activation_tasks')[0]['id']
        result=self.client.put(f'/api/activation-tasks/{task}',json={'status':'done','xui_username':'DEMO_FAMILIAR','xui_expires_at':'2026-12-09','maxplayer_sync':False,'register_payment':False})
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertEqual(rows('SELECT devices FROM client_service_credentials')[0]['devices'],6)
        self.assertEqual(len(rows('SELECT * FROM pagos')),2)

    def test_cancelling_task_preserves_order_payment_and_receipt(self):
        plan=rows("SELECT id FROM plans WHERE slug='familiar-1m'")[0]['id']
        self.client.post('/api/activation-tasks',json={'username':'DEMO_FAMILIAR','plan_id':plan,'amount':90,'payment_proof':'data:image/png;base64,DEMO'})
        task=rows('SELECT id FROM activation_tasks')[0]['id']
        self.client.put(f'/api/activation-tasks/{task}',json={'status':'done','xui_username':'DEMO_FAMILIAR','xui_expires_at':'2026-12-09','maxplayer_sync':False,'register_payment':True})
        payment=rows('SELECT payment_id FROM orders')[0]['payment_id']
        self.assertEqual(self.client.delete(f'/api/activation-tasks/{task}').status_code,200)
        self.assertEqual(rows('SELECT status FROM activation_tasks')[0]['status'],'cancelled')
        self.assertEqual(rows('SELECT status FROM orders')[0]['status'],'cancelled')
        saved=rows('SELECT * FROM pagos WHERE id=?',(payment,))[0]
        self.assertTrue(saved['is_void']);self.assertEqual(saved['comprobante'],'data:image/png;base64,DEMO')


def preview():
    initialize();seed()
    today=module.today_gt()
    db=module.get_db()
    for i in range(1,48):
        username=f'DEMO_{i:02}'
        db.execute('INSERT INTO clientes(username,nombre,vencimiento,total_pagado,notas) VALUES(?,?,?,?,?)',
                   (username,f'Cliente de ejemplo {i}',(today+timedelta(days=i-8)).isoformat(),270,'Datos ficticios para probar las vistas.'))
        db.execute('INSERT INTO client_service_credentials(username,service_username,devices) VALUES(?,?,?)',(username,username,6 if i%4==0 else 3))
        for ago in range(3):
            day=today-timedelta(days=i+ago*20)
            db.execute('INSERT INTO pagos(username,mes,monto,created_by) VALUES(?,?,?,?)',(username,day.isoformat(),90.5,'DEMO_ATENCION'))
    db.commit();db.close()
    @module.app.route('/demo/<role>')
    def demo_role(role):
        if role not in ('admin','atencion'):
            return 'Perfil de ejemplo no encontrado',404
        module.session.clear()
        module.session['user']='DEMO_ADMIN' if role=='admin' else 'DEMO_ATENCION'
        module.session['rol']=role
        return module.redirect('/app')
    module.app.config['TESTING']=False
    print('LOCAL SYNTHETIC PREVIEW ONLY: http://127.0.0.1:5058',flush=True)
    module.app.run(host='127.0.0.1',port=5058,use_reloader=False)


if __name__=='__main__':
    if '--preview' in sys.argv:preview()
    else:unittest.main()
