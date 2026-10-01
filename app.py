import os
import io
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
import pandas as pd
import plotly.express as px
from fpdf import FPDF
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from supabase import create_client, Client
import streamlit as st

# Importación ultra-robusta de librerías para lectura de PDF (Priorizando pdfplumber)
PDF_READER_AVAILABLE = False
try:
    import pdfplumber
    PDF_READER_TYPE = "pdfplumber"
    PDF_READER_AVAILABLE = True
except ImportError:
    try:
        import pypdf
        PDF_READER_TYPE = "pypdf"
        PDF_READER_AVAILABLE = True
    except ImportError:
        try:
            import PyPDF2 as pypdf
            PDF_READER_TYPE = "pypdf2"
            PDF_READER_AVAILABLE = True
        except ImportError:
            PDF_READER_AVAILABLE = False

# --- CONFIGURACIÓN ÚNICA AL INICIO ---
st.set_page_config(page_title="Itelcam CRM", layout="wide")

# --- GESTIÓN DE NAVEGACIÓN PERSISTENTE ---
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = 0

# =============================================================================
# 1. FUNCIONES DE BACKEND, BASE DE DATOS Y LÓGICA GLOBALES (SUPABASE 100%)
# =============================================================================

@st.cache_resource
def init_supabase() -> Client:
    """Inicializa y reutiliza el cliente de Supabase usando credenciales seguras."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

@st.cache_data(ttl=60)
def cargar_datos():
    """Consulta todos los registros de la tabla 'ingresos' en Supabase y los depura con seguridad."""
    response = supabase.table("ingresos").select("*").execute()
    data = response.data
    
    if not data:
        return pd.DataFrame(columns=[
            "Factura", "Empresa", "Planta", "Grupo_Servicio", "Servicio", 
            "Monto", "Moneda", "dias_programados", "dias_reales", "Fecha_Cotizacion", 
            "Fecha_OC", "Fecha_Emision", "Fecha_Vencimiento", "Fecha_GES", 
            "Fecha_Pago", "Semaforo", "Estado", "Requiere_GES", "Año", "Mes"
        ])
        
    df = pd.DataFrame(data)
    df.columns = df.columns.str.strip()
    
    for col_posible in ['AÑO', 'Año', 'ano', 'anio', 'ANO']:
        if col_posible in df.columns and 'Año' not in df.columns:
            df = df.rename(columns={col_posible: 'Año'})
            break
            
    for col_mes in ['Mes', 'MES', 'mes']:
        if col_mes in df.columns and 'Mes' not in df.columns:
            df = df.rename(columns={col_mes: 'Mes'})
            break
    
    if 'Moneda' not in df.columns:
        df['Moneda'] = 'CLP'

    if 'Monto' in df.columns:
        def limpiar_monto_entero(val):
            if pd.isna(val) or val is None:
                return 0
            if isinstance(val, (int, float)):
                return int(round(float(val)))
            s_val = str(val).strip().replace('$', '')
            if '.' in s_val and ',' in s_val:
                s_val = s_val.replace('.', '').replace(',', '.')
            elif ',' in s_val:
                s_val = s_val.replace(',', '.')
            try:
                return int(round(float(s_val)))
            except:
                return 0

        df['Monto'] = df['Monto'].apply(limpiar_monto_entero).astype('int64')
    else:
        df['Monto'] = 0
        
    for col in ['Fecha_Cotizacion', 'Fecha_OC', 'Fecha_Emision', 'Fecha_GES', 'Fecha_Pago', 'Fecha_Vencimiento']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
            
    df['Año'] = df['Fecha_Pago'].dt.year
    df['Mes'] = df['Fecha_Pago'].dt.month

    df['Empresa'] = df['Empresa'].astype(str).str.strip().str.upper()
    df['Planta'] = df['Planta'].fillna('SIN PLANTA').astype(str).str.strip().str.upper()
    
    if 'Grupo_Servicio' in df.columns:
        df['Grupo Servicio'] = df['Grupo_Servicio'].fillna('SIN SERVICIO').astype(str).str.strip().str.upper()
    elif 'Grupo Servicio' in df.columns:
        df['Grupo Servicio'] = df['Grupo Servicio'].fillna('SIN SERVICIO').astype(str).str.strip().str.upper()
    else:
        df['Grupo Servicio'] = 'SIN SERVICIO'
        
    df['Servicio'] = df['Servicio'].fillna('SIN DETALLE').astype(str).str.strip().str.upper()
    
    if 'Factura' in df.columns:
        df['Factura_Num'] = pd.to_numeric(df['Factura'], errors='coerce')
        df = df.sort_values(by=['Factura_Num', 'Factura'], ascending=[False, False]).drop(columns=['Factura_Num'])
         
    return df

def eliminar_factura(numero_factura):
    """Elimina una factura directamente desde Supabase."""
    try:
        supabase.table("ingresos").delete().eq("Factura", str(numero_factura)).execute()
        return True
    except Exception as e:
        st.error(f"Error al eliminar la factura: {e}")
        return False

@st.cache_data(ttl=30)
def cargar_contactos():
    """Consulta los contactos directamente desde Supabase sin depender de archivos CSV locales."""
    try:
        response = supabase.table("Contactos").select("*").execute()
        if response.data:
            df_c = pd.DataFrame(response.data)
            col_map = {
                "nombre": "Nombre",
                "email": "Correo",
                "estado": "Estado",
                "telefono": "Celular",
                "empresa": "Empresa",
                "planta": "Planta",
                "valor": "Valor",
                "rol": "Rol_Contacto",
                "bitacora": "Bitacora"
            }
            df_c = df_c.rename(columns={k: v for k, v in col_map.items() if k in df_c.columns})

            for col_req in ["Nombre", "Empresa", "Planta", "Correo", "Celular", "Estado", "Valor", "Rol_Contacto", "Bitacora"]:
                if col_req not in df_c.columns:
                    df_c[col_req] = ""

            try:
                df_facturas_exist = cargar_datos()
                if not df_facturas_exist.empty and 'Empresa' in df_facturas_exist.columns and not df_c.empty:
                    empresas_con_factura = set(df_facturas_exist['Empresa'].dropna().astype(str).str.strip().str.upper().unique())
                    mask_facturado = df_c['Empresa'].astype(str).str.strip().str.upper().isin(empresas_con_factura)
                    df_c.loc[mask_facturado, 'Estado'] = 'Ganado'
            except Exception:
                pass

            return df_c
    except Exception as e:
        st.error(f"Error al cargar contactos desde Supabase: {e}")

    return pd.DataFrame(columns=["Nombre", "Empresa", "Planta", "Correo", "Celular", "Estado", "Valor", "Rol_Contacto", "Bitacora"])

def guardar_contacto(nombre, email, estado, telefono="", empresa="", planta="", valor=0, rol="Influenciador", bitacora=""):
    """Inserta o actualiza un contacto directamente en Supabase."""
    try:
        df_fact = cargar_datos()
        if not df_fact.empty and 'Empresa' in df_fact.columns:
            empresas_facturadas = set(df_fact['Empresa'].dropna().astype(str).str.strip().str.upper().unique())
            if str(empresa).strip().upper() in empresas_facturadas:
                estado = "Ganado"
    except Exception:
        pass

    registro_supa = {
        "nombre": str(nombre).strip(),
        "email": str(email).strip().lower(),
        "estado": str(estado).strip(),
        "telefono": str(telefono).strip(),
        "empresa": str(empresa).strip().upper(),
        "planta": str(planta).strip().upper(),
        "valor": int(valor),
        "rol": str(rol).strip(),
        "bitacora": str(bitacora)
    }
    
    try:
        supabase.table("Contactos").upsert(registro_supa, on_conflict="email").execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al guardar contacto en Supabase: {e}")

def eliminar_contacto(email):
    """Elimina permanentemente un contacto desde Supabase."""
    try:
        supabase.table("Contactos").delete().eq("email", str(email).lower()).execute()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error al eliminar contacto de Supabase: {e}")
        return False

# --- GESTIÓN DE INTERACCIONES EN NUBE ---
@st.cache_data(ttl=30)
def cargar_interacciones():
    """Consulta el historial de interacciones directamente desde Supabase."""
    try:
        res = supabase.table("interacciones").select("*").execute()
        if res.data:
            df_i = pd.DataFrame(res.data)
            col_m = {
                "nombre_contacto": "Nombre_Contacto",
                "empresa": "Empresa",
                "tipo": "Tipo",
                "detalle": "Detalle",
                "fecha": "Fecha"
            }
            df_i = df_i.rename(columns={k: v for k, v in col_m.items() if k in df_i.columns})
            return df_i
    except Exception:
        pass
    return pd.DataFrame(columns=["Nombre_Contacto", "Empresa", "Tipo", "Detalle", "Fecha"])

def guardar_interaccion(nombre_contacto, empresa, tipo, detalle):
    """Guarda una interaccion en la base de datos de Supabase."""
    dict_i = {
        "nombre_contacto": str(nombre_contacto).strip(),
        "empresa": str(empresa).strip().upper(),
        "tipo": str(tipo).strip(),
        "detalle": str(detalle).strip(),
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    try:
        supabase.table("interacciones").insert(dict_i).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al registrar interacción en la nube: {e}")

# --- GESTIÓN GLOBAL UNIVERSAL DE TICKETS (SUPABASE) ---
@st.cache_data(ttl=30)
def cargar_tickets():
    """Carga tickets de soporte exclusivamente desde Supabase."""
    try:
        res = supabase.table("tickets").select("*").execute()
        if res.data:
            df_t = pd.DataFrame(res.data)
            col_m = {
                "id_ticket": "ID_Ticket",
                "empresa": "Empresa",
                "contacto": "Contacto",
                "asunto": "Asunto",
                "estado": "Estado",
                "prioridad": "Prioridad",
                "fecha": "Fecha",
                "creado_por": "Creado_Por"
            }
            df_t = df_t.rename(columns={k: v for k, v in col_m.items() if k in df_t.columns})
            for c_req in ["ID_Ticket", "Empresa", "Contacto", "Asunto", "Estado", "Prioridad", "Fecha", "Creado_Por"]:
                if c_req not in df_t.columns:
                    df_t[c_req] = ""
            return df_t
    except Exception as e:
        st.error(f"Error al obtener tickets desde la nube: {e}")

    return pd.DataFrame(columns=["ID_Ticket", "Empresa", "Contacto", "Asunto", "Estado", "Prioridad", "Fecha", "Creado_Por"])

def guardar_ticket(dict_ticket):
    """Guarda o actualiza un ticket en Supabase."""
    supa_dict = {
        "id_ticket": str(dict_ticket.get("ID_Ticket", "")),
        "empresa": str(dict_ticket.get("Empresa", "")),
        "contacto": str(dict_ticket.get("Contacto", "")),
        "asunto": str(dict_ticket.get("Asunto", "")),
        "estado": str(dict_ticket.get("Estado", "")),
        "prioridad": str(dict_ticket.get("Prioridad", "")),
        "fecha": str(dict_ticket.get("Fecha", "")),
        "creado_por": str(dict_ticket.get("Creado_Por", ""))
    }
    try:
        supabase.table("tickets").upsert(supa_dict, on_conflict="id_ticket").execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al guardar ticket en Supabase: {e}")

def eliminar_ticket(id_ticket):
    """Elimina un ticket en Supabase."""
    try:
        supabase.table("tickets").delete().eq("id_ticket", str(id_ticket)).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al eliminar ticket de Supabase: {e}")

# --- GESTIÓN DE COTIZACIONES (SUPABASE) ---
@st.cache_data(ttl=30)
def cargar_cotizaciones():
    """Carga cotizaciones directamente desde Supabase."""
    df_c = pd.DataFrame()
    try:
        res = supabase.table("cotizaciones").select("*").execute()
        if res.data:
            df_c = pd.DataFrame(res.data)
    except Exception as e:
        st.error(f"Error al consultar cotizaciones: {e}")
        
    if df_c.empty:
        cols = [
            "Folio", "Empresa", "RUT_Empresa", "Planta", "Contacto", "Email_Contacto", 
            "Fono_Contacto", "Ejecutivo", "Email_Ejecutivo", "Fono_Ejecutivo", 
            "Condicion_Pago", "Moneda", "Fecha_Emision", "Fecha_Validez", "Glosa", 
            "Grupo_Servicio", "Detalle_Servicio", "Cantidad", "Unidad", 
            "Monto_Neto", "Monto_IVA", "Monto_Total", "Estado"
        ]
        return pd.DataFrame(columns=cols)

    if 'Moneda' not in df_c.columns:
        df_c['Moneda'] = 'CLP'

    if 'Fecha_Emision' in df_c.columns:
        df_c['Fecha_Emision'] = df_c['Fecha_Emision'].astype(str).str.split(' ').str[0].str.split('T').str[0]
        
    if 'Fecha_Validez' in df_c.columns:
        df_c['Fecha_Validez'] = df_c['Fecha_Validez'].astype(str).str.split(' ').str[0].str.split('T').str[0]

    return df_c

def guardar_cotizacion(dict_cot):
    """Guarda o actualiza cotización en Supabase y sincroniza el contacto en la nube."""
    try:
        supabase.table("cotizaciones").upsert(dict_cot, on_conflict="Folio").execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al guardar cotización en Supabase: {e}")
        
    nom_c = dict_cot.get("Contacto", "").strip()
    em_c = dict_cot.get("Email_Contacto", "").strip()
    if nom_c or em_c:
        if not em_c and nom_c:
            em_c = f"{nom_c.lower().replace(' ', '.')}@{dict_cot.get('Empresa', 'cliente').lower().replace(' ', '')}.cl"
            
        estado_contacto = "Ganado" if dict_cot.get("Estado") in ["GANADO", "APROBADA"] else "Propuesta"
        guardar_contacto(
            nombre=nom_c if nom_c else em_c.split("@")[0].title(),
            email=em_c,
            estado=estado_contacto,
            telefono=dict_cot.get("Fono_Contacto", ""),
            empresa=dict_cot.get("Empresa", ""),
            planta=dict_cot.get("Planta", ""),
            valor=dict_cot.get("Monto_Total", 0),
            rol="Tomador de Decisiones"
        )

def marcar_cotizacion_como_ganada(folio_cot, empresa, planta, monto):
    """Actualiza el estado de una cotización y su contacto a GANADO en Supabase."""
    if not folio_cot or folio_cot == "--- Sin Enlace ---":
        return
    try:
        supabase.table("cotizaciones").update({"Estado": "GANADO"}).eq("Folio", str(folio_cot)).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al actualizar estado de cotización: {e}")
        
    df_cot = cargar_cotizaciones()
    if not df_cot.empty and 'Folio' in df_cot.columns:
        idx_c = df_cot[df_cot['Folio'].astype(str) == str(folio_cot)].index
        if not idx_c.empty:
            row_c = df_cot.loc[idx_c[0]]
            nom_c = str(row_c.get("Contacto", "")).strip()
            em_c = str(row_c.get("Email_Contacto", "")).strip()
            if nom_c or em_c:
                if not em_c and nom_c:
                    em_c = f"{nom_c.lower().replace(' ', '.')}@{empresa.lower().replace(' ', '')}.cl"
                guardar_contacto(
                    nombre=nom_c if nom_c else empresa,
                    email=em_c if em_c else f"contacto@{empresa.lower().replace(' ', '')}.cl",
                    estado="Ganado",
                    telefono=str(row_c.get("Fono_Contacto", "")),
                    empresa=empresa,
                    planta=planta,
                    valor=monto,
                    rol="Tomador de Decisiones"
                )

def eliminar_cotizacion(folio_cot):
    """Elimina una cotización directamente desde Supabase."""
    try:
        supabase.table("cotizaciones").delete().eq("Folio", str(folio_cot)).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al eliminar cotización de Supabase: {e}")

def obtener_consejo_ia(notas_bitacora):
    return (
        "💡 **Consejo de IA (Entorno Local / VS Code):**\n"
        f"1. Analiza las notas recientes sobre '{notas_bitacora}' para identificar necesidades pendientes.\n"
        "2. Propón una reunión de seguimiento enfocada en resolver dudas técnicas o comerciales.\n"
        "3. Envía un correo con un resumen de valor antes de la próxima llamada."
    )

def calcular_semaforo_avanzado(row):
    hoy = pd.Timestamp(datetime.now().date())
   
    if pd.notna(row.get('Fecha_Pago')):
        if pd.notna(row.get('Fecha_Vencimiento')) and row['Fecha_Pago'] <= row['Fecha_Vencimiento']:
            return 'Verde (Pagado a tiempo)'
        else:
            return 'Amarillo/Rojo (Pagado fuera de plazo)'
    else:
        if row.get('Requiere_GES') == 'Sí' and pd.isna(row.get('Fecha_GES')):
            return 'Naranjo (Pendiente emisión GES)'
          
        if pd.isna(row.get('Fecha_Vencimiento')):
            return 'Sin Fecha Vencimiento'
          
        dias_vencido = (hoy - row['Fecha_Vencimiento']).days
        if dias_vencido <= 0:
            return 'Azul/Verde (Azul/Verde)'
        elif dias_vencido <= 15:
            return 'Amarillo (Pendiente con alerta)'
        else:
            return 'Rojo (Vencido crítico)'

def color_semaforo(val):
    if 'Verde' in str(val) or 'Al día' in str(val):
        return 'background-color: #dcfce7; color: #166534;'
    elif 'Amarillo' in str(val) or 'tolerancia' in str(val):
        return 'background-color: #fef9c3; color: #854d0e;'
    elif 'Rojo' in str(val) or 'Vencido' in str(val):
        return 'background-color: #fee2e2; color: #991b1b;'
    elif 'Naranjo' in str(val):
        return 'background-color: #ffedd5; color: #9a3412;'
    return ''

# --- CONFIGURACIÓN DE USUARIOS Y ROLES ---
USERS = {
    "javiera.ponce@itelcam.cl": {"role": "admin", "pass": "Itelcam2026"},
    "sandro.cannizzo@itelcam.cl": {"role": "viewer", "pass": "Itelcam2026"},
    "edgar.cabrera@itelcam.cl": {"role": "viewer", "pass": "Itelcam2026"}
}

def check_password():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["role"] = None
        st.session_state["user_email"] = None

    if not st.session_state["logged_in"]:
        st.title("🚀 Itelcam CRM - Gestión Estratégica")
        email = st.text_input("Correo Institucional", key="login_email")
        password = st.text_input("Contraseña", type="password", key="login_password")
        if st.button("Ingresar"):
            if email in USERS and USERS[email]["pass"] == password:
                st.session_state["logged_in"] = True
                st.session_state["role"] = USERS[email]["role"]
                st.session_state["user_email"] = email
                st.rerun()
            else:
                st.error("Credenciales incorrectas")
        return False
    return True

# =============================================================================
# GENERACIÓN DE REPORTE PDF
# =============================================================================
def generar_pdf(df_original):
    def safe_txt(txt):
        if txt is None:
            return ""
        return str(txt).encode('latin-1', 'replace').decode('latin-1')

    df = df_original.dropna(subset=['Fecha_Pago']).copy()
    pdf = FPDF()
    pdf.add_page()
   
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt=safe_txt("Reporte Ejecutivo CRM Itelcam (Ingresos Reales por Pago)"), ln=True, align='C')
    pdf.ln(5)
   
    ingresos_totales = int(df['Monto'].sum())
    total_clientes = df['Empresa'].nunique() if 'Empresa' in df.columns else len(df)
    ingresos_2025 = int(df[df['Año'] == 2025]['Monto'].sum()) if 'Año' in df.columns else 0
    ingresos_2026 = int(df[df['Año'] == 2026]['Monto'].sum()) if 'Año' in df.columns else 0

    pdf.set_font("Arial", 'B', 11)
    pdf.cell(200, 6, txt=safe_txt(f"Ingresos Totales (Pagados): ${ingresos_totales:,.0f}".replace(",", ".")), ln=True)
    pdf.cell(200, 6, txt=safe_txt(f"Total Clientes: {total_clientes}"), ln=True)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(200, 6, txt=safe_txt(f"KPIs Anuales (Según Pago) -> 2025: ${ingresos_2025:,.0f} | 2026: ${ingresos_2026:,.0f}".replace(",", ".")), ln=True)
    pdf.ln(5)

    if 'Mes' in df.columns and 'Año' in df.columns:
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(200, 8, txt=safe_txt("Comparativa Ingresos Reales 2025 vs 2026"), ln=True)
       
        plt.figure(figsize=(7, 3.8))
        df_valid = df.dropna(subset=['Mes', 'Año'])
        pivot_df = df_valid.pivot_table(index='Mes', columns='Año', values='Monto', aggfunc='sum').fillna(0)
        pivot_df.plot(kind='bar', figsize=(7, 3.5), width=0.8)
       
        plt.title("Comparativa Ingresos Reales (Fecha de Pago) 2025 vs 2026", fontsize=10)
        plt.xlabel("Mes", fontsize=9)
        plt.ylabel("Monto Pagado", fontsize=9)
        plt.xticks(rotation=0)
        plt.legend(title="Año")
        plt.tight_layout()
       
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            plt.savefig(tmp.name, dpi=150)
            tmp_path = tmp.name
        plt.close()
       
        pdf.image(tmp_path, x=15, w=180)
        os.remove(tmp_path)
        pdf.ln(5)

    def agregar_grafico_empresa_por_anio(pdf, df_anio, anio):
        if df_anio.empty:
            return
        empresa_data = df_anio.groupby('Empresa', as_index=False)['Monto'].sum().sort_values(by='Monto', ascending=True)
       
        plt.figure(figsize=(6, 3.2))
        plt.barh(empresa_data['Empresa'], empresa_data['Monto'], color='skyblue')
        plt.title(f"Ingresos Reales por Empresa ({anio})", fontsize=10)
        plt.xlabel("Monto Pagado ($)", fontsize=9)
        plt.ylabel("Empresa", fontsize=9)
        plt.tight_layout()
       
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            plt.savefig(tmp.name, dpi=150)
            tmp_path = tmp.name
        plt.close()
       
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(200, 7, txt=safe_txt(f"Ingresos Reales por Empresa - Año {anio}"), ln=True)
        pdf.image(tmp_path, x=25, w=150)
        os.remove(tmp_path)
        pdf.ln(2)
       
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(200, 5, safe_txt(f"Detalle Empresas ({anio})"), ln=True)
        pdf.set_font("Arial", size=8)
        for _, row in empresa_data.iterrows():
            monto_str = f"${int(row['Monto']):,.0f}".replace(",", ".")
            pdf.cell(90, 5, safe_txt(f"{row['Empresa']}: {monto_str}"), border=1)
            pdf.ln()
        pdf.ln(4)

    def agregar_grafico_servicio_por_anio(pdf, df_anio, anio):
        if df_anio.empty:
            return
        servicio_data = df_anio.groupby('Grupo Servicio', as_index=False)['Monto'].sum()
       
        total_monto = servicio_data['Monto'].sum()
        if total_monto > 0:
            etiquetas_leyenda = [
                f"{row['Grupo Servicio']} ({row['Monto']/total_monto*100:.1f}%)"
                for _, row in servicio_data.iterrows()
            ]
        else:
            etiquetas_leyenda = [f"{row['Grupo Servicio']} (0.0%)" for _, row in servicio_data.iterrows()]
       
        plt.figure(figsize=(6, 3.2))
        wedges, texts = plt.pie(
            servicio_data['Monto'],
            labels=None,
            startangle=140
        )
        plt.legend(wedges, etiquetas_leyenda, title="Servicios", loc="center left", bbox_to_anchor=(1, 0.5), fontsize=8)
        plt.title(f"Mix de Servicios Reales ({anio})", fontsize=10)
        plt.tight_layout()
       
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            plt.savefig(tmp.name, dpi=150, bbox_inches='tight')
            tmp_path = tmp.name
        plt.close()
       
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(200, 7, txt=safe_txt(f"Mix de Servicios Reales - Año {anio}"), ln=True)
        pdf.image(tmp_path, x=20, w=160)
        os.remove(tmp_path)
        pdf.ln(2)
       
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(200, 5, safe_txt(f"Detalle Mix de Servicios ({anio})"), ln=True)
        pdf.set_font("Arial", size=8)
        for _, row in servicio_data.iterrows():
            monto_str = f"${int(row['Monto']):,.0f}".replace(",", ".")
            pdf.cell(90, 5, safe_txt(f"{row['Grupo Servicio']}: {monto_str}"), border=1)
            pdf.ln()
        pdf.ln(4)

    anios_disponibles = [2025, 2026]
    for anio in anios_disponibles:
        if 'Año' in df.columns:
            df_anio = df[df['Año'] == anio]
        else:
            df_anio = df
           
        if not df_anio.empty:
            if 'Empresa' in df_anio.columns:
                agregar_grafico_empresa_por_anio(pdf, df_anio, anio)
               
            if 'Grupo Servicio' in df_anio.columns:
                agregar_grafico_servicio_por_anio(pdf, df_anio, anio)

    return bytes(pdf.output())

# =============================================================================
# 2. BLOQUE PRINCIPAL E INTERFAZ DE USUARIO CON STREAMLIT
# =============================================================================
if check_password():

    df_tickets = cargar_tickets()
    df_interacciones = cargar_interacciones()

    if "log_actividad" not in st.session_state:
        st.session_state["log_actividad"] = []

    def registrar_log(accion):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state["log_actividad"].insert(0, f"[{timestamp}] - {st.session_state.get('user_email', 'Sistema')}: {accion}")

    with st.sidebar:
        st.write(f"**Usuario:** {st.session_state['user_email']}")
        st.write(f"**Rol:** {st.session_state['role'].upper()}")
        st.write("---")
       
        if st.button("📥 Descargar Reporte PDF"):
            df_pdf = cargar_datos()
            st.download_button("📥 Confirmar Descarga PDF", data=generar_pdf(df_pdf), file_name="CRM_Itelcam.pdf", mime="application/pdf")

        if st.button("🔄 Sincronizar Datos"):
            st.cache_data.clear()
            registrar_log("Sincronización de datos realizada")
            st.success("¡Datos sincronizados exitosamente desde Supabase!")
            st.rerun()
       
        if st.button("🚪 Cerrar Sesión"):
            st.session_state["logged_in"] = False
            st.rerun()

    st.title("🚀 Itelcam CRM - Gestión Estratégica")

    df_contactos = cargar_contactos()
    if 'Rol_Contacto' not in df_contactos.columns:
        df_contactos['Rol_Contacto'] = 'Influenciador'

    df = cargar_datos()
    df_cotizaciones = cargar_cotizaciones()

    tab1, tab2, tab3, tab_cot, tab4, tab5 = st.tabs([
        "📊 Dashboard", 
        "🏢 Gestión por Planta", 
        "📈 Análisis Estratégico", 
        "📑 Cotizaciones",
        "➕ Gestión de Facturas y Ciclo de Pago", 
        "🔥 Embudo Ventas"
    ])
   
    with tab1:
        st.info("💡 **Nota Financiera:** Todos los ingresos, gráficos y métricas mostrados a continuación reflejan exclusivamente los montos correspondientes a su **fecha de pago efectiva**.")
          
        st.subheader("🔔 Alertas de Renovación y Vencimientos Anuales")
        if 'Fecha_Vencimiento' in df.columns:
            hoy_alerta = pd.Timestamp(datetime.now().date())
            df_sin_pagar = df[df['Fecha_Pago'].isna() & df['Fecha_Vencimiento'].notna()].copy()
            if not df_sin_pagar.empty:
                df_sin_pagar['Dias_Restantes'] = (df_sin_pagar['Fecha_Vencimiento'] - hoy_alerta).dt.days
                
                df_vencidas = df_sin_pagar[df_sin_pagar['Dias_Restantes'] < 0].copy()
                if not df_vencidas.empty:
                    df_vencidas['Dias_Atraso'] = df_vencidas['Dias_Restantes'].abs()
                    df_vencidas = df_vencidas.sort_values(by='Dias_Atraso', ascending=False)
                    
                    st.error(f"🚨 **¡ATENCIÓN URGENTE! HAY {len(df_vencidas)} FACTURAS YA VENCIDAS PENDIENTES DE PAGO**")
                    st.dataframe(
                        df_vencidas[['Empresa', 'Planta', 'Factura', 'Monto', 'Fecha_Vencimiento', 'Dias_Atraso']],
                        column_config={"Dias_Atraso": "Días de Atraso"},
                        hide_index=True,
                        use_container_width=True
                    )
                
                df_proximos = df_sin_pagar[(df_sin_pagar['Dias_Restantes'] >= 0) & (df_sin_pagar['Dias_Restantes'] <= 30)].sort_values(by='Dias_Restantes', ascending=True)
                if not df_proximos.empty:
                    st.warning(f"⚠ Hay **{len(df_proximos)} contratos/facturas** que vencen en los próximos 30 días. ¡Contacta al cliente para asegurar la renovación!")
                    st.dataframe(
                        df_proximos[['Empresa', 'Planta', 'Factura', 'Monto', 'Fecha_Vencimiento', 'Dias_Restantes']],
                        column_config={"Dias_Restantes": "Días Restantes"},
                        hide_index=True,
                        use_container_width=True
                    )
                
                if df_vencidas.empty and df_proximos.empty:
                    st.info("No hay vencimientos ni facturas con atraso en este momento.")
            else:
                st.info("No hay vencimientos ni facturas con atraso en este momento.")

        st.divider()

        st.subheader("🛠️ Estado Global de Soporte Técnico y Tickets")
        if not df_tickets.empty:
            tickets_abiertos = df_tickets[df_tickets['Estado'] != 'Cerrado']
            tickets_urgentes = df_tickets[(df_tickets['Estado'] != 'Cerrado') & (df_tickets['Prioridad'] == '🚨 Urgente / Crítica')]
            
            k_t1, k_t2, k_t3 = st.columns(3)
            k_t1.metric("Tickets Activos / Abiertos", len(tickets_abiertos))
            k_t2.metric("🚨 Tickets URGENTES", len(tickets_urgentes))
            k_t3.metric("Total Histórico de Tickets", len(df_tickets))
            
            if not tickets_urgentes.empty:
                st.error(f"🚨 **Hay {len(tickets_urgentes)} ticket(s) URGENTE(S) pendiente(s) de atención:**")
                st.dataframe(tickets_urgentes[['ID_Ticket', 'Empresa', 'Contacto', 'Asunto', 'Fecha', 'Creado_Por']], hide_index=True, use_container_width=True)
            elif not tickets_abiertos.empty:
                with st.expander("Ver detalle de todos los tickets abiertos (Universal)"):
                    st.dataframe(tickets_abiertos[['ID_Ticket', 'Empresa', 'Contacto', 'Asunto', 'Prioridad', 'Fecha', 'Creado_Por']], hide_index=True, use_container_width=True)
        else:
            st.info("No hay tickets de soporte registrados en el sistema.")

        st.divider()

        if 'Fecha_Vencimiento' in df.columns and not df.empty:
            df['Semáforo'] = df.apply(calcular_semaforo_avanzado, axis=1)
        else:
            df['Semáforo'] = 'Sin Fecha Vencimiento'

        st.subheader("🔎 Buscador Global Rápido")
        busqueda_global = st.text_input("Escribe una palabra clave (empresa, factura, servicio, planta):", key="global_search_input")

        if busqueda_global:
            q = busqueda_global.upper()
            mask = (
                df['Empresa'].str.contains(q, na=False) |
                df['Planta'].str.contains(q, na=False) |
                df['Grupo Servicio'].str.contains(q, na=False) |
                df['Factura'].astype(str).str.contains(q, na=False)
            )
            df_resultados_globales = df[mask]
            st.write(f"Se encontraron **{len(df_resultados_globales)} registros** coincidente(s):")
            st.dataframe(df_resultados_globales, use_container_width=True, hide_index=True)
            st.divider()

        with st.expander("📋 Ver Actividad Reciente de la Sesión"):
            if "log_actividad" in st.session_state and st.session_state["log_actividad"]:
                for evento in st.session_state["log_actividad"][:5]:
                    st.caption(evento)
            else:
                st.info("No hay eventos registrados en la sesión actual.")

        st.subheader("🤖 Asistente de Inteligencia Comercial")
       
        user_query = st.text_input("Pregúntale algo sobre tus ingresos o tendencias:", key="input_ia")
        if st.button("Consultar IA"):
            if user_query:
                with st.spinner("Procesando consulta local..."):
                    query_lower = user_query.lower()
                    if "ingresos" in query_lower or "total" in query_lower or "cuánto" in query_lower:
                        total_2026_val = df[df['Año'] == 2026]['Monto'].sum()
                        total_2025_val = df[df['Año'] == 2025]['Monto'].sum()
                        respuesta_ia = f"📊 **Análisis Local (Por Fecha de Pago):** Los ingresos reales pagados durante el año 2026 ascienden a ${total_2026_val:,.0f}".replace(",", ".") + f", comparados con ${total_2025_val:,.0f}".replace(",", ".") + " en 2025."
                    elif "cliente" in query_lower or "empresa" in query_lower:
                        top_empresa = df[df['Año'] == 2026].groupby('Empresa')['Monto'].sum().idxmax() if not df[df['Año'] == 2026].empty else "N/A"
                        respuesta_ia = f"🏢 **Análisis Local:** La empresa con mayor aportación de ingresos reales (pagados) durante el 2026 es **{top_empresa}**."
                    else:
                        respuesta_ia = f"🤖 **Respuesta Local:** He procesado tu consulta ('{user_query}'). Te sugiero revisar el panel de KPIs ejecutivos y el desglose de ingresos reales por planta."
                 
                    st.write("### Respuesta de la IA:")
                    st.write(respuesta_ia)
            else:
                st.warning("Por favor, escribe una pregunta.")

        st.subheader("📊 Resumen Ejecutivo de Ingresos Reales (KPIs)")
        df_pagados = df.dropna(subset=['Fecha_Pago'])
        total_2026 = int(df_pagados[df_pagados['Año'] == 2026]['Monto'].sum())
        total_2025 = int(df_pagados[df_pagados['Año'] == 2025]['Monto'].sum())
        variacion = ((total_2026 - total_2025) / total_2025 * 100) if total_2025 != 0 else 0
        ticket_promedio = int(round(df_pagados[df_pagados['Año'] == 2026]['Monto'].mean())) if not df_pagados[df_pagados['Año'] == 2026].empty else 0
        top_cliente = df_pagados[df_pagados['Año'] == 2026].groupby('Empresa')['Monto'].sum().idxmax() if not df_pagados[df_pagados['Año'] == 2026].empty else "N/A"
          
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Ingresos Pagados 2026", f"${total_2026:,.0f}".replace(",", "."))
        k2.metric("Crecimiento vs 2025", f"{variacion:,.1f}%", delta=f"{variacion:,.1f}%")
        k3.metric("Ticket Promedio Pagado", f"${ticket_promedio:,.0f}".replace(",", "."))
        k4.metric("Top Cliente Pagado 2026", top_cliente)    
        st.divider()
          
        st.subheader("Ingresos Reales Totales: Comparativa 2025 vs 2026 (Por Fecha de Pago)")
        df_line_valid = df_pagados[df_pagados['Año'].isin([2025, 2026])].dropna(subset=['Mes', 'Año'])
        if not df_line_valid.empty:
            tendencia = df_line_valid.groupby(['Año', 'Mes'])['Monto'].sum().reset_index()
            fig_line = px.line(tendencia, x='Mes', y='Monto', color='Año', markers=True, labels={'Monto': 'Monto Pagado ($)'})
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.info("No hay pagos registrados para graficar la comparativa anual.")
          
        st.subheader("Mix de Servicios Reales Comparativo")
        c1, c2 = st.columns(2)
        for anio, col in zip([2025, 2026], [c1, c2]):
            with col:
                st.write(f"### Mix Pagado {anio}")
                df_anio_pie = df_pagados[df_pagados['Año'] == anio]
                if not df_anio_pie.empty:
                    df_pie_grouped = df_anio_pie.groupby('Grupo Servicio', as_index=False)['Monto'].sum()
                    if not df_pie_grouped.empty and df_pie_grouped['Monto'].sum() > 0:
                        fig = px.pie(df_pie_grouped, values='Monto', names='Grupo Servicio', hole=0.4)
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info(f"Sin montos registrados para el año {anio}")
                else:
                    st.info(f"Sin registros para el año {anio}")

        st.subheader("📉 Alertas Tempranas Riesgo de Abandono (Ingresos Reales)")
        if 'Año' in df_pagados.columns and 'Mes' in df_pagados.columns and 'Empresa' in df_pagados.columns:
            df_historico_mensual = df_pagados[df_pagados['Año'].isin([2025, 2026])].dropna(subset=['Mes']).groupby(['Empresa', 'Año', 'Mes'])['Monto'].sum().reset_index()
            df_2025 = df_historico_mensual[df_historico_mensual['Año'] == 2025]
            df_2026 = df_historico_mensual[df_historico_mensual['Año'] == 2026]
           
            if not df_2025.empty and not df_2026.empty:
                df_churn_comparativa = pd.merge(
                    df_2026, df_2025,
                    on=['Empresa', 'Mes'],
                    suffixes=('_2026', '_2025')
                )
                df_churn_comparativa['Variacion_%'] = ((df_churn_comparativa['Monto_2026'] - df_churn_comparativa['Monto_2025']) / df_churn_comparativa['Monto_2025']) * 100
                clientes_en_riesgo = df_churn_comparativa[df_churn_comparativa['Variacion_%'] <= -30.0]
               
                if not clientes_en_riesgo.empty:
                    st.error(f"⚠️ Se detectó **riesgo de abandono** en **{len(clientes_en_riesgo)} registros mensuales de pagos**...")
                    df_churn_display = clientes_en_riesgo[['Empresa', 'Mes', 'Monto_2025', 'Monto_2026', 'Variacion_%']].copy()
                    df_churn_display['Variacion_%'] = df_churn_display['Variacion_%'].map(lambda x: f"{x:.1f}%")
                    df_churn_display['Monto_2025'] = df_churn_display['Monto_2025'].map(lambda x: f"${int(x):,.0f}".replace(",", "."))
                    df_churn_display['Monto_2026'] = df_churn_display['Monto_2026'].map(lambda x: f"${int(x):,.0f}".replace(",", "."))
                    df_churn_display.columns = ['Empresa', 'Mes', 'Pagado 2025', 'Pagado 2026', 'Variación (%)']
                    st.dataframe(df_churn_display, hide_index=True, use_container_width=True)
                else:
                    st.success("✨ ¡Todo en orden! No se registran caídas críticas de pagos mensuales.")
            else:
                st.info("ℹ Se requieren datos pagados de 2025 y 2026 para el análisis de churn.")
        else:
            st.info("ℹ Columnas necesarias no disponibles.")
           
        st.divider()

    with tab2:
        container_filtros = st.container()
        with container_filtros:
            st.subheader("Análisis Jerárquico de Ingresos Reales por Empresa y Planta")     
            c_emp1, c_emp2 = st.columns(2)
            df_pagados_tab2 = df.dropna(subset=['Fecha_Pago'])
            for anio, col in zip([2025, 2026], [c_emp1, c_emp2]):
                with col:
                    st.write(f"### Ingresos Reales por Empresa {anio}")
                    df_anio = df_pagados_tab2[df_pagados_tab2['Año'] == anio]
                    if not df_anio.empty:
                        df_emp_grouped = df_anio.groupby('Empresa', as_index=False)['Monto'].sum()
                        if not df_emp_grouped.empty and df_emp_grouped['Monto'].sum() > 0:
                            fig_emp = px.pie(df_emp_grouped, values='Monto', names='Empresa')
                            st.plotly_chart(fig_emp, use_container_width=True)
                        else:
                            st.info(f"Sin montos en {anio}")
                    else:
                        st.info(f"No hay pagos registrados para {anio}")
            st.divider()
            empresa_sel = st.selectbox("Selecciona Empresa:", sorted(df['Empresa'].unique()), key="filtro_estatico_empresa")
            plantas_disponibles = sorted(df[df['Empresa'] == empresa_sel]['Planta'].unique())
            planta_sel = st.selectbox("Selecciona Planta:", plantas_disponibles, key="filtro_estatico_planta")
            st.subheader(f"Mix de Ingresos Pagados por Planta - {empresa_sel}")
            c_pl1, c_pl2 = st.columns(2)
            for anio, col in zip([2025, 2026], [c_pl1, c_pl2]):
                with col:
                    st.write(f"#### Año {anio}")
                    df_filtro = df_pagados_tab2[(df_pagados_tab2['Empresa'] == empresa_sel) & (df_pagados_tab2['Año'] == anio)]
                    if not df_filtro.empty:
                        df_planta_grouped = df_filtro.groupby('Planta', as_index=False)['Monto'].sum()
                        if not df_planta_grouped.empty and df_planta_grouped['Monto'].sum() > 0:
                            fig_p = px.pie(df_planta_grouped, values='Monto', names='Planta')
                            st.plotly_chart(fig_p, use_container_width=True)
                        else:
                            st.write(f"Sin montos en {anio}")
                    else:
                        st.write(f"Sin pagos en {anio}")
            st.divider()
            
            # --- HISTORIAL DE COTIZACIONES Y PROPUESTAS POR PLANTA / CLIENTE ---
            st.subheader(f"📑 Propuestas y Cotizaciones Emitidas - {empresa_sel} ({planta_sel})")
            if not df_cotizaciones.empty:
                df_c_planta = df_cotizaciones[(df_cotizaciones['Empresa'].str.upper() == empresa_sel.upper()) & (df_cotizaciones['Planta'].str.upper() == planta_sel.upper())]
                if not df_c_planta.empty:
                    st.dataframe(
                        df_c_planta[["Folio", "Contacto", "Fecha_Emision", "Moneda", "Grupo_Servicio", "Detalle_Servicio", "Monto_Total", "Estado"]],
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info(f"No hay cotizaciones registradas específicamente para la planta {planta_sel}.")
            else:
                st.info("No hay cotizaciones registradas en el sistema.")

            st.divider()
            st.subheader(f"📈 Estacionalidad Mensual de Pagos por Planta: {planta_sel} ({empresa_sel})")
           
            df_planta_estacional = df_pagados_tab2[(df_pagados_tab2['Empresa'] == empresa_sel) & (df_pagados_tab2['Planta'] == planta_sel) & df_pagados_tab2['Año'].isin([2025, 2026])].dropna(subset=['Mes'])
           
            if not df_planta_estacional.empty:
                df_estacional_planta = df_planta_estacional.groupby(['Año', 'Mes'])['Monto'].sum().reset_index()
               
                fig_estacional_planta = px.line(
                    df_estacional_planta,
                    x='Mes',
                    y='Monto',
                    color='Año',
                    markers=True,
                    title=f"Comparativa Estacional de Pagos (2025 vs 2026) - {planta_sel}",
                    labels={'Monto': 'Monto Pagado ($)', 'Mes': 'Mes'},
                    category_orders={"Mes": list(range(1, 13))}
                )
                st.plotly_chart(fig_estacional_planta, use_container_width=True)
                st.info(f"💡 **Lectura de estacionalidad:** Este gráfico refleja el flujo de caja real ingresado mes a mes para la planta **{planta_sel}**.")
            else:
                st.warning(f"No hay registros de pagos suficientes para mostrar la estacionalidad de la planta {planta_sel}.")
           
            st.divider()
            st.subheader(f"Análisis General de Estacionalidad de Pagos: {empresa_sel}")
            df_estacional = df_pagados_tab2[(df_pagados_tab2['Empresa'] == empresa_sel) & df_pagados_tab2['Año'].isin([2025, 2026])].dropna(subset=['Mes']).groupby(['Año', 'Mes'])['Monto'].sum().reset_index()
            if not df_estacional.empty:
                fig_estacional = px.line(
                    df_estacional,
                    x='Mes',
                    y='Monto',
                    color='Año',
                    markers=True,
                    title=f"Tendencia Mensual de Pagos 2025 vs 2026",
                    labels={'Monto': 'Ingresos Pagados ($)', 'Mes': 'Mes'},
                    category_orders={"Mes": list(range(1, 13))}
                )
                st.plotly_chart(fig_estacional, use_container_width=True)

    with tab3:
        st.subheader("📊 Análisis de Servicios Pagados por Empresa")
       
        if 'Grupo Service' in df.columns:
            col_serv = 'Grupo Service'
        elif 'Grupo_Servicio' in df.columns:
            col_serv = 'Grupo_Servicio'
        elif 'Grupo Servicio' in df.columns:
            col_serv = 'Grupo Servicio'
        else:
            df['Grupo Servicio'] = 'SIN SERVICIO'
            col_serv = 'Grupo Servicio'

        df_analisis = df.dropna(subset=['Fecha_Pago']).groupby(['Empresa', col_serv])['Monto'].sum().reset_index()
        if col_serv != 'Grupo Servicio':
            df_analisis = df_analisis.rename(columns={col_serv: 'Grupo Servicio'})
       
        fig_bar = px.bar(
            df_analisis,
            x="Empresa",
            y="Monto",
            color="Grupo Servicio",
            title="Distribución de Servicios según Ingresos Reales",
            barmode="stack",
            labels={'Monto': 'Monto Pagado ($)'}
        )
        st.plotly_chart(fig_bar, use_container_width=True)
        st.info("💡 Tip: Analiza qué servicios generan mayor flujo de caja real por cliente.")

        st.subheader("📊 Análisis de Ventas Cruzadas (2026)")
        df_2026 = df.dropna(subset=['Fecha_Pago'])[df.dropna(subset=['Fecha_Pago'])['Año'] == 2026].copy()
        
        col_serv_2026 = 'Grupo Servicio' if 'Grupo Servicio' in df_2026.columns else ('Grupo_Servicio' if 'Grupo_Servicio' in df_2026.columns else None)
        if not col_serv_2026:
            df_2026['Grupo Servicio'] = 'SIN SERVICIO'
            col_serv_2026 = 'Grupo Servicio'
        elif col_serv_2026 != 'Grupo Servicio':
            df_2026['Grupo Servicio'] = df_2026[col_serv_2026]

        st.write("### Identificación de Venta Cruzada")
        servicios_disponibles = df_2026['Grupo Servicio'].unique() if not df_2026.empty else ["SERVICIO GENERAL"]
        servicio_target = st.selectbox("Selecciona un servicio para buscar clientes potenciales:", servicios_disponibles, key="select_servicio_target_cruzada")
             
        clientes_con_servicio = df_2026[df_2026['Grupo Servicio'] == servicio_target]['Empresa'].unique() if not df_2026.empty else []
        todos_los_clientes = df_2026['Empresa'].unique()
             
        clientes_potenciales = [c for c in todos_los_clientes if c not in clientes_con_servicio]
             
        if clientes_potenciales:
            st.success(f"Empresas que podrían contratar **{servicio_target}**:")
            df_potencial = pd.DataFrame(clientes_potenciales, columns=["Empresas sin este servicio"])
            st.table(df_potencial.head(10))
        else:
            st.info("¡Excelente! Todos tus clientes activos ya tienen contratado este servicio en base a los pagos recientes.")

        st.divider()

        st.subheader("🏆 Clasificación de Clientes (Por Facturación Real Pagada)")
        df_abc_raw = df.dropna(subset=['Fecha_Pago'])
        if not df_abc_raw.empty:
            df_abc = df_abc_raw.groupby('Empresa')['Monto'].sum().reset_index()
            df_abc = df_abc.sort_values(by='Monto', ascending=False)
            df_abc['Acumulado'] = df_abc['Monto'].cumsum()
            total_general_abc = df_abc['Monto'].sum()
           
            if total_general_abc > 0:
                df_abc['Porcentaje_Acumulado'] = (df_abc['Acumulado'] / total_general_abc) * 100
               
                def asignar_abc(p):
                    if p <= 80:
                        return 'Clase A (Alto Impacto)'
                    elif p <= 95:
                        return 'Clase B (Medio Impacto)'
                    else:
                        return 'Clase C (Bajo Impacto)'
                        
                df_abc['Categoria'] = df_abc['Porcentaje_Acumulado'].apply(asignar_abc)
                df_abc_disp = df_abc[['Empresa', 'Monto', 'Categoria']].copy()
                df_abc_disp['Monto'] = df_abc_disp['Monto'].apply(lambda x: f"${int(x):,.0f}".replace(",", "."))
                st.dataframe(df_abc_disp, use_container_width=True, hide_index=True)
                st.info("💡 **Estrategia ABC:** Cuida y mantén la relación cercana con tus clientes **Clase A** basándote en su aporte real de caja.")

        st.divider()

    # =========================================================================
    # SECCIÓN: MÓDULO DE COTIZACIONES (CREAR, EDITAR Y ELIMINAR)
    # =========================================================================
    with tab_cot:
        st.header("📑 Gestión de Cotizaciones")

        p_pdf_folio = f"137{len(df_cotizaciones)+7}"
        p_pdf_empresa = ""
        p_pdf_rut = ""
        p_pdf_planta = ""
        p_pdf_contacto = ""
        p_pdf_email_cont = ""
        p_pdf_fono_cont = ""
        p_pdf_ejecutivo = ""
        p_pdf_email_ejec = ""
        p_pdf_fono_ejec = ""
        p_pdf_neto = 0
        p_pdf_moneda = "CLP"
        p_pdf_glosa = ""
        p_pdf_detalle = ""
        p_pdf_fecha_emi = date.today()
        p_pdf_fecha_val = date.today() + timedelta(days=15)

        with st.expander("📄 Cargar e Importar Cotización desde Archivo PDF", expanded=False):
            st.write("Sube el PDF de una cotización emitida para extraer automáticamente su información. *(No almacena archivos)*")
            archivo_pdf_cot = st.file_uploader("Seleccionar archivo PDF Cotización", type=["pdf"], key="uploader_pdf_cotizacion")
            
            if archivo_pdf_cot is not None:
                if not PDF_READER_AVAILABLE:
                    st.error("⚠️ Para procesar archivos PDF en la nube, debes agregar `pdfplumber` o `pypdf` a tu archivo `requirements.txt` de GitHub.")
                else:
                    try:
                        texto_extraido = ""
                        pdf_stream = io.BytesIO(archivo_pdf_cot.read())
                        
                        if PDF_READER_TYPE == "pdfplumber":
                            with pdfplumber.open(pdf_stream) as pdf_doc:
                                for page in pdf_doc.pages:
                                    txt_p = page.extract_text()
                                    if txt_p:
                                        texto_extraido += txt_p + "\n"
                        elif PDF_READER_TYPE in ["pypdf", "pypdf2"]:
                            reader = pypdf.PdfReader(pdf_stream)
                            for page in reader.pages:
                                txt_p = page.extract_text()
                                if txt_p:
                                    texto_extraido += txt_p + "\n"

                        if texto_extraido:
                            import re
                            
                            if re.search(r'\b(?:USD|d[oó]lares|US\$|USD\$)\b', texto_extraido, re.IGNORECASE):
                                p_pdf_moneda = "USD"
                            else:
                                p_pdf_moneda = "CLP"

                            m_folio = re.search(r'(?:Folio|Cotizaci[oó]n|N[°º])\s*[:#]?\s*(\d+)', texto_extraido, re.IGNORECASE)
                            if m_folio:
                                p_pdf_folio = m_folio.group(1).strip()

                            m_rut = re.search(r'\b(\d{1,2}\.\d{3}\.\d{3}[-–][0-9kK]|\d{7,8}[-–][0-9kK])\b', texto_extraido)
                            if m_rut:
                                p_pdf_rut = m_rut.group(1).strip()

                            m_f_emi = re.search(r'(?:Fecha\s*Emisi[oó]n|Emisi[oó]n|Fecha)\s*[:#]?\s*(\d{4}[\/\.-]\d{1,2}[\/\.-]\d{1,2}|\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{4})', texto_extraido, re.IGNORECASE)
                            if m_f_emi:
                                try:
                                    str_f = m_f_emi.group(1).replace('/', '-').replace('.', '-')
                                    p_pdf_fecha_emi = pd.to_datetime(str_f, dayfirst=True if len(str_f.split('-')[0]) <= 2 else False).date()
                                except:
                                    pass

                            m_f_val = re.search(r'(?:V[aá]lido\s*Hasta|Validez|Vencimiento)\s*[:#]?\s*(\d{4}[\/\.-]\d{1,2}[\/\.-]\d{1,2}|\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{4})', texto_extraido, re.IGNORECASE)
                            if m_f_val:
                                try:
                                    str_fv = m_f_val.group(1).replace('/', '-').replace('.', '-')
                                    p_pdf_fecha_val = pd.to_datetime(str_fv, dayfirst=True if len(str_fv.split('-')[0]) <= 2 else False).date()
                                except:
                                    p_pdf_fecha_val = p_pdf_fecha_emi + timedelta(days=15)
                            else:
                                p_pdf_fecha_val = p_pdf_fecha_emi + timedelta(days=15)

                            m_neto = re.search(r'(?:Neto|Subtotal|Sub-Total)\s*[:$]?\s*([\d\.\,]+)', texto_extraido, re.IGNORECASE)
                            if m_neto:
                                try:
                                    limp = m_neto.group(1).replace('.', '').replace(',', '.')
                                    p_pdf_neto = int(round(float(limp)))
                                except:
                                    pass

                            emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', texto_extraido)
                            for em in emails:
                                if "itelcam" in em.lower():
                                    p_pdf_email_ejec = em
                                elif not p_pdf_email_cont:
                                    p_pdf_email_cont = em

                            fonos = re.findall(r'(?:\+?56\s?)?(?:9\s?\d{8}|\d{2}\s?\d{7})', texto_extraido)
                            if len(fonos) >= 1:
                                p_pdf_fono_ejec = fonos[0].replace(" ", "")
                            if len(fonos) >= 2:
                                p_pdf_fono_cont = fonos[1].replace(" ", "")

                            m_emp = re.search(r'(?:Señores|Señor(?:es)?|Empresa|Raz[oó]n Social|Cliente)\s*[:#]?\s*([^\n]+)', texto_extraido, re.IGNORECASE)
                            if m_emp:
                                val_e = m_emp.group(1).strip()
                                val_e = re.split(r'\b(?:RUT|Planta|Sucursal|Atenci[oó]n|Fecha)\b', val_e, flags=re.IGNORECASE)[0].strip()
                                if len(val_e) > 2:
                                    p_pdf_empresa = val_e.upper()

                            m_cont = re.search(r'(?:Contacto|Atenci[oó]n|Atte|Estimado)\s*[:#]?\s*([^\n]+)', texto_extraido, re.IGNORECASE)
                            if m_cont:
                                val_c = m_cont.group(1).strip()
                                val_c = re.split(r'\b(?:Email|Correo|Fono|Tel[eé]fono|RUT)\b', val_c, flags=re.IGNORECASE)[0].strip()
                                if len(val_c) > 2:
                                    p_pdf_contacto = val_c

                            m_ejec = re.search(r'(?:Ejecutivo|Atendida por|Vendedor|Emitido por)\s*[:#]?\s*([^\n]+)', texto_extraido, re.IGNORECASE)
                            if m_ejec:
                                val_ej = m_ejec.group(1).strip()
                                val_ej = re.split(r'\b(?:Email|Correo|Fono|Tel[eé]fono)\b', val_ej, flags=re.IGNORECASE)[0].strip()
                                if len(val_ej) > 2:
                                    p_pdf_ejecutivo = val_ej

                            m_planta = re.search(r'(?:Planta|Sucursal|Direcci[oó]n)\s*[:#]?\s*([^\n]+)', texto_extraido, re.IGNORECASE)
                            if m_planta:
                                val_p = m_planta.group(1).strip()
                                val_p = re.split(r'\b(?:RUT|Contacto|Fecha)\b', val_p, flags=re.IGNORECASE)[0].strip()
                                if len(val_p) > 2:
                                    p_pdf_planta = val_p.upper()

                            if not p_pdf_empresa and p_pdf_email_cont:
                                dom = p_pdf_email_cont.split("@")[-1].lower()
                                if "arcor" in dom or "dosenuno" in dom:
                                    p_pdf_empresa = "ARCOR / DOS EN UNO"
                                elif "agrosuper" in dom:
                                    p_pdf_empresa = "AGROSUPER"
                                elif "cmpc" in dom:
                                    p_pdf_empresa = "CMPC"

                            m_glosa = re.search(r'(?:Glosa|Descripci[oó]n|Trabajo a realizar)\s*[:#]?\s*([^\n]+(?:\n[^\n]+){0,3})', texto_extraido, re.IGNORECASE)
                            if m_glosa:
                                p_pdf_glosa = m_glosa.group(1).strip()

                            st.success("✅ Archivo PDF procesado exitosamente. Fechas y datos extraídos correctamente.")
                        else:
                            st.warning("No se pudo extraer texto legible del PDF.")
                    except Exception as e:
                        st.error(f"Error al leer el archivo PDF: {e}")

        with st.expander("➕ Generar Nueva Cotización (Manual o Autocompletada)", expanded=True):
            
            contactos_opciones = ["➕ Crear/Ingresar Nuevo Contacto"]
            if not df_contactos.empty:
                for _, r_cont in df_contactos.iterrows():
                    nom_disp = str(r_cont.get('Nombre', '')).strip()
                    emp_disp = str(r_cont.get('Empresa', '')).strip()
                    if nom_disp or emp_disp:
                        contactos_opciones.append(f"{nom_disp} ({emp_disp})".strip())

            contacto_cot_sel = st.selectbox(
                "Seleccionar Contacto del CRM para autocompletar (Opcional):",
                options=contactos_opciones,
                key="select_contacto_cotizacion_manual"
            )

            sug_nombre = p_pdf_contacto
            sug_email = p_pdf_email_cont
            sug_fono = p_pdf_fono_cont
            sug_empresa = p_pdf_empresa
            sug_planta = p_pdf_planta

            if contacto_cot_sel != "➕ Crear/Ingresar Nuevo Contacto" and not df_contactos.empty:
                nombre_extraido = contacto_cot_sel.split(" (")[0].strip()
                m_match = df_contactos[df_contactos['Nombre'].astype(str).str.strip() == nombre_extraido]
                if not m_match.empty:
                    row_m = m_match.iloc[0]
                    sug_nombre = str(row_m.get('Nombre', '')).strip()
                    sug_email = str(row_m.get('Correo', row_m.get('email', ''))).strip()
                    sug_fono = str(row_m.get('Celular', row_m.get('telefono', ''))).strip()
                    sug_empresa = str(row_m.get('Empresa', '')).strip().upper()
                    sug_planta = str(row_m.get('Planta', '')).strip().upper()

            with st.form("form_nueva_cotizacion", clear_on_submit=True):
                st.subheader("1. Identificación y Encabezado del Documento")
                c_head1, c_head2, c_head3 = st.columns(3)
                
                with c_head1:
                    cot_folio = st.text_input("Folio N° *", value=p_pdf_folio)
                    cot_empresa = st.text_input("Empresa (Cliente) *", value=sug_empresa)
                    cot_rut = st.text_input("RUT Cliente *", value=p_pdf_rut)
                    cot_planta = st.text_input("Planta / Sucursal", value=sug_planta)
                
                with c_head2:
                    cot_contacto = st.text_input("Nombre Contacto Cliente", value=sug_nombre)
                    cot_email_cont = st.text_input("Email Contacto", value=sug_email)
                    cot_fono_cont = st.text_input("Fono Contacto", value=sug_fono)
                    cot_condicion = st.selectbox("Condición de Pago", ["Contado CLP", "Crédito 30 días", "Crédito 60 días", "Transferencia / Chq"])

                with c_head3:
                    cot_ejecutivo = st.text_input("Ejecutivo Comercial", value=p_pdf_ejecutivo)
                    cot_email_ejec = st.text_input("Email Ejecutivo", value=p_pdf_email_ejec)
                    cot_fono_ejec = st.text_input("Fono Ejecutivo", value=p_pdf_fono_ejec)
                    
                    c_f1, c_f2 = st.columns(2)
                    cot_f_emi = c_f1.date_input("Fecha Emisión", value=p_pdf_fecha_emi)
                    cot_f_val = c_f2.date_input("Válido Hasta", value=p_pdf_fecha_val)

                st.divider()
                st.subheader("2. Glosa Descriptiva del Servicio")
                cot_glosa = st.text_area("Glosa / Descripción resumida del trabajo:", value=p_pdf_glosa)

                st.divider()
                st.subheader("3. Detalle por Sección / Items Cotizados")
                
                servicios_exist = sorted(df['Grupo Servicio'].dropna().unique().tolist()) if not df.empty else ["SERVICIO GENERAL"]
                cot_grupo_serv = st.selectbox("Grupo de Servicio", options=servicios_exist, key="cot_grupo_serv_sel")
                
                det_col0, det_col1, det_col2, det_col3, det_col4 = st.columns([1.5, 1, 1, 4, 2])
                cot_moneda = det_col0.selectbox("Moneda *", ["CLP", "USD"], index=0 if p_pdf_moneda == "CLP" else 1, key="cot_moneda_select_new")
                cot_cant = det_col1.number_input("Cant.", min_value=1, value=1)
                cot_uni = det_col2.text_input("Unid.", value="SC")
                cot_detalle = det_col3.text_input("Detalle del Servicio", value=p_pdf_detalle)
                cot_neto = det_col4.number_input("Valor Neto", min_value=0, step=100 if cot_moneda == "USD" else 1000, value=p_pdf_neto)

                calc_iva = int(round(cot_neto * 0.19))
                calc_total = cot_neto + calc_iva
                simbolo_m = "$" if cot_moneda == "CLP" else "US$"
                
                m1, m2, m3 = st.columns(3)
                m1.metric("Subtotal Neto", f"{simbolo_m}{cot_neto:,.0f}".replace(",", "."))
                m2.metric("IVA (19%)", f"{simbolo_m}{calc_iva:,.0f}".replace(",", "."))
                m3.metric("Total Cotización", f"{simbolo_m}{calc_total:,.0f}".replace(",", "."))

                if st.form_submit_button("💾 Guardar y Registrar Cotización"):
                    if cot_folio and cot_empresa:
                        dict_guardar = {
                            "Folio": str(cot_folio).strip(),
                            "Empresa": cot_empresa.strip().upper(),
                            "RUT_Empresa": cot_rut.strip(),
                            "Planta": cot_planta.strip().upper(),
                            "Contacto": cot_contacto.strip(),
                            "Email_Contacto": cot_email_cont.strip(),
                            "Fono_Contacto": cot_fono_cont.strip(),
                            "Ejecutivo": cot_ejecutivo.strip(),
                            "Email_Ejecutivo": cot_email_ejec.strip(),
                            "Fono_Ejecutivo": cot_fono_ejec.strip(),
                            "Condicion_Pago": cot_condicion,
                            "Moneda": cot_moneda,
                            "Fecha_Emision": str(cot_f_emi),
                            "Fecha_Validez": str(cot_f_val),
                            "Glosa": cot_glosa.strip(),
                            "Grupo_Servicio": cot_grupo_serv.upper(),
                            "Detalle_Servicio": cot_detalle.strip().upper(),
                            "Cantidad": int(cot_cant),
                            "Unidad": cot_uni.strip().upper(),
                            "Monto_Neto": int(cot_neto),
                            "Monto_IVA": calc_iva,
                            "Monto_Total": calc_total,
                            "Estado": "PENDIENTE"
                        }
                        guardar_cotizacion(dict_guardar)
                        st.success(f"¡Cotización Folio N° {cot_folio} guardada exitosamente y contacto sincronizado en la nube!")
                        st.rerun()
                    else:
                        st.warning("Por favor ingresa el Folio y Nombre de Empresa.")

        with st.expander("✏ Editar Cotización Existente"):
            if not df_cotizaciones.empty and 'Folio' in df_cotizaciones.columns:
                folios_cot_list = sorted(df_cotizaciones['Folio'].astype(str).unique().tolist())
                folio_cot_editar = st.selectbox("Selecciona el Folio de Cotización a Editar:", folios_cot_list, key="select_cot_edit")
                
                if folio_cot_editar:
                    row_c_edit = df_cotizaciones[df_cotizaciones['Folio'].astype(str) == str(folio_cot_editar)].iloc[0]
                    
                    def parse_date_dynamic(val, fallback):
                        if pd.notna(val) and str(val).strip() not in ["", "None", "NaT", "nan"]:
                            try:
                                return pd.to_datetime(val).date()
                            except:
                                return fallback
                        return fallback

                    with st.form(f"form_edit_cot_{folio_cot_editar}"):
                        st.subheader(f"Modificar Cotización Folio #{folio_cot_editar}")
                        ec_col1, ec_col2, ec_col3 = st.columns(3)
                        
                        with ec_col1:
                            ec_empresa = st.text_input("Empresa", value=str(row_c_edit.get('Empresa', '')))
                            ec_rut = st.text_input("RUT Cliente", value=str(row_c_edit.get('RUT_Empresa', '')))
                            ec_planta = st.text_input("Planta", value=str(row_c_edit.get('Planta', '')))
                            ec_condicion = st.selectbox("Condición de Pago", ["Contado CLP", "Crédito 30 días", "Crédito 60 días", "Transferencia / Chq"],
                                                       index=["Contado CLP", "Crédito 30 días", "Crédito 60 días", "Transferencia / Chq"].index(row_c_edit.get('Condicion_Pago', 'Contado CLP')) if row_c_edit.get('Condicion_Pago') in ["Contado CLP", "Crédito 30 días", "Crédito 60 días", "Transferencia / Chq"] else 0)
                        
                        with ec_col2:
                            ec_contacto = st.text_input("Contacto Cliente", value=str(row_c_edit.get('Contacto', '')))
                            ec_email_cont = st.text_input("Email Contacto", value=str(row_c_edit.get('Email_Contacto', '')))
                            ec_fono_cont = st.text_input("Fono Contacto", value=str(row_c_edit.get('Fono_Contacto', '')))
                            ec_estado = st.selectbox("Estado", ["PENDIENTE", "GANADO", "RECHAZADA"], 
                                                     index=["PENDIENTE", "GANADO", "RECHAZADA"].index(row_c_edit.get('Estado', 'PENDIENTE')) if row_c_edit.get('Estado') in ["PENDIENTE", "GANADO", "RECHAZADA"] else 0)

                        with ec_col3:
                            ec_ejecutivo = st.text_input("Ejecutivo", value=str(row_c_edit.get('Ejecutivo', '')))
                            ec_email_ejec = st.text_input("Email Ejecutivo", value=str(row_c_edit.get('Email_Ejecutivo', '')))
                            ec_fono_ejec = st.text_input("Fono Ejecutivo", value=str(row_c_edit.get('Fono_Ejecutivo', '')))
                            ec_f_emi = st.date_input("Fecha Emisión", value=parse_date_dynamic(row_c_edit.get('Fecha_Emision'), date.today()))
                            ec_f_val = st.date_input("Válido Hasta", value=parse_date_dynamic(row_c_edit.get('Fecha_Validez'), date.today() + timedelta(days=15)))

                        ec_glosa = st.text_area("Glosa", value=str(row_c_edit.get('Glosa', '')))
                        
                        servicios_exist = sorted(df['Grupo Servicio'].dropna().unique().tolist()) if not df.empty else ["SERVICIO GENERAL"]
                        grp_c_act = str(row_c_edit.get('Grupo_Servicio', '')).strip().upper()
                        if grp_c_act and grp_c_act not in servicios_exist:
                            servicios_exist.append(grp_c_act)
                            servicios_exist = sorted(servicios_exist)
                        idx_c_grp = servicios_exist.index(grp_c_act) if grp_c_act in servicios_exist else 0
                        
                        ec_grupo_serv = st.selectbox("Grupo Servicio", options=servicios_exist, index=idx_c_grp, key=f"edit_grp_serv_cot_{folio_cot_editar}")
                        
                        ed_col0, ed_col1, ed_col2, ed_col3, ed_col4 = st.columns([1.5, 1, 1, 4, 2])
                        moneda_act = str(row_c_edit.get('Moneda', 'CLP')).upper()
                        ec_moneda = ed_col0.selectbox("Moneda", ["CLP", "USD"], index=1 if moneda_act == "USD" else 0, key=f"edit_moneda_{folio_cot_editar}")
                        ec_cant = ed_col1.number_input("Cantidad", min_value=1, value=int(row_c_edit.get('Cantidad', 1)))
                        ec_uni = ed_col2.text_input("Unidad", value=str(row_c_edit.get('Unidad', 'SC')))
                        ec_detalle = ed_col3.text_input("Detalle Servicio", value=str(row_c_edit.get('Detalle_Servicio', '')))
                        ec_neto = ed_col4.number_input("Monto Neto", min_value=0, step=100 if ec_moneda == "USD" else 1000, value=int(row_c_edit.get('Monto_Neto', 0)))

                        if st.form_submit_button("💾 Guardar Cambios en Cotización"):
                            c_iva_edit = int(round(ec_neto * 0.19))
                            c_total_edit = ec_neto + c_iva_edit
                            
                            dict_editado = {
                                "Folio": str(folio_cot_editar).strip(),
                                "Empresa": ec_empresa.strip().upper(),
                                "RUT_Empresa": ec_rut.strip(),
                                "Planta": ec_planta.strip().upper(),
                                "Contacto": ec_contacto.strip(),
                                "Email_Contacto": ec_email_cont.strip(),
                                "Fono_Contacto": ec_fono_cont.strip(),
                                "Ejecutivo": ec_ejecutivo.strip(),
                                "Email_Ejecutivo": ec_email_ejec.strip(),
                                "Fono_Ejecutivo": ec_fono_ejec.strip(),
                                "Condicion_Pago": ec_condicion,
                                "Moneda": ec_moneda,
                                "Fecha_Emision": str(ec_f_emi),
                                "Fecha_Validez": str(ec_f_val),
                                "Glosa": ec_glosa.strip(),
                                "Grupo_Servicio": ec_grupo_serv.upper(),
                                "Detalle_Servicio": ec_detalle.strip().upper(),
                                "Cantidad": int(ec_cant),
                                "Unidad": ec_uni.strip().upper(),
                                "Monto_Neto": int(ec_neto),
                                "Monto_IVA": c_iva_edit,
                                "Monto_Total": c_total_edit,
                                "Estado": ec_estado
                            }
                            guardar_cotizacion(dict_editado)
                            st.success(f"¡Cotización Folio N° {folio_cot_editar} actualizada exitosamente!")
                            st.rerun()
            else:
                st.info("No hay cotizaciones registradas para editar.")

        with st.expander("🗑 Eliminar Cotización"):
            if not df_cotizaciones.empty and 'Folio' in df_cotizaciones.columns:
                folios_del_list = sorted(df_cotizaciones['Folio'].astype(str).unique().tolist())
                folio_cot_del = st.selectbox("Selecciona el Folio de Cotización a Eliminar:", folios_del_list, key="select_cot_del")
                
                if folio_cot_del:
                    row_del = df_cotizaciones[df_cotizaciones['Folio'].astype(str) == str(folio_cot_del)].iloc[0]
                    st.warning(f"⚠️ ¿Estás seguro de que deseas eliminar permanentemente la Cotización Folio **#{folio_cot_del}** del cliente **{row_del.get('Empresa', 'N/A')}**?")
                    
                    if st.button(f"🔥 Confirmar y Eliminar Cotización #{folio_cot_del}", key="btn_confirm_del_cot"):
                        eliminar_cotizacion(folio_cot_del)
                        st.success(f"Cotización Folio #{folio_cot_del} eliminada con éxito de Supabase.")
                        st.rerun()
            else:
                st.info("No hay cotizaciones registradas para eliminar.")

        st.divider()

        st.subheader("📋 Historial de Cotizaciones Emitidas")
        if not df_cotizaciones.empty:
            df_cot_disp = df_cotizaciones.copy()
            if 'Moneda' not in df_cot_disp.columns:
                df_cot_disp['Moneda'] = 'CLP'
            df_cot_disp['Fecha_Emision'] = df_cot_disp['Fecha_Emision'].astype(str).str.split(' ').str[0].str.split('T').str[0]
                
            st.dataframe(
                df_cot_disp[["Folio", "Empresa", "Planta", "Contacto", "Fecha_Emision", "Moneda", "Grupo_Servicio", "Monto_Neto", "Monto_Total", "Estado"]],
                column_config={
                    "Monto_Neto": st.column_config.NumberColumn("Monto Neto", format="%d"),
                    "Monto_Total": st.column_config.NumberColumn("Total", format="%d"),
                    "Fecha_Emision": st.column_config.TextColumn("Fecha Emisión")
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No hay cotizaciones registradas aún.")

    with tab4:
        st.header("➕ Gestión de Facturas y Ciclo de Pago")

        if "doc_factura" not in st.session_state:
            st.session_state["doc_factura"] = ""
        if "doc_empresa" not in st.session_state:
            st.session_state["doc_empresa"] = ""
        if "doc_planta_pdf" not in st.session_state:
            st.session_state["doc_planta_pdf"] = ""
        if "doc_grupo_serv" not in st.session_state:
            st.session_state["doc_grupo_serv"] = "SERVICIO GENERAL"
        if "doc_monto_neto" not in st.session_state:
            st.session_state["doc_monto_neto"] = 0
        if "doc_moneda" not in st.session_state:
            st.session_state["doc_moneda"] = "CLP"
        if "doc_fecha_cot" not in st.session_state:
            st.session_state["doc_fecha_cot"] = date.today()
        if "doc_fecha_emi" not in st.session_state:
            st.session_state["doc_fecha_emi"] = date.today()
        if "doc_fecha_venc" not in st.session_state:
            st.session_state["doc_fecha_venc"] = date.today() + timedelta(days=30)
        if "doc_detalle" not in st.session_state:
            st.session_state["doc_detalle"] = ""

        PALABRAS_CLAVE_SERVICIOS = [
            "MANTENIMIENTO", "MONITOREO", "MANTENCION", "REPARACION", "INSTALACION",
            "CONFIGURACION", "CABLEADO", "FIBRA OPTICA", "CAMARAS", "CCTV", "CONTROL DE ACCESO",
            "SOPORTE", "PROYECTO", "OBRA", "SUMINISTRO", "INSPECCION", "MONTAJE", "REDES"
        ]

        with st.expander("📄 Cargar e Importar Factura desde Archivo PDF", expanded=False):
            st.write("Sube el PDF de una factura recibida o emitida para extraer automáticamente sus datos. *(No almacena el archivo)*")
            archivo_pdf_fact = st.file_uploader("Seleccionar archivo PDF Factura", type=["pdf"], key="uploader_pdf_factura")
            
            if archivo_pdf_fact is not None:
                if not PDF_READER_AVAILABLE:
                    st.error("⚠️ Para procesar archivos PDF en la nube, debes agregar `pdfplumber` a tu archivo `requirements.txt` de GitHub.")
                else:
                    try:
                        texto_fact_pdf = ""
                        pdf_stream_f = io.BytesIO(archivo_pdf_fact.read())
                        
                        if PDF_READER_TYPE == "pdfplumber":
                            with pdfplumber.open(pdf_stream_f) as pdf_doc_f:
                                for page in pdf_doc_f.pages:
                                    txt_p = page.extract_text()
                                    if txt_p:
                                        texto_fact_pdf += txt_p + "\n"
                        elif PDF_READER_TYPE in ["pypdf", "pypdf2"]:
                            reader_f = pypdf.PdfReader(pdf_stream_f)
                            for page in reader_f.pages:
                                txt_p = page.extract_text()
                                if txt_p:
                                    texto_fact_pdf += txt_p + "\n"

                        if texto_fact_pdf:
                            import re

                            meses_es = {
                                'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
                                'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
                            }

                            if re.search(r'\b(?:USD|d[oó]lares|US\$|USD\$)\b', texto_fact_pdf, re.IGNORECASE):
                                st.session_state["doc_moneda"] = "USD"
                            else:
                                st.session_state["doc_moneda"] = "CLP"

                            m_fact = re.search(r'(?:FACTURA\s*ELECTR[OÓ]NICA\s*)?N[º°]\s*(\d+)', texto_fact_pdf, re.IGNORECASE)
                            if m_fact:
                                st.session_state["doc_factura"] = m_fact.group(1).strip()

                            m_emp_f = re.search(r'SEÑOR\(ES\)\s*:\s*([^\n]+)', texto_fact_pdf, re.IGNORECASE)
                            if m_emp_f:
                                val_ef = m_emp_f.group(1).strip()
                                val_ef = re.split(r'\b(?:RUT|R\.U\.T|Planta|Sucursal|Fecha)\b', val_ef, flags=re.IGNORECASE)[0].strip()
                                st.session_state["doc_empresa"] = val_ef.upper()

                            m_f_emi_txt = re.search(r'Fecha\s*Emisi[oó]n\s*:\s*(\d{1,2})\s*de\s*([A-Za-z]+)\s*del?\s*(\d{4})', texto_fact_pdf, re.IGNORECASE)
                            if m_f_emi_txt:
                                dia_e = int(m_f_emi_txt.group(1))
                                mes_e_str = m_f_emi_txt.group(2).lower()
                                anio_e = int(m_f_emi_txt.group(3))
                                mes_e = meses_es.get(mes_e_str, 1)
                                st.session_state["doc_fecha_emi"] = date(anio_e, mes_e, dia_e)

                            m_f_venc_pago = re.search(r'(\d{4}-\d{2}-\d{2})\s*\$[\d\.\,]+\s*Pago\s*total', texto_fact_pdf, re.IGNORECASE)
                            if m_f_venc_pago:
                                try:
                                    st.session_state["doc_fecha_venc"] = pd.to_datetime(m_f_venc_pago.group(1)).date()
                                except:
                                    pass

                            m_planta_pdf = re.search(r'Planta\s+([A-Za-z0-9\áéíóúÁÉÍÓÚñÑ]+)', texto_fact_pdf, re.IGNORECASE)
                            if m_planta_pdf:
                                st.session_state["doc_planta_pdf"] = m_planta_pdf.group(1).strip().upper()

                            m_neto_f = re.search(r'MONTO\s*NETO\s*\$?\s*([\d\.\,]+)', texto_fact_pdf, re.IGNORECASE)
                            if m_neto_f:
                                try:
                                    limp_f = m_neto_f.group(1).replace('.', '').replace(',', '.')
                                    st.session_state["doc_monto_neto"] = int(round(float(limp_f)))
                                except:
                                    pass

                            lineas_pdf = [l.strip() for l in texto_fact_pdf.split('\n') if l.strip()]
                            det_lineas = []
                            capturando = False
                            
                            planta_key = st.session_state.get("doc_planta_pdf", "").upper()
                            
                            for l in lineas_pdf:
                                l_upper = l.upper()
                                coincide_kw = any(kw in l_upper for kw in PALABRAS_CLAVE_SERVICIOS)
                                coincide_planta = (planta_key != "" and planta_key in l_upper)
                                
                                if "TRABAJOS" in l_upper or "INSTALACIÓN" in l_upper or "SERVICIO" in l_upper or coincide_kw or coincide_planta:
                                    capturando = True
                                if capturando:
                                    if any(k in l_upper for k in ["REFERENCIAS", "PAGOS", "MONTO NETO", "FORMA DE PAGO", "1 SG"]):
                                        break
                                    det_lineas.append(l)
                                    
                            if det_lineas:
                                st.session_state["doc_detalle"] = " ".join(det_lineas).upper()
                            else:
                                m_det_gen = re.search(r'Trabajos[^\n]*\n([^\n]+)', texto_fact_pdf, re.IGNORECASE)
                                if m_det_gen:
                                    st.session_state["doc_detalle"] = m_det_gen.group(1).strip().upper()

                            st.success(f"✅ Factura PDF N° {st.session_state['doc_factura']} ({st.session_state['doc_empresa']}) leída correctamente. Datos extraídos sin almacenar el archivo.")
                        else:
                            st.warning("No se pudo extraer texto legible del PDF de la factura.")
                    except Exception as e:
                        st.error(f"Error al leer el archivo PDF de la factura: {e}")

        with st.expander("📄 Cargar Importar Factura desde Archivo XML (DTE)", expanded=False):
            st.write("Sube el archivo XML del Documento Tributario Electrónico (DTE) emitido o recibido para registrar la factura. *(No almacena el archivo en servidor/nube)*")
            archivo_xml = st.file_uploader("Seleccionar archivo XML DTE", type=["xml"], key="uploader_xml_factura")

            if archivo_xml is not None:
                try:
                    xml_stream = io.BytesIO(archivo_xml.read())
                    tree = ET.parse(xml_stream)
                    root = tree.getroot()
                    
                    for elem in root.iter():
                        if '}' in elem.tag:
                            elem.tag = elem.tag.split('}', 1)[1]
                    
                    folio_elem = root.find(".//Folio")
                    if folio_elem is not None and folio_elem.text:
                        st.session_state["doc_factura"] = folio_elem.text.strip()
                    
                    recep_elem = root.find(".//RznSocRecep")
                    emisor_elem = root.find(".//RznSoc")
                    if recep_elem is not None and recep_elem.text:
                        st.session_state["doc_empresa"] = recep_elem.text.strip().upper()
                    elif emisor_elem is not None and emisor_elem.text:
                        st.session_state["doc_empresa"] = emisor_elem.text.strip().upper()
                        
                    neto_elem = root.find(".//MntNeto")
                    if neto_elem is not None and neto_elem.text:
                        try:
                            st.session_state["doc_monto_neto"] = int(round(float(neto_elem.text.strip())))
                        except:
                            pass

                    fch_elem = root.find(".//FchEmis")
                    if fch_elem is not None and fch_elem.text:
                        try:
                            st.session_state["doc_fecha_emi"] = pd.to_datetime(fch_elem.text.strip()).date()
                        except:
                            pass

                    fch_venc_elem = root.find(".//FchVenc")
                    if fch_venc_elem is not None and fch_venc_elem.text:
                        try:
                            st.session_state["doc_fecha_venc"] = pd.to_datetime(fch_venc_elem.text.strip()).date()
                        except:
                            pass

                    detalles_items = []
                    for item in root.findall(".//DchItem"):
                        nmb = item.find("NmbItem")
                        dsc = item.find("DscrItem")
                        txt_item = ""
                        if nmb is not None and nmb.text:
                            txt_item += nmb.text.strip()
                        if dsc is not None and dsc.text:
                            txt_item += f" ({dsc.text.strip()})" if txt_item else dsc.text.strip()
                        if txt_item:
                            detalles_items.append(txt_item)

                    if not detalles_items:
                        for nmb in root.findall(".//NmbItem"):
                            if nmb.text:
                                detalles_items.append(nmb.text.strip())

                    if detalles_items:
                        st.session_state["doc_detalle"] = " / ".join(detalles_items).upper()

                    st.success(f"✅ Factura XML N° {st.session_state['doc_factura']} ({st.session_state['doc_empresa']}) leída correctamente.")
                except Exception as e:
                    st.error(f"Error al procesar el archivo XML: {e}")

        st.divider()

        with st.expander("➕ Crear Nueva Factura / Registro de Ingreso", expanded=True):
            st.markdown("### 🔗 Enlazar desde Cotización Existente (Opcional)")
            cotizaciones_list = df_cotizaciones["Folio"].astype(str).tolist() if not df_cotizaciones.empty else []
            
            def cargar_datos_cotizacion_callback():
                cot_sel = st.session_state.get("select_cot_to_fact")
                if cot_sel and cot_sel != "--- Sin Enlace ---":
                    row_c = df_cotizaciones[df_cotizaciones["Folio"].astype(str) == str(cot_sel)].iloc[0]
                    st.session_state["doc_empresa"] = str(row_c.get("Empresa", "")).strip().upper()
                    st.session_state["doc_planta_pdf"] = str(row_c.get("Planta", "")).strip().upper()
                    
                    grupo_cot = str(row_c.get("Grupo_Servicio", "SERVICIO GENERAL")).strip().upper()
                    st.session_state["doc_grupo_serv"] = grupo_cot
                    st.session_state["doc_moneda"] = str(row_c.get("Moneda", "CLP")).upper()
                    
                    if not st.session_state.get("doc_detalle"):
                        cand_detalle = str(row_c.get("Detalle_Servicio", row_c.get("Glosa", ""))).strip().upper()
                        st.session_state["doc_detalle"] = cand_detalle
                    
                    if not st.session_state.get("doc_monto_neto") or st.session_state.get("doc_monto_neto") == 0:
                        st.session_state["doc_monto_neto"] = int(row_c.get("Monto_Neto", row_c.get("Monto_Total", 0)))
                    
                    raw_f_cot = row_c.get("Fecha_Emision")
                    if pd.notna(raw_f_cot) and str(raw_f_cot).strip() not in ["", "None", "NaT"]:
                        try:
                            st.session_state["doc_fecha_cot"] = pd.to_datetime(raw_f_cot).date()
                        except:
                            st.session_state["doc_fecha_cot"] = date.today()

            cot_seleccionada = st.selectbox(
                "Seleccionar Cotización para importar datos:",
                options=["--- Sin Enlace ---"] + cotizaciones_list,
                key="select_cot_to_fact",
                on_change=cargar_datos_cotizacion_callback
            )

            if cot_seleccionada != "--- Sin Enlace ---":
                st.info(f"💡 Datos vinculados desde Cotización Folio **#{cot_seleccionada}** (Fecha Cotización: {st.session_state['doc_fecha_cot']})")

            with st.form("form_nueva_factura", clear_on_submit=True):
                fc1, fc2 = st.columns(2)
                with fc1:
                    n_factura = st.text_input("Número de Factura / Documento", value=st.session_state["doc_factura"])
                    n_empresa_ins = st.text_input("Empresa", value=st.session_state["doc_empresa"])
                    n_planta_ins = st.text_input("Planta", value=st.session_state["doc_planta_pdf"])
                    
                    servicios_existentes = sorted(df['Grupo Servicio'].dropna().unique().tolist()) if not df.empty else ["SERVICIO GENERAL"]
                    p_grp_s = st.session_state["doc_grupo_serv"]
                    if p_grp_s and p_grp_s not in servicios_existentes:
                        servicios_existentes.append(p_grp_s)
                        servicios_existentes = sorted(servicios_existentes)
                    
                    idx_grp_p = servicios_existentes.index(p_grp_s) if p_grp_s in servicios_existentes else 0
                    n_grupo_servicio = st.selectbox("Grupo Servicio", options=servicios_existentes, index=idx_grp_p, key="n_grupo_serv_input")
                    
                    n_servicio_detalle = st.text_input("Servicio (Detalle del servicio prestado)", value=st.session_state["doc_detalle"], key="n_serv_det_input")
                    
                    m_col1, m_col2 = st.columns([1, 3])
                    n_moneda = m_col1.selectbox("Moneda", ["CLP", "USD"], index=0 if st.session_state["doc_moneda"] == "CLP" else 1, key="n_moneda_select_fact")
                    n_monto = m_col2.number_input("Monto Neto", min_value=0, step=100 if n_moneda == "USD" else 1000, value=st.session_state["doc_monto_neto"])
                    
                    n_dias_prog = st.number_input("Días Programados de Ejecución", min_value=0.0, step=1.0, value=0.0)
                    n_dias_real = st.number_input("Días Reales de Ejecución", min_value=0.0, step=1.0, value=0.0)

                with fc2:
                    n_estado_pago = st.selectbox("Estado de Pago", ["PENDIENTE", "Pagado"])
                    if n_estado_pago == "Pagado":
                        n_f_pago = st.date_input("Fecha de Pago", value=datetime.now())
                    else:
                        n_f_pago = st.date_input("Fecha de Pago", value=None)
                        
                    n_f_cot = st.date_input("Fecha Cotización", value=st.session_state["doc_fecha_cot"])
                    n_f_oc = st.date_input("Fecha Orden de Compra", value=None)
                    n_f_emi = st.date_input("Fecha Emisión", value=st.session_state["doc_fecha_emi"])
                    n_f_venc = st.date_input("Fecha Vencimiento", value=st.session_state["doc_fecha_venc"])
                    
                    n_f_ges = st.date_input("Fecha GES (si aplica)", value=None)
                    n_req_ges = st.selectbox("¿Requiere GES?", ["No", "Sí"], key="n_req_ges_input")
                
                if st.form_submit_button("💾 Guardar y Sincronizar en la Nube"):
                    if n_factura.strip() != "" and n_empresa_ins.strip() != "":
                        fecha_pago_final = pd.to_datetime(n_f_pago) if (n_estado_pago == "Pagado" and n_f_pago) else None
                        
                        if pd.notna(fecha_pago_final):
                            anio_val = int(fecha_pago_final.year)
                            mes_val = int(fecha_pago_final.month)
                        else:
                            anio_val = None
                            mes_val = None

                        nuevo_registro_supa = {
                            "Factura": str(n_factura).strip(),
                            "Empresa": n_empresa_ins.strip().upper(),
                            "Planta": n_planta_ins.strip().upper() if n_planta_ins else "SIN PLANTA",
                            "Grupo_Servicio": n_grupo_servicio.upper(),
                            "Servicio": n_servicio_detalle.strip().upper() if n_servicio_detalle else "SIN DETALLE",
                            "Monto": int(n_monto),
                            "dias_programados": float(n_dias_prog),
                            "dias_reales": float(n_dias_real),
                            "Fecha_Cotizacion": str(n_f_cot) if n_f_cot else None,
                            "Fecha_OC": str(n_f_oc) if n_f_oc else None,
                            "Fecha_Emision": str(n_f_emi) if n_f_emi else None,
                            "Fecha_Vencimiento": str(n_f_venc) if n_f_venc else None,
                            "Fecha_GES": str(n_f_ges) if n_f_ges else None,
                            "Fecha_Pago": str(fecha_pago_final) if fecha_pago_final else None,
                            "Semaforo": "",
                            "Estado": n_estado_pago,
                            "Requiere_GES": n_req_ges,
                            "Ano": anio_val,
                            "Mes": mes_val
                        }
                        
                        try:
                            supabase.table("ingresos").upsert(nuevo_registro_supa, on_conflict="Factura").execute()
                            
                            if cot_seleccionada != "--- Sin Enlace ---":
                                marcar_cotizacion_como_ganada(cot_seleccionada, n_empresa_ins.strip().upper(), n_planta_ins.strip().upper(), int(n_monto))
                            else:
                                guardar_contacto(
                                    nombre=f"Contacto {n_empresa_ins.strip().upper()}",
                                    email=f"contacto@{n_empresa_ins.strip().lower().replace(' ', '')}.cl",
                                    estado="Ganado",
                                    empresa=n_empresa_ins.strip().upper(),
                                    planta=n_planta_ins.strip().upper() if n_planta_ins else "SIN PLANTA",
                                    valor=int(n_monto),
                                    rol="Finanzas / Compras"
                                )
                            
                            st.success(f"¡Factura #{n_factura} guardada y sincronizada exitosamente!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al guardar en Supabase: {e}")
                    else:
                        st.warning("Por lo menos debes rellenar el Número de Factura y la Empresa.")

        with st.expander("✏ Editar Factura Existente (Todas las Secciones)"):
            if not df.empty and 'Factura' in df.columns:
                facturas_list = sorted(df['Factura'].astype(str).unique().tolist())
                factura_a_editar = st.selectbox("Selecciona la Factura a Modificar:", facturas_list, key="edit_factura_select")
                
                if factura_a_editar:
                    row_edit = df[df['Factura'].astype(str) == str(factura_a_editar)].iloc[0]
                    
                    def safe_date_val(val):
                        if pd.notna(val) and str(val).strip() != "" and str(val) not in ["None", "NaT", "nan"]:
                            try:
                                return pd.to_datetime(val).date()
                            except:
                                return None
                        return None

                    def safe_date_str(val):
                        d = safe_date_val(val)
                        return str(d) if d else None

                    with st.form(f"form_editar_factura_{factura_a_editar}"):
                        e_col1, e_col2 = st.columns(2)
                        with e_col1:
                            e_empresa = st.text_input("Empresa", value=str(row_edit.get('Empresa', '')))
                            e_planta = st.text_input("Planta", value=str(row_edit.get('Planta', '')))
                            
                            servicios_existentes = sorted(df['Grupo Servicio'].dropna().unique().tolist()) if not df.empty else ["SERVICIO GENERAL"]
                            grp_actual = str(row_edit.get('Grupo Servicio', row_edit.get('Grupo_Servicio', ''))).strip().upper()
                            if grp_actual and grp_actual not in servicios_existentes:
                                servicios_existentes.append(grp_actual)
                                servicios_existentes = sorted(servicios_existentes)
                            idx_grp = servicios_existentes.index(grp_actual) if grp_actual in servicios_existentes else 0
                            e_grupo_servicio = st.selectbox("Grupo Servicio", options=servicios_existentes, index=idx_grp, key=f"e_grupo_serv_{factura_a_editar}")
                            
                            e_servicio_detalle = st.text_input("Servicio (Detalle)", value=str(row_edit.get('Servicio', '')))
                            
                            em_col1, em_col2 = st.columns([1, 3])
                            mon_f_act = str(row_edit.get('Moneda', 'CLP')).upper()
                            e_moneda = em_col1.selectbox("Moneda", ["CLP", "USD"], index=1 if mon_f_act == "USD" else 0, key=f"e_moneda_{factura_a_editar}")
                            monto_val = row_edit.get('Monto', 0)
                            e_monto = em_col2.number_input("Monto Neto", min_value=0, value=int(monto_val) if pd.notna(monto_val) else 0, step=100 if e_moneda == "USD" else 1000)
                            
                            prog_val = row_edit.get('dias_programados', row_edit.get('Dias_Programados', 0.0))
                            e_dias_prog = st.number_input("Días Programados", min_value=0.0, value=float(prog_val) if pd.notna(prog_val) else 0.0, step=1.0)
                            
                            real_val = row_edit.get('dias_reales', row_edit.get('Dias_Reales', 0.0))
                            e_dias_real = st.number_input("Días Reales", min_value=0.0, value=float(real_val) if pd.notna(real_val) else 0.0, step=1.0)

                        with e_col2:
                            estado_actual = str(row_edit.get('Estado', 'PENDIENTE'))
                            opts_estado = ["PENDIENTE", "Pagado", "Esperando OC", "Servicio Ejecutado"]
                            if estado_actual not in opts_estado:
                                opts_estado.append(estado_actual)
                            idx_est = opts_estado.index(estado_actual)
                            e_estado_pago = st.selectbox("Estado de Pago", opts_estado, index=idx_est, key=f"e_estado_pago_select_{factura_a_editar}")
                            
                            e_f_cot = st.date_input("Fecha Cotización", value=safe_date_val(row_edit.get('Fecha_Cotizacion')), key=f"e_fcot_{factura_a_editar}")
                            e_f_oc = st.date_input("Fecha Orden de Compra", value=safe_date_val(row_edit.get('Fecha_OC')), key=f"e_foc_{factura_a_editar}")
                            e_f_emi = st.date_input("Fecha Emisión", value=safe_date_val(row_edit.get('Fecha_Emision')), key=f"e_femi_{factura_a_editar}")
                            e_f_venc = st.date_input("Fecha Vencimiento", value=safe_date_val(row_edit.get('Fecha_Vencimiento')), key=f"e_fvenc_{factura_a_editar}")
                            
                            req_ges_act = str(row_edit.get('Requiere_GES', 'No'))
                            idx_ges = 1 if req_ges_act == "Sí" else 0
                            e_req_ges = st.selectbox("¿Requiere GES?", ["No", "Sí"], index=idx_ges, key=f"e_req_ges_select_{factura_a_editar}")
                            e_f_ges = st.date_input("Fecha GES (si aplica)", value=safe_date_val(row_edit.get('Fecha_GES')), key=f"e_fges_{factura_a_editar}")
                            
                            e_f_pago = st.date_input("Fecha de Pago", value=safe_date_val(row_edit.get('Fecha_Pago')), key=f"e_fpago_{factura_a_editar}")

                        if st.form_submit_button("💾 Actualizar Factura en Supabase"):
                            f_cot_final = str(e_f_cot) if e_f_cot else safe_date_str(row_edit.get('Fecha_Cotizacion'))
                            f_oc_final = str(e_f_oc) if e_f_oc else safe_date_str(row_edit.get('Fecha_OC'))
                            f_emi_final = str(e_f_emi) if e_f_emi else safe_date_str(row_edit.get('Fecha_Emision'))
                            f_venc_final = str(e_f_venc) if e_f_venc else safe_date_str(row_edit.get('Fecha_Vencimiento'))
                            f_ges_final = str(e_f_ges) if e_f_ges else safe_date_str(row_edit.get('Fecha_GES'))
                            f_pago_final = str(e_f_pago) if e_f_pago else safe_date_str(row_edit.get('Fecha_Pago'))

                            if f_pago_final and pd.notna(pd.to_datetime(f_pago_final, errors='coerce')):
                                dt_p = pd.to_datetime(f_pago_final)
                                anio_val = int(dt_p.year)
                                mes_val = int(dt_p.month)
                            else:
                                anio_val = None
                                mes_val = None

                            registro_actualizado = {
                                "Empresa": e_empresa.strip().upper(),
                                "Planta": e_planta.strip().upper() if e_planta else "SIN PLANTA",
                                "Grupo_Servicio": e_grupo_servicio.upper(),
                                "Servicio": e_servicio_detalle.strip().upper() if e_servicio_detalle else "SIN DETALLE",
                                "Monto": int(e_monto),
                                "dias_programados": float(e_dias_prog),
                                "dias_reales": float(e_dias_real),
                                "Fecha_Cotizacion": f_cot_final,
                                "Fecha_OC": f_oc_final,
                                "Fecha_Emision": f_emi_final,
                                "Fecha_Vencimiento": f_venc_final,
                                "Fecha_GES": f_ges_final,
                                "Fecha_Pago": f_pago_final,
                                "Estado": e_estado_pago,
                                "Requiere_GES": e_req_ges,
                                "Ano": anio_val,
                                "Mes": mes_val
                            }

                            try:
                                supabase.table("ingresos").update(registro_actualizado).eq("Factura", str(factura_a_editar)).execute()
                                st.success(f"¡Factura #{factura_a_editar} actualizada exitosamente!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al actualizar la factura en Supabase: {e}")
            else:
                st.info("No hay facturas registradas para editar.")

        with st.expander("🗑 Eliminar Factura"):
            if not df.empty and 'Factura' in df.columns:
                facturas_del_list = sorted(df['Factura'].astype(str).unique().tolist())
                factura_a_eliminar = st.selectbox("Selecciona el Número de Factura a Eliminar:", facturas_del_list, key="select_factura_del")
                
                if factura_a_eliminar:
                    row_f_del = df[df['Factura'].astype(str) == str(factura_a_eliminar)].iloc[0]
                    st.warning(f"⚠️ ¿Estás seguro de que deseas eliminar permanentemente la Factura N° **#{factura_a_eliminar}** de la empresa **{row_f_del.get('Empresa', 'N/A')}**?")
                    
                    if st.button(f"🔥 Confirmar y Eliminar Factura #{factura_a_eliminar}", key="btn_confirm_del_factura"):
                        if eliminar_factura(factura_a_eliminar):
                            st.success(f"Factura #{factura_a_eliminar} eliminada exitosamente de Supabase.")
                            st.rerun()
            else:
                st.info("No hay facturas registradas para eliminar.")

        st.divider()

        if 'Fecha_Vencimiento' in df.columns:
            df['Semáforo'] = df.apply(calcular_semaforo_avanzado, axis=1)
        else:
            df['Semáforo'] = 'Sin Fecha Vencimiento'

        st.subheader("📊 Historial General de Facturas")
          
        df['Estado'] = df['Fecha_Pago'].apply(lambda x: 'Pagado' if pd.notna(x) else 'PENDIENTE')
          
        if not df.empty:
            st.write("### 🔍 Detalle Extendido por Factura")
            lista_facturas = df['Factura'].astype(str).tolist() if 'Factura' in df.columns else []
            if lista_facturas:
                factura_seleccionada = st.selectbox("Selecciona una factura del historial para ver su información detallada:", lista_facturas)
                 
                row_det = df[df['Factura'].astype(str) == str(factura_seleccionada)].iloc[0]
                 
                d_prog = row_det.get('dias_programados', 0)
                if pd.isna(d_prog):
                    d_prog = row_det.get('Dias_Programados', 0)
                d_prog = float(d_prog) if pd.notna(d_prog) else 0.0

                d_real = row_det.get('dias_reales', 0)
                if pd.isna(d_real):
                    d_real = row_det.get('Dias_Reales', 0)
                d_real = float(d_real) if pd.notna(d_real) else 0.0

                desviacion = d_real - d_prog
                 
                f_emi_val = row_det.get('Fecha_Emision')
                f_pago_val = row_det.get('Fecha_Pago')
                dias_cobro = (pd.to_datetime(f_pago_val) - pd.to_datetime(f_emi_val)).days if pd.notna(f_emi_val) and pd.notna(f_pago_val) else "N/A"
                
                mon_str = str(row_det.get('Moneda', 'CLP')).upper()
                simb_str = "$" if mon_str == "CLP" else "US$"
                monto_det_str = f"{simb_str}{int(row_det.get('Monto', 0)):,.0f}".replace(",", ".")
                
                with st.expander(f"📂 Información Detallada: Factura #{row_det.get('Factura', 'N/A')} - {row_det.get('Empresa', 'N/A')}", expanded=True):
                    dc1, dc2, dc3 = st.columns(3)
                     
                    with dc1:
                        st.markdown(f"**Empresa:** {row_det.get('Empresa', 'N/A')}")
                        st.markdown(f"**Planta:** {row_det.get('Planta', 'N/A')}")
                        st.markdown(f"**Grupo de Servicio:** {row_det.get('Grupo Servicio', 'N/A')}")
                        st.markdown(f"**Servicio Entregado:** {row_det.get('Servicio', 'N/A')}")
                        st.markdown(f"**Monto Neto:** {monto_det_str} ({mon_str})")
                        st.markdown(f"**Días Programados:** {d_prog}")
                        st.markdown(f"**Días Reales:** {d_real}")
                        st.markdown(f"**Desviación de Ejecución:** {desviacion:+g} días")
                         
                    with dc2:
                        st.markdown(f"**Fecha Cotización:** {str(row_det.get('Fecha_Cotizacion', 'N/A')).split(' ')[0]}")
                        st.markdown(f"**Fecha Orden de Compra (OC):** {str(row_det.get('Fecha_OC', 'N/A')).split(' ')[0]}")
                        st.markdown(f"**Fecha Emisión:** {str(row_det.get('Fecha_Emision', 'N/A')).split(' ')[0]}")
                        st.markdown(f"**Fecha de Vencimiento:** {str(row_det.get('Fecha_Vencimiento', 'N/A')).split(' ')[0]}")
                         
                    with dc3:
                        f_pago_str = str(f_pago_val).split(' ')[0] if pd.notna(f_pago_val) else "Pendiente de pago"
                        st.markdown(f"**Fecha de Pago:** {f_pago_str}")
                        st.markdown(f"**Días en Cobrar (desde Emisión):** {dias_cobro}")
                        st.markdown(f"**Semáforo:** {row_det.get('Semáforo', 'N/A')}")
                        st.markdown(f"**¿Requiere GES?:** {row_det.get('Requiere_GES', 'No')}")
                        f_ges_val = row_det.get('Fecha_GES')
                        f_ges_str = str(f_ges_val).split(' ')[0] if pd.notna(f_ges_val) else "N/A / No aplica"
                        st.markdown(f"**Fecha GES:** {f_ges_str}")

            st.divider()

            st.write("### 📋 Listado General Preliminar")
            columnas_esenciales = [col for col in ['Factura', 'Empresa', 'Planta', 'Moneda', 'Monto', 'Estado'] if col in df.columns]
             
            configuracion_columnas = {
                "Monto": st.column_config.NumberColumn(
                    "Monto Neto",
                    format="%d"
                ),
                "Estado": st.column_config.SelectboxColumn(
                    "Estado del Servicio/Cobro",
                    options=["Esperando OC", "Servicio Ejecutado", "Pagado", "PENDIENTE"],
                    required=True,
                )
            }
           
            df_editado = st.data_editor(
                df[columnas_esenciales],
                column_config=configuracion_columnas,
                use_container_width=True,
                hide_index=True
            )

            if st.button("💾 Guardar cambios de estados en la Nube"):
                for idx, row in df_editado.iterrows():
                    fac_num = str(row['Factura'])
                    nuevo_est = row['Estado']
                    try:
                        supabase.table("ingresos").update({"Estado": nuevo_est}).eq("Factura", fac_num).execute()
                    except Exception as e:
                        st.error(f"Error al actualizar factura {fac_num}: {e}")
                st.success("¡Estados actualizados exitosamente en Supabase!")
                st.session_state["active_tab"] = 4
                st.rerun()

        st.divider()

    # =========================================================================
    # SECCIÓN: EMBUDO DE VENTAS Y MÓDULO UNIVERSAL DE SOPORTE Y TICKETS
    # =========================================================================
    with tab5:
        st.header("🔥 Embudo de Ventas y Métricas Comerciales")

        if 'Bitacora' not in df_contactos.columns:
            df_contactos['Bitacora'] = ""

        estados = ["Prospecto", "Contactado", "Propuesta", "Ganado", "Perdido"]

        st.subheader("📈 Indicadores Clave de Rendimiento (KPIs Comerciales)")
          
        total_contactos = len(df_contactos)
        total_ganados = len(df_contactos[df_contactos['Estado'] == 'Ganado']) if total_contactos > 0 else 0
        tasa_conversion = (total_ganados / total_contactos * 100) if total_contactos > 0 else 0
          
        if not df.empty and 'Empresa' in df.columns:
            conteo_por_empresa = df['Empresa'].value_counts()
            clientes_recurrentes = len(conteo_por_empresa[conteo_por_empresa > 1])
            total_empresas = len(conteo_por_empresa)
            tasa_retencion = (clientes_recurrentes / total_empresas * 100) if total_empresas > 0 else 0
            pct_clientes_rec = tasa_retencion
              
            conteo_servicios = df['Servicio'].value_counts() if 'Servicio' in df.columns else pd.Series(dtype=int)
            servicios_recurrentes = len(conteo_servicios[conteo_servicios > 1])
            total_servicios_unicos = len(conteo_servicios)
            pct_servicios_rec = (servicios_recurrentes / total_servicios_unicos * 100) if total_servicios_unicos > 0 else 0
        else:
            tasa_retencion = 0.0
            pct_clientes_rec = 0.0
            pct_servicios_rec = 0.0

        promedio_dias_respuesta = 0.0
        if not df_interacciones.empty:
            try:
                temp_int = df_interacciones.copy()
                temp_int['Fecha_DT'] = pd.to_datetime(temp_int['Fecha'], errors='coerce')
                temp_int = temp_int.sort_values(by=['Nombre_Contacto', 'Fecha_DT'])
                diferencias_resp = temp_int.groupby('Nombre_Contacto')['Fecha_DT'].diff().dt.days.dropna()
                if not diferencias_resp.empty:
                    promedio_dias_respuesta = diferencias_resp.mean()
            except:
                promedio_dias_respuesta = 0.0

        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
        kpi1.metric("Tasa de Conversión", f"{tasa_conversion:.1f}%")
        kpi2.metric("Tasa de Retención", f"{tasa_retencion:.1f}%")
        kpi3.metric("Clientes Recurrentes", f"{pct_clientes_rec:.1f}%")
        kpi4.metric("Servicios Recurrentes", f"{pct_servicios_rec:.1f}%")
        kpi5.metric("Tiempo de Respuesta", f"{promedio_dias_respuesta:.1f} días")

        st.divider()

        with st.expander("➕ Crear Nuevo Contacto (Manual)", expanded=False):
            with st.form("form_contacto_unificado"):
                c1, c2 = st.columns(2)
                nombre = c1.text_input("Nombre completo *")
                empresa = c2.text_input("Empresa *")
                planta = c1.text_input("Planta")
                correo = c2.text_input("Correo electrónico *")
                celular = c1.text_input("Celular")
                estado = c2.selectbox("Estado del Cliente", estados)
                rol = c1.selectbox("Rol en la Cuenta", ["Tomador de Decisiones (CEO/Gerente)", "Influenciador", "Técnico / Operativo", "Finanzas / Compras"])
                valor = c2.number_input("Valor", min_value=0, step=1000, value=0)

                submitted = st.form_submit_button("💾 Guardar Registro (Sincronizado a Nube)")

                if submitted:
                    if nombre and correo and empresa:
                        guardar_contacto(nombre, correo, estado, celular, empresa, planta, valor, rol)
                        st.success(f"¡Cliente {nombre} registrado exitosamente en la nube!")
                        st.session_state["active_tab"] = 5
                        st.rerun()
                    else:
                        st.warning("Por favor completa los campos obligatorios (*).")
      
        st.divider()

        st.subheader("📊 Gráfico de Conversión de Oportunidades")
        conteo_estados = df_contactos['Estado'].value_counts().reindex(estados).fillna(0).reset_index()
        conteo_estados.columns = ['Etapa', 'Cantidad']

        fig_funnel = px.funnel(
            conteo_estados,
            x='Cantidad',
            y='Etapa',
            title="Distribución de Oportunidades por Fase"
        )
        st.plotly_chart(fig_funnel, use_container_width=True)
        st.divider()

        st.subheader("📌 Tablero de Contactos por Etapa del Embudo (Edición Directa)")
        cols = st.columns(5)
       
        for i, col in enumerate(cols):
            with col:
                st.subheader(estados[i])
                contactos_estado = df_contactos[df_contactos["Estado"] == estados[i]]
                for idx, row in contactos_estado.iterrows():
                    monto_val_row = f"${int(row.get('Valor', 0)):,.0f}".replace(",", ".")
                    st.write(f"👤 **{row.get('Nombre', 'Sin Nombre')}**")
                    st.write(f"🏢 Empresa: {row.get('Empresa', 'N/A')}")
                    if row.get('Planta'):
                        st.write(f"🏭 Planta: {row.get('Planta')}")
                    st.write(f"💼 Rol: **{row.get('Rol_Contacto', 'Influenciador')}**")
                    st.write(f"💰 Valor: {monto_val_row}")
                   
                    correo_contacto = row.get('Correo', row.get('email', ''))
                    nombre_contacto = row.get('Nombre', 'Cliente')
                   
                    if pd.notna(correo_contacto) and str(correo_contacto).strip() != "":
                        asunto = f"Seguimiento de Propuesta / Proyecto - Itelcam"
                        cuerpo = f"Hola {nombre_contacto},\n\nEspero que te encuentres muy bien. Te escribo para hacer un breve seguimiento de nuestra propuesta y ver cómo podemos avanzar.\n\nQuedo atento a tus comentarios.\n\nSaludos cordiales,"
                       
                        import urllib.parse
                        asunto_enc = urllib.parse.quote(asunto)
                        cuerpo_enc = urllib.parse.quote(cuerpo)
                       
                        mailto_link = f"mailto:{correo_contacto}?subject={asunto_enc}&body={cuerpo_enc}"
                       
                        st.markdown(
                            f"""
                            <a href="{mailto_link}" target="_blank" style="display:inline-block; padding:6px 12px; margin:4px 0px; font-size:12px; color:white; background-color:#2563eb; text-align:center; text-decoration:none; border-radius:4px; font-weight:600;">
                                ✉ Enviar Correo
                            </a>
                            """,
                            unsafe_allow_html=True
                        )
                    else:
                        st.caption("⚠ Sin correo registrado")

                    with st.expander(f"✏️ Editar Tarjeta ({row.get('Nombre', 'Contacto')})"):
                        with st.form(f"form_quick_edit_card_{idx}"):
                            qe_nombre = st.text_input("Nombre", value=str(row.get('Nombre', '')))
                            qe_empresa = st.text_input("Empresa", value=str(row.get('Empresa', '')))
                            qe_planta = st.text_input("Planta", value=str(row.get('Planta', '')))
                            qe_correo = st.text_input("Correo", value=str(correo_contacto))
                            qe_celular = st.text_input("Celular", value=str(row.get('Celular', '')))
                            
                            roles_op = ["Tomador de Decisiones (CEO/Gerente)", "Influenciador", "Técnico / Operativo", "Finanzas / Compras"]
                            rol_act = str(row.get('Rol_Contacto', 'Influenciador'))
                            idx_rol = roles_op.index(rol_act) if rol_act in roles_op else 1
                            qe_rol = st.selectbox("Rol", roles_op, index=idx_rol)
                            
                            qe_valor = st.number_input("Valor", value=int(row.get('Valor', 0)) if pd.notna(row.get('Valor')) else 0, min_value=0, step=1000)
                            
                            idx_est_card = estados.index(row['Estado']) if row['Estado'] in estados else 0
                            qe_estado = st.selectbox("Etapa / Estado", estados, index=idx_est_card)
                            
                            if st.form_submit_button("💾 Guardar Cambios"):
                                guardar_contacto(
                                    nombre=qe_nombre,
                                    email=qe_correo,
                                    estado=qe_estado,
                                    telefono=qe_celular,
                                    empresa=qe_empresa,
                                    planta=qe_planta,
                                    valor=qe_valor,
                                    rol=qe_rol,
                                    bitacora=str(row.get('Bitacora', ''))
                                )
                                st.success("¡Tarjeta actualizada en la nube!")
                                st.session_state["active_tab"] = 5
                                st.rerun()

                    nota_actual = row.get('Bitacora', '')
                    if pd.isna(nota_actual):
                        nota_actual = ""
                       
                    with st.expander(f"📝 Bitácora ({row.get('Nombre', 'Contacto')})"):
                        nueva_nota = st.text_area(
                            "Resumen de llamada/reunión:",
                            value=nota_actual,
                            key=f"bitacora_txt_{idx}"
                        )

                        with st.form(f"form_interaccion_{idx}"):
                            st.write("Registrar Evento en Línea de Tiempo")
                            tipo_inter = st.selectbox("Tipo de Interacción", ["Llamada Telefónica", "Reunión", "Correo Electrónico", "WhatsApp"], key=f"tipo_int_{idx}")
                            detalle_inter = st.text_input("Breve detalle del avance", key=f"det_int_{idx}")
                           
                            if st.form_submit_button("➕ Añadir a Línea de Tiempo"):
                                if detalle_inter.strip() != "":
                                    guardar_interaccion(
                                        nombre_contacto=row['Nombre'],
                                        empresa=row['Empresa'],
                                        tipo=tipo_inter,
                                        detalle=detalle_inter
                                    )
                                    st.success("¡Interacción registrada en la nube!")
                                    st.rerun()
                                else:
                                    st.warning("Escribe un detalle para la interacción.")
                       
                        if nueva_nota.strip() != "":
                            nota_lower = nueva_nota.lower()
                            if any(w in nota_lower for w in ["excelente", "genial", "interesado", "positivo", "listo", "pagarán", "agendar"]):
                                st.success("😊 Sentimiento detectado en nota: **Positivo / Oportunidad Alta**")
                            elif any(w in nota_lower for w in ["problema", "caro", "retraso", "molesto", "duda", "cancelar", "esperar"]):
                                st.warning("⚠️ Sentimiento detectado en nota: **Riesgo / Requiere Atención**")
                            else:
                                st.info("ℹ️ Sentimiento detectado en nota: **Neutral**")

                        col_b1, col_b2 = st.columns(2)
                        with col_b1:
                            if st.button("💾 Guardar", key=f"btn_bitacora_{idx}"):
                                guardar_contacto(
                                    nombre=row['Nombre'],
                                    email=correo_contacto,
                                    estado=row['Estado'],
                                    telefono=row.get('Celular', ''),
                                    empresa=row.get('Empresa', ''),
                                    planta=row.get('Planta', ''),
                                    valor=row.get('Valor', 0),
                                    rol=row.get('Rol_Contacto', 'Influenciador'),
                                    bitacora=nueva_nota
                                )
                                guardar_interaccion(
                                    nombre_contacto=row['Nombre'],
                                    empresa=row['Empresa'],
                                    tipo="Nota / Bitácora",
                                    detalle=nueva_nota[:80] + "..."
                                )
                                st.success("¡Bitácora sincronizada en Supabase!")
                                st.rerun()
                        with col_b2:
                            nuevo_estado_rapido = st.selectbox("Mover:", estados, index=estados.index(row['Estado']) if row['Estado'] in estados else 0, key=f"mov_{idx}")
                            if nuevo_estado_rapido != row['Estado']:
                                guardar_contacto(
                                    nombre=row['Nombre'],
                                    email=correo_contacto,
                                    estado=nuevo_estado_rapido,
                                    telefono=row.get('Celular', ''),
                                    empresa=row.get('Empresa', ''),
                                    planta=row.get('Planta', ''),
                                    valor=row.get('Valor', 0),
                                    rol=row.get('Rol_Contacto', 'Influenciador'),
                                    bitacora=nota_actual
                                )
                                st.rerun()

                    with st.expander(f"⏱ Línea de Tiempo ({row.get('Nombre', 'Contacto')})"):
                        filtro_inter = df_interacciones[df_interacciones['Nombre_Contacto'] == row.get('Nombre')]
                        if not filtro_inter.empty:
                            for _, inter_row in filtro_inter.iterrows():
                                st.caption(f"[{inter_row['Fecha']}] **{inter_row['Tipo']}**: {inter_row['Detalle']}")
                        else:
                            st.caption("No hay interacciones registradas aún.")

                    if st.button("🗑️ Borrar", key=f"del_{idx}"):
                        eliminar_contacto(correo_contacto)
                        st.session_state["active_tab"] = 5
                        st.rerun()

        st.divider()

        st.subheader("🎯 Calificación de Prospectos (Lead Scoring)")
       
        def calcular_lead_scoring(row):
            score_valor = 0
            score_velocidad = 0
           
            valor = row.get('Valor', 0)
            if valor >= 3000000:
                score_valor = 50
            elif valor >= 1500000:
                score_valor = 40
            elif valor >= 800000:
                score_valor = 30
            elif valor >= 400000:
                score_valor = 15
            else:
                score_valor = 5
               
            nombre_c = row.get('Nombre', '')
            interacciones_contacto = df_interacciones[df_interacciones['Nombre_Contacto'] == nombre_c]
           
            if not interacciones_contacto.empty and len(interacciones_contacto) >= 2:
                try:
                    interacciones_contacto['Fecha_DT'] = pd.to_datetime(interacciones_contacto['Fecha'], errors='coerce')
                    interacciones_contacto = interacciones_contacto.sort_values(by='Fecha_DT')
                    diferencias = interacciones_contacto['Fecha_DT'].diff().dt.days.dropna()
                   
                    if not diferencias.empty:
                        promedio_dias_respuesta = diferencias.mean()
                        if promedio_dias_respuesta <= 2:
                            score_velocidad = 50
                        elif promedio_dias_respuesta <= 5:
                            score_velocidad = 35
                        elif promedio_dias_respuesta <= 10:
                            score_velocidad = 20
                        else:
                            score_velocidad = 5
                    else:
                        score_velocidad = 25
                except:
                    score_velocidad = 25
            else:
                score_velocidad = 15
               
            puntaje_total = score_valor + score_velocidad
           
            if puntaje_total >= 70:
                return pd.Series([puntaje_total, "🔥 Lead Caliente (Alta Prioridad)"])
            elif puntaje_total >= 40:
                return pd.Series([puntaje_total, "⚡ Lead Tibio (Seguimiento Activo)"])
            else:
                return pd.Series([puntaje_total, "❄️ Lead Frío (Bajo Interés / Lento)"])

        if not df_contactos.empty:
            df_contactos[['Lead_Score', 'Temperatura_Lead']] = df_contactos.apply(calcular_lead_scoring, axis=1)
        else:
            df_contactos['Lead_Score'] = 0
            df_contactos['Temperatura_Lead'] = "❄ Lead Frío"

        col_sc1, col_sc2 = st.columns(2)
        with col_sc1:
            st.write("### 🌡️ Clasificación de Prospectos por Temperatura")
            conteo_temp = df_contactos['Temperatura_Lead'].value_counts().reset_index()
            conteo_temp.columns = ['Temperatura', 'Cantidad']
            st.dataframe(conteo_temp, hide_index=True, use_container_width=True)
        with col_sc2:
            st.write("### 📋 Top Prospectos con mayor score")
            st.dataframe(df_contactos[['Nombre', 'Empresa', 'Lead_Score', 'Temperatura_Lead', 'Valor']].sort_values(by='Lead_Score', ascending=False).head(5), hide_index=True, use_container_width=True)

        st.divider()

        st.subheader("💰 Pronóstico de Ingresos (Forecast)")
        probabilidades = {
            "Prospecto": 0.10,
            "Contactado": 0.25,
            "Propuesta": 0.50,
            "Ganado": 1.00,
            "Perdido": 0.00
        }
        df_contactos['Probabilidad'] = df_contactos['Estado'].map(probabilidades).fillna(0.10)
        df_contactos['Valor_Ponderado'] = df_contactos['Valor'] * df_contactos['Probabilidad']

        total_pipeline = int(df_contactos[df_contactos['Estado'] != 'Perdido']['Valor'].sum())
        forecast_ponderado = int(round(df_contactos['Valor_Ponderado'].sum()))

        col_f1, col_f2 = st.columns(2)
        col_f1.metric("Valor Total en Pipeline Activo", f"${total_pipeline:,.0f}".replace(",", "."))
        col_f2.metric("Forecast Ponderado (Proyección Real)", f"${forecast_ponderado:,.0f}".replace(",", "."))

        st.divider()

        st.subheader("📥 Exportar Datos Comerciales")
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_contactos.to_excel(writer, index=False, sheet_name='Embudo_Contactos')
        excel_data = output.getvalue()

        st.download_button(
            label="📊 Descargar Base de Contactos y Bitácoras (Excel)",
            data=excel_data,
            file_name="Embudo_Ventas_Itelcam.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheet.sheet"
        )

        st.divider()

        # =====================================================================
        # MÓDULO UNIVERSAL DE SOPORTE Y TICKETS (CREAR, EDITAR, ELIMINAR, VINCULAR)
        # =====================================================================
        st.subheader("🛠️ Módulo Universal de Soporte y Tickets (Helpdesk)")
        
        lista_contactos_opciones = ["--- Sin Contacto Específico ---"]
        if not df_contactos.empty:
            for _, r_cont in df_contactos.iterrows():
                n_c = str(r_cont.get('Nombre', '')).strip()
                e_c = str(r_cont.get('Empresa', '')).strip()
                if n_c or e_c:
                    lista_contactos_opciones.append(f"{n_c} ({e_c})")

        with st.expander("➕ Crear Nuevo Ticket de Soporte", expanded=False):
            with st.form("form_ticket_universal", clear_on_submit=True):
                col_tk1, col_tk2 = st.columns(2)
                
                empresas_disp = sorted(df['Empresa'].unique()) if not df.empty else ["EMPRESA GENERAL"]
                
                with col_tk1:
                    tk_empresa = st.selectbox("Empresa del Cliente *", empresas_disp)
                    tk_contacto_sel = st.selectbox("Contacto Asociado (CRM)", lista_contactos_opciones)
                    tk_asunto = st.text_input("Asunto / Problema Técnico *")
                    
                with col_tk2:
                    tk_prioridad = st.selectbox("Prioridad *", ["🟢 Puede Esperar / Baja", "🟡 Media", "🟧 Alta", "🚨 Urgente / Crítica"])
                    tk_estado = st.selectbox("Estado inicial", ["Abierto", "En Proceso", "Cerrado"])
                
                if st.form_submit_button("💾 Crear y Sincronizar Ticket Universal"):
                    if tk_asunto.strip():
                        contacto_final = tk_contacto_sel if tk_contacto_sel != "--- Sin Contacto Específico ---" else f"Contacto General {tk_empresa}"
                        nuevo_id = f"TKT-{len(df_tickets)+1:03d}"
                        
                        dict_tk = {
                            "ID_Ticket": nuevo_id,
                            "Empresa": tk_empresa,
                            "Contacto": contacto_final,
                            "Asunto": tk_asunto.strip(),
                            "Estado": tk_estado,
                            "Prioridad": tk_prioridad,
                            "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "Creado_Por": st.session_state.get('user_email', 'Sistema')
                        }
                        
                        guardar_ticket(dict_tk)
                        st.success(f"¡Ticket #{nuevo_id} registrado y publicado globalmente!")
                        st.rerun()
                    else:
                        st.warning("Escribe un asunto para el ticket.")

        with st.expander("✏️ Editar Ticket Existente", expanded=False):
            if not df_tickets.empty and 'ID_Ticket' in df_tickets.columns:
                lista_ids_tk = sorted(df_tickets['ID_Ticket'].astype(str).unique().tolist())
                id_tk_editar = st.selectbox("Selecciona el ID del Ticket a Modificar:", lista_ids_tk, key="select_tk_edit")
                
                if id_tk_editar:
                    row_tk_edit = df_tickets[df_tickets['ID_Ticket'].astype(str) == str(id_tk_editar)].iloc[0]
                    
                    with st.form(f"form_edit_tk_{id_tk_editar}"):
                        etk_col1, etk_col2 = st.columns(2)
                        
                        empresas_disp = sorted(df['Empresa'].unique()) if not df.empty else ["EMPRESA GENERAL"]
                        idx_emp_tk = empresas_disp.index(row_tk_edit.get('Empresa')) if row_tk_edit.get('Empresa') in empresas_disp else 0
                        
                        with etk_col1:
                            etk_empresa = st.selectbox("Empresa", empresas_disp, index=idx_emp_tk, key=f"e_emp_tk_{id_tk_editar}")
                            
                            cont_act_tk = str(row_tk_edit.get('Contacto', ''))
                            if cont_act_tk and cont_act_tk not in lista_contactos_opciones:
                                lista_contactos_opciones.append(cont_act_tk)
                            idx_cont_tk = lista_contactos_opciones.index(cont_act_tk) if cont_act_tk in lista_contactos_opciones else 0
                            etk_contacto = st.selectbox("Contacto Asociado", lista_contactos_opciones, index=idx_cont_tk, key=f"e_cont_tk_{id_tk_editar}")
                            
                            etk_asunto = st.text_input("Asunto", value=str(row_tk_edit.get('Asunto', '')))

                        with etk_col2:
                            prio_opts = ["🟢 Puede Esperar / Baja", "🟡 Media", "🟧 Alta", "🚨 Urgente / Crítica"]
                            prio_act = str(row_tk_edit.get('Prioridad', '🟡 Media'))
                            idx_prio = prio_opts.index(prio_act) if prio_act in prio_opts else 1
                            etk_prioridad = st.selectbox("Prioridad", prio_opts, index=idx_prio, key=f"e_prio_tk_{id_tk_editar}")
                            
                            est_opts = ["Abierto", "En Proceso", "Cerrado"]
                            est_act = str(row_tk_edit.get('Estado', 'Abierto'))
                            idx_est_tk = est_opts.index(est_act) if est_act in est_opts else 0
                            etk_estado = st.selectbox("Estado", est_opts, index=idx_est_tk, key=f"e_est_tk_{id_tk_editar}")

                        if st.form_submit_button("💾 Guardar Cambios en Ticket"):
                            dict_tk_edit = {
                                "ID_Ticket": str(id_tk_editar),
                                "Empresa": etk_empresa,
                                "Contacto": etk_contacto,
                                "Asunto": etk_asunto.strip(),
                                "Estado": etk_estado,
                                "Prioridad": etk_prioridad,
                                "Fecha": str(row_tk_edit.get('Fecha', datetime.now().strftime("%Y-%m-%d"))),
                                "Creado_Por": str(row_tk_edit.get('Creado_Por', 'Sistema'))
                            }
                            guardar_ticket(dict_tk_edit)
                            st.success(f"¡Ticket #{id_tk_editar} actualizado exitosamente!")
                            st.rerun()
            else:
                st.info("No hay tickets registrados para editar.")

        with st.expander("🗑️ Eliminar Ticket de Soporte", expanded=False):
            if not df_tickets.empty and 'ID_Ticket' in df_tickets.columns:
                lista_del_tk = sorted(df_tickets['ID_Ticket'].astype(str).unique().tolist())
                id_tk_del = st.selectbox("Selecciona el Ticket a Eliminar:", lista_del_tk, key="select_tk_del")
                if id_tk_del:
                    row_tk_d = df_tickets[df_tickets['ID_Ticket'].astype(str) == str(id_tk_del)].iloc[0]
                    st.warning(f"⚠️ ¿Eliminar permanentemente el Ticket **#{id_tk_del}** ({row_tk_d.get('Asunto', 'N/A')})?")
                    if st.button(f"🔥 Confirmar y Eliminar Ticket #{id_tk_del}", key="btn_confirm_del_tk"):
                        eliminar_ticket(id_tk_del)
                        st.success(f"Ticket #{id_tk_del} eliminado correctamente.")
                        st.rerun()
            else:
                st.info("No hay tickets registrados para eliminar.")

        st.divider()

        st.subheader("📋 Tablero Universal de Tickets Registrados")
        if not df_tickets.empty:
            st.dataframe(
                df_tickets[["ID_Ticket", "Empresa", "Contacto", "Asunto", "Prioridad", "Estado", "Fecha", "Creado_Por"]],
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No hay tickets registrados en el sistema.")

        st.divider()

        with st.expander("✏️ Editar contactos existentes"):
            for idx, row in df_contactos.iterrows():
                with st.form(f"edit_{idx}"):
                    st.write(f"Editando: {row['Nombre']}")
                    n_nombre = st.text_input("Nombre", row['Nombre'])
                    n_empresa = st.text_input("Empresa", row['Empresa'])
                    n_planta = st.text_input("Planta", row.get('Planta', ''))
                    n_correo = st.text_input("Correo", row.get('Correo', ''))
                    n_celular = st.text_input("Celular", row.get('Celular', ''))
                    n_estado = st.selectbox("Estado", estados, index=estados.index(row['Estado']) if row['Estado'] in estados else 0)
                    n_rol = st.selectbox("Rol en la Cuenta", ["Tomador de Decisiones (CEO/Gerente)", "Influenciador", "Técnico / Operativo", "Finanzas / Compras"], index=0 if row.get('Rol_Contacto') not in ["Influenciador", "Técnico / Operativo", "Finanzas / Compras"] else ["Tomador de Decisiones (CEO/Gerente)", "Influenciador", "Técnico / Operativo", "Finanzas / Compras"].index(row.get('Rol_Contacto', 'Influenciador')))
                    n_valor = st.number_input("Valor", value=int(row['Valor']) if pd.notna(row['Valor']) else 0, min_value=0, step=1000)
                   
                    if st.form_submit_button("💾 Guardar Cambios"):
                        guardar_contacto(
                            nombre=n_nombre,
                            email=n_correo,
                            estado=n_estado,
                            telefono=n_celular,
                            empresa=n_empresa,
                            planta=n_planta,
                            valor=n_valor,
                            rol=n_rol,
                            bitacora=str(row.get('Bitacora', ''))
                        )
                        st.success("¡Contacto actualizado con éxito en Supabase!")
                        st.session_state["active_tab"] = 5
                        st.rerun()