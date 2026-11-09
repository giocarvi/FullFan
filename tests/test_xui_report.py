"""Synthetic transport, matching, access and history-preservation checks."""
from datetime import date
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import test_control as fixture
from xui_report import OWNER, XuiReportError, compare_clients, fetch_lines, parse_line


def raw_line(line_id=1, username='DEMO_FAMILIAR', owner=OWNER, state='Active', expiry='2026-12-01', devices='0 / 6'):
    return [str(line_id), username, 'CLIENT_PASSWORD_MUST_NOT_LEAK', owner,
            '<i title="'+state+'"></i>', '', '', '', devices, expiry, 'Never', '<a>Options</a>']


class Response:
    def __init__(self, value, url):
        self.value = value.encode();self.url = url
    def __enter__(self):return self
    def __exit__(self, *args):pass
    def read(self, size):return self.value[:size]
    def geturl(self):return self.url


class Opener:
    def __init__(self, pages):self.pages=iter(pages);self.calls=[]
    def open(self, req, timeout):
        url=req if isinstance(req,str) else req.full_url
        method='GET' if isinstance(req,str) else req.get_method()
        self.calls.append((method,url))
        if method=='POST':return Response('login accepted',url)
        return Response(json.dumps(next(self.pages)),url)


class XuiParsingTests(unittest.TestCase):
    def test_owner_and_password_redaction_and_max_connections(self):
        row=parse_line(raw_line())
        self.assertEqual(row['devices'],6)
        self.assertNotIn('PASSWORD',json.dumps(row))
        self.assertIsNone(parse_line(raw_line(owner='other')))
        self.assertIsNone(parse_line(raw_line(owner='giocarvi2')))
        self.assertEqual(parse_line(raw_line(state='Inactive'))['state'],'inactivo')

    def test_unknowns_are_not_guessed(self):
        row=parse_line(raw_line(state='?',devices='?',expiry='?'))
        self.assertIsNone(row['devices']);self.assertIsNone(row['expiry'])
        self.assertEqual(row['state'],'desconocido')
        row=parse_line(raw_line(expiry='Never',devices='3'))
        self.assertTrue(row['unlimited']);self.assertEqual(row['devices'],3)

    def test_capped_pages_use_returned_length_and_only_read_endpoints(self):
        opener=Opener([{'recordsFiltered':3,'data':[raw_line()]},
                       {'recordsFiltered':3,'data':[raw_line(2,owner='another')]},
                       {'recordsFiltered':3,'data':[raw_line(3,username='demo2')]}])
        lines=fetch_lines('TEST_PANEL_USER','TEST_PANEL_PASSWORD',opener=opener)
        self.assertEqual(len(lines),2)
        self.assertEqual([c[0] for c in opener.calls],['POST','GET','GET','GET'])
        self.assertTrue(opener.calls[0][1].endswith('/login'))
        self.assertEqual([parse_qs(urlparse(c[1]).query)['start'][0] for c in opener.calls[1:]],['0','1','2'])
        self.assertNotIn('TEST_PANEL_PASSWORD',json.dumps(lines)+str(opener.calls))

    def test_partial_duplicate_changing_count_and_no_owner_abort(self):
        pages=[
            [{'recordsFiltered':2,'data':[raw_line()]},{'recordsFiltered':2,'data':[]}],
            [{'recordsFiltered':2,'data':[raw_line()]},{'recordsFiltered':2,'data':[raw_line()]}],
            [{'recordsFiltered':2,'data':[raw_line()]},{'recordsFiltered':3,'data':[raw_line(2)]}],
            [{'recordsFiltered':1,'data':[raw_line(owner='other')]}],
            [{'data':[]}],
        ]
        for responses in pages:
            with self.subTest(responses=responses),self.assertRaises(XuiReportError):
                fetch_lines('test','test',opener=Opener(responses))

    def test_bad_host_never_receives_login(self):
        opener=Opener([])
        with self.assertRaises(XuiReportError):
            fetch_lines('test','secret',base_url='http://another-host.local/panel',opener=opener)
        self.assertEqual(opener.calls,[])

    def test_network_error_cannot_expose_credentials(self):
        opener=Opener([])
        with patch.object(opener,'open',side_effect=RuntimeError('TEST_SECRET')):
            with self.assertRaises(XuiReportError) as error:fetch_lines('test','TEST_SECRET',opener=opener)
        self.assertNotIn('TEST_SECRET',str(error.exception))


class XuiMatchingTests(unittest.TestCase):
    def client(self,username='DEMO_FAMILIAR',**kwargs):
        return dict(username=username,nombre='Demo',vencimiento='2026-12-01',devices=6,**kwargs)
    def compare(self,clients,lines):return compare_clients(clients,lines,date(2026,11,9))['rows']
    def test_active_fenix_missing_time_devices_and_expired_xui(self):
        rows=self.compare([self.client()],[parse_line(raw_line(expiry='2026-11-08',devices='0 / 3',state='Expired'))])
        self.assertEqual(rows[0]['difference_days'],-23)
        for flag in ['falta_tiempo_xui','fenix_activo_xui_no','dispositivos_distintos']:
            self.assertIn(flag,rows[0]['flags'])

    def test_xui_active_fenix_expired_and_today_inclusive(self):
        client=self.client();client['vencimiento']='2026-11-08'
        self.assertIn('xui_activo_fenix_vencido',self.compare([client],[parse_line(raw_line())])[0]['flags'])
        client['vencimiento']='2026-11-09'
        self.assertEqual(self.compare([client],[parse_line(raw_line())])[0]['fenix'][0]['state'],'activo')

    def test_service_alias_casefold_not_approximate_and_excludes_other_owners(self):
        client=self.client(service_username='  ServiceName  ')
        rows=self.compare([client],[parse_line(raw_line(username='servicename'))])
        self.assertEqual(len(rows),1);self.assertIn('coinciden',rows[0]['flags'])
        rows=self.compare([client],[parse_line(raw_line(username='service name'))])
        self.assertEqual(len(rows),2)
        line=parse_line(raw_line());line['owner']='other'
        self.assertEqual(self.compare([],[line]),[])

    def test_duplicates_are_grouped_without_arbitrary_pair_comparison(self):
        clients=[self.client('portalA',service_username='shared'),self.client('portalB',service_username='SHARED')]
        lines=[parse_line(raw_line(1,'shared')),parse_line(raw_line(2,'SHARED'))]
        row=self.compare(clients,lines)[0]
        self.assertIn('duplicados',row['flags']);self.assertIsNone(row['difference_days'])
        self.assertEqual(len(row['fenix']),2);self.assertEqual(len(row['xui']),2)
        self.assertNotIn('falta_tiempo_xui',row['flags'])

    def test_archived_unknown_and_absent_not_assumed_active(self):
        row=self.compare([self.client(archived_at='2026-11-01')],[])[0]
        self.assertIn('archivados',row['flags']);self.assertIn('solo_fenix',row['flags'])
        row=self.compare([self.client()],[parse_line(raw_line(state='?',devices='?',expiry='?'))])[0]
        self.assertIn('datos_incompletos',row['flags']);self.assertNotIn('fenix_activo_xui_no',row['flags'])
        self.assertNotIn('coinciden',row['flags'])


class XuiRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.initialize()
    def setUp(self):fixture.seed();self.client=fixture.client()

    def test_admin_only_even_with_direct_api_request(self):
        with patch.object(fixture.module,'fetch_xui_report_lines') as fetch:
            for role in ['atencion','reseller']:
                c=fixture.client(role)
                for method in ['get','post']:
                    self.assertEqual(getattr(c,method)('/api/admin/xui-comparacion',json={'username':'test','password':'secret'}).status_code,403)
            c=fixture.module.app.test_client()
            self.assertEqual(c.get('/api/admin/xui-comparacion').status_code,302)
            fetch.assert_not_called()
        for role in ['admin','atencion']:
            page=fixture.client(role).get('/app').get_data(as_text=True)
            self.assertEqual('id="view-xui"' in page,role=='admin')
            self.assertEqual('data-view="xui"' in page,role=='admin')

    def test_readonly_report_preserves_entire_historical_snapshot(self):
        from scripts.snapshot_payment_history import capture
        db=fixture.module.get_db();before=capture(db);db.close()
        with patch.object(fixture.module,'fetch_xui_report_lines',return_value=[parse_line(raw_line())]):
            response=self.client.post('/api/admin/xui-comparacion',json={'username':'panel','password':'PANEL_SECRET'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(response.json['total_xui'],1);self.assertEqual(response.json['owner'],OWNER)
        self.assertNotIn('SECRET',response.get_data(as_text=True));self.assertNotIn('PASSWORD',response.get_data(as_text=True))
        db=fixture.module.get_db();after=capture(db,baseline=before);db.close()
        self.assertEqual(before['tables'],after['tables'])

    def test_missing_credentials_and_transport_failure_return_no_partial_rows(self):
        with patch.dict(fixture.module.os.environ,{'XUI_USER':'','XUI_PASS':''}):
            response=self.client.get('/api/admin/xui-comparacion')
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.json['code'],'xui_credentials_required')
        with patch.object(fixture.module,'fetch_xui_report_lines',side_effect=XuiReportError('Consulta no disponible')):
            response=self.client.post('/api/admin/xui-comparacion',json={'username':'test','password':'secret'})
            self.assertEqual(response.status_code,502);self.assertNotIn('rows',response.json)


if __name__=='__main__':unittest.main()
