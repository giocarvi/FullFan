from datetime import date
import io
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
import test_control as fixture
from maxplayer_report import MaxReportError, normalize_customer, parse_csv, fetch_customers, compare_accounts
from scripts.snapshot_payment_history import capture


TODAY=date(2026,11,9)


def account(username='DEMO',customer_id=1,**values):
    return normalize_customer(dict(id=customer_id,username=username,password='CLIENT_PASSWORD',**values))


def customer(username='DEMO',expiry='2026-10-01',**values):
    return dict(username=username,nombre='Synthetic client',vencimiento=expiry,**values)


class MaxReportTests(unittest.TestCase):
    def test_aliases_and_unknown_status_never_infer_active_or_never_connected(self):
        row=account(iptv_user='service',playlists=[{'username':'second','password':'SECRET'}])
        self.assertEqual(row['list_usernames'],['service','second']);self.assertEqual(row['state'],'no_confirmado')
        self.assertIsNone(row['last_connection']);self.assertNotIn('SECRET',json.dumps(row));self.assertNotIn('CLIENT_PASSWORD',json.dumps(row))
        self.assertEqual(account(last_login=0)['last_connection'],'Nunca')

    def test_active_any_alias_duplicate_or_online_is_reserved(self):
        clients=[customer(expiry='2026-12-01')]
        row=compare_accounts(clients,[account(last_login=0)],TODAY)['rows'][0]
        self.assertFalse(row['candidate']);self.assertIn('conservar_activo',row['flags'])
        clients=[customer(),customer('OTHER',expiry='2026-12-01')]
        row=compare_accounts(clients,[account(iptv_user='OTHER')],TODAY)['rows'][0]
        self.assertFalse(row['candidate']);self.assertIn('coincidencia_ambigua',row['flags'])
        row=compare_accounts([customer()],[account(is_online=True)],TODAY)['rows'][0]
        self.assertFalse(row['candidate']);self.assertIn('conectado',row['flags'])
        rows=compare_accounts([customer()],[account(),account(customer_id=2)],TODAY)['rows']
        self.assertTrue(all(not r['candidate'] and 'duplicados' in r['flags'] for r in rows))

    def test_expired_or_missing_candidates_but_recent_payments_and_tasks_are_reserved(self):
        for clients in [[],[customer()],[customer(archived_at='2026-10-01')]]:
            self.assertTrue(compare_accounts(clients,[account()],TODAY)['rows'][0]['candidate'])
        for client in [customer(expiry='2026-11-08'),customer(last_payment_recorded='2026-11-09T10:00:00'),customer(pending_activation=True),customer(expiry=None)]:
            self.assertFalse(compare_accounts([client],[account()],TODAY)['rows'][0]['candidate'])
        self.assertTrue(compare_accounts([customer()],[account(enabled=False)],TODAY)['rows'][0]['candidate'])
        self.assertTrue(compare_accounts([customer(expiry='2026-11-08')],[account()],TODAY,0)['rows'][0]['candidate'])

    def test_csv_no_secrets_and_no_guessing_name_matches(self):
        rows=parse_csv(b'MaxPlayer ID,Username,List Username,Password,Last Login\n1,PORTAL,SERVICE,SECRET,0\n')
        self.assertNotIn('SECRET',json.dumps(rows))
        client=customer('different',service_username='service',expiry='2026-12-01')
        row=compare_accounts([client],rows,TODAY)['rows'][0]
        self.assertFalse(row['candidate']);self.assertEqual(row['fenix'][0]['username'],'different')
        with self.assertRaises(MaxReportError):parse_csv(b'Random,File\nx,y\n')

    def test_api_pagination_and_unconfirmed_total(self):
        calls=[]
        def get(params):
            calls.append(params)
            if len(calls)==1:return {'payload':[{'id':1,'username':'DEMO_1'}],'has_more':'true','next_cursor':'1'}
            return {'payload':[{'id':2,'username':'DEMO_2'}],'has_more':'false','next_cursor':None}
        rows,complete=fetch_customers(get,pause=lambda delay:None)
        self.assertTrue(complete);self.assertEqual(len(rows),2)
        self.assertEqual(calls,[{'limit':100},{'limit':100,'after_id':'1'}])
        rows,complete=fetch_customers(lambda p:[{'id':1,'username':'ONLY_RETURNED_ACCOUNT'}])
        self.assertFalse(complete);self.assertEqual(len(rows),1)
        with self.assertRaises(MaxReportError):
            fetch_customers(lambda p:{'payload':[{'id':1,'username':'SAME'}],'has_more':'true','next_cursor':'1'},pause=lambda delay:None)

    def test_cursor_headers_are_required_to_claim_complete_and_bad_cursors_abort(self):
        for page in [
            {'payload':[{'id':1,'username':'DEMO'}],'has_more':'true','next_cursor':''},
            {'payload':[],'has_more':'true','next_cursor':'1'},
            {'payload':[{'id':1,'username':'DEMO'}],'has_more':'unexpected','next_cursor':'1'}
        ]:
            with self.subTest(page=page),self.assertRaises(MaxReportError):fetch_customers(lambda p:page)
        rows,complete=fetch_customers(lambda p:{'payload':[],'has_more':'false','next_cursor':None})
        self.assertEqual(rows,[]);self.assertTrue(complete)
        rows,complete=fetch_customers(lambda p:{'payload':[{'id':1,'username':'DEMO'}],'has_more':None,'next_cursor':None})
        self.assertEqual(len(rows),1);self.assertFalse(complete)

    def test_cursor_read_is_paced_and_never_follows_arbitrary_urls(self):
        pages=iter([
            {'payload':[{'id':1,'username':'DEMO_1'}],'has_more':'true','next_cursor':'opaque:next/value'},
            {'payload':[{'id':2,'username':'DEMO_2'}],'has_more':'false','next_cursor':None}])
        calls=[];pauses=[]
        def get(params):calls.append(params);return next(pages)
        rows,complete=fetch_customers(get,pause=pauses.append)
        self.assertTrue(complete);self.assertEqual(len(rows),2)
        self.assertEqual(calls[1],{'limit':100,'after_id':'opaque:next/value'})
        self.assertTrue(pauses);self.assertLessEqual(pauses[0],1.05)


class MaxReportRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.initialize()
    def setUp(self):fixture.seed();self.client=fixture.client()

    def test_permissions_and_hidden_menu(self):
        with patch.object(fixture.module,'maxplayer_request') as remote:
            for role in ['atencion','reseller']:
                for method in ['get','post']:
                    self.assertEqual(getattr(fixture.client(role),method)('/api/admin/maxplayer-comparacion').status_code,403)
            remote.assert_not_called()
        for role in ['admin','atencion']:
            page=fixture.client(role).get('/app').get_data(as_text=True)
            self.assertEqual('id="view-maxplayer"' in page,role=='admin')

    def test_api_uses_get_only_and_preserves_all_historical_hashes(self):
        db=fixture.module.get_db();before=capture(db);db.close()
        with patch.object(fixture.module,'maxplayer_configured',return_value=True),\
             patch.object(fixture.module,'maxplayer_request',return_value={'users':[{'id':1,'username':'DEMO_FAMILIAR'}],'total':1}) as remote:
            response=self.client.get('/api/admin/maxplayer-comparacion')
        self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(remote.call_args.args,('GET','/users?limit=100'))
        self.assertEqual(remote.call_args.kwargs,{'include_pagination':True})
        self.assertIn('conservar_activo',response.json['rows'][0]['flags'])
        db=fixture.module.get_db();after=capture(db,baseline=before);db.close()
        self.assertEqual(before['tables'],after['tables'])

    def test_documented_transport_captures_only_pagination_headers_and_read_needs_no_domain(self):
        response=MagicMock()
        response.read.return_value=b'[{"id":1,"username":"DEMO"}]'
        response.headers={'X-Has-More':'false','X-Next-Cursor':'1','Api-Token':'PROVIDER_SECRET','Set-Cookie':'COOKIE_SECRET'}
        context=MagicMock();context.__enter__.return_value=response
        with patch.object(fixture.module,'MAXPLAYER_API_TOKEN','SYNTHETIC_TOKEN'),patch.object(fixture.module,'MAXPLAYER_DOMAIN_ID',''),\
             patch.object(fixture.module.urlrequest,'urlopen',return_value=context) as network:
            self.assertTrue(fixture.module.maxplayer_configured(require_domain=False))
            self.assertFalse(fixture.module.maxplayer_configured())
            page=fixture.module.get_maxplayer_users({'limit':100},include_pagination=True)
            self.assertEqual(network.call_args.args[0].get_method(),'GET')
            self.assertTrue(network.call_args.args[0].full_url.endswith('/users?limit=100'))
            self.assertEqual(page['has_more'],'false');self.assertEqual(page['next_cursor'],'1')
            self.assertNotIn('PROVIDER_SECRET',json.dumps(page));self.assertNotIn('COOKIE_SECRET',json.dumps(page))
            with patch.object(fixture.module,'maxplayer_request',return_value=page):
                result=self.client.get('/api/admin/maxplayer-comparacion')
            self.assertEqual(result.status_code,200);self.assertTrue(result.json['source_complete'])

    def test_csv_is_not_saved_and_api_error_cannot_leak_token(self):
        content=b'MaxPlayer ID,Username,List Username,Password\n1,DEMO_FAMILIAR,DEMO_FAMILIAR,SECRET\n'
        response=self.client.post('/api/admin/maxplayer-comparacion',data={'file':(io.BytesIO(content),'test.csv'),'exported_on':'2026-11-09'})
        self.assertEqual(response.status_code,200);self.assertNotIn('SECRET',response.get_data(as_text=True))
        self.assertEqual(response.json['source_complete'],False)
        with patch.object(fixture.module,'maxplayer_configured',return_value=True),\
             patch.object(fixture.module,'maxplayer_request',side_effect=fixture.module.MaxPlayerError('TOKEN_SECRET')):
            response=self.client.get('/api/admin/maxplayer-comparacion')
        self.assertEqual(response.status_code,502);self.assertNotIn('TOKEN_SECRET',response.get_data(as_text=True))
        self.assertEqual(self.client.get('/api/admin/maxplayer-comparacion?min_dias=-1').status_code,400)

    def test_http_failures_are_distinguished_without_returning_provider_body(self):
        for status,body,kind in [(401,b'TOKEN_SECRET','authentication'),(403,b'cloudflare TOKEN_SECRET','edge_block'),
                                 (403,b'TOKEN_SECRET','forbidden'),(404,b'TOKEN_SECRET','endpoint'),
                                 (422,b'TOKEN_SECRET','parameters'),(429,b'TOKEN_SECRET','rate_limit'),
                                 (503,b'TOKEN_SECRET','provider_unavailable')]:
            with self.subTest(status=status,kind=kind),patch.object(fixture.module,'maxplayer_configured',return_value=True),\
                 patch.object(fixture.module.urlrequest,'urlopen',side_effect=HTTPError('https://api.maxplayer.tv/',status,'error',{},io.BytesIO(body))):
                response=self.client.get('/api/admin/maxplayer-comparacion')
                self.assertEqual(response.status_code,502)
                self.assertEqual(response.json['diagnostic'],{'kind':kind,'http_status':status})
                self.assertNotIn('TOKEN_SECRET',response.get_data(as_text=True))
                self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_network_failures_and_provider_domain_rejections_are_not_assumed_invalid_token(self):
        with patch.object(fixture.module,'maxplayer_configured',return_value=True),\
             patch.object(fixture.module.urlrequest,'urlopen',side_effect=URLError('NETWORK_SECRET')):
            response=self.client.get('/api/admin/maxplayer-comparacion')
        self.assertEqual(response.json['diagnostic']['kind'],'network')
        self.assertNotIn('NETWORK_SECRET',response.get_data(as_text=True))
        self.assertEqual(fixture.module.maxplayer_error_kind(200,'Invalid domain ID: SECRET'),'domain')
        self.assertEqual(fixture.module.maxplayer_error_kind(200,'API token is not valid: SECRET'),'authentication')


if __name__=='__main__':unittest.main()
