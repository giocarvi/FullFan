import pandas as pd
import sqlite3
import os

def migrate():
    db_path = os.path.join(os.path.dirname(__file__), 'database.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.executescript('''
        CREATE TABLE IF NOT EXISTS clientes (
            username TEXT PRIMARY KEY,
            nombre TEXT,
            contacto TEXT,
            vencimiento TEXT,
            referido TEXT DEFAULT 'NO',
            total_pagado REAL DEFAULT 0,
            notas TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            mes TEXT,
            monto REAL,
            fecha_registro TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(username) REFERENCES clientes(username)
        );
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            rol TEXT DEFAULT 'atencion'
        );
    ''')

    # Admin user
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('admin','admin123','admin')")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('atencion','atencion123','atencion')")

    # Read Excel
    df = pd.read_excel('IPTV Nuevo (2).xlsx', sheet_name='Sheet1', header=None)
    headers = df.iloc[1].tolist()
    data = df.iloc[2:].copy()
    data.columns = range(len(headers))

    clients_added = 0
    payments_added = 0

    for _, row in data.iterrows():
        username = str(row[0]).strip() if pd.notna(row[0]) else None
        if not username or username == 'nan':
            continue
        name = str(row[1]).strip() if pd.notna(row[1]) else ''
        expiration = row[2]
        contact = str(row[3]).strip() if pd.notna(row[3]) else ''
        referido_raw = str(row[4]).strip().upper() if pd.notna(row[4]) else 'NO'
        referido = 'SI' if referido_raw in ('SI', 'S') else 'NO'
        total = float(row[82]) if pd.notna(row[82]) else 0

        exp_str = None
        if pd.notna(expiration):
            try:
                exp_str = pd.Timestamp(expiration).strftime('%Y-%m-%d')
            except:
                pass

        c.execute("INSERT OR IGNORE INTO clientes (username, nombre, contacto, vencimiento, referido, total_pagado) VALUES (?,?,?,?,?,?)",
                  (username, name, contact, exp_str, referido, total))
        clients_added += 1

        for col in range(5, 82):
            val = row[col]
            if pd.notna(val) and isinstance(val, (int, float)) and val > 0:
                month_date = headers[col]
                if hasattr(month_date, 'strftime'):
                    month_str = month_date.strftime('%Y-%m-%d')
                    c.execute("INSERT OR IGNORE INTO pagos (username, mes, monto) SELECT ?,?,? WHERE NOT EXISTS (SELECT 1 FROM pagos WHERE username=? AND mes=?)",
                              (username, month_str, float(val), username, month_str))
                    payments_added += 1

    conn.commit()
    conn.close()
    print(f"Migración completa: {clients_added} clientes, {payments_added} pagos")

if __name__ == '__main__':
    migrate()
