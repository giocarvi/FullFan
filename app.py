from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
from datetime import date
from functools import wraps

app = Flask(__name__)
app.secret_key = 'fullfan_secret_2026'

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
        c.execute("INSERT INTO usuarios (username,password,rol) VALUES ('admin','admin123','admin') ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO usuarios (username,password,rol) VALUES ('atencion','atencion123','atencion') ON CONFLICT DO NOTHING")
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
        c.execute("INSERT OR IGNORE INTO usuarios (username,password,rol) VALUES ('admin','admin123','admin')")
        c.execute("INSERT OR IGNORE INTO usuarios (username,password,rol) VALUES ('atencion','atencion123','atencion')")

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
            ('wa_saludo', 'Hola {nombre}, te saludamos de Full Fan Digital TV 👋'),
            ('wa_recordatorio', 'Hola {nombre}, tu servicio de Full Fan Digital TV vence el {fecha}. Para renovar escríbenos o realiza tu pago. ¡Gracias! 📺'),
            ('wa_confirmar_pago', 'Hola {nombre}, hemos recibido tu pago ✅. Tu servicio ha sido renovado hasta el {fecha}. ¡Gracias por preferirnos! 📺'),
            ('wa_vencido', 'Hola {nombre}, tu servicio de Full Fan Digital TV ha vencido 📅. Para reactivarlo realiza tu pago y envíanos el comprobante. ¡Te esperamos! 💜'),
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
            ('wa_saludo', 'Hola {nombre}, te saludamos de Full Fan Digital TV 👋'),
            ('wa_recordatorio', 'Hola {nombre}, tu servicio de Full Fan Digital TV vence el {fecha}. Para renovar escríbenos o realiza tu pago. ¡Gracias! 📺'),
            ('wa_confirmar_pago', 'Hola {nombre}, hemos recibido tu pago ✅. Tu servicio ha sido renovado hasta el {fecha}. ¡Gracias por preferirnos! 📺'),
            ('wa_vencido', 'Hola {nombre}, tu servicio de Full Fan Digital TV ha vencido 📅. Para reactivarlo realiza tu pago y envíanos el comprobante. ¡Te esperamos! 💜'),
        ]
        for clave, valor in defaults:
            c.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?)", (clave, valor))

    conn.commit()

    # Migrar Excel si DB está vacía
    c.execute("SELECT COUNT(*) as c FROM clientes")
    total = c.fetchone()[0] if PG else fetchone(c)['c']
    conn.close()
    if total == 0:
        _migrate_from_excel()

def _migrate_from_excel():
    excel_path = os.path.join(os.path.dirname(__file__), 'IPTV Nuevo (2).xlsx')
    if not os.path.exists(excel_path):
        return
    try:
        import pandas as pd
        df = pd.read_excel(excel_path, sheet_name='Sheet1', header=None)
        headers = df.iloc[1].tolist()
        data = df.iloc[2:].copy()
        data.columns = range(len(headers))
        conn = get_db()
        c = conn.cursor()
        for _, row in data.iterrows():
            username = str(row[0]).strip() if pd.notna(row[0]) else None
            if not username or username == 'nan':
                continue
            nombre = str(row[1]).strip() if pd.notna(row[1]) else ''
            contact = str(row[3]).strip() if pd.notna(row[3]) else ''
            referido_raw = str(row[4]).strip().upper() if pd.notna(row[4]) else 'NO'
            referido = 'SI' if referido_raw in ('SI', 'S') else 'NO'
            total = float(row[82]) if pd.notna(row[82]) else 0
            exp_str = None
            if pd.notna(row[2]):
                try:
                    exp_str = pd.Timestamp(row[2]).strftime('%Y-%m-%d')
                except:
                    pass
            if PG:
                c.execute("INSERT INTO clientes (username,nombre,contacto,vencimiento,referido,total_pagado) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                          (username, nombre, contact, exp_str, referido, total))
            else:
                c.execute("INSERT OR IGNORE INTO clientes (username,nombre,contacto,vencimiento,referido,total_pagado) VALUES (?,?,?,?,?,?)",
                          (username, nombre, contact, exp_str, referido, total))
            for col in range(5, 82):
                val = row[col]
                if pd.notna(val) and isinstance(val, (int, float)) and val > 0:
                    month_date = headers[col]
                    if hasattr(month_date, 'strftime'):
                        month_str = month_date.strftime('%Y-%m-%d')
                        if PG:
                            c.execute("INSERT INTO pagos (username,mes,monto) SELECT %s,%s,%s WHERE NOT EXISTS (SELECT 1 FROM pagos WHERE username=%s AND mes=%s)",
                                      (username, month_str, float(val), username, month_str))
                        else:
                            ex = c.execute("SELECT 1 FROM pagos WHERE username=? AND mes=?", (username, month_str)).fetchone()
                            if not ex:
                                c.execute("INSERT INTO pagos (username,mes,monto) VALUES (?,?,?)", (username, month_str, float(val)))
        conn.commit()
        conn.close()
        print("Migración desde Excel completada.")
    except Exception as e:
        print(f"Error migrando Excel: {e}")


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
        c.execute(qmark("SELECT * FROM usuarios WHERE username=? AND password=?"), (u, p))
        user = fetchone(c)
        db.close()
        if user:
            session['user'] = u
            session['rol'] = user['rol']
            return redirect(url_for('index'))
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
    today = date.today().isoformat()
    in_30 = date.today().replace(day=min(date.today().day + 30, 28)).isoformat()
    mes_actual = date.today().strftime('%Y-%m')

    c.execute(qmark("SELECT COUNT(*) as c FROM clientes WHERE vencimiento >= ?"), (today,))
    activos = fetchone(c)['c']

    c.execute(qmark("SELECT COUNT(*) as c FROM clientes WHERE vencimiento < ? OR vencimiento IS NULL"), (today,))
    vencidos = fetchone(c)['c']

    c.execute(qmark("SELECT COUNT(*) as c FROM clientes WHERE vencimiento >= ? AND vencimiento <= ?"), (today, in_30))
    por_vencer = fetchone(c)['c']

    c.execute(qmark("SELECT COALESCE(SUM(monto),0) as t FROM pagos WHERE mes LIKE ?"), (f'{mes_actual}%',))
    ingresos = fetchone(c)['t']

    if PG:
        c.execute("""
            SELECT TO_CHAR(mes::date, 'YYYY-MM') as m, SUM(monto) as total, COUNT(DISTINCT username) as clientes
            FROM pagos WHERE mes::date >= NOW() - INTERVAL '6 months'
            GROUP BY m ORDER BY m
        """)
    else:
        c.execute("""
            SELECT strftime('%Y-%m', mes) as m, SUM(monto) as total, COUNT(DISTINCT username) as clientes
            FROM pagos WHERE mes >= date('now', '-6 months')
            GROUP BY m ORDER BY m
        """)
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
    today = date.today().isoformat()

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
        in_30 = date.today().replace(day=min(date.today().day + 30, 28)).isoformat()
        where.append("vencimiento >= ? AND vencimiento <= ?"); params += [today, in_30]

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    db = get_db()
    c = db.cursor()
    c.execute(qmark(f"SELECT COUNT(*) as c FROM clientes {where_sql}"), params)
    total = fetchone(c)['c']
    c.execute(qmark(f"""
        SELECT username, nombre, contacto, vencimiento, referido, total_pagado, notas
        FROM clientes {where_sql} ORDER BY vencimiento DESC LIMIT ? OFFSET ?
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
    return jsonify({'ok': True})

# ── API: PAGOS ────────────────────────────────────────────────────────────────
@app.route('/api/pagos', methods=['POST'])
@login_required
def registrar_pago():
    data = request.json
    username = data.get('username')
    monto = float(data.get('monto', 0))
    vencimiento_nuevo = data.get('vencimiento')
    mes = data.get('mes', date.today().strftime('%Y-%m-01'))
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
    today = date.today().isoformat()
    c.execute(qmark("SELECT COUNT(*) as c FROM clientes WHERE (vencimiento < ? OR vencimiento IS NULL) AND total_pagado > 0"), (today,))
    no_renovaron = fetchone(c)['c']

    # Total histórico
    c.execute("SELECT COALESCE(SUM(monto),0) as t FROM pagos")
    total_historico = round(float(fetchone(c)['t']), 2)

    c.execute("SELECT COUNT(*) as c FROM clientes")
    total_clientes = fetchone(c)['c']

    db.close()

    return jsonify({
        'ventas_mensuales': ventas_mensuales,
        'ventas_anuales': ventas_anuales,
        'planes': planes,
        'nuevos_por_mes': nuevos_por_mes,
        'renovaciones_por_mes': renovaciones_por_mes,
        'no_renovaron': no_renovaron,
        'total_historico': total_historico,
        'total_clientes': total_clientes
    })


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


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
