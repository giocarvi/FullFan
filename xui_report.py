"""Read-only XUI reconciliation. Never exposes passwords or edits service lines."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import html
import http.cookiejar
import json
import re
import time
from urllib import request, parse

OWNER = 'giocarvi'
BASE_URL = 'http://xdplustv.online/99access99'
GT = timezone(timedelta(hours=-6))


class XuiReportError(Exception):
    pass


def text(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', str(value or '')))).strip()


def day(value):
    value = text(value)
    match = re.search(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)', value)
    try:
        if match:
            return date.fromisoformat(match.group(1))
        match = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', value)
        if match:
            d, m, y = map(int, match.groups())
            return date(y, m, d)
    except ValueError:
        pass
    return None


def number(value):
    try:
        return int(str(value).strip()) if int(str(value).strip()) > 0 else None
    except (TypeError, ValueError):
        return None


def parse_line(raw):
    row = raw if isinstance(raw, list) else raw.get('value', []) if isinstance(raw, dict) else []
    if len(row) < 12:
        raise XuiReportError('XUI cambió el formato de su tabla. No se mostrará una comparación incompleta.')
    if text(row[3]).casefold() != OWNER:
        return None
    titles = ' '.join(re.findall(r'title=[\"\']([^\"\']*)[\"\']', str(row[4]), re.I))
    status = (text(titles) + ' ' + text(row[4])).strip().casefold()
    if re.search(r'\b(disabled|banned|blocked|deshabilitado|bloqueado)\b', status):
        state = 'bloqueado'
    elif re.search(r'\b(expired|vencido)\b', status):
        state = 'vencido'
    elif re.search(r'\b(inactive|inactivo)\b', status):
        state = 'inactivo'
    elif re.search(r'\b(active|enabled|activo)\b', status):
        state = 'activo'
    else:
        state = 'desconocido'
    expiry = day(row[9])
    devices = None
    ratio = re.search(r'\b\d+\s*/\s*(\d+)\b', text(row[8]))
    if ratio:
        devices = number(ratio.group(1))
    elif re.fullmatch(r'\d+', text(row[8])):
        devices = number(text(row[8]))
    line_id = text(row[0])
    username = text(row[1])
    if not line_id.isdigit() or not username:
        raise XuiReportError('XUI devolvió una línea sin identificador o usuario válido.')
    return {'id': line_id, 'username': username, 'owner': OWNER,
            'expiry': expiry.isoformat() if expiry else None, 'devices': devices,
            'state': state, 'unlimited': bool(re.search(r'\b(unlimited|never|sin vencimiento)\b', text(row[9]), re.I))}


def fetch_lines(username, password, *, base_url=BASE_URL, reseller='3652', opener=None):
    """Only POST /login and GET /table; reject partial or repeated pages."""
    if not username or not password:
        raise XuiReportError('Ingresa el usuario y la contraseña del panel XUI.')
    parsed = parse.urlparse(base_url)
    if parsed.scheme not in ('http', 'https') or parsed.hostname != 'xdplustv.online' or parsed.username or parsed.password:
        raise XuiReportError('La conexión XUI debe apuntar al panel autorizado xdplustv.online.')
    base_url = base_url.rstrip('/')
    class PanelRedirects(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target = parse.urlparse(newurl)
            if target.hostname != parsed.hostname or (parsed.scheme == 'https' and target.scheme != 'https'):
                raise XuiReportError('XUI redirigió a un sitio distinto o menos seguro. Consulta detenida.')
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = opener or request.build_opener(PanelRedirects(), request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    deadline = time.monotonic() + 150
    def read(req):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise XuiReportError('XUI tardó demasiado. No se mostrará un reporte parcial; vuelve a consultar.')
        with opener.open(req, timeout=min(30, remaining)) as response:
            final = parse.urlparse(response.geturl())
            if final.hostname != parsed.hostname:
                raise XuiReportError('XUI redirigió a un sitio distinto. Consulta detenida.')
            data = response.read(12_000_001)
            if len(data) > 12_000_000:
                raise XuiReportError('La respuesta de XUI excedió el límite de seguridad.')
            return data.decode('utf-8', 'replace')
    login = parse.urlencode({'username': username, 'password': password, 'referrer': 'dashboard', 'login': 'Login'}).encode()
    try:
        read(request.Request(base_url + '/login', data=login, method='POST'))
        result, seen, start, total = [], set(), 0, None
        while total is None or start < total:
            params = {'draw': str(start // 500 + 1), 'start': str(start), 'length': '500', 'id': 'lines',
                      'filter': '', 'reseller': str(reseller), 'order[0][column]': '0',
                      'order[0][dir]': 'desc', 'search[value]': '', 'search[regex]': 'false'}
            for i in range(12):
                for key, value in {'data': str(i), 'name': '', 'searchable': 'true', 'orderable': 'true',
                                   'search][value': '', 'search][regex': 'false'}.items():
                    params[f'columns[{i}][{key}]'] = value
            payload = json.loads(read(base_url + '/table?' + parse.urlencode(params)))
            if not isinstance(payload, dict) or payload.get('error') or not isinstance(payload.get('data'), list):
                raise XuiReportError('XUI no permitió consultar las líneas. Revisa el acceso del panel.')
            count = payload.get('recordsFiltered', payload.get('recordsTotal'))
            if count is None or isinstance(count, bool):
                raise ValueError('missing count')
            count = int(count)
            if count < 0 or count > 50000 or (total is not None and count != total):
                raise XuiReportError('La lista de XUI cambió durante la consulta. Reintenta para obtener un reporte completo.')
            total = count
            batch = payload['data']
            if not batch and start < total:
                raise XuiReportError('XUI no entregó todas las páginas. No se mostrará un reporte incompleto.')
            for raw in batch:
                line = parse_line(raw)
                # Include other owners in the completeness check, never in output.
                cells = raw if isinstance(raw, list) else raw.get('value', [])
                raw_id = text(cells[0])
                if raw_id in seen:
                    raise XuiReportError('XUI repitió líneas durante la consulta. Reintenta el reporte.')
                seen.add(raw_id)
                if line:
                    result.append(line)
            start += len(batch)
            if start > total:
                raise XuiReportError('La cantidad de líneas de XUI no coincide con su total.')
        if not result:
            raise XuiReportError('XUI no devolvió líneas del owner giocarvi. Revisa el acceso antes de comparar usuarios faltantes.')
        return result
    except XuiReportError:
        raise
    except Exception:
        # Network/auth responses can include credentials; never forward them.
        raise XuiReportError('No se pudo leer XUI. Revisa las credenciales o la conexión y vuelve a consultar.') from None


def compare_clients(clients, lines, today):
    fenix, xui = defaultdict(list), defaultdict(list)
    for client in clients:
        account = str(client.get('service_username') or client['username']).strip()
        expiry = day(client.get('vencimiento'))
        archived = bool(client.get('archived_at'))
        fenix[account.casefold()].append({'username': client['username'], 'name': client.get('nombre') or client['username'],
            'service_username': account, 'expiry': expiry.isoformat() if expiry else None,
            'devices': number(client.get('devices')), 'archived': archived,
            'state': 'archivado' if archived else 'sin_fecha' if not expiry else 'activo' if expiry >= today else 'vencido'})
    for line in lines:
        if line.get('owner', '').casefold() != OWNER:
            continue
        line = dict(line)
        expiry = day(line.get('expiry'))
        if expiry and expiry < today and line['state'] not in ('bloqueado', 'inactivo'):
            line['state'] = 'vencido'
        if line['state'] == 'activo' and not expiry and not line.get('unlimited'):
            line['state'] = 'sin_fecha'
        xui[line['username'].strip().casefold()].append(line)
    rows, counts = [], defaultdict(int)
    for key in sorted(fenix.keys() | xui.keys()):
        f, x = fenix[key], xui[key]
        flags, delta = [], None
        if len(f) > 1 or len(x) > 1:
            flags.append('duplicados')
        if not f:
            flags.append('solo_xui')
        if not x:
            flags.append('solo_fenix')
        if any(item['archived'] for item in f):
            flags.append('archivados')
        if any(item['state'] == 'vencido' for item in f):
            flags.append('vencido_fenix')
        if any(item['state'] == 'vencido' for item in x):
            flags.append('vencido_xui')
        if len(f) == len(x) == 1:
            a, b = f[0], x[0]
            if a['expiry'] and b['expiry']:
                delta = (day(b['expiry']) - day(a['expiry'])).days
                if delta != 0:
                    flags.append('fechas_distintas')
                if delta < 0 and a['state'] == 'activo':
                    flags.append('falta_tiempo_xui')
                if delta > 0:
                    flags.append('tiempo_extra_xui')
            if a['state'] != b['state']:
                flags.append('estados_distintos')
            if a['state'] == 'activo' and b['state'] in ('vencido', 'bloqueado', 'inactivo'):
                flags.append('fenix_activo_xui_no')
            if a['state'] == 'vencido' and b['state'] == 'activo':
                flags.append('xui_activo_fenix_vencido')
            if a['state'] == b['state'] == 'activo':
                flags.append('activos_ambos')
            if a['state'] == b['state'] == 'vencido':
                flags.append('vencidos_ambos')
            if a['devices'] is not None and b['devices'] is not None and a['devices'] != b['devices']:
                flags.append('dispositivos_distintos')
            if a['devices'] is None or b['devices'] is None or a['state'] == 'sin_fecha' or b['state'] in ('sin_fecha', 'desconocido'):
                flags.append('datos_incompletos')
            if b.get('unlimited') and not b['expiry']:
                flags.append('sin_vencimiento_xui')
            if a['state'] == b['state'] and a['state'] in ('activo', 'vencido') and delta == 0 and a['devices'] is not None and a['devices'] == b['devices']:
                flags.append('coinciden')
        for flag in flags:
            counts[flag] += 1
        rows.append({'key': key, 'fenix': f, 'xui': x, 'flags': flags, 'difference_days': delta})
    priority = ('fenix_activo_xui_no', 'falta_tiempo_xui', 'xui_activo_fenix_vencido', 'duplicados', 'solo_xui', 'solo_fenix')
    rows.sort(key=lambda row: (min([priority.index(flag) for flag in row['flags'] if flag in priority] or [99]), row['key']))
    return {'rows': rows, 'counts': dict(counts), 'owner': OWNER, 'today': today.isoformat(),
            'generated_at': datetime.now(GT).isoformat(), 'total_fenix': sum(map(len, fenix.values())),
            'total_xui': sum(map(len, xui.values())), 'total_groups': len(rows)}
