import os
import sqlite3

import psycopg2


SQLITE_DB = "complejo.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

TABLAS = [
    "usuarios",
    "inventario",
    "tarifas",
    "tarifas_cancha",
    "configuracion",
    "trabajadores",
    "tarifas_local",
    "ventas",
    "detalle_ventas",
    "detalle_creditos",
    "cocina",
    "piscina",
    "cancha",
    "reservas_local",
    "historial_cajas",
    "boletas_liberadas",
    "stock_movimientos",
    "pagos_caja",
]


def columnas_sqlite(cursor, tabla):
    cursor.execute(f"PRAGMA table_info({tabla})")
    return [fila[1] for fila in cursor.fetchall()]


def tabla_existe_sqlite(cursor, tabla):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,))
    return cursor.fetchone() is not None


def tabla_existe_postgres(cursor, tabla):
    cursor.execute("SELECT to_regclass(%s)", (tabla,))
    return cursor.fetchone()[0] is not None


def sincronizar_secuencia(cursor, tabla):
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name=%s AND column_name='id'
        """,
        (tabla,),
    )
    if not cursor.fetchone():
        return
    cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {tabla}")
    max_id = cursor.fetchone()[0] or 0
    if max_id > 0:
        cursor.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, true)", (tabla, max_id))


def migrar():
    if not DATABASE_URL:
        raise SystemExit("Configura DATABASE_URL antes de ejecutar este script.")
    if not os.path.exists(SQLITE_DB):
        raise SystemExit(f"No existe {SQLITE_DB} en esta carpeta.")

    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_cur = sqlite_conn.cursor()
    pg_conn = psycopg2.connect(DATABASE_URL)
    pg_cur = pg_conn.cursor()

    for tabla in TABLAS:
        if not tabla_existe_sqlite(sqlite_cur, tabla):
            print(f"Saltando {tabla}: no existe en SQLite.")
            continue
        if not tabla_existe_postgres(pg_cur, tabla):
            print(f"Saltando {tabla}: no existe en PostgreSQL. Abre primero la app en Streamlit Cloud para crear estructura.")
            continue

        columnas = columnas_sqlite(sqlite_cur, tabla)
        if not columnas:
            continue

        sqlite_cur.execute(f"SELECT {', '.join(columnas)} FROM {tabla}")
        filas = sqlite_cur.fetchall()
        if not filas:
            print(f"{tabla}: sin filas.")
            continue

        cols_sql = ", ".join(columnas)
        marcas = ", ".join(["%s"] * len(columnas))
        sql = f"INSERT INTO {tabla} ({cols_sql}) VALUES ({marcas}) ON CONFLICT DO NOTHING"
        pg_cur.executemany(sql, filas)
        sincronizar_secuencia(pg_cur, tabla)
        print(f"{tabla}: {len(filas)} filas enviadas.")

    pg_conn.commit()
    pg_cur.close()
    pg_conn.close()
    sqlite_conn.close()
    print("Migración terminada.")


if __name__ == "__main__":
    migrar()
