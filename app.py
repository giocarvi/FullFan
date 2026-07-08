from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
import os
import hmac
from datetime import date, datetime, timezone, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

# Zona horaria Guatemala (UTC-6)
GT_TZ = timezone(timedelta(hours=-6))

def today_gt():
    """Fecha actual en hora Guatemala."""
    return datetime.now(GT_TZ).date()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY')
if not app.secret_key:
    raise RuntimeError('SECRET_KEY environment variable is required')

PASSWORD_HASH_PREFIXES = ('scrypt:', 'pbkdf2:', 'argon2:')

def hash_password(password):
    return generate_password_hash(password)

def is_password_hash(value):
    return isinstance(value, str) and value.startswith(PASSWORD_HASH_PREFIXES)

def verify_password(stored_password, candidate_password):
    """Acepta hashes nuevos y contraseñas legacy en texto plano durante la transición."""
    if not stored_password:
        return False
    if is_password_hash(stored_password):
        return check_password_hash(stored_password, candidate_password)
    return hmac.compare_digest(str(stored_password), str(candidate_password))

def maybe_upgrade_password_hash(cursor, username, stored_password, candidate_password):
    """Si el usuario aún tiene password legacy, lo migra a hash después de login/cambio válido."""
    if not is_password_hash(stored_password) and verify_password(stored_password, candidate_password):
        cursor.execute(qmark("UPDATE usuarios SET password=? WHERE username=?"),
                       (hash_password(candidate_password), username))

# ── BASE DE DATOS ─────────────────────────────────────────────────────────────
# Si existe DATABASE_URL (Railway PostgreSQL), lo usa.
# Si no, usa SQLite local.
DATABASE_URL = os.environ.get('DATABASE_URL', '')

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    PG = True
    # Railway a veces usa "postgres://" en vez de "postgresql://"
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        return conn

    def qmark(sql):
        """Convierte ? de SQLite a %s de PostgreSQL."""
        return sql.replace('?', '%s')
else:
    import sqlite3
    PG = False
    DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def qmark(sql):
        return sql


def fetchone(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    if PG:
        return dict(zip([d[0] for d in cursor.description], row))
    return dict(row)


def fetchall(cursor):
    rows = cursor.fetchall()
    if PG:
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


# ── INICIALIZAR DB ────────────────────────────────────────────────────────────
def init_db():
    conn = get_db()
    c = conn.cursor()

    if PG:
        c.execute('''CREATE TABLE IF NOT EXISTS clientes (
            username TEXT PRIMARY KEY,
            nombre TEXT,
            contacto TEXT,
            vencimiento TEXT,
            referido TEXT DEFAULT 'NO',
            total_pagado REAL DEFAULT 0,
            notas TEXT DEFAULT '',
            created_at TEXT DEFAULT (NOW()::text)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS pagos (
            id SERIAL PRIMARY KEY,
            username TEXT,
            mes TEXT,
            monto REAL,
            fecha_registro TEXT DEFAULT (NOW()::text)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            rol TEXT DEFAULT 'atencion'
        )''')
        default_users = [
            ('admin', os.environ.get('DEFAULT_ADMIN_PASSWORD'), 'admin'),
            ('atencion', os.environ.get('DEFAULT_ATENCION_PASSWORD'), 'atencion'),
            ('jackye', os.environ.get('DEFAULT_JACKYE_PASSWORD'), 'atencion'),
            ('ingrid', os.environ.get('DEFAULT_INGRID_PASSWORD'), 'atencion'),
            ('turcios', os.environ.get('DEFAULT_TURCIOS_PASSWORD'), 'atencion'),
        ]
        for username, password, rol in default_users:
            if not password:
                continue
            c.execute("INSERT INTO usuarios (username,password,rol) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                      (username, hash_password(password), rol))
    else:
        c.executescript('''
            CREATE TABLE IF NOT EXISTS clientes (
                username TEXT PRIMARY KEY, nombre TEXT, contacto TEXT,
                vencimiento TEXT, referido TEXT DEFAULT 'NO',
                total_pagado REAL DEFAULT 0, notas TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS pagos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT,
                mes TEXT, monto REAL,
                fecha_registro TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE,
                password TEXT, rol TEXT DEFAULT 'atencion'
            );
        ''')
        default_users = [
            ('admin', os.environ.get('DEFAULT_ADMIN_PASSWORD'), 'admin'),
            ('atencion', os.environ.get('DEFAULT_ATENCION_PASSWORD'), 'atencion'),
            ('jackye', os.environ.get('DEFAULT_JACKYE_PASSWORD'), 'atencion'),
            ('ingrid', os.environ.get('DEFAULT_INGRID_PASSWORD'), 'atencion'),
            ('turcios', os.environ.get('DEFAULT_TURCIOS_PASSWORD'), 'atencion'),
        ]
        for username, password, rol in default_users:
            if not password:
                continue
            c.execute("INSERT OR IGNORE INTO usuarios (username,password,rol) VALUES (?,?,?)",
                      (username, hash_password(password), rol))

    # Migrar: agregar columna comprobante a pagos si no existe
    if PG:
        c.execute("ALTER TABLE pagos ADD COLUMN IF NOT EXISTS comprobante TEXT DEFAULT NULL")
    else:
        try:
            c.execute("ALTER TABLE pagos ADD COLUMN comprobante TEXT DEFAULT NULL")
        except Exception:
            pass

    # Tabla de configuración
    if PG:
        c.execute('''CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT
        )''')
        defaults = [
            ('wa_prefijo', '502'),
            ('wa_saludo', 'Hola {nombre}, te saludamos de Fénix Digital TV 👋 Tu entretenimiento, sin fronteras.'),
            ('wa_recordatorio', 'Hola {nombre}, tu servicio de Fénix Digital TV vence el {fecha}. Puedes renovar antes de la fecha para evitar interrupciones. ¡Gracias! 🔥'),
            ('wa_confirmar_pago', 'Hola {nombre}, hemos recibido tu pago ✅. Tu servicio Fénix Digital TV ha sido renovado hasta el {fecha}. ¡Gracias por preferirnos! 🔥'),
            ('wa_vencido', 'Hola {nombre}, tu servicio de Fénix Digital TV ha vencido 📅. Para reactivarlo realiza tu pago y envíanos el comprobante. ¡Te esperamos! 🔥'),
        ]
        for clave, valor in defaults:
            c.execute("INSERT INTO configuracion (clave, valor) VALUES (%s, %s) ON CONFLICT DO NOTHING", (clave, valor))
    else:
        c.execute('''CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT
        )''')
        defaults = [
            ('wa_prefijo', '502'),
            ('wa_saludo', 'Hola {nombre}, te saludamos de Fénix Digital TV 👋 Tu entretenimiento, sin fronteras.'),
            ('wa_recordatorio', 'Hola {nombre}, tu servicio de Fénix Digital TV vence el {fecha}. Puedes renovar antes de la fecha para evitar interrupciones. ¡Gracias! 🔥'),
            ('wa_confirmar_pago', 'Hola {nombre}, hemos recibido tu pago ✅. Tu servicio Fénix Digital TV ha sido renovado hasta el {fecha}. ¡Gracias por preferirnos! 🔥'),
            ('wa_vencido', 'Hola {nombre}, tu servicio de Fénix Digital TV ha vencido 📅. Para reactivarlo realiza tu pago y envíanos el comprobante. ¡Te esperamos! 🔥'),
        ]
        for clave, valor in defaults:
            c.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?)", (clave, valor))

    # Rebrand suave: solo reemplaza plantillas antiguas que aún mencionen Full Fan.
    brand_updates = [
        ('wa_saludo', 'Hola {nombre}, te saludamos de Fénix Digital TV 👋 Tu entretenimiento, sin fronteras.'),
        ('wa_recordatorio', 'Hola {nombre}, tu servicio de Fénix Digital TV vence el {fecha}. Puedes renovar antes de la fecha para evitar interrupciones. ¡Gracias! 🔥'),
        ('wa_confirmar_pago', 'Hola {nombre}, hemos recibido tu pago ✅. Tu servicio Fénix Digital TV ha sido renovado hasta el {fecha}. ¡Gracias por preferirnos! 🔥'),
        ('wa_vencido', 'Hola {nombre}, tu servicio de Fénix Digital TV ha vencido 📅. Para reactivarlo realiza tu pago y envíanos el comprobante. ¡Te esperamos! 🔥'),
    ]
    for clave, valor in brand_updates:
        c.execute(qmark("UPDATE configuracion SET valor=? WHERE clave=? AND valor LIKE ?"),
                  (valor, clave, '%Full Fan%'))

    conn.commit()

    # Migrar Excel si DB está vacía
    c.execute("SELECT COUNT(*) as c FROM clientes")
    total = c.fetchone()[0] if PG else fetchone(c)['c']
    conn.close()
    if total == 0:
        _migrate_from_excel()


def _parse_excel_rows(excel_path):
    """Lee el Excel con openpyxl y devuelve (headers_row, data_rows) como listas."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 'openpyxl'])
        from openpyxl import load_workbook
    from datetime import datetime
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()
    headers = list(all_rows[1])   # fila 2 = índice 1
    data = all_rows[2:]           # desde fila 3
    return headers, data


def _cell_val(v):
    return v if v is not None else None


def _migrate_from_excel(update_existing=False):
    excel_path = os.path.join(os.path.dirname(__file__), 'IPTV Nuevo (2).xlsx')
    if not os.path.exists(excel_path):
        return 0, 0
    try:
        return _import_excel_rows(excel_path, update_existing)
    except Exception as e:
        print(f"Error migrando Excel: {e}")
        return 0, 0


def _import_excel_rows(excel_path, update_existing=False):
    from datetime import datetime as dt
    headers, data = _parse_excel_rows(excel_path)
    conn = get_db()
    c = conn.cursor()
    clients_ok = 0
    pagos_ok = 0
    for row in data:
        if not row or len(row) < 5:
            continue
        username = str(row[0]).strip() if row[0] is not None else None
        if not username or username.lower() == 'nan' or username == '':
            continue
        nombre = str(row[1]).strip() if row[1] is not None else ''
        exp_val = row[2]
        contact = str(row[3]).strip() if row[3] is not None else ''
        referido_raw = str(row[4]).strip().upper() if row[4] is not None else 'NO'
        referido = 'SI' if referido_raw in ('SI', 'S') else 'NO'
        total = float(row[82]) if len(row) > 82 and row[82] is not None else 0
        exp_str = None
        if exp_val is not None:
            try:
                if isinstance(exp_val, (dt,)):
                    exp_str = exp_val.strftime('%Y-%m-%d')
                else:
                    from datetime import datetime
                    exp_str = datetime.strptime(str(exp_val)[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
            except:
                pass
        if PG:
            if update_existing:
                c.execute("""INSERT INTO clientes (username,nombre,contacto,vencimiento,referido,total_pagado)
                             VALUES (%s,%s,%s,%s,%s,%s)
                             ON CONFLICT (username) DO UPDATE SET
                               nombre=EXCLUDED.nombre, contacto=EXCLUDED.contacto,
                               vencimiento=EXCLUDED.vencimiento, referido=EXCLUDED.referido,
                               total_pagado=EXCLUDED.total_pagado""",
                          (username, nombre, contact, exp_str, referido, total))
            else:
                c.execute("INSERT INTO clientes (username,nombre,contacto,vencimiento,referido,total_pagado) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                          (username, nombre, contact, exp_str, referido, total))
        else:
            c.execute("INSERT OR IGNORE INTO clientes (username,nombre,contacto,vencimiento,referido,total_pagado) VALUES (?,?,?,?,?,?)",
                      (username, nombre, contact, exp_str, referido, total))
        clients_ok += 1
        for col in range(5, min(82, len(row))):
            val = row[col]
            if val is not None and isinstance(val, (int, float)) and val > 0:
                month_date = headers[col] if col < len(headers) else None
                if month_date is not None and hasattr(month_date, 'strftime'):
                    month_str = month_date.strftime('%Y-%m-%d')
                    if PG:
                        c.execute("INSERT INTO pagos (username,mes,monto) SELECT %s,%s,%s WHERE NOT EXISTS (SELECT 1 FROM pagos WHERE username=%s AND mes=%s)",
                                  (username, month_str, float(val), username, month_str))
                    else:
                        ex = c.execute("SELECT 1 FROM pagos WHERE username=? AND mes=?", (username, month_str)).fetchone()
                        if not ex:
                            c.execute("INSERT INTO pagos (username,mes,monto) VALUES (?,?,?)", (username, month_str, float(val)))
                    pagos_ok += 1
    conn.commit()
    conn.close()
    print(f"Migración desde Excel completada: {clients_ok} clientes, {pagos_ok} pagos.")
    return clients_ok, pagos_ok


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── AUTH ──────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '').strip()
        db = get_db()
        c = db.cursor()
        c.execute(qmark("SELECT * FROM usuarios WHERE username=?"), (u,))
        user = fetchone(c)
        if user and verify_password(user.get('password'), p):
            maybe_upgrade_password_hash(c, u, user.get('password'), p)
            db.commit()
            db.close()
            session['user'] = u
            session['rol'] = user['rol']
            return redirect(url_for('index'))
        db.close()
        error = 'Usuario o contraseña incorrectos'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html', user=session['user'], rol=session['rol'])

# ── API: DASHBOARD ────────────────────────────────────────────────────────────
@app.route('/api/dashboard')
@login_required
def dashboard():
    db = get_db()
    c = db.cursor()
    today = today_gt().isoformat()
    in_30 = today_gt().replace(day=min(today_gt().day + 30, 28)).isoformat()
    mes_actual = today_gt().strftime('%Y-%m')

    c.execute(qmark("SELECT COUNT(*) as c FROM clientes WHERE vencimiento >= ?"), (today,))
    activos = fetchone(c)['c']

    c.execute(qmark("SELECT COUNT(*) as c FROM clientes WHERE vencimiento < ? OR vencimiento IS NULL"), (today,))
    vencidos = fetchone(c)['c']

    c.execute(qmark("SELECT COUNT(*) as c FROM clientes WHERE vencimiento >= ? AND vencimiento <= ?"), (today, in_30))
    por_vencer = fetchone(c)['c']

    c.execute(qmark("SELECT COALESCE(SUM(monto),0) as t FROM pagos WHERE mes LIKE ?"), (f'{mes_actual}%',))
    ingresos = fetchone(c)['t']

    t = today_gt()
    m6 = t.month - 6
    y6 = t.year + (m6 - 1) // 12
    m6 = ((m6 - 1) % 12) + 1
    six_ago_str = f"{y6}-{m6:02d}"
    if PG:
        c.execute("""
            SELECT TO_CHAR(mes::date, 'YYYY-MM') as m,
                   SUM(monto) as total,
                   COUNT(DISTINCT username) as clientes,
                   COUNT(*) as unidades
            FROM pagos WHERE SUBSTRING(mes,1,7) >= %s
            GROUP BY m ORDER BY m
        """, (six_ago_str,))
    else:
        c.execute("""
            SELECT strftime('%Y-%m', mes) as m,
                   SUM(monto) as total,
                   COUNT(DISTINCT username) as clientes,
                   COUNT(*) as unidades
            FROM pagos WHERE substr(mes,1,7) >= ?
            GROUP BY m ORDER BY m
        """, (six_ago_str,))
    ultimos_meses = fetchall(c)

    c.execute(qmark("""
        SELECT username, nombre, contacto, vencimiento FROM clientes
        WHERE vencimiento >= ? AND vencimiento <= ?
        ORDER BY vencimiento LIMIT 20
    """), (today, in_30))
    pronto = fetchall(c)
    db.close()

    return jsonify({
        'activos': activos, 'vencidos': vencidos, 'por_vencer': por_vencer,
        'ingresos_mes': round(float(ingresos), 2),
        'ultimos_meses': ultimos_meses,
        'por_vencer_lista': pronto
    })

# ── API: SYNC (para reporte_diario) ──────────────────────────────────────────
@app.route('/api/sync/clientes')
@login_required
def sync_clientes():
    """Devuelve todos los usernames + vencimiento de una sola vez (sin paginación).
    Solo para uso interno del reporte_diario.py."""
    db = get_db()
    c = db.cursor()
    c.execute("SELECT username, vencimiento FROM clientes ORDER BY username ASC")
    rows = fetchall(c)
    db.close()
    return jsonify({'clientes': rows, 'total': len(rows)})

# ── API: CLIENTES ─────────────────────────────────────────────────────────────
@app.route('/api/clientes')
@login_required
def clientes():
    q = request.args.get('q', '').strip()
    estado = request.args.get('estado', '')
    fecha = request.args.get('fecha', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page
    today = today_gt().isoformat()

    where, params = [], []
    if q:
        where.append("(nombre ILIKE ? OR username ILIKE ? OR contacto ILIKE ?)" if PG else
                     "(nombre LIKE ? OR username LIKE ? OR contacto LIKE ?)")
        params += [f'%{q}%', f'%{q}%', f'%{q}%']
    if fecha:
        where.append("vencimiento = ?"); params.append(fecha)
    elif estado == 'activo':
        where.append("vencimiento >= ?"); params.append(today)
    elif estado == 'vencido':
        where.append("(vencimiento < ? OR vencimiento IS NULL)"); params.append(today)
    elif estado == 'por_vencer':
        in_30 = today_gt().replace(day=min(today_gt().day + 30, 28)).isoformat()
        where.append("vencimiento >= ? AND vencimiento <= ?"); params += [today, in_30]

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    db = get_db()
    c = db.cursor()
    c.execute(qmark(f"SELECT COUNT(*) as c FROM clientes {where_sql}"), params)
    total = fetchone(c)['c']
    c.execute(qmark(f"""
        SELECT username, nombre, contacto, vencimiento, referido, total_pagado, notas
        FROM clientes {where_sql} ORDER BY vencimiento DESC, username ASC LIMIT ? OFFSET ?
    """), params + [per_page, offset])
    rows = fetchall(c)
    db.close()
    return jsonify({'total': total, 'clientes': rows})

@app.route('/api/clientes', methods=['POST'])
@login_required
def crear_cliente():
    data = request.json
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'error': 'El username es obligatorio'}), 400
    db = get_db()
    c = db.cursor()
    c.execute(qmark("SELECT username FROM clientes WHERE username=?"), (username,))
    if fetchone(c):
        db.close()
        return jsonify({'error': 'Ese username ya existe'}), 409
    c.execute(qmark("""
        INSERT INTO clientes (username, nombre, contacto, vencimiento, referido, notas, total_pagado)
        VALUES (?,?,?,?,?,?,0)
    """), (username, data.get('nombre',''), data.get('contacto',''),
           data.get('vencimiento') or None, data.get('referido','NO'), data.get('notas','')))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/clientes/<username>')
@login_required
def cliente_detalle(username):
    db = get_db()
    c = db.cursor()
    c.execute(qmark("SELECT * FROM clientes WHERE username=?"), (username,))
    cliente = fetchone(c)
    if not cliente:
        db.close()
        return jsonify({'error': 'No encontrado'}), 404

    rol = session.get('rol', 'atencion')
    # Ambos roles ven el historial de pagos reciente
    c.execute(qmark("SELECT id, mes, monto, fecha_registro, (comprobante IS NOT NULL) as has_comprobante FROM pagos WHERE username=? ORDER BY mes DESC LIMIT 24"), (username,))
    pagos = fetchall(c)
    db.close()
    return jsonify({'cliente': cliente, 'pagos': pagos, 'rol': rol})

@app.route('/api/clientes/<username>', methods=['PUT'])
@login_required
def actualizar_cliente(username):
    data = request.json
    db = get_db()
    c = db.cursor()

    # Cambio de username (solo admin)
    nuevo_username = data.get('nuevo_username', '').strip()
    if nuevo_username and nuevo_username != username:
        if session.get('rol') != 'admin':
            db.close()
            return jsonify({'error': 'Sin permiso para cambiar username'}), 403
        # Verificar que el nuevo username no exista
        c.execute(qmark("SELECT username FROM clientes WHERE username=?"), (nuevo_username,))
        if fetchone(c):
            db.close()
            return jsonify({'error': 'Ese username ya está en uso'}), 409
        # Actualizar pagos primero (FK)
        c.execute(qmark("UPDATE pagos SET username=? WHERE username=?"), (nuevo_username, username))
        # Actualizar cliente
        c.execute(qmark("UPDATE clientes SET username=? WHERE username=?"), (nuevo_username, username))
        username = nuevo_username  # usar el nuevo para el resto de campos

    fields, params = [], []
    for field in ['nombre', 'contacto', 'vencimiento', 'referido', 'notas']:
        if field in data:
            fields.append(f"{field}=?")
            params.append(data[field])
    if fields:
        params.append(username)
        c.execute(qmark(f"UPDATE clientes SET {', '.join(fields)} WHERE username=?"), params)

    db.commit()
    db.close()
    return jsonify({'ok': True, 'nuevo_username': username})

@app.route('/api/clientes/<username>', methods=['DELETE'])
@login_required
def eliminar_cliente(username):
    if session.get('rol') != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    db = get_db()
    c = db.cursor()
    c.execute(qmark("SELECT username FROM clientes WHERE username=?"), (username,))
    if not fetchone(c):
        db.close()
        return jsonify({'error': 'Cliente no encontrado'}), 404
    # Eliminar pagos asociados primero
    c.execute(qmark("DELETE FROM pagos WHERE username=?"), (username,))
    # Luego eliminar el cliente
    c.execute(qmark("DELETE FROM clientes WHERE username=?"), (username,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── API: PAGOS ────────────────────────────────────────────────────────────────
@app.route('/api/pagos', methods=['POST'])
@login_required
def registrar_pago():
    data = request.json
    username = data.get('username')
    monto = float(data.get('monto', 0))
    vencimiento_nuevo = data.get('vencimiento')
    mes = data.get('mes', today_gt().strftime('%Y-%m-01'))
    comprobante = data.get('comprobante')  # base64 data URL, optional
    if not username or monto <= 0:
        return jsonify({'error': 'Datos inválidos'}), 400
    db = get_db()
    c = db.cursor()
    c.execute(qmark("INSERT INTO pagos (username, mes, monto, comprobante) VALUES (?,?,?,?)"), (username, mes, monto, comprobante))
    c.execute(qmark("UPDATE clientes SET total_pagado = total_pagado + ?, vencimiento=? WHERE username=?"),
              (monto, vencimiento_nuevo, username))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/admin/corregir-mes', methods=['POST'])
@login_required
def corregir_mes():
    """Corrige pagos registrados con mes incorrecto (UTC vs Guatemala)."""
    if session.get('rol') != 'admin':
        return jsonify({'error': 'Sin permiso'}), 403
    data = request.json or {}
    mes_incorrecto = data.get('mes_incorrecto', '2026-05')
    mes_correcto   = data.get('mes_correcto',   '2026-04-30')
    db = get_db()
    c = db.cursor()
    # Buscar pagos con el mes incorrecto
    c.execute(qmark("SELECT id, username, monto, mes, fecha_registro FROM pagos WHERE mes LIKE ?"),
              (f'{mes_incorrecto}%',))
    pagos = fetchall(c)
    if not pagos:
        db.close()
        return jsonify({'ok': True, 'corregidos': 0, 'mensaje': 'No se encontraron pagos con ese mes'})
    ids = [p['id'] for p in pagos]
    # Corregir
    for pid in ids:
        c.execute(qmark("UPDATE pagos SET mes=? WHERE id=?"), (mes_correcto, pid))
    db.commit()
    db.close()
    return jsonify({'ok': True, 'corregidos': len(ids),
                    'pagos': [{'id': p['id'], 'username': p['username'],
                               'monto': p['monto'], 'mes_anterior': p['mes']} for p in pagos]})

@app.route('/api/pagos/<int:pago_id>', methods=['DELETE'])
@login_required
def eliminar_pago(pago_id):
    if session.get('rol') != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    db = get_db()
    c = db.cursor()
    c.execute(qmark("SELECT username, monto FROM pagos WHERE id=?"), (pago_id,))
    pago = fetchone(c)
    if not pago:
        db.close()
        return jsonify({'error': 'Pago no encontrado'}), 404
    c.execute(qmark("DELETE FROM pagos WHERE id=?"), (pago_id,))
    c.execute(qmark("""UPDATE clientes SET total_pagado =
        CASE WHEN total_pagado - ? < 0 THEN 0 ELSE total_pagado - ? END
        WHERE username=?"""), (pago['monto'], pago['monto'], pago['username']))
    db.commit()
    db.close()
    return jsonify({'ok': True, 'username': pago['username'], 'monto': pago['monto']})

@app.route('/api/pagos/<int:pago_id>/comprobante')
@login_required
def get_comprobante(pago_id):
    db = get_db()
    c = db.cursor()
    c.execute(qmark("SELECT comprobante FROM pagos WHERE id=?"), (pago_id,))
    row = fetchone(c)
    db.close()
    if not row or not row['comprobante']:
        return jsonify({'error': 'No encontrado'}), 404
    return jsonify({'comprobante': row['comprobante']})

# ── API: ANALYTICS ────────────────────────────────────────────────────────────
@app.route('/api/analytics')
@login_required
def analytics():
    if session.get('rol') != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403

    db = get_db()
    c = db.cursor()

    # Ventas mensuales (todo el tiempo)
    if PG:
        c.execute("""
            SELECT TO_CHAR(mes::date, 'YYYY-MM') as m,
                   SUM(monto) as total, COUNT(*) as n_pagos,
                   COUNT(DISTINCT username) as clientes
            FROM pagos GROUP BY m ORDER BY m
        """)
    else:
        c.execute("""
            SELECT strftime('%Y-%m', mes) as m,
                   SUM(monto) as total, COUNT(*) as n_pagos,
                   COUNT(DISTINCT username) as clientes
            FROM pagos GROUP BY m ORDER BY m
        """)
    ventas_mensuales = fetchall(c)

    # Ventas anuales
    if PG:
        c.execute("""
            SELECT TO_CHAR(mes::date, 'YYYY') as y,
                   SUM(monto) as total, COUNT(DISTINCT username) as clientes
            FROM pagos GROUP BY y ORDER BY y
        """)
    else:
        c.execute("""
            SELECT strftime('%Y', mes) as y,
                   SUM(monto) as total, COUNT(DISTINCT username) as clientes
            FROM pagos GROUP BY y ORDER BY y
        """)
    ventas_anuales = fetchall(c)

    # Distribución por tipo de plan (según monto del pago)
    if PG:
        c.execute("""
            SELECT
                CASE
                    WHEN monto <= 120  THEN 'Mensual'
                    WHEN monto <= 320  THEN 'Trimestral'
                    WHEN monto <= 650  THEN 'Semestral'
                    WHEN monto <= 1300 THEN 'Anual'
                    ELSE 'Más de 1 año'
                END as plan,
                COUNT(*) as n, SUM(monto) as total
            FROM pagos GROUP BY plan ORDER BY n DESC
        """)
    else:
        c.execute("""
            SELECT
                CASE
                    WHEN monto <= 120  THEN 'Mensual'
                    WHEN monto <= 320  THEN 'Trimestral'
                    WHEN monto <= 650  THEN 'Semestral'
                    WHEN monto <= 1300 THEN 'Anual'
                    ELSE 'Más de 1 año'
                END as plan,
                COUNT(*) as n, SUM(monto) as total
            FROM pagos GROUP BY plan ORDER BY n DESC
        """)
    planes = fetchall(c)

    # Clientes nuevos por mes (primer pago de cada usuario)
    if PG:
        c.execute("""
            SELECT TO_CHAR(p.mes::date, 'YYYY-MM') as m, COUNT(*) as nuevos
            FROM pagos p
            WHERE p.mes = (SELECT MIN(p2.mes) FROM pagos p2 WHERE p2.username = p.username)
            GROUP BY m ORDER BY m
        """)
    else:
        c.execute("""
            SELECT strftime('%Y-%m', p.mes) as m, COUNT(*) as nuevos
            FROM pagos p
            WHERE p.mes = (SELECT MIN(p2.mes) FROM pagos p2 WHERE p2.username = p.username)
            GROUP BY m ORDER BY m
        """)
    nuevos_por_mes = fetchall(c)

    # Renovaciones por mes (pagos que NO son el primero del usuario)
    if PG:
        c.execute("""
            SELECT TO_CHAR(p.mes::date, 'YYYY-MM') as m, COUNT(*) as renovaciones
            FROM pagos p
            WHERE p.mes != (SELECT MIN(p2.mes) FROM pagos p2 WHERE p2.username = p.username)
            GROUP BY m ORDER BY m
        """)
    else:
        c.execute("""
            SELECT strftime('%Y-%m', p.mes) as m, COUNT(*) as renovaciones
            FROM pagos p
            WHERE p.mes != (SELECT MIN(p2.mes) FROM pagos p2 WHERE p2.username = p.username)
            GROUP BY m ORDER BY m
        """)
    renovaciones_por_mes = fetchall(c)

    # Clientes que no renovaron (vencidos con pagos históricos)
    today = today_gt().isoformat()
    c.execute(qmark("SELECT COUNT(*) as c FROM clientes WHERE (vencimiento < ? OR vencimiento IS NULL) AND total_pagado > 0"), (today,))
    no_renovaron = fetchone(c)['c']

    # Total histórico
    c.execute("SELECT COALESCE(SUM(monto),0) as t FROM pagos")
    total_historico = round(float(fetchone(c)['t']), 2)

    c.execute("SELECT COUNT(*) as c FROM clientes")
    total_clientes = fetchone(c)['c']

    # Ventas por día (últimos 60 días)
    mes_actual = today_gt().strftime('%Y-%m')
    mes_anterior = (today_gt().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    if PG:
        c.execute("""
            SELECT TO_CHAR(mes::date, 'YYYY-MM-DD') as dia,
                   SUM(monto) as total, COUNT(*) as n_pagos
            FROM pagos
            WHERE SUBSTRING(mes,1,7) IN (%s, %s)
            GROUP BY dia ORDER BY dia
        """, (mes_actual, mes_anterior))
    else:
        c.execute("""
            SELECT strftime('%Y-%m-%d', mes) as dia,
                   SUM(monto) as total, COUNT(*) as n_pagos
            FROM pagos
            WHERE substr(mes,1,7) IN (?, ?)
            GROUP BY dia ORDER BY dia
        """, (mes_actual, mes_anterior))
    ventas_por_dia = fetchall(c)

    db.close()

    return jsonify({
        'ventas_mensuales': ventas_mensuales,
        'ventas_anuales': ventas_anuales,
        'planes': planes,
        'nuevos_por_mes': nuevos_por_mes,
        'renovaciones_por_mes': renovaciones_por_mes,
        'no_renovaron': no_renovaron,
        'total_historico': total_historico,
        'total_clientes': total_clientes,
        'ventas_por_dia': ventas_por_dia
    })


# ── CLIENTES NUEVOS POR RANGO ─────────────────────────────────────────────────
@app.route('/api/admin/clientes-nuevos')
@login_required
def clientes_nuevos():
    if session.get('rol') != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    if not desde or not hasta:
        return jsonify({'error': 'Parámetros desde y hasta requeridos'}), 400
    db = get_db()
    c = db.cursor()
    if PG:
        c.execute("""
            SELECT cl.username, cl.nombre, cl.contacto, cl.vencimiento,
                   cl.total_pagado, cl.created_at,
                   COUNT(p.id) as num_pagos,
                   MAX(p.mes) as ultimo_pago
            FROM clientes cl
            LEFT JOIN pagos p ON p.username = cl.username
            WHERE SUBSTRING(cl.created_at, 1, 10) >= %s
              AND SUBSTRING(cl.created_at, 1, 10) <= %s
            GROUP BY cl.username, cl.nombre, cl.contacto,
                     cl.vencimiento, cl.total_pagado, cl.created_at
            ORDER BY cl.created_at ASC
        """, (desde, hasta))
    else:
        c.execute("""
            SELECT cl.username, cl.nombre, cl.contacto, cl.vencimiento,
                   cl.total_pagado, cl.created_at,
                   COUNT(p.id) as num_pagos,
                   MAX(p.mes) as ultimo_pago
            FROM clientes cl
            LEFT JOIN pagos p ON p.username = cl.username
            WHERE substr(cl.created_at, 1, 10) >= ?
              AND substr(cl.created_at, 1, 10) <= ?
            GROUP BY cl.username, cl.nombre, cl.contacto,
                     cl.vencimiento, cl.total_pagado, cl.created_at
            ORDER BY cl.created_at ASC
        """, (desde, hasta))
    rows = fetchall(c)
    db.close()
    return jsonify({'clientes': rows, 'total': len(rows), 'desde': desde, 'hasta': hasta})

# ── EXPORTAR CLIENTES (datos JSON para generar Excel en el frontend) ──────────
@app.route('/api/admin/exportar-clientes')
@login_required
def exportar_clientes():
    if session.get('rol') != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    db = get_db()
    c = db.cursor()
    if PG:
        c.execute("""
            SELECT cl.username, cl.nombre, cl.contacto, cl.vencimiento,
                   cl.total_pagado,
                   MAX(p.mes) as ultimo_pago,
                   COUNT(p.id) as num_pagos
            FROM clientes cl
            LEFT JOIN pagos p ON p.username = cl.username
            GROUP BY cl.username, cl.nombre, cl.contacto, cl.vencimiento, cl.total_pagado
            ORDER BY cl.vencimiento DESC NULLS LAST, cl.username ASC
        """)
    else:
        c.execute("""
            SELECT cl.username, cl.nombre, cl.contacto, cl.vencimiento,
                   cl.total_pagado,
                   MAX(p.mes) as ultimo_pago,
                   COUNT(p.id) as num_pagos
            FROM clientes cl
            LEFT JOIN pagos p ON p.username = cl.username
            GROUP BY cl.username, cl.nombre, cl.contacto, cl.vencimiento, cl.total_pagado
            ORDER BY CASE WHEN cl.vencimiento IS NULL THEN 1 ELSE 0 END,
                     cl.vencimiento DESC, cl.username ASC
        """)
    rows = fetchall(c)
    db.close()
    return jsonify({'clientes': rows})

# ── CONFIGURACIÓN ─────────────────────────────────────────────────────────────
@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT clave, valor FROM configuracion")
    rows = fetchall(c)
    db.close()
    return jsonify({r['clave']: r['valor'] for r in rows})


@app.route('/api/config', methods=['POST'])
@login_required
def save_config():
    if session.get('rol') != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    data = request.get_json()
    db = get_db()
    c = db.cursor()
    for clave, valor in data.items():
        if PG:
            c.execute(
                "INSERT INTO configuracion (clave, valor) VALUES (%s, %s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
                (clave, valor)
            )
        else:
            c.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (clave, valor))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/cambiar-password', methods=['POST'])
@login_required
def cambiar_password():
    data = request.json
    password_actual = data.get('password_actual', '')
    password_nueva = data.get('password_nueva', '')
    if not password_actual or not password_nueva or len(password_nueva) < 4:
        return jsonify({'error': 'Datos inválidos. La nueva contraseña debe tener al menos 4 caracteres.'}), 400
    username = session['user']
    db = get_db()
    c = db.cursor()
    c.execute(qmark("SELECT id, password FROM usuarios WHERE username=?"), (username,))
    user = fetchone(c)
    if not user or not verify_password(user.get('password'), password_actual):
        db.close()
        return jsonify({'error': 'La contraseña actual es incorrecta.'}), 403
    c.execute(qmark("UPDATE usuarios SET password=? WHERE username=?"), (hash_password(password_nueva), username))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/admin/reimportar-excel', methods=['POST'])
@login_required
def reimportar_excel():
    if session.get('rol') != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    import tempfile
    usar_tmp = False
    if 'archivo' in request.files:
        f = request.files['archivo']
        suffix = '.xlsx' if f.filename.lower().endswith('.xlsx') else '.xls'
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        f.save(tmp.name)
        excel_path = tmp.name
        usar_tmp = True
    else:
        excel_path = os.path.join(os.path.dirname(__file__), 'IPTV Nuevo (2).xlsx')
    if not os.path.exists(excel_path):
        return jsonify({'ok': False, 'error': 'Excel no encontrado. Sube el archivo directamente.'})
    try:
        clientes, pagos = _import_excel_rows(excel_path, update_existing=True)
        return jsonify({'ok': True, 'clientes_actualizados': clientes, 'pagos_procesados': pagos})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})
    finally:
        if usar_tmp and os.path.exists(excel_path):
            os.unlink(excel_path)


@app.route('/api/diagnostico')
@login_required
def diagnostico():
    if session.get('rol') != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    db = get_db()
    c = db.cursor()
    # Total pagos
    c.execute("SELECT COUNT(*) as total FROM pagos")
    total = fetchone(c)['total']
    # Últimos 10 pagos registrados
    c.execute(qmark("SELECT id, username, mes, monto, fecha_registro FROM pagos ORDER BY id DESC LIMIT 10"))
    ultimos = fetchall(c)
    # Tablas existentes
    if PG:
        c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    else:
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tablas = [r[0] for r in c.fetchall()]
    db.close()
    return jsonify({'total_pagos': total, 'ultimos_pagos': ultimos, 'tablas': tablas})


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
