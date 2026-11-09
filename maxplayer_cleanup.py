"""Fail-closed policy and immutable confirmation fingerprint for one-account cleanup."""
import hashlib
import json
from urllib.parse import urlparse


def supported_endpoint(base):
    try:
        url=urlparse(base)
        return url.scheme=='https' and url.hostname=='api.maxplayer.tv' and url.port in (None,443) and url.path.rstrip('/')=='/v3/api/public' and not (url.username or url.password or url.query or url.fragment)
    except ValueError:return False


def fingerprint(row):
    # Heartbeat timestamps advance on every read; identity, devices and status must not.
    canonical={**row,'maxplayer':{k:v for k,v in row['maxplayer'].items() if k!='presence_generated_at_unix'}}
    return hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def review_block(row, complete):
    if not complete:return 'La API no confirmó el recorrido completo. No se permite borrar desde una fuente parcial o CSV.'
    if not row:return 'No se encontró esa cuenta en la lectura actual de Max Player.'
    account=row['maxplayer']
    if not str(account.get('id','')).isdigit() or int(account['id'])<1 or not account.get('username'):
        return 'Falta un identificador o usuario inequívoco de la cuenta.'
    if any('*' in value or value.casefold() in ('redacted','hidden','<redacted>') for value in [account['username'],*account.get('list_usernames',[])]):
        return 'La API ocultó parte de la identidad. No se permite borrar sin una coincidencia verificable.'
    flags=set(row['flags'])
    guards=[('conservar_activo','Tiene una coincidencia vigente en Fénix.'),
            ('duplicados','Hay usuarios o listas duplicados en Max Player.'),
            ('coincidencia_ambigua','Hay más de una coincidencia en Fénix.'),
            ('sin_fecha','Falta una fecha de vencimiento verificable en Fénix.'),
            ('activacion_pendiente','Tiene una activación pendiente.'),
            ('pago_reciente','Tiene un pago válido registrado en los últimos 7 días.'),
            ('vencido_reciente','Su vencimiento está dentro del margen de protección.')]
    for flag,message in guards:
        if flag in flags:return message+' No se eliminará.'
    matches=row['fenix']
    if matches and not all(f['expiry'] and f['state'] in ('archivado','vencido') and f['days_expired']>=7 for f in matches):
        return 'No cumple el margen mínimo de 7 días vencido en Fénix, incluso si está archivado.'
    if not row.get('candidate'):
        return 'La cuenta no cumple los criterios y el margen elegidos en la revisión actual.'
    return None


def deletion_block(row, complete):
    if complete and row and row['maxplayer'].get('online') is True:
        return 'La cuenta está conectada. No se eliminará para evitar cortar el servicio.'
    blocked=review_block(row,complete)
    if blocked:return blocked
    if row['maxplayer'].get('online') is not False:
        return row['maxplayer'].get('presence_reason') or 'Max Player no confirmó si está conectada. No se permite eliminarla con conexión desconocida.'
    return None


def device_presence(payload,now):
    """OpenAPI 1.5.0 GET /customers/{id}/devices. Never infer offline from absence."""
    unknown={'online':None,'presence_reason':'Max Player no pudo confirmar la conexión actual de todos los dispositivos.'}
    if not isinstance(payload,dict) or type(payload.get('success')) is not int or payload['success']!=1 or not isinstance(payload.get('data'),list):
        return unknown
    devices=payload['data']
    if any(isinstance(d,dict) and d.get('online') is True for d in devices):
        return {'online':True,'presence_reason':None}
    if not devices:
        return {**unknown,'presence_reason':'No hay dispositivos registrados. La ausencia de registros no confirma que esté desconectada; puede haber registros pendientes.'}
    stamp=payload.get('presence_generated_at_unix')
    if payload.get('presence_available') is not True or type(stamp) is not int or not now-120<=stamp<=now+15:
        return {**unknown,'presence_reason':'La información de conexión está ausente o desactualizada. No se permite eliminar la cuenta.'}
    ids=set();evidence=[]
    for device in devices:
        if not isinstance(device,dict):return unknown
        identity=device.get('id');identifier=device.get('identifier')
        if not isinstance(identity,str) or not identity.isascii() or not identity.isdigit() or int(identity)<1 or identity in ids or not isinstance(identifier,str) or not identifier.strip() or device.get('online') is not False:
            return unknown
        ids.add(identity);evidence.append([identity,identifier])
    evidence.sort()
    return {'online':False,'presence_reason':None,'presence_source':'customer_devices',
            'presence_device_count':len(devices),'presence_generated_at_unix':stamp,
            'presence_devices_hash':hashlib.sha256(json.dumps(evidence,separators=(',',':')).encode()).hexdigest()}


SCHEMA='''CREATE TABLE IF NOT EXISTS maxplayer_cleanup_operations (
    maxplayer_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    username TEXT NOT NULL,
    actor TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
)'''
