"""One-account administrative deletion with fresh checks and durable at-most-once sending."""
import hmac
import hashlib
import secrets
from urllib.parse import urlparse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import request, session, jsonify
from maxplayer_cleanup import deletion_block, review_block, device_presence, fingerprint, supported_endpoint
from maxplayer_report import normalize_page

TTL=180
TERMINAL_OR_PENDING={'checking','sending','verifying','uncertain','deleted'}


def csrf_token():
    if 'maxplayer_cleanup_csrf' not in session:
        session['maxplayer_cleanup_csrf']=secrets.token_urlsafe(32)
    return session['maxplayer_cleanup_csrf']


def operations(api):
    db=api.get_db()
    try:
        c=db.cursor();c.execute('SELECT maxplayer_id,username,actor,status,reason,updated_at FROM maxplayer_cleanup_operations ORDER BY updated_at DESC')
        return api.fetchall(c)
    finally:db.close()


def decorate_report(api, report, live):
    report['deletion_csrf']=csrf_token()
    by_id={r['maxplayer_id']:r for r in operations(api)}
    for row in report['rows']:
        reason=deletion_block(row,live and report['source_complete'])
        can_check=review_block(row,live and report['source_complete']) is None and row['maxplayer'].get('online') is not True
        if not supported_endpoint(api.MAXPLAYER_API_BASE):
            reason='El borrado requiere el endpoint HTTPS oficial documentado de Max Player.';can_check=False
        operation=by_id.get(row['maxplayer']['id'])
        if operation and operation['status'] in TERMINAL_OR_PENDING:
            reason='Existe una eliminación registrada o pendiente. Revisa el historial; no se enviará otra orden.'
            can_check=False
        row['deletion_block']=reason
        row['can_prepare_deletion']=reason is None
        row['can_check_connection']=can_check
        row['cleanup_status']=operation['status'] if operation else None
    return report


def register_routes(app,api):
    def response(data,status=200):
        result=jsonify(data);result.headers['Cache-Control']='no-store'
        return result,status

    def authorized(mutating=False):
        if session.get('rol')!='admin':return response({'error':'Solo administrador.'},403)
        db=api.get_db()
        try:
            c=db.cursor();c.execute(api.qmark('SELECT rol FROM usuarios WHERE username=?'),(session.get('user'),))
            user=api.fetchone(c)
        finally:db.close()
        if not user or user['rol']!='admin':return response({'error':'Tu perfil actual no autoriza esta operación.'},403)
        if mutating:
            value=request.headers.get('X-CSRF-Token','')
            if not value.isascii() or not session.get('maxplayer_cleanup_csrf') or not hmac.compare_digest(value,session['maxplayer_cleanup_csrf']):
                return response({'error':'La confirmación de sesión no es válida. Vuelve a consultar el reporte.'},403)
            if request.headers.get('Origin'):
                origin=urlparse(request.headers['Origin'])
                local=request.host.split(':',1)[0] in ('localhost','127.0.0.1')
                # Railway terminates HTTPS before Flask; do not compare with wsgi.url_scheme.
                if origin.netloc.casefold()!=request.host.casefold() or origin.scheme not in (('http','https') if local else ('https',)) or origin.path not in ('','/') or origin.query or origin.fragment or origin.username:
                    return response({'error':'Origen de la solicitud no permitido.'},403)
            if not request.is_json:return response({'error':'Se requiere una solicitud JSON.'},415)
            if not supported_endpoint(api.MAXPLAYER_API_BASE):return response({'error':'El borrado requiere el endpoint HTTPS oficial documentado de Max Player.'},503)
        return None

    def signer():return URLSafeTimedSerializer(app.secret_key,salt='maxplayer-single-account-delete-v1')

    def provider_scope():
        secret=app.secret_key.encode() if isinstance(app.secret_key,str) else app.secret_key
        return hmac.new(secret,('maxplayer-cleanup:'+api.MAXPLAYER_API_TOKEN).encode(),hashlib.sha256).hexdigest()

    def read_live(grace,account_id=None):
        target_page={}
        def observe(params,accounts):
            if any(a['id']==str(account_id) for a in accounts):target_page.update(params)
        accounts,complete=api.fetch_max_report_customers(lambda params:api.get_maxplayer_users(params,include_pagination=True),page_observer=observe)
        if account_id is not None and complete and any(a['id']==str(account_id) for a in accounts) and not target_page:
            raise api.MaxReportError('No se pudo ubicar la página actual de la cuenta. No se permite eliminarla.')
        if account_id is not None and complete and target_page:
            # Re-read the documented page containing the target, after the complete scan.
            # Its connection must not be inferred from an earlier page or a stale report.
            api.time.sleep(1.05)
            fresh=normalize_page(api.get_maxplayer_users(target_page,include_pagination=True))
            target_rows=[a for a in fresh if a['id']==str(account_id)]
            if len(target_rows)>1:raise api.MaxReportError('La cuenta se repitió durante la comprobación actual.')
            accounts=[a for a in accounts if a['id']!=str(account_id)]+target_rows
        report=api.compare_max_accounts(api.load_max_comparison_clients(),accounts,api.today_gt(),grace)
        report.update(source='API Max Player',source_complete=complete,exported_on=api.today_gt().isoformat())
        row=target(report,account_id) if account_id is not None else None
        if row and complete and review_block(row,complete) is None and row['maxplayer'].get('online') is not True:
            # OpenAPI 1.5.0: GET /users/{id} lists a RESELLER's customers.
            # Single-customer identity and heartbeat have separate documented routes.
            api.time.sleep(1.05)
            details=api.maxplayer_request('GET',f'/customers/{account_id}')
            if not isinstance(details,dict) or type(details.get('success')) is not int or details['success']!=1 or not isinstance(details.get('data'),dict):
                raise api.MaxReportError('Max Player no devolvió una identidad individual verificable. No se permite borrar.')
            identity=details['data']
            if identity.get('id')!=str(account_id) or identity.get('username')!=row['maxplayer']['username']:
                raise api.MaxReportError('La identidad individual ya no coincide con el reporte. Actualiza la consulta; no se permite borrar.')
            api.time.sleep(1.05)
            presence=device_presence(api.maxplayer_request('GET',f'/customers/{account_id}/devices'),api.time.time())
            for account in accounts:
                if account['id']==str(account_id):account.update(presence)
            # Reload Fénix AFTER the latest provider heartbeat.
            report=api.compare_max_accounts(api.load_max_comparison_clients(),accounts,api.today_gt(),grace)
            report.update(source='API Max Player',source_complete=complete,exported_on=api.today_gt().isoformat())
        return report

    def target(report,account_id):
        matches=[row for row in report['rows'] if row['maxplayer']['id']==str(account_id)]
        return matches[0] if len(matches)==1 else None

    def get_operation(account_id):
        db=api.get_db()
        try:
            c=db.cursor();c.execute(api.qmark('SELECT * FROM maxplayer_cleanup_operations WHERE maxplayer_id=?'),(str(account_id),))
            return api.fetchone(c)
        finally:db.close()

    def set_status(account_id,request_id,status,reason,action):
        db=api.get_db()
        try:
            c=db.cursor();c.execute(api.qmark('''UPDATE maxplayer_cleanup_operations SET status=?,reason=?,updated_at=?
                WHERE maxplayer_id=? AND request_id=?'''),(status,reason,api.now_gt().isoformat(),str(account_id),request_id))
            if c.rowcount!=1:raise RuntimeError('No se pudo asegurar el registro de la operación.')
            api.audit_event(c,'maxplayer',account_id,action,reason=reason,metadata={'request_id':request_id,'status':status})
            db.commit()
        finally:db.close()

    def claim(account_id,plan,reason):
        db=api.get_db()
        try:
            c=db.cursor();c.execute(api.qmark('''INSERT INTO maxplayer_cleanup_operations
                (maxplayer_id,request_id,username,actor,status,reason,updated_at) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(maxplayer_id) DO NOTHING'''),
                (str(account_id),plan['request_id'],plan['username'],session['user'],'checking',reason,api.now_gt().isoformat()))
            created=c.rowcount==1
            if not created:
                c.execute(api.qmark('SELECT * FROM maxplayer_cleanup_operations WHERE maxplayer_id=?'),(str(account_id),))
                old=api.fetchone(c)
                if old['status'] in TERMINAL_OR_PENDING or old['request_id']==plan['request_id']:
                    db.rollback();return old
                c.execute(api.qmark('''UPDATE maxplayer_cleanup_operations SET request_id=?,username=?,actor=?,status='checking',reason=?,updated_at=?
                    WHERE maxplayer_id=? AND request_id=? AND status IN ('blocked','not_sent','rejected')'''),
                    (plan['request_id'],plan['username'],session['user'],reason,api.now_gt().isoformat(),str(account_id),old['request_id']))
                if c.rowcount!=1:
                    db.rollback();return old
            api.audit_event(c,'maxplayer',account_id,'deletion_requested',reason=reason,
                metadata={'request_id':plan['request_id'],'maxplayer_username':plan['username']})
            db.commit();return None
        finally:db.close()

    @app.route('/api/admin/maxplayer-eliminaciones',methods=['GET'])
    @api.login_required
    def maxplayer_cleanup_history():
        denied=authorized()
        if denied:return denied
        return response({'operations':operations(api)[:100],'csrf':csrf_token()})

    @app.route('/api/admin/maxplayer/<int:account_id>/preparar-eliminacion',methods=['POST'])
    @api.login_required
    def maxplayer_cleanup_prepare(account_id):
        denied=authorized(True)
        if denied:return denied
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return response({'error':'Solicitud inválida.'},400)
        try:grace=max(7,min(3650,int(data.get('min_dias',7))))
        except (ValueError,TypeError):return response({'error':'Margen inválido.'},400)
        old=get_operation(account_id)
        if old and old['status'] in TERMINAL_OR_PENDING:
            return response({'error':'Ya hay una operación registrada. Revisa o verifica su estado; no se enviará otra orden.','status':old['status']},409)
        if not api._max_report_lock.acquire(blocking=False):return response({'error':'Hay otra consulta en proceso. Espera a que termine.'},409)
        try:
            report=read_live(grace,account_id);row=target(report,account_id)
            block=deletion_block(row,report['source_complete'])
            if block:return response({'error':block},409)
            if data.get('username')!=row['maxplayer']['username']:
                return response({'error':'El usuario ya no coincide con la cuenta seleccionada. Actualiza el reporte.'},409)
            plan={'actor':session['user'],'id':str(account_id),'username':row['maxplayer']['username'],
                  'fingerprint':fingerprint(row),'grace':grace,'request_id':secrets.token_urlsafe(24),'provider_scope':provider_scope()}
            return response({'confirmation':signer().dumps(plan),'account':row['maxplayer'],'fenix':row['fenix'],
                             'flags':row['flags'],'expires_in':TTL,'checked_at':report['generated_at']})
        except api.MaxReportError as error:return response({'error':str(error)},502)
        except api.MaxPlayerError as error:return response(api.maxplayer_report_failure(error),502)
        finally:api._max_report_lock.release()

    @app.route('/api/admin/maxplayer/<int:account_id>/eliminar',methods=['POST'])
    @api.login_required
    def maxplayer_cleanup_delete(account_id):
        denied=authorized(True)
        if denied:return denied
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return response({'error':'Solicitud inválida.'},400)
        try:plan=signer().loads(data.get('confirmation',''),max_age=TTL)
        except (BadSignature,SignatureExpired,TypeError):return response({'error':'La confirmación venció o no es válida. Prepara una nueva revisión.'},409)
        if plan.get('actor')!=session['user'] or plan.get('id')!=str(account_id):
            return response({'error':'La confirmación no corresponde a esta sesión o cuenta.'},403)
        if not hmac.compare_digest(str(plan.get('provider_scope','')),provider_scope()):
            return response({'error':'Cambió el acceso a Max Player desde la preparación. Revisa una nueva confirmación.'},409)
        reason=data.get('reason')
        if data.get('typed_username')!=plan['username'] or data.get('acknowledged') is not True or not isinstance(reason,str) or not 3<=len(reason.strip())<=500:
            return response({'error':'Escribe exactamente el usuario, indica el motivo y confirma la advertencia.'},400)
        if not api._max_report_lock.acquire(blocking=False):return response({'error':'Hay otra consulta en proceso. Espera a que termine.'},409)
        claimed=False;sent=False;delete_returned=False
        try:
            old=claim(account_id,plan,reason.strip())
            if old:
                if old['status']=='deleted' and old['username']==plan['username']:
                    return response({'ok':True,'status':'deleted','replayed':True,'message':'La eliminación ya estaba confirmada. No se envió otra orden.'})
                return response({'error':'La operación ya fue recibida. Revisa el historial; no se reenvía el borrado.','status':old['status']},409)
            claimed=True
            report=read_live(plan['grace'],account_id);row=target(report,account_id)
            block=deletion_block(row,report['source_complete'])
            if not block and (fingerprint(row)!=plan['fingerprint'] or row['maxplayer']['username']!=plan['username']):
                block='Los datos cambiaron desde la preparación. Debes revisar una nueva confirmación.'
            try:signer().loads(data['confirmation'],max_age=TTL)
            except (BadSignature,SignatureExpired):block='La confirmación venció durante la comprobación. Prepara otra.'
            if block:
                set_status(account_id,plan['request_id'],'blocked',block,'deletion_blocked')
                return response({'error':block,'status':'blocked'},409)
            # Make an intended send durable before the one and only external DELETE.
            set_status(account_id,plan['request_id'],'sending',reason.strip(),'deletion_sending')
            sent=True
            api.delete_maxplayer_user(str(account_id))
            delete_returned=True
            set_status(account_id,plan['request_id'],'verifying',reason.strip(),'deletion_submitted')
            after=read_live(plan['grace'])
            absent=after['source_complete'] and target(after,account_id) is None
            state='deleted' if absent else 'uncertain'
            message='Cuenta eliminada de Max Player y ausencia confirmada. Cliente y pagos de Fénix conservados.' if absent else 'La orden fue enviada, pero no se confirmó la ausencia. No se reenviará; usa Verificar estado.'
            set_status(account_id,plan['request_id'],state,reason.strip(),'deletion_confirmed' if absent else 'deletion_uncertain')
            return response({'ok':absent,'status':state,'message':message,'request_id':plan['request_id']},200 if absent else 202)
        except (api.MaxPlayerError,api.MaxReportError) as error:
            safe=api.maxplayer_report_failure(error) if isinstance(error,api.MaxPlayerError) else {'error':str(error)}
            rejected=sent and not delete_returned and isinstance(error,api.MaxPlayerError) and error.http_status in (400,401,403,404,405,409,422,429)
            state='rejected' if rejected else 'uncertain' if sent else 'not_sent'
            if claimed:set_status(account_id,plan['request_id'],state,safe['error'],'deletion_'+state)
            suffix=' Max Player rechazó la orden. No se reintenta automáticamente; corrige la causa y prepara otra revisión.' if rejected else ' La orden pudo haberse recibido. No la repitas; verifica el estado.' if sent else ' No se envió una orden de borrado.'
            return response({**safe,'status':state,'error':safe['error']+suffix},502)
        except Exception:
            # Never automatically repeat a request after a lost response or local recording failure.
            return response({'error':'No se pudo completar la comprobación. Revisa el historial antes de repetir.','status':'uncertain' if sent else 'checking'},500)
        finally:api._max_report_lock.release()

    @app.route('/api/admin/maxplayer/<int:account_id>/verificar-eliminacion',methods=['POST'])
    @api.login_required
    def maxplayer_cleanup_verify(account_id):
        denied=authorized(True)
        if denied:return denied
        operation=get_operation(account_id)
        if not operation:return response({'error':'No hay una operación registrada para esta cuenta.'},404)
        if operation['status']=='deleted':return response({'ok':True,'status':'deleted','message':'La ausencia ya estaba confirmada.'})
        if not api._max_report_lock.acquire(blocking=False):return response({'error':'Hay otra consulta en proceso.'},409)
        try:
            report=read_live(7)
            if not report['source_complete']:return response({'error':'La API no confirmó un recorrido completo. No se cambia el estado.'},409)
            if target(report,account_id) is None:
                set_status(account_id,operation['request_id'],'deleted',operation['reason'],'deletion_absence_verified')
                return response({'ok':True,'status':'deleted','message':'Ausencia de la cuenta confirmada. No se envió una nueva orden de borrado.'})
            return response({'ok':False,'status':operation['status'],'message':'La cuenta aún aparece en Max Player. No se envió ninguna orden de borrado; requiere revisión.'},409)
        except api.MaxReportError as error:return response({'error':str(error)},502)
        except api.MaxPlayerError as error:return response(api.maxplayer_report_failure(error),502)
        finally:api._max_report_lock.release()
