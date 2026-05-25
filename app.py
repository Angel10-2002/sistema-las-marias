import streamlit as st
import pandas as pd
import sqlite3
import secrets
import base64
import mimetypes
import shutil
from datetime import datetime
from pathlib import Path

# Configuración de página
st.set_page_config(page_title="Complejo Recreativo Las Marías", layout="wide", page_icon="🏊‍♂️")

DB_NAME = "complejo.db"
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
BACKUP_DIR = BASE_DIR / "backups"

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

    # Registros iniciales por defecto
    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('administrador', 'admin123', 'Administrador')")
    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('cocinero', 'cocina123', 'Cocinero')")
    cursor.execute("INSERT OR IGNORE INTO tarifas VALUES ('Niños', 5.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas VALUES ('Adultos', 10.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas VALUES ('Mayores', 7.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_cancha VALUES ('Cancha Grande', 70.0)")
    cursor.execute("INSERT OR IGNORE INTO tarifas_cancha VALUES ('Media Cancha', 40.0)")
    
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

def formatear_montos_df(df, columnas):
    df_formateado = df.copy()
    for columna in columnas:
        if columna in df_formateado.columns:
            df_formateado[columna] = pd.to_numeric(df_formateado[columna], errors="coerce").fillna(0).map(lambda valor: f"{valor:.2f}")
    return df_formateado

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
    origen = BASE_DIR / DB_NAME
    marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = BACKUP_DIR / f"backup_complejo_{marca_tiempo}.db"
    shutil.copy2(origen, destino)
    return destino

preparar_directorios_sistema()

# --- INICIALIZAR CARRITO TEMPORAL ---
if 'carrito' not in st.session_state:
    st.session_state['carrito'] = []

# --- MODAL DE IMPRESIÓN REFORMATEADO Y OPTIMIZADO PARA IMPRESORA TÉRMICA ---
@st.dialog("📄 Boleto de Venta - LAS MARÍAS")
def mostrar_ticket_multiple(cliente, items, total, tipo):
    fecha_ticket = datetime.now().strftime('%d/%m/%Y %H:%M')
    
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
            <b style="font-size: 16px; letter-spacing: 1px;">RC. LAS MARÍAS</b><br>
            <span style="font-size: 11px; color: #333;">COMPLEJO RECREATIVO</span><br>
            <span style="font-size: 11px; color: #333;">Sullana, Piura, Perú</span><br>
            <small>----------------------------------</small>
        </div>
        
        <div style="font-size: 12px; margin-bottom: 8px; text-align: left;">
            <b>FECHA:</b> {fecha_ticket}<br>
            <b>CLIENTE:</b> {cliente}<br>
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

        .block-container {
            padding-top: 1rem;
            padding-bottom: 3rem;
            max-width: 1500px;
        }

        [data-testid="stSidebar"] {
            background: #222b35;
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }

        [data-testid="stSidebar"] * {
            color: #ffffff !important;
        }

        [data-testid="stSidebar"] [data-testid="stImage"] {
            display: flex;
            justify-content: center;
            align-items: center;
            margin-top: 14px;
            margin-bottom: 10px;
            width: 100%;
        }

        [data-testid="stSidebar"] img {
            display: block;
            margin-left: auto;
            margin-right: auto;
            padding: 8px;
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.10);
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.24);
        }

        [data-testid="stSidebar"] h1 {
            font-size: 22px;
            font-weight: 800;
            text-align: center;
            margin-bottom: 8px;
        }

        [data-testid="stSidebar"] [data-testid="stAlert"] {
            background: rgba(255, 255, 255, 0.10);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 8px;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] {
            gap: 3px;
            background: transparent;
            border: 0;
        }

        [data-testid="stSidebar"] label[data-baseweb="radio"] {
            min-height: 38px;
            margin: 0;
            padding: 8px 10px;
            border-radius: 4px;
            color: #d7e0e8 !important;
            transition: background 0.15s ease;
        }

        [data-testid="stSidebar"] label[data-baseweb="radio"]:hover {
            background: rgba(22, 184, 196, 0.18);
        }

        [data-testid="stSidebar"] label[data-baseweb="radio"] > div:first-child {
            display: none;
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
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            if st.button("Ingresar", use_container_width=True):
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
    if st.session_state['rol'] == "Administrador":
        opciones_menu = [
            "🛒 Ventas y Cocina",
            "📦 Control de Stock",
            "🏊‍♂️ Control de piscina",
            "⚽ Control de Cancha",
            "💰 Caja y Reportes",
            "⚙️ Configuración"
        ]
        titulos_modulos = {
            opciones_menu[0]: "Generar Nueva Venta / Crédito",
            opciones_menu[1]: "Control e Ingreso de Mercadería",
            opciones_menu[2]: "Ingreso y Control de la Piscina",
            opciones_menu[3]: "Reservas de Cancha",
            opciones_menu[4]: "Control de Finanzas y Cierre de Caja Diaria",
            opciones_menu[5]: "Configuración del Sistema"
        }
        modulo_actual = resolver_modulo_admin(opciones_menu)
        st.sidebar.markdown("### Menú Principal")
        st.sidebar.radio(
            "Módulos",
            opciones_menu,
            label_visibility="collapsed",
            key="modulo_admin_selector",
            on_change=cambiar_modulo_admin
        )
        modulo_actual = st.session_state["modulo_admin_activo"]
        if st.sidebar.button("Cerrar Sesión", type="secondary", use_container_width=True):
            logout()

        st.title("Panel de Administración - LAS MARIAS")
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

            col_v1, col_v2 = st.columns([1.2, 1])
            
            # 1. OBTENER DATOS ACTUALIZADOS DE LA BASE DE DATOS
            productos = ejecutar_query("SELECT nombre, precio, stock, proveedor FROM inventario WHERE stock > 0", fetch=True)
            dict_productos = {p[0]: {"precio": p[1], "stock": p[2], "proveedor": p[3]} for p in productos}
            
            # Cargar los clientes que actualmente tienen deudas activas para el buscador
            clientes_credito_activos = ejecutar_query("SELECT DISTINCT cliente FROM ventas WHERE estado='CREDITO'", fetch=True)
            lista_clientes_base = [c[0] for c in clientes_credito_activos] if clientes_credito_activos else []
            
            # --- COLUMNA IZQUIERDA: AGREGAR PRODUCTOS Y MONITOR DE COCINA ---
            with col_v1:
                if dict_productos:
                    prod_sel = st.selectbox("Seleccione el Producto/Plato", list(dict_productos.keys()), key="sb_producto_venta")
                    cant = st.number_input("Cantidad", min_value=1, value=1, key="num_cantidad_venta")
                    
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
                                st.rerun()
                            else:
                                st.error("No puedes añadir esa cantidad, supera el stock disponible en el inventario.")
                else:
                    st.info("No hay productos con stock registrado en el inventario.")
                
                st.markdown("---")
                st.subheader("👨‍🍳 Monitor de Cocina (Platos Pendientes)")
                pendientes = ejecutar_query("SELECT id, cliente, plato, cantidad, fecha_hora FROM cocina WHERE estado='PENDIENTE' ORDER BY id ASC", fetch=True)
                if pendientes:
                    df_pend = pd.DataFrame(pendientes, columns=["ID Pedido", "Cliente / Mesa", "Plato", "Cantidad", "Fecha/Hora"])
                    st.dataframe(df_pend, use_container_width=True, hide_index=True)
                    
                    st.markdown("##### ⚙️ Modificar / Anular Pedido Pendiente")
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
                else:
                    st.success("¡Cocina al día!")

                with st.expander("Ver historial de platos entregados", expanded=False):
                    historial_cocina = ejecutar_query(
                        "SELECT id, cliente, plato, cantidad, COALESCE(fecha_entrega, fecha_hora), fecha_hora FROM cocina WHERE estado='ENTREGADO' ORDER BY COALESCE(fecha_entrega, fecha_hora) DESC LIMIT 80",
                        fetch=True
                    )
                    if historial_cocina:
                        df_hist_cocina = pd.DataFrame(
                            historial_cocina,
                            columns=["ID Pedido", "Cliente / Mesa", "Plato", "Cantidad", "Hora de entrega", "Hora de pedido"]
                        )
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
                    cliente_input = st.text_input("Nombre del Cliente / Mesa:", value="General", key="txt_cliente_mostrador")
                    cliente_final = cliente_input.strip().upper() if cliente_input.strip() else "GENERAL"
                
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
                                fecha_actual = datetime.now().strftime('%Y-%m-%d %H:%M')
                                
                                # A. Restar del inventario y mandar a cocina si aplica
                                for item in st.session_state['carrito']:
                                    st_act = ejecutar_query("SELECT stock FROM inventario WHERE nombre=?", (item['producto'],), fetch=True)[0][0]
                                    ejecutar_query("UPDATE inventario SET stock=? WHERE nombre=?", (st_act - item['cantidad'], item['producto']), commit=True)
                                    
                                    if str(item['proveedor']).strip().upper() == "INTERNO":
                                        ejecutar_query("INSERT INTO cocina (cliente, plato, cantidad, fecha_hora, estado) VALUES (?,?,?,?,?)",
                                                       (cliente_final, item['producto'], item['cantidad'], fecha_actual, "PENDIENTE"), commit=True)
                                
                                # B. Si es cuenta de crédito
                                if tipo_pago == "LLEVAR A CUENTA CRÉDITO (Anotar en lista histórica)":
                                    existe_cabecera = ejecutar_query("SELECT id, total FROM ventas WHERE cliente=? AND estado='CREDITO'", (cliente_final,), fetch=True)
                                    
                                    if existe_cabecera:
                                        id_venta_existente, total_antiguo = existe_cabecera[0]
                                        nuevo_total_maestro = total_antiguo + total_carrito
                                        ejecutar_query("UPDATE ventas SET total=? WHERE id=?", (nuevo_total_maestro, id_venta_existente), commit=True)
                                    else:
                                        ejecutar_query("INSERT INTO ventas (cliente, total, estado, fecha, estado_caja) VALUES (?,?,?,?, 'ABIERTO')",
                                                       (cliente_final, total_carrito, "CREDITO", fecha_actual), commit=True)
                                    
                                    for item in st.session_state['carrito']:
                                        ejecutar_query("INSERT INTO detalle_creditos (cliente, producto, cantidad, precio_unitario, subtotal, fecha) VALUES (?,?,?,?,?,?)",
                                                       (cliente_final, item['producto'], item['cantidad'], item['precio_unitario'], item['subtotal'], fecha_actual), commit=True)
                                    
                                    st.success(f"¡Cargado con éxito al crédito de {cliente_final}!")
                                    st.session_state['carrito'] = []
                                    st.rerun()
                                
                                # C. Si es pago al instante (CONTROLADO LOCALMENTE)
                                else:
                                    ejecutar_query("INSERT INTO ventas (cliente, total, estado, fecha, estado_caja) VALUES (?,?,?,?, 'ABIERTO')",
                                                   (cliente_final, total_carrito, "PAGADO", fecha_actual), commit=True)
                                    
                                    ultimo_id_req = ejecutar_query("SELECT max(id) FROM ventas", fetch=True)
                                    venta_id = ultimo_id_req[0][0] if ultimo_id_req else 1
                                    
                                    for item in st.session_state['carrito']:
                                        ejecutar_query("INSERT INTO detalle_ventas (venta_id, producto, cantidad, precio_unitario, subtotal) VALUES (?,?,?,?,?)",
                                                       (venta_id, item['producto'], item['cantidad'], item['precio_unitario'], item['subtotal']), commit=True)
                                    
                                    # CARGAMOS LOS DATOS EN EL ESTADO TEMPORAL LOCAL
                                    st.session_state["ticket_cliente"] = cliente_final
                                    st.session_state["ticket_items"] = list(st.session_state['carrito'])
                                    st.session_state["ticket_total"] = total_carrito
                                    st.session_state["ticket_tipo"] = "VENTA EN MOSTRADOR"
                                    st.session_state["ticket_listo"] = True
                                    
                                    st.session_state['carrito'] = []
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
                            detalles = ejecutar_query("SELECT producto, cantidad, precio_unitario, subtotal FROM detalle_creditos WHERE cliente=?", (cliente_a_cobrar,), fetch=True)
                            
                            if detalles:
                                st.markdown(f"**Detalle de consumo real para: {cliente_a_cobrar}**")
                                df_detalles = pd.DataFrame(detalles, columns=["Producto", "Cantidad", "Unidad P.", "Total parcial"])
                                st.table(formatear_montos_df(df_detalles, ["Unidad P.", "Total parcial"]))
                                
                                total_deuda = df_detalles["Total parcial"].sum()
                                
                                if st.button(f"💵 Cerrar Cuenta y Cobrar S/. {total_deuda:.2f}", type="primary", use_container_width=True, key="btn_liquidar_final"):
                                    ejecutar_query("UPDATE ventas SET estado='PAGADO' WHERE cliente=? AND estado='CREDITO'", (cliente_a_cobrar,), commit=True)
                                    
                                    items_boleta = []
                                    for prod, cant_b, p_uni, sub in detalles:
                                        items_boleta.append({
                                            "producto": prod,
                                            "cantidad": cant_b,
                                            "precio_unitario": p_uni,
                                            "subtotal": sub
                                        })
                                    
                                    ejecutar_query("DELETE FROM detalle_creditos WHERE cliente=?", (cliente_a_cobrar,), commit=True)
                                    
                                    # CARGAMOS LOS DATOS EN EL ESTADO TEMPORAL LOCAL PARA LA LIQUIDACIÓN
                                    st.session_state["ticket_cliente"] = cliente_a_cobrar
                                    st.session_state["ticket_items"] = items_boleta
                                    st.session_state["ticket_total"] = total_deuda
                                    st.session_state["ticket_tipo"] = "LIQUIDACIÓN DE CRÉDITO"
                                    st.session_state["ticket_listo"] = True
                                    st.rerun()
                    else:
                        st.info("No hay deudas pendientes.")

            # --- BLOQUE DE RENDERIZADO DEL TICKET (EXCLUSIVO Y SEGURO) ---
            # Este contenedor se pinta abajo de la PESTAÑA 1 únicamente si la bandera local es True.
            # No usa Modales/Dialogs propensos a colapsar, y añade un botón para limpiar el estado por completo.
            if st.session_state["ticket_listo"]:
                st.markdown("---")
                st.markdown("### 📄 Comprobante Generado Exitosamente")
                
                # Caja estilizada que emula el contenedor flotante anterior, pero seguro
                with st.container(border=True):
                    mostrar_ticket_multiple(
                        st.session_state["ticket_cliente"],
                        st.session_state["ticket_items"],
                        st.session_state["ticket_total"],
                        st.session_state["ticket_tipo"]
                    )
                    
                    if st.button("✅ Confirmar y Quitar Boleta de la Pantalla", use_container_width=True, type="primary", key="btn_cerrar_ticket_seguro"):
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
            
            with col_st1:
                with st.form("ingreso_stock", clear_on_submit=True):
                    # CORRECCIÓN: Título limpio sin emoji
                    st.subheader("Registrar Nuevo / Aumentar Ingreso")
                    col_s1, col_s2, col_s3 = st.columns(3)
                    with col_s1:
                        s_nombre = st.text_input("Nombre del Producto / Insumo")
                        s_proveedor = st.text_input("Proveedor (Escribe 'INTERNO' si es plato)")
                    with col_s2:
                        s_costo = st.number_input("Costo de Compra (S/.)", min_value=0.0, step=0.5)
                        s_precio = st.number_input("Precio de Venta (S/.)", min_value=0.0, step=0.5)
                    with col_s3:
                        s_stock = st.number_input("Cantidad que Ingresa", min_value=1, step=1)
                        s_fecha = st.date_input("Fecha de Ingreso")
                    
                    if st.form_submit_button("Guardar En Inventario", type="primary"):
                        if s_nombre:
                            s_nombre_formato = s_nombre.strip().upper()
                            prov_formato = s_proveedor.strip().upper() if s_proveedor.strip() else "DISTRIBUIDORA"
                            existe = ejecutar_query("SELECT id, stock FROM inventario WHERE nombre=?", (s_nombre_formato,), fetch=True)
                            if existe:
                                nuevo_stock = existe[0][1] + s_stock
                                ejecutar_query("UPDATE inventario SET proveedor=?, fecha_ingreso=?, costo=?, precio=?, stock=? WHERE id=?",
                                               (prov_formato, s_fecha.strftime('%Y-%m-%d'), s_costo, s_precio, nuevo_stock, existe[0][0]), commit=True)
                            else:
                                ejecutar_query("INSERT INTO inventario (nombre, proveedor, fecha_ingreso, costo, precio, stock) VALUES (?,?,?,?,?,?)",
                                               (s_nombre_formato, prov_formato, s_fecha.strftime('%Y-%m-%d'), s_costo, s_precio, s_stock), commit=True)
                            st.success("¡Inventario Actualizado!")
                            st.rerun()

            with col_st2:
                # CORRECCIÓN: Título limpio sin emoji
                st.subheader("Panel de Edición y Eliminación")
                items_db = ejecutar_query("SELECT id, nombre, proveedor, costo, precio, stock FROM inventario", fetch=True)
                
                if items_db:
                    opciones_items = {f"{item[1]} (ID: {item[0]})": item for item in items_db}
                    item_seleccionado = st.selectbox("Selecciona el producto a modificar:", list(opciones_items.keys()))
                    
                    if item_seleccionado:
                        id_edit, nom_edit, prov_edit, cost_edit, prec_edit, stock_edit = opciones_items[item_seleccionado]
                        
                        col_ed1, col_ed2 = st.columns(2)
                        with col_ed1:
                            nuevo_nombre = st.text_input("Editar Nombre", value=nom_edit)
                            nuevo_prov = st.text_input("Editar Proveedor", value=prov_edit)
                            nuevo_stock_val = st.number_input("Ajustar Stock Real", min_value=0, value=int(stock_edit))
                        with col_ed2:
                            nuevo_costo_val = st.number_input("Editar Costo (S/.)", min_value=0.0, value=float(cost_edit), step=0.5)
                            nuevo_precio_val = st.number_input("Editar Precio Venta (S/.)", min_value=0.0, value=float(prec_edit), step=0.5)
                        
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            if st.button("📝 Guardar Cambios", use_container_width=True):
                                if nuevo_nombre.strip():
                                    ejecutar_query(
                                        "UPDATE inventario SET nombre=?, proveedor=?, costo=?, precio=?, stock=? WHERE id=?",
                                        (nuevo_nombre.strip().upper(), nuevo_prov.strip().upper(), nuevo_costo_val, nuevo_precio_val, nuevo_stock_val, id_edit),
                                        commit=True
                                    )
                                    st.success("¡Modificado!")
                                    st.rerun()
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
                
                ninos = st.number_input(
                    "Cantidad de Niños / Niñas", 
                    min_value=0, step=1, value=0,
                    help="Considerados desde los 0 hasta los 17 años de edad."
                )
                st.caption("*Niños: 17 años a menos*")
                
                adultos = st.number_input(
                    "Cantidad de Adultos", 
                    min_value=0, step=1, value=0,
                    help="Considerados desde los 18 hasta los 50 años de edad."
                )
                st.caption("*Adultos: De 18 a 50 años*")
                
                mayores = st.number_input(
                    "Cantidad de Adultos Mayores (Ancianos)", 
                    min_value=0, step=1, value=0,
                    help="Considerados desde los 51 años de edad para adelante."
                )
                st.caption("*Adultos Mayores: De 51 años a más*")
                
                # Cálculo automático en tiempo real basado en la selección
                calculo_sugerido = (ninos * p_nino) + (adultos * p_adulto) + (mayores * p_mayor)
                st.warning(f"Pago Sugerido: S/. {calculo_sugerido:.2f}")
                
                monto_final = st.number_input("Monto Final Recibido", min_value=0.0, value=float(calculo_sugerido), step=1.0)
                monto_mayor_al_sugerido = monto_final > calculo_sugerido
                if monto_mayor_al_sugerido:
                    st.warning("El monto final no puede ser mayor al pago sugerido. Ajusta el importe para continuar.")
                
                if st.button("Registrar Ingreso Piscina", use_container_width=True, type="primary"):
                    if ninos == 0 and adultos == 0 and mayores == 0:
                        st.error("Debes ingresar al menos 1 persona para registrar la entrada.")
                    elif monto_mayor_al_sugerido:
                        st.error("No se guardó el ingreso porque el monto final supera el pago sugerido.")
                    else:
                        # Registro en base de datos manteniendo el control de caja abierto para los turnos
                        fecha_registro = datetime.now().strftime('%Y-%m-%d %H:%M')
                        ejecutar_query(
                            "INSERT INTO piscina (ninos, adultos, mayores, monto_pagado, fecha, estado_caja) VALUES (?,?,?,?,?, 'ABIERTO')",
                            (ninos, adultos, mayores, monto_final, fecha_registro), 
                            commit=True
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
                        
                        # Disparador del ticket de acceso
                        st.session_state["ticket_piscina_listo"] = True
                        st.session_state["ticket_piscina_items"] = items_piscina_ticket
                        st.session_state["ticket_piscina_total"] = monto_final
                        st.session_state["ticket_piscina_fecha"] = fecha_registro

                if st.session_state.get("ticket_piscina_listo"):
                    st.markdown("---")
                    st.markdown("### Comprobante de Piscina Generado")
                    with st.container(border=True):
                        mostrar_ticket_multiple(
                            "CLIENTE PISCINA",
                            st.session_state.get("ticket_piscina_items", []),
                            st.session_state.get("ticket_piscina_total", 0.0),
                            "ACCESO PISCINA"
                        )
                        if st.button("Confirmar y Quitar Boleta de Piscina", use_container_width=True, type="primary", key="btn_cerrar_ticket_piscina"):
                            st.session_state["ticket_piscina_listo"] = False
                            st.session_state["ticket_piscina_items"] = []
                            st.session_state["ticket_piscina_total"] = 0.0
                            st.session_state["ticket_piscina_fecha"] = ""
                            st.rerun()
            
            # --- COLUMNA 2: CONFIGURACIÓN DE TARIFAS POR CATEGORÍA ---
            with col_p2:
                st.subheader("Panel de Tarifas Piscina")
                nuevo_p_nino = st.number_input("Precio Entrada Niños (S/.)", min_value=0.0, value=float(p_nino), step=0.5, help="Tarifa aplicable a menores de 18 años.")
                nuevo_p_adulto = st.number_input("Precio Entrada Adultos (S/.)", min_value=0.0, value=float(p_adulto), step=0.5, help="Tarifa aplicable de 18 a 50 años.")
                nuevo_p_mayor = st.number_input("Precio Entrada Mayores (S/.)", min_value=0.0, value=float(p_mayor), step=0.5, help="Tarifa aplicable desde los 51 años en adelante.")
                
                if st.button("🔄 Actualizar Tarifas Piscina", use_container_width=True):
                    ejecutar_query("UPDATE tarifas SET precio=? WHERE categoria='Niños'", (nuevo_p_nino,), commit=True)
                    ejecutar_query("UPDATE tarifas SET precio=? WHERE categoria='Adultos'", (nuevo_p_adulto,), commit=True)
                    ejecutar_query("UPDATE tarifas SET precio=? WHERE categoria='Mayores'", (nuevo_p_mayor,), commit=True)
                    st.success("¡Tarifas de edad actualizadas con éxito!")
                    st.rerun()

            # --- COLUMNA 3: HISTORIAL RECIENTE DE ENTRADAS ---
            with col_p3:
                st.subheader("Historial de Entradas")
                registros_piscina = ejecutar_query("SELECT ninos, adultos, mayores, monto_pagado, fecha FROM piscina ORDER BY id DESC", fetch=True)
                if registros_piscina:
                    df_pis = pd.DataFrame(registros_piscina, columns=["Niños", "Adultos", "Adultos Mayores", "Monto", "Fecha/Hora"])
                    st.dataframe(df_pis, use_container_width=True, hide_index=True)
                else:
                    st.info("No se registran ingresos a la piscina el día de hoy.")

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
            
            precio_grande = dict_t_cancha.get("Cancha Grande", 70.0)
            precio_media = dict_t_cancha.get("Media Cancha", 40.0)

            col_c1, col_c2, col_c3 = st.columns([1.3, 1.1, 1.6])
            
            # --- COLUMNA 1: REGISTRO DE NUEVA RESERVA ---
            with col_c1:
                c_cliente = st.text_input("Nombre del Cliente")
                c_fecha = st.date_input("Fecha del Alquiler", value=datetime.today())
                
                st.markdown("**Horario de la Reserva:**")
                c_c1, c_c2 = st.columns(2)
                with c_c1:
                    hora_num = st.selectbox("Hora", [str(i) for i in range(1, 13)], index=9)
                with c_c2:
                    # CORRECCIÓN: Usamos puntos para evitar que el traductor del navegador lo cambie por "SOY"
                    periodo = st.selectbox("Periodo", ["P.M.", "A.M."], index=0)
                
                horario_final_str = f"{hora_num}:00 {periodo}"
                tipo_cancha_sel = st.selectbox("Tipo de Cancha", ["Cancha Grande", "Media Cancha"])
                costo_base_cancha = precio_grande if tipo_cancha_sel == "Cancha Grande" else precio_media
                
                c_total = st.number_input("Monto Total Contractual (S/.)", min_value=0.0, value=float(costo_base_cancha))
                c_adelanto = st.number_input("Monto de Adelanto (S/.)", min_value=0.0, value=0.0)
                
                if st.button("Guardar Reserva de Cancha", type="primary", use_container_width=True):
                    if not c_cliente.strip():
                        st.error("Por favor, ingresa el nombre del cliente.")
                    else:
                        fecha_str = c_fecha.strftime('%Y-%m-%d')
                        
                        # Validación de disponibilidad para evitar duplicados (compara usando el estado activo)
                        cruce_db = ejecutar_query(
                            "SELECT id, cliente FROM cancha WHERE fecha_reserva = ? AND horario = ? AND tipo_cancha = ? AND estado IN ('PENDIENTE', 'PAGADO')",
                            (fecha_str, horario_final_str, tipo_cancha_sel),
                            fetch=True
                        )
                        
                        if cruce_db:
                            id_existente, cliente_existente = cruce_db[0]
                            st.error(f"❌ Horario NO disponible. La {tipo_cancha_sel} ya está reservada para el {fecha_str} a las {horario_final_str} por el cliente: {cliente_existente} (ID: {id_existente}).")
                        else:
                            ejecutar_query(
                                "INSERT INTO cancha (cliente, fecha_reserva, horario, tipo_cancha, monto_total, adelanto, estado, estado_caja) VALUES (?,?,?,?,?,?,?, 'ABIERTO')",
                                (c_cliente.strip().upper(), fecha_str, horario_final_str, tipo_cancha_sel, c_total, c_adelanto, "PENDIENTE"), 
                                commit=True
                            )
                            st.success("¡Reserva guardada correctamente!")
                            if c_adelanto > 0:
                                it_cancha = [{"producto": f"Adelanto Alquiler ({tipo_cancha_sel})", "cantidad": 1, "subtotal": c_adelanto}]
                                mostrar_ticket_multiple(c_cliente.strip().upper(), it_cancha, c_adelanto, "ADELANTO ALQUILER")
                            else:
                                st.rerun()
                        
            # --- COLUMNA 2: CONFIGURACIÓN DE TARIFAS Y LIQUIDACIÓN FLEXIBLE ---
            with col_c2:
                st.subheader("Panel de Tarifas Canchas")
                nuevo_p_grande = st.number_input("Cancha Grande / Hora (S/.)", min_value=0.0, value=float(precio_grande), step=5.0)
                nuevo_p_media = st.number_input("Media Cancha / Hora (S/.)", min_value=0.0, value=float(precio_media), step=5.0)
                
                if st.button("Actualizar Precios Cancha", use_container_width=True):
                    ejecutar_query("UPDATE tarifas_cancha SET precio=? WHERE tipo='Cancha Grande'", (nuevo_p_grande,), commit=True)
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
                        check_reserva = ejecutar_query("SELECT cliente, monto_total, adelanto FROM cancha WHERE id=?", (id_cancha_liquidar,), fetch=True)
                        if check_reserva:
                            cliente_c, tot_c, ade_c = check_reserva[0]
                            restante = tot_c - ade_c
                            ejecutar_query("UPDATE cancha SET estado='PAGADO', estado_caja='ABIERTO' WHERE id=?", (id_cancha_liquidar,), commit=True)
                            st.success(f"¡Reserva ID {id_cancha_liquidar} saldada por completo!")
                            it_liq = [{"producto": "Saldo Restante Cancha", "cantidad": 1, "subtotal": restante}]
                            mostrar_ticket_multiple(cliente_c, it_liq, restante, "LIQUIDACIÓN CANCHA")
                        else:
                            st.error("El ID de reserva ingresado no existe en el sistema.")

            # --- COLUMNA 3: HISTORIAL MODIFICADO CON COLUMNA FECHA ---
            with col_c3:
                st.subheader("Historial de Reservas")
                
                buscar_cliente = st.text_input("🔍 Buscar reserva por nombre de cliente:", placeholder="Escribe el nombre aquí...").strip().upper()
                
                reservas = ejecutar_query("SELECT id, cliente, fecha_reserva, horario, monto_total, adelanto, estado FROM cancha ORDER BY id DESC", fetch=True)
                
                if reservas:
                    df_res = pd.DataFrame(reservas, columns=["ID", "Cliente", "Fecha", "Horario", "Total", "Adelanto", "Estado"])
                    
                    if buscar_cliente:
                        df_res = df_res[df_res["Cliente"].str.contains(buscar_cliente, na=False)]
                    
                    if not df_res.empty:
                        st.dataframe(df_res, use_container_width=True, hide_index=True)
                    else:
                        st.warning("No se encontraron reservas que coincidan con la búsqueda.")
                else:
                    st.info("No hay reservas registradas en el sistema.")

        # ---------------------------------------------------------------------
        # PESTAÑA 5: CAJA Y REPORTES DIARIOS (100% BLINDADA CONTRA COMPROBANTES FANTASMAS)
        # ---------------------------------------------------------------------
        elif modulo_actual == opciones_menu[4]:
            # --- LIMPIEZA PROACTIVA DE BOLETAS AL ENTRAR A FINANZAS ---
            # Si el usuario entra aquí, apagamos inmediatamente cualquier rastro del ticket de la Pestaña 1
            if "ticket_listo" in st.session_state:
                st.session_state["ticket_listo"] = False
            if "mostrar_boleta" in st.session_state:
                st.session_state["mostrar_boleta"] = False
            if "mostrar_ticket" in st.session_state:
                st.session_state["mostrar_ticket"] = False
            
            # --- CONSULTA DE LA CAJA ACTIVA (TURNO ACTUAL) ---
            ventas_hoy = ejecutar_query("SELECT total FROM ventas WHERE estado='PAGADO' AND estado_caja='ABIERTO'", fetch=True)
            piscina_hoy = ejecutar_query("SELECT monto_pagado FROM piscina WHERE estado_caja='ABIERTO'", fetch=True)
            canchas_hoy = ejecutar_query("SELECT adelanto FROM cancha WHERE estado_caja='ABIERTO'", fetch=True)
            canchas_saldos_hoy = ejecutar_query("SELECT (monto_total - adelanto) FROM cancha WHERE estado='PAGADO' AND estado_caja='ABIERTO'", fetch=True)
            
            total_v = sum([v[0] for v in ventas_hoy])
            total_p = sum([p[0] for p in piscina_hoy])
            total_c = sum([c[0] for c in canchas_hoy]) + sum([cs[0] for cs in canchas_saldos_hoy])
            
            gran_total_caja = total_v + total_p + total_c
            
            cm1, cm2, cm3, cm4 = st.columns(4)
            with cm1: st.metric("🛒 Ventas de Productos", f"S/. {total_v:.2f}")
            with cm2: st.metric("🏊‍♂️ Ingresos Piscina", f"S/. {total_p:.2f}")
            with cm3: st.metric("⚽ Ingresos Canchas", f"S/. {total_c:.2f}")
            with cm4: 
                st.markdown(f"<div style='background-color:#1E6F5C; padding:10px; border-radius:10px; text-align:center;'><h3 style='color:white; margin:0;'>TOTAL EN CAJA</h3><h2 style='color:white; margin:0;'>S/. {gran_total_caja:.2f}</h2></div>", unsafe_allow_html=True)
            
            st.markdown("---")
            col_rc1, col_rc2 = st.columns([1, 1.2])
            
            # --- COLUMNA 1: OPERACIÓN DE CIERRE ---
            with col_rc1:
                st.subheader("Realizar Cierre de Caja")
                st.write("Al cerrar caja, este monto se guardará en el historial financiero de forma definitiva.")
                
                if st.button("🔴 CERRAR CAJA HOY Y EMPEZAR NUEVO DÍA", type="primary", use_container_width=True):
                    if gran_total_caja >= 0:
                        fecha_cierre_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                        
                        # 1. Registramos el cierre en el historial central
                        ejecutar_query(f"INSERT INTO historial_cajas (fecha_cierre, total_vendido, usuario_cierre) VALUES ('{fecha_cierre_str}', {gran_total_caja}, '{st.session_state['usuario']}')", commit=True)
                        
                        # 2. Obtenemos el ID asignado automáticamente a este cierre específico
                        ultimo_id_res = ejecutar_query("SELECT id FROM historial_cajas ORDER BY id DESC LIMIT 1", fetch=True)
                        id_cierre_actual = ultimo_id_res[0][0] if ultimo_id_res else None
                        
                        if id_cierre_actual:
                            # 3. Enlazamos y cerramos formateando las consultas directamente para asegurar compatibilidad total
                            ejecutar_query(f"UPDATE ventas SET estado_caja='CERRADO', id_cierre={id_cierre_actual} WHERE estado_caja='ABIERTO'", commit=True)
                            ejecutar_query(f"UPDATE cancha SET estado_caja='CERRADO', id_cierre={id_cierre_actual} WHERE estado_caja='ABIERTO'", commit=True)
                            ejecutar_query(f"UPDATE piscina SET estado_caja='CERRADO', id_cierre={id_cierre_actual} WHERE estado_caja='ABIERTO'", commit=True)
                        else:
                            # Respaldo de seguridad
                            ejecutar_query("UPDATE ventas SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO'", commit=True)
                            ejecutar_query("UPDATE cancha SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO'", commit=True)
                            ejecutar_query("UPDATE piscina SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO'", commit=True)
                        
                        st.success("¡Caja cerrada correctamente! El sistema se ha reiniciado para el siguiente turno.")
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
                        st.dataframe(df_c_hist, use_container_width=True, hide_index=True)
                        
                        total_canchas_cierre = df_c_hist["Adelanto Registrado"].sum()
                        st.metric("Total Ingresos Canchas del Cierre", f"S/. {total_canchas_cierre:.2f}")
                    else:
                        st.info("No se registraron alquileres de canchas en este cierre de caja.")

    # =========================================================================
    # ROL: COCINERO (MEJORADO CON AGRUPACIÓN Y DISEÑO OPTIMIZADO V2)
    # =========================================================================
        # ---------------------------------------------------------------------
        # PESTAÑA 6: CONFIGURACION, MARCA, RESPALDOS Y SOPORTE
        # ---------------------------------------------------------------------
        elif modulo_actual == opciones_menu[5]:
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
                    backup_creado = crear_backup_base_datos()
                    st.success(f"Copia creada: {backup_creado.name}")

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
        if st.sidebar.button("Cerrar Sesión", type="secondary", use_container_width=True):
            logout()
        st.title("👨‍🍳 Monitor de Cocina - LAS MARÍAS")
        
        # Consultamos todos los platos pendientes
        pedidos_cocina = ejecutar_query("SELECT id, cliente, plato, cantidad, fecha_hora FROM cocina WHERE estado='PENDIENTE' ORDER BY fecha_hora ASC", fetch=True)
        
        if pedidos_cocina:
            # Creamos un diccionario para agrupar por cliente y fecha_hora
            pedidos_agrupados = {}
            for id_p, cliente_p, plato, cant, fecha_h in pedidos_cocina:
                llave = (cliente_p, fecha_h)
                if llave not in pedidos_agrupados:
                    pedidos_agrupados[llave] = {'ids': [], 'items': []}
                pedidos_agrupados[llave]['ids'].append(id_p)
                pedidos_agrupados[llave]['items'].append(f"{plato} x {cant}")
            
            # Mostramos los pedidos agrupados con el diseño ajustado
            for (cliente_p, fecha_h), data in pedidos_agrupados.items():
                with st.container():
                    st.markdown(f"""
                    <div style='background-color: #262730; padding: 20px; border-radius: 10px; border-left: 5px solid #FF4B4B; margin-bottom: 15px;'>
                        <p style='margin: 0 0 12px 0; color: #FF4B4B; font-size: 26px; font-weight: bold;'>
                            🍴 {", ".join(data['items'])}
                        </p>
                        <p style='margin: 0; color: #FFFFFF; font-size: 18px; font-weight: 500;'>
                            👤 Cliente: {cliente_p}
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Botón para despachar todo el grupo de platos juntos
                    if st.button(f"✓ Entregar Pedido Completo (IDs: {data['ids']})", key=f"btn_{data['ids']}"):
                        fecha_entrega = datetime.now().strftime('%Y-%m-%d %H:%M')
                        for id_individual in data['ids']:
                            ejecutar_query("UPDATE cocina SET estado='ENTREGADO', fecha_entrega=? WHERE id=?", (fecha_entrega, id_individual), commit=True)
                        st.rerun()
        else:
            st.success("¡No hay pedidos pendientes en la cocina!")

        st.markdown("---")
        with st.expander("Historial de platos entregados", expanded=False):
            historial_cocina = ejecutar_query(
                "SELECT id, cliente, plato, cantidad, COALESCE(fecha_entrega, fecha_hora), fecha_hora FROM cocina WHERE estado='ENTREGADO' ORDER BY COALESCE(fecha_entrega, fecha_hora) DESC LIMIT 120",
                fetch=True
            )
            if historial_cocina:
                df_hist_cocina = pd.DataFrame(
                    historial_cocina,
                    columns=["ID Pedido", "Cliente / Mesa", "Plato", "Cantidad", "Hora de entrega", "Hora de pedido"]
                )
                st.dataframe(df_hist_cocina, use_container_width=True, hide_index=True)
            else:
                st.info("Aún no hay platos entregados para mostrar.")
