import streamlit as st
import pandas as pd
import sqlite3
import secrets
from datetime import datetime

# Configuración de página
st.set_page_config(page_title="Complejo Recreativo Las Marías", layout="wide", page_icon="🏊‍♂️")

DB_NAME = "complejo.db"

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

restaurar_sesion_desde_url()

def aplicar_estilos_login():
    st.markdown("""
    <style>
        [data-testid="stAppViewContainer"] {
            background:
                linear-gradient(120deg, rgba(4, 47, 68, 0.78), rgba(8, 121, 150, 0.42)),
                url("https://images.unsplash.com/photo-1575429198097-0414ec08e8cd?auto=format&fit=crop&w=1800&q=80");
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
    """, unsafe_allow_html=True)

def aplicar_estilos_sistema():
    st.markdown("""
    <style>
        :root {
            --lm-primary: #006d77;
            --lm-primary-dark: #073b4c;
            --lm-accent: #0ea5a4;
            --lm-bg: #f4f8fb;
            --lm-panel: #ffffff;
            --lm-border: #d8e6ea;
            --lm-text: #17333b;
            --lm-muted: #5f7780;
        }

        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at top left, rgba(14, 165, 164, 0.14), transparent 32%),
                linear-gradient(180deg, #f6fbfd 0%, var(--lm-bg) 100%);
            color: var(--lm-text);
        }

        [data-testid="stHeader"] {
            background: rgba(246, 251, 253, 0.86);
            backdrop-filter: blur(10px);
            border-bottom: 1px solid rgba(216, 230, 234, 0.8);
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1500px;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #073b4c 0%, #006d77 100%);
            border-right: 1px solid rgba(255, 255, 255, 0.16);
        }

        [data-testid="stSidebar"] * {
            color: #ffffff !important;
        }

        [data-testid="stSidebar"] [data-testid="stImage"] {
            display: flex;
            justify-content: center;
            margin-top: 14px;
            margin-bottom: 8px;
        }

        [data-testid="stSidebar"] img {
            padding: 10px;
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.16);
            box-shadow: 0 10px 26px rgba(0, 0, 0, 0.22);
        }

        [data-testid="stSidebar"] h1 {
            font-size: 22px;
            font-weight: 800;
            text-align: center;
            margin-bottom: 8px;
        }

        [data-testid="stSidebar"] [data-testid="stAlert"] {
            background: rgba(255, 255, 255, 0.14);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
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

        div[data-testid="stTabs"] > div[role="tablist"] {
            gap: 8px;
            padding: 8px;
            border: 1px solid var(--lm-border);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.82);
            box-shadow: 0 10px 28px rgba(7, 59, 76, 0.07);
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
    st.sidebar.image("https://cdn-icons-png.flaticon.com/512/456/456212.png", width=80)
    st.sidebar.title(f"Hola, {st.session_state['usuario']}")
    st.sidebar.info(f"Rol: {st.session_state['rol']}")
    if st.sidebar.button("Cerrar Sesión", type="secondary"):
        logout()

    if st.session_state['rol'] == "Administrador":
        st.title("🏆 Panel de Administración - LAS MARIAS")
        
        opciones_menu = ["🛒 Ventas y Cocina", "📦 Control de Stock", "🏊‍♂️ Control de piscina", "⚽ Control de Cancha", "💰 Caja y Reportes"]
        pestana_url = obtener_parametro_url("tab")
        pestana_inicial = pestana_url if pestana_url in opciones_menu else opciones_menu[0]
        menu = st.tabs(opciones_menu, default=pestana_inicial, key="pestana_admin", on_change=guardar_pestana_admin)
        
        # ---------------------------------------------------------------------
        # PESTAÑA 1: VENTAS Y COCINA
        # ---------------------------------------------------------------------
        with menu[0]:
            st.header("Generar Nueva Venta / Crédito")
            col_v1, col_v2 = st.columns([1.2, 1])
            
            with col_v1:
                productos = ejecutar_query("SELECT nombre, precio, stock, proveedor FROM inventario WHERE stock > 0", fetch=True)
                dict_productos = {p[0]: {"precio": p[1], "stock": p[2], "proveedor": p[3]} for p in productos}
                
                if dict_productos:
                    prod_sel = st.selectbox("Seleccione el Producto/Plato", list(dict_productos.keys()))
                    cant = st.number_input("Cantidad", min_value=1, value=1)
                    
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
                else:
                    st.success("¡Cocina al día!")

            with col_v2:
                st.subheader("📋 Lista de compra del Cliente")
                cliente_input = st.text_input("Nombre del Cliente / Mesa:", value="General")
                tipo_pago = st.radio("Destino de la Venta:", ["PAGADO AL INSTANTE", "LLEVAR A CUENTA CRÉDITO (Anotar en lista histórica)"])
                
                if st.session_state['carrito']:
                    df_carrito = pd.DataFrame(st.session_state['carrito'])
                    st.table(df_carrito[["producto", "cantidad", "subtotal"]])
                    
                    total_carrito = df_carrito["subtotal"].sum()
                    st.markdown(f"### **Total a Pagar: S/. {total_carrito:.2f}**")
                    
                    col_c1, col_c2 = st.columns(2)
                    with col_c1:
                        if st.button("❌ Vaciar Lista", use_container_width=True):
                            st.session_state['carrito'] = []
                            st.rerun()
                            
                    with col_c2:
                        if st.button("PROCESAR Y COBRAR TODO", type="primary", use_container_width=True):
                            cliente_final = cliente_input.strip().upper() if cliente_input.strip() else "GENERAL"
                            fecha_actual = datetime.now().strftime('%Y-%m-%d %H:%M')
                            
                            for item in st.session_state['carrito']:
                                st_act = ejecutar_query("SELECT stock FROM inventario WHERE nombre=?", (item['producto'],), fetch=True)[0][0]
                                ejecutar_query("UPDATE inventario SET stock=? WHERE nombre=?", (st_act - item['cantidad'], item['producto']), commit=True)
                                
                                if str(item['proveedor']).strip().upper() == "INTERNO":
                                    ejecutar_query("INSERT INTO cocina (cliente, plato, cantidad, fecha_hora, estado) VALUES (?,?,?,?,?)",
                                                   (cliente_final, item['producto'], item['cantidad'], fecha_actual, "PENDIENTE"), commit=True)
                            
                            if tipo_pago == "LLEVAR A CUENTA CRÉDITO (Anotar en lista histórica)":
                                ejecutar_query("INSERT INTO ventas (cliente, total, estado, fecha, estado_caja) VALUES (?,?,?,?, 'ABIERTO')",
                                               (cliente_final, total_carrito, "CREDITO", fecha_actual), commit=True)
                                for item in st.session_state['carrito']:
                                    ejecutar_query("INSERT INTO detalle_creditos (cliente, producto, cantidad, precio_unitario, subtotal, fecha) VALUES (?,?,?,?,?,?)",
                                                   (cliente_final, item['producto'], item['cantidad'], item['precio_unitario'], item['subtotal'], fecha_actual), commit=True)
                                st.success("¡Guardado en la lista de cuentas de crédito!")
                                st.session_state['carrito'] = []
                                st.rerun()
                            else:
                                conn = sqlite3.connect(DB_NAME)
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO ventas (cliente, total, estado, fecha, estado_caja) VALUES (?,?,?,?, 'ABIERTO')",
                                               (cliente_final, total_carrito, "PAGADO", fecha_actual))
                                venta_id = cursor.lastrowid
                                
                                for item in st.session_state['carrito']:
                                    cursor.execute("INSERT INTO detalle_ventas (venta_id, producto, cantidad, precio_unitario, subtotal) VALUES (?,?,?,?,?)",
                                                   (venta_id, item['producto'], item['cantidad'], item['precio_unitario'], item['subtotal']))
                                conn.commit()
                                conn.close()
                                
                                items_copia = list(st.session_state['carrito'])
                                st.session_state['carrito'] = []
                                st.success("¡Venta finalizada con éxito!")
                                mostrar_ticket_multiple(cliente_final, items_copia, total_carrito, "VENTA EN MOSTRADOR")
                else:
                    st.info("La lista está vacía. Añade productos desde el panel izquierdo.")
                    
                    st.markdown("---")
                    st.subheader("📋 Resumen de Cuentas por Cobrar")
                    creditos = ejecutar_query("SELECT id, cliente, total, fecha FROM ventas WHERE estado='CREDITO'", fetch=True)
                    if creditos:
                        df_cred = pd.DataFrame(creditos, columns=["ID Lista", "Cliente", "Monto Total", "Fecha"])
                        st.dataframe(df_cred, use_container_width=True, hide_index=True)
                        id_cobrar = st.number_input("ID de lista crédito a liquidar hoy", min_value=1, step=1)
                        if st.button("Cerrar e imprimir saldo de crédito"):
                            cli_data = ejecutar_query("SELECT cliente, total FROM ventas WHERE id=?", (id_cobrar,), fetch=True)
                            if cli_data:
                                nombre_cli, monto_t = cli_data[0]
                                ejecutar_query("UPDATE ventas SET estado='PAGADO', estado_caja='ABIERTO' WHERE id=?", (id_cobrar,), commit=True)
                                ejecutar_query("DELETE FROM detalle_creditos WHERE cliente=?", (nombre_cli,), commit=True)
                                st.success("¡Cobrado!")
                                item_t = [{"producto": "LIQUIDACIÓN DE CRÉDITO", "cantidad": 1, "subtotal": monto_t}]
                                mostrar_ticket_multiple(nombre_cli, item_t, monto_t, "PAGO DE DEUDA HISTÓRICA")
                    else:
                        st.info("No hay deudas pendientes.")

        # ---------------------------------------------------------------------
        # PESTAÑA 2: CONTROL DE STOCK
        # ---------------------------------------------------------------------
        with menu[1]:
            st.header("Control e Ingreso de Mercadería")
            col_st1, col_st2 = st.columns([1.2, 1])
            
            with col_st1:
                with st.form("ingreso_stock", clear_on_submit=True):
                    st.subheader("➕ Registrar Nuevo / Aumentar Ingreso")
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
                st.subheader("🛠️ Panel de Edición y Eliminación")
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
            st.subheader("📊 Inventario Actual en Tiempo Real")
            inventario_total = ejecutar_query("SELECT id, nombre, proveedor, fecha_ingreso, costo, precio, stock FROM inventario", fetch=True)
            if inventario_total:
                df_inv = pd.DataFrame(inventario_total, columns=["ID", "Producto", "Proveedor", "Últ. Ingreso", "Costo", "Precio Venta", "Stock"])
                st.dataframe(df_inv, use_container_width=True, hide_index=True)

        # ---------------------------------------------------------------------
        # PESTAÑA 3: CONTROL DE PISCINA (CORREGIDO CON ESTADO DE CAJA ABIERTO)
        # ---------------------------------------------------------------------
        with menu[2]:
            st.header("Ingreso y Control de la Piscina")
            
            tarifas_db = ejecutar_query("SELECT categoria, precio FROM tarifas", fetch=True)
            dict_tarifas = {t[0]: t[1] for t in tarifas_db} if tarifas_db else {}
            
            p_nino = dict_tarifas.get("Niños", 5.0)
            p_adulto = dict_tarifas.get("Adultos", 10.0)
            p_mayor = dict_tarifas.get("Mayores", 7.0)

            col_p1, col_p2, col_p3 = st.columns([1.2, 1.2, 1.4])
            
            with col_p1:
                st.subheader("📸 Registro de Entradas")
                ninos = st.number_input("Cantidad de Niños / Niñas", min_value=0, step=1, value=0)
                adultos = st.number_input("Cantidad de Adultos", min_value=0, step=1, value=0)
                mayores = st.number_input("Cantidad de Adultos Mayores", min_value=0, step=1, value=0)
                
                calculo_sugerido = (ninos * p_nino) + (adultos * p_adulto) + (mayores * p_mayor)
                st.warning(f"Pago Sugerido: S/. {calculo_sugerido:.2f}")
                monto_final = st.number_input("Monto Final Recibido", min_value=0.0, value=float(calculo_sugerido), step=1.0)
                
                if st.button("Registrar Ingreso Piscina", use_container_width=True, type="primary"):
                    if ninos == 0 and adultos == 0 and mayores == 0:
                        st.error("Debes ingresar al menos 1 persona para registrar la entrada.")
                    else:
                        # Se introduce explícitamente el estado_caja='ABIERTO' para controlar los turnos
                        ejecutar_query("INSERT INTO piscina (ninos, adultos, mayores, monto_pagado, fecha, estado_caja) VALUES (?,?,?,?,?, 'ABIERTO')",
                                       (ninos, adultos, mayores, monto_final, datetime.now().strftime('%Y-%m-%d %H:%M')), commit=True)
                        st.success("¡Ingreso de piscina guardado exitosamente!")
                        
                        items_piscina_ticket = []
                        if ninos > 0:
                            items_piscina_ticket.append({"producto": "ENTRADA PISCINA (NIÑO)", "cantidad": ninos, "subtotal": ninos * p_nino})
                        if adultos > 0:
                            items_piscina_ticket.append({"producto": "ENTRADA PISCINA (ADULTO)", "cantidad": adultos, "subtotal": adultos * p_adulto})
                        if mayores > 0:
                            items_piscina_ticket.append({"producto": "ENTRADA PISCINA (AD. MAYOR)", "cantidad": mayores, "subtotal": mayores * p_mayor})
                        
                        mostrar_ticket_multiple("CLIENTE PISCINA", items_piscina_ticket, monto_final, "ACCESO PISCINA")
            
            with col_p2:
                st.subheader("⚙️ Panel de Tarifas Piscina")
                nuevo_p_nino = st.number_input("Precio Entrada Niños (S/.)", min_value=0.0, value=float(p_nino), step=0.5)
                nuevo_p_adulto = st.number_input("Precio Entrada Adultos (S/.)", min_value=0.0, value=float(p_adulto), step=0.5)
                nuevo_p_mayor = st.number_input("Precio Entrada Mayores (S/.)", min_value=0.0, value=float(p_mayor), step=0.5)
                
                if st.button("🔄 Actualizar Tarifas Piscina", use_container_width=True):
                    ejecutar_query("UPDATE tarifas SET precio=? WHERE categoria='Niños'", (nuevo_p_nino,), commit=True)
                    ejecutar_query("UPDATE tarifas SET precio=? WHERE categoria='Adultos'", (nuevo_p_adulto,), commit=True)
                    ejecutar_query("UPDATE tarifas SET precio=? WHERE categoria='Mayores'", (nuevo_p_mayor,), commit=True)
                    st.success("¡Tarifas actualizadas!")
                    st.rerun()

            with col_p3:
                st.subheader("📋 Historial de Entradas")
                registros_piscina = ejecutar_query("SELECT ninos, adultos, mayores, monto_pagado, fecha FROM piscina ORDER BY id DESC", fetch=True)
                if registros_piscina:
                    df_pis = pd.DataFrame(registros_piscina, columns=["Niños", "Adultos", "Adultos Mayores", "Monto", "Fecha/Hora"])
                    st.dataframe(df_pis, use_container_width=True, hide_index=True)

        # ---------------------------------------------------------------------
        # PESTAÑA 4: CONTROL DE CANCHAS
        # ---------------------------------------------------------------------
        with menu[3]:
            st.header("Reservas de Cancha")
            
            tarifas_c_db = ejecutar_query("SELECT tipo, precio FROM tarifas_cancha", fetch=True)
            dict_t_cancha = {tc[0]: tc[1] for tc in tarifas_c_db} if tarifas_c_db else {}
            
            precio_grande = dict_t_cancha.get("Cancha Grande", 70.0)
            precio_media = dict_t_cancha.get("Media Cancha", 40.0)

            col_c1, col_c2, col_c3 = st.columns([1.3, 1.1, 1.6])
            
            with col_c1:
                c_cliente = st.text_input("Nombre del Cliente")
                c_fecha = st.date_input("Fecha del Alquiler", value=datetime.today())
                
                st.markdown("**Horario de la Reserva:**")
                c_c1, c_c2 = st.columns(2)
                with c_c1:
                    hora_num = st.selectbox("Hora", [str(i) for i in range(1, 13)], index=9)
                with c_c2:
                    periodo = st.selectbox("Periodo", ["PM", "AM"], index=0)
                
                horario_final_str = f"{hora_num}:00 {periodo}"
                tipo_cancha_sel = st.selectbox("Tipo de Cancha", ["Cancha Grande", "Media Cancha"])
                costo_base_cancha = precio_grande if tipo_cancha_sel == "Cancha Grande" else precio_media
                
                c_total = st.number_input("Monto Total Contractual (S/.)", min_value=0.0, value=float(costo_base_cancha))
                c_adelanto = st.number_input("Monto de Adelanto (S/.)", min_value=0.0, value=0.0)
                
                if st.button("Guardar Reserva de Cancha", type="primary", use_container_width=True):
                    if c_cliente.strip():
                        fecha_str = c_fecha.strftime('%Y-%m-%d')
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
                        
            with col_c2:
                st.subheader("⚙️ Tarifas de Canchas")
                nuevo_p_grande = st.number_input("Cancha Grande / Hora (S/.)", min_value=0.0, value=float(precio_grande), step=5.0)
                nuevo_p_media = st.number_input("Media Cancha / Hora (S/.)", min_value=0.0, value=float(precio_media), step=5.0)
                
                if st.button("🔄 Actualizar Precios Cancha", use_container_width=True):
                    ejecutar_query("UPDATE tarifas_cancha SET precio=? WHERE tipo='Cancha Grande'", (nuevo_p_grande,), commit=True)
                    ejecutar_query("UPDATE tarifas_cancha SET precio=? WHERE tipo='Media Cancha'", (nuevo_p_media,), commit=True)
                    st.success("¡Precios de alquiler updatedos!")
                    st.rerun()
                    
                st.markdown("---")
                st.subheader("✅ Liquidar Saldo")
                id_cancha_liquidar = st.number_input("ID de Reserva a Cancelar", min_value=1, step=1)
                if st.button("Marcar como Completado/Pagado", use_container_width=True):
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

            with col_c3:
                reservas = ejecutar_query("SELECT id, cliente, horario, monto_total, adelanto, estado FROM cancha ORDER BY id DESC", fetch=True)
                if reservas:
                    df_res = pd.DataFrame(reservas, columns=["ID", "Cliente", "Horario", "Total", "Adelanto", "Estado"])
                    st.dataframe(df_res, use_container_width=True, hide_index=True)

        # ---------------------------------------------------------------------
        # PESTAÑA 5: 💰 CAJA Y REPORTES DIARIOS (SOPORTE DE REINICIO DE PISCINA)
        # ---------------------------------------------------------------------
        with menu[4]:
            st.header("💰 Control de Finanzas y Cierre de Caja Diaria")
            
            # Ahora filtramos la piscina basándonos en 'estado_caja' en vez de la fecha, unificando criterios
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
            with cm4: st.markdown(f"<div style='background-color:#1E6F5C; padding:10px; border-radius:10px; text-align:center;'><h3 style='color:white; margin:0;'>💰 TOTAL EN CAJA</h3><h2 style='color:white; margin:0;'>S/. {gran_total_caja:.2f}</h2></div>", unsafe_allow_html=True)
            
            st.markdown("---")
            col_rc1, col_rc2 = st.columns([1, 1.2])
            
            with col_rc1:
                st.subheader("🔐 Realizar Cierre de Caja")
                st.write("Al cerrar caja, este monto se guardará en el historial financiero de forma definitiva.")
                
                if st.button("🔴 CERRAR CAJA HOY Y EMPEZAR NUEVO DÍA", type="primary", use_container_width=True):
                    if gran_total_caja >= 0:
                        fecha_cierre_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                        
                        # Guardamos el total actual de la caja activa
                        ejecutar_query("INSERT INTO historial_cajas (fecha_cierre, total_vendido, usuario_cierre) VALUES (?,?,?)",
                                       (fecha_cierre_str, gran_total_caja, st.session_state['usuario']), commit=True)
                        
                        # CERRAMOS TODO AL MISMO TIEMPO (Ventas, Canchas y Piscina)
                        ejecutar_query("UPDATE ventas SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO'", commit=True)
                        ejecutar_query("UPDATE cancha SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO'", commit=True)
                        ejecutar_query("UPDATE piscina SET estado_caja='CERRADO' WHERE estado_caja='ABIERTO'", commit=True)
                        
                        st.success("¡Caja cerrada correctamente! El sistema se ha reiniciado para el siguiente turno.")
                        st.rerun()
            
            with col_rc2:
                st.subheader("📚 Historial de Cajas Cerradas (Días Anteriores)")
                historico = ejecutar_query("SELECT id, fecha_cierre, total_vendido, usuario_cierre FROM historial_cajas ORDER BY id DESC", fetch=True)
                if historico:
                    df_hist = pd.DataFrame(historico, columns=["ID Cierre", "Fecha / Hora Cierre", "Monto Total Recaudado", "Cerrado Por"])
                    st.dataframe(df_hist, use_container_width=True, hide_index=True)
                else:
                    st.info("Aún no tienes cierres de caja registrados en el historial.")

    # =========================================================================
    # ROL: COCINERO (MEJORADO CON AGRUPACIÓN Y DISEÑO OPTIMIZADO V2)
    # =========================================================================
    elif st.session_state['rol'] == "Cocinero":
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
                        for id_individual in data['ids']:
                            ejecutar_query("UPDATE cocina SET estado='ENTREGADO' WHERE id=?", (id_individual,), commit=True)
                        st.rerun()
        else:
            st.success("¡No hay pedidos pendientes en la cocina!")
