"""All external deletions are mocked. No real Max Player account is touched."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import unittest
from unittest.mock import patch
import test_control as fixture
from maxplayer_report import normalize_customer
from scripts.snapshot_payment_history import capture,compare


class MaxCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.initialize()
    def setUp(self):
        fixture.seed();self.client=fixture.client()
        self.accounts=[normalize_customer({'id':101,'username':'MAX_UNUSED','is_online':False,'last_login':0})]
        self.complete=True;self.keep_after_delete=False;self.timeout_delete=False
        self.fetch=self.mock('fetch_max_report_customers',side_effect=self.fake_fetch)
        self.get=self.mock('get_maxplayer_users',side_effect=self.fake_get)
        self.delete=self.mock('delete_maxplayer_user',side_effect=self.fake_delete)
        sleeper=patch.object(fixture.module.time,'sleep',return_value=None);sleeper.start();self.addCleanup(sleeper.stop)
        self.csrf=self.client.get('/api/admin/maxplayer-eliminaciones').json['csrf']
        self.headers={'X-CSRF-Token':self.csrf}

    def mock(self,name,**kwargs):
        p=patch.object(fixture.module,name,**kwargs);result=p.start();self.addCleanup(p.stop);return result

    def fake_fetch(self,callback,**kwargs):
        rows=[dict(a) for a in self.accounts]
        if kwargs.get('page_observer'):kwargs['page_observer']({'limit':100},rows)
        return rows,self.complete

    def fake_get(self,params=None,**kwargs):
        rows=[]
        for a in self.accounts:
            row={'id':a['id'],'username':a['username'],'is_online':a['online'],'last_login':a['last_connection'],
                 'lists':[{'username':value} for value in a['list_usernames']]}
            if a['state']!='no_confirmado':row['enabled']=a['state']=='activo'
            rows.append(row)
        return {'payload':rows,'has_more':'false','next_cursor':None}

    def fake_delete(self,account_id):
        self.assertEqual(account_id,'101')
        if not self.keep_after_delete:self.accounts=[]
        if self.timeout_delete:raise fixture.module.MaxPlayerError('PROVIDER_SECRET',kind='timeout')
        return {'success':1}

    def prepare(self,**data):
        body={'username':'MAX_UNUSED','min_dias':7};body.update(data)
        return self.client.post('/api/admin/maxplayer/101/preparar-eliminacion',json=body,headers=self.headers)

    def confirm(self,plan,client=None,account_id=101,**data):
        body={'confirmation':plan['confirmation'],'typed_username':'MAX_UNUSED','acknowledged':True,'reason':'No renovó, revisado por administrador'}
        body.update(data)
        return (client or self.client).post(f'/api/admin/maxplayer/{account_id}/eliminar',json=body,headers=self.headers)

    def test_success_retains_all_clients_payments_credentials_and_original_audit_rows(self):
        db=fixture.module.get_db();before=capture(db);db.close()
        prepared=self.prepare();self.assertEqual(prepared.status_code,200)
        self.delete.assert_not_called()
        result=self.confirm(prepared.json)
        self.assertEqual(result.status_code,200);self.assertEqual(result.json['status'],'deleted')
        self.delete.assert_called_once_with('101')
        db=fixture.module.get_db();after=capture(db,baseline=before);db.close()
        changes=compare(before,after)
        for table,diff in changes.items():
            self.assertEqual(diff['faltantes'],0,table);self.assertEqual(diff['modificados'],0,table)
            if table not in ('audit_log','maxplayer_cleanup_operations'):self.assertEqual(diff['nuevos'],0,table)
        record=fixture.rows('SELECT * FROM maxplayer_cleanup_operations')[0]
        self.assertEqual(record['actor'],'DEMO_ADMIN');self.assertEqual(record['status'],'deleted')
        events=fixture.rows("SELECT action FROM audit_log WHERE entity_type='maxplayer'")
        self.assertIn('deletion_confirmed',[e['action'] for e in events])
        fixture.initialize()
        self.assertEqual(fixture.rows('SELECT status FROM maxplayer_cleanup_operations')[0]['status'],'deleted')

    def test_exact_confirmation_csrf_admin_and_actor_are_required(self):
        self.assertEqual(self.client.post('/api/admin/maxplayer/101/preparar-eliminacion',json={'username':'MAX_UNUSED'}).status_code,403)
        for role in ['atencion','reseller']:
            c=fixture.client(role)
            self.assertEqual(c.post('/api/admin/maxplayer/101/eliminar',json={},headers=self.headers).status_code,403)
            self.assertEqual(c.get('/api/admin/maxplayer-eliminaciones').status_code,403)
        plan=self.prepare().json
        for values in [{'typed_username':'another'},{'acknowledged':False},{'reason':''}]:
            self.assertEqual(self.confirm(plan,**values).status_code,400)
        self.assertEqual(self.confirm(plan,account_id=102).status_code,403)
        self.assertEqual(self.confirm(plan,confirmation=plan['confirmation']+'tampered').status_code,409)
        self.assertEqual(self.client.delete('/api/admin/maxplayer/101/eliminar').status_code,405)
        self.delete.assert_not_called()

    def test_current_database_role_and_origin_are_checked(self):
        bad=self.client.post('/api/admin/maxplayer/101/preparar-eliminacion',json={'username':'MAX_UNUSED'},headers={**self.headers,'Origin':'https://unrelated.example'})
        self.assertEqual(bad.status_code,403)
        db=fixture.module.get_db();db.execute("UPDATE usuarios SET rol='atencion' WHERE username='DEMO_ADMIN'");db.commit();db.close()
        self.assertEqual(self.prepare().status_code,403)
        self.fetch.assert_not_called();self.delete.assert_not_called()

    def test_changed_provider_key_and_unapproved_api_host_block_deletion(self):
        plan=self.prepare().json
        with patch.object(fixture.module,'MAXPLAYER_API_TOKEN','DIFFERENT_PROVIDER_KEY'):
            self.assertEqual(self.confirm(plan).status_code,409)
        with patch.object(fixture.module,'MAXPLAYER_API_BASE','https://another-provider.example/api'):
            self.assertEqual(self.prepare().status_code,503)
        self.delete.assert_not_called()

    def test_https_origin_is_valid_behind_tls_terminating_proxy(self):
        result=self.client.post('/api/admin/maxplayer/101/preparar-eliminacion',json={'username':'MAX_UNUSED'},headers={**self.headers,'Origin':'https://localhost'})
        self.assertEqual(result.status_code,200)
        self.delete.assert_not_called()

    def test_online_unknown_partial_duplicate_and_paid_clients_block(self):
        for online in (True,None):
            self.accounts[0]['online']=online
            self.assertEqual(self.prepare().status_code,409)
        self.accounts[0]['online']=False;self.complete=False
        self.assertEqual(self.prepare().status_code,409)
        self.complete=True;self.accounts.append({**self.accounts[0],'id':'102'})
        self.assertEqual(self.prepare().status_code,409)
        self.accounts=self.accounts[:1]
        db=fixture.module.get_db();db.execute("UPDATE client_service_credentials SET maxplayer_user_id='101' WHERE username='DEMO_FAMILIAR'");db.commit();db.close()
        response=self.prepare();self.assertEqual(response.status_code,409);self.assertIn('vigente',response.json['error'])
        self.delete.assert_not_called()

    def test_last_target_page_is_read_again_and_can_block_new_connection(self):
        normal_get=self.fake_get
        def connected(params=None,**kwargs):
            result=normal_get(params,**kwargs);result['payload'][0]['is_online']=True;return result
        self.get.side_effect=connected
        response=self.prepare();self.assertEqual(response.status_code,409);self.assertIn('conectada',response.json['error'])
        self.get.assert_called_once_with({'limit':100},include_pagination=True)
        self.delete.assert_not_called()

    def test_new_active_client_new_payment_pending_task_and_new_connection_block_after_preparation(self):
        plan=self.prepare().json
        db=fixture.module.get_db();db.execute("INSERT INTO clientes(username,nombre,vencimiento) VALUES('MAX_UNUSED','New client','2099-01-01')");db.commit();db.close()
        result=self.confirm(plan);self.assertEqual(result.status_code,409);self.delete.assert_not_called()
        # New independent fixture; the next tests show updated eligibility, not old report trust.
        fixture.seed();self.accounts[0]['online']=False
        db=fixture.module.get_db();db.execute("INSERT INTO clientes(username,nombre,vencimiento) VALUES('MAX_UNUSED','Old client','2026-01-01')");db.commit();db.close()
        plan=self.prepare().json
        db=fixture.module.get_db();db.execute("INSERT INTO pagos(username,mes,monto,fecha_registro) VALUES('MAX_UNUSED','2026-11-09',90,'2026-11-09T12:00:00')");db.commit();db.close()
        self.assertEqual(self.confirm(plan).status_code,409);self.delete.assert_not_called()
        fixture.seed();plan=self.prepare().json;self.accounts[0]['online']=True
        self.assertEqual(self.confirm(plan).status_code,409);self.delete.assert_not_called()

    def test_fingerprint_change_and_expired_confirmation_require_new_preparation(self):
        plan=self.prepare().json;self.accounts[0]['last_connection']='2026-01-01T10:00:00'
        self.assertEqual(self.confirm(plan).status_code,409)
        fixture.seed();plan=self.prepare().json
        with patch('maxplayer_cleanup_routes.TTL',-1):self.assertEqual(self.confirm(plan).status_code,409)
        self.delete.assert_not_called()

    def test_retry_never_sends_a_second_external_delete(self):
        plan=self.prepare().json;first=self.confirm(plan);calls=self.fetch.call_count
        second=self.confirm(plan)
        self.assertEqual(first.json['status'],'deleted');self.assertTrue(second.json['replayed'])
        self.assertEqual(self.fetch.call_count,calls);self.delete.assert_called_once()

    def test_two_simultaneous_confirmations_send_at_most_one_delete(self):
        plan=self.prepare().json
        def send(_):
            c=fixture.client()
            with c.session_transaction() as session:session['maxplayer_cleanup_csrf']=self.csrf
            return self.confirm(plan,client=c).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(send,range(2)))
        self.assertIn(200,statuses);self.assertTrue(all(s in (200,409) for s in statuses));self.delete.assert_called_once()

    def test_uncertain_timeout_is_not_retried_and_can_be_reconciled_readonly(self):
        plan=self.prepare().json;self.timeout_delete=True
        result=self.confirm(plan)
        self.assertEqual(result.status_code,502);self.assertEqual(result.json['status'],'uncertain')
        self.assertNotIn('PROVIDER_SECRET',json.dumps(result.json))
        self.assertEqual(self.confirm(plan).status_code,409)
        verified=self.client.post('/api/admin/maxplayer/101/verificar-eliminacion',json={},headers=self.headers)
        self.assertEqual(verified.json['status'],'deleted');self.delete.assert_called_once()
        self.assertNotIn('PROVIDER_SECRET',json.dumps(fixture.rows('SELECT * FROM audit_log')))

    def test_success_response_is_not_enough_until_absence_is_verified(self):
        plan=self.prepare().json;self.keep_after_delete=True
        result=self.confirm(plan)
        self.assertEqual(result.status_code,202);self.assertEqual(result.json['status'],'uncertain')
        self.assertEqual(self.prepare().status_code,409)
        verified=self.client.post('/api/admin/maxplayer/101/verificar-eliminacion',json={},headers=self.headers)
        self.assertEqual(verified.status_code,409);self.delete.assert_called_once()

    def test_rejected_request_is_not_replayed_but_allows_new_explicit_confirmation(self):
        plan=self.prepare().json
        self.delete.side_effect=fixture.module.MaxPlayerError('TOKEN_SECRET',kind='forbidden',http_status=403)
        result=self.confirm(plan)
        self.assertEqual(result.json['status'],'rejected');self.assertNotIn('TOKEN_SECRET',json.dumps(result.json))
        self.assertEqual(self.confirm(plan).status_code,409);self.assertEqual(self.delete.call_count,1)
        newer=self.prepare();self.assertEqual(newer.status_code,200)
        self.delete.side_effect=self.fake_delete
        self.assertEqual(self.confirm(newer.json).json['status'],'deleted');self.assertEqual(self.delete.call_count,2)

    def test_minimum_margin_and_pending_activation_are_not_bypassed(self):
        db=fixture.module.get_db();db.execute("INSERT INTO clientes(username,nombre,vencimiento) VALUES('MAX_UNUSED','Recent expiry',?)",((fixture.module.today_gt()-fixture.module.timedelta(days=2)).isoformat(),));db.commit();db.close()
        self.assertEqual(self.prepare(min_dias=0).status_code,409)
        db=fixture.module.get_db();db.execute("UPDATE clientes SET vencimiento='2026-01-01' WHERE username='MAX_UNUSED'");db.execute("INSERT INTO activation_tasks(username,task_type,status) VALUES('MAX_UNUSED','renewal','open')");db.commit();db.close()
        self.assertEqual(self.prepare().status_code,409);self.delete.assert_not_called()

    def test_archived_but_unexpired_or_undated_client_is_reserved(self):
        db=fixture.module.get_db();db.execute("INSERT INTO clientes(username,nombre,vencimiento,archived_at) VALUES('MAX_UNUSED','Archived but paid','2099-01-01','2026-01-01')");db.commit();db.close()
        self.assertEqual(self.prepare().status_code,409)
        db=fixture.module.get_db();db.execute("UPDATE clientes SET vencimiento=NULL WHERE username='MAX_UNUSED'");db.commit();db.close()
        self.assertEqual(self.prepare().status_code,409);self.delete.assert_not_called()

    def test_larger_selected_margin_also_protects_archived_clients(self):
        db=fixture.module.get_db();db.execute("INSERT INTO clientes(username,nombre,vencimiento,archived_at) VALUES('MAX_UNUSED','Archived client',?,'2026-01-01')",((fixture.module.today_gt()-fixture.module.timedelta(days=45)).isoformat(),));db.commit();db.close()
        self.assertEqual(self.prepare(min_dias=90).status_code,409)
        self.assertEqual(self.prepare(min_dias=7).status_code,200)
        self.delete.assert_not_called()

    def test_another_admin_cannot_use_the_confirmation(self):
        plan=self.prepare().json
        db=fixture.module.get_db();db.execute("INSERT INTO usuarios(username,password,rol) VALUES('SECOND_ADMIN','synthetic','admin')");db.commit();db.close()
        other=fixture.client()
        with other.session_transaction() as session:
            session['user']='SECOND_ADMIN';session['maxplayer_cleanup_csrf']=self.csrf
        self.assertEqual(self.confirm(plan,client=other).status_code,403)
        self.delete.assert_not_called()

    def test_verification_failure_after_delete_is_uncertain_not_rejected(self):
        plan=self.prepare().json
        def deleted_then_read_failure(account_id):
            self.fake_delete(account_id)
            self.fetch.side_effect=fixture.module.MaxPlayerError('SECRET',kind='forbidden',http_status=403)
        self.delete.side_effect=deleted_then_read_failure
        result=self.confirm(plan)
        self.assertEqual(result.json['status'],'uncertain')
        self.assertEqual(self.confirm(plan).status_code,409)
        self.delete.assert_called_once()

    def test_inactive_max_account_can_free_a_slot_but_never_a_paid_fenix_client(self):
        self.accounts[0]['state']='inactivo'
        response=self.prepare();self.assertEqual(response.status_code,200)
        self.assertEqual(self.confirm(response.json).json['status'],'deleted')

    def test_csv_never_enables_deletion_and_history_is_admin_only(self):
        result=self.client.post('/api/admin/maxplayer-comparacion',data={'file':(io.BytesIO(b'MaxPlayer ID,Username\n101,MAX_UNUSED\n'),'test.csv'),'exported_on':'2026-11-09'})
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json['rows'][0]['can_prepare_deletion'])
        self.delete.assert_not_called()


if __name__=='__main__':unittest.main()
