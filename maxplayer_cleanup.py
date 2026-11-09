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
    return hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def deletion_block(row, complete):
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
    if account.get('online') is True:return 'La cuenta está conectada. No se eliminará para evitar cortar el servicio.'
    if account.get('online') is not False:return 'Max Player no confirmó si está conectada. No se permite eliminarla con conexión desconocida.'
    if not row.get('candidate'):
        return 'La cuenta no cumple los criterios y el margen elegidos en la revisión actual.'
    return None


SCHEMA='''CREATE TABLE IF NOT EXISTS maxplayer_cleanup_operations (
    maxplayer_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    username TEXT NOT NULL,
    actor TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
)'''
