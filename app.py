import os
import io
import tempfile
from datetime import datetime
import pandas as pd
import plotly.express as px
from fpdf import FPDF
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from supabase import create_client, Client
import streamlit as st

# --- CONFIGURACIÓN ÚNICA AL INICIO ---
st.set_page_config(page_title="Itelcam CRM", layout="wide")

# --- GESTIÓN DE NAVEGACIÓN PERSISTENTE ---
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = 0

# =============================================================================
# 1. FUNCIONES DE BACKEND, BASE DE DATOS Y LÓGICA GLOBALES
# =============================================================================

@st.cache_resource
def init_supabase() -> Client:
    """Inicializa y reutiliza el cliente de Supabase usando credenciales seguras."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

def cargar_contactos():
    """Consulta todos los registros de la tabla 'Contactos' en Supabase."""
    response = supabase.table("Contactos").select("*").execute()
    data = response.data
    return pd.DataFrame(data)

def guardar_contacto(nombre, email, estado, telefono=""):
    """Inserta un nuevo contacto en la base de datos de Supabase."""
    nuevo_registro = {
        "nombre": nombre,
        "email": email,
        "estado": estado,
        "telefono": telefono
    }
    response = supabase.table("Contactos").insert(nuevo_registro).execute()
    return response

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
            return 'Azul/Verde (Al día / Por vencer)'
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

def generar_pdf(df_original):
    df = df_original.dropna(subset=['Fecha_Pago']).copy()
    pdf = FPDF()
    pdf.add_page()
   
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Reporte Ejecutivo CRM Itelcam (Ingresos Reales por Pago)", ln=True, align='C')
    pdf.ln(5)
   
    ingresos_totales = df['Monto'].sum()
    total_clientes = df['Empresa'].nunique() if 'Empresa' in df.columns else len(df)
    ingresos_2025 = df[df['Año'] == 2025]['Monto'].sum() if 'Año' in df.columns else 0
    ingresos_2026 = df[df['Año'] == 2026]['Monto'].sum() if 'Año' in df.columns else 0

    pdf.set_font("Arial", 'B', 11)
    pdf.cell(200, 6, txt=f"Ingresos Totales (Pagados): ${ingresos_totales:,.2f}", ln=True)
    pdf.cell(200, 6, txt=f"Total Clientes: {total_clientes}", ln=True)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(200, 6, txt=f"KPIs Anuales (Según Pago) -> 2025: ${ingresos_2025:,.0f} | 2026: ${ingresos_2026:,.0f}", ln=True)
    pdf.ln(5)

    if 'Mes' in df.columns and 'Año' in df.columns:
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(200, 8, txt="Comparativa Ingresos Reales 2025 vs 2026", ln=True)
       
        plt.figure(figsize=(7, 3.8))
        pivot_df = df.pivot_table(index='Mes', columns='Año', values='Monto', aggfunc='sum').fillna(0)
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
        pdf.cell(200, 7, txt=f"Ingresos Reales por Empresa - Año {anio}", ln=True)
        pdf.image(tmp_path, x=25, w=150)
        os.remove(tmp_path)
        pdf.ln(2)
       
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(200, 5, f"Detalle Empresas ({anio})", ln=True)
        pdf.set_font("Arial", size=8)
        for _, row in empresa_data.iterrows():
            pdf.cell(90, 5, f"{row['Empresa']}: ${row['Monto']:,.0f}", border=1)
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
        pdf.cell(200, 7, txt=f"Mix de Servicios Reales - Año {anio}", ln=True)
        pdf.image(tmp_path, x=20, w=160)
        os.remove(tmp_path)
        pdf.ln(2)
       
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(200, 5, f"Detalle Mix de Servicios ({anio})", ln=True)
        pdf.set_font("Arial", size=8)
        for _, row in servicio_data.iterrows():
            pdf.cell(90, 5, f"{row['Grupo Servicio']}: ${row['Monto']:,.0f}", border=1)
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
    RUTA_MAESTRA = "H:/Ingresos.xlsx" if os.path.exists("H:/Ingresos.xlsx") else "Ingresos.xlsx"
    ARCHIVO_CONTACTOS = "contactos.csv"
    ARCHIVO_TICKETS = "tickets_soporte.csv"
    ARCHIVO_HISTORIAL_INTERACCIONES = "historial_interacciones.csv"

    if not os.path.exists(ARCHIVO_TICKETS):
        pd.DataFrame(columns=["ID_Ticket", "Empresa", "Asunto", "Estado", "Prioridad", "Fecha"]).to_csv(ARCHIVO_TICKETS, index=False)
    df_tickets = pd.read_csv(ARCHIVO_TICKETS)

    if not os.path.exists(ARCHIVO_HISTORIAL_INTERACCIONES):
        pd.DataFrame(columns=["Nombre_Contacto", "Empresa", "Tipo", "Detalle", "Fecha"]).to_csv(ARCHIVO_HISTORIAL_INTERACCIONES, index=False)
    df_interacciones = pd.read_csv(ARCHIVO_HISTORIAL_INTERACCIONES)

    if "log_actividad" not in st.session_state:
        st.session_state["log_actividad"] = []

    def registrar_log(accion):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state["log_actividad"].insert(0, f"[{timestamp}] - {st.session_state.get('user_email', 'Sistema')}: {accion}")

    with st.sidebar:
        st.write(f"**Usuario:** {st.session_state['user_email']}")
        st.write(f"**Rol:** {st.session_state['role'].upper()}")
        st.write("---")
       
        if os.path.exists(RUTA_MAESTRA):
            df_pdf = pd.read_excel(RUTA_MAESTRA)
            st.download_button("📥 Descargar Reporte PDF", data=generar_pdf(df_pdf), file_name="CRM_Itelcam.pdf", mime="application/pdf")

        if st.button("🔄 Sincronizar Excel"):
            st.cache_data.clear()
            registrar_log("Sincronización de Excel realizada")
            st.success("¡Datos sincronizados desde la unidad H:!")
            st.rerun()
       
        if st.button("🚪 Cerrar Sesión"):
            st.session_state["logged_in"] = False
            st.rerun()

    # --- TÍTULO PRINCIPAL DEL DASHBOARD ---
    st.title("🚀 CRM Itelcam - Gestión Estratégica")

    # --- CARGA DE DATOS LOCALES EXCEL / CSV ---
    @st.cache_data
    def cargar_datos():
        df = pd.read_excel(RUTA_MAESTRA)
        df.columns = df.columns.str.strip()
        
        # --- LIMPIEZA ROBUSTA DE MONTO ---
        if 'Monto' in df.columns:
            if df['Monto'].dtype == object or str(df['Monto'].dtype).startswith('string'):
                df['Monto'] = (
                    df['Monto'].astype(str)
                    .str.replace('$', '', regex=False)
                    .str.replace('.', '', regex=False)
                    .str.replace(',', '.', regex=False)
                    .str.strip()
                )
            df['Monto'] = pd.to_numeric(df['Monto'], errors='coerce').fillna(0.0)
        else:
            df['Monto'] = 0.0
        # ---------------------------------
        
        # Conversión de fechas
        df['Fecha_Cotizacion'] = pd.to_datetime(df.get('Fecha_Cotizacion'), errors='coerce')
        df['Fecha_OC'] = pd.to_datetime(df.get('Fecha_OC'), errors='coerce')
        df['Fecha_Emision'] = pd.to_datetime(df.get('Fecha_Emision'), errors='coerce')
        df['Fecha_GES'] = pd.to_datetime(df.get('Fecha_GES'), errors='coerce')
        df['Fecha_Pago'] = pd.to_datetime(df.get('Fecha_Pago'), errors='coerce')
        df['Fecha_Vencimiento'] = pd.to_datetime(df.get('Fecha_Vencimiento'), errors='coerce')
        
        # Sincronización automática del estado según la fecha de pago
        if 'Fecha_Pago' in df.columns:
            if 'Estado' not in df.columns:
                df['Estado'] = 'PENDIENTE'
            df['Estado'] = df['Fecha_Pago'].apply(lambda x: 'Pagado' if pd.notna(x) else 'PENDIENTE')
            df.to_excel(RUTA_MAESTRA, index=False)
        
        df['Año'] = df['Fecha_Pago'].dt.year.fillna(0).astype(int)
        df['Mes'] = df['Fecha_Pago'].dt.month

        df['Empresa'] = df['Empresa'].astype(str).str.strip().str.upper()
        df['Planta'] = df['Planta'].fillna('SIN PLANTA').astype(str).str.strip().str.upper()
        df['Grupo Servicio'] = df['Grupo Servicio'].fillna('SIN SERVICIO').astype(str).str.strip().str.upper()
        df['Servicio'] = df['Servicio'].fillna('SIN DETALLE').astype(str).str.strip().str.upper()
        
        if 'Factura' in df.columns:
            df['Factura_Num'] = pd.to_numeric(df['Factura'], errors='coerce')
            df = df.sort_values(by=['Factura_Num', 'Factura'], ascending=[False, False]).drop(columns=['Factura_Num'])
            
        return df
   
    if not os.path.exists(ARCHIVO_CONTACTOS):
        pd.DataFrame(columns=["Nombre", "Empresa", "Planta", "Correo", "Celular", "Estado", "Valor", "Rol_Contacto"]).to_csv(ARCHIVO_CONTACTOS, index=False)
    
    # Manejo de contactos local (CSV para tab 5)
    df_contactos = pd.read_csv(ARCHIVO_CONTACTOS, dtype={"Bitacora": str, "Nombre": str, "Empresa": str, "Planta": str, "Correo": str, "Celular": str, "Estado": str, "Rol_Contacto": str})
   
    if 'Rol_Contacto' not in df_contactos.columns:
        df_contactos['Rol_Contacto'] = 'Influenciador'
        df_contactos.to_csv(ARCHIVO_CONTACTOS, index=False)

    df = cargar_datos()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Dashboard", "🏢 Gestión por Planta", "📈 Análisis Estratégico", "➕ Gestión de Facturas y Ciclo de Pago", "🔥 Embudo Ventas"])
   
    with tab1:
        st.info("💡 **Nota Financiera:** Todos los ingresos, gráficos y métricas mostrados a continuación reflejan exclusivamente los montos correspondientes a su **fecha de pago efectiva**.")
          
        st.subheader("🔔 Alertas de Renovación y Vencimientos Anuales")
        if 'Fecha_Vencimiento' in df.columns:
            hoy_alerta = pd.Timestamp(datetime.now().date())
            df_por_vencer = df[df['Fecha_Pago'].isna() & df['Fecha_Vencimiento'].notna()].copy()
            if not df_por_vencer.empty:
                df_por_vencer['Dias_Restantes'] = (df_por_vencer['Fecha_Vencimiento'] - hoy_alerta).dt.days
                df_proximos = df_por_vencer[(df_por_vencer['Dias_Restantes'] >= 0) & (df_por_vencer['Dias_Restantes'] <= 30)]
                if not df_proximos.empty:
                    st.warning(f"⚠️ Hay **{len(df_proximos)} contratos/facturas** que vencen en los próximos 30 días. ¡Contacta al cliente para asegurar la renovación!")
                    st.dataframe(df_proximos[['Empresa', 'Planta', 'Factura', 'Monto', 'Fecha_Vencimiento', 'Dias_Restantes']], hide_index=True)
                else:
                    st.info("No hay vencimientos críticos en los próximos 30 días.")

        st.divider()

        st.subheader("🛠️ Estado de Soporte Técnico")
        if not df_tickets.empty:
            tickets_abiertos = df_tickets[df_tickets['Estado'] != 'Cerrado']
            k_t1, k_t2 = st.columns(2)
            k_t1.metric("Tickets Activos / Abiertos", len(tickets_abiertos))
            k_t2.metric("Total Histórico de Tickets", len(df_tickets))
            if not tickets_abiertos.empty:
                with st.expander("Ver detalle de tickets abiertos"):
                    st.dataframe(tickets_abiertos, hide_index=True)
        else:
            st.info("No hay tickets de soporte registrados.")

        st.divider()

        if 'Fecha_Vencimiento' in df.columns:
            df['Semáforo'] = df.apply(calcular_semaforo_avanzado, axis=1)
        else:
            df['Semáforo'] = 'Sin Fecha Vencimiento'
           
        st.subheader("🚨 Alertas de Cobranza Urgentes")
        df_criticos = df[df['Semáforo'].str.contains('Rojo|Amarillo', na=False)]
        if not df_criticos.empty:
            st.warning(f"Tienes **{len(df_criticos)} documentos** que requieren gestión de cobranza inmediata.")
            with st.expander("Ver detalle de alertas pendientes"):
                st.dataframe(df_criticos[['Empresa', 'Planta', 'Factura', 'Monto', 'Fecha_Vencimiento', 'Semáforo']], hide_index=True)
        else:
            st.success("🎉 ¡Excelente! No hay documentos críticos ni vencidos en este momento.")

        st.divider()

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
                        respuesta_ia = f"📊 **Análisis Local (Por Fecha de Pago):** Los ingresos reales pagados durante el año 2026 ascienden a ${total_2026_val:,.0f}, comparados con ${total_2025_val:,.0f} en 2025."
                    elif "cliente" in query_lower or "empresa" in query_lower:
                        top_empresa = df[df['Año'] == 2026].groupby('Empresa')['Monto'].sum().idxmax() if not df[df['Año'] == 2026].empty else "N/A"
                        respuesta_ia = f"🏢 **Análisis Local:** La empresa con mayor aportación de ingresos reales (pagados) durante el 2026 es **{top_empresa}**."
                    else:
                        respuesta_ia = f"🤖 **Respuesta Local (VS Code):** He procesado tu consulta ('{user_query}'). Te sugiero revisar el panel de KPIs ejecutivos y el desglose de ingresos reales por planta."
                   
                    st.write("### Respuesta de la IA:")
                    st.write(respuesta_ia)
            else:
                st.warning("Por favor, escribe una pregunta.")

        st.subheader("📊 Resumen Ejecutivo de Ingresos Reales (KPIs)")
        total_2026 = df[df['Año'] == 2026]['Monto'].sum()
        total_2025 = df[df['Año'] == 2025]['Monto'].sum()
        variacion = ((total_2026 - total_2025) / total_2025 * 100) if total_2025 != 0 else 0
        ticket_promedio = df[df['Año'] == 2026]['Monto'].mean() if not df[df['Año'] == 2026].empty else 0
        top_cliente = df[df['Año'] == 2026].groupby('Empresa')['Monto'].sum().idxmax() if not df[df['Año'] == 2026].empty else "N/A"
          
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Ingresos Pagados 2026", f"${total_2026:,.0f}")
        k2.metric("Crecimiento vs 2025", f"{variacion:,.1f}%", delta=f"{variacion:,.1f}%")
        k3.metric("Ticket Promedio Pagado", f"${ticket_promedio:,.0f}")
        k4.metric("Top Cliente Pagado 2026", top_cliente)    
        st.divider()
          
        st.subheader("Ingresos Reales Totales: Comparativa 2025 vs 2026 (Por Fecha de Pago)")
        tendencia = df[df['Año'].isin([2025, 2026])].groupby(['Año', 'Mes'])['Monto'].sum().reset_index()
        fig_line = px.line(tendencia, x='Mes', y='Monto', color='Año', markers=True, labels={'Monto': 'Monto Pagado ($)'})
        st.plotly_chart(fig_line, use_container_width=True)
          
        st.subheader("Mix de Servicios Reales Comparativo")
        c1, c2 = st.columns(2)
        for anio, col in zip([2025, 2026], [c1, c2]):
            with col:
                st.write(f"### Mix Pagado {anio}")
                fig = px.pie(df[df['Año'] == anio], values='Monto', names='Grupo Servicio', hole=0.4)
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("📉 Alertas Tempranas Riesgo de Abandono (Ingresos Reales)")
        if 'Año' in df.columns and 'Mes' in df.columns and 'Empresa' in df.columns:
            df_historico_mensual = df[df['Año'].isin([2025, 2026])].groupby(['Empresa', 'Año', 'Mes'])['Monto'].sum().reset_index()
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
                    df_churn_display['Monto_2025'] = df_churn_display['Monto_2025'].map(lambda x: f"${x:,.0f}")
                    df_churn_display['Monto_2026'] = df_churn_display['Monto_2026'].map(lambda x: f"${x:,.0f}")
                    df_churn_display.columns = ['Empresa', 'Mes', 'Pagado 2025', 'Pagado 2026', 'Variación (%)']
                    st.dataframe(df_churn_display, hide_index=True, use_container_width=True)
                else:
                    st.success("✨ ¡Todo en orden! No se registran caídas críticas de pagos mensuales.")
            else:
                st.info("ℹ️ Se requieren datos pagados de 2025 y 2026 para el análisis de churn.")
        else:
            st.info("ℹ️ Columnas necesarias no disponibles.")
           
        st.divider()

    with tab2:
        container_filtros = st.container()
        with container_filtros:
            st.subheader("Análisis Jerárquico de Ingresos Reales por Empresa y Planta")        
            c_emp1, c_emp2 = st.columns(2)
            for anio, col in zip([2025, 2026], [c_emp1, c_emp2]):
                with col:
                    st.write(f"### Ingresos Reales por Empresa {anio}")
                    df_anio = df[df['Año'] == anio]
                    if not df_anio.empty:
                        fig_emp = px.pie(df_anio, values='Monto', names='Empresa')
                        st.plotly_chart(fig_emp, use_container_width=True)
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
                    df_filtro = df[(df['Empresa'] == empresa_sel) & (df['Año'] == anio)]
                    if not df_filtro.empty:
                        fig_p = px.pie(df_filtro, values='Monto', names='Planta')
                        st.plotly_chart(fig_p, use_container_width=True)
                    else:
                        st.write(f"Sin pagos en {anio}")
            st.divider()
            st.subheader(f"📈 Estacionalidad Mensual de Pagos por Planta: {planta_sel} ({empresa_sel})")
           
            df_planta_estacional = df[(df['Empresa'] == empresa_sel) & (df['Planta'] == planta_sel) & df['Año'].isin([2025, 2026])]
           
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
            df_estacional = df[(df['Empresa'] == empresa_sel) & df['Año'].isin([2025, 2026])].groupby(['Año', 'Mes'])['Monto'].sum().reset_index()
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
       
        df_analisis = df.groupby(['Empresa', 'Grupo Servicio'])['Monto'].sum().reset_index()
       
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
        df_2026 = df[df['Año'] == 2026]
        st.write("### Identificación de Venta Cruzada")
        servicios_disponibles = df['Grupo Servicio'].unique()
        servicio_target = st.selectbox("Selecciona un servicio para buscar clientes potenciales:", servicios_disponibles)
             
        clientes_con_servicio = df_2026[df_2026['Grupo Servicio'] == servicio_target]['Empresa'].unique()
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
        if not df.empty:
            df_abc = df.groupby('Empresa')['Monto'].sum().reset_index()
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
                st.dataframe(df_abc[['Empresa', 'Monto', 'Categoria']], use_container_width=True, hide_index=True)
                st.info("💡 **Estrategia ABC:** Cuida y mantén la relación cercana con tus clientes **Clase A** basándote en su aporte real de caja.")

        st.divider()

        st.write("### 🔍 Mix del Cliente vs. Mix Promedio de la Empresa (Ingresos Reales)")
       
        if not df_2026.empty:
            total_general_2026 = df_2026['Monto'].sum()
            if total_general_2026 > 0:
                mix_global = df_2026.groupby('Grupo Servicio')['Monto'].sum() / total_general_2026 * 100
            else:
                mix_global = pd.Series(dtype=float)

            empresas_2026 = sorted(df_2026['Empresa'].unique())
            c_g1, c_g2 = st.columns(2)
            with c_g1:
                empresa_gap = st.selectbox("Selecciona empresa para brechas:", empresas_2026, key="select_gap_empresa")
           
            plantas_gap_disponibles = sorted(df_2026[df_2026['Empresa'] == empresa_gap]['Planta'].unique())
            with c_g2:
                planta_gap = st.selectbox("Selecciona planta específica:", plantas_gap_disponibles, key="select_gap_planta")
           
            df_planta_gap = df_2026[(df_2026['Empresa'] == empresa_gap) & (df_2026['Planta'] == planta_gap)]
            total_planta = df_planta_gap['Monto'].sum()
           
            if total_planta > 0:
                mix_planta = df_planta_gap.groupby('Grupo Servicio')['Monto'].sum() / total_planta * 100
            else:
                mix_planta = pd.Series(dtype=float)

            df_gap = pd.DataFrame({
                'Mix Promedio Empresa (%)': mix_global,
                f'Mix Actual {empresa_gap} - {planta_gap} (%)': mix_planta
            }).fillna(0)
           
            df_gap['Brecha / Oportunidad (%)'] = df_gap['Mix Promedio Empresa (%)'] - df_gap[f'Mix Actual {empresa_gap} - {planta_gap} (%)']
            df_gap = df_gap.sort_values(by='Brecha / Oportunidad (%)', ascending=False)

            df_gap_display = df_gap.map(lambda x: f"{x:.2f}%")
           
            st.dataframe(df_gap_display, use_container_width=True)
            st.info(f"💡 **Gap Analysis (Pagos):** Muestra qué servicios tienen mayor peso en la recaudación general respecto a la planta **{planta_gap}** de **{empresa_gap}**.")
        else:
            st.warning("No hay datos suficientes de pagos del año 2026 para ejecutar el Gap Analysis.")

    with tab4:
        st.header("➕ Gestión de Facturas y Ciclo de Pago")

        with st.expander("➕ Crear Nueva Factura / Registro de Ingreso"):
            with st.form("form_nueva_factura"):
                fc1, fc2 = st.columns(2)
                with fc1:
                    n_factura = st.text_input("Número de Factura / Documento")
                    n_empresa_ins = st.text_input("Empresa")
                    n_planta_ins = st.text_input("Planta")
                    
                    servicios_existentes = sorted(df['Grupo Servicio'].dropna().unique().tolist()) if not df.empty else ["SERVICIO GENERAL"]
                    n_grupo_servicio = st.selectbox("Grupo Servicio", options=servicios_existentes, key="n_grupo_serv_input")
                    
                    n_servicio_detalle = st.text_input("Servicio (Detalle del servicio prestado)", key="n_serv_det_input")
                    
                    n_monto = st.number_input("Monto ($)", min_value=0.0, step=1000.0)
                    
                    # Nuevos campos de ejecución
                    n_dias_prog = st.number_input("Días Programados de Ejecución", min_value=0.0, step=1.0, value=0.0)
                    n_dias_real = st.number_input("Días Reales de Ejecución", min_value=0.0, step=1.0, value=0.0)

                with fc2:
                    n_estado_pago = st.selectbox("Estado de Pago", ["PENDIENTE", "Pagado"])
                    if n_estado_pago == "Pagado":
                        n_f_pago = st.date_input("Fecha de Pago", value=datetime.now())
                    else:
                        n_f_pago = st.date_input("Fecha de Pago", value=None)
                        
                    n_f_cot = st.date_input("Fecha Cotización", value=None)
                    n_f_oc = st.date_input("Fecha Orden de Compra", value=None)
                    n_f_emi = st.date_input("Fecha Emisión", value=None)
                    n_f_venc = st.date_input("Fecha Vencimiento", value=None)
                    
                    n_f_ges = st.date_input("Fecha GES (si aplica)", value=None)
                    n_req_ges = st.selectbox("¿Requiere GES?", ["No", "Sí"], key="n_req_ges_input")
                
                if st.form_submit_button("💾 Guardar Nueva Factura"):
                    if n_factura.strip() != "" and n_empresa_ins.strip() != "":
                        fecha_pago_final = pd.to_datetime(n_f_pago) if (n_estado_pago == "Pagado" and n_f_pago) else pd.NaT
                        
                        nueva_fila = pd.DataFrame([{
                            "Factura": n_factura,
                            "Empresa": n_empresa_ins.upper(),
                            "Planta": n_planta_ins.upper() if n_planta_ins else "SIN PLANTA",
                            "Grupo Servicio": n_grupo_servicio.upper(),
                            "Servicio": n_servicio_detalle.upper() if n_servicio_detalle else "SIN DETALLE",
                            "Monto": n_monto,
                            "Dias_Programados": n_dias_prog,
                            "Dias_Reales": n_dias_real,
                            "Fecha_Cotizacion": pd.to_datetime(n_f_cot) if n_f_cot else pd.NaT,
                            "Fecha_OC": pd.to_datetime(n_f_oc) if n_f_oc else pd.NaT,
                            "Fecha_Emision": pd.to_datetime(n_f_emi) if n_f_emi else pd.NaT,
                            "Fecha_Vencimiento": pd.to_datetime(n_f_venc) if n_f_venc else pd.NaT,
                            "Fecha_GES": pd.to_datetime(n_f_ges) if n_f_ges else pd.NaT,
                            "Fecha_Pago": fecha_pago_final,
                            "Semáforo": "",
                            "Estado": n_estado_pago,
                            "Requiere_GES": n_req_ges
                        }])
                        df_actualizado = pd.concat([df, nueva_fila], ignore_index=True)
                        df_actualizado.to_excel(RUTA_MAESTRA, index=False)
                        st.cache_data.clear()
                        st.success("¡Factura creada y guardada con éxito en el Excel!")
                        st.rerun()
                    else:
                        st.warning("Por lo menos debes rellenar el Número de Factura y la Empresa.")

        st.divider()

        if 'Fecha_Vencimiento' in df.columns:
            df['Semáforo'] = df.apply(calcular_semaforo_avanzado, axis=1)
        else:
            df['Semáforo'] = 'Sin Fecha Vencimiento'

        # =====================================================================
        # ÚNICO HISTORIAL GENERAL Y MENÚ DESPLEGABLE DE DETALLE
        # =====================================================================
        st.subheader("📊 Historial General de Facturas")
        
        df['Estado'] = df['Fecha_Pago'].apply(lambda x: 'Pagado' if pd.notna(x) else 'PENDIENTE')
        
        if not df.empty:
            # 1. Menú desplegable preliminar para elegir la factura y ver su detalle completo
            st.write("### 🔍 Detalle Extendido por Factura")
            lista_facturas = df['Factura'].astype(str).tolist() if 'Factura' in df.columns else []
            if lista_facturas:
                factura_seleccionada = st.selectbox("Selecciona una factura del historial para ver su información detallada:", lista_facturas)
                
                # Filtrar la fila correspondiente
                row_det = df[df['Factura'].astype(str) == str(factura_seleccionada)].iloc[0]
                
                # Cálculo de KPIs de eficiencia y cobro para el detalle
                d_prog = row_det.get('Dias_Programados', 0)
                d_real = row_det.get('Dias_Reales', 0)
                desviacion = d_real - d_prog
                
                f_emi_val = row_det.get('Fecha_Emision')
                f_pago_val = row_det.get('Fecha_Pago')
                dias_cobro = (pd.to_datetime(f_pago_val) - pd.to_datetime(f_emi_val)).days if pd.notna(f_emi_val) and pd.notna(f_pago_val) else "N/A"

                # Desplegable con todo el detalle técnico solicitado
                with st.expander(f"📂 Información Detallada: Factura #{row_det.get('Factura', 'N/A')} - {row_det.get('Empresa', 'N/A')}", expanded=True):
                    dc1, dc2, dc3 = st.columns(3)
                    
                    with dc1:
                        st.markdown(f"**Empresa:** {row_det.get('Empresa', 'N/A')}")
                        st.markdown(f"**Planta:** {row_det.get('Planta', 'N/A')}")
                        st.markdown(f"**Grupo de Servicio:** {row_det.get('Grupo Servicio', 'N/A')}")
                        st.markdown(f"**Servicio Entregado:** {row_det.get('Servicio', 'N/A')}")
                        st.markdown(f"**Monto:** ${row_det.get('Monto', 0):,.0f}")
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

            # 2. Tabla general limpia y simplificada (Número, Empresa, Planta, Monto, Estado)
            st.write("### 📋 Listado General Preliminar")
            columnas_esenciales = [col for col in ['Factura', 'Empresa', 'Planta', 'Monto', 'Estado'] if col in df.columns]
            
            configuracion_columnas = {
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

            if st.button("💾 Guardar cambios de estados"):
                df.update(df_editado[['Estado']])
                df.to_excel(RUTA_MAESTRA, index=False)
                st.cache_data.clear()
                st.session_state["active_tab"] = 3
                st.rerun()

        st.divider()
           
    with tab5:
        st.header("🔥 Embudo de Ventas")

        if 'Bitacora' not in df_contactos.columns:
            df_contactos['Bitacora'] = ""

        estados = ["Prospecto", "Contactado", "Propuesta", "Ganado", "Perdido"]
       
        # =====================================================================
        # FORMULARIO UNIFICADO (LOCAL + SUPABASE) 
        # =====================================================================
        with st.expander("➕ Crear Nuevo Contacto", expanded=True):
            with st.form("form_contacto_unificado"):
                c1, c2 = st.columns(2)
                nombre = c1.text_input("Nombre completo *")
                empresa = c2.text_input("Empresa *")
                planta = c1.text_input("Planta")
                correo = c2.text_input("Correo electrónico *")
                celular = c1.text_input("Celular")
                estado = c2.selectbox("Estado del Cliente", estados)
                rol = c1.selectbox("Rol en la Cuenta", ["Tomador de Decisiones (CEO/Gerente)", "Influenciador", "Técnico / Operativo", "Finanzas / Compras"])
                valor = c2.number_input("Valor", min_value=0.0, step=1000.0)

                submitted = st.form_submit_button("💾 Guardar Registro (Sincronizado a Nube)")

                if submitted:
                    if nombre and correo and empresa:
                        try:
                            guardar_contacto(nombre, correo, estado, celular)
                            supa_success = True
                        except Exception as e:
                            st.error(f"Error al guardar en Supabase: {e}")
                            supa_success = False

                        nueva = pd.DataFrame([{
                            "Nombre": nombre,
                            "Empresa": empresa,
                            "Planta": planta,
                            "Correo": correo,
                            "Celular": celular,
                            "Estado": estado,
                            "Valor": valor,
                            "Bitacora": "",
                            "Rol_Contacto": rol
                        }])
                        pd.concat([df_contactos, nueva], ignore_index=True).to_csv(ARCHIVO_CONTACTOS, index=False)
                        
                        if supa_success:
                            st.success(f"¡Cliente {nombre} registrado exitosamente en Supabase y Embudo Local!")
                        else:
                            st.warning(f"¡Cliente {nombre} guardado en tu sistema local, pero hubo un error de conexión con Supabase!")
                            
                        st.session_state["active_tab"] = 4
                        st.rerun()
                    else:
                        st.warning("Por favor completa los campos obligatorios (*).")
      
        st.divider()

        st.subheader("📊 Gráfico de Conversión")
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

        cols = st.columns(5)
       
        for i, col in enumerate(cols):
            with col:
                st.subheader(estados[i])
                contactos_estado = df_contactos[df_contactos["Estado"] == estados[i]]
                for idx, row in contactos_estado.iterrows():
                    st.write(f"*{row['Nombre']}*")
                    st.write(f"Empresa: {row['Empresa']}")
                    st.write(f"Rol: **{row.get('Rol_Contacto', 'Influenciador')}**")
                    st.write(f"Valor: ${row['Valor']}")
                   
                    correo_contacto = row.get('Correo', '')
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
                                ✉️ Enviar Correo
                            </a>
                            """,
                            unsafe_allow_html=True
                        )
                    else:
                        st.caption("⚠️ Sin correo registrado")

                    nota_actual = row.get('Bitacora', '')
                    if pd.isna(nota_actual):
                        nota_actual = ""
                       
                    with st.expander(f"📝 Bitácora ({row['Nombre']})"):
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
                                    nueva_interaccion = pd.DataFrame([{
                                        "Nombre_Contacto": row['Nombre'],
                                        "Empresa": row['Empresa'],
                                        "Tipo": tipo_inter,
                                        "Detalle": detalle_inter,
                                        "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M")
                                    }])
                                    pd.concat([df_interacciones, nueva_interaccion], ignore_index=True).to_csv(ARCHIVO_HISTORIAL_INTERACCIONES, index=False)
                                    st.success("¡Interacción registrada!")
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
                                df_contactos.loc[idx, 'Bitacora'] = nueva_nota
                                df_contactos.to_csv(ARCHIVO_CONTACTOS, index=False)
                               
                                nueva_interaccion = pd.DataFrame([{
                                    "Nombre_Contacto": row['Nombre'],
                                    "Empresa": row['Empresa'],
                                    "Tipo": "Nota / Bitácora",
                                    "Detalle": nueva_nota[:80] + "...",
                                    "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M")
                                }])
                                pd.concat([df_interacciones, nueva_interaccion], ignore_index=True).to_csv(ARCHIVO_HISTORIAL_INTERACCIONES, index=False)
                               
                                st.success("¡Guardado!")
                                st.rerun()
                        with col_b2:
                            nuevo_estado_rapido = st.selectbox("Mover:", estados, index=estados.index(row['Estado']), key=f"mov_{idx}")
                            if nuevo_estado_rapido != row['Estado']:
                                df_contactos.loc[idx, 'Estado'] = nuevo_estado_rapido
                                df_contactos.to_csv(ARCHIVO_CONTACTOS, index=False)
                                st.rerun()

                    with st.expander(f"⏱️ Línea de Tiempo ({row['Nombre']})"):
                        filtro_inter = df_interacciones[df_interacciones['Nombre_Contacto'] == row['Nombre']]
                        if not filtro_inter.empty:
                            for _, inter_row in filtro_inter.iterrows():
                                st.caption(f"[{inter_row['Fecha']}] **{inter_row['Tipo']}**: {inter_row['Detalle']}")
                        else:
                            st.caption("No hay interacciones registradas aún.")

                    if st.button("🗑️ Borrar", key=f"del_{idx}"):
                        df_contactos.drop(idx).to_csv(ARCHIVO_CONTACTOS, index=False)
                        st.session_state["active_tab"] = 4
                        st.rerun()

        st.divider()

        st.subheader("🎯 Calificación de Prospectos")
       
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
            df_contactos['Temperatura_Lead'] = "❄️ Lead Frío"

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

        st.subheader("💰 Pronóstico de Ingresos")
        probabilidades = {
            "Prospecto": 0.10,
            "Contactado": 0.25,
            "Propuesta": 0.50,
            "Ganado": 1.00,
            "Perdido": 0.00
        }
        df_contactos['Probabilidad'] = df_contactos['Estado'].map(probabilidades)
        df_contactos['Valor_Ponderado'] = df_contactos['Valor'] * df_contactos['Probabilidad']

        total_pipeline = df_contactos[df_contactos['Estado'] != 'Perdido']['Valor'].sum()
        forecast_ponderado = df_contactos['Valor_Ponderado'].sum()

        col_f1, col_f2 = st.columns(2)
        col_f1.metric("Valor Total en Pipeline Activo", f"${total_pipeline:,.0f}")
        col_f2.metric("Forecast Ponderado (Proyección Real)", f"${forecast_ponderado:,.0f}")

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

        st.subheader("🛠️ Módulo de Soporte y Tickets (Helpdesk)")
        with st.expander("➕ Crear Nuevo Ticket de Soporte"):
            with st.form("form_ticket"):
                t_empresa = st.selectbox("Empresa del Cliente", sorted(df['Empresa'].unique()))
                t_asunto = st.text_input("Asunto / Problema Técnico")
                t_prioridad = st.selectbox("Prioridad", ["Baja", "Media", "Alta", "Crítica"])
                t_estado = st.selectbox("Estado del Ticket", ["Abierto", "En Proceso", "Cerrado"])
                if st.form_submit_button("Guardar Ticket"):
                    nuevo_t = pd.DataFrame([{
                        "ID_Ticket": f"TKT-{len(df_tickets)+1:03d}",
                        "Empresa": t_empresa,
                        "Asunto": t_asunto,
                        "Estado": t_estado,
                        "Prioridad": t_prioridad,
                        "Fecha": datetime.now().strftime("%Y-%m-%d")
                    }])
                    pd.concat([df_tickets, nuevo_t], ignore_index=True).to_csv(ARCHIVO_TICKETS, index=False)
                    st.success("¡Ticket creado con éxito!")
                    st.rerun()

        st.divider()

        with st.expander("✏️ Editar contactos existentes"):
            for idx, row in df_contactos.iterrows():
                with st.form(f"edit_{idx}"):
                    st.write(f"Editando: {row['Nombre']}")
                    n_nombre = st.text_input("Nombre", row['Nombre'])
                    n_empresa = st.text_input("Empresa", row['Empresa'])
                    n_planta = st.text_input("Planta", row['Planta'])
                    n_correo = st.text_input("Correo", row.get('Correo', ''))
                    n_celular = st.text_input("Celular", row.get('Celular', ''))
                    n_estado = st.selectbox("Estado", estados, index=estados.index(row['Estado']))
                    n_rol = st.selectbox("Rol en la Cuenta", ["Tomador de Decisiones (CEO/Gerente)", "Influenciador", "Técnico / Operativo", "Finanzas / Compras"], index=0 if row.get('Rol_Contacto') not in ["Influenciador", "Técnico / Operativo", "Finanzas / Compras"] else ["Tomador de Decisiones (CEO/Gerente)", "Influenciador", "Técnico / Operativo", "Finanzas / Compras"].index(row.get('Rol_Contacto', 'Influenciador')))
                    n_valor = st.number_input("Valor", value=float(row['Valor']))
                   
                    if st.form_submit_button("💾 Guardar Cambios"):
                        df_contactos.loc[idx, 'Nombre'] = n_nombre
                        df_contactos.loc[idx, 'Empresa'] = n_empresa
                        df_contactos.loc[idx, 'Planta'] = n_planta
                        df_contactos.loc[idx, 'Correo'] = n_correo
                        df_contactos.loc[idx, 'Celular'] = n_celular
                        df_contactos.loc[idx, 'Estado'] = n_estado
                        df_contactos.loc[idx, 'Valor'] = n_valor
                        df_contactos.loc[idx, 'Rol_Contacto'] = n_rol
                       
                        df_contactos.to_csv(ARCHIVO_CONTACTOS, index=False)
                        st.success("¡Contacto actualizado con éxito!")
                        st.session_state["active_tab"] = 4
                        st.rerun()