import streamlit as st
import pandas as pd
import sqlite3
import secrets
import base64
import mimetypes
import shutil
import zipfile
import ast
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import streamlit.components.v1 as components

# Configuración de página
st.set_page_config(page_title="Complejo Recreativo Las Marías", layout="wide", page_icon="🏊‍♂️", initial_sidebar_state="expanded")

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = str(BASE_DIR / "complejo.db")
ASSETS_DIR = BASE_DIR / "assets"
BACKUP_DIR = BASE_DIR / "backups"
METODOS_PAGO = ["Efectivo", "Tarjeta", "Yape José Luis", "Yape Sofia", "PLIN"]
METODOS_RECAUDADOR = {"Yape José Luis", "Yape Sofia", "PLIN"}
ZONA_HORARIA_SISTEMA = ZoneInfo("America/Lima")

def ahora_windows():
    return datetime.now(ZONA_HORARIA_SISTEMA)

def fecha_hoy_local():
    return ahora_windows().date()

def fecha_hora_actual():
    return ahora_windows().strftime('%Y-%m-%d %H:%M')

def fecha_ticket_actual():
    return ahora_windows().strftime('%d/%m/%Y %H:%M')

# --- MIGRACIÓN AUTOMÁTICA E INICIALIZACIÓN DE LA BASE DE DATOS ---
def asegurar_estructura_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, rol TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, proveedor TEXT, fecha_ingreso TEXT, costo REAL, precio REAL, stock INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_creditos (id INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT, producto TEXT, cantidad INTEGER, precio_unitario REAL, subtotal REAL, fecha TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS cocina (id INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT, plato TEXT, cantidad INTEGER, fecha_hora TEXT, estado TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS tarifas (categoria TEXT PRIMARY KEY, precio REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS tarifas_cancha (tipo TEXT PRIMARY KEY, precio REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trabajadores (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, rol TEXT, asistio_hoy TEXT DEFAULT 'SI', activo INTEGER DEFAULT 1)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS tarifas_local (area TEXT PRIMARY KEY, precio REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS reservas_local (id INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT, area TEXT, fecha_reserva TEXT, horario TEXT, monto_total REAL, estado TEXT, metodo_pago TEXT, receptor_tipo TEXT, receptor_nombre TEXT, trabajador TEXT, estado_caja TEXT DEFAULT 'ABIERTO', id_cierre INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS boletas_liberadas (id INTEGER PRIMARY KEY AUTOINCREMENT, venta_id INTEGER, cliente TEXT, total REAL, items TEXT, fecha_liberacion TEXT, estado TEXT DEFAULT 'LIBERADA')''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS stock_movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, inventario_id INTEGER, producto TEXT, tipo TEXT, cantidad INTEGER, stock_anterior INTEGER, stock_nuevo INTEGER, fecha TEXT, usuario TEXT, motivo TEXT)''')
    
    # Tabla piscina con estado_caja para permitir el reinicio correcto en los cierres
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS piscina (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            ninos INTEGER, 
            adultos INTEGER, 
            mayores INTEGER, 
            monto_pagado REAL, 
            fecha TEXT,
            estado_caja TEXT DEFAULT 'ABIERTO'
        )
    ''')
    
    # Tabla ventas consolidada con estado_caja
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            cliente TEXT, 
            total REAL, 
            estado TEXT, 
            fecha TEXT,
            estado_caja TEXT DEFAULT 'ABIERTO'
        )
    ''')
    
    # Detalle de las ventas realizadas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS detalle_ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER,
            producto TEXT,
            cantidad INTEGER,
            precio_unitario REAL,
            subtotal REAL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historial_cajas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_cierre TEXT,
            total_vendido REAL,
            usuario_cierre TEXT
        )
    ''')
    
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
            estado_caja TEXT DEFAULT 'ABIERTO'
        )
    ''')
    
    # Verificaciones de actualización de columnas (MIGRACIÓN EN CALIENTE)
    cursor.execute("PRAGMA table_info(piscina)")
    if "estado_caja" not in [col[1] for col in cursor.fetchall()]:
        try: cursor.execute("ALTER TABLE piscina ADD COLUMN estado_caja TEXT DEFAULT 'ABIERTO'")
        except: pass

    cursor.execute("PRAGMA table_info(ventas)")
    if "estado_caja" not in [col[1] for col in cursor.fetchall()]:
        try: cursor.execute("ALTER TABLE ventas ADD COLUMN estado_caja TEXT DEFAULT 'ABIERTO'")
        except: pass

    cursor.execute("PRAGMA table_info(cancha)")
    if "estado_caja" not in [col[1] for col in cursor.fetchall()]:
        try: cursor.execute("ALTER TABLE cancha ADD COLUMN estado_caja TEXT DEFAULT 'ABIERTO'")
        except: pass

    cursor.execute("PRAGMA table_info(usuarios)")
    if "login_token" not in [col[1] for col in cursor.fetchall()]:
        try: cursor.execute("ALTER TABLE usuarios ADD COLUMN login_token TEXT")
        except: pass

    cursor.execute("PRAGMA table_info(cocina)")
    if "fecha_entrega" not in [col[1] for col in cursor.fetchall()]:
        try: cursor.execute("ALTER TABLE cocina ADD COLUMN fecha_entrega TEXT")
        except: pass

    columnas_migracion = {
        "ventas": [
            ("id_cierre", "INTEGER"),
            ("atendido_por_tipo", "TEXT"),
            ("atendido_por_nombre", "TEXT"),
            ("metodo_pago", "TEXT DEFAULT 'Efectivo'"),
            ("receptor_tipo", "TEXT DEFAULT 'Caja Chica'"),
            ("receptor_nombre", "TEXT"),
            ("origen", "TEXT DEFAULT 'Ventas'"),
            ("estado_boleta", "TEXT DEFAULT 'ACTIVA'"),
            ("observaciones", "TEXT")
        ],
        "detalle_creditos": [
            ("origen", "TEXT DEFAULT 'Ventas'"),
            ("referencia_id", "INTEGER"),
            ("mesero_nombre", "TEXT"),
            ("trabajador_nombre", "TEXT")
        ],
        "piscina": [
            ("id_cierre", "INTEGER"),
            ("cliente", "TEXT DEFAULT 'CLIENTE PISCINA'"),
            ("metodo_pago", "TEXT DEFAULT 'Efectivo'"),
            ("receptor_tipo", "TEXT DEFAULT 'Caja Chica'"),
            ("receptor_nombre", "TEXT"),
            ("trabajador", "TEXT"),
            ("destino", "TEXT DEFAULT 'PAGADO'"),
            ("estado", "TEXT DEFAULT 'PAGADO'")
        ],
        "cancha": [
            ("id_cierre", "INTEGER"),
            ("metodo_pago", "TEXT DEFAULT 'Efectivo'"),
            ("receptor_tipo", "TEXT DEFAULT 'Caja Chica'"),
            ("receptor_nombre", "TEXT"),
            ("trabajador", "TEXT")
        ],
        "cocina": [
            ("modificado_en", "TEXT"),
            ("mesero_nombre", "TEXT")
        ]
    }
    for tabla, columnas in columnas_migracion.items():
        cursor.execute(f"PRAGMA table_info({tabla})")
        existentes = [col[1] for col in cursor.fetchall()]
        for nombre_col, tipo_col in columnas:
            if nombre_col not in existentes:
                try:
                    cursor.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre_col} {tipo_col}")
                except:
                    pass

    # Corregir fechas futuras causadas por servidores en UTC (Streamlit Cloud)
    # cuando el negocio todavía está trabajando en la fecha local de Perú.
    hoy_sistema = fecha_hoy_local().strftime('%Y-%m-%d')
    ahora_sistema = fecha_hora_actual()
    campos_fecha_sistema = [
        ("inventario", "fecha_ingreso", hoy_sistema),
        ("stock_movimientos", "fecha", ahora_sistema),
        ("ventas", "fecha", ahora_sistema),
        ("detalle_creditos", "fecha", ahora_sistema),
        ("cocina", "fecha_hora", ahora_sistema),
        ("cocina", "fecha_entrega", ahora_sistema),
        ("cocina", "modificado_en", ahora_sistema),
        ("piscina", "fecha", ahora_sistema),
        ("historial_cajas", "fecha_cierre", ahora_sistema),
        ("boletas_liberadas", "fecha_liberacion", ahora_sistema),
    ]
    for tabla_fecha, campo_fecha, valor_fecha in campos_fecha_sistema:
        cursor.execute(f"PRAGMA table_info({tabla_fecha})")
        columnas_fecha = [col[1] for col in cursor.fetchall()]
        if campo_fecha in columnas_fecha:
            try:
                cursor.execute(
                    f"UPDATE {tabla_fecha} SET {campo_fecha}=? WHERE {campo_fecha} IS NOT NULL AND substr({campo_fecha},1,10)>?",
                    (valor_fecha, hoy_sistema)
                )
            except:
                pass

    # Registros iniciales por defecto
    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('administrador', 'admin123', 'Administrador')")
    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('cocinero', 'cocina123', 'Cocinero')")
    cursor.execute("INSERT OR IGNORE INTO tarifas VALUES ('Niños', 5.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas VALUES ('Adultos', 10.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas VALUES ('Mayores', 7.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_cancha VALUES ('Cancha Grande', 70.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_cancha VALUES ('Cancha Grande 3', 70.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_cancha VALUES ('Media Cancha', 40.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_cancha VALUES ('Cancha Mediana 1', 40.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_cancha VALUES ('Cancha Mediana 2', 40.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_local VALUES ('Comedor Principal', 0.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_local VALUES ('Comedor Piscina', 0.0)")

    # Consolidar cabeceras de crédito heredadas para evitar cuentas duplicadas por módulo.
    cursor.execute("SELECT cliente, MIN(id), SUM(total) FROM ventas WHERE estado='CREDITO' GROUP BY cliente HAVING COUNT(*) > 1")
    creditos_duplicados = cursor.fetchall()
    for cliente_dup, id_conservar, total_consolidado in creditos_duplicados:
        cursor.execute(
            "UPDATE ventas SET total=?, origen='Cuenta Corriente' WHERE id=?",
            (total_consolidado or 0, id_conservar)
        )
        cursor.execute(
            "DELETE FROM ventas WHERE cliente=? AND estado='CREDITO' AND id<>?",
            (cliente_dup, id_conservar)
        )

    # Corregir créditos de piscina antiguos que se guardaron como cantidad 1.
    cursor.execute(
        """
        SELECT dc.id, COALESCE(dc.subtotal,0), COALESCE(p.ninos,0), COALESCE(p.adultos,0), COALESCE(p.mayores,0)
        FROM detalle_creditos dc
        JOIN piscina p ON p.id=dc.referencia_id
        WHERE dc.origen='Piscina'
          AND COALESCE(dc.cantidad,1)=1
          AND COALESCE(p.ninos,0) + COALESCE(p.adultos,0) + COALESCE(p.mayores,0) > 1
        """
    )
    creditos_piscina_por_corregir = cursor.fetchall()
    for credito_id, subtotal_credito, ninos_cred, adultos_cred, mayores_cred in creditos_piscina_por_corregir:
        cantidad_real = int(ninos_cred or 0) + int(adultos_cred or 0) + int(mayores_cred or 0)
        precio_promedio = float(subtotal_credito or 0) / cantidad_real if cantidad_real else 0
        cursor.execute(
            "UPDATE detalle_creditos SET cantidad=?, precio_unitario=? WHERE id=?",
            (cantidad_real, precio_promedio, credito_id)
        )

    # Reconciliar cabeceras de crédito con sus detalles reales para quitar deudas fantasma.
    cursor.execute("SELECT id, cliente FROM ventas WHERE estado='CREDITO'")
    cabeceras_credito = cursor.fetchall()
    for venta_credito_id, cliente_credito in cabeceras_credito:
        cursor.execute("SELECT COALESCE(SUM(subtotal),0) FROM detalle_creditos WHERE cliente=?", (cliente_credito,))
        total_credito_real = cursor.fetchone()[0] or 0
        if total_credito_real > 0:
            cursor.execute(
                "UPDATE ventas SET total=?, origen='Cuenta Corriente' WHERE id=?",
                (total_credito_real, venta_credito_id)
            )
        else:
            cursor.execute(
                "UPDATE ventas SET total=0, estado='PAGADO', origen='Cuenta Corriente' WHERE id=?",
                (venta_credito_id,)
            )
    
    conn.commit()
    conn.close()

asegurar_estructura_db()

def ejecutar_query(query, params=(), fetch=False, commit=False):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(query, params)
    res = None
    if fetch:
        res = cursor.fetchall()
    if commit:
        conn.commit()
    conn.close()
    return res

def registrar_movimiento_stock(inventario_id, producto, tipo, cantidad, stock_anterior, stock_nuevo, motivo=""):
    usuario = st.session_state.get("usuario", "Sistema")
    ejecutar_query(
        "INSERT INTO stock_movimientos (inventario_id, producto, tipo, cantidad, stock_anterior, stock_nuevo, fecha, usuario, motivo) VALUES (?,?,?,?,?,?,?,?,?)",
        (inventario_id, producto, tipo, int(cantidad or 0), int(stock_anterior or 0), int(stock_nuevo or 0), fecha_hora_actual(), usuario, motivo),
        commit=True
    )

def reiniciar_formulario(prefix):
    key = f"{prefix}_form_nonce"
    st.session_state[key] = st.session_state.get(key, 0) + 1

def selector_horario_reserva(key_prefix, default_hora_index=9, default_periodo_index=0):
    st.markdown("**Horario de la Reserva:**")
    col_hora, col_periodo = st.columns(2)
    with col_hora:
        hora_num = st.selectbox("Hora", [str(i) for i in range(1, 13)], index=default_hora_index, key=f"{key_prefix}_hora")
    with col_periodo:
        periodo = st.selectbox("Periodo", ["P.M.", "A.M."], index=default_periodo_index, key=f"{key_prefix}_periodo")
    return f"{hora_num}:00 {periodo}"

def trabajadores_por_rol(roles=("Mesero", "Trabajador")):
    marcadores = ",".join(["?"] * len(roles))
    filas = ejecutar_query(
        f"SELECT nombre, rol FROM trabajadores WHERE activo=1 AND UPPER(COALESCE(asistio_hoy, 'SI'))='SI' AND rol IN ({marcadores}) ORDER BY rol, nombre",
        tuple(roles),
        fetch=True
    )
    return filas or []

def seleccionar_trabajador(label, roles=("Mesero", "Trabajador"), key_prefix="trab"):
    personas = trabajadores_por_rol(roles)
    opciones = ["Ventanilla"] + [f"{nombre} ({rol})" for nombre, rol in personas]
    elegido = st.selectbox(label, opciones, key=f"{key_prefix}_selector")
    if elegido == "Ventanilla":
        return "", ""
    nombre = elegido.rsplit(" (", 1)[0]
    rol = elegido.rsplit("(", 1)[1].replace(")", "")
    return rol, nombre

def seleccionar_pago_receptor(key_prefix, incluir_mesero=True, receptor_preseleccionado=None):
    metodo_pago = st.selectbox("Método de Pago", METODOS_PAGO, key=f"{key_prefix}_metodo_pago")
    responsable = metodo_pago if metodo_pago in METODOS_RECAUDADOR else "Caja Chica"
    return metodo_pago, "Metodo de pago", responsable

def nombre_responsable_pago(metodo_pago, receptor_tipo="", receptor_nombre=""):
    if metodo_pago in METODOS_RECAUDADOR:
        return metodo_pago
    return receptor_nombre or receptor_tipo or metodo_pago or "Caja Chica"

def mesero_cocina_sql(alias="c"):
    return f"""
        COALESCE(
            NULLIF(TRIM({alias}.mesero_nombre),''),
            (
                SELECT NULLIF(TRIM(v.atendido_por_nombre),'')
                FROM ventas v
                WHERE v.cliente={alias}.cliente
                  AND NULLIF(TRIM(v.atendido_por_nombre),'') IS NOT NULL
                ORDER BY v.id DESC
                LIMIT 1
            ),
            'Sin asignar'
        )
    """

def calcular_tiempo_entrega(fecha_pedido, fecha_entrega):
    try:
        inicio = datetime.strptime(str(fecha_pedido), "%Y-%m-%d %H:%M")
        fin = datetime.strptime(str(fecha_entrega), "%Y-%m-%d %H:%M")
        segundos = max(0, int((fin - inicio).total_seconds()))
        minutos, resto = divmod(segundos, 60)
        if minutos >= 60:
            horas, mins = divmod(minutos, 60)
            return f"{horas}h {mins}min"
        return f"{minutos}min {resto:02d}s"
    except Exception:
        return "Sin dato"

def html_ticket_impresion(cliente, items, total, tipo, vendedor=""):
    fecha_ticket = fecha_ticket_actual()
    filas = ""
    for item in items:
        filas += f"""
        <tr>
          <td class="item-desc">
            <span class="item-name">{item['producto']}</span>
            <span class="item-qty">{item['cantidad']} x</span>
          </td>
          <td class="item-total">S/. {float(item['subtotal']):.2f}</td>
        </tr>
        """
    return f"""
    <html>
    <head>
      <style>
        @page {{ margin: 0; }}
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          background: #fff;
          color: #000;
          display: flex;
          justify-content: center;
          font-family: "Courier New", monospace;
        }}
        .ticket {{
          width: 280px;
          margin: 0 auto;
          padding: 10px 9px 12px;
          background: #fff;
        }}
        .brand {{
          text-align: center;
          padding-bottom: 8px;
          border-bottom: 1px dashed #000;
        }}
        .brand-title {{
          font-size: 15px;
          line-height: 1.15;
          font-weight: 900;
          letter-spacing: 0;
        }}
        .brand-subtitle {{
          margin-top: 3px;
          font-size: 11px;
          font-weight: 700;
        }}
        .meta {{
          margin: 8px 0;
          padding: 7px 0;
          border-bottom: 1px dashed #000;
          font-size: 11px;
          line-height: 1.45;
        }}
        .meta-row {{
          display: flex;
          gap: 6px;
          align-items: flex-start;
        }}
        .meta-label {{
          min-width: 58px;
          font-weight: 800;
        }}
        .meta-value {{
          flex: 1;
          text-align: right;
          word-break: break-word;
        }}
        .items {{
          width: 100%;
          border-collapse: collapse;
          font-size: 12px;
        }}
        .items th {{
          padding: 0 0 5px;
          border-bottom: 1px solid #000;
          font-size: 11px;
          text-align: left;
        }}
        .items th:last-child {{
          text-align: right;
        }}
        .items td {{
          padding: 6px 0;
          vertical-align: top;
          border-bottom: 1px dotted #999;
        }}
        .item-desc {{
          width: 70%;
          padding-right: 7px;
        }}
        .item-name {{
          display: block;
          font-weight: 700;
          line-height: 1.2;
        }}
        .item-qty {{
          display: block;
          margin-top: 2px;
          font-size: 10px;
        }}
        .item-total {{
          width: 30%;
          text-align: right;
          white-space: nowrap;
          font-weight: 700;
        }}
        .total-box {{
          margin-top: 9px;
          padding: 8px 0;
          border-top: 2px solid #000;
          border-bottom: 2px solid #000;
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-weight: 900;
        }}
        .total-label {{
          font-size: 13px;
        }}
        .total-amount {{
          font-size: 16px;
        }}
        .thanks {{
          margin-top: 10px;
          text-align: center;
          font-size: 11px;
          font-weight: 700;
        }}
      </style>
    </head>
    <body onload="setTimeout(function(){{window.print();}}, 250);">
    <div class="ticket">
      <div class="brand">
        <div class="brand-title">NOTA DE VENTA<br>LAS MARÍAS</div>
        <div class="brand-subtitle">RC. LAS MARÍAS</div>
      </div>
      <div class="meta">
        <div class="meta-row"><span class="meta-label">FECHA</span><span class="meta-value">{fecha_ticket}</span></div>
        <div class="meta-row"><span class="meta-label">CLIENTE</span><span class="meta-value">{cliente}</span></div>
        {'<div class="meta-row"><span class="meta-label">VENDEDOR</span><span class="meta-value">' + vendedor + '</span></div>' if vendedor else ''}
        <div class="meta-row"><span class="meta-label">OP</span><span class="meta-value">{tipo}</span></div>
      </div>
      <table class="items">
        <thead><tr><th>DETALLE</th><th>TOTAL</th></tr></thead>
        <tbody>{filas}</tbody>
      </table>
      <div class="total-box"><span class="total-label">TOTAL A PAGAR</span><span class="total-amount">S/. {float(total):.2f}</span></div>
      <div class="thanks">Muchas gracias por su visita</div>
    </div>
    </body></html>
    """

def imprimir_nota_automatica(cliente, items, total, tipo, vendedor=""):
    components.html(html_ticket_impresion(cliente, items, total, tipo, vendedor), height=1, scrolling=False)

def encolar_impresion_nota(cliente, items, total, tipo, vendedor=""):
    st.session_state["auto_print_payload"] = {
        "cliente": cliente,
        "items": items,
        "total": total,
        "tipo": tipo,
        "vendedor": vendedor
    }

def registrar_credito_cliente(cliente, origen, producto, cantidad, precio_unitario, subtotal, fecha, referencia_id=None, mesero_nombre="", trabajador_nombre=""):
    cliente_normalizado = cliente.strip().upper() if cliente and cliente.strip() else "GENERAL"
    existente = ejecutar_query(
        "SELECT id, total FROM ventas WHERE cliente=? AND estado='CREDITO' ORDER BY id ASC LIMIT 1",
        (cliente_normalizado,),
        fetch=True
    )
    if existente:
        id_venta, total_actual = existente[0]
        ejecutar_query("UPDATE ventas SET total=?, origen='Cuenta Corriente' WHERE id=?", ((total_actual or 0) + subtotal, id_venta), commit=True)
    else:
        ejecutar_query(
            "INSERT INTO ventas (cliente, total, estado, fecha, estado_caja, origen) VALUES (?,?,?,?, 'ABIERTO', ?)",
            (cliente_normalizado, subtotal, "CREDITO", fecha, "Cuenta Corriente"),
            commit=True
        )
    ejecutar_query(
        "INSERT INTO detalle_creditos (cliente, producto, cantidad, precio_unitario, subtotal, fecha, origen, referencia_id, mesero_nombre, trabajador_nombre) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cliente_normalizado, producto, cantidad, precio_unitario, subtotal, fecha, origen, referencia_id, mesero_nombre, trabajador_nombre),
        commit=True
    )

def clientes_credito_abiertos():
    filas = ejecutar_query(
        """
        SELECT cliente FROM ventas WHERE estado='CREDITO'
        UNION
        SELECT cliente FROM detalle_creditos
        ORDER BY cliente
        """,
        fetch=True
    )
    return [fila[0] for fila in filas or [] if fila[0]]

def recalcular_credito_cliente(cliente):
    cliente_normalizado = cliente.strip().upper() if cliente and cliente.strip() else "GENERAL"
    total = ejecutar_query(
        "SELECT SUM(subtotal) FROM detalle_creditos WHERE cliente=?",
        (cliente_normalizado,),
        fetch=True
    )[0][0] or 0
    cabeceras = ejecutar_query(
        "SELECT id FROM ventas WHERE cliente=? AND estado='CREDITO' ORDER BY id ASC",
        (cliente_normalizado,),
        fetch=True
    ) or []
    if cabeceras:
        id_conservar = cabeceras[0][0]
        ejecutar_query(
            "UPDATE ventas SET total=?, origen='Cuenta Corriente' WHERE id=?",
            (total, id_conservar),
            commit=True
        )
        for (id_dup,) in cabeceras[1:]:
            ejecutar_query("DELETE FROM ventas WHERE id=?", (id_dup,), commit=True)
    elif total > 0:
        ejecutar_query(
            "INSERT INTO ventas (cliente, total, estado, fecha, estado_caja, origen) VALUES (?,?,?,?, 'ABIERTO', 'Cuenta Corriente')",
            (cliente_normalizado, total, "CREDITO", fecha_hora_actual()),
            commit=True
        )
    return total

def liquidar_creditos_cliente(cliente, metodo_pago, receptor_tipo, receptor_nombre, atendido_nombre="", detalle_ids=None):
    cliente_normalizado = cliente.strip().upper() if cliente and cliente.strip() else "GENERAL"
    params_detalles = [cliente_normalizado]
    filtro_ids = ""
    if detalle_ids is not None:
        detalle_ids = [int(det_id) for det_id in detalle_ids]
        if not detalle_ids:
            return [], 0
        filtro_ids = " AND id IN (" + ",".join(["?"] * len(detalle_ids)) + ")"
        params_detalles.extend(detalle_ids)
    detalles = ejecutar_query(
        f"SELECT id, producto, cantidad, precio_unitario, subtotal, origen, referencia_id FROM detalle_creditos WHERE cliente=?{filtro_ids}",
        tuple(params_detalles),
        fetch=True
    ) or []
    if not detalles:
        return [], 0

    fecha_pago = fecha_hora_actual()
    detalles_ventas = [d for d in detalles if (d[5] or "Ventas") == "Ventas"]
    total_ventas = sum(float(d[4] or 0) for d in detalles_ventas)
    total_general = sum(float(d[4] or 0) for d in detalles)
    referencias_piscina = sorted({d[6] for d in detalles if d[5] == "Piscina" and d[6]})
    referencias_cancha = sorted({d[6] for d in detalles if d[5] == "Cancha" and d[6]})
    tiene_piscina_sin_ref = any(d[5] == "Piscina" and not d[6] for d in detalles)
    tiene_cancha_sin_ref = any(d[5] == "Cancha" and not d[6] for d in detalles)

    if total_ventas > 0:
        ejecutar_query(
            "INSERT INTO ventas (cliente, total, estado, fecha, estado_caja, atendido_por_tipo, atendido_por_nombre, metodo_pago, receptor_tipo, receptor_nombre, origen) VALUES (?,?,?,?, 'ABIERTO', ?,?,?,?,?, 'Ventas')",
            (cliente_normalizado, total_ventas, "PAGADO", fecha_pago, "Trabajador" if atendido_nombre else "", atendido_nombre, metodo_pago, receptor_tipo, receptor_nombre),
            commit=True
        )
        venta_pago_id = ejecutar_query("SELECT max(id) FROM ventas", fetch=True)[0][0]
        for _, producto, cantidad, precio_unitario, subtotal, _, _ in detalles_ventas:
            ejecutar_query(
                "INSERT INTO detalle_ventas (venta_id, producto, cantidad, precio_unitario, subtotal) VALUES (?,?,?,?,?)",
                (venta_pago_id, producto, cantidad, precio_unitario, subtotal),
                commit=True
            )

    ids_pagados = [d[0] for d in detalles]
    ejecutar_query(
        "DELETE FROM detalle_creditos WHERE id IN (" + ",".join(["?"] * len(ids_pagados)) + ")",
        tuple(ids_pagados),
        commit=True
    )

    for piscina_id in referencias_piscina:
        pendiente_ref = ejecutar_query(
            "SELECT COUNT(*) FROM detalle_creditos WHERE origen='Piscina' AND referencia_id=?",
            (piscina_id,),
            fetch=True
        )[0][0]
        if pendiente_ref == 0:
            ejecutar_query(
                "UPDATE piscina SET estado='PAGADO', destino='Pagado al Instante', metodo_pago=?, receptor_tipo=?, receptor_nombre=? WHERE id=?",
                (metodo_pago, receptor_tipo, receptor_nombre, piscina_id),
                commit=True
            )
    if tiene_piscina_sin_ref:
        pendiente_piscina = ejecutar_query(
            "SELECT COUNT(*) FROM detalle_creditos WHERE cliente=? AND origen='Piscina'",
            (cliente_normalizado,),
            fetch=True
        )[0][0]
        if pendiente_piscina == 0:
            ejecutar_query(
                "UPDATE piscina SET estado='PAGADO', destino='Pagado al Instante', metodo_pago=?, receptor_tipo=?, receptor_nombre=? WHERE cliente=? AND estado='CREDITO'",
                (metodo_pago, receptor_tipo, receptor_nombre, cliente_normalizado),
                commit=True
            )

    for cancha_id in referencias_cancha:
        pendiente_ref = ejecutar_query(
            "SELECT COUNT(*) FROM detalle_creditos WHERE origen='Cancha' AND referencia_id=?",
            (cancha_id,),
            fetch=True
        )[0][0]
        if pendiente_ref == 0:
            ejecutar_query(
                "UPDATE cancha SET estado='PAGADO', metodo_pago=?, receptor_tipo=?, receptor_nombre=? WHERE id=?",
                (metodo_pago, receptor_tipo, receptor_nombre, cancha_id),
                commit=True
            )
    if tiene_cancha_sin_ref:
        pendiente_cancha = ejecutar_query(
            "SELECT COUNT(*) FROM detalle_creditos WHERE cliente=? AND origen='Cancha'",
            (cliente_normalizado,),
            fetch=True
        )[0][0]
        if pendiente_cancha == 0:
            ejecutar_query(
                "UPDATE cancha SET estado='PAGADO', metodo_pago=?, receptor_tipo=?, receptor_nombre=? WHERE cliente=? AND estado='PENDIENTE'",
                (metodo_pago, receptor_tipo, receptor_nombre, cliente_normalizado),
                commit=True
            )

    total_restante = recalcular_credito_cliente(cliente_normalizado)
    if total_restante <= 0:
        ejecutar_query(
            "UPDATE ventas SET estado='PAGADO', total=0, metodo_pago=?, receptor_tipo=?, receptor_nombre=?, atendido_por_nombre=?, origen='Cuenta Corriente' WHERE cliente=? AND estado='CREDITO'",
            (metodo_pago, receptor_tipo, receptor_nombre, atendido_nombre, cliente_normalizado),
            commit=True
        )

    items_boleta = [
        {
            "producto": f"{(origen or 'Ventas').upper()} - {producto}",
            "cantidad": cantidad,
            "precio_unitario": precio_unitario,
            "subtotal": subtotal
        }
        for _, producto, cantidad, precio_unitario, subtotal, origen, _ in detalles
    ]
    return items_boleta, total_general

def sincronizar_cliente_nota(venta_id, cliente_anterior, cliente_nuevo, estado_nota):
    anterior = cliente_anterior.strip().upper() if cliente_anterior and cliente_anterior.strip() else "GENERAL"
    nuevo = cliente_nuevo.strip().upper() if cliente_nuevo and cliente_nuevo.strip() else anterior
    if not nuevo or nuevo == anterior:
        return anterior
    fecha_mod = fecha_hora_actual()
    ejecutar_query(
        "UPDATE cocina SET cliente=?, modificado_en=CASE WHEN estado='PENDIENTE' THEN ? ELSE modificado_en END WHERE cliente=?",
        (nuevo, fecha_mod, anterior),
        commit=True
    )
    if estado_nota == "CREDITO":
        ejecutar_query("UPDATE detalle_creditos SET cliente=? WHERE cliente=?", (nuevo, anterior), commit=True)
        ejecutar_query("UPDATE ventas SET cliente=? WHERE id=?", (nuevo, venta_id), commit=True)
        recalcular_credito_cliente(nuevo)
    else:
        ejecutar_query("UPDATE ventas SET cliente=? WHERE id=?", (nuevo, venta_id), commit=True)
    return nuevo

def deudas_centralizadas():
    return ejecutar_query(
        "SELECT cliente, origen, producto, cantidad, subtotal, fecha FROM detalle_creditos ORDER BY cliente, fecha DESC",
        fetch=True
    ) or []

def operaciones_pendientes_caja():
    pendientes = []
    consultas = [
        ("Ventas", "SELECT id, cliente, total FROM ventas WHERE estado='PENDIENTE' AND estado_caja='ABIERTO'"),
        ("Piscina", "SELECT id, cliente, monto_pagado FROM piscina WHERE estado='PENDIENTE' AND estado_caja='ABIERTO'"),
        (
            "Cancha",
            """
            SELECT c.id, c.cliente, (c.monto_total - c.adelanto)
            FROM cancha c
            WHERE c.estado='PENDIENTE'
              AND c.estado_caja='ABIERTO'
              AND NOT EXISTS (
                  SELECT 1 FROM detalle_creditos dc
                  WHERE dc.origen='Cancha' AND dc.referencia_id=c.id
              )
            """
        ),
        ("Reserva de Local", "SELECT id, cliente, monto_total FROM reservas_local WHERE estado='PENDIENTE' AND estado_caja='ABIERTO'"),
    ]
    for origen, query in consultas:
        for fila in ejecutar_query(query, fetch=True) or []:
            pendientes.append((origen, fila[0], fila[1], fila[2] or 0))
    return pendientes

def creditos_abiertos_caja():
    return ejecutar_query(
        """
        SELECT
            'Crédito' AS tipo,
            v.id,
            v.cliente,
            COALESCE(v.total,0),
            COALESCE((
                SELECT GROUP_CONCAT(DISTINCT COALESCE(NULLIF(TRIM(dc.origen),''),'Ventas'))
                FROM detalle_creditos dc
                WHERE dc.cliente=v.cliente
            ), COALESCE(NULLIF(TRIM(v.origen),''),'Ventas')) AS modulo,
            COALESCE((
                SELECT NULLIF(TRIM(dc.mesero_nombre),'')
                FROM detalle_creditos dc
                WHERE dc.cliente=v.cliente AND NULLIF(TRIM(dc.mesero_nombre),'') IS NOT NULL
                ORDER BY dc.id DESC LIMIT 1
            ), NULLIF(TRIM(v.atendido_por_nombre),''), 'Sin asignar') AS mesero,
            COALESCE((
                SELECT NULLIF(TRIM(dc.trabajador_nombre),'')
                FROM detalle_creditos dc
                WHERE dc.cliente=v.cliente AND NULLIF(TRIM(dc.trabajador_nombre),'') IS NOT NULL
                ORDER BY dc.id DESC LIMIT 1
            ), NULLIF(TRIM(v.atendido_por_nombre),''), 'Sin asignar') AS trabajador
        FROM ventas v
        WHERE v.estado='CREDITO'
          AND v.estado_caja='ABIERTO'
          AND COALESCE(v.total,0)>0
        ORDER BY v.cliente
        """,
        fetch=True
    ) or []

def marcar_notificacion_cocina(cliente, descripcion):
    fecha_mod = fecha_hora_actual()
    ejecutar_query(
        "UPDATE cocina SET modificado_en=? WHERE cliente=? AND estado='PENDIENTE'",
        (fecha_mod, cliente),
        commit=True
    )
    st.session_state["ultima_modificacion_cocina"] = {
        "cliente": cliente,
        "descripcion": descripcion,
        "fecha": fecha_mod
    }

def formatear_montos_df(df, columnas):
    df_formateado = df.copy()
    for columna in columnas:
        if columna in df_formateado.columns:
            df_formateado[columna] = pd.to_numeric(df_formateado[columna], errors="coerce").fillna(0).map(lambda valor: f"{valor:.2f}")
    return df_formateado

def detalle_ingreso_caja(origen, registro_id, monto):
    if origen == "Ventas":
        cabecera = ejecutar_query(
            "SELECT cliente, fecha, total FROM ventas WHERE id=?",
            (registro_id,),
            fetch=True
        )
        detalles = ejecutar_query(
            "SELECT producto, cantidad, precio_unitario, subtotal FROM detalle_ventas WHERE venta_id=?",
            (registro_id,),
            fetch=True
        )
        if cabecera:
            cliente, fecha, total = cabecera[0]
            return cliente, fecha, detalles or [], total or monto
    if origen == "Piscina":
        fila = ejecutar_query(
            "SELECT cliente, fecha, ninos, adultos, mayores, monto_pagado FROM piscina WHERE id=?",
            (registro_id,),
            fetch=True
        )
        if fila:
            cliente, fecha, ninos, adultos, mayores, total = fila[0]
            tarifas = dict(ejecutar_query("SELECT categoria, precio FROM tarifas", fetch=True) or [])
            precio_nino = tarifas.get("Niños", 0)
            precio_adulto = tarifas.get("Adultos", 0)
            precio_mayor = tarifas.get("Mayores", 0)
            items = []
            if ninos:
                items.append(("Entradas piscina niños", ninos, precio_nino, ninos * precio_nino))
            if adultos:
                items.append(("Entradas piscina adultos", adultos, precio_adulto, adultos * precio_adulto))
            if mayores:
                items.append(("Entradas piscina adultos mayores", mayores, precio_mayor, mayores * precio_mayor))
            if not items:
                items.append(("Ingreso piscina", 1, total or monto, total or monto))
            return cliente, fecha, items, total or monto
    if origen in ("Cancha - Adelanto", "Cancha - Saldo"):
        fila = ejecutar_query(
            "SELECT cliente, fecha_reserva, horario, tipo_cancha, monto_total, adelanto, estado FROM cancha WHERE id=?",
            (registro_id,),
            fetch=True
        )
        if fila:
            cliente, fecha_reserva, horario, tipo_cancha, monto_total, adelanto, estado = fila[0]
            concepto = "Adelanto de cancha" if origen == "Cancha - Adelanto" else "Saldo de cancha"
            fecha = f"{fecha_reserva} {horario}"
            items = [(f"{concepto} - {tipo_cancha}", 1, monto, monto)]
            return cliente, fecha, items, monto
    if origen == "Reserva de Local":
        fila = ejecutar_query(
            "SELECT cliente, fecha_reserva, horario, area, monto_total FROM reservas_local WHERE id=?",
            (registro_id,),
            fetch=True
        )
        if fila:
            cliente, fecha_reserva, horario, area, total = fila[0]
            return cliente, f"{fecha_reserva} {horario}", [(f"Reserva de local - {area}", 1, total or monto, total or monto)], total or monto
    return "", "", [], monto

@st.fragment(run_every="1s")
def render_panel_cocina_tiempo_real():
    st.markdown(
        """
        <style>
        .st-key-confirmar_modificacion_cocina button {
            min-height: 96px;
            font-size: 38px;
            font-weight: 900;
            border: 4px solid #16a34a;
            background: #dcfce7;
            color: #14532d;
        }
        .st-key-confirmar_modificacion_cocina button:hover {
            border-color: #15803d;
            background: #bbf7d0;
            color: #14532d;
        }
        div[class*="st-key-entregar_pedido_"] button {
            min-height: 52px;
            font-size: 15px;
            font-weight: 900;
            border: 2px solid #15803d;
            background: #16a34a;
            color: #fff;
            margin-top: -8px;
            margin-bottom: 12px;
        }
        div[class*="st-key-entregar_pedido_"] button:hover {
            border-color: #14532d;
            background: #15803d;
            color: #fff;
        }
        @keyframes cocinaBlink {
            0%, 100% { background-color:#dc2626; box-shadow:0 0 0 rgba(255,255,255,0); border-color:#dc2626; }
            50% { background-color:#b91c1c; box-shadow:0 0 0 6px rgba(255,255,255,.75); border-color:#ffffff; }
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    produccion_dia = ejecutar_query(
        "SELECT plato, SUM(cantidad) FROM cocina WHERE estado='PENDIENTE' GROUP BY plato ORDER BY SUM(cantidad) DESC",
        fetch=True
    )
    if produccion_dia:
        st.subheader("Resumen de Producción del Día")
        cols_prod = st.columns(min(4, len(produccion_dia)))
        for idx, (plato_prod, cant_prod) in enumerate(produccion_dia):
            cols_prod[idx % len(cols_prod)].metric(plato_prod, int(cant_prod or 0))

    mods_pendientes = ejecutar_query(
        "SELECT id, cliente, plato, cantidad, modificado_en FROM cocina WHERE estado='PENDIENTE' AND modificado_en IS NOT NULL ORDER BY modificado_en DESC LIMIT 1",
        fetch=True
    )
    if mods_pendientes:
        id_mod, cli_mod, plato_mod, cant_mod, hora_mod = mods_pendientes[0]
        col_mod_msg, col_mod_ok = st.columns([4.5, 1.2])
        with col_mod_msg:
            st.markdown(
                f"""
                <div style='position:sticky; top:0; z-index:20; background:#7f1d1d; color:white; padding:20px; border-radius:8px; margin-bottom:8px; text-align:center;'>
                    <h2 style='margin:0; font-size:34px;'>PEDIDO MODIFICADO</h2>
                    <p style='font-size:22px; margin:8px 0 0 0;'>Cliente: {cli_mod} | {plato_mod} x {cant_mod} | Hora: {hora_mod}</p>
                </div>
                """,
                unsafe_allow_html=True
            )
        with col_mod_ok:
            with st.container(key="confirmar_modificacion_cocina"):
                if st.button("✅", key=f"btn_confirmar_mod_cocina_{id_mod}", help="Confirmar modificación revisada", use_container_width=True):
                    ejecutar_query("UPDATE cocina SET modificado_en=NULL WHERE id=?", (id_mod,), commit=True)
                    st.rerun()

    mesero_sql = mesero_cocina_sql("c")
    pedidos_cocina = ejecutar_query(
        f"SELECT c.id, c.cliente, c.plato, c.cantidad, c.fecha_hora, {mesero_sql} AS mesero FROM cocina c WHERE c.estado='PENDIENTE' ORDER BY c.fecha_hora ASC",
        fetch=True
    )
    if not pedidos_cocina:
        st.success("¡No hay pedidos pendientes en la cocina!")
        return

    pedidos_agrupados = {}
    for id_p, cliente_p, plato, cant, fecha_h, mesero_p in pedidos_cocina:
        llave = (cliente_p, fecha_h, mesero_p)
        if llave not in pedidos_agrupados:
            pedidos_agrupados[llave] = {'ids': [], 'items': []}
        pedidos_agrupados[llave]['ids'].append(id_p)
        pedidos_agrupados[llave]['items'].append(f"{plato} x {cant}")

    for (cliente_p, fecha_h, mesero_p), data in pedidos_agrupados.items():
        try:
            inicio_dt = datetime.strptime(fecha_h, '%Y-%m-%d %H:%M')
            ahora_servidor = ahora_windows()
            segundos_espera = int((ahora_servidor - inicio_dt).total_seconds())
            inicio_ms = int(inicio_dt.timestamp() * 1000)
            server_now_ms = int(ahora_servidor.timestamp() * 1000)
        except Exception:
            segundos_espera = 0
            inicio_ms = int(ahora_windows().timestamp() * 1000)
            server_now_ms = int(ahora_windows().timestamp() * 1000)
        color_tiempo = "#16a34a" if segundos_espera < 600 else "#f97316" if segundos_espera < 900 else "#dc2626"
        alerta_tiempo = "<div class='late-alert'>PEDIDO FUERA DE TIEMPO</div>" if segundos_espera >= 900 else ""
        card_id = "cook_" + "_".join(str(x) for x in data["ids"])
        animacion_roja = "animation:cocinaBlink 1s infinite;" if segundos_espera >= 900 else ""
        components.html(f"""
        <style>
        @keyframes cocinaBlink {{
            0%, 100% {{ background-color:#dc2626; box-shadow:0 0 0 rgba(255,255,255,0); border-color:#dc2626; }}
            50% {{ background-color:#b91c1c; box-shadow:0 0 0 6px rgba(255,255,255,.75); border-color:#ffffff; }}
        }}
        </style>
        <div id="{card_id}" class="cook-card" data-start-ms="{inicio_ms}" data-server-now-ms="{server_now_ms}" data-client-render-ms="" style="background-color:{color_tiempo}; padding:20px; border:3px solid transparent; border-radius:10px; margin-bottom:15px; color:white; display:grid; grid-template-columns:1fr 140px; gap:14px; align-items:center; {animacion_roja}">
            <div>
                <p style='margin:0 0 6px 0; color:white; font-size:18px; font-weight:900;'>Pedido #{", #".join(str(x) for x in data["ids"])}</p>
                <p style='margin:0 0 12px 0; color:white; font-size:26px; font-weight:bold;'>🍴 {", ".join(data['items'])}</p>
                <p style='margin:0; color:white; font-size:18px; font-weight:700;'>👤 Cliente: {cliente_p} &nbsp; | &nbsp; Mesero: {mesero_p}</p>
                {alerta_tiempo}
            </div>
            <div style='background:rgba(0,0,0,.22); border:1px solid rgba(255,255,255,.45); border-radius:8px; padding:12px; text-align:center;'>
                <div style='font-size:12px;font-weight:700;'>Tiempo restante</div>
                <div class='timer-main' style='font-size:28px;font-weight:900;'>--:--</div>
                <div class='timer-sub' style='font-size:12px;'>Calculando...</div>
            </div>
        </div>
        <script>
        (function() {{
            const card = document.getElementById("{card_id}");
            if (!card) return;
            const startMs = Number(card.dataset.startMs);
            const serverNowMs = Number(card.dataset.serverNowMs);
            const clientRenderMs = Date.now();
            const main = card.querySelector(".timer-main");
            const sub = card.querySelector(".timer-sub");
            function pad(n) {{ return String(n).padStart(2, "0"); }}
            function tick() {{
                const syncedNowMs = serverNowMs + (Date.now() - clientRenderMs);
                const elapsed = Math.max(0, Math.floor((syncedNowMs - startMs) / 1000));
                const mins = Math.floor(elapsed / 60);
                const remaining = Math.max(900 - elapsed, 0);
                if (remaining > 0) {{
                    main.textContent = pad(Math.floor(remaining / 60)) + ":" + pad(remaining % 60);
                }} else {{
                    const lateSecs = elapsed - 900;
                    main.textContent = "+" + pad(Math.floor(lateSecs / 60)) + ":" + pad(lateSecs % 60);
                }}
                sub.textContent = mins + " min transcurridos";
                const vencido = elapsed >= 900;
                const color = elapsed < 600 ? "#16a34a" : elapsed < 900 ? "#f97316" : "#dc2626";
                card.style.backgroundColor = color;
                card.style.animation = vencido ? "cocinaBlink 1s infinite" : "none";
                let late = card.querySelector(".late-alert");
                if (vencido && !late) {{
                    const div = document.createElement("div");
                    div.className = "late-alert";
                    div.style.cssText = "font-size:22px;font-weight:900;margin-top:10px;";
                    div.textContent = "PEDIDO FUERA DE TIEMPO";
                    card.firstElementChild.appendChild(div);
                }} else if (!vencido && late) {{
                    late.remove();
                }}
            }}
            tick();
            if (card._timer) clearInterval(card._timer);
            card._timer = setInterval(tick, 500);
        }})();
        </script>
        """, height=150, scrolling=False)

        ids_key = "_".join(str(id_item) for id_item in data["ids"])
        with st.container(key=f"entregar_pedido_{ids_key}"):
            if st.button(f"✅ ENTREGAR PEDIDO COMPLETO", key=f"btn_{data['ids']}", help="Marcar este pedido como entregado", use_container_width=True):
                fecha_entrega = fecha_hora_actual()
                for id_individual in data['ids']:
                    ejecutar_query("UPDATE cocina SET estado='ENTREGADO', fecha_entrega=? WHERE id=?", (fecha_entrega, id_individual), commit=True)
                st.rerun()

@st.fragment(run_every="1s")
def render_monitor_cocina_admin_tabla():
    mesero_pend_sql = mesero_cocina_sql("c")
    pendientes = ejecutar_query(
        f"SELECT c.id, c.cliente, c.plato, c.cantidad, c.fecha_hora, {mesero_pend_sql} AS mesero FROM cocina c WHERE c.estado='PENDIENTE' ORDER BY c.id ASC",
        fetch=True
    )
    if not pendientes:
        st.success("Cocina al día.")
        return

    df_pend = pd.DataFrame(
        pendientes,
        columns=["ID Pedido", "Cliente / Mesa", "Plato", "Cantidad", "Fecha/Hora", "Mesero"]
    )
    ahora_servidor = ahora_windows()
    parpadeo_rojo = ahora_servidor.second % 2 == 0

    def estilo_id_pedido(fila):
        estilos = [""] * len(fila)
        try:
            inicio = datetime.strptime(str(fila["Fecha/Hora"]), "%Y-%m-%d %H:%M")
            segundos = int((ahora_servidor - inicio).total_seconds())
        except Exception:
            segundos = 0
        if segundos < 600:
            color = "#16a34a"
        elif segundos < 900:
            color = "#f97316"
            texto = "white"
        else:
            color = "#dc2626" if parpadeo_rojo else "#ffffff"
            texto = "white" if parpadeo_rojo else "#dc2626"
        if segundos < 600:
            texto = "white"
        borde = "2px solid #dc2626" if segundos >= 900 and not parpadeo_rojo else "1px solid #dc2626"
        estilos[0] = f"background-color: {color}; color: {texto}; font-weight: 900; border: {borde};"
        return estilos

    st.dataframe(df_pend.style.apply(estilo_id_pedido, axis=1), use_container_width=True, hide_index=True)

def render_modificar_notas(dict_productos):
    if st.button("Modificar Pedido / Boleta", type="primary", use_container_width=True, key="btn_abrir_modificar_boleta"):
        st.session_state["modal_modificar_boleta"] = True
        st.session_state["boleta_modificada_pendiente"] = False
        st.session_state["confirmar_cierre_boleta"] = False

    def contenido_editor_boleta():
        def separador_editor():
            st.markdown(
                "<div style='height:3px;background:#cbd5e1;margin:26px 0 22px 0;border-radius:3px;'></div>",
                unsafe_allow_html=True
            )

        ventas_editables = ejecutar_query(
            "SELECT id, cliente, total, estado, fecha FROM ventas WHERE estado IN ('PAGADO','CREDITO') AND COALESCE(estado_boleta,'ACTIVA')='ACTIVA' ORDER BY id DESC LIMIT 80",
            fetch=True
        )
        if not ventas_editables:
            st.info("No hay notas activas para modificar.")
            return

        st.markdown("#### Boleta o pedido")
        opciones_ventas = {f"Nota #{v[0]} - {v[1]} - S/. {v[2]:.2f} ({v[3]}) - {v[4]}": v[0] for v in ventas_editables}
        venta_label = st.selectbox("Boleta o pedido", list(opciones_ventas.keys()), key="sb_editar_nota_venta")
        venta_editar_id = opciones_ventas[venta_label]
        venta_info = ejecutar_query(
            "SELECT cliente, estado, metodo_pago, COALESCE(atendido_por_nombre,''), COALESCE(observaciones,'') FROM ventas WHERE id=?",
            (venta_editar_id,),
            fetch=True
        )[0]
        cliente_actual_nota, estado_actual_nota, metodo_actual, mesero_actual, obs_actual = venta_info
        tabla_det = "detalle_creditos" if estado_actual_nota == "CREDITO" else "detalle_ventas"
        filtro_sql = "cliente=?" if tabla_det == "detalle_creditos" else "venta_id=?"
        filtro_val = cliente_actual_nota if tabla_det == "detalle_creditos" else venta_editar_id

        meseros_activos = [nombre for nombre, rol in trabajadores_por_rol(("Mesero",))]
        opciones_mesero = ["Sin asignar"] + meseros_activos
        if mesero_actual and mesero_actual not in opciones_mesero:
            opciones_mesero.append(mesero_actual)
        mesero_index = opciones_mesero.index(mesero_actual) if mesero_actual in opciones_mesero else 0

        col_a, col_b = st.columns(2)
        with col_a:
            nuevo_cliente_nota = st.text_input("Cliente / mesa", value=cliente_actual_nota, key="txt_cliente_edit_nota").strip().upper()
            mesero_seleccionado = st.selectbox("Mesero asociado", opciones_mesero, index=mesero_index, key="sb_mesero_edit_nota")
            nuevo_mesero = "" if mesero_seleccionado == "Sin asignar" else mesero_seleccionado
        with col_b:
            metodo_index = METODOS_PAGO.index(metodo_actual) if metodo_actual in METODOS_PAGO else 0
            nuevo_metodo = st.selectbox("Método de pago", METODOS_PAGO, index=metodo_index, key="sb_metodo_edit_nota")
            nuevas_obs = st.text_area("Observaciones", value=obs_actual, height=82, key="txt_obs_edit_nota")

        datos_generales_modificados = (
            nuevo_cliente_nota != (cliente_actual_nota or "").strip().upper() or
            nuevo_mesero != (mesero_actual or "").strip() or
            nuevo_metodo != (metodo_actual or "Efectivo") or
            nuevas_obs.strip() != (obs_actual or "").strip()
        )

        separador_editor()
        st.markdown("#### Producto a editar")

        editor_key = f"{tabla_det}_{venta_editar_id}_{cliente_actual_nota}"
        if st.session_state.get("boleta_editor_key") != editor_key:
            if tabla_det == "detalle_creditos":
                detalles_base = ejecutar_query(
                    "SELECT id, producto, cantidad, precio_unitario, subtotal, origen, referencia_id, COALESCE(mesero_nombre,'') FROM detalle_creditos WHERE cliente=?",
                    (cliente_actual_nota,),
                    fetch=True
                ) or []
                st.session_state["boleta_temp_items"] = [
                    {"id": d[0], "producto": d[1], "cantidad": int(d[2]), "precio_unitario": float(d[3] or 0), "subtotal": float(d[4] or 0), "origen": d[5] or "Ventas", "referencia_id": d[6], "mesero_nombre": d[7]}
                    for d in detalles_base
                ]
            else:
                detalles_base = ejecutar_query(
                    "SELECT id, producto, cantidad, precio_unitario, subtotal FROM detalle_ventas WHERE venta_id=?",
                    (venta_editar_id,),
                    fetch=True
                ) or []
                st.session_state["boleta_temp_items"] = [
                    {"id": d[0], "producto": d[1], "cantidad": int(d[2]), "precio_unitario": float(d[3] or 0), "subtotal": float(d[4] or 0), "origen": "Ventas", "referencia_id": None, "mesero_nombre": ""}
                    for d in detalles_base
                ]
            st.session_state["boleta_editor_key"] = editor_key
            st.session_state["boleta_modificada_pendiente"] = False

        detalles_nota = st.session_state.get("boleta_temp_items", [])
        if detalles_nota:
            df_temp_nota = pd.DataFrame(detalles_nota)
            st.dataframe(
                df_temp_nota[["id", "producto", "cantidad", "precio_unitario", "subtotal"]].rename(columns={
                    "id": "ID",
                    "producto": "Producto",
                    "cantidad": "Cantidad",
                    "precio_unitario": "Precio",
                    "subtotal": "Subtotal"
                }),
                use_container_width=True,
                hide_index=True
            )
            ids_detalle = {f"{d['producto']} x {d['cantidad']} - S/. {float(d['subtotal'] or 0):.2f}": idx for idx, d in enumerate(detalles_nota)}
            detalle_sel = st.selectbox("Producto a editar", list(ids_detalle.keys()), key="sb_item_edit_nota")
            idx_det = ids_detalle[detalle_sel]
            item_det = detalles_nota[idx_det]
            producto_det = item_det["producto"]
            cant_actual = item_det["cantidad"]
            precio_det = item_det["precio_unitario"]
            col_c, col_d = st.columns(2)
            with col_c:
                nueva_cant_item = st.number_input("Cantidad", min_value=1, value=int(cant_actual), key="num_edit_cant_nota")
                if st.button("Actualizar cantidad", use_container_width=True, key="btn_mod_cant_nota"):
                    st.session_state["boleta_temp_items"][idx_det]["cantidad"] = int(nueva_cant_item)
                    st.session_state["boleta_temp_items"][idx_det]["subtotal"] = float(precio_det) * int(nueva_cant_item)
                    st.session_state["boleta_modificada_pendiente"] = True
                    st.rerun()
            with col_d:
                st.write("")
                st.write("")
                if st.button("Eliminar producto", use_container_width=True, key="btn_del_item_nota"):
                    st.session_state["boleta_temp_items"].pop(idx_det)
                    st.session_state["boleta_modificada_pendiente"] = True
                    st.rerun()
        else:
            st.info("Esta boleta no tiene productos registrados.")

        separador_editor()
        if dict_productos:
            st.markdown("#### Agregar consumo")
            col_e, col_f = st.columns([2, 1])
            with col_e:
                prod_extra = st.selectbox("Producto", [""] + list(dict_productos.keys()), key="sb_add_prod_nota")
            with col_f:
                cant_extra = st.number_input("Cantidad nueva", min_value=1, value=1, key="num_add_prod_nota")
            if st.button("Agregar a la boleta", use_container_width=True, key="btn_add_prod_nota") and prod_extra:
                precio_extra = dict_productos[prod_extra]["precio"]
                subtotal_extra = precio_extra * cant_extra
                fecha_actual = fecha_hora_actual()
                st.session_state.setdefault("boleta_temp_items", []).append({
                    "id": f"NUEVO-{len(st.session_state.get('boleta_temp_items', [])) + 1}",
                    "producto": prod_extra,
                    "cantidad": int(cant_extra),
                    "precio_unitario": float(precio_extra),
                    "subtotal": float(subtotal_extra),
                    "origen": "Ventas",
                    "referencia_id": None,
                    "mesero_nombre": nuevo_mesero,
                    "fecha": fecha_actual
                })
                st.session_state["boleta_modificada_pendiente"] = True
                st.rerun()

        separador_editor()
        col_g, col_h = st.columns(2)
        with col_g:
            if st.button("Guardar Modificación", type="primary", use_container_width=True, key="btn_guardar_modificacion_boleta"):
                cliente_trabajo = sincronizar_cliente_nota(venta_editar_id, cliente_actual_nota, nuevo_cliente_nota, estado_actual_nota)
                responsable_pago = nombre_responsable_pago(nuevo_metodo, "Metodo de pago", "")
                items_temp_guardar = st.session_state.get("boleta_temp_items", [])
                nuevo_total = sum(float(item.get("subtotal", 0) or 0) for item in items_temp_guardar)
                fecha_guardado = fecha_hora_actual()
                if tabla_det == "detalle_creditos":
                    productos_originales_cocina = [p[0] for p in ejecutar_query("SELECT producto FROM detalle_creditos WHERE cliente=?", (cliente_trabajo,), fetch=True) or []]
                else:
                    productos_originales_cocina = [p[0] for p in ejecutar_query("SELECT producto FROM detalle_ventas WHERE venta_id=?", (venta_editar_id,), fetch=True) or []]
                if tabla_det == "detalle_creditos":
                    ejecutar_query("DELETE FROM detalle_creditos WHERE cliente=?", (cliente_trabajo,), commit=True)
                    for item in items_temp_guardar:
                        ejecutar_query(
                            "INSERT INTO detalle_creditos (cliente, producto, cantidad, precio_unitario, subtotal, fecha, origen, referencia_id, mesero_nombre) VALUES (?,?,?,?,?,?,?,?,?)",
                            (cliente_trabajo, item["producto"], item["cantidad"], item["precio_unitario"], item["subtotal"], item.get("fecha", fecha_guardado), item.get("origen", "Ventas"), item.get("referencia_id"), nuevo_mesero),
                            commit=True
                        )
                    nuevo_total = recalcular_credito_cliente(cliente_trabajo)
                else:
                    ejecutar_query("DELETE FROM detalle_ventas WHERE venta_id=?", (venta_editar_id,), commit=True)
                    for item in items_temp_guardar:
                        ejecutar_query(
                            "INSERT INTO detalle_ventas (venta_id, producto, cantidad, precio_unitario, subtotal) VALUES (?,?,?,?,?)",
                            (venta_editar_id, item["producto"], item["cantidad"], item["precio_unitario"], item["subtotal"]),
                            commit=True
                        )
                ejecutar_query(
                    "UPDATE ventas SET cliente=?, total=?, atendido_por_tipo=?, atendido_por_nombre=?, metodo_pago=?, receptor_tipo='Metodo de pago', receptor_nombre=?, observaciones=? WHERE id=?",
                    (cliente_trabajo, nuevo_total, "Mesero" if nuevo_mesero else "", nuevo_mesero, nuevo_metodo, responsable_pago, nuevas_obs.strip(), venta_editar_id),
                    commit=True
                )
                productos_cocina = sorted(set(productos_originales_cocina + [item["producto"] for item in items_temp_guardar]))
                for producto_cocina in productos_cocina:
                    ejecutar_query("DELETE FROM cocina WHERE cliente=? AND plato=? AND estado='PENDIENTE'", (cliente_trabajo, producto_cocina), commit=True)
                for item in items_temp_guardar:
                    if str(dict_productos.get(item["producto"], {}).get("proveedor", "")).strip().upper() == "INTERNO":
                        ejecutar_query(
                            "INSERT INTO cocina (cliente, plato, cantidad, fecha_hora, estado, modificado_en, mesero_nombre) VALUES (?,?,?,?,?,?,?)",
                            (cliente_trabajo, item["producto"], item["cantidad"], fecha_guardado, "PENDIENTE", fecha_guardado, nuevo_mesero),
                            commit=True
                        )
                ejecutar_query("UPDATE detalle_creditos SET mesero_nombre=? WHERE cliente=?", (nuevo_mesero, cliente_trabajo), commit=True)
                items_impresion = [{"producto": item["producto"], "cantidad": item["cantidad"], "subtotal": item["subtotal"]} for item in items_temp_guardar]
                encolar_impresion_nota(cliente_trabajo, items_impresion, nuevo_total, "NOTA ACTUALIZADA", nuevo_mesero)
                st.session_state["boleta_modificada_pendiente"] = False
                st.session_state["confirmar_cierre_boleta"] = False
                st.session_state["modal_modificar_boleta"] = False
                st.session_state.pop("boleta_temp_items", None)
                st.session_state.pop("boleta_editor_key", None)
                st.rerun()
        with col_h:
            if st.button("Cerrar", use_container_width=True, key="btn_cerrar_modal_boleta"):
                if st.session_state.get("boleta_modificada_pendiente") or datos_generales_modificados:
                    st.session_state["confirmar_cierre_boleta"] = True
                else:
                    st.session_state["modal_modificar_boleta"] = False
                st.rerun()

        if st.session_state.get("confirmar_cierre_boleta"):
            st.markdown(
                """
                <style>
                .st-key-confirmar_cierre_overlay {
                    position: fixed;
                    inset: 0;
                    z-index: 999999;
                    background: rgba(15, 23, 42, .55);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 18px;
                }
                .st-key-confirmar_cierre_overlay > div {
                    width: min(520px, 92vw);
                    background: #ffffff;
                    border: 2px solid #f59e0b;
                    border-radius: 8px;
                    padding: 18px;
                    box-shadow: 0 22px 60px rgba(15, 23, 42, .35);
                }
                .confirm-title {
                    color: #92400e;
                    font-weight: 900;
                    font-size: 18px;
                    text-align: center;
                    margin: 0 0 14px 0;
                }
                </style>
                """,
                unsafe_allow_html=True
            )
            with st.container(key="confirmar_cierre_overlay"):
                st.markdown("<div class='confirm-title'>QUIERES CERRAR Y PERDER LAS MODIFICACIONES</div>", unsafe_allow_html=True)
                col_cancelar, col_cerrar = st.columns(2)
                with col_cancelar:
                    if st.button("CANCELAR", use_container_width=True, key="btn_cancelar_cierre_boleta"):
                        st.session_state["confirmar_cierre_boleta"] = False
                        st.rerun()
                with col_cerrar:
                    if st.button("CERRAR", use_container_width=True, key="btn_confirmar_cierre_boleta"):
                        st.session_state["boleta_modificada_pendiente"] = False
                        st.session_state["confirmar_cierre_boleta"] = False
                        st.session_state["modal_modificar_boleta"] = False
                        st.session_state.pop("boleta_temp_items", None)
                        st.session_state.pop("boleta_editor_key", None)
                        st.rerun()

    if st.session_state.get("modal_modificar_boleta"):
        if hasattr(st, "dialog"):
            try:
                dialog_decorator = st.dialog("Modificar Pedido / Boleta", width="large")
            except TypeError:
                dialog_decorator = st.dialog("Modificar Pedido / Boleta")

            @dialog_decorator
            def dialogo_modificar_boleta():
                contenido_editor_boleta()
            dialogo_modificar_boleta()
        else:
            with st.expander("Modificar Pedido / Boleta", expanded=True):
                contenido_editor_boleta()

# --- SERVICIOS DE CONFIGURACION, MARCA Y RESPALDOS ---
def preparar_directorios_sistema():
    ASSETS_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(exist_ok=True)

def obtener_config(clave, valor_defecto=""):
    fila = ejecutar_query("SELECT valor FROM configuracion WHERE clave=?", (clave,), fetch=True)
    return fila[0][0] if fila else valor_defecto

def guardar_config(clave, valor):
    ejecutar_query(
        "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
        (clave, valor),
        commit=True
    )

def guardar_archivo_subido(archivo, nombre_base):
    preparar_directorios_sistema()
    extension = Path(archivo.name).suffix.lower() or ".png"
    destino = ASSETS_DIR / f"{nombre_base}{extension}"
    with destino.open("wb") as salida:
        salida.write(archivo.getbuffer())
    return str(destino)

def imagen_css_desde_archivo(ruta, fallback_url):
    ruta_archivo = Path(ruta) if ruta else None
    if ruta_archivo and ruta_archivo.exists():
        mime = mimetypes.guess_type(ruta_archivo.name)[0] or "image/png"
        data = base64.b64encode(ruta_archivo.read_bytes()).decode("utf-8")
        return f'url("data:{mime};base64,{data}")'
    return f'url("{fallback_url}")'

def crear_backup_base_datos():
    preparar_directorios_sistema()
    origen = Path(DB_NAME)
    marca_tiempo = ahora_windows().strftime("%Y%m%d_%H%M%S")
    destino = BACKUP_DIR / f"backup_complejo_{marca_tiempo}.db"
    shutil.copy2(origen, destino)
    excel_destino = BACKUP_DIR / f"historial_cajas_{marca_tiempo}.xlsx"
    try:
        historial = ejecutar_query("SELECT id, fecha_cierre, total_vendido, usuario_cierre FROM historial_cajas ORDER BY id DESC", fetch=True)
        df_historial = pd.DataFrame(historial or [], columns=["ID Cierre", "Fecha Cierre", "Total Vendido", "Usuario Cierre"])
        with pd.ExcelWriter(excel_destino) as writer:
            df_historial.to_excel(writer, sheet_name="Historial Cajas", index=False)
    except Exception:
        excel_destino = None
    return destino, excel_destino

preparar_directorios_sistema()

# --- INICIALIZAR CARRITO TEMPORAL ---
if 'carrito' not in st.session_state:
    st.session_state['carrito'] = []
if "venta_form_nonce" not in st.session_state:
    st.session_state["venta_form_nonce"] = 0

def limpiar_formulario_venta():
    st.session_state["venta_form_nonce"] += 1

# --- MODAL DE IMPRESIÓN REFORMATEADO Y OPTIMIZADO PARA IMPRESORA TÉRMICA ---
@st.dialog("📄 Boleto de Venta - LAS MARÍAS")
def mostrar_ticket_multiple(cliente, items, total, tipo, vendedor=""):
    fecha_ticket = fecha_ticket_actual()
    
    # Construcción de los items en filas HTML limpias
    lineas_html = ""
    for item in items:
        nombre_prod = item['producto'].strip().upper()
        lineas_html += f"""
        <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 5px; font-family: monospace;">
            <div style="text-align: left; width: 70%;">
                <b>{item['cantidad']}</b> x {nombre_prod}
            </div>
            <div style="text-align: right; width: 30%; font-weight: bold;">
                S/. {item['subtotal']:.2f}
            </div>
        </div>
        """
        
    # Documento HTML autocontenido con botón de impresión interno
    html_completo = f"""
    <div id="ticket-termico" style="font-family: 'Courier New', Courier, monospace; color: black; background-color: white; padding: 10px; width: 280px; margin: 0 auto; line-height: 1.3;">
        
        <div style="text-align: center; margin-bottom: 8px;">
            <b style="font-size: 15px; letter-spacing: 1px;">NOTA DE VENTA - LAS MARÍAS</b><br>
            <b style="font-size: 16px; letter-spacing: 1px;">RC. LAS MARÍAS</b><br>
            <span style="font-size: 11px; color: #333;">COMPLEJO RECREATIVO</span><br>
            <span style="font-size: 11px; color: #333;">Sullana, Piura, Perú</span><br>
            <small>----------------------------------</small>
        </div>
        
        <div style="font-size: 12px; margin-bottom: 8px; text-align: left;">
            <b>FECHA:</b> {fecha_ticket}<br>
            <b>CLIENTE:</b> {cliente}<br>
            {f"<b>VENDEDOR:</b> {vendedor}<br>" if vendedor else ""}
            <b>OP:</b> {tipo}<br>
            <small>----------------------------------</small>
        </div>
        
        <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: bold; margin-bottom: 5px; border-bottom: 1px dashed black; padding-bottom: 3px;">
            <span style="width: 70%; text-align: left;">DESCRIPCIÓN</span>
            <span style="width: 30%; text-align: right;">TOTAL</span>
        </div>
        
        <div style="margin-bottom: 8px;">
            {lineas_html}
        </div>
        
        <div style="border-top: 1px dashed black; padding-top: 6px; margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; font-size: 14px; font-weight: bold;">
                <span>TOTAL PAGADO:</span>
                <span>S/. {total:.2f}</span>
            </div>
        </div>
        
        <div style="text-align: center; font-size: 11px; margin-top: 10px;">
            <small>----------------------------------</small><br>
            <b>¡Muchas gracias por su visita!</b><br>
            <span>Conserve su comprobante</span><br><br>
            <b style="letter-spacing: 1px;">*** VUELVA PRONTO ***</b>
        </div>

        <div class="no-print" style="margin-top: 20px; text-align: center;">
            <button onclick="window.print();" style="width: 100%; padding: 12px; background-color: #FF4B4B; color: white; border: none; border-radius: 5px; font-weight: bold; cursor: pointer; font-family: sans-serif; font-size: 14px; box-shadow: 0px 4px 6px rgba(0,0,0,0.1);">
                🖨️ Mandar a Impresora Térmica
            </button>
        </div>
    </div>

    <style>
        @media print {{
            .no-print {{
                display: none !important;
            }}
            body {{
                margin: 0;
                padding: 0;
                background-color: white;
            }}
        }}
    </style>
    """
    
    st.components.v1.html(html_completo, height=450, scrolling=True)


# --- SISTEMA DE LOGEO ---
if 'autenticado' not in st.session_state:
    st.session_state['autenticado'] = False
    st.session_state['usuario'] = ""
    st.session_state['rol'] = ""

def obtener_parametro_url(nombre):
    valor = st.query_params.get(nombre)
    if isinstance(valor, list):
        return valor[0] if valor else ""
    return valor or ""

def guardar_sesion_en_url(usuario, rol, token):
    st.query_params["usuario"] = usuario
    st.query_params["rol"] = rol
    st.query_params["token"] = token

def limpiar_sesion_url():
    for parametro in ["usuario", "rol", "token", "tab"]:
        if parametro in st.query_params:
            del st.query_params[parametro]

def restaurar_sesion_desde_url():
    if st.session_state['autenticado']:
        return

    usuario = obtener_parametro_url("usuario")
    token = obtener_parametro_url("token")
    if not usuario or not token:
        return

    user_data = ejecutar_query(
        "SELECT rol FROM usuarios WHERE username=? AND login_token=?",
        (usuario, token),
        fetch=True
    )
    if user_data:
        st.session_state['autenticado'] = True
        st.session_state['usuario'] = usuario
        st.session_state['rol'] = user_data[0][0]
    else:
        limpiar_sesion_url()

def guardar_pestana_admin():
    pestana = st.session_state.get("pestana_admin")
    if pestana:
        st.query_params["tab"] = pestana

def cambiar_modulo_admin():
    modulo = st.session_state.get("modulo_admin_selector")
    if modulo:
        st.session_state["modulo_admin_activo"] = modulo
        st.query_params["tab"] = modulo

def activar_modulo_admin(modulo):
    st.session_state["modulo_admin_activo"] = modulo
    st.session_state["modulo_admin_selector"] = modulo
    st.query_params["tab"] = modulo
    st.rerun()

def resolver_modulo_admin(opciones_menu):
    modulo_guardado = st.session_state.get("modulo_admin_activo")
    modulo_url = obtener_parametro_url("tab")

    if modulo_guardado in opciones_menu:
        modulo_activo = modulo_guardado
    elif modulo_url in opciones_menu:
        modulo_activo = modulo_url
    else:
        modulo_activo = opciones_menu[0]

    st.session_state["modulo_admin_activo"] = modulo_activo
    st.session_state["modulo_admin_selector"] = modulo_activo
    st.query_params["tab"] = modulo_activo
    return modulo_activo

restaurar_sesion_desde_url()

def aplicar_estilos_login():
    fondo_login = imagen_css_desde_archivo(
        obtener_config("login_background_path"),
        "https://images.unsplash.com/photo-1575429198097-0414ec08e8cd?auto=format&fit=crop&w=1800&q=80"
    )
    st.markdown("""
    <style>
        [data-testid="stAppViewContainer"] {
            background:
                linear-gradient(120deg, rgba(4, 47, 68, 0.78), rgba(8, 121, 150, 0.42)),
                __LOGIN_BACKGROUND__;
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        [data-testid="stToolbar"] {
            display: none;
        }

        .block-container {
            padding-top: 7vh;
        }

        .login-hero {
            max-width: 460px;
            margin: 0 auto 18px auto;
            text-align: center;
            color: white;
            text-shadow: 0 2px 12px rgba(0, 0, 0, 0.35);
        }

        .login-hero h1 {
            margin-bottom: 8px;
            font-size: 40px;
            font-weight: 800;
            letter-spacing: 0;
        }

        .login-hero p {
            margin: 0;
            font-size: 17px;
            font-weight: 500;
        }

        .st-key-login_card {
            max-width: 430px;
            margin: 0 auto;
            padding: 30px 30px 26px 30px;
            border: 1px solid rgba(255, 255, 255, 0.38);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.94);
            box-shadow: 0 22px 55px rgba(0, 32, 44, 0.35);
        }

        .login-card-title {
            margin: 0 0 4px 0;
            color: #073b4c;
            text-align: center;
            font-size: 24px;
            font-weight: 800;
        }

        .login-card-subtitle {
            margin: 0 0 22px 0;
            color: #45636d;
            text-align: center;
            font-size: 14px;
        }

        .stTextInput label {
            color: #123943 !important;
            font-weight: 700 !important;
        }

        .stTextInput input {
            border-radius: 6px;
            border: 1px solid #c9dce2;
            background: #f8fcfd;
        }

        .stButton > button {
            height: 46px;
            border: 0;
            border-radius: 6px;
            background: linear-gradient(90deg, #0077b6, #00a6a6);
            color: white;
            font-weight: 800;
            box-shadow: 0 8px 18px rgba(0, 119, 182, 0.28);
        }

        .stButton > button:hover {
            border: 0;
            background: linear-gradient(90deg, #006da8, #009795);
            color: white;
        }
    </style>
    """.replace("__LOGIN_BACKGROUND__", fondo_login), unsafe_allow_html=True)

def aplicar_estilos_sistema():
    st.markdown("""
    <style>
        :root {
            --lm-primary: #0f9ca7;
            --lm-primary-dark: #1f2933;
            --lm-accent: #16b8c4;
            --lm-bg: #dfe7f1;
            --lm-panel: #ffffff;
            --lm-border: #cdd8e3;
            --lm-text: #17333b;
            --lm-muted: #5f7780;
        }

        [data-testid="stAppViewContainer"] {
            background: var(--lm-bg);
            color: var(--lm-text);
        }

        [data-testid="stHeader"] {
            display: none;
        }

        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }

        .block-container {
            padding-top: 1rem;
            padding-bottom: 3rem;
            max-width: 1500px;
        }

        [data-testid="stSidebar"] {
            background: #121827;
            border-right: 1px solid rgba(255, 255, 255, 0.07);
            display: block !important;
            visibility: visible !important;
            transform: none !important;
        }

        [data-testid="stSidebar"] * {
            color: #ffffff !important;
        }

        [data-testid="stSidebar"] [data-testid="stImage"] {
            display: flex;
            justify-content: flex-start;
            align-items: center;
            margin-top: 8px;
            margin-bottom: 6px;
            width: 100%;
        }

        [data-testid="stSidebar"] img {
            display: block;
            width: 44px !important;
            height: 44px !important;
            object-fit: contain;
            margin-left: 2px;
            margin-right: 0;
            padding: 6px;
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.08);
            box-shadow: 0 12px 28px rgba(0, 0, 0, 0.22);
        }

        [data-testid="stSidebar"] h1 {
            font-size: 15px;
            font-weight: 800;
            text-align: left;
            margin: 4px 0 8px 2px;
        }

        [data-testid="stSidebar"] h3 {
            color: #ffffff !important;
            font-size: 1.17em;
            font-weight: 800;
            line-height: 1.4;
            margin: 1em 0 0.5em 0;
            text-align: left;
        }

        [data-testid="stSidebar"] [data-testid="stAlert"] {
            margin: 0 0 16px 0;
            padding: 8px 10px;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
        }

        [data-testid="stSidebar"] [data-testid="stAlert"] p {
            font-size: 11px !important;
            line-height: 1.2 !important;
        }

        .sidebar-section-title {
            margin: 12px 0 6px 4px;
            padding: 0;
            color: #9aa7bd !important;
            font-size: 11px;
            font-weight: 850;
            letter-spacing: .01em;
            line-height: 1.2;
        }

        .sidebar-section-title.settings {
            margin-top: 12px;
        }

        [data-testid="stSidebar"] [class*="st-key-nav_item_"] button {
            display: flex !important;
            align-items: center !important;
            justify-content: flex-start !important;
            min-height: 30px !important;
            width: 100% !important;
            margin: 0 0 3px 0 !important;
            padding: 6px 9px !important;
            border: 1px solid transparent !important;
            border-radius: 5px !important;
            background: transparent !important;
            color: #dce4f2 !important;
            box-shadow: none !important;
            text-align: left !important;
            transition: background .15s ease, color .15s ease, transform .15s ease !important;
        }

        [data-testid="stSidebar"] [class*="st-key-nav_item_"] button:hover {
            background: rgba(255, 255, 255, 0.08) !important;
            color: #ffffff !important;
            transform: translateX(2px);
        }

        [data-testid="stSidebar"] [class*="st-key-nav_item_active_"] button,
        [data-testid="stSidebar"] [class*="st-key-nav_item_active_"] button:hover {
            background: #ffffff !important;
            border-color: #ffffff !important;
            color: #111827 !important;
            box-shadow: 0 10px 22px rgba(0, 0, 0, 0.20) !important;
            transform: none !important;
        }

        [data-testid="stSidebar"] [class*="st-key-nav_item_"] button div,
        [data-testid="stSidebar"] [class*="st-key-nav_item_"] button p,
        [data-testid="stSidebar"] [class*="st-key-nav_item_"] button span {
            width: 100% !important;
            margin: 0 !important;
            color: inherit !important;
            font-size: 11px !important;
            font-weight: 800 !important;
            line-height: 1.15 !important;
            text-align: left !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        [data-testid="stSidebar"] [class*="st-key-nav_item_active_"] button div,
        [data-testid="stSidebar"] [class*="st-key-nav_item_active_"] button p,
        [data-testid="stSidebar"] [class*="st-key-nav_item_active_"] button span {
            color: #111827 !important;
            font-weight: 900 !important;
        }
        [data-testid="stSidebar"] .st-key-btn_logout_sidebar button {
            min-height: 32px;
            margin-top: 10px;
            color: #ffffff !important;
            background: #263348 !important;
            border: 1px solid rgba(255, 255, 255, 0.14) !important;
            border-radius: 6px !important;
            box-shadow: none !important;
        }

        [data-testid="stSidebar"] .st-key-btn_logout_sidebar button:hover {
            color: #ffffff !important;
            background: #334155 !important;
            border-color: rgba(255, 255, 255, 0.24) !important;
        }

        .st-key-payment_destination_card {
            padding: 14px;
            border: 1px solid var(--lm-border);
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 10px 24px rgba(31, 41, 51, 0.07);
        }

        .st-key-payment_destination_card div[role="radiogroup"] {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            border: 0;
            background: transparent;
        }

        .st-key-payment_destination_card label[data-baseweb="radio"] {
            min-height: 58px;
            margin: 0;
            padding: 13px 14px;
            border: 1px solid #cdd8e3;
            border-radius: 8px;
            background: #f8fbfd;
            box-shadow: 0 4px 12px rgba(31, 41, 51, 0.04);
            transition: all 0.16s ease;
        }

        .st-key-payment_destination_card label[data-baseweb="radio"]:hover {
            border-color: var(--lm-primary);
            background: #eefbfc;
            transform: translateY(-1px);
            box-shadow: 0 10px 20px rgba(15, 156, 167, 0.12);
        }

        .st-key-payment_destination_card label[data-baseweb="radio"] p {
            color: var(--lm-primary-dark) !important;
            font-weight: 850 !important;
            font-size: 13px !important;
            line-height: 1.25;
        }

        .st-key-payment_destination_card label[data-baseweb="radio"] > div:first-child {
            margin-right: 8px;
        }

        .module-subtitle {
            margin: -4px 0 22px 0;
            padding: 13px 16px;
            border: 1px solid var(--lm-border);
            border-left: 5px solid var(--lm-primary);
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 8px 20px rgba(31, 41, 51, 0.06);
        }

        .module-subtitle strong {
            display: block;
            color: var(--lm-primary-dark);
            font-size: 20px;
            font-weight: 850;
            text-align: left;
        }

        @media (max-width: 900px) {
            .st-key-payment_destination_card div[role="radiogroup"] {
                grid-template-columns: 1fr;
            }
        }

        h1, h2, h3 {
            color: var(--lm-primary-dark);
            letter-spacing: 0;
        }

        h1 {
            font-size: 34px;
            font-weight: 850;
            margin-bottom: 1.2rem;
        }

        h2, h3 {
            font-weight: 800;
        }

        div[data-testid="stTabs"] button[role="tab"] {
            height: 44px;
            padding: 0 16px;
            border-radius: 6px;
            color: var(--lm-muted);
            font-weight: 800;
        }

        div[data-testid="stTabs"] button[aria-selected="true"] {
            background: linear-gradient(90deg, var(--lm-primary), var(--lm-accent));
            color: white;
            box-shadow: 0 8px 18px rgba(0, 109, 119, 0.22);
        }

        div[data-testid="stTabs"] button[role="tab"] p {
            font-size: 15px;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--lm-border);
            border-radius: 8px;
        }

        [data-testid="stMetric"] {
            padding: 16px 18px;
            border: 1px solid var(--lm-border);
            border-radius: 8px;
            background: var(--lm-panel);
            box-shadow: 0 10px 26px rgba(7, 59, 76, 0.06);
        }

        [data-testid="stMetricLabel"] p {
            color: var(--lm-muted);
            font-weight: 800;
        }

        [data-testid="stMetricValue"] {
            color: var(--lm-primary-dark);
            font-weight: 850;
        }

        .stButton > button,
        .stFormSubmitButton > button {
            min-height: 42px;
            border: 1px solid rgba(0, 109, 119, 0.2);
            border-radius: 6px;
            background: #ffffff;
            color: var(--lm-primary-dark);
            font-weight: 800;
            box-shadow: 0 6px 16px rgba(7, 59, 76, 0.08);
            transition: all 0.15s ease;
        }

        .stButton > button:hover,
        .stFormSubmitButton > button:hover {
            border-color: var(--lm-primary);
            color: var(--lm-primary);
            transform: translateY(-1px);
            box-shadow: 0 10px 20px rgba(7, 59, 76, 0.12);
        }

        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {
            border: 0;
            background: linear-gradient(90deg, var(--lm-primary), var(--lm-accent));
            color: white;
        }

        .stTextInput input,
        .stNumberInput input,
        .stDateInput input,
        div[data-baseweb="select"] > div,
        div[role="radiogroup"] {
            border-radius: 6px;
            border-color: #c9dce2;
            background: #ffffff;
        }

        label p {
            color: var(--lm-primary-dark);
            font-weight: 750;
        }

        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            border: 1px solid var(--lm-border);
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 10px 24px rgba(7, 59, 76, 0.06);
        }

        [data-testid="stAlert"] {
            border-radius: 8px;
            border: 1px solid rgba(0, 109, 119, 0.14);
        }

        hr {
            margin: 1.6rem 0;
            border-color: var(--lm-border);
        }

        .stMarkdown div[style*="background-color:#1E6F5C"] {
            border-radius: 8px !important;
            box-shadow: 0 12px 28px rgba(7, 59, 76, 0.18);
        }

        @media (max-width: 900px) {
            .block-container {
                padding-top: 1rem;
            }

            h1 {
                font-size: 26px;
            }

            div[data-testid="stTabs"] button[role="tab"] {
                padding: 0 10px;
            }
        }
    </style>
    """, unsafe_allow_html=True)
    components.html(
        """
        <script>
        (function keepSidebarOpen() {
            const doc = window.parent.document;
            try {
                Object.keys(window.parent.localStorage || {}).forEach(function(key) {
                    if (key.toLowerCase().includes("sidebar")) {
                        window.parent.localStorage.removeItem(key);
                    }
                });
            } catch (error) {}

            let tries = 0;
            const timer = setInterval(function() {
                tries += 1;
                const sidebar = doc.querySelector('[data-testid="stSidebar"]');
                const isHidden = !sidebar || sidebar.getBoundingClientRect().width < 80;
                const openButton =
                    doc.querySelector('[data-testid="collapsedControl"]') ||
                    doc.querySelector('button[aria-label="Open sidebar"]') ||
                    doc.querySelector('button[aria-label="Expand sidebar"]') ||
                    Array.from(doc.querySelectorAll("button")).find(function(button) {
                        return /open sidebar|expand sidebar|mostrar sidebar|abrir sidebar/i.test(button.getAttribute("aria-label") || button.title || button.textContent || "");
                    });

                if (isHidden && openButton) {
                    openButton.click();
                }
                if (!isHidden || tries > 30) {
                    clearInterval(timer);
                }
            }, 100);
            if (window.parent.__lmSidebarObserver) {
                window.parent.__lmSidebarObserver.disconnect();
            }
            window.parent.__lmSidebarObserver = new MutationObserver(function() {
                const sidebar = doc.querySelector('[data-testid="stSidebar"]');
                const openButton = doc.querySelector('[data-testid="collapsedControl"]');
                if ((!sidebar || sidebar.getBoundingClientRect().width < 80) && openButton) {
                    openButton.click();
                }
            });
            window.parent.__lmSidebarObserver.observe(doc.body, { childList: true, subtree: true, attributes: true });
        })();
        </script>
        """,
        height=0,
        scrolling=False
    )

def login():
    aplicar_estilos_login()
    st.markdown("""
    <div class="login-hero">
        <h1>Las Marías</h1>
        <p>Complejo recreativo, piscina y control de ventas</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1.2, 1, 1.2])
    with col2:
        with st.container(key="login_card"):
            st.markdown("""
            <h2 class="login-card-title">Inicio de sesión</h2>
            <p class="login-card-subtitle">Ingresa con tu usuario para continuar</p>
            """, unsafe_allow_html=True)
            with st.form("login_form"):
                username = st.text_input("Usuario")
                password = st.text_input("Contraseña", type="password")
                login_submit = st.form_submit_button("Ingresar", use_container_width=True)
            components.html(
                """
                <script>
                (function bindLoginEnter() {
                    const doc = window.parent.document;
                    const user = Array.from(doc.querySelectorAll('input')).find(input => input.getAttribute('aria-label') === 'Usuario');
                    const pass = Array.from(doc.querySelectorAll('input')).find(input => input.getAttribute('aria-label') === 'Contraseña');
                    if (!user || !pass) {
                        setTimeout(bindLoginEnter, 250);
                        return;
                    }
                    if (!user.dataset.lmEnterBound) {
                        user.dataset.lmEnterBound = "1";
                        user.addEventListener("keydown", function(event) {
                            if (event.key === "Enter") {
                                event.preventDefault();
                                event.stopPropagation();
                                pass.focus();
                            }
                        }, true);
                    }
                })();
                </script>
                """,
                height=0,
                scrolling=False
            )
            if login_submit:
                user_data = ejecutar_query("SELECT rol FROM usuarios WHERE username=? AND password=?", (username, password), fetch=True)
                if user_data:
                    token = secrets.token_urlsafe(32)
                    ejecutar_query("UPDATE usuarios SET login_token=? WHERE username=?", (token, username), commit=True)
                    st.session_state['autenticado'] = True
                    st.session_state['usuario'] = username
                    st.session_state['rol'] = user_data[0][0]
                    guardar_sesion_en_url(username, user_data[0][0], token)
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos")

def logout():
    if st.session_state['usuario']:
        ejecutar_query("UPDATE usuarios SET login_token=NULL WHERE username=?", (st.session_state['usuario'],), commit=True)
    st.session_state['autenticado'] = False
    st.session_state['usuario'] = ""
    st.session_state['rol'] = ""
    st.session_state['carrito'] = []
    limpiar_sesion_url()
    st.rerun()

if not st.session_state['autenticado']:
    login()
else:
    aplicar_estilos_sistema()
    logo_sistema = obtener_config("logo_path")
    if logo_sistema and Path(logo_sistema).exists():
        st.sidebar.image(logo_sistema, width=92)
    else:
        st.sidebar.image("https://cdn-icons-png.flaticon.com/512/456/456212.png", width=80)
    st.sidebar.title(f"Hola, {st.session_state['usuario']}")
    st.sidebar.info(f"Rol: {st.session_state['rol']}")
    if st.session_state.get("auto_print_payload"):
        payload_print_global = st.session_state.pop("auto_print_payload")
        imprimir_nota_automatica(
            payload_print_global["cliente"],
            payload_print_global["items"],
            payload_print_global["total"],
            payload_print_global["tipo"],
            payload_print_global.get("vendedor", "")
        )
    if st.session_state['rol'] == "Administrador":
        opciones_menu = [
            "🛒 Ventas y Cocina",
            "📦 Control de Stock",
            "🏊‍♂️ Control de Piscina",
            "⚽ Control de Cancha",
            "🏢 Reservación de Local",
            "💰 Caja y Reportes",
            "👥 Trabajadores",
            "⚙️ Configuración"
        ]
        titulos_modulos = {
            opciones_menu[0]: "Generar Nueva Venta / Crédito",
            opciones_menu[1]: "Control e Ingreso de Mercadería",
            opciones_menu[2]: "Ingreso y Control de la Piscina",
            opciones_menu[3]: "Reservas de Cancha",
            opciones_menu[4]: "Reservación de Local",
            opciones_menu[5]: "Control de Finanzas y Cierre de Caja Diaria",
            opciones_menu[6]: "Gestión de Personal",
            opciones_menu[7]: "Configuración del Sistema"
        }
        modulo_actual = resolver_modulo_admin(opciones_menu)
        for key_menu in ("modulo_admin_principal_selector", "modulo_admin_ajustes_selector"):
            if key_menu in st.session_state:
                del st.session_state[key_menu]
        secciones_sidebar = [
            ("Menú principal", opciones_menu[:6]),
            ("Ajustes", opciones_menu[6:]),
        ]
        iconos_sidebar = {
            opciones_menu[0]: "🛒",
            opciones_menu[1]: "📦",
            opciones_menu[2]: "🏊",
            opciones_menu[3]: "⚽",
            opciones_menu[4]: "🏢",
            opciones_menu[5]: "💰",
            opciones_menu[6]: "👥",
            opciones_menu[7]: "⚙️",
        }
        etiquetas_sidebar = {opcion: opcion.split(" ", 1)[1] if " " in opcion else opcion for opcion in opciones_menu}
        for nombre_seccion, opciones_seccion in secciones_sidebar:
            clase_seccion = " settings" if nombre_seccion != "Menú principal" else ""
            st.sidebar.markdown(f"<div class='sidebar-section-title{clase_seccion}'>{nombre_seccion}</div>", unsafe_allow_html=True)
            for opcion_menu in opciones_seccion:
                idx_menu = opciones_menu.index(opcion_menu)
                estado_nav = "active" if opcion_menu == modulo_actual else "idle"
                etiqueta_nav = f"{iconos_sidebar.get(opcion_menu, '')}  {etiquetas_sidebar.get(opcion_menu, opcion_menu)}"
                with st.sidebar.container(key=f"nav_item_{estado_nav}_{idx_menu}"):
                    st.button(
                        etiqueta_nav,
                        key=f"btn_nav_{idx_menu}",
                        use_container_width=True,
                        on_click=activar_modulo_admin,
                        args=(opcion_menu,)
                    )
        modulo_actual = st.session_state["modulo_admin_activo"]
        if st.sidebar.button("🔓 Cerrar Sesión", type="secondary", use_container_width=True, key="btn_logout_sidebar"):
            logout()

        st.title("Panel de Administración - LAS MARÍAS")
        st.markdown(
            f"""
            <div class="module-subtitle">
                <strong>{titulos_modulos[modulo_actual]}</strong>
            </div>
            """,
            unsafe_allow_html=True
        )
        
        # ---------------------------------------------------------------------
        # PESTAÑA 1: VENTAS Y COCINA (SOLUCIÓN DEFINITIVA SIN COMPROBANTES FANTASMAS)
        # ---------------------------------------------------------------------
        if modulo_actual == opciones_menu[0]:
            # --- DETECTOR DE CAMBIO DE FORMULARIO/PESTAÑA ---
            # Si el usuario hace clic en otra pestaña, forzamos que el ticket desaparezca de la memoria
            if "pestaña_actual" not in st.session_state:
                st.session_state["pestaña_actual"] = 0
            
            # Si detecta que cambió de pestaña (o si estás renderizando este bloque de código limpio)
            # Nos aseguramos de inicializar las variables del ticket controlado
            if "ticket_listo" not in st.session_state:
                st.session_state["ticket_listo"] = False
                st.session_state["ticket_cliente"] = ""
                st.session_state["ticket_items"] = []
                st.session_state["ticket_total"] = 0.0
                st.session_state["ticket_tipo"] = ""
            if st.session_state.get("auto_print_payload"):
                payload_print = st.session_state.pop("auto_print_payload")
                imprimir_nota_automatica(
                    payload_print["cliente"],
                    payload_print["items"],
                    payload_print["total"],
                    payload_print["tipo"],
                    payload_print.get("vendedor", "")
                )

            col_v1, col_v2 = st.columns([1.2, 1])
            
            # 1. OBTENER DATOS ACTUALIZADOS DE LA BASE DE DATOS
            productos = ejecutar_query("SELECT nombre, precio, stock, proveedor FROM inventario WHERE stock > 0", fetch=True)
            dict_productos = {p[0]: {"precio": p[1], "stock": p[2], "proveedor": p[3]} for p in productos}
            
            # Cargar los clientes que actualmente tienen deudas activas para el buscador
            lista_clientes_base = clientes_credito_abiertos()
            
            # --- COLUMNA IZQUIERDA: AGREGAR PRODUCTOS Y MONITOR DE COCINA ---
            with col_v1:
                if dict_productos:
                    if "venta_producto_nonce" not in st.session_state:
                        st.session_state["venta_producto_nonce"] = 0
                    producto_widget_key = f"sb_producto_venta_{st.session_state['venta_producto_nonce']}"
                    cantidad_widget_key = f"num_cantidad_venta_{st.session_state['venta_producto_nonce']}"
                    components.html(
                        """
                        <script>
                        setTimeout(() => {
                            const doc = window.parent.document;
                            const labels = [...doc.querySelectorAll("label")];
                            const label = labels.find((item) => item.textContent.includes("Seleccione el Producto/Plato"));
                            const container = label ? label.closest('[data-testid="stWidgetLabel"]')?.parentElement : null;
                            const target = container?.querySelector('[role="combobox"], input');
                            if (target) {
                                target.focus();
                                target.click();
                            }
                        }, 250);
                        </script>
                        """,
                        height=0,
                    )
                    prod_sel = st.selectbox("Seleccione el Producto/Plato", [""] + list(dict_productos.keys()), key=producto_widget_key)
                    cant = st.number_input("Cantidad", min_value=1, value=1, key=cantidad_widget_key)
                    
                    if prod_sel:
                        stock_disp = dict_productos[prod_sel]["stock"]
                        precio_unid = dict_productos[prod_sel]["precio"]
                        proveedor_prod = dict_productos[prod_sel]["proveedor"]
                        
                        st.caption(f"Stock disponible: {stock_disp} unidades | Precio: S/. {precio_unid:.2f} | Tipo: {proveedor_prod}")
                        
                        if st.button("➕ Añadir a la Lista Actual", use_container_width=True):
                            cant_en_carrito = sum([item['cantidad'] for item in st.session_state['carrito'] if item['producto'] == prod_sel])
                            if stock_disp >= (cant + cant_en_carrito):
                                st.session_state['carrito'].append({
                                    "producto": prod_sel,
                                    "amount": cant, 
                                    "cantidad": cant,
                                    "precio_unitario": precio_unid,
                                    "subtotal": precio_unid * cant,
                                    "proveedor": proveedor_prod
                                })
                                st.toast(f"¡{prod_sel} añadido!")
                                st.session_state["venta_producto_nonce"] += 1
                                st.rerun()
                            else:
                                st.error("No puedes añadir esa cantidad, supera el stock disponible en el inventario.")
                else:
                    st.info("No hay productos con stock registrado en el inventario.")
                
                st.markdown("---")
                st.subheader("👨‍🍳 Monitor de Cocina (Platos Pendientes)")
                render_monitor_cocina_admin_tabla()
                render_modificar_notas(dict_productos)
                if False:
                    df_pend = pd.DataFrame(pendientes, columns=["ID Pedido", "Cliente / Mesa", "Plato", "Cantidad", "Fecha/Hora"])
                    st.dataframe(df_pend, use_container_width=True, hide_index=True)
                    
                    st.markdown("##### Editor anterior desactivado")
                    opcion_busqueda = st.radio("Buscar pedido por:", ["ID de Pedido", "Nombre del Cliente"], horizontal=True, key="rad_buscar_cocina")
                    id_seleccionado = None
                    
                    if opcion_busqueda == "ID de Pedido":
                        id_ingresado = st.number_input("Ingrese ID del Pedido:", min_value=1, step=1, key="num_id_cocina")
                        existe = ejecutar_query("SELECT id FROM cocina WHERE id=? AND estado='PENDIENTE'", (id_ingresado,), fetch=True)
                        if existe:
                            id_seleccionado = id_ingresado
                    else:
                        clientes_en_cocina = sorted(list(set([p[1] for p in pendientes])))
                        cli_sel = st.selectbox("Seleccione el Cliente:", clientes_en_cocina, key="sb_cliente_cocina")
                        platos_cliente = [p for p in pendientes if p[1] == cli_sel]
                        dict_platos_cli = {f"ID {p[0]} - {p[2]} (Cant: {p[3]})": p[0] for p in platos_cliente}
                        plato_elegido = st.selectbox("Seleccione el pedido específico a modificar:", list(dict_platos_cli.keys()), key="sb_pedido_cocina")
                        if plato_elegido:
                            id_seleccionado = dict_platos_cli[plato_elegido]
                    
                    if id_seleccionado:
                        info_actual = ejecutar_query("SELECT plato, cantidad, cliente FROM cocina WHERE id=?", (id_seleccionado,), fetch=True)[0]
                        plato_act, cant_act, cliente_act = info_actual
                        
                        st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px; margin-bottom:10px;'>"
                                    f"<strong>Editando Pedido ID {id_seleccionado}</strong> ({cliente_act})<br>Plato actual: {plato_act} | Cantidad: {cant_act}</div>", unsafe_allow_html=True)
                        
                        col_ed1, col_ed2 = st.columns(2)
                        with col_ed1:
                            lista_claves_prod = list(dict_productos.keys())
                            idx_defecto = lista_claves_prod.index(plato_act) if plato_act in lista_claves_prod else 0
                            nuevo_plato = st.selectbox("Cambiar Producto/Plato por:", lista_claves_prod, index=idx_defecto, key="sb_cambio_plato_cocina")
                        with col_ed2:
                            nueva_cantidad = st.number_input("Modificar Cantidad:", min_value=1, value=int(cant_act), key="num_cambio_cant_cocina")
                        
                        col_btn1, col_btn2, col_btn3 = st.columns(3)
                        with col_btn1:
                            if st.button("💾 Guardar Cambios", use_container_width=True, type="primary", key="btn_save_cocina"):
                                ejecutar_query("UPDATE inventario SET stock = stock + ? WHERE nombre=?", (cant_act, plato_act), commit=True)
                                stock_nuevo_prod = ejecutar_query("SELECT stock FROM inventario WHERE nombre=?", (nuevo_plato,), fetch=True)[0][0]
                                if stock_nuevo_prod >= nueva_cantidad:
                                    ejecutar_query("UPDATE cocina SET plato=?, cantidad=? WHERE id=?", (nuevo_plato, nueva_cantidad, id_seleccionado), commit=True)
                                    ejecutar_query("UPDATE inventario SET stock = stock - ? WHERE nombre=?", (nueva_cantidad, nuevo_plato), commit=True)
                                    
                                    precio_nuevo = dict_productos[nuevo_plato]["precio"] if nuevo_plato in dict_productos else 0.0
                                    nuevo_subtotal = precio_nuevo * nueva_cantidad
                                    
                                    en_credito = ejecutar_query("SELECT id FROM detalle_creditos WHERE cliente=? AND producto=?", (cliente_act, plato_act), fetch=True)
                                    if en_credito:
                                        ejecutar_query("UPDATE detalle_creditos SET producto=?, cantidad=?, precio_unitario=?, subtotal=? WHERE cliente=? AND producto=?", 
                                                       (nuevo_plato, nueva_cantidad, precio_nuevo, nuevo_subtotal, cliente_act, plato_act), commit=True)
                                        nueva_suma_total = ejecutar_query("SELECT SUM(subtotal) FROM detalle_creditos WHERE cliente=?", (cliente_act,), fetch=True)[0][0] or 0
                                        ejecutar_query("UPDATE ventas SET total=? WHERE cliente=? AND estado='CREDITO'", (nueva_suma_total, cliente_act), commit=True)
                                    
                                    st.success("¡Pedido actualizado perfectamente!")
                                    st.rerun()
                                else:
                                    ejecutar_query("UPDATE inventario SET stock = stock - ? WHERE nombre=?", (cant_act, plato_act), commit=True)
                                    st.error(f"No hay stock suficiente. Stock disponible: {stock_nuevo_prod}")
                                    
                        with col_btn2:
                            if st.button("🗑️ Eliminar Plato", use_container_width=True, key="btn_del_plato_cocina"):
                                ejecutar_query("UPDATE inventario SET stock = stock + ? WHERE nombre=?", (cant_act, plato_act), commit=True)
                                ejecutar_query("DELETE FROM cocina WHERE id=?", (id_seleccionado,), commit=True)
                                
                                en_credito = ejecutar_query("SELECT id FROM detalle_creditos WHERE cliente=? AND producto=?", (cliente_act, plato_act), fetch=True)
                                if en_credito:
                                    ejecutar_query("DELETE FROM detalle_creditos WHERE cliente=? AND producto=?", (cliente_act, plato_act), commit=True)
                                    nueva_suma_total = ejecutar_query("SELECT SUM(subtotal) FROM detalle_creditos WHERE cliente=?", (cliente_act,), fetch=True)[0][0] or 0
                                    if nueva_suma_total > 0:
                                        ejecutar_query("UPDATE ventas SET total=? WHERE cliente=? AND estado='CREDITO'", (nueva_suma_total, cliente_act), commit=True)
                                    else:
                                        ejecutar_query("DELETE FROM ventas WHERE cliente=? AND estado='CREDITO'", (cliente_act,), commit=True)
                                
                                st.warning("¡Plato anulado con éxito!")
                                st.rerun()
                        with col_btn3:
                            if st.button("Cancelar", use_container_width=True, key="btn_cancel_edit_cocina"):
                                st.rerun()
                elif False:
                    st.success("¡Cocina al día!")

                with st.expander("Ver historial de platos entregados", expanded=False):
                    mesero_hist_sql = mesero_cocina_sql("c")
                    historial_cocina = ejecutar_query(
                        f"SELECT c.id, c.cliente, c.plato, c.cantidad, {mesero_hist_sql} AS mesero, COALESCE(c.fecha_entrega, c.fecha_hora), c.fecha_hora FROM cocina c WHERE c.estado='ENTREGADO' ORDER BY COALESCE(c.fecha_entrega, c.fecha_hora) DESC LIMIT 80",
                        fetch=True
                    )
                    if historial_cocina:
                        df_hist_cocina = pd.DataFrame(
                            historial_cocina,
                            columns=["ID Pedido", "Cliente / Mesa", "Plato", "Cantidad", "Mesero", "Hora de entrega", "Hora de pedido"]
                        )
                        df_hist_cocina["Tiempo de entrega"] = df_hist_cocina.apply(
                            lambda fila: calcular_tiempo_entrega(fila["Hora de pedido"], fila["Hora de entrega"]),
                            axis=1
                        )
                        df_hist_cocina = df_hist_cocina[
                            ["ID Pedido", "Cliente / Mesa", "Plato", "Cantidad", "Mesero", "Tiempo de entrega", "Hora de entrega", "Hora de pedido"]
                        ]
                        st.dataframe(df_hist_cocina, use_container_width=True, hide_index=True)
                    else:
                        st.info("Aún no hay platos entregados para mostrar.")

            # --- COLUMNA DERECHA: CARRITO DE COMPRAS Y OPCIONES DE PAGO ---
            with col_v2:
                st.subheader("📋 Lista de compra del Cliente")
                with st.container(key="payment_destination_card"):
                    tipo_pago = st.radio(
                        "Destino de la Venta:",
                        ["PAGADO AL INSTANTE", "LLEVAR A CUENTA CRÉDITO (Anotar en lista histórica)"],
                        key="rad_tipo_pago_maestro",
                        horizontal=True
                    )
                
                # Buscador inteligente de clientes para la cuenta de crédito
                cliente_final = "GENERAL"
                if tipo_pago == "LLEVAR A CUENTA CRÉDITO (Anotar en lista histórica)":
                    opciones_clientes = ["➕ AGREGAR NUEVO CLIENTE"] + lista_clientes_base
                    cliente_elegido_combo = st.selectbox("Seleccione Cliente Existente o agregue uno:", opciones_clientes, key="sb_combo_clientes_credito")
                    
                    if cliente_elegido_combo == "➕ AGREGAR NUEVO CLIENTE":
                        cliente_input = st.text_input("Escriba el Nombre del Nuevo Cliente:", value="", key="txt_nuevo_cliente_cred")
                        cliente_final = cliente_input.strip().upper()
                    else:
                        cliente_final = cliente_elegido_combo.strip().upper()
                        st.info(f"Se añadirán los productos a la cuenta corriente de: **{cliente_final}**")
                else:
                    venta_form_nonce = st.session_state["venta_form_nonce"]
                    cliente_input = st.text_input("Nombre del Cliente / Mesa:", value="", key=f"txt_cliente_mostrador_{venta_form_nonce}")
                    cliente_final = cliente_input.strip().upper() if cliente_input.strip() else "GENERAL"

                st.markdown("### Atendido por")
                venta_form_nonce = st.session_state["venta_form_nonce"]
                atendido_tipo, atendido_nombre = seleccionar_trabajador("Mesero o Trabajador", ("Mesero", "Trabajador"), f"venta_atendido_{venta_form_nonce}")
                metodo_pago_venta, receptor_tipo_venta, receptor_nombre_venta = seleccionar_pago_receptor(
                    f"venta_{venta_form_nonce}",
                    incluir_mesero=True,
                    receptor_preseleccionado={"tipo": atendido_tipo, "nombre": atendido_nombre}
                )
                
                # Renderizar la tabla del carrito si tiene elementos
                if st.session_state['carrito']:
                    df_carrito = pd.DataFrame(st.session_state['carrito'])
                    df_carrito_vista = df_carrito[["producto", "cantidad", "subtotal"]].rename(columns={
                        "producto": "Producto",
                        "cantidad": "Cantidad",
                        "subtotal": "Total Parcial"
                    })
                    df_carrito_vista = formatear_montos_df(df_carrito_vista, ["Total Parcial"])
                    st.table(df_carrito_vista)
                    
                    total_carrito = df_carrito["subtotal"].sum()
                    st.markdown(f"### **Total a Pagar: S/. {total_carrito:.2f}**")
                    
                    col_c1, col_c2 = st.columns(2)
                    with col_c1:
                        if st.button("❌ Vaciar Lista", use_container_width=True, key="btn_clear_carrito"):
                            st.session_state['carrito'] = []
                            st.rerun()
                            
                    with col_c2:
                        if st.button("PROCESAR Y COBRAR TODO", type="primary", use_container_width=True, key="btn_procesar_pago_final"):
                            if not cliente_final or cliente_final == "➕ AGREGAR NUEVO CLIENTE":
                                st.error("Por favor, ingrese o seleccione un nombre de cliente válido.")
                            else:
                                fecha_actual = fecha_hora_actual()
                                
                                # A. Restar del inventario y mandar a cocina si aplica
                                for item in st.session_state['carrito']:
                                    st_act = ejecutar_query("SELECT stock FROM inventario WHERE nombre=?", (item['producto'],), fetch=True)[0][0]
                                    ejecutar_query("UPDATE inventario SET stock=? WHERE nombre=?", (st_act - item['cantidad'], item['producto']), commit=True)
                                    
                                    if str(item['proveedor']).strip().upper() == "INTERNO":
                                        ejecutar_query("INSERT INTO cocina (cliente, plato, cantidad, fecha_hora, estado, mesero_nombre) VALUES (?,?,?,?,?,?)",
                                                       (cliente_final, item['producto'], item['cantidad'], fecha_actual, "PENDIENTE", atendido_nombre), commit=True)
                                
                                # B. Si es cuenta de crédito
                                if tipo_pago == "LLEVAR A CUENTA CRÉDITO (Anotar en lista histórica)":
                                    existe_cabecera = ejecutar_query("SELECT id, total FROM ventas WHERE cliente=? AND estado='CREDITO'", (cliente_final,), fetch=True)
                                    
                                    if existe_cabecera:
                                        id_venta_existente, total_antiguo = existe_cabecera[0]
                                        nuevo_total_maestro = total_antiguo + total_carrito
                                        ejecutar_query(
                                            "UPDATE ventas SET total=?, atendido_por_tipo=?, atendido_por_nombre=?, metodo_pago=?, receptor_tipo=?, receptor_nombre=?, origen='Cuenta Corriente' WHERE id=?",
                                            (nuevo_total_maestro, atendido_tipo, atendido_nombre, metodo_pago_venta, receptor_tipo_venta, receptor_nombre_venta, id_venta_existente),
                                            commit=True
                                        )
                                    else:
                                        ejecutar_query(
                                            "INSERT INTO ventas (cliente, total, estado, fecha, estado_caja, atendido_por_tipo, atendido_por_nombre, metodo_pago, receptor_tipo, receptor_nombre, origen) VALUES (?,?,?,?, 'ABIERTO', ?,?,?,?,?, 'Cuenta Corriente')",
                                            (cliente_final, total_carrito, "CREDITO", fecha_actual, atendido_tipo, atendido_nombre, metodo_pago_venta, receptor_tipo_venta, receptor_nombre_venta),
                                            commit=True
                                        )
                                    
                                    for item in st.session_state['carrito']:
                                        mesero_credito = atendido_nombre if atendido_tipo == "Mesero" else ""
                                        trabajador_credito = atendido_nombre if atendido_tipo != "Mesero" else ""
                                        ejecutar_query("INSERT INTO detalle_creditos (cliente, producto, cantidad, precio_unitario, subtotal, fecha, origen, mesero_nombre, trabajador_nombre) VALUES (?,?,?,?,?,?, 'Ventas', ?, ?)",
                                                       (cliente_final, item['producto'], item['cantidad'], item['precio_unitario'], item['subtotal'], fecha_actual, mesero_credito, trabajador_credito), commit=True)
                                    
                                    st.success(f"¡Cargado con éxito al crédito de {cliente_final}!")
                                    st.session_state['carrito'] = []
                                    limpiar_formulario_venta()
                                    st.rerun()
                                
                                # C. Si es pago al instante (CONTROLADO LOCALMENTE)
                                else:
                                    ejecutar_query(
                                        "INSERT INTO ventas (cliente, total, estado, fecha, estado_caja, atendido_por_tipo, atendido_por_nombre, metodo_pago, receptor_tipo, receptor_nombre, origen) VALUES (?,?,?,?, 'ABIERTO', ?,?,?,?,?, 'Ventas')",
                                        (cliente_final, total_carrito, "PAGADO", fecha_actual, atendido_tipo, atendido_nombre, metodo_pago_venta, receptor_tipo_venta, receptor_nombre_venta),
                                        commit=True
                                    )
                                    
                                    ultimo_id_req = ejecutar_query("SELECT max(id) FROM ventas", fetch=True)
                                    venta_id = ultimo_id_req[0][0] if ultimo_id_req else 1
                                    
                                    for item in st.session_state['carrito']:
                                        ejecutar_query("INSERT INTO detalle_ventas (venta_id, producto, cantidad, precio_unitario, subtotal) VALUES (?,?,?,?,?)",
                                                       (venta_id, item['producto'], item['cantidad'], item['precio_unitario'], item['subtotal']), commit=True)
                                    
                                    encolar_impresion_nota(cliente_final, list(st.session_state['carrito']), total_carrito, "VENTA EN MOSTRADOR", atendido_nombre)
                                    
                                    st.session_state['carrito'] = []
                                    limpiar_formulario_venta()
                                    st.rerun()
                else:
                    st.info("La lista está vacía. Añade productos desde el panel izquierdo.")
                    
                    # --- HISTÓRICO: RESUMEN DE CUENTAS POR COBRAR ---
                    st.markdown("---")
                    st.subheader("📋 Resumen de Cuentas por Cobrar")
                    creditos = ejecutar_query("SELECT id, cliente, total, fecha FROM ventas WHERE estado='CREDITO'", fetch=True)
                    
                    if creditos:
                        df_cred = pd.DataFrame(creditos, columns=["ID Lista", "Cliente", "Monto Total", "Fecha"])
                        st.dataframe(formatear_montos_df(df_cred, ["Monto Total"]), use_container_width=True, hide_index=True)
                        
                        lista_clientes_deuda = sorted(list(set([c[1] for c in creditos])))
                        cliente_a_cobrar = st.selectbox("Seleccione el Cliente para revisar/liquidar cuenta:", lista_clientes_deuda, key="sb_cobrar_final")
                        
                        if cliente_a_cobrar:
                            detalles = ejecutar_query(
                                "SELECT id, origen, producto, cantidad, precio_unitario, subtotal FROM detalle_creditos WHERE cliente=? ORDER BY fecha ASC, id ASC",
                                (cliente_a_cobrar,),
                                fetch=True
                            )
                            
                            if detalles:
                                st.markdown(f"**Detalle de consumo real para: {cliente_a_cobrar}**")
                                df_detalles = pd.DataFrame(detalles, columns=["ID", "Origen", "Producto", "Cantidad", "Unidad P.", "Total parcial"])
                                df_detalles.insert(0, "Pagar", True)
                                df_editor_creditos = st.data_editor(
                                    formatear_montos_df(df_detalles, ["Unidad P.", "Total parcial"]),
                                    use_container_width=True,
                                    hide_index=True,
                                    disabled=["ID", "Origen", "Producto", "Cantidad", "Unidad P.", "Total parcial"],
                                    column_config={
                                        "Pagar": st.column_config.CheckboxColumn("Pagar", help="Desmarca lo que quedará pendiente."),
                                        "ID": None
                                    },
                                    key=f"editor_creditos_cobro_{cliente_a_cobrar}"
                                )
                                
                                ids_seleccionados_pago = [
                                    int(fila["ID"])
                                    for _, fila in df_editor_creditos.iterrows()
                                    if bool(fila["Pagar"])
                                ]
                                total_deuda = sum(
                                    float(det[5] or 0)
                                    for det in detalles
                                    if int(det[0]) in ids_seleccionados_pago
                                )
                                total_pendiente_post = sum(float(det[5] or 0) for det in detalles) - total_deuda
                                col_total_sel, col_total_pen = st.columns(2)
                                with col_total_sel:
                                    st.metric("Total seleccionado para cobrar", f"S/. {total_deuda:.2f}")
                                with col_total_pen:
                                    st.metric("Quedará pendiente", f"S/. {total_pendiente_post:.2f}")
                                
                                if not ids_seleccionados_pago:
                                    st.warning("Selecciona al menos un consumo para poder cobrar.")
                                elif st.button(f"💵 Cerrar Cuenta y Cobrar S/. {total_deuda:.2f}", type="primary", use_container_width=True, key="btn_liquidar_final"):
                                    items_boleta, total_deuda = liquidar_creditos_cliente(
                                        cliente_a_cobrar,
                                        metodo_pago_venta,
                                        receptor_tipo_venta,
                                        receptor_nombre_venta,
                                        atendido_nombre,
                                        ids_seleccionados_pago
                                    )
                                    encolar_impresion_nota(cliente_a_cobrar, items_boleta, total_deuda, "LIQUIDACION DE CREDITO", atendido_nombre)
                                    st.rerun()
                    else:
                        st.info("No hay deudas pendientes.")

                st.markdown("---")
                if False:
                    ventas_editables = ejecutar_query(
                        "SELECT id, cliente, total, estado, fecha FROM ventas WHERE estado IN ('PAGADO','CREDITO') AND COALESCE(estado_boleta,'ACTIVA')='ACTIVA' ORDER BY id DESC LIMIT 80",
                        fetch=True
                    )
                    if ventas_editables:
                        opciones_ventas = {f"Nota #{v[0]} - {v[1]} - S/. {v[2]:.2f} ({v[3]})": v[0] for v in ventas_editables}
                        venta_label = st.selectbox("Seleccione nota", list(opciones_ventas.keys()), key="sb_editar_nota_venta")
                        venta_editar_id = opciones_ventas[venta_label]
                        venta_info = ejecutar_query("SELECT cliente, estado FROM ventas WHERE id=?", (venta_editar_id,), fetch=True)[0]
                        cliente_actual_nota, estado_actual_nota = venta_info
                        nuevo_cliente_nota = st.text_input("Cliente", value=cliente_actual_nota, key="txt_cliente_edit_nota").strip().upper()
                        detalles_nota = ejecutar_query("SELECT id, producto, cantidad, precio_unitario, subtotal FROM detalle_ventas WHERE venta_id=?", (venta_editar_id,), fetch=True)
                        if not detalles_nota and estado_actual_nota == "CREDITO":
                            detalles_nota = ejecutar_query("SELECT id, producto, cantidad, precio_unitario, subtotal FROM detalle_creditos WHERE cliente=?", (cliente_actual_nota,), fetch=True)
                        if detalles_nota:
                            st.dataframe(pd.DataFrame(detalles_nota, columns=["ID Detalle", "Producto", "Cantidad", "Precio", "Subtotal"]), use_container_width=True, hide_index=True)
                            ids_detalle = {f"{d[1]} x {d[2]}": d[0] for d in detalles_nota}
                            detalle_sel = st.selectbox("Item a modificar/eliminar", list(ids_detalle.keys()), key="sb_item_edit_nota")
                            nueva_cant_item = st.number_input("Nueva cantidad", min_value=1, value=1, key="num_edit_cant_nota")
                            col_ne1, col_ne2 = st.columns(2)
                            with col_ne1:
                                if st.button("Modificar cantidad", use_container_width=True, key="btn_mod_cant_nota"):
                                    det_id = ids_detalle[detalle_sel]
                                    tabla_det = "detalle_creditos" if estado_actual_nota == "CREDITO" else "detalle_ventas"
                                    precio_det = ejecutar_query(f"SELECT precio_unitario FROM {tabla_det} WHERE id=?", (det_id,), fetch=True)[0][0]
                                    ejecutar_query(f"UPDATE {tabla_det} SET cantidad=?, subtotal=? WHERE id=?", (nueva_cant_item, precio_det * nueva_cant_item, det_id), commit=True)
                                    nuevo_total = ejecutar_query(f"SELECT SUM(subtotal) FROM {tabla_det} WHERE {'cliente=?' if tabla_det == 'detalle_creditos' else 'venta_id=?'}", (cliente_actual_nota if tabla_det == "detalle_creditos" else venta_editar_id,), fetch=True)[0][0] or 0
                                    ejecutar_query("UPDATE ventas SET cliente=?, total=? WHERE id=?", (nuevo_cliente_nota, nuevo_total, venta_editar_id), commit=True)
                                    marcar_notificacion_cocina(nuevo_cliente_nota, "Nota de venta modificada")
                                    st.session_state["ticket_cliente"] = nuevo_cliente_nota
                                    st.session_state["ticket_items"] = [{"producto": d[1], "cantidad": d[2], "subtotal": d[4]} for d in detalles_nota]
                                    st.session_state["ticket_total"] = nuevo_total
                                    st.session_state["ticket_tipo"] = "NOTA ACTUALIZADA"
                                    st.session_state["ticket_listo"] = True
                                    st.rerun()
                            with col_ne2:
                                if st.button("Eliminar item", use_container_width=True, key="btn_del_item_nota"):
                                    det_id = ids_detalle[detalle_sel]
                                    tabla_det = "detalle_creditos" if estado_actual_nota == "CREDITO" else "detalle_ventas"
                                    ejecutar_query(f"DELETE FROM {tabla_det} WHERE id=?", (det_id,), commit=True)
                                    nuevo_total = ejecutar_query(f"SELECT SUM(subtotal) FROM {tabla_det} WHERE {'cliente=?' if tabla_det == 'detalle_creditos' else 'venta_id=?'}", (cliente_actual_nota if tabla_det == "detalle_creditos" else venta_editar_id,), fetch=True)[0][0] or 0
                                    ejecutar_query("UPDATE ventas SET cliente=?, total=? WHERE id=?", (nuevo_cliente_nota, nuevo_total, venta_editar_id), commit=True)
                                    marcar_notificacion_cocina(nuevo_cliente_nota, "Producto eliminado de la nota")
                                    st.rerun()
                        if dict_productos:
                            prod_extra = st.selectbox("Agregar producto", [""] + list(dict_productos.keys()), key="sb_add_prod_nota")
                            cant_extra = st.number_input("Cantidad a agregar", min_value=1, value=1, key="num_add_prod_nota")
                            if st.button("Agregar a nota", use_container_width=True, key="btn_add_prod_nota") and prod_extra:
                                precio_extra = dict_productos[prod_extra]["precio"]
                                subtotal_extra = precio_extra * cant_extra
                                if estado_actual_nota == "CREDITO":
                                    ejecutar_query("INSERT INTO detalle_creditos (cliente, producto, cantidad, precio_unitario, subtotal, fecha, origen) VALUES (?,?,?,?,?,?, 'Ventas')", (nuevo_cliente_nota, prod_extra, cant_extra, precio_extra, subtotal_extra, fecha_hora_actual()), commit=True)
                                    nuevo_total = ejecutar_query("SELECT SUM(subtotal) FROM detalle_creditos WHERE cliente=?", (nuevo_cliente_nota,), fetch=True)[0][0] or 0
                                else:
                                    ejecutar_query("INSERT INTO detalle_ventas (venta_id, producto, cantidad, precio_unitario, subtotal) VALUES (?,?,?,?,?)", (venta_editar_id, prod_extra, cant_extra, precio_extra, subtotal_extra), commit=True)
                                    nuevo_total = ejecutar_query("SELECT SUM(subtotal) FROM detalle_ventas WHERE venta_id=?", (venta_editar_id,), fetch=True)[0][0] or 0
                                ejecutar_query("UPDATE ventas SET cliente=?, total=? WHERE id=?", (nuevo_cliente_nota, nuevo_total, venta_editar_id), commit=True)
                                marcar_notificacion_cocina(nuevo_cliente_nota, "Producto agregado a la nota")
                                st.rerun()
                        if st.button("Reutilizar Boleta", use_container_width=True, key="btn_liberar_boleta"):
                            detalles_guardar = ejecutar_query("SELECT producto, cantidad, subtotal FROM detalle_ventas WHERE venta_id=?", (venta_editar_id,), fetch=True) or []
                            ejecutar_query(
                                "INSERT INTO boletas_liberadas (venta_id, cliente, total, items, fecha_liberacion, estado) VALUES (?,?,?,?,?, 'LIBERADA')",
                                (venta_editar_id, cliente_actual_nota, float(venta_label.split('S/. ')[1].split(' ')[0]), str(detalles_guardar), fecha_hora_actual()),
                                commit=True
                            )
                            ejecutar_query("UPDATE ventas SET estado_boleta='LIBERADA', estado='LIBERADA', total=0 WHERE id=?", (venta_editar_id,), commit=True)
                            st.warning("Boleta liberada. No contará como venta activa.")
                            st.rerun()
                    else:
                        st.info("No hay notas activas para modificar.")

            # --- BLOQUE DE RENDERIZADO DEL TICKET (EXCLUSIVO Y SEGURO) ---
            # Este contenedor se pinta abajo de la PESTAÑA 1 únicamente si la bandera local es True.
            # No usa Modales/Dialogs propensos a colapsar, y añade un botón para limpiar el estado por completo.
            if False and st.session_state["ticket_listo"]:
                st.markdown("---")
                st.markdown("### Nota de Venta")
                
                # Caja estilizada que emula el contenedor flotante anterior, pero seguro
                with st.container(border=True):
                    mostrar_ticket_multiple(
                        st.session_state["ticket_cliente"],
                        st.session_state["ticket_items"],
                        st.session_state["ticket_total"],
                        st.session_state["ticket_tipo"],
                        st.session_state.get("ticket_vendedor", "")
                    )
                    
                    if st.button("Cerrar vista", use_container_width=True, type="primary", key="btn_cerrar_ticket_seguro"):
                        # Reseteamos por completo todas las variables temporales para que desaparezca
                        st.session_state["ticket_listo"] = False
                        st.session_state["ticket_cliente"] = ""
                        st.session_state["ticket_items"] = []
                        st.session_state["ticket_total"] = 0.0
                        st.session_state["ticket_tipo"] = ""
                        st.rerun()

        # ---------------------------------------------------------------------
        # PESTAÑA 2: CONTROL DE STOCK (TÍTULOS SIN EMOJIS)
        # ---------------------------------------------------------------------
        elif modulo_actual == opciones_menu[1]:
            col_st1, col_st2 = st.columns([1.2, 1])
            if "stock_registro_nonce" not in st.session_state:
                st.session_state["stock_registro_nonce"] = 0
            
            with col_st1:
                with st.form("ingreso_stock", clear_on_submit=True):
                    # CORRECCIÓN: Título limpio sin emoji
                    st.subheader("Registrar Nuevo")
                    col_s1, col_s2, col_s3 = st.columns(3)
                    with col_s1:
                        s_nombre = st.text_input("Nombre del Producto / Insumo")
                        s_proveedor = st.text_input("Proveedor (Escribe 'INTERNO' si es plato)")
                    with col_s2:
                        s_costo = st.number_input("Costo de Compra (S/.)", min_value=0.0, step=0.5)
                        s_precio = st.number_input("Precio de Venta (S/.)", min_value=0.0, step=0.5)
                    with col_s3:
                        s_stock = st.number_input("Cantidad que Ingresa", min_value=1, step=1)
                        s_fecha = fecha_hoy_local()
                        st.text_input(
                            "Fecha de Ingreso",
                            value=s_fecha.strftime('%Y/%m/%d'),
                            disabled=True,
                            key=f"fecha_ingreso_stock_windows_{st.session_state['stock_registro_nonce']}"
                        )
                    
                    if st.form_submit_button("Guardar En Inventario", type="primary"):
                        if s_nombre:
                            s_nombre_formato = s_nombre.strip().upper()
                            prov_formato = s_proveedor.strip().upper() if s_proveedor.strip() else "DISTRIBUIDORA"
                            existe = ejecutar_query("SELECT id, stock FROM inventario WHERE nombre=?", (s_nombre_formato,), fetch=True)
                            if existe:
                                st.error("El producto ya existe. Para aumentar stock usa el Panel de Edición y Eliminación.")
                            else:
                                ejecutar_query("INSERT INTO inventario (nombre, proveedor, fecha_ingreso, costo, precio, stock) VALUES (?,?,?,?,?,?)",
                                               (s_nombre_formato, prov_formato, s_fecha.strftime('%Y-%m-%d'), s_costo, s_precio, s_stock), commit=True)
                                nuevo_id_stock = ejecutar_query("SELECT max(id) FROM inventario", fetch=True)[0][0]
                                registrar_movimiento_stock(nuevo_id_stock, s_nombre_formato, "REGISTRO", s_stock, 0, s_stock, "Registro inicial")
                                st.success("Producto registrado.")
                                st.session_state["stock_registro_nonce"] += 1
                                st.rerun()

            with col_st2:
                # CORRECCIÓN: Título limpio sin emoji
                st.subheader("Panel de Edición y Eliminación")
                items_db = ejecutar_query("SELECT id, nombre, proveedor, costo, precio, stock FROM inventario", fetch=True)
                
                if items_db:
                    if "stock_edit_nonce" not in st.session_state:
                        st.session_state["stock_edit_nonce"] = 0
                    opciones_items = {f"{item[1]} (ID: {item[0]})": item for item in items_db}
                    item_seleccionado = st.selectbox("Selecciona el producto a modificar:", list(opciones_items.keys()))
                    
                    if item_seleccionado:
                        id_edit, nom_edit, prov_edit, cost_edit, prec_edit, stock_edit = opciones_items[item_seleccionado]
                        stock_edit_nonce = st.session_state["stock_edit_nonce"]
                        
                        col_ed1, col_ed2 = st.columns(2)
                        with col_ed1:
                            nuevo_nombre = st.text_input("Editar Nombre", value=nom_edit)
                            nuevo_prov = st.text_input("Editar Proveedor", value=prov_edit)
                        with col_ed2:
                            nuevo_costo_val = st.number_input("Editar Costo (S/.)", min_value=0.0, value=float(cost_edit), step=0.5)
                            nuevo_precio_val = st.number_input("Editar Precio Venta (S/.)", min_value=0.0, value=float(prec_edit), step=0.5)

                        st.markdown("##### Movimiento de stock")
                        col_stock_actual, col_stock_add, col_stock_sub = st.columns(3)
                        with col_stock_actual:
                            st.number_input("Stock Actual", min_value=0, value=int(stock_edit), disabled=True, key=f"stock_actual_{id_edit}")
                        with col_stock_add:
                            stock_a_sumar = st.number_input("Añadir Stock", min_value=0, value=0, step=1, key=f"stock_add_{id_edit}_{stock_edit_nonce}")
                        with col_stock_sub:
                            stock_a_restar = st.number_input("Disminuir Stock", min_value=0, value=0, step=1, key=f"stock_sub_{id_edit}_{stock_edit_nonce}")

                        stock_preview = int(stock_edit) + int(stock_a_sumar) - int(stock_a_restar)
                        if stock_preview < 0:
                            st.warning("La disminución supera el stock disponible.")
                        else:
                            st.caption(f"Stock final al guardar: {stock_preview}")
                        
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            if st.button("📝 Guardar Cambios", use_container_width=True, key=f"btn_guardar_stock_{id_edit}_{stock_edit_nonce}"):
                                if nuevo_nombre.strip():
                                    stock_final = int(stock_edit) + int(stock_a_sumar) - int(stock_a_restar)
                                    if stock_final < 0:
                                        st.error("No se puede disminuir más stock del disponible.")
                                    else:
                                        ejecutar_query(
                                            "UPDATE inventario SET nombre=?, proveedor=?, costo=?, precio=?, stock=? WHERE id=?",
                                            (nuevo_nombre.strip().upper(), nuevo_prov.strip().upper(), nuevo_costo_val, nuevo_precio_val, stock_final, id_edit),
                                            commit=True
                                        )
                                        producto_mov = nuevo_nombre.strip().upper()
                                        if int(stock_a_sumar) > 0:
                                            registrar_movimiento_stock(id_edit, producto_mov, "AUMENTO", stock_a_sumar, stock_edit, int(stock_edit) + int(stock_a_sumar), "Panel de edición")
                                        if int(stock_a_restar) > 0:
                                            registrar_movimiento_stock(id_edit, producto_mov, "DISMINUCION", stock_a_restar, int(stock_edit) + int(stock_a_sumar), stock_final, "Panel de edición")
                                        st.success("¡Modificado!")
                                        st.session_state["stock_edit_nonce"] += 1
                                        st.rerun()
                                else:
                                    st.error("Ingrese un nombre válido para el producto.")
                        with col_btn2:
                            if st.button("❌ Eliminar Producto", type="secondary", use_container_width=True):
                                ejecutar_query("DELETE FROM inventario WHERE id=?", (id_edit,), commit=True)
                                st.warning("¡Producto eliminado!")
                                st.rerun()

            st.markdown("---")
            # CORRECCIÓN: Título limpio sin emoji
            st.subheader("Inventario Actual en Tiempo Real")
            inventario_total = ejecutar_query("SELECT id, nombre, proveedor, fecha_ingreso, costo, precio, stock FROM inventario", fetch=True)
            if inventario_total:
                df_inv = pd.DataFrame(inventario_total, columns=["ID", "Producto", "Proveedor", "Últ. Ingreso", "Costo", "Precio Venta", "Stock"])
                st.dataframe(df_inv, use_container_width=True, hide_index=True)
            with st.expander("Historial de movimientos de stock", expanded=False):
                movimientos_stock = ejecutar_query(
                    "SELECT fecha, usuario, producto, tipo, cantidad, stock_anterior, stock_nuevo, motivo FROM stock_movimientos ORDER BY id DESC LIMIT 200",
                    fetch=True
                )
                if movimientos_stock:
                    st.dataframe(
                        pd.DataFrame(movimientos_stock, columns=["Fecha", "Usuario", "Producto", "Movimiento", "Cantidad", "Stock anterior", "Stock nuevo", "Motivo"]),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("Aún no hay movimientos de stock registrados.")

        # ---------------------------------------------------------------------
        # PESTAÑA 3: CONTROL DE PISCINA (ACTUALIZADO SIN EMOJIS EN SUBTEXTOS)
        # ---------------------------------------------------------------------
        elif modulo_actual == opciones_menu[2]:
            # Consultamos las tarifas actuales de la base de datos
            tarifas_db = ejecutar_query("SELECT categoria, precio FROM tarifas", fetch=True)
            dict_tarifas = {t[0]: t[1] for t in tarifas_db} if tarifas_db else {}
            
            p_nino = dict_tarifas.get("Niños", 5.0)
            p_adulto = dict_tarifas.get("Adultos", 10.0)
            p_mayor = dict_tarifas.get("Mayores", 7.0)

            col_p1, col_p2, col_p3 = st.columns([1.2, 1.2, 1.4])
            
            # --- COLUMNA 1: REGISTRO DE ENTRADAS ---
            with col_p1:
                st.subheader("Registro de Entradas")
                piscina_nonce = st.session_state.get("piscina_form_nonce", 0)
                
                ninos = st.number_input(
                    "Cantidad de Niños / Niñas", 
                    min_value=0, step=1, value=0,
                    help="Considerados desde los 2 hasta los 12 años de edad.",
                    key=f"ninos_piscina_{piscina_nonce}"
                )
                st.caption("*Niños: 2 a 12 años*")
                
                adultos = st.number_input(
                    "Cantidad de Adultos", 
                    min_value=0, step=1, value=0,
                    help="Considerados desde los 13 años a más.",
                    key=f"adultos_piscina_{piscina_nonce}"
                )
                st.caption("*Adultos: 13 años a más*")
                mayores = 0
                destino_piscina = st.radio("Destino de la Venta", ["Pagado al Instante", "Llevar a Cuenta Crédito"], horizontal=True, key=f"destino_piscina_{piscina_nonce}")
                cliente_piscina = "CLIENTE PISCINA"
                cliente_credito_piscina = ""
                if destino_piscina == "Llevar a Cuenta Crédito":
                    opciones_credito_piscina = ["➕ AGREGAR NUEVO CLIENTE"] + clientes_credito_abiertos()
                    credito_piscina_sel = st.selectbox("Cuenta crédito existente", opciones_credito_piscina, key=f"sb_credito_existente_piscina_{piscina_nonce}")
                    if credito_piscina_sel == "➕ AGREGAR NUEVO CLIENTE":
                        cliente_credito_piscina = st.text_input("Nombre del nuevo cliente", key=f"txt_nuevo_credito_piscina_{piscina_nonce}").strip().upper()
                    else:
                        cliente_credito_piscina = credito_piscina_sel
                        st.caption(f"Se agregará a la cuenta corriente de: {cliente_credito_piscina}")
                else:
                    cliente_piscina = st.text_input("Cliente", value="CLIENTE PISCINA", key=f"cliente_piscina_{piscina_nonce}").strip().upper() or "CLIENTE PISCINA"
                _, trabajador_piscina = seleccionar_trabajador("Trabajador que atendió", ("Trabajador",), f"piscina_trabajador_{piscina_nonce}")
                metodo_piscina, receptor_piscina, receptor_nombre_piscina = seleccionar_pago_receptor(
                    f"piscina_{piscina_nonce}",
                    incluir_mesero=False,
                    receptor_preseleccionado={"tipo": "Trabajador", "nombre": trabajador_piscina}
                )
                
                # Cálculo automático en tiempo real basado en la selección
                calculo_sugerido = (ninos * p_nino) + (adultos * p_adulto) + (mayores * p_mayor)
                st.warning(f"Pago Sugerido: S/. {calculo_sugerido:.2f}")
                
                monto_final = st.number_input(
                    "Monto Final Recibido",
                    min_value=0.0,
                    value=float(calculo_sugerido),
                    step=1.0,
                    key=f"monto_final_piscina_{piscina_nonce}_{ninos}_{adultos}_{mayores}_{calculo_sugerido:.2f}"
                )
                monto_mayor_al_sugerido = monto_final > calculo_sugerido
                if monto_mayor_al_sugerido:
                    st.warning("El monto final no puede ser mayor al pago sugerido. Ajusta el importe para continuar.")
                
                if st.button("Registrar Ingreso Piscina", use_container_width=True, type="primary"):
                    if ninos == 0 and adultos == 0 and mayores == 0:
                        st.error("Debes ingresar al menos 1 persona para registrar la entrada.")
                    elif destino_piscina == "Llevar a Cuenta Crédito" and not cliente_credito_piscina.strip():
                        st.error("Selecciona o ingresa el cliente de la cuenta crédito.")
                    elif monto_mayor_al_sugerido:
                        st.error("No se guardó el ingreso porque el monto final supera el pago sugerido.")
                    else:
                        # Registro en base de datos manteniendo el control de caja abierto para los turnos
                        fecha_registro = fecha_hora_actual()
                        estado_piscina = "CREDITO" if destino_piscina == "Llevar a Cuenta Crédito" else "PAGADO"
                        cliente_piscina_guardar = cliente_credito_piscina.strip().upper() if estado_piscina == "CREDITO" else cliente_piscina
                        ejecutar_query(
                            "INSERT INTO piscina (ninos, adultos, mayores, monto_pagado, fecha, estado_caja, cliente, metodo_pago, receptor_tipo, receptor_nombre, trabajador, destino, estado) VALUES (?,?,?,?,?, 'ABIERTO', ?,?,?,?,?,?,?)",
                            (ninos, adultos, mayores, monto_final, fecha_registro, cliente_piscina_guardar, metodo_piscina, receptor_piscina, receptor_nombre_piscina, trabajador_piscina, destino_piscina, estado_piscina), 
                            commit=True
                        )
                        piscina_id = ejecutar_query("SELECT max(id) FROM piscina", fetch=True)[0][0]
                        if estado_piscina == "CREDITO":
                            total_personas_piscina = int(ninos or 0) + int(adultos or 0) + int(mayores or 0)
                            precio_promedio_piscina = (float(monto_final or 0) / total_personas_piscina) if total_personas_piscina else 0
                            registrar_credito_cliente(
                                cliente_piscina_guardar,
                                "Piscina",
                                "ENTRADA PISCINA",
                                total_personas_piscina,
                                precio_promedio_piscina,
                                monto_final,
                                fecha_registro,
                                piscina_id,
                                trabajador_nombre=trabajador_piscina
                            )
                        st.success("¡Ingreso de piscina guardado exitosamente!")
                        
                        # Estructuración detallada para el ticket térmico
                        items_piscina_ticket = []
                        if ninos > 0:
                            items_piscina_ticket.append({"producto": "ENTRADA PISCINA (NIÑO)", "cantidad": ninos, "subtotal": ninos * p_nino})
                        if adultos > 0:
                            items_piscina_ticket.append({"producto": "ENTRADA PISCINA (ADULTO)", "cantidad": adultos, "subtotal": adultos * p_adulto})
                        if mayores > 0:
                            items_piscina_ticket.append({"producto": "ENTRADA PISCINA (ANCIANO)", "cantidad": mayores, "subtotal": mayores * p_mayor})
                        
                        encolar_impresion_nota(cliente_piscina_guardar, items_piscina_ticket, monto_final, "ACCESO PISCINA", trabajador_piscina)
                        reiniciar_formulario("piscina")
                        st.rerun()

                if False and st.session_state.get("ticket_piscina_listo"):
                    st.markdown("---")
                    st.markdown("### Nota de Piscina")
                    with st.container(border=True):
                        mostrar_ticket_multiple(
                            cliente_piscina,
                            st.session_state.get("ticket_piscina_items", []),
                            st.session_state.get("ticket_piscina_total", 0.0),
                            "ACCESO PISCINA",
                            st.session_state.get("ticket_piscina_vendedor", "")
                        )
                        if st.button("Cerrar nota de piscina", use_container_width=True, type="primary", key="btn_cerrar_ticket_piscina"):
                            st.session_state["ticket_piscina_listo"] = False
                            st.session_state["ticket_piscina_items"] = []
                            st.session_state["ticket_piscina_total"] = 0.0
                            st.session_state["ticket_piscina_fecha"] = ""
                            st.rerun()
            
            # --- COLUMNA 2: CONFIGURACIÓN DE TARIFAS POR CATEGORÍA ---
            with col_p2:
                st.subheader("Panel de Tarifas Piscina")
                nuevo_p_nino = st.number_input("Precio Entrada Niños (S/.)", min_value=0.0, value=float(p_nino), step=0.5, help="Tarifa aplicable a menores de 18 años.")
                nuevo_p_adulto = st.number_input("Precio Entrada Adultos (S/.)", min_value=0.0, value=float(p_adulto), step=0.5, help="Tarifa aplicable desde los 13 años.")
                
                if st.button("🔄 Actualizar Tarifas Piscina", use_container_width=True):
                    ejecutar_query("UPDATE tarifas SET precio=? WHERE categoria='Niños'", (nuevo_p_nino,), commit=True)
                    ejecutar_query("UPDATE tarifas SET precio=? WHERE categoria='Adultos'", (nuevo_p_adulto,), commit=True)
                    st.success("¡Tarifas de edad actualizadas con éxito!")
                    st.rerun()

            # --- COLUMNA 3: HISTORIAL RECIENTE DE ENTRADAS ---
            with col_p3:
                st.subheader("Historial de Entradas")
                registros_piscina = ejecutar_query(
                    "SELECT ninos, adultos, monto_pagado, fecha, cliente, estado FROM piscina WHERE estado_caja='ABIERTO' ORDER BY id DESC",
                    fetch=True
                )
                if registros_piscina:
                    df_pis = pd.DataFrame(registros_piscina, columns=["Niños", "Adultos", "Monto", "Fecha/Hora", "Cliente", "Estado"])
                    st.dataframe(df_pis, use_container_width=True, hide_index=True)
                else:
                    st.info("No se registran ingresos a la piscina el día de hoy.")

                st.markdown("---")
                st.subheader("Cuentas por Cobrar - Piscina")
                deudas_piscina = ejecutar_query(
                    "SELECT cliente, producto, subtotal FROM detalle_creditos WHERE origen='Piscina' ORDER BY fecha DESC",
                    fetch=True
                )
                if deudas_piscina:
                    st.dataframe(pd.DataFrame(deudas_piscina, columns=["Cliente", "Concepto", "Monto pendiente"]), use_container_width=True, hide_index=True)
                    clientes_piscina_deuda = sorted({d[0] for d in deudas_piscina})
                    cli_pis_cobrar = st.selectbox("Cliente a cancelar", clientes_piscina_deuda, key="sb_cobrar_piscina")
                    if st.button("Cancelar deuda de piscina", use_container_width=True, key="btn_cobrar_piscina"):
                        ejecutar_query("DELETE FROM detalle_creditos WHERE cliente=? AND origen='Piscina'", (cli_pis_cobrar,), commit=True)
                        ejecutar_query("UPDATE piscina SET estado='PAGADO' WHERE cliente=? AND estado='CREDITO'", (cli_pis_cobrar,), commit=True)
                        total_restante_piscina = recalcular_credito_cliente(cli_pis_cobrar)
                        if total_restante_piscina <= 0:
                            ejecutar_query("UPDATE ventas SET total=0, estado='PAGADO' WHERE cliente=? AND estado='CREDITO'", (cli_pis_cobrar,), commit=True)
                        st.rerun()
                else:
                    st.info("No hay cuentas pendientes de piscina.")

        # ---------------------------------------------------------------------
        # PESTAÑA 4: CONTROL DE CANCHAS (CORRECCIÓN DE TRADUCCIÓN Y BUSCADOR LIQUIDACIÓN)
        # ---------------------------------------------------------------------
        elif modulo_actual == opciones_menu[3]:
            # Inyección para desactivar el autocompletado/sugerencias del navegador en los inputs
            st.markdown(
                """
                <style>
                input {
                    autocomplete: off !important;
                }
                </style>
                """, 
                unsafe_allow_html=True
            )
            tarifas_c_db = ejecutar_query("SELECT tipo, precio FROM tarifas_cancha", fetch=True)
            dict_t_cancha = {tc[0]: tc[1] for tc in tarifas_c_db} if tarifas_c_db else {}
            
            precio_grande = dict_t_cancha.get("Cancha Grande 3", dict_t_cancha.get("Cancha Grande", 70.0))
            precio_media = dict_t_cancha.get("Media Cancha", 40.0)

            col_c1, col_c2, col_c3 = st.columns([1.3, 1.1, 1.6])
            
            # --- COLUMNA 1: REGISTRO DE NUEVA RESERVA ---
            with col_c1:
                cancha_nonce = st.session_state.get("cancha_form_nonce", 0)
                destino_cancha = st.radio("Destino de la Venta", ["Pagado al Instante", "Llevar a Cuenta Crédito"], horizontal=True, key=f"destino_cancha_{cancha_nonce}")
                c_cliente = ""
                cliente_credito_cancha = ""
                if destino_cancha == "Llevar a Cuenta Crédito":
                    opciones_credito_cancha = ["➕ AGREGAR NUEVO CLIENTE"] + clientes_credito_abiertos()
                    credito_cancha_sel = st.selectbox("Cuenta crédito existente", opciones_credito_cancha, key=f"sb_credito_existente_cancha_{cancha_nonce}")
                    if credito_cancha_sel == "➕ AGREGAR NUEVO CLIENTE":
                        cliente_credito_cancha = st.text_input("Nombre del nuevo cliente", key=f"txt_nuevo_credito_cancha_{cancha_nonce}").strip().upper()
                    else:
                        cliente_credito_cancha = credito_cancha_sel
                        st.caption(f"Se agregará a la cuenta corriente de: {cliente_credito_cancha}")
                else:
                    c_cliente = st.text_input("Nombre del Cliente", key=f"cliente_cancha_{cancha_nonce}").strip().upper()
                    cliente_credito_cancha = c_cliente
                c_fecha = st.date_input("Fecha del Alquiler", value=fecha_hoy_local(), key=f"fecha_cancha_{cancha_nonce}")
                
                horario_final_str = selector_horario_reserva(f"cancha_{cancha_nonce}")
                tipo_cancha_sel = st.selectbox("Tipo de Cancha", ["Cancha Mediana 1", "Cancha Mediana 2", "Cancha Grande 3"], key=f"tipo_cancha_{cancha_nonce}")
                costo_base_cancha = precio_grande if tipo_cancha_sel == "Cancha Grande 3" else precio_media
                
                c_total = st.number_input("Monto Total Contractual (S/.)", min_value=0.0, value=float(costo_base_cancha), key=f"total_cancha_{cancha_nonce}_{tipo_cancha_sel}")
                c_adelanto = st.number_input("Monto de Adelanto (S/.)", min_value=0.0, value=0.0, key=f"adelanto_cancha_{cancha_nonce}")
                if c_adelanto > c_total:
                    st.warning("El adelanto no puede ser mayor al monto total contractual.")
                _, trabajador_cancha = seleccionar_trabajador("Trabajador que atendió", ("Trabajador",), f"cancha_trabajador_{cancha_nonce}")
                metodo_cancha, receptor_cancha, receptor_nombre_cancha = seleccionar_pago_receptor(
                    f"cancha_{cancha_nonce}",
                    incluir_mesero=False,
                    receptor_preseleccionado={"tipo": "Trabajador", "nombre": trabajador_cancha}
                )
                
                if st.button("Guardar Reserva de Cancha", type="primary", use_container_width=True):
                    cliente_cancha_guardar = cliente_credito_cancha.strip().upper()
                    if not cliente_cancha_guardar:
                        st.error("Por favor, ingresa el nombre del cliente.")
                    else:
                        fecha_str = c_fecha.strftime('%Y-%m-%d')
                        
                        # Validación de disponibilidad para evitar duplicados (compara usando el estado activo)
                        if tipo_cancha_sel == "Cancha Mediana 1":
                            tipos_bloqueantes = ["Cancha Grande 3", "Cancha Grande", "Cancha Mediana 1"]
                        elif tipo_cancha_sel == "Cancha Mediana 2":
                            tipos_bloqueantes = ["Cancha Grande 3", "Cancha Grande", "Cancha Mediana 2"]
                        else:
                            tipos_bloqueantes = ["Cancha Grande 3", "Cancha Grande", "Cancha Mediana 1", "Cancha Mediana 2"]
                        marcas = ",".join(["?"] * len(tipos_bloqueantes))
                        cruce_db = ejecutar_query(
                            f"SELECT id, cliente, tipo_cancha FROM cancha WHERE fecha_reserva = ? AND horario = ? AND tipo_cancha IN ({marcas}) AND estado IN ('PENDIENTE', 'PAGADO') AND estado_caja='ABIERTO'",
                            tuple([fecha_str, horario_final_str] + tipos_bloqueantes),
                            fetch=True
                        )
                        
                        if cruce_db:
                            id_existente, cliente_existente, tipo_existente = cruce_db[0]
                            st.error(f"Horario NO disponible. {tipo_existente} bloquea la reserva para el {fecha_str} a las {horario_final_str}. Cliente: {cliente_existente} (ID: {id_existente}).")
                        elif c_adelanto > c_total:
                            st.error("No se guardó la reserva porque el adelanto supera el monto total.")
                        else:
                            adelanto_guardar = c_adelanto
                            saldo_cancha = max(c_total - adelanto_guardar, 0)
                            estado_guardar = "PAGADO" if saldo_cancha <= 0 else "PENDIENTE"
                            ejecutar_query(
                                "INSERT INTO cancha (cliente, fecha_reserva, horario, tipo_cancha, monto_total, adelanto, estado, estado_caja, metodo_pago, receptor_tipo, receptor_nombre, trabajador) VALUES (?,?,?,?,?,?,?, 'ABIERTO', ?,?,?,?)",
                                (cliente_cancha_guardar, fecha_str, horario_final_str, tipo_cancha_sel, c_total, adelanto_guardar, estado_guardar, metodo_cancha, receptor_cancha, receptor_nombre_cancha, trabajador_cancha), 
                                commit=True
                            )
                            cancha_id = ejecutar_query("SELECT max(id) FROM cancha", fetch=True)[0][0]
                            if destino_cancha == "Llevar a Cuenta Crédito" and saldo_cancha > 0:
                                registrar_credito_cliente(cliente_cancha_guardar, "Cancha", f"SALDO {tipo_cancha_sel}", 1, saldo_cancha, saldo_cancha, fecha_hora_actual(), cancha_id, trabajador_nombre=trabajador_cancha)
                            st.success("¡Reserva guardada correctamente!")
                            if adelanto_guardar > 0:
                                it_cancha = [{"producto": f"Alquiler ({tipo_cancha_sel})", "cantidad": 1, "subtotal": adelanto_guardar}]
                                encolar_impresion_nota(cliente_cancha_guardar, it_cancha, adelanto_guardar, "ALQUILER CANCHA", trabajador_cancha)
                                reiniciar_formulario("cancha")
                                st.rerun()
                            else:
                                reiniciar_formulario("cancha")
                                st.rerun()
                        
            # --- COLUMNA 2: CONFIGURACIÓN DE TARIFAS Y LIQUIDACIÓN FLEXIBLE ---
            with col_c2:
                st.subheader("Panel de Tarifas Canchas")
                nuevo_p_grande = st.number_input("Cancha Grande 3 / Hora (S/.)", min_value=0.0, value=float(precio_grande), step=5.0)
                nuevo_p_media = st.number_input("Media Cancha / Hora (S/.)", min_value=0.0, value=float(precio_media), step=5.0)
                
                if st.button("Actualizar Precios Cancha", use_container_width=True):
                    ejecutar_query("INSERT OR REPLACE INTO tarifas_cancha (tipo, precio) VALUES (?,?)", ("Cancha Grande 3", nuevo_p_grande), commit=True)
                    ejecutar_query("UPDATE tarifas_cancha SET precio=? WHERE tipo='Media Cancha'", (nuevo_p_media,), commit=True)
                    st.success("¡Precios de alquiler actualizados!")
                    st.rerun()
                    
                st.markdown("---")
                st.subheader("Liquidar Saldo Cancha")
                
                # Selector del método de búsqueda para liquidar
                metodo_busqueda = st.radio("Buscar reserva a liquidar por:", ["ID de Reserva", "Nombre del Cliente"], horizontal=True)
                
                id_cancha_liquidar = None
                
                if metodo_busqueda == "ID de Reserva":
                    id_cancha_liquidar = st.number_input("Ingrese ID de Reserva", min_value=1, step=1)
                else:
                    # Traemos solo los clientes con reservas de cancha en estado 'PENDIENTE'
                    deudores_db = ejecutar_query("SELECT id, cliente, fecha_reserva, horario FROM cancha WHERE estado='PENDIENTE' ORDER BY id DESC", fetch=True)
                    if deudores_db:
                        opciones_clientes = {f"ID {d[0]} - {d[1]} ({d[2]} | {d[3]})": d[0] for d in deudores_db}
                        cliente_seleccionado = st.selectbox("Seleccione el Cliente de la lista:", list(opciones_clientes.keys()))
                        id_cancha_liquidar = opciones_clientes[cliente_seleccionado]
                    else:
                        st.info("No hay clientes con saldos pendientes por liquidar.")
                
                # Ejecución de la liquidación si se cuenta con un ID válido
                if id_cancha_liquidar:
                    if st.button("Marcar como Completado/Pagado", use_container_width=True, type="primary"):
                        check_reserva = ejecutar_query("SELECT cliente, monto_total, adelanto, estado_caja FROM cancha WHERE id=?", (id_cancha_liquidar,), fetch=True)
                        if check_reserva:
                            cliente_c, tot_c, ade_c, estado_caja_reserva = check_reserva[0]
                            restante = tot_c - ade_c
                            if estado_caja_reserva == "CERRADO":
                                ejecutar_query("UPDATE cancha SET estado='PAGADO', metodo_pago=?, receptor_tipo=?, receptor_nombre=? WHERE id=?", (metodo_cancha, receptor_cancha, receptor_nombre_cancha, id_cancha_liquidar), commit=True)
                                ejecutar_query(
                                    "INSERT INTO ventas (cliente, total, estado, fecha, estado_caja, atendido_por_tipo, atendido_por_nombre, metodo_pago, receptor_tipo, receptor_nombre, origen) VALUES (?,?,?,?, 'ABIERTO', ?,?,?,?,?, 'Cancha')",
                                    (cliente_c, restante, "PAGADO", fecha_hora_actual(), "Trabajador", trabajador_cancha, metodo_cancha, receptor_cancha, receptor_nombre_cancha),
                                    commit=True
                                )
                            else:
                                ejecutar_query("UPDATE cancha SET estado='PAGADO', estado_caja='ABIERTO', metodo_pago=?, receptor_tipo=?, receptor_nombre=? WHERE id=?", (metodo_cancha, receptor_cancha, receptor_nombre_cancha, id_cancha_liquidar), commit=True)
                            ejecutar_query("DELETE FROM detalle_creditos WHERE origen='Cancha' AND referencia_id=?", (id_cancha_liquidar,), commit=True)
                            deuda_restante_cliente = ejecutar_query("SELECT SUM(subtotal) FROM detalle_creditos WHERE cliente=?", (cliente_c,), fetch=True)[0][0] or 0
                            if deuda_restante_cliente > 0:
                                ejecutar_query("UPDATE ventas SET total=?, estado='CREDITO' WHERE cliente=? AND estado='CREDITO'", (deuda_restante_cliente, cliente_c), commit=True)
                            else:
                                ejecutar_query("UPDATE ventas SET total=0, estado='PAGADO' WHERE cliente=? AND estado='CREDITO'", (cliente_c,), commit=True)
                            st.success(f"¡Reserva ID {id_cancha_liquidar} saldada por completo!")
                            it_liq = [{"producto": "Saldo Restante Cancha", "cantidad": 1, "subtotal": restante}]
                            encolar_impresion_nota(cliente_c, it_liq, restante, "LIQUIDACION CANCHA", trabajador_cancha)
                            st.rerun()
                        else:
                            st.error("El ID de reserva ingresado no existe en el sistema.")

            # --- COLUMNA 3: HISTORIAL MODIFICADO CON COLUMNA FECHA ---
            with col_c3:
                st.subheader("Estado Visual de la Cancha")
                fecha_visual = c_fecha.strftime("%Y-%m-%d")
                reservas_hoy_visual = ejecutar_query(
                    "SELECT tipo_cancha FROM cancha WHERE fecha_reserva=? AND horario=? AND estado IN ('PENDIENTE','PAGADO') AND estado_caja='ABIERTO'",
                    (fecha_visual, horario_final_str),
                    fetch=True
                )
                reservadas_visual = {r[0] for r in reservas_hoy_visual} if reservas_hoy_visual else set()
                grande_ocupada = "Cancha Grande 3" in reservadas_visual or "Cancha Grande" in reservadas_visual
                izq_ocupada = "Cancha Mediana 1" in reservadas_visual or grande_ocupada
                der_ocupada = "Cancha Mediana 2" in reservadas_visual or grande_ocupada
                cancha_html = f"""
                <div style="position:relative; height:230px; border:3px solid white; overflow:hidden; background:
                    repeating-linear-gradient(90deg,#167a23 0,#167a23 38px,#1f8a2d 38px,#1f8a2d 76px); box-shadow: inset 0 0 0 2px rgba(255,255,255,.6); margin-bottom:14px;">
                    <div style="position:absolute; inset:10px; border:2px solid rgba(255,255,255,.8);"></div>
                    <div style="position:absolute; left:50%; top:10px; bottom:10px; border-left:2px solid rgba(255,255,255,.8);"></div>
                    <div style="position:absolute; left:50%; top:50%; width:74px; height:74px; margin-left:-37px; margin-top:-37px; border:2px solid rgba(255,255,255,.8); border-radius:50%;"></div>
                    <div style="position:absolute; left:10px; top:64px; width:70px; height:100px; border:2px solid rgba(255,255,255,.8);"></div>
                    <div style="position:absolute; right:10px; top:64px; width:70px; height:100px; border:2px solid rgba(255,255,255,.8);"></div>
                    <div style="position:absolute; left:0; top:0; width:50%; height:100%; background:{'rgba(220,38,38,.48)' if izq_ocupada else 'transparent'}; display:flex; align-items:center; justify-content:center; color:white; font-weight:900; text-shadow:0 1px 3px #000;">Cancha Mediana 1</div>
                    <div style="position:absolute; right:0; top:0; width:50%; height:100%; background:{'rgba(220,38,38,.48)' if der_ocupada else 'transparent'}; display:flex; align-items:center; justify-content:center; color:white; font-weight:900; text-shadow:0 1px 3px #000;">Cancha Mediana 2</div>
                    <div style="position:absolute; left:50%; top:8px; transform:translateX(-50%); color:white; font-weight:900; text-shadow:0 1px 3px #000;">Cancha Grande 3</div>
                </div>
                """
                st.markdown(cancha_html, unsafe_allow_html=True)
                st.subheader("Historial de Reservas")
                
                buscar_cliente = st.text_input("🔍 Buscar reserva por nombre de cliente:", placeholder="Escribe el nombre aquí...").strip().upper()
                
                reservas = ejecutar_query(
                    "SELECT id, cliente, fecha_reserva, horario, monto_total, adelanto, (monto_total - adelanto), estado FROM cancha WHERE estado_caja='ABIERTO' ORDER BY id DESC",
                    fetch=True
                )
                
                if reservas:
                    df_res = pd.DataFrame(reservas, columns=["ID", "Cliente", "Fecha", "Horario", "Total", "Adelanto", "Saldo Pendiente", "Estado"])
                    
                    if buscar_cliente:
                        df_res = df_res[df_res["Cliente"].str.contains(buscar_cliente, na=False)]
                    
                    if not df_res.empty:
                        st.dataframe(df_res, use_container_width=True, hide_index=True)
                        ids_reserva = {f"ID {r[0]} - {r[1]}": r[0] for r in reservas}
                        reserva_eliminar = st.selectbox("Reserva a eliminar", list(ids_reserva.keys()), key="sb_eliminar_reserva_cancha")
                        if st.button("Eliminar reserva", use_container_width=True, key="btn_eliminar_reserva_cancha"):
                            ejecutar_query("UPDATE cancha SET estado='ELIMINADA' WHERE id=?", (ids_reserva[reserva_eliminar],), commit=True)
                            ejecutar_query("DELETE FROM detalle_creditos WHERE origen='Cancha' AND referencia_id=?", (ids_reserva[reserva_eliminar],), commit=True)
                            st.rerun()
                    else:
                        st.warning("No se encontraron reservas que coincidan con la búsqueda.")
                else:
                    st.info("No hay reservas registradas en el sistema.")

        # ---------------------------------------------------------------------
        # PESTAÑA 5: CAJA Y REPORTES DIARIOS (100% BLINDADA CONTRA COMPROBANTES FANTASMAS)
        # ---------------------------------------------------------------------
        elif modulo_actual == opciones_menu[5]:
            # --- LIMPIEZA PROACTIVA DE BOLETAS AL ENTRAR A FINANZAS ---
            # Si el usuario entra aquí, apagamos inmediatamente cualquier rastro del ticket de la Pestaña 1
            if "ticket_listo" in st.session_state:
                st.session_state["ticket_listo"] = False
            if "mostrar_boleta" in st.session_state:
                st.session_state["mostrar_boleta"] = False
            if "mostrar_ticket" in st.session_state:
                st.session_state["mostrar_ticket"] = False
            
            # --- CONSULTA DE LA CAJA ACTIVA (TURNO ACTUAL) ---
            ventas_hoy = ejecutar_query("SELECT total FROM ventas WHERE estado='PAGADO' AND estado_caja='ABIERTO' AND COALESCE(estado_boleta,'ACTIVA')!='LIBERADA'", fetch=True)
            piscina_hoy = ejecutar_query("SELECT monto_pagado FROM piscina WHERE estado='PAGADO' AND estado_caja='ABIERTO'", fetch=True)
            canchas_hoy = ejecutar_query("SELECT adelanto FROM cancha WHERE estado_caja='ABIERTO' AND estado!='ELIMINADA' AND COALESCE(adelanto,0)>0", fetch=True)
            canchas_saldos_hoy = ejecutar_query("SELECT (monto_total - adelanto) FROM cancha WHERE estado='PAGADO' AND estado_caja='ABIERTO'", fetch=True)
            local_hoy = ejecutar_query("SELECT monto_total FROM reservas_local WHERE estado='PAGADO' AND estado_caja='ABIERTO'", fetch=True)
            
            total_v = sum([v[0] for v in ventas_hoy])
            total_p = sum([p[0] for p in piscina_hoy])
            total_c = sum([c[0] for c in canchas_hoy]) + sum([cs[0] for cs in canchas_saldos_hoy])
            total_l = sum([l[0] for l in local_hoy])
            
            gran_total_caja = total_v + total_p + total_c + total_l
            
            cm1, cm2, cm3, cm4 = st.columns(4)
            with cm1:
                st.metric("🛒 Ventas de Productos", f"S/. {total_v:.2f}")
                st.metric("Reservación de Local", f"S/. {total_l:.2f}")
            with cm2: st.metric("🏊‍♂️ Ingresos Piscina", f"S/. {total_p:.2f}")
            with cm3: st.metric("⚽ Ingresos Canchas", f"S/. {total_c:.2f}")
            with cm4: 
                st.markdown(f"<div style='background-color:#1E6F5C; padding:10px; border-radius:10px; text-align:center;'><h3 style='color:white; margin:0;'>TOTAL EN CAJA</h3><h2 style='color:white; margin:0;'>S/. {gran_total_caja:.2f}</h2></div>", unsafe_allow_html=True)
            with st.expander("Detalle de ingresos"):
                detalle_ingresos = ejecutar_query(
                    """
                    SELECT 'Ventas' AS origen, id, cliente, fecha, total, metodo_pago
                    FROM ventas
                    WHERE estado='PAGADO' AND estado_caja='ABIERTO' AND COALESCE(estado_boleta,'ACTIVA')!='LIBERADA'
                    UNION ALL
                    SELECT 'Piscina', id, cliente, fecha, monto_pagado, metodo_pago
                    FROM piscina
                    WHERE estado='PAGADO' AND estado_caja='ABIERTO'
                    UNION ALL
                    SELECT 'Cancha - Adelanto', id, cliente, fecha_reserva || ' ' || horario, adelanto, metodo_pago
                    FROM cancha
                    WHERE estado_caja='ABIERTO' AND estado!='ELIMINADA' AND COALESCE(adelanto,0)>0
                    UNION ALL
                    SELECT 'Cancha - Saldo', id, cliente, fecha_reserva || ' ' || horario, (monto_total - adelanto), metodo_pago
                    FROM cancha
                    WHERE estado='PAGADO' AND estado_caja='ABIERTO' AND (monto_total - adelanto)>0
                    UNION ALL
                    SELECT 'Reserva de Local', id, cliente, fecha_reserva || ' ' || horario, monto_total, metodo_pago
                    FROM reservas_local
                    WHERE estado='PAGADO' AND estado_caja='ABIERTO'
                    ORDER BY fecha DESC
                    """,
                    fetch=True
                )
                if detalle_ingresos:
                    df_detalle_ingresos = pd.DataFrame(
                        detalle_ingresos,
                        columns=["Origen", "ID", "Cliente", "Fecha/Hora", "Monto", "Método de pago"]
                    )
                    buscar_metodo = st.text_input(
                        "Buscar por método de pago o cliente",
                        placeholder="Ejemplo: Yape José Luis, PLIN, Efectivo o nombre del cliente",
                        key="txt_buscar_metodo_caja"
                    ).strip().upper()
                    if buscar_metodo:
                        metodo_busqueda = df_detalle_ingresos["Método de pago"].fillna("").astype(str).str.upper()
                        cliente_busqueda = df_detalle_ingresos["Cliente"].fillna("").astype(str).str.upper()
                        df_detalle_ingresos = df_detalle_ingresos[
                            metodo_busqueda.str.contains(buscar_metodo, regex=False) |
                            cliente_busqueda.str.contains(buscar_metodo, regex=False)
                        ]
                    if not df_detalle_ingresos.empty:
                        st.markdown("#### Ingresos encontrados")
                        st.markdown(
                            """
                            <style>
                            .ingreso-row-head, .ingreso-row {
                                display: grid;
                                grid-template-columns: 1.25fr 1.15fr 1.35fr 1.2fr .75fr 1.1fr 1.15fr;
                                gap: 8px;
                                align-items: center;
                            }
                            .ingreso-row-head {
                                margin-bottom: 6px;
                                color: #5f7780;
                                font-size: 12px;
                                font-weight: 900;
                            }
                            .ingreso-cell {
                                min-height: 34px;
                                padding: 7px 8px;
                                border: 1px solid #d9e3ea;
                                background: #ffffff;
                                border-radius: 6px;
                                font-size: 12px;
                                overflow-wrap: anywhere;
                            }
                            </style>
                            <div class="ingreso-row-head">
                                <div>Cliente</div><div>Origenes</div><div>IDs</div><div>Ultimo movimiento</div><div>Monto</div><div>Metodo</div><div>Accion</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                        grupos_ingresos = []
                        for cliente_grupo, grupo in df_detalle_ingresos.groupby("Cliente", sort=False):
                            grupo = grupo.reset_index(drop=True)
                            origenes = ", ".join(dict.fromkeys(grupo["Origen"].fillna("").astype(str)))
                            metodos = ", ".join(dict.fromkeys(grupo["Método de pago"].fillna("").astype(str)))
                            ids_grupo = ", ".join([str(int(valor)) for valor in grupo["ID"]])
                            total_grupo = float(pd.to_numeric(grupo["Monto"], errors="coerce").fillna(0).sum())
                            grupos_ingresos.append({
                                "cliente": cliente_grupo,
                                "grupo": grupo,
                                "origenes": origenes,
                                "metodos": metodos,
                                "ids": ids_grupo,
                                "fecha": grupo.iloc[0]["Fecha/Hora"],
                                "total": total_grupo
                            })

                        for idx, ingreso_grupo in enumerate(grupos_ingresos):
                            cols_ingreso = st.columns([1.25, 1.15, 1.35, 1.2, .75, 1.1, 1.15])
                            with cols_ingreso[0]:
                                st.markdown(f"<div class='ingreso-cell'>{ingreso_grupo['cliente']}</div>", unsafe_allow_html=True)
                            with cols_ingreso[1]:
                                st.markdown(f"<div class='ingreso-cell'>{ingreso_grupo['origenes']}</div>", unsafe_allow_html=True)
                            with cols_ingreso[2]:
                                st.markdown(f"<div class='ingreso-cell'>{ingreso_grupo['ids']}</div>", unsafe_allow_html=True)
                            with cols_ingreso[3]:
                                st.markdown(f"<div class='ingreso-cell'>{ingreso_grupo['fecha']}</div>", unsafe_allow_html=True)
                            with cols_ingreso[4]:
                                st.markdown(f"<div class='ingreso-cell'>S/. {ingreso_grupo['total']:.2f}</div>", unsafe_allow_html=True)
                            with cols_ingreso[5]:
                                st.markdown(f"<div class='ingreso-cell'>{ingreso_grupo['metodos']}</div>", unsafe_allow_html=True)
                            with cols_ingreso[6]:
                                if st.button("IMPRIMIR NOTA DE VENTA", use_container_width=True, key=f"btn_reimprimir_ingreso_cliente_{idx}_{ingreso_grupo['cliente']}"):
                                    items_ticket = []
                                    total_ticket = 0
                                    for _, row in ingreso_grupo["grupo"].iterrows():
                                        cliente_imp, fecha_imp, items_imp, total_imp = detalle_ingreso_caja(
                                            row["Origen"],
                                            int(row["ID"]),
                                            float(row["Monto"] or 0)
                                        )
                                        total_ticket += float(total_imp or row["Monto"] or 0)
                                        if items_imp:
                                            for item in items_imp:
                                                items_ticket.append({
                                                    "producto": f"{row['Origen']} - {item[0]}",
                                                    "cantidad": item[1],
                                                    "subtotal": float(item[3] or 0)
                                                })
                                        else:
                                            items_ticket.append({"producto": row["Origen"], "cantidad": 1, "subtotal": float(row["Monto"] or 0)})
                                    encolar_impresion_nota(
                                        ingreso_grupo["cliente"],
                                        items_ticket,
                                        total_ticket,
                                        "REIMPRESION CONSOLIDADA",
                                        ""
                                    )
                                    st.rerun()
                        opciones_detalle = {}
                        for idx, ingreso_grupo in enumerate(grupos_ingresos):
                            etiqueta_detalle = f"{ingreso_grupo['cliente']} | {ingreso_grupo['origenes']} | S/. {ingreso_grupo['total']:.2f} | {ingreso_grupo['metodos']}"
                            opciones_detalle[etiqueta_detalle] = idx
                        seleccion_detalle = st.selectbox("Ver detalle del cliente", list(opciones_detalle.keys()), key="sb_detalle_ingreso_caja")
                        ingreso_detalle = grupos_ingresos[opciones_detalle[seleccion_detalle]]
                        filas_items_det = []
                        for _, fila_detalle in ingreso_detalle["grupo"].iterrows():
                            cliente_det, fecha_det, items_det, total_det = detalle_ingreso_caja(
                                fila_detalle["Origen"],
                                int(fila_detalle["ID"]),
                                float(fila_detalle["Monto"] or 0)
                            )
                            if items_det:
                                for item in items_det:
                                    filas_items_det.append((fila_detalle["Origen"], item[0], item[1], item[2], item[3]))
                            else:
                                filas_items_det.append((fila_detalle["Origen"], fila_detalle["Origen"], 1, fila_detalle["Monto"], fila_detalle["Monto"]))
                        st.markdown(f"#### Detalle de consumo - {ingreso_detalle['cliente']}")
                        st.write(f"Origenes: {ingreso_detalle['origenes']} | Metodo de pago: {ingreso_detalle['metodos']}")
                        if filas_items_det:
                            df_items_det = pd.DataFrame(filas_items_det, columns=["Origen", "Concepto", "Cantidad", "Precio", "Subtotal"])
                            st.dataframe(formatear_montos_df(df_items_det, ["Precio", "Subtotal"]), use_container_width=True, hide_index=True)
                        else:
                            st.info("No se encontraron artículos detallados para este ingreso.")
                        st.metric("Total del cliente", f"S/. {ingreso_detalle['total']:.2f}")
                    else:
                        st.info("No hay ingresos que coincidan con el método de pago o cliente buscado.")
                else:
                    st.info("No hay ingresos registrados en la caja abierta.")
            recaudacion_trab = ejecutar_query(
                """
                SELECT receptor, SUM(monto)
                FROM (
                    SELECT COALESCE(NULLIF(TRIM(metodo_pago),''),'Efectivo') receptor, total monto
                    FROM ventas
                    WHERE estado='PAGADO'
                      AND estado_caja='ABIERTO'
                      AND COALESCE(estado_boleta,'ACTIVA')!='LIBERADA'
                    UNION ALL
                    SELECT COALESCE(NULLIF(TRIM(metodo_pago),''),'Efectivo'), monto_pagado
                    FROM piscina
                    WHERE estado='PAGADO'
                      AND estado_caja='ABIERTO'
                    UNION ALL
                    SELECT COALESCE(NULLIF(TRIM(metodo_pago),''),'Efectivo'), adelanto
                    FROM cancha
                    WHERE estado_caja='ABIERTO'
                      AND estado!='ELIMINADA'
                      AND COALESCE(adelanto,0)>0
                    UNION ALL
                    SELECT COALESCE(NULLIF(TRIM(metodo_pago),''),'Efectivo'), (monto_total - adelanto)
                    FROM cancha
                    WHERE estado='PAGADO'
                      AND estado_caja='ABIERTO'
                      AND (monto_total - adelanto)>0
                    UNION ALL
                    SELECT COALESCE(NULLIF(TRIM(metodo_pago),''),'Efectivo'), monto_total
                    FROM reservas_local
                    WHERE estado='PAGADO'
                      AND estado_caja='ABIERTO'
                )
                GROUP BY receptor
                ORDER BY receptor
                """,
                fetch=True
            )
            if recaudacion_trab:
                st.markdown("### Recaudación por Trabajador")
                for receptor, monto in recaudacion_trab:
                    st.write(f"{receptor} -> S/. {monto:.2f}")
            
            st.markdown("---")
            col_rc1, col_rc2 = st.columns([1, 1.2])
            
            # --- COLUMNA 1: OPERACIÓN DE CIERRE ---
            with col_rc1:
                st.subheader("Realizar Cierre de Caja")
                st.write("Al cerrar caja, este monto se guardará en el historial financiero de forma definitiva.")
                pendientes_caja = operaciones_pendientes_caja()
                creditos_caja = creditos_abiertos_caja()
                if pendientes_caja:
                    st.error("Existen operaciones pendientes de cobro. Debe regularizarlas antes de cerrar la caja.")
                    st.dataframe(pd.DataFrame(pendientes_caja, columns=["Módulo", "ID", "Cliente", "Saldo pendiente"]), use_container_width=True, hide_index=True)
                mantener_creditos = True
                if creditos_caja:
                    st.warning("Existen cuentas registradas como crédito. No se sumarán al efectivo recaudado.")
                    st.dataframe(
                        pd.DataFrame(
                            creditos_caja,
                            columns=["Tipo", "ID", "Cliente", "Monto pendiente", "Módulo / Formulario", "Mesero", "Trabajador responsable"]
                        ),
                        use_container_width=True,
                        hide_index=True
                    )
                    mantener_creditos = st.checkbox("Mantener cuentas pendientes para el siguiente día", value=False, key="chk_mantener_creditos_caja")

                if st.button("CERRAR CAJA HOY Y EMPEZAR NUEVO DÍA", type="primary", use_container_width=True):
                    if pendientes_caja:
                        st.error("Existen operaciones pendientes de cobro. Debe regularizarlas antes de cerrar la caja.")
                    elif creditos_caja and not mantener_creditos:
                        st.warning("Confirme que desea mantener las cuentas crédito pendientes para el siguiente día.")
                    elif gran_total_caja >= 0:
                        fecha_cierre_str = fecha_hora_actual()
                        ejecutar_query("INSERT INTO historial_cajas (fecha_cierre, total_vendido, usuario_cierre) VALUES (?,?,?)", (fecha_cierre_str, gran_total_caja, st.session_state['usuario']), commit=True)
                        ultimo_id_res = ejecutar_query("SELECT id FROM historial_cajas ORDER BY id DESC LIMIT 1", fetch=True)
                        id_cierre_actual = ultimo_id_res[0][0] if ultimo_id_res else None

                        if id_cierre_actual:
                            ejecutar_query(f"UPDATE ventas SET estado_caja='CERRADO', id_cierre={id_cierre_actual} WHERE estado_caja='ABIERTO' AND estado='PAGADO'", commit=True)
                            ejecutar_query(f"UPDATE cancha SET estado_caja='CERRADO', id_cierre={id_cierre_actual} WHERE estado_caja='ABIERTO'", commit=True)
                            ejecutar_query(f"UPDATE piscina SET estado_caja='CERRADO', id_cierre={id_cierre_actual} WHERE estado_caja='ABIERTO' AND estado='PAGADO'", commit=True)
                            ejecutar_query(f"UPDATE reservas_local SET estado_caja='CERRADO', id_cierre={id_cierre_actual} WHERE estado_caja='ABIERTO' AND estado='PAGADO'", commit=True)
                        else:
                            ejecutar_query("UPDATE ventas SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO' AND estado='PAGADO'", commit=True)
                            ejecutar_query("UPDATE cancha SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO'", commit=True)
                            ejecutar_query("UPDATE piscina SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO' AND estado='PAGADO'", commit=True)
                            ejecutar_query("UPDATE reservas_local SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO' AND estado='PAGADO'", commit=True)

                        st.success("Caja cerrada correctamente. El sistema se ha reiniciado para el siguiente turno.")
                        st.rerun()
            
            # --- COLUMNA 2: TABLA HISTÓRICA GENERAL ---
            with col_rc2:
                st.subheader("Historial de Cajas Cerradas (Días Anteriores)")
                historico = ejecutar_query("SELECT id, fecha_cierre, total_vendido, usuario_cierre FROM historial_cajas ORDER BY id DESC", fetch=True)
                if historico:
                    df_hist = pd.DataFrame(historico, columns=["ID Cierre", "Fecha / Hora Cierre", "Monto Total Recaudado", "Cerrado Por"])
                    st.dataframe(df_hist, use_container_width=True, hide_index=True)
                else:
                    st.info("Aún no tienes cierres de caja registrados en el historial.")

            # --- SECCIÓN DE AUDITORÍA AVANZADA ---
            if historico:
                st.markdown("---")
                st.subheader("Auditoría Detallada de Cierres Anteriores")
                st.write("Selecciona un registro de caja cerrada para desglosar el origen de todos sus ingresos:")
                
                # Generamos una lista mapeada para que el usuario elija con facilidad
                lista_opciones_cierre = [f"Cierre #{reg[0]} — Fecha: {reg[1]} — Total: S/. {reg[2]:.2f}" for reg in historico]
                seleccion_cierre = st.selectbox("Seleccione el cierre que desea auditar:", lista_opciones_cierre, key="sb_auditoria_cierres_main")
                
                # Recuperamos el número identificador aislado del string de selección
                id_cierre_a_consultar = int(seleccion_cierre.split("#")[1].split(" ")[0])
                
                # Ejecutamos las consultas relacionales filtrando rigurosamente por el ID del cierre
                v_hist = ejecutar_query(f"SELECT id, cliente, total, fecha FROM ventas WHERE id_cierre={id_cierre_a_consultar}", fetch=True)
                p_hist = ejecutar_query(f"SELECT id, ninos, adultos, mayores, monto_pagado, fecha FROM piscina WHERE id_cierre={id_cierre_a_consultar}", fetch=True)
                c_hist = ejecutar_query(f"SELECT id, cliente, horario, tipo_cancha, monto_total, adelanto, estado, fecha_reserva FROM cancha WHERE id_cierre={id_cierre_a_consultar}", fetch=True)
                
                # Despliegue interactivo organizado en pestañas limpias
                tab_v, tab_p, tab_c = st.tabs(["🛒 Desglose de Ventas", "🏊‍♂️ Entradas Piscina", "⚽ Reservas de Canchas"])
                
                with tab_v:
                    if v_hist:
                        df_v_hist = pd.DataFrame(v_hist, columns=["ID Venta", "Cliente / Mesa", "Total Pagado", "Fecha / Hora"])
                        
                        st.write("💡 *Selecciona una fila para auditar los productos específicos comprados:*")
                        evento_seleccion = st.dataframe(
                            df_v_hist, 
                            use_container_width=True, 
                            hide_index=True,
                            on_select="rerun",
                            selection_mode="single-row",
                            key="tabla_auditoria_ventas"
                        )
                        
                        # Procesar la selección de la fila de forma segura e inofensiva
                        if evento_seleccion and "rows" in evento_seleccion["selection"] and evento_seleccion["selection"]["rows"]:
                            fila_index = evento_seleccion["selection"]["rows"][0]
                            id_venta_sel = int(df_v_hist.iloc[fila_index]["ID Venta"])
                            cliente_seleccionado = df_v_hist.iloc[fila_index]["Cliente / Mesa"]
                            
                            st.markdown(f"#### 📦 Productos Comprados por: `{cliente_seleccionado}` (Venta ID: {id_venta_sel})")
                            
                            # CAMBIO CLAVE: Consultamos la tabla 'detalle_ventas' relacional por 'venta_id'
                            # Esto rompe el vínculo fantasma con la tabla de créditos que activaba las boletas de mostrador
                            prod_comprados = ejecutar_query(
                                f"SELECT producto, cantidad, precio_unitario, subtotal FROM detalle_ventas WHERE venta_id={id_venta_sel}", 
                                fetch=True
                            )
                            
                            # RASTREO AUXILIAR: Si no existiera en detalle_ventas, busca en detalle_creditos pero de forma aislada
                            if not prod_comprados:
                                fecha_seleccionada = df_v_hist.iloc[fila_index]["Fecha / Hora"]
                                prod_comprados = ejecutar_query(
                                    f"SELECT producto, cantidad, precio_unitario, subtotal FROM detalle_creditos WHERE cliente='{cliente_seleccionado}' AND fecha LIKE '{fecha_seleccionada[:10]}%'", 
                                    fetch=True
                                )
                            
                            if prod_comprados:
                                df_prod = pd.DataFrame(prod_comprados, columns=["Producto / Plato", "Cantidad", "Precio Unitario", "Subtotal"])
                                # Renderizado plano sin botones, funciones ni disparadores extras
                                st.dataframe(df_prod, use_container_width=True, hide_index=True)
                            else:
                                st.warning("No se encontraron detalles de artículos individuales guardados para esta venta.")
                        
                        st.markdown("---")
                        st.metric("Total en Ventas del Cierre", f"S/. {df_v_hist['Total Pagado'].sum():.2f}")
                    else:
                        st.info("No se registraron ventas de productos en este cierre de caja.")
                        
                with tab_p:
                    if p_hist:
                        df_p_hist = pd.DataFrame(p_hist, columns=["ID Registro", "Niños", "Adultos", "Adultos Mayores", "Monto Recaudado", "Fecha / Hora"])
                        st.dataframe(df_p_hist, use_container_width=True, hide_index=True)
                        st.metric("Total Ingresos Piscina del Cierre", f"S/. {df_p_hist['Monto Recaudado'].sum():.2f}")
                    else:
                        st.info("No se registraron ingresos a la piscina en este cierre de caja.")
                        
                with tab_c:
                    if c_hist:
                        df_c_hist = pd.DataFrame(c_hist, columns=["ID Reserva", "Cliente", "Horario Alquiler", "Tipo Cancha", "Monto Contractual", "Adelanto Registrado", "Estado Inicial", "Fecha Reserva"])
                        df_c_hist["Saldo Cobrado"] = df_c_hist.apply(
                            lambda fila: max(float(fila["Monto Contractual"] or 0) - float(fila["Adelanto Registrado"] or 0), 0) if fila["Estado Inicial"] == "PAGADO" else 0,
                            axis=1
                        )
                        df_c_hist["Total Recaudado"] = df_c_hist["Adelanto Registrado"] + df_c_hist["Saldo Cobrado"]
                        st.dataframe(df_c_hist, use_container_width=True, hide_index=True)
                        
                        total_canchas_cierre = df_c_hist["Total Recaudado"].sum()
                        st.metric("Total Ingresos Canchas del Cierre", f"S/. {total_canchas_cierre:.2f}")
                    else:
                        st.info("No se registraron alquileres de canchas en este cierre de caja.")

    # =========================================================================
    # ROL: COCINERO (MEJORADO CON AGRUPACIÓN Y DISEÑO OPTIMIZADO V2)
    # =========================================================================
        # ---------------------------------------------------------------------
        # PESTAÑA 6: CONFIGURACION, MARCA, RESPALDOS Y SOPORTE
        # ---------------------------------------------------------------------
        elif modulo_actual == opciones_menu[6]:
            col_t1, col_t2 = st.columns([1, 1.4])
            with col_t1:
                st.subheader("Registrar trabajador")
                with st.form("form_trabajador", clear_on_submit=True):
                    nombre_trab = st.text_input("Nombre completo").strip().upper()
                    rol_trab = st.selectbox("Rol", ["Mesero", "Trabajador"])
                    asistio = st.checkbox("Asistió Hoy", value=True)
                    if st.form_submit_button("Guardar trabajador", type="primary", use_container_width=True):
                        if nombre_trab:
                            ejecutar_query(
                                "INSERT OR REPLACE INTO trabajadores (nombre, rol, asistio_hoy, activo) VALUES (?,?,?,1)",
                                (nombre_trab, rol_trab, "SI" if asistio else "NO"),
                                commit=True
                            )
                            st.success("Trabajador guardado.")
                            st.rerun()
                        else:
                            st.error("Ingrese el nombre del trabajador.")
            with col_t2:
                st.subheader("Control de asistencia")
                trabajadores = ejecutar_query("SELECT id, nombre, rol, asistio_hoy FROM trabajadores WHERE activo=1 ORDER BY rol, nombre", fetch=True)
                if trabajadores:
                    df_trab = pd.DataFrame(trabajadores, columns=["ID", "Nombre", "Rol", "Asistió Hoy"])
                    st.dataframe(df_trab, use_container_width=True, hide_index=True)
                    st.markdown("### Actualizar / eliminar")
                    ids_trab = {f"{t[1]} ({t[2]})": t[0] for t in trabajadores}
                    elegido = st.selectbox("Trabajador", list(ids_trab.keys()), key="sb_trab_admin")
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        if st.button("Asistió: SÍ", use_container_width=True):
                            ejecutar_query("UPDATE trabajadores SET asistio_hoy='SI' WHERE id=?", (ids_trab[elegido],), commit=True)
                            st.rerun()
                    with col_b:
                        if st.button("Asistió: NO", use_container_width=True):
                            ejecutar_query("UPDATE trabajadores SET asistio_hoy='NO' WHERE id=?", (ids_trab[elegido],), commit=True)
                            st.rerun()
                    with col_c:
                        if st.button("Eliminar", use_container_width=True):
                            ejecutar_query("UPDATE trabajadores SET activo=0 WHERE id=?", (ids_trab[elegido],), commit=True)
                            st.rerun()
                else:
                    st.info("Todavía no hay trabajadores registrados.")

        elif modulo_actual == opciones_menu[4]:
            tarifas_local_db = ejecutar_query("SELECT area, precio FROM tarifas_local", fetch=True)
            tarifas_local = {a: p for a, p in tarifas_local_db} if tarifas_local_db else {}
            col_l1, col_l2, col_l3 = st.columns([1.1, 1, 1.4])
            with col_l1:
                local_nonce = st.session_state.get("local_form_nonce", 0)
                st.subheader("Nueva reservación")
                cliente_local = st.text_input("Cliente", key=f"txt_cliente_local_{local_nonce}").strip().upper()
                area_local = st.selectbox("Área", ["Comedor Principal", "Comedor Piscina"], key=f"sb_area_local_{local_nonce}")
                fecha_local = st.date_input("Fecha de reserva", value=fecha_hoy_local(), key=f"fecha_local_{local_nonce}")
                horario_local = selector_horario_reserva(f"local_{local_nonce}")
                tarifa_local_actual = float(tarifas_local.get(area_local, 0.0))
                monto_local = st.number_input(
                    "Monto total (S/.)",
                    min_value=0.0,
                    value=tarifa_local_actual,
                    step=5.0,
                    key=f"monto_local_{local_nonce}_{area_local}_{tarifa_local_actual:.2f}"
                )
                trabajador_local_tipo, trabajador_local = seleccionar_trabajador("Atendido por", ("Trabajador",), f"local_atendido_{local_nonce}")
                metodo_local, receptor_local, receptor_nombre_local = seleccionar_pago_receptor(
                    f"local_{local_nonce}",
                    incluir_mesero=False,
                    receptor_preseleccionado={"tipo": "Trabajador", "nombre": trabajador_local}
                )
                if st.button("Guardar reserva de local", type="primary", use_container_width=True):
                    if not cliente_local:
                        st.error("Ingrese el cliente.")
                    else:
                        fecha_str = fecha_local.strftime("%Y-%m-%d")
                        cruce_local = ejecutar_query(
                            "SELECT id, cliente FROM reservas_local WHERE area=? AND fecha_reserva=? AND horario=? AND estado='PAGADO'",
                            (area_local, fecha_str, horario_local),
                            fetch=True
                        )
                        if cruce_local:
                            st.error(f"Horario no disponible para {area_local}. Ya existe reserva de {cruce_local[0][1]} (ID: {cruce_local[0][0]}).")
                        else:
                            ejecutar_query(
                                "INSERT INTO reservas_local (cliente, area, fecha_reserva, horario, monto_total, estado, metodo_pago, receptor_tipo, receptor_nombre, trabajador, estado_caja) VALUES (?,?,?,?,?,?,?,?,?,?, 'ABIERTO')",
                                (cliente_local, area_local, fecha_str, horario_local, monto_local, "PAGADO", metodo_local, receptor_local, receptor_nombre_local, trabajador_local),
                                commit=True
                            )
                            encolar_impresion_nota(cliente_local, [{"producto": f"RESERVA LOCAL - {area_local}", "cantidad": 1, "subtotal": monto_local}], monto_local, "RESERVA DE LOCAL", trabajador_local)
                            reiniciar_formulario("local")
                            st.rerun()
            with col_l2:
                st.subheader("Tarifas")
                p_principal = st.number_input("Comedor Principal", min_value=0.0, value=float(tarifas_local.get("Comedor Principal", 0.0)), step=5.0)
                p_piscina = st.number_input("Comedor Piscina", min_value=0.0, value=float(tarifas_local.get("Comedor Piscina", 0.0)), step=5.0)
                if st.button("Actualizar tarifas de local", use_container_width=True):
                    ejecutar_query("INSERT OR REPLACE INTO tarifas_local (area, precio) VALUES (?,?)", ("Comedor Principal", p_principal), commit=True)
                    ejecutar_query("INSERT OR REPLACE INTO tarifas_local (area, precio) VALUES (?,?)", ("Comedor Piscina", p_piscina), commit=True)
                    for key_estado in list(st.session_state.keys()):
                        if str(key_estado).startswith("monto_local_"):
                            del st.session_state[key_estado]
                    st.rerun()
            with col_l3:
                st.subheader("Historial")
                reservas_local = ejecutar_query("SELECT id, cliente, area, fecha_reserva, horario, monto_total, estado FROM reservas_local ORDER BY id DESC", fetch=True)
                if reservas_local:
                    st.dataframe(pd.DataFrame(reservas_local, columns=["ID", "Cliente", "Área", "Fecha", "Horario", "Monto", "Estado"]), use_container_width=True, hide_index=True)
                    ids_local = {f"ID {r[0]} - {r[1]} ({r[2]})": r[0] for r in reservas_local}
                    reserva_sel = st.selectbox("Reserva a modificar/eliminar", list(ids_local.keys()))
                    nuevo_cliente_local = st.text_input("Nuevo cliente", key="edit_cliente_local")
                    if st.button("Modificar cliente", use_container_width=True) and nuevo_cliente_local.strip():
                        ejecutar_query("UPDATE reservas_local SET cliente=? WHERE id=?", (nuevo_cliente_local.strip().upper(), ids_local[reserva_sel]), commit=True)
                        st.rerun()
                    if st.button("Eliminar reserva", use_container_width=True):
                        ejecutar_query("UPDATE reservas_local SET estado='ELIMINADA' WHERE id=?", (ids_local[reserva_sel],), commit=True)
                        st.rerun()
                else:
                    st.info("No hay reservas de local.")

        elif modulo_actual == opciones_menu[7]:
            st.caption("Administra identidad visual, respaldo de datos y canales de soporte.")

            col_cfg1, col_cfg2 = st.columns([1, 1])

            with col_cfg1:
                st.subheader("Identidad visual")
                logo_actual = obtener_config("logo_path")
                if logo_actual and Path(logo_actual).exists():
                    st.image(logo_actual, width=150, caption="Logo actual")
                nuevo_logo = st.file_uploader(
                    "Logo del sistema",
                    type=["png", "jpg", "jpeg", "webp"],
                    key="upload_logo_sistema"
                )
                if nuevo_logo and st.button("Guardar logo", type="primary", use_container_width=True):
                    ruta_logo = guardar_archivo_subido(nuevo_logo, "logo_sistema")
                    guardar_config("logo_path", ruta_logo)
                    st.success("Logo actualizado correctamente.")
                    st.rerun()

                st.markdown("---")
                fondo_actual = obtener_config("login_background_path")
                if fondo_actual and Path(fondo_actual).exists():
                    st.image(fondo_actual, caption="Fondo actual del inicio de sesión", use_container_width=True)
                nuevo_fondo = st.file_uploader(
                    "Imagen de fondo del inicio de sesión",
                    type=["png", "jpg", "jpeg", "webp"],
                    key="upload_fondo_login"
                )
                if nuevo_fondo and st.button("Guardar fondo de login", type="primary", use_container_width=True):
                    ruta_fondo = guardar_archivo_subido(nuevo_fondo, "fondo_login")
                    guardar_config("login_background_path", ruta_fondo)
                    st.success("Fondo de inicio de sesión actualizado correctamente.")
                    st.rerun()

            with col_cfg2:
                st.subheader("Copia de seguridad")
                st.write("Genera una copia completa del archivo SQLite del sistema.")
                if st.button("Crear copia de seguridad ahora", type="primary", use_container_width=True):
                    backup_creado, excel_creado = crear_backup_base_datos()
                    mensaje_backup = f"Copia creada: {backup_creado.name}"
                    if excel_creado:
                        mensaje_backup += f" | Excel: {excel_creado.name}"
                    st.success(mensaje_backup)

                backups = sorted(BACKUP_DIR.glob("*.db"), reverse=True)
                if backups:
                    df_backups = pd.DataFrame(
                        [
                            {
                                "Archivo": b.name,
                                "Fecha": datetime.fromtimestamp(b.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
                                "Tamaño KB": round(b.stat().st_size / 1024, 2)
                            }
                            for b in backups[:10]
                        ]
                    )
                    st.dataframe(df_backups, use_container_width=True, hide_index=True)
                    ultimo_backup = backups[0]
                    with ultimo_backup.open("rb") as archivo_backup:
                        st.download_button(
                            "Descargar última copia",
                            data=archivo_backup,
                            file_name=ultimo_backup.name,
                            mime="application/octet-stream",
                            use_container_width=True
                        )
                else:
                    st.info("Todavía no hay copias de seguridad creadas.")

            st.markdown("---")
            st.subheader("Soporte")
            st.markdown("""
            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px;">
                <a href="https://wa.me/51997630035" target="_blank" style="display:block; padding:14px 16px; border-radius:6px; background:#0f9ca7; color:white; text-decoration:none; font-weight:800; text-align:center;">
                    WhatsApp: +51 997630035
                </a>
                <a href="mailto:pacvangel2002@omail.com" style="display:block; padding:14px 16px; border-radius:6px; background:#1f2933; color:white; text-decoration:none; font-weight:800; text-align:center;">
                    Correo: pacvangel2002@omail.com
                </a>
            </div>
            """, unsafe_allow_html=True)

    elif st.session_state['rol'] == "Cocinero":
        if st.sidebar.button("🔓 Cerrar Sesión", type="secondary", use_container_width=True):
            logout()
        st.title("👨‍🍳 Monitor de Cocina - LAS MARÍAS")
        render_panel_cocina_tiempo_real()

        st.markdown("---")
        with st.expander("Historial de platos entregados", expanded=False):
            mesero_hist_sql = mesero_cocina_sql("c")
            historial_cocina = ejecutar_query(
                f"SELECT c.id, c.cliente, c.plato, c.cantidad, {mesero_hist_sql} AS mesero, COALESCE(c.fecha_entrega, c.fecha_hora), c.fecha_hora FROM cocina c WHERE c.estado='ENTREGADO' ORDER BY COALESCE(c.fecha_entrega, c.fecha_hora) DESC LIMIT 120",
                fetch=True
            )
            if historial_cocina:
                df_hist_cocina = pd.DataFrame(
                    historial_cocina,
                    columns=["ID Pedido", "Cliente / Mesa", "Plato", "Cantidad", "Mesero", "Hora de entrega", "Hora de pedido"]
                )
                df_hist_cocina["Tiempo de entrega"] = df_hist_cocina.apply(
                    lambda fila: calcular_tiempo_entrega(fila["Hora de pedido"], fila["Hora de entrega"]),
                    axis=1
                )
                df_hist_cocina = df_hist_cocina[
                    ["ID Pedido", "Cliente / Mesa", "Plato", "Cantidad", "Mesero", "Tiempo de entrega", "Hora de entrega", "Hora de pedido"]
                ]
                st.dataframe(df_hist_cocina, use_container_width=True, hide_index=True)
            else:
                st.info("Aún no hay platos entregados para mostrar.")
