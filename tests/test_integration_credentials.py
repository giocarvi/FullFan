import unittest
from unittest.mock import patch
import test_control as fixture
from integration_credentials import CredentialError, PREFIX, seal, unseal
from xui_report import XuiReportError
from scripts.snapshot_payment_history import capture


class IntegrationCredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.initialize()
    def setUp(self):fixture.seed();self.client=fixture.client()

    def test_authenticated_encryption_bound_to_integration_and_server_key(self):
        token=seal('SYNTHETIC_SERVER_KEY','xui',{'password':'PANEL_SECRET'})
        self.assertNotIn('PANEL_SECRET',token)
        self.assertEqual(unseal('SYNTHETIC_SERVER_KEY','xui',token),{'password':'PANEL_SECRET'})
        for secret,integration in [('OTHER_KEY','xui'),('SYNTHETIC_SERVER_KEY','other')]:
            with self.assertRaises(CredentialError):unseal(secret,integration,token)
        with self.assertRaises(CredentialError):unseal('SYNTHETIC_SERVER_KEY','xui',token[:-2]+'AB')

    def test_save_only_after_success_and_reuse_without_exposing_in_config(self):
        db=fixture.module.get_db();before=capture(db);db.close()
        with patch.object(fixture.module,'fetch_xui_report_lines',return_value=[]):
            response=self.client.post('/api/admin/xui-comparacion',json={'username':'PANEL_USER','password':'PANEL_SECRET','remember':True})
        self.assertEqual(response.status_code,200);self.assertTrue(response.json['credential_saved'])
        stored=fixture.rows('SELECT valor FROM configuracion WHERE clave=?',(PREFIX+'xui',))[0]['valor']
        self.assertNotIn('PANEL_SECRET',stored);self.assertNotIn('PANEL_USER',stored)
        with patch.object(fixture.module,'fetch_xui_report_lines',return_value=[]) as fetch:
            self.assertEqual(self.client.get('/api/admin/xui-comparacion').status_code,200)
            self.assertEqual(fetch.call_args.args,('PANEL_USER','PANEL_SECRET'))
        for role in ['admin','atencion']:
            response=fixture.client(role).get('/api/config')
            self.assertNotIn(PREFIX,response.get_data(as_text=True));self.assertNotIn('PANEL_SECRET',response.get_data(as_text=True))
        db=fixture.module.get_db();after=capture(db,baseline=before);db.close()
        self.assertEqual(before['tables'],after['tables'])

    def test_failed_access_is_not_saved_and_general_config_cannot_overwrite_it(self):
        with patch.object(fixture.module,'fetch_xui_report_lines',side_effect=XuiReportError('Acceso no disponible')):
            response=self.client.post('/api/admin/xui-comparacion',json={'username':'test','password':'secret','remember':True})
        self.assertEqual(response.status_code,502)
        self.assertEqual(fixture.rows('SELECT * FROM configuracion WHERE clave=?',(PREFIX+'xui',)),[])
        self.assertEqual(self.client.post('/api/config',json={PREFIX+'xui':'not_encrypted'}).status_code,400)

    def test_only_admin_can_forget_and_only_integration_access_is_removed(self):
        fixture.module.save_integration_access('xui',{'username':'test','password':'secret'})
        before=fixture.rows('SELECT * FROM pagos')
        self.assertEqual(fixture.client('atencion').delete('/api/admin/integrations/xui').status_code,403)
        self.assertEqual(self.client.delete('/api/admin/integrations/not-an-integration').status_code,404)
        self.assertEqual(self.client.delete('/api/admin/integrations/xui').status_code,200)
        self.assertEqual(fixture.rows('SELECT * FROM configuracion WHERE clave=?',(PREFIX+'xui',)),[])
        self.assertEqual(before,fixture.rows('SELECT * FROM pagos'))


if __name__=='__main__':unittest.main()
