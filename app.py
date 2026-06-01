import sqlite3

DB_NAME = "complejo.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. TABLA USUARIOS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            rol TEXT
        )
    ''')
    
    # 2. TABLA INVENTARIO / STOCK
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE,
            proveedor TEXT,
            fecha_ingreso TEXT,
            costo REAL,
            precio REAL,
            stock INTEGER
        )
    ''')
    
    # 3. TABLA VENTAS (Actualizada con estado_caja e id_cierre)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT,
            total REAL,
            estado TEXT,
            fecha TEXT,
            estado_caja TEXT DEFAULT 'ABIERTO',
            id_cierre INTEGER
        )
    ''')
    
    # 4. TABLA DETALLE CRÉDITOS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS detalle_creditos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT,
            producto TEXT,
            cantidad INTEGER,
            precio_unitario REAL,
            subtotal REAL,
            fecha TEXT
        )
    ''')
    
    # 5. TABLA COCINA
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cocina (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT,
            plato TEXT,
            cantidad INTEGER,
            fecha_hora TEXT,
            estado TEXT
        )
    ''')
    
    # 6. TABLA PISCINA (Actualizada con estado_caja e id_cierre)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS piscina (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ninos INTEGER,
            adultos INTEGER,
            mayores INTEGER,
            monto_pagado REAL,
            fecha TEXT,
            estado_caja TEXT DEFAULT 'ABIERTO',
            id_cierre INTEGER
        )
    ''')
    
    # 7. TABLA RESERVAS CANCHA (Actualizada con estado_caja e id_cierre)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cancha (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT,
            fecha_reserva TEXT,
            horario TEXT,
            tipo_cancha TEXT,
            monto_total REAL,
            adelanto REAL,
            estado TEXT,
            estado_caja TEXT DEFAULT 'ABIERTO',
            id_cierre INTEGER
        )
    ''')
    
    # 8. TABLA TARIFAS PISCINA
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tarifas (
            categoria TEXT PRIMARY KEY,
            precio REAL
        )
    ''')

    # 9. TABLA TARIFAS CANCHA
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tarifas_cancha (
            tipo TEXT PRIMARY KEY,
            precio REAL
        )
    ''')
    
    # 10. TABLA HISTORIAL DE CAJAS (Nueva tabla crucial para auditoría)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historial_cajas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_cierre TEXT,
            total_vendido REAL,
            usuario_cierre TEXT
        )
    ''')
    
    # --- PARCHE DE MIGRACIÓN SEGURO ---
    # Si la base de datos ya existía, añadimos las columnas faltantes para evitar errores
    columnas_por_tabla = {
        "ventas": [("estado_caja", "TEXT DEFAULT 'ABIERTO'"), ("id_cierre", "INTEGER")],
        "piscina": [("estado_caja", "TEXT DEFAULT 'ABIERTO'"), ("id_cierre", "INTEGER")],
        "cancha": [("estado_caja", "TEXT DEFAULT 'ABIERTO'"), ("id_cierre", "INTEGER")]
    }
    
    for tabla, columnas in columnas_por_tabla.items():
        for col_nombre, col_tipo in columnas:
            try:
                cursor.execute(f"ALTER TABLE {tabla} ADD COLUMN {col_nombre} {col_tipo}")
            except sqlite3.OperationalError:
                # Si la columna ya existe, SQLite lanzará un error operativo que ignoramos de forma segura
                pass

    # --- INSERCIÓN DE DATOS INICIALES ---
    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('administrador', 'admin123', 'Administrador')")
    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('cocinero', 'cocina123', 'Cocinero')")
    
    cursor.execute("INSERT OR IGNORE INTO tarifas VALUES ('Niños', 5.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas VALUES ('Adultos', 10.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas VALUES ('Mayores', 7.0)")

    cursor.execute("INSERT OR IGNORE INTO tarifas_cancha VALUES ('Cancha Grande', 70.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_cancha VALUES ('Media Cancha', 40.0)")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("¡Base de datos estructurada con soporte completo de cierres y auditorías históricas!")
