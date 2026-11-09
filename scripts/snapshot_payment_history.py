"""Read-only verification of historical rows before/after a deployment.

This produces hashes, NOT a database backup. Take a restorable backup separately.
Use DATABASE_URL for Postgres, or explicitly pass --sqlite-file for a local copy.
"""
import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

TABLES=('clientes','pagos','client_service_credentials','client_portal_accounts',
        'orders','activation_tasks','smartone_records','smartone_inventory','audit_log','maxplayer_cleanup_operations')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str,
                                     separators=(',',':')).encode('utf-8')).hexdigest()


def capture(conn, postgres=False, baseline=None):
    tables={}
    for table in TABLES:
        cursor=conn.cursor()
        if postgres:
            cursor.execute('SELECT to_regclass(%s)',('public.'+table,))
            exists=cursor.fetchone()[0] is not None
        else:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,))
            exists=cursor.fetchone() is not None
        if not exists:
            continue
        cursor.execute(f'SELECT * FROM "{table}" LIMIT 0')
        available=[d[0] for d in cursor.description]
        previous=(baseline or {}).get('tables',{}).get(table)
        columns=previous['columns'] if previous else available
        if not set(columns).issubset(available):
            raise ValueError(f'Faltan columnas históricas en {table}')
        if postgres:
            cursor.execute('''SELECT k.column_name FROM information_schema.table_constraints t
                JOIN information_schema.key_column_usage k ON k.constraint_name=t.constraint_name
                AND k.table_schema=t.table_schema AND k.table_name=t.table_name
                WHERE t.table_schema='public' AND t.table_name=%s AND t.constraint_type='PRIMARY KEY'
                ORDER BY k.ordinal_position''',(table,))
            keys=[r[0] for r in cursor.fetchall()]
        else:
            cursor.execute(f'PRAGMA table_info("{table}")')
            keys=[r[1] for r in sorted(cursor.fetchall(),key=lambda r:r[5]) if r[5]]
        keys=previous['keys'] if previous else keys
        quoted=','.join('"'+c.replace('"','""')+'"' for c in columns)
        cursor.execute(f'SELECT {quoted} FROM "{table}"')
        records={}
        for values in cursor:
            row=dict(zip(columns,values))
            row_hash=digest(row)
            key_hash=digest([row[k] for k in keys]) if keys else row_hash
            if keys:records[key_hash]=row_hash
            else:records[key_hash]=records.get(key_hash,0)+1
        tables[table]={'columns':columns,'keys':keys,'records':records}
    return {'created_at':datetime.now(timezone.utc).isoformat(),'tables':tables}


def compare(before,after):
    result={}
    for name,table in before['tables'].items():
        original=table['records'];current=after['tables'].get(name,{}).get('records',{})
        result[name]={'originales':len(original),
                      'faltantes':sum(k not in current for k in original),
                      'modificados':sum(k in current and current[k]!=v for k,v in original.items()),
                      'nuevos':sum(k not in original for k in current)}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output',type=Path)
    group.add_argument('--compare',type=Path)
    parser.add_argument('--sqlite-file',type=Path)
    args=parser.parse_args()
    url=os.environ.get('DATABASE_URL','')
    if args.sqlite_file:
        conn=sqlite3.connect('file:'+quote(args.sqlite_file.resolve().as_posix(),safe='/:')+'?mode=ro',uri=True)
        postgres=False
    elif url.startswith(('postgres://','postgresql://')):
        import psycopg2
        conn=psycopg2.connect(url,connect_timeout=10)
        conn.set_session(readonly=True,isolation_level='REPEATABLE READ')
        postgres=True
    else:
        parser.error('Configura DATABASE_URL de Postgres o indica --sqlite-file. No se elige una base por defecto.')
    try:
        baseline=json.loads(args.compare.read_text(encoding='utf-8')) if args.compare else None
        snapshot=capture(conn,postgres,baseline)
    finally:conn.close()
    if args.output:
        if args.output.exists():parser.error('El archivo de referencia ya existe; usa otro nombre para conservarlo.')
        args.output.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Referencia guardada. No se modificó la base de datos.')
    else:
        result=compare(baseline,snapshot)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if any(r['faltantes'] or r['modificados'] for r in result.values()):
            print('Hay diferencias que revisar. No se modifica ni revierte ningún dato automáticamente.')
            return 1
        print('Todos los registros de referencia permanecen intactos. Los nuevos se informan por separado.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
