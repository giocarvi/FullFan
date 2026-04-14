from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import os
from datetime import datetime, date
from functools import wraps

app = Flask(__name__)
app.secret_key = 'iptv_secret_key_2026'
DB = os.path.join(os.path.dirname(__file__), 'database.db')

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── AUTH ────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '').strip()
        db = get_db()
        user = db.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
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

# ── MAIN ─────────────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    return render_template('index.html', user=session['user'], rol=session['rol'])

# ── API: DASHBOARD ────────────────────────────────────────────────────────────
@app.route('/api/dashboard')
@login_required
def dashboard():
    db = get_db()
    today = date.today().isoformat()
    in_30 = date.today().replace(day=min(date.today().day + 30, 28))

    activos = db.execute("SELECT COUNT(*) as c FROM clientes WHERE vencimiento >= ?", (today,)).fetchone()['c']
    vencidos = db.execute("SELECT COUNT(*) as c FROM clientes WHERE vencimiento < ? OR vencimiento IS NULL", (today,)).fetchone()['c']
    por_vencer = db.execute("SELECT COUNT(*) as c FROM clientes WHERE vencimiento >= ? AND vencimiento <= ?", (today, in_30.isoformat())).fetchone()['c']

    # revenue this month
    mes_actual = date.today().strftime('%Y-%m')
    ingresos = db.execute("SELECT COALESCE(SUM(monto),0) as t FROM pagos WHERE mes LIKE ?", (f'{mes_actual}%',)).fetchone()['t']

    # last 6 months revenue
    ultimos_meses = db.execute("""
        SELECT strftime('%Y-%m', mes) as m, SUM(monto) as total, COUNT(DISTINCT username) as clientes
        FROM pagos
        WHERE mes >= date('now', '-6 months')
        GROUP BY m ORDER BY m
    """).fetchall()

    # expiring soon list
    pronto = db.execute("""
        SELECT username, nombre, contacto, vencimiento
        FROM clientes WHERE vencimiento >= ? AND vencimiento <= ?
        ORDER BY vencimiento LIMIT 20
    """, (today, in_30.isoformat())).fetchall()

    db.close()
    return jsonify({
        'activos': activos,
        'vencidos': vencidos,
        'por_vencer': por_vencer,
        'ingresos_mes': round(ingresos, 2),
        'ultimos_meses': [dict(r) for r in ultimos_meses],
        'por_vencer_lista': [dict(r) for r in pronto]
    })

# ── API: CLIENTES ─────────────────────────────────────────────────────────────
@app.route('/api/clientes')
@login_required
def clientes():
    q = request.args.get('q', '').strip()
    estado = request.args.get('estado', '')
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page
    today = date.today().isoformat()

    where = []
    params = []

    if q:
        where.append("(nombre LIKE ? OR username LIKE ? OR contacto LIKE ?)")
        params += [f'%{q}%', f'%{q}%', f'%{q}%']

    if estado == 'activo':
        where.append("vencimiento >= ?")
        params.append(today)
    elif estado == 'vencido':
        where.append("(vencimiento < ? OR vencimiento IS NULL)")
        params.append(today)
    elif estado == 'por_vencer':
        in_30 = date.today().replace(day=min(date.today().day + 30, 28)).isoformat()
        where.append("vencimiento >= ? AND vencimiento <= ?")
        params += [today, in_30]

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) as c FROM clientes {where_sql}", params).fetchone()['c']
    rows = db.execute(f"""
        SELECT username, nombre, contacto, vencimiento, referido, total_pagado, notas
        FROM clientes {where_sql}
        ORDER BY vencimiento DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, offset]).fetchall()
    db.close()
    return jsonify({'total': total, 'clientes': [dict(r) for r in rows]})

@app.route('/api/clientes/<username>')
@login_required
def cliente_detalle(username):
    db = get_db()
    c = db.execute("SELECT * FROM clientes WHERE username=?", (username,)).fetchone()
    if not c:
        db.close()
        return jsonify({'error': 'No encontrado'}), 404
    pagos = db.execute("""
        SELECT mes, monto, fecha_registro FROM pagos
        WHERE username=? ORDER BY mes DESC LIMIT 24
    """, (username,)).fetchall()
    db.close()
    return jsonify({'cliente': dict(c), 'pagos': [dict(p) for p in pagos]})

@app.route('/api/clientes/<username>', methods=['PUT'])
@login_required
def actualizar_cliente(username):
    data = request.json
    db = get_db()
    db.execute("""
        UPDATE clientes SET nombre=?, contacto=?, vencimiento=?, referido=?, notas=?
        WHERE username=?
    """, (data.get('nombre'), data.get('contacto'), data.get('vencimiento'),
          data.get('referido'), data.get('notas'), username))
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

    if not username or monto <= 0:
        return jsonify({'error': 'Datos inválidos'}), 400

    db = get_db()
    db.execute("INSERT INTO pagos (username, mes, monto) VALUES (?,?,?)", (username, mes, monto))
    db.execute("UPDATE clientes SET total_pagado = total_pagado + ?, vencimiento=? WHERE username=?",
               (monto, vencimiento_nuevo, username))
    db.commit()
    db.close()
    return jsonify({'ok': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
