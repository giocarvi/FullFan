"""Read-only account review. Candidates are never deletion instructions."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import csv
import io
import re
import time
from xui_report import day, GT


class MaxReportError(Exception):
    pass


def clean(value):
    return str(value if value is not None else '').strip()


def key(value):
    return clean(value).casefold()


def pick(row, *names):
    lookup={re.sub(r'[\s_-]+','',str(k)).casefold():v for k,v in row.items()}
    for name in names:
        value=lookup.get(re.sub(r'[\s_-]+','',name).casefold())
        if value is not None and value != '':
            return value
    return None


def boolean(value):
    value=key(value)
    if value in ('1','true','yes','active','enabled','online','activo'):return True
    if value in ('0','false','no','inactive','disabled','offline','inactivo'):return False
    return None


def connection(value):
    if value is None or clean(value)=='':return None
    if key(value) in ('never','nunca','0','null','none'):return 'Nunca'
    try:
        timestamp=float(value)
        if timestamp>10**12:timestamp/=1000
        if timestamp>0:return datetime.fromtimestamp(timestamp,GT).isoformat()
    except (ValueError, TypeError, OSError, OverflowError):pass
    return clean(value)[:100]


def normalize_customer(raw):
    if not isinstance(raw,dict):raise MaxReportError('Max Player devolvió una cuenta con formato desconocido.')
    customer_id=clean(pick(raw,'id','customer_id','user_id','MaxPlayer ID'))
    username=clean(pick(raw,'username','user_name','Username Max Player'))
    aliases=[clean(pick(raw,'iptv_user','iptv_username','list_username','List Username'))]
    for list_key in ('lists','playlists'):
        lists=raw.get(list_key,[])
        if isinstance(lists,list):
            for item in lists:
                if isinstance(item,dict):aliases.append(clean(pick(item,'username','iptv_user','list_username')))
    aliases=list(dict.fromkeys(v for v in aliases if v))
    if not username and not aliases:
        raise MaxReportError('Falta el usuario de una cuenta de Max Player. No se puede comparar una lista incompleta.')
    state=boolean(pick(raw,'is_active','enabled','status'))
    return {'id':customer_id if customer_id.isdigit() else None,'username':username,'list_usernames':aliases,
            'state':'activo' if state is True else 'inactivo' if state is False else 'no_confirmado',
            'online':boolean(pick(raw,'is_online','online')),
            'last_connection':connection(pick(raw,'last_login','last_connection','connection','Last Login'))}


def parse_csv(content):
    try:decoded=content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise MaxReportError('El CSV debe estar en UTF-8. Vuelve a exportarlo desde Max Player.') from None
    try:
        dialect=csv.Sniffer().sniff(decoded[:10000],delimiters=',;\t')
        reader=csv.DictReader(io.StringIO(decoded),dialect=dialect)
        headers={re.sub(r'[\s_-]+','',h or '').casefold() for h in reader.fieldnames or []}
        if not headers.intersection({'username','listusername','iptvuser','iptvusername'}):
            raise MaxReportError('El archivo no tiene las columnas de usuarios de Max Player.')
        rows=[]
        for row in reader:
            if len(rows)>=50000:raise MaxReportError('El archivo excede el límite de cuentas permitido.')
            if all(not clean(v) for v in row.values()):continue
            rows.append(normalize_customer(row))
        if not rows:raise MaxReportError('El CSV no contiene cuentas para comparar.')
        return rows
    except (csv.Error, TypeError):
        raise MaxReportError('No se pudo interpretar el CSV exportado de Max Player.') from None


def normalize_page(page):
    wrapped=isinstance(page,dict) and 'payload' in page and 'has_more' in page
    payload=page['payload'] if wrapped else page
    container=payload
    if isinstance(payload,dict) and isinstance(payload.get('data'),dict):container=payload['data']
    batch=container if isinstance(container,list) else None
    if isinstance(container,dict):
        for name in ('users','customers','items','results','data'):
            if isinstance(container.get(name),list):batch=container[name];break
    if batch is None:raise MaxReportError('La API no devolvió una lista reconocible. Usa un CSV reciente de Customers.')
    return [normalize_customer(raw) for raw in batch]


def fetch_customers(get_users, *, pause=time.sleep, page_observer=None):
    """Documented cursor API: limit=100, X-Next-Cursor -> after_id until no more."""
    rows=[];seen=set();cursors=set();cursor=None;deadline=time.monotonic()+150;last_request=None
    while True:
        if time.monotonic()>deadline or len(cursors)>500:
            raise MaxReportError('La consulta de Max Player tardó demasiado. No se mostrará un reporte parcial; puedes usar su CSV.')
        if last_request is not None:
            remaining=1.05-(time.monotonic()-last_request)
            if remaining>0:pause(remaining)
        params={'limit':100}
        if cursor is not None:params['after_id']=cursor
        last_request=time.monotonic()
        page=get_users(params)
        wrapped=isinstance(page,dict) and 'payload' in page and 'has_more' in page
        batch=normalize_page(page)
        if page_observer:page_observer(dict(params),batch)
        for account in batch:
            identity=account['id'] or key(account['username'])
            if not identity or identity in seen:
                raise MaxReportError('Max Player repitió cuentas entre páginas. Usa un CSV reciente para evitar un reporte parcial.')
            seen.add(identity);rows.append(account)
        if len(rows)>50000:raise MaxReportError('Max Player excedió el límite de cuentas permitido.')
        more=clean(page.get('has_more')).casefold() if wrapped else ''
        if not more:
            if not rows:raise MaxReportError('La API no devolvió cuentas de Max Player.')
            # Without the documented final header, do not claim complete coverage.
            return rows,False
        if more in ('false','0'):return rows,True
        if more not in ('true','1'):
            raise MaxReportError('Max Player devolvió una cabecera X-Has-More no válida.')
        next_cursor=clean(page.get('next_cursor'))
        if not batch or not next_cursor or len(next_cursor)>2048 or next_cursor in cursors:
            raise MaxReportError('Max Player indicó más cuentas, pero el cursor falta o se repite. No se mostrará un reporte parcial.')
        cursors.add(next_cursor);cursor=next_cursor


def compare_accounts(clients,accounts,today,grace_days=7):
    index=defaultdict(dict);by_max_id=defaultdict(dict)
    for raw in clients:
        client=dict(raw);expiry=day(client.get('vencimiento'))
        archived=bool(client.get('archived_at'))
        client={'username':client['username'],'name':client.get('nombre') or client['username'],
                'expiry':expiry.isoformat() if expiry else None,
                'state':'archivado' if archived else 'sin_fecha' if not expiry else 'activo' if expiry>=today else 'vencido',
                'has_current_service':bool(expiry and expiry>=today),
                'days_expired':(today-expiry).days if expiry and expiry<today else 0,
                'last_payment':clean(client.get('last_payment')) or None,
                'recent_payment':bool(day(client.get('last_payment_recorded')) and day(client['last_payment_recorded'])>=today-timedelta(days=7)),
                'pending_activation':bool(client.get('pending_activation'))}
        for alias in (raw['username'],raw.get('service_username')):
            if key(alias):index[key(alias)][raw['username']]=client
        if clean(raw.get('maxplayer_user_id')):
            by_max_id[clean(raw['maxplayer_user_id'])][raw['username']]=client
    names=Counter();ids=Counter(a['id'] for a in accounts if a['id'])
    for account in accounts:
        for alias in {key(account['username']),*(key(a) for a in account['list_usernames'])}-{''}:names[alias]+=1
    rows=[];counts=Counter()
    for account in accounts:
        aliases={key(account['username']),*(key(a) for a in account['list_usernames'])}-{''}
        found={}
        for alias in aliases:found.update(index.get(alias,{}))
        found.update(by_max_id.get(account['id'],{}))
        matches=list(found.values());flags=[]
        duplicate=any(names[a]>1 for a in aliases) or bool(account['id'] and ids[account['id']]>1)
        active=any(f['state']=='activo' or f.get('has_current_service') for f in matches)
        pending=any(f['pending_activation'] or f['recent_payment'] for f in matches)
        ambiguous=len(matches)>1 or duplicate
        if duplicate:flags.append('duplicados')
        if len(matches)>1:flags.append('coincidencia_ambigua')
        if active:flags.append('conservar_activo')
        if not matches:flags.append('sin_fenix')
        if matches and all(f['state']=='archivado' for f in matches):flags.append('archivado_fenix')
        if any(f['state']=='vencido' for f in matches):flags.append('vencido_fenix')
        if any(not f['expiry'] for f in matches):flags.append('sin_fecha')
        if any(f['pending_activation'] for f in matches):flags.append('activacion_pendiente')
        if any(f['recent_payment'] for f in matches):flags.append('pago_reciente')
        if account['last_connection']=='Nunca':flags.append('nunca_conecto')
        if account['state']=='inactivo':flags.append('ya_inactivo_max')
        if account['state']=='no_confirmado':flags.append('estado_max_no_confirmado')
        if account['online'] is True:flags.append('conectado')
        expired_long=bool(matches) and all(f['expiry'] and f['state'] in ('archivado','vencido') and f['days_expired']>=grace_days for f in matches)
        candidate=(not matches or expired_long) and not (active or pending or ambiguous or account['online'] is True)
        if candidate:flags.append('candidato_revision')
        elif any(f['state']=='vencido' and f['days_expired']<grace_days for f in matches):flags.append('vencido_reciente')
        for flag in flags:counts[flag]+=1
        rows.append({'maxplayer':account,'fenix':matches,'flags':flags,'candidate':candidate})
    rows.sort(key=lambda r:(not r['candidate'],key(r['maxplayer']['username'])))
    return {'rows':rows,'counts':dict(counts),'today':today.isoformat(),'generated_at':datetime.now(GT).isoformat(),
            'grace_days':grace_days,'total_maxplayer':len(accounts),'total_fenix':len(clients)}
