"""Postgres checks run only on the disposable CI database, never production."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import urlparse

CI_URL=os.environ.get('FENIX_PG_TEST_URL','')


@unittest.skipUnless(CI_URL,'No disposable Postgres test database configured')
class PostgresControlTests(unittest.TestCase):
    def test_history_upgrade_and_payment_retries_on_postgres(self):
        parsed=urlparse(CI_URL)
        self.assertIn(parsed.hostname,('localhost','127.0.0.1'))
        self.assertEqual(parsed.path,'/fenix_ci')
        script=r'''
import os
os.environ['SECRET_KEY']='disposable-postgres-fixture-only'
os.environ['DATABASE_URL']=os.environ['FENIX_PG_TEST_URL']
import app
from unittest.mock import patch
from datetime import date
with patch.object(app,'_migrate_from_excel'):
    app.init_db()
db=app.get_db();c=db.cursor()
c.execute("INSERT INTO clientes(username,nombre,vencimiento,total_pagado) VALUES('PG_DEMO','Ejemplo Postgres','2026-12-01',90)")
c.execute("INSERT INTO client_service_credentials(username,devices) VALUES('PG_DEMO',6)")
c.execute("INSERT INTO pagos(username,mes,monto,comprobante) VALUES('PG_DEMO','2026-10-01',90,'TEST_RECEIPT') RETURNING id")
old_id=c.fetchone()[0]
db.commit()
c.execute('SELECT * FROM pagos WHERE id=%s',(old_id,));historical=c.fetchone()
db.commit()
with patch.object(app,'_migrate_from_excel'):
    app.init_db()
c.execute('SELECT * FROM pagos WHERE id=%s',(old_id,));assert c.fetchone()==historical
client=app.app.test_client()
with client.session_transaction() as s:s['user']='PG_TEST';s['rol']='admin'
data={'username':'PG_DEMO','monto':'90.50','mes':'2026-11-09','vencimiento':'2026-12-09'}
headers={'Idempotency-Key':'pg_request_123456789'}
a=client.post('/api/pagos',json=data,headers=headers)
b=client.post('/api/pagos',json=data,headers=headers)
assert a.status_code==200,a.get_data(as_text=True)
assert b.status_code==200,b.get_data(as_text=True)
assert a.json['payment_id']==b.json['payment_id']
assert b.json['replayed'] is True
c.execute("SELECT COUNT(*),SUM(monto) FROM pagos WHERE username='PG_DEMO'");n,total=c.fetchone()
assert n==2 and abs(total-180.5)<0.01
response=client.put('/api/clientes/PG_DEMO',json={'nombre':'Nombre editado','vencimiento':'2026-12-09'})
assert response.status_code==200,response.get_data(as_text=True)
assert client.get('/api/clientes/PG_DEMO').json['service']['devices']==6
with patch.object(app,'today_gt',return_value=date(2026,11,29)):
    assert client.get('/api/dashboard').json['por_vencer']==1
    assert client.get('/api/clientes?estado=por_vencer').json['total']==1
ledger=client.get('/api/pagos?desde=2026-10-01&hasta=2026-12-31')
assert ledger.status_code==200,ledger.get_data(as_text=True)
assert ledger.json['total']==2
analytics=client.get('/api/analytics')
assert analytics.status_code==200,analytics.get_data(as_text=True)
assert analytics.json['ventas_trimestrales'][0]['clientes']==1
c.execute('SELECT * FROM pagos WHERE id=%s',(old_id,));assert c.fetchone()==historical
db.commit()
with patch.object(app,'fetch_xui_report_lines',return_value=[]):
    saved=client.post('/api/admin/xui-comparacion',json={'username':'PG_PANEL_DEMO','password':'PG_SECRET_DEMO','remember':True})
    assert saved.status_code==200,saved.get_data(as_text=True)
    assert saved.json['credential_saved'] is True
    assert client.get('/api/admin/xui-comparacion').status_code==200
assert not any(k.startswith('integration_credentials.') for k in client.get('/api/config').json)
c.execute("SELECT valor FROM configuracion WHERE clave='integration_credentials.xui'")
assert 'PG_SECRET_DEMO' not in c.fetchone()[0]
with patch.object(app,'maxplayer_configured',return_value=True),patch.object(app,'maxplayer_request',return_value={'payload':[{'id':1,'username':'PG_DEMO'}],'has_more':'false','next_cursor':None}) as remote:
    report=client.get('/api/admin/maxplayer-comparacion')
    assert report.status_code==200,report.get_data(as_text=True)
    assert remote.call_args.args==('GET','/users?limit=100')
    assert remote.call_args.kwargs=={'include_pagination':True}
    assert report.json['source_complete'] is True
c.execute('SELECT * FROM pagos WHERE id=%s',(old_id,));assert c.fetchone()==historical
db.close()

# The only DELETE in this test is a mock; Postgres retains all client/payment data.
db=app.get_db();c=db.cursor()
c.execute("INSERT INTO usuarios(username,password,rol) VALUES('PG_TEST','synthetic','admin') ON CONFLICT(username) DO UPDATE SET rol='admin'")
db.commit();db.close()
from maxplayer_report import normalize_customer
accounts=[normalize_customer({'id':999,'username':'PG_UNUSED','is_online':False,'last_login':0})]
def fake_fetch(callback,**kwargs):
    if kwargs.get('page_observer'):kwargs['page_observer']({'limit':100},accounts)
    return list(accounts),True
def fake_page(*args,**kwargs):
    return {'payload':[{'id':999,'username':'PG_UNUSED','is_online':False,'last_login':0}] if accounts else [],'has_more':'false','next_cursor':None}
def fake_delete(user_id):
    assert user_id=='999'
    accounts.clear()
with patch.object(app,'fetch_max_report_customers',side_effect=fake_fetch),patch.object(app,'get_maxplayer_users',side_effect=fake_page),patch.object(app,'delete_maxplayer_user',side_effect=fake_delete) as deletion,patch.object(app.time,'sleep',return_value=None):
    csrf=client.get('/api/admin/maxplayer-eliminaciones').json['csrf'];headers={'X-CSRF-Token':csrf}
    prepare=client.post('/api/admin/maxplayer/999/preparar-eliminacion',json={'username':'PG_UNUSED'},headers=headers)
    assert prepare.status_code==200,prepare.get_data(as_text=True)
    body={'confirmation':prepare.json['confirmation'],'typed_username':'PG_UNUSED','reason':'No renovó, ejemplo','acknowledged':True}
    result=client.post('/api/admin/maxplayer/999/eliminar',json=body,headers=headers)
    assert result.status_code==200,result.get_data(as_text=True)
    assert result.json['status']=='deleted'
    assert client.post('/api/admin/maxplayer/999/eliminar',json=body,headers=headers).json['replayed'] is True
    deletion.assert_called_once_with('999')
db=app.get_db();c=db.cursor()
c.execute('SELECT * FROM pagos WHERE id=%s',(old_id,));assert c.fetchone()==historical
c.execute("SELECT status FROM maxplayer_cleanup_operations WHERE maxplayer_id='999'");assert c.fetchone()[0]=='deleted'
db.close()
print('Postgres history, devices, expiry, reports, ledger and idempotency verified')
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],
                              capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)


if __name__=='__main__':unittest.main()
