import re
from datetime import datetime
import pandas as pd
import streamlit as st
from alertas_correo import (
    enviar_email_smtp,
    guardar_config_smtp,
    notificar_nueva_cotizacion,
    obtener_config_smtp,
    revisar_y_enviar_alertas_24h,
)
from database import (
    CENTROS_VALIDOS,
    MESES_VALIDOS,
    get_conn,
    init_db,
    registrar_historial,
)

def _obtener_clave_smtp_admin():
    try:
        if "SMTP_ADMIN_PIN" in st.secrets:
            val = str(st.secrets["SMTP_ADMIN_PIN"]).strip()
            if val:
                return val
    except Exception:
        pass
    return "2026"


def _renderizar_bloque_smtp_y_alertas(df_com, df_resp, df_dir, df_cli):

    st.markdown("#### 📋 AUDITORÍA RECIENTE DE ALERTAS DIARIAS (11:00 – 12:00)")
    try:
        conn_aud = get_conn()
        df_aud = pd.read_sql_query(
            """
            SELECT fecha_envio_alerta, id_cotizacion, responsable, email_responsable,
                   estado_cotizacion, enviado_ok, detalle_envio
            FROM log_alertas_11_12
            ORDER BY id_alerta DESC
            LIMIT 25
            """,
            conn_aud,
        )
        conn_aud.close()
        if not df_aud.empty:
            st.dataframe(df_aud, use_container_width=True, hide_index=True)
        else:
            st.caption("Aún no hay registros en log_alertas_11_12.")
    except Exception:
        st.caption("La tabla log_alertas_11_12 se creará automáticamente al ejecutar las alertas.")

    st.divider()
    st.markdown("#### 🔒 SERVIDOR DE CORREO (SMTP), ALERTAS +24H Y RECORDATORIOS DIARIOS (11:00 – 12:00)")

    clave_correcta = _obtener_clave_smtp_admin()
    unlocked_key = "smtp_admin_unlocked"
    if unlocked_key not in st.session_state:
        st.session_state[unlocked_key] = False

    if not st.session_state[unlocked_key]:
        st.info("🔒 Este apartado está protegido con clave para que solo tú puedas consultar o cambiar la configuración SMTP y las alertas.")
        with st.form("form_desbloqueo_smtp"):
            pin_ingresado = st.text_input("INTRODUCE TU CLAVE DE ACCESO", type="password", key="smtp_pin_input")
            b_unlock = st.form_submit_button("🔓 DESBLOQUEAR APARTADO")
            if b_unlock:
                if pin_ingresado == clave_correcta:
                    st.session_state[unlocked_key] = True
                    st.success("Acceso concedido.")
                    st.rerun()
                else:
                    st.error("Clave incorrecta.")
        return

    c_lock_top, _ = st.columns([1.4, 4.6])
    if c_lock_top.button("🔒 BLOQUEAR APARTADO", key="btn_lock_smtp"):
        st.session_state[unlocked_key] = False
        st.rerun()

    st.markdown("#### SERVIDOR DE CORREO (SMTP) Y ALERTAS +24H")
    cfg_smtp = obtener_config_smtp()

    with st.form("form_smtp"):
        s1, s2 = st.columns(2)
        smtp_host = s1.text_input("SERVIDOR SMTP (EJ. SMTP.OFFICE365.COM O SMTP.GMAIL.COM)", value=cfg_smtp["smtp_host"])
        smtp_port = s2.number_input("PUERTO SMTP", min_value=1, max_value=65535, value=int(cfg_smtp["smtp_port"] or 587))

        s3, s4, s5 = st.columns(3)
        smtp_user = s3.text_input("USUARIO / CORREO REMITENTE", value=cfg_smtp["smtp_user"])
        smtp_password = s4.text_input("CONTRASEÑA O APP PASSWORD", type="password", value=cfg_smtp["smtp_password"])
        use_tls = s5.checkbox("USAR STARTTLS", value=bool(cfg_smtp["use_tls"]))

        b1, b2 = st.columns(2)
        guardar_smtp_btn = b1.form_submit_button("GUARDAR CONFIGURACIÓN SMTP")
        probar_smtp_btn = b2.form_submit_button("ENVIAR CORREO DE PRUEBA A EMILIO")

        if guardar_smtp_btn:
            guardar_config_smtp(smtp_host, smtp_port, smtp_user, smtp_password, use_tls)
            st.success("CONFIGURACIÓN SMTP GUARDADA.")
            st.rerun()

        if probar_smtp_btn:
            guardar_config_smtp(smtp_host, smtp_port, smtp_user, smtp_password, use_tls)
            ok_p, msg_p = enviar_email_smtp(
                ["eastier@mbe.es"],
                "[PRUEBA] GESTOR DE COTIZACIONES (>300€)",
                "Correo de prueba enviado desde el Gestor de Cotizaciones en C:\\gestor_cotizaciones.",
            )
            if ok_p:
                st.success(msg_p)
            else:
                st.error(msg_p)

    if st.button("⏱️ COMPROBAR Y ENVIAR ALERTAS PENDIENTES (+24H)"):
        res_alertas = revisar_y_enviar_alertas_24h(24)
        if isinstance(res_alertas, tuple) and len(res_alertas) == 3:
            rev, env, errs = res_alertas
            st.info(f"COTIZACIONES VENCIDAS (+24H) DETECTADAS: {rev} | ALERTAS ENVIADAS: {env}")
        else:
            env, errs = res_alertas
            st.info(f"ALERTAS ENVIADAS (+24H): {env}")
        for er in errs:
            st.warning(er)

    st.divider()
    st.markdown("#### 🔔 RECORDATORIOS DIARIOS AL RESPONSABLE (11:00 – 12:00 · DÍA SIGUIENTE HASTA SALIR DE EN CURSO)")
    st.caption(
        "Se envía al correo del responsable a partir del día siguiente de mandar la cotización, entre las 11:00 y las 12:00, "
        "cada día que siga 'En curso' sin acción registrada, incluyendo el enlace de la web."
    )
    _url_alerta_cfg = st.text_input(
        "ENLACE DE LA WEB PARA EL CORREO DEL RESPONSABLE",
        value="http://localhost:8501",
        key="url_alerta_responsable_11_12",
    )
    _b_al1, _b_al2 = st.columns(2)
    if _b_al1.button("⏱️ EJECUTAR ALERTAS AHORA (RESPETANDO FRANJA 11:00-12:00)", key="btn_run_11_12_strict"):
        if callable(procesar_alertas_responsables_11_12):
            _r1 = procesar_alertas_responsables_11_12(forzar_ventana=False, url_web=_url_alerta_cfg)
            st.info(f"Candidatas: {_r1['candidatas']} | Enviadas: {_r1['enviadas']} | Omitidas: {_r1['omitidas']}")
            for _d in _r1["detalles"]:
                st.success(_d)
            for _e in _r1["errores"]:
                st.warning(_e)
    if _b_al2.button("🧪 PROBAR ENVÍO AHORA (SIMULANDO FRANJA 11:00-12:00)", key="btn_run_11_12_sim"):
        if callable(procesar_alertas_responsables_11_12):
            _r2 = procesar_alertas_responsables_11_12(forzar_ventana=True, url_web=_url_alerta_cfg)
            st.info(f"Candidatas: {_r2['candidatas']} | Enviadas: {_r2['enviadas']} | Omitidas: {_r2['omitidas']}")
            for _d in _r2["detalles"]:
                st.success(_d)
            for _e in _r2["errores"]:
                st.warning(_e)

try:
    from recordatorios_diarios import (
        ejecutar_chequeo_automatico_11_12_en_app,
        procesar_alertas_responsables_11_12,
    )
except Exception:
    ejecutar_chequeo_automatico_11_12_en_app = None
    procesar_alertas_responsables_11_12 = None

st.set_page_config(page_title="TRANSEUSKADI GROUP — Gestor de Cotizaciones (>300€)", layout="wide", initial_sidebar_state="expanded")
init_db()
if callable(ejecutar_chequeo_automatico_11_12_en_app):
    try:
        ejecutar_chequeo_automatico_11_12_en_app()
    except Exception:
        pass

st.markdown(
    """
    <style>
        .stApp {
            background-color: #f4f6f9;
            color: #162232;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f233c 0%, #173459 100%);
            border-right: 1px solid rgba(255,255,255,0.08);
        }
        [data-testid="stSidebar"] * {
            color: #eef3f8 !important;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] > div {
            gap: 6px;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 10px;
            padding: 10px 14px;
            transition: all 0.18s ease;
            cursor: pointer;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
            background: rgba(255,255,255,0.14);
            border-color: rgba(255,255,255,0.28);
            transform: translateX(2px);
        }
        .te-brand-card {
            background: linear-gradient(135deg, #0f233c 0%, #1d4270 100%);
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 14px;
            padding: 16px 16px 14px 16px;
            margin-bottom: 14px;
            box-shadow: 0 8px 20px rgba(15, 35, 60, 0.18);
        }
        .te-brand-badge {
            display: inline-block;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            color: #93c5fd !important;
            background: rgba(147, 197, 253, 0.14);
            padding: 3px 8px;
            border-radius: 999px;
            margin-bottom: 8px;
        }
        .te-brand-title {
            font-size: 18px;
            font-weight: 800;
            letter-spacing: 0.5px;
            color: #ffffff !important;
            line-height: 1.2;
            margin: 0 0 4px 0;
        }
        .te-brand-sub {
            font-size: 12px;
            color: #cbd5e1 !important;
            margin: 0;
        }
        .te-header-banner {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-left: 6px solid #0f233c;
            border-radius: 14px;
            padding: 18px 24px;
            margin-bottom: 18px;
            box-shadow: 0 4px 14px rgba(15, 35, 60, 0.05);
        }
        .te-header-kicker {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1.1px;
            text-transform: uppercase;
            color: #1d4ed8;
            margin-bottom: 4px;
        }
        .te-header-title {
            font-size: 26px;
            font-weight: 800;
            color: #0f233c;
            margin: 0 0 4px 0;
        }
        .te-header-desc {
            font-size: 13px;
            color: #475569;
            margin: 0;
        }
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 14px 16px;
            box-shadow: 0 2px 8px rgba(15, 35, 60, 0.04);
        }
        [data-testid="stMetricLabel"] {
            font-weight: 700 !important;
            color: #475569 !important;
        }
        [data-testid="stMetricValue"] {
            color: #0f233c !important;
            font-weight: 800 !important;
            font-size: clamp(1.15rem, 1.55vw, 1.7rem) !important;
            white-space: nowrap !important;
            overflow: visible !important;
            text-overflow: clip !important;
        }
        [data-testid="stMetricValue"] > div {
            overflow: visible !important;
            text-overflow: clip !important;
            white-space: nowrap !important;
        }
        [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 6px;
            box-shadow: 0 2px 8px rgba(15, 35, 60, 0.04);

        }
        .stButton > button, .stFormSubmitButton > button {
            border-radius: 10px;
            font-weight: 700;
            border: 1px solid #0f233c;
            transition: all 0.15s ease;
        }
        .stButton > button:hover, .stFormSubmitButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 10px rgba(15, 35, 60, 0.12);
        }
        .te-critical-alert {
            background: #fffbeb;
            border: 1.5px solid #f59e0b;
            border-left: 6px solid #d97706;
            border-radius: 10px;
            padding: 10px 14px;
            margin-bottom: 12px;
            color: #78350f;
            font-size: 13px;
            font-weight: 600;
        }
        .te-critical-tag {
            display: inline-block;
            background: #fef3c7;
            color: #92400e;
            border: 1px solid #f59e0b;
            border-radius: 6px;
            padding: 1px 7px;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.5px;
            margin-left: 6px;
            vertical-align: middle;
        }
        .te-resp-pending-label {
            display: inline-block;
            background: #fef2f2;
            color: #b91c1c;
            border: 1.5px solid #ef4444;
            border-radius: 6px;
            padding: 1px 7px;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.5px;
            margin-left: 6px;
            vertical-align: middle;
        }
        .te-resp-ok-label {
            display: inline-block;
            background: #ecfdf5;
            color: #047857;
            border: 1px solid #10b981;
            border-radius: 6px;
            padding: 1px 7px;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.5px;
            margin-left: 6px;
            vertical-align: middle;
        }
        div[data-testid="stForm"] div[data-testid="stSelectbox"]:has(input[aria-label="RESPONSABLE_PENDIENTE"]),
        div[data-testid="stForm"] div[data-testid="stSelectbox"]:has(div[data-baseweb="select"] span:contains("-- SELECCIONAR RESPONSABLE --")) {
            border: 2px solid #dc2626 !important;
            border-radius: 10px !important;
            background-color: #fef2f2 !important;
            padding: 2px !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

MESES_ES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL",
    5: "MAYO", 6: "JUNIO", 7: "JULIO", 8: "AGOSTO",
    9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE",
}


def mes_desde_fecha(fecha_str):
    txt = (fecha_str or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(txt, fmt)
            return MESES_ES[dt.month]
        except ValueError:
            continue
    return MESES_ES[datetime.now().month]


def a_float_seguro(val, defecto=0.0):
    if val is None:
        return defecto
    if isinstance(val, (int, float)):
        return float(val)
    txt = str(val).replace("€", "").replace("%", "").replace(" ", "").replace(",", ".").strip()
    if not txt:
        return defecto
    try:
        return float(txt)
    except ValueError:
        return defecto


def normalizar_centro(val):
    t = (val or "").upper().strip()
    for c in CENTROS_VALIDOS:
        codigo = c.split()[0]
        if c == t or codigo in t or c.split()[1] in t:
            return c
    return "0329 DERIO"


def _extraer_ddmmaaaa(fecha_str=None):
    txt = str(fecha_str or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d%m%Y"):
        try:
            return datetime.strptime(txt, fmt).strftime("%d%m%Y")
        except ValueError:
            continue
    m_dmy = re.search(r"\b(\d{2})[/-](\d{2})[/-](\d{4})\b", txt)
    if m_dmy:
        return f"{m_dmy.group(1)}{m_dmy.group(2)}{m_dmy.group(3)}"
    return datetime.now().strftime("%d%m%Y")


def generar_siguiente_id(fecha_str=None):
    prefijo = f"{_extraer_ddmmaaaa(fecha_str)}-"
    conn = get_conn()
    rows = conn.execute(
        "SELECT id FROM cotizaciones WHERE UPPER(TRIM(CAST(id AS TEXT))) LIKE ?",
        (f"{prefijo}%",),
    ).fetchall()
    conn.close()
    max_num = 0
    for r in rows:
        val_id = str(r["id"] or "").strip().upper()
        if val_id.startswith(prefijo):
            sufijo = val_id[len(prefijo):]
            m_num = re.match(r"^(\d+)", sufijo)
            if m_num:
                max_num = max(max_num, int(m_num.group(1)))
    return f"{prefijo}{max_num + 1:03d}"


def detectar_especial_texto(texto, pais="", servicio="", tipo_envio=""):
    t = f"{texto or ''} {pais or ''} {servicio or ''} {tipo_envio or ''}".upper()
    claves = [
        "DIRECTO", "DIRECTOS", "SERVICIO DIRECTO",
        "FREIGHT", "AIR FREIGHT", "SEA FREIGHT", "ROAD FREIGHT",
        "PALLET INTERNACIONAL", "PALETS INTERNACIONALES",
        "PALLET INT", "PALETS INT",
        "PALLET EUROPA", "PALETS EUROPA", "PALLET UE", "PALETS UE",
        "PALLET", "PALETS", "PALET",
    ]
    return "SÍ" if any(k in t for k in claves) else "NO"

CATALOGO_MERCANCIA = {
    "PAQUETES": {
        "UPS": ["STANDARD", "SAVER", "EXPRESS (MORNING)", "EXPRESS PLUS"],
        "FEDEX": ["ECONOMY", "PRIORITY"],
        "TNT": ["ECONOMY", "GLOBAL"],
    },
    "PALET": {
        "FEDEX": ["ECONOMY FREIGHT", "PRIORITY FREIGHT"],
        "TNT": ["ECONOMY", "GLOBAL"],
        "DSV": ["ESTÁNDAR / GENERAL"],
    },
    "GRUPAJES": {
        "DSV": ["GRUPAJE"],
        "TRANSATUR (COURIERS)": ["GRUPAJE"],
        "XPO": ["GRUPAJE"],
    },
    "DIRECTO": {
        "ADER": ["DIRECTO"],
        "ABIAN": ["DIRECTO"],
        "EMDIPA": ["DIRECTO"],
    },
}


def _inferir_mercancia(tipo_envio="", servicio="", courier="", es_especial=""):
    txt = f"{tipo_envio or ''} {servicio or ''} {courier or ''}".upper()
    if "GRUPAJ" in txt:
        return "GRUPAJES"
    if any(k in txt for k in ("ADER", "ABIAN", "EMDIPA", "DIRECTO")):
        return "DIRECTO"
    if any(k in txt for k in ("PALET", "PALLET", "FREIGHT")):
        return "PALET"
    return "PAQUETES"



def _formatear_eur_tabla(val):
    if val is None or pd.isna(val) or str(val).strip().lower() in ("", "none", "nan"):
        return "-"
    try:
        num = float(str(val).replace("€", "").replace(",", ".").strip())
        return f"{num:.2f} €".replace(".", ",")
    except ValueError:
        return str(val).strip()


def _formatear_pct_tabla(val):
    if val is None or pd.isna(val) or str(val).strip().lower() in ("", "none", "nan"):
        return "-"
    try:
        num = float(str(val).replace("%", "").replace(",", ".").strip())
        return f"{num:.2f} %".replace(".", ",")
    except ValueError:
        return str(val).strip()


def _limpiar_texto_tabla(val):
    if val is None or pd.isna(val) or str(val).strip().lower() in ("", "none", "nan"):
        return "-"
    return str(val).strip()



def _formatear_rango_prevision(rango_val):
    if isinstance(rango_val, (list, tuple)):
        fechas_limpias = [f for f in rango_val if f is not None]
        if len(fechas_limpias) >= 2:
            d1 = fechas_limpias[0].strftime("%d/%m/%Y") if hasattr(fechas_limpias[0], "strftime") else str(fechas_limpias[0])
            d2 = fechas_limpias[1].strftime("%d/%m/%Y") if hasattr(fechas_limpias[1], "strftime") else str(fechas_limpias[1])
            return f"{d1} - {d2}" if d1 != d2 else d1
        if len(fechas_limpias) == 1:
            return fechas_limpias[0].strftime("%d/%m/%Y") if hasattr(fechas_limpias[0], "strftime") else str(fechas_limpias[0])
        return ""
    if hasattr(rango_val, "strftime"):
        return rango_val.strftime("%d/%m/%Y")
    return str(rango_val or "").strip()

def _texto_seguro(val, defecto=""):
    if val is None or pd.isna(val) or str(val).strip().lower() in ("none", "nan"):
        return defecto
    return str(val)


def cargar_comerciales_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM comerciales ORDER BY comercial ASC", conn)
    conn.close()
    return df


def cargar_responsables_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM responsables ORDER BY responsable ASC", conn)
    conn.close()
    return df


def cargar_direccion_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM direccion ORDER BY persona ASC", conn)
    conn.close()
    return df


def cargar_clientes_df():
    conn = get_conn()
    df = pd.read_sql_query(
        """
        SELECT cli.*, com.email_comercial
        FROM clientes cli
        LEFT JOIN comerciales com ON cli.comercial = com.comercial
        ORDER BY cli.cliente ASC
        """,
        conn,
    )
    conn.close()
    return df


def cargar_cotizaciones_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM cotizaciones ORDER BY ultima_actualizacion ASC", conn)
    conn.close()
    return df


def mostrar_aviso_precios_cliente(df_cot, nombre_cliente):
    hist = df_cot[df_cot["cliente"] == nombre_cliente].copy()
    if hist.empty:
        return

    aceptadas = hist[hist["estado"] == "Aceptada"]["importe_ofertado"].dropna().tolist()
    refs_comp = []
    for _, r in hist.iterrows():
        if r["estado"] == "Aceptada" and pd.notna(r["importe_ofertado"]):
            refs_comp.append(float(r["importe_ofertado"]))
        txt_comp = str(r.get("precio_competencia") or "").replace(",", ".").strip()
        try:
            if txt_comp:
                refs_comp.append(float("".join(ch for ch in txt_comp if ch.isdigit() or ch == ".")))
        except ValueError:
            pass

    rechazadas = hist[hist["estado"] == "Perdida"]["importe_ofertado"].dropna().tolist()

    if aceptadas or rechazadas or refs_comp:
        msg_partes = []
        if rechazadas:
            msg_partes.append(f"Ofertado rechazado: {', '.join(f'{x:.2f}€' for x in rechazadas)}")
        if refs_comp:
            rango_min = min(refs_comp)
            rango_max = max(refs_comp)
            msg_partes.append(f"Referencias aceptadas/competencia: {rango_min:.2f}€ – {rango_max:.2f}€")
        if aceptadas:
            msg_partes.append(f"Aceptado: {', '.join(f'{x:.2f}€' for x in aceptadas)}")
        st.info("💡 **HISTORIAL DE PRECIOS DEL CLIENTE:** " + " | ".join(msg_partes))


qp = st.query_params
viene_de_mbe = str(qp.get("mbe", "")).strip() in ("1", "true", "yes", "si", "sí")

q_centro = normalizar_centro(qp.get("centro", "0329 DERIO"))
q_fecha = str(qp.get("fecha", datetime.now().strftime("%d/%m/%Y"))).strip() or datetime.now().strftime("%d/%m/%Y")
q_mes_raw = str(qp.get("mes", "")).upper().strip()
q_mes = q_mes_raw if q_mes_raw in MESES_VALIDOS else mes_desde_fecha(q_fecha)
q_cliente = str(qp.get("cliente", "")).upper().strip()
q_peso = str(qp.get("peso", "")).upper().strip()
q_courier = str(qp.get("courier", "")).upper().strip()
q_tipo_envio_raw = str(qp.get("tipo_envio", "EXPORT")).upper().strip()
q_tipo_envio = "IMPORT" if "IMPORT" in q_tipo_envio_raw else "EXPORT"
q_pais = str(qp.get("pais", "")).upper().strip()
q_servicio = str(qp.get("servicio", "")).upper().strip()
q_coste = a_float_seguro(qp.get("coste", 0.0), 0.0)
q_coste_total = a_float_seguro(qp.get("coste_total", 0.0), 0.0)
q_precio = a_float_seguro(qp.get("precio", 0.0), 0.0)
q_precio_total = a_float_seguro(qp.get("precio_total", 0.0), 0.0)
q_margen = a_float_seguro(qp.get("margen", 0.0), 0.0)
q_margen_total = a_float_seguro(qp.get("margen_total", 0.0), 0.0)

st.sidebar.markdown(
    """
    <div class="te-brand-card">
        <div class="te-brand-badge">GRUPO LOGÍSTICO</div>
        <div class="te-brand-title">TRANSEUSKADI GROUP</div>
        <p class="te-brand-sub">Gestión de Cotizaciones (&gt;300 €)</p>
    </div>
    """,
    unsafe_allow_html=True,
)

menu = st.sidebar.radio(
    "NAVEGACIÓN",
    [
        "➕ NUEVA COTIZACIÓN",
        "📋 SEGUIMIENTO Y ACCIONES",
        "📊 PANEL Y RECHAZOS",
        "📈 DASHBOARD TIEMPO REAL",
        "👥 CARTERA Y CORREOS",
    ],
)

st.sidebar.markdown("---")
st.sidebar.caption("TRANSEUSKADI GROUP · Control comercial y operativo en tiempo real.")

st.markdown(
    f"""
    <div class="te-header-banner">
        <div class="te-header-kicker">TRANSEUSKADI GROUP · PORTAL DE COTIZACIONES</div>
        <h1 class="te-header-title">📦 Gestor de Cotizaciones de Envíos (&gt;300 €)</h1>
        <p class="te-header-desc">Sección activa: <strong>{menu}</strong> — Seguimiento, sinergias, cartera y métricas en vivo.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    if menu == "➕ NUEVA COTIZACIÓN":
        st.subheader("REGISTRAR NUEVA COTIZACIÓN")
        if viene_de_mbe:
            st.success("⚡ **DATOS CAPTURADOS DESDE MBE HUB.** Revisa el **RESPONSABLE** y **COTIZACIÓN ESPECIAL** antes de guardar.")

        df_cli = cargar_clientes_df()
        df_com = cargar_comerciales_df()
        df_resp = cargar_responsables_df()
        df_cot = cargar_cotizaciones_df()

        coincidencia_idx = 0
        cliente_en_cartera = None
        if not df_cli.empty and q_cliente:
            exactos = df_cli[df_cli["cliente"].str.upper().str.strip() == q_cliente]
            if not exactos.empty:
                cliente_en_cartera = exactos.iloc[0]
                coincidencia_idx = int(exactos.index[0])

        modo_defecto = "CLIENTE EXISTENTE" if (cliente_en_cartera is not None or not viene_de_mbe) else "CLIENTE NUEVO"
        modo_cliente = st.radio(
            "TIPO DE CLIENTE",
            ["CLIENTE EXISTENTE", "CLIENTE NUEVO"],
            index=0 if modo_defecto == "CLIENTE EXISTENTE" else 1,
            horizontal=True,
        )

        if modo_cliente == "CLIENTE EXISTENTE" and not df_cli.empty:
            opciones = [f"{r['id_cliente']} | {r['cliente']}" for _, r in df_cli.iterrows()]
            seleccion = st.selectbox("BUSCAR CLIENTE", opciones, index=coincidencia_idx)
            id_cli_sel = int(seleccion.split(" | ")[0])
            fila_cli = df_cli[df_cli["id_cliente"] == id_cli_sel].iloc[0]

            id_cliente = int(fila_cli["id_cliente"])
            cliente_nombre = str(fila_cli["cliente"]).upper()
            contacto_def = str(fila_cli["contacto_habitual"] or "").upper()
            comercial_asig = str(fila_cli["comercial"]).upper()
            if comercial_asig == "VASILY":
                comercial_asig = "VASYL"
            email_comercial = str(fila_cli["email_comercial"] or "")
            st.success(f"COMERCIAL DE CARTERA: **{comercial_asig}** | CORREO: **{email_comercial or 'SIN CONFIGURAR'}**")
            mostrar_aviso_precios_cliente(df_cot, cliente_nombre)
        else:
            c_n1, c_n2 = st.columns(2)
            cliente_nombre = c_n1.text_input("NOMBRE DEL CLIENTE", value=q_cliente).upper().strip()
            contacto_def = ""
            id_cliente = None

            com_sugerido = None
            if not df_cli.empty and cliente_nombre:
                match_sub = df_cli[df_cli["cliente"].str.upper().str.contains(cliente_nombre, na=False, regex=False)]
                if not match_sub.empty:
                    com_sugerido = str(match_sub.iloc[0]["comercial"]).upper()
                    if com_sugerido == "VASILY":
                        com_sugerido = "VASYL"

            lista_com = df_com["comercial"].tolist() if not df_com.empty else ["ENEKO"]
            idx_com = lista_com.index(com_sugerido) if (com_sugerido and com_sugerido in lista_com) else 0
            comercial_asig = c_n2.selectbox("COMERCIAL ASIGNADO", lista_com, index=idx_com)
            fila_com = df_com[df_com["comercial"] == comercial_asig]
            email_comercial = fila_com.iloc[0]["email_comercial"] if not fila_com.empty else ""
            if com_sugerido:
                st.info(f"COMERCIAL DETECTADO EN CARTERA: **{comercial_asig}**")

        lista_resp_base = [str(x).strip() for x in (df_resp["responsable"].tolist() if not df_resp.empty else []) if str(x).strip()]
        for _r_def in ["VASYL", "BEGOÑA", "FRANCINE", "IMANOL", "JULEN", "OLGA", "MARIA", "NAIARA LLAMAS", "NAIARA ZARATE", "ENEKO", "ELENA", "EMILIO", "IBON"]:
            if _r_def not in lista_resp_base:
                lista_resp_base.append(_r_def)
        lista_resp_vacia = [""] + lista_resp_base

        _resp_actual_key = "nueva_cot_responsable_sel"
        _resp_actual_val = str(st.session_state.get(_resp_actual_key, "") or "").strip()

        _rc_left, _rc_right = st.columns([1.3, 3.7])
        with _rc_left:
            if not _resp_actual_val:
                st.markdown(
                    """
                    <style>
                        div[data-testid="stSelectbox"] > div[data-baseweb="select"] > div {
                            border-color: #dc2626 !important;
                            background-color: #fef2f2 !important;
                            box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.22) !important;
                        }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(
                    "🔴 <strong style='color:#b91c1c;'>RESPONSABLE</strong> <span class='te-resp-pending-label'>OBLIGATORIO · EN ROJO</span>",
                    unsafe_allow_html=True,
                )
                responsable_sel = st.selectbox(
                    "RESPONSABLE_PENDIENTE",
                    lista_resp_vacia,
                    index=0,
                    format_func=lambda v: "-- SIN RELLENAR (ELEGIR) --" if v == "" else v,
                    label_visibility="collapsed",
                    key=_resp_actual_key,
                )
            else:
                st.markdown(
                    """
                    <style>
                        div[data-testid="stSelectbox"] > div[data-baseweb="select"] > div {
                            border-color: #059669 !important;
                            background-color: #ecfdf5 !important;
                            box-shadow: 0 0 0 2px rgba(5, 150, 105, 0.22) !important;
                        }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(
                    "🟢 <strong style='color:#047857;'>RESPONSABLE</strong> <span class='te-resp-ok-label'>CUMPLIMENTADO · EN VERDE</span>",
                    unsafe_allow_html=True,
                )
                responsable_sel = st.selectbox(
                    "RESPONSABLE_CUMPLIMENTADO",
                    lista_resp_vacia,
                    index=lista_resp_vacia.index(_resp_actual_val) if _resp_actual_val in lista_resp_vacia else 0,
                    format_func=lambda v: "-- SIN RELLENAR (ELEGIR) --" if v == "" else v,
                    label_visibility="collapsed",
                    key=_resp_actual_key,
                )
                st.markdown(
                    f"<div style='background:#ecfdf5;color:#047857;border:1px solid #10b981;border-radius:8px;padding:4px 8px;font-size:12px;font-weight:700;margin-top:4px;'>🟢 Cumplimentado: {responsable_sel}</div>",
                    unsafe_allow_html=True,
                )

        with st.form("form_nueva_cotizacion", clear_on_submit=True):
            r2, r3, r4, r5 = st.columns(4)
            nuevo_id = r2.text_input("ID COTIZACIÓN", value=generar_siguiente_id(q_fecha))
            centro_sel = r3.selectbox("CENTRO", CENTROS_VALIDOS, index=CENTROS_VALIDOS.index(q_centro))
            prioridad = r4.selectbox("PRIORIDAD", ["Alta", "Baja"])
            origen = r5.selectbox("ORIGEN", ["Email", "Teléfono"])

            c1, c2, c3, c4, c5 = st.columns(5)
            fecha_cot = c1.text_input("FECHA (DD/MM/YYYY)", value=q_fecha)
            mes_sel = c2.selectbox("MES", MESES_VALIDOS, index=MESES_VALIDOS.index(q_mes))
            tipo_envio_sel = c3.selectbox("TIPO DE ENVIO", ["EXPORT", "IMPORT"], index=0 if q_tipo_envio == "EXPORT" else 1)
            pais_sel = c4.text_input("PAIS", value=q_pais).upper()
            contacto = c5.text_input("CONTACTO", value=contacto_def)

            merc_def = _inferir_mercancia(q_tipo_envio, q_servicio, q_courier)
            merc_opts = list(CATALOGO_MERCANCIA.keys()) + ["OTRO / MANUAL"]
            m_sel_1, m_sel_2, m_sel_3 = st.columns(3)
            mercancia_sel = m_sel_1.selectbox(
                "TIPO DE MERCANCÍA",
                merc_opts,
                index=merc_opts.index(merc_def) if merc_def in merc_opts else 0,
                key="nueva_cot_mercancia",
            )
            if mercancia_sel in CATALOGO_MERCANCIA:
                couriers_disp = list(CATALOGO_MERCANCIA[mercancia_sel].keys()) + ["OTRO / MANUAL"]
                idx_c = couriers_disp.index(q_courier) if q_courier in couriers_disp else 0
                courier_choice = m_sel_2.selectbox("COURIER", couriers_disp, index=idx_c, key="nueva_cot_courier_sel")
                courier_sel = (
                    m_sel_2.text_input("ESCRIBIR COURIER", value=q_courier, key="nueva_cot_courier_txt").upper().strip()
                    if courier_choice == "OTRO / MANUAL"
                    else courier_choice
                )
                servicios_disp = CATALOGO_MERCANCIA[mercancia_sel].get(courier_choice, ["ESTÁNDAR"]) + ["OTRO / MANUAL"]
                idx_s = servicios_disp.index(q_servicio) if q_servicio in servicios_disp else 0
                servicio_choice = m_sel_3.selectbox("SERVICIO", servicios_disp, index=idx_s, key="nueva_cot_servicio_sel")
                servicio_sel = (
                    m_sel_3.text_input("ESCRIBIR SERVICIO", value=q_servicio, key="nueva_cot_servicio_txt").upper().strip()
                    if servicio_choice == "OTRO / MANUAL"
                    else servicio_choice
                )
            else:
                courier_sel = m_sel_2.text_input("COURIER", value=q_courier, key="nueva_cot_courier_libre").upper().strip()
                servicio_sel = m_sel_3.text_input("SERVICIO", value=q_servicio, key="nueva_cot_servicio_libre").upper().strip()

            d1, d2, d3 = st.columns(3)
            peso_sel = d1.text_input("PESO", value=q_peso).upper()
            _rango_prev_new = d2.date_input(
                "PREVISIÓN ENVÍO (RANGO DE FECHAS)",
                value=(),
                format="DD/MM/YYYY",
                key="nueva_cot_prevision_rango",
            )
            prevision_envio = _formatear_rango_prevision(_rango_prev_new)
            estado = d3.selectbox("ESTADO", ["En Curso", "Enviada"])

            m1, m2, m3, m4 = st.columns(4)
            coste_val = m1.number_input("COSTE (€)", min_value=-100000.0, max_value=1000000.0, step=1.0, value=float(q_coste))
            coste_total_val = m2.number_input("COSTE TOTAL (€)", min_value=-100000.0, max_value=1000000.0, step=1.0, value=float(q_coste_total))
            precio_val = m3.number_input("PRECIO (€)", min_value=-100000.0, max_value=1000000.0, step=1.0, value=float(q_precio))
            precio_total_val = m4.number_input("PRECIO TOTAL (€)", min_value=-100000.0, max_value=1000000.0, step=1.0, value=float(q_precio_total))

            n1, n2, n3 = st.columns(3)
            margen_val = n1.number_input("MARGEN", min_value=-100000.0, max_value=1000000.0, step=0.5, value=float(q_margen))
            margen_total_val = n2.number_input("MARGEN TOTAL", min_value=-100000.0, max_value=1000000.0, step=0.5, value=float(q_margen_total))
            with n3:
                st.markdown("🚨 **COTIZACIÓN ESPECIAL** <span class='te-critical-tag'>REVISAR</span>", unsafe_allow_html=True)
                tipo_especial = st.selectbox(
                    "COTIZACIÓN ESPECIAL (PALLET INT., FREIGHT UE/FUERA UE, DIRECTO)",
                    ["AUTO (DETECTAR)", "SÍ", "NO"],
                    label_visibility="collapsed",
                )

            det_mbe = f"{q_centro} | {q_tipo_envio} | {q_pais} | {q_servicio} | {q_courier} | {q_peso} | {q_precio_total:.2f}€"
            envios = st.text_area("DETALLES DEL ENVÍO", value=det_mbe if viene_de_mbe else "")
            comentarios = st.text_area("COMENTARIOS")
            notas = st.text_area("NOTAS GENERALES")

            submitted = st.form_submit_button("GUARDAR COTIZACIÓN")

            if submitted:
                if not str(responsable_sel).strip():
                    st.error("🔴 DEBES CUMPLIMENTAR EL CAMPO RESPONSABLE ANTES DE GUARDAR LA COTIZACIÓN.")
                elif not cliente_nombre:
                    st.error("DEBES INDICAR EL NOMBRE DEL CLIENTE.")
                else:
                    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    mes_final = mes_sel or mes_desde_fecha(fecha_cot)
                    id_final = (nuevo_id or "").upper().strip() or generar_siguiente_id(fecha_cot)
                    es_esp_final = (
                        detectar_especial_texto(
                            f"{envios} {comentarios} {notas}",
                            pais=pais_sel,
                            servicio=servicio_sel,
                            tipo_envio=tipo_envio_sel,
                        )
                        if tipo_especial == "AUTO (DETECTAR)"
                        else tipo_especial
                    )

                    fila_r = df_resp[df_resp["responsable"] == responsable_sel]
                    email_resp = fila_r.iloc[0]["email_responsable"] if not fila_r.empty else ""

                    conn = get_conn()
                    conn.execute(
                        "INSERT OR IGNORE INTO clientes (cliente, contacto_habitual, comercial) VALUES (?, ?, ?)",
                        (cliente_nombre, contacto.upper().strip(), comercial_asig),
                    )
                    cur = conn.cursor()
                    cur.execute("SELECT id_cliente FROM clientes WHERE cliente = ?", (cliente_nombre,))
                    row_c = cur.fetchone()
                    id_cli_final = row_c["id_cliente"] if row_c else id_cliente

                    importe_ref = float(precio_total_val) if precio_total_val > 0 else (float(precio_val) if precio_val > 0 else None)
                    margen_ref = float(margen_total_val) if margen_total_val != 0 else float(margen_val)

                    cur.execute(
                        """
                        INSERT INTO cotizaciones (
                            id, prioridad, fecha, mes, centro, id_cliente, cliente, contacto, comercial,
                            responsable, email_responsable, prevision_envio, estado, motivo_cierre,
                            precio_competencia, importe_ofertado, margen_pct,
                            peso, courier, tipo_envio, pais, servicio,
                            coste, coste_total, precio, precio_total, margen, margen_total,
                            es_especial, comentarios, notas_generales, origen, envios,
                            ultima_actualizacion, alerta_24h_enviada
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                        """,
                        (
                            id_final, prioridad, fecha_cot.strip(), mes_final, centro_sel,
                            id_cli_final, cliente_nombre, contacto.upper().strip(), comercial_asig,
                            responsable_sel, email_resp, str(prevision_envio or '').strip(), estado, "",
                            "", importe_ref, margen_ref,
                            peso_sel.strip(), courier_sel.strip(), tipo_envio_sel, pais_sel.strip(), servicio_sel.strip(),
                            float(coste_val), float(coste_total_val), float(precio_val), float(precio_total_val),
                            float(margen_val), float(margen_total_val),
                            es_esp_final, comentarios.upper().strip(), notas.upper().strip(),
                            origen, envios.upper().strip(), ahora,
                        ),
                    )
                    conn.commit()
                    conn.close()

                    registrar_historial(
                        id_final,
                        responsable_sel,
                        "Alta cotización",
                        "Pendiente seguimiento",
                        f"CENTRO: {centro_sel} | COMERCIAL: {comercial_asig} | ESPECIAL: {es_esp_final}",
                    )

                    ok_mail, msg_mail = notificar_nueva_cotizacion(
                        id_final,
                        cliente_nombre,
                        comercial_asig,
                        responsable_sel,
                        importe_ref,
                        es_esp_final,
                        envios.upper().strip(),
                    )
                    st.success(f"COTIZACIÓN {id_final} GUARDADA CORRECTAMENTE.")
                    if ok_mail:
                        st.info(f"✉️ {msg_mail}")
                    else:
                        st.warning(f"⚠️ AVISO CORREO: {msg_mail}")
    elif menu == "📋 SEGUIMIENTO Y ACCIONES":
        st.subheader("SEGUIMIENTO OBLIGATORIO Y CIERRES")
        df_cot = cargar_cotizaciones_df()
        df_resp = cargar_responsables_df()
        df_com = cargar_comerciales_df()

        if "editando_cot_id" not in st.session_state:
            st.session_state["editando_cot_id"] = None

        if df_cot.empty:
            st.info("NO HAY COTIZACIONES REGISTRADAS.")
        else:
            def _calcular_antiguedad_en_curso(row):
                if str(row.get("estado") or "").strip().lower() != "en curso":
                    return "⚪ Cerrada / Enviada"
                ref_dt = None
                for cand_col in ("ultima_actualizacion", "fecha"):
                    raw_val = str(row.get(cand_col) or "").strip()
                    if not raw_val:
                        continue
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                        try:
                            ref_dt = datetime.strptime(raw_val[:19] if "S" not in fmt else raw_val, fmt)
                            break
                        except ValueError:
                            continue
                    if ref_dt is not None:
                        break
                if ref_dt is None:
                    return "🟠 En Curso (revisar)"
                horas = max(0.0, (datetime.now() - ref_dt).total_seconds() / 3600.0)
                if horas >= 48.0:
                    return f"🔴 +48h ({int(horas)}h)"
                if horas >= 24.0:
                    return f"🟠 24–48h ({int(horas)}h)"
                return f"🟡 0–24h ({int(horas)}h)"

            df_cot["_semaforo_curso"] = df_cot.apply(_calcular_antiguedad_en_curso, axis=1)

            m_p1, m_p2 = st.columns([2.2, 3.8])
            solo_mis_pendientes = m_p1.checkbox("⚡ SOLO MIS PENDIENTES EN CURSO", value=False, key="chk_solo_mis_pendientes")
            pend_en_curso_total = int((df_cot["estado"].astype(str).str.strip().str.lower() == "en curso").sum())
            pend_mas_24h = int(df_cot["_semaforo_curso"].astype(str).str.startswith(("🟠", "🔴")).sum())
            m_p2.caption(
                f"En curso: **{pend_en_curso_total}** cotizaciones · Con 24h o más sin moverse: **{pend_mas_24h}**"
            )

            f1, f2, f3, f4 = st.columns(4)
            resp_opts = ["TODOS"] + sorted(df_cot["responsable"].dropna().unique().tolist())
            com_opts = ["TODOS"] + sorted(df_cot["comercial"].dropna().unique().tolist())
            centro_opts = ["TODOS"] + CENTROS_VALIDOS
            est_opts = ["TODOS", "En Curso", "Enviada", "Aceptada", "Perdida"]

            sel_resp = f1.selectbox("FILTRAR POR RESPONSABLE", resp_opts)
            sel_com = f2.selectbox("FILTRAR POR COMERCIAL", com_opts)
            sel_centro = f3.selectbox("FILTRAR POR CENTRO", centro_opts)
            sel_est = f4.selectbox("FILTRAR POR ESTADO", est_opts)

            df_view = df_cot.copy()
            if sel_resp != "TODOS":
                df_view = df_view[df_view["responsable"] == sel_resp]
            if sel_com != "TODOS":
                df_view = df_view[df_view["comercial"] == sel_com]
            if sel_centro != "TODOS":
                df_view = df_view[df_view["centro"] == sel_centro]
            if sel_est != "TODOS":
                df_view = df_view[df_view["estado"] == sel_est]
            if solo_mis_pendientes:
                df_view = df_view[df_view["estado"].astype(str).str.strip().str.lower() == "en curso"]
                if sel_resp != "TODOS":
                    df_view = df_view[df_view["responsable"] == sel_resp]

            ids_disp = df_view["id"].tolist() if not df_view.empty else df_cot["id"].tolist()

            def _etiqueta_estado_color(val):
                t = str(val or "").strip()
                tl = t.lower()
                if tl == "aceptada":
                    return f"🟢 {t}"
                if tl == "perdida":
                    return f"🔴 {t}"
                if tl == "enviada":
                    return f"🔵 {t}"
                if tl == "en curso":
                    return f"🟠 {t}"
                return f"⚪ {t or '-'}"

            def _estilo_celda_estado(val):
                tl = str(val or "").replace("🟢", "").replace("🔴", "").replace("🔵", "").replace("🟠", "").replace("⚪", "").strip().lower()
                if tl == "aceptada":
                    return "background-color: #dcfce7; color: #166534; font-weight: 800; border-radius: 6px;"
                if tl == "perdida":
                    return "background-color: #fee2e2; color: #991b1b; font-weight: 800; border-radius: 6px;"
                if tl == "enviada":
                    return "background-color: #dbeafe; color: #1e40af; font-weight: 800; border-radius: 6px;"
                if tl == "en curso":
                    return "background-color: #ffedd5; color: #9a3412; font-weight: 800; border-radius: 6px;"
                return "background-color: #f1f5f9; color: #334155; font-weight: 700;"

            st.markdown(
                """
                <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:8px 14px;margin-bottom:10px;font-size:12px;">
                    <strong style="color:#0f233c;margin-right:4px;">CÓDIGO DE COLOR DE ESTADO:</strong>
                    <span style="background:#ffedd5;color:#9a3412;border:1px solid #fdba74;padding:2px 9px;border-radius:999px;font-weight:800;">🟠 En Curso</span>
                    <span style="background:#dbeafe;color:#1e40af;border:1px solid #93c5fd;padding:2px 9px;border-radius:999px;font-weight:800;">🔵 Enviada</span>
                    <span style="background:#dcfce7;color:#166534;border:1px solid #86efac;padding:2px 9px;border-radius:999px;font-weight:800;">🟢 Aceptada</span>
                    <span style="background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;padding:2px 9px;border-radius:999px;font-weight:800;">🔴 Perdida</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            estados_limpios = df_view["estado"].apply(_limpiar_texto_tabla).tolist()
            estados_coloreados = df_view["estado"].apply(_etiqueta_estado_color).tolist()

            df_tabla_base = pd.DataFrame({
                "SELECCIONAR": [False] * len(df_view),
                "ID": df_view["id"].apply(_limpiar_texto_tabla).tolist(),
                "FECHA": df_view["fecha"].apply(_limpiar_texto_tabla).tolist(),
                "CLIENTE": df_view["cliente"].apply(_limpiar_texto_tabla).tolist(),
                "COMERCIAL": df_view["comercial"].apply(_limpiar_texto_tabla).tolist(),
                "RESPONSABLE": df_view["responsable"].apply(_limpiar_texto_tabla).tolist(),
                "TIPO": df_view["tipo_envio"].apply(_limpiar_texto_tabla).tolist(),
                "PAÍS": df_view["pais"].apply(_limpiar_texto_tabla).tolist(),
                "SERVICIO": df_view["servicio"].apply(_limpiar_texto_tabla).tolist(),
                "COURIER": df_view["courier"].apply(_limpiar_texto_tabla).tolist(),
                "PESO": df_view["peso"].apply(_limpiar_texto_tabla).tolist(),
                "PRECIO TOTAL": df_view["precio_total"].apply(_formatear_eur_tabla).tolist(),
                "MARGEN TOTAL": df_view["margen_total"].apply(_formatear_pct_tabla).tolist(),
                "ANTIGÜEDAD": df_view["_semaforo_curso"].apply(_limpiar_texto_tabla).tolist() if "_semaforo_curso" in df_view.columns else ["-"] * len(df_view),
                "ESPECIAL": df_view["es_especial"].apply(_limpiar_texto_tabla).tolist(),
                "ESTADO": estados_coloreados,
                "MOTIVO CIERRE": df_view["motivo_cierre"].apply(_limpiar_texto_tabla).tolist(),
            })

            cols_no_editables = [c for c in df_tabla_base.columns if c != "SELECCIONAR"]
            df_editada = st.data_editor(
                df_tabla_base.style.map(_estilo_celda_estado, subset=["ESTADO"]),
                use_container_width=True,
                hide_index=True,
                disabled=cols_no_editables,
                column_config={
                    "SELECCIONAR": st.column_config.CheckboxColumn(
                        "SELECCIONAR",
                        help="Marca una o varias filas para gestionarlas o eliminarlas",
                        default=False,
                    )
                },
                key="tabla_seguimiento_multiseleccion",
            )

            ids_marcados = df_editada.loc[df_editada["SELECCIONAR"] == True, "ID"].tolist() if not df_editada.empty else []
            idx_defecto_top = ids_disp.index(ids_marcados[0]) if (ids_marcados and ids_marcados[0] in ids_disp) else 0

            top_s, top_e, top_c, top_b = st.columns([2.6, 1.3, 1.2, 1.5])
            id_sel = top_s.selectbox("COTIZACIÓN ACTIVA", ids_disp, index=idx_defecto_top, key="sel_cot_top")

            if top_e.button("✏️ EDITAR COTIZACIÓN", use_container_width=True, key="btn_abrir_edicion"):
                st.session_state["editando_cot_id"] = id_sel

            ids_a_borrar = ids_marcados if ids_marcados else [id_sel]
            etiqueta_borrar = f"🗑️ ELIMINAR ({len(ids_a_borrar)})" if len(ids_marcados) > 1 else "🗑️ ELIMINAR COTIZACIÓN"

            conf_top = top_c.checkbox("CONFIRMAR BORRADO", key="conf_top_mult")
            if top_b.button(etiqueta_borrar, use_container_width=True, key="btn_top_mult"):
                if not conf_top:
                    st.warning("Marca 'CONFIRMAR BORRADO' antes de eliminar.")
                else:
                    conn_del = get_conn()
                    for _id in ids_a_borrar:
                        conn_del.execute("DELETE FROM seguimiento WHERE id_cotizacion = ?", (_id,))
                        conn_del.execute("DELETE FROM cotizaciones WHERE id = ?", (_id,))
                    conn_del.commit()
                    conn_del.close()
                    if st.session_state.get("editando_cot_id") in ids_a_borrar:
                        st.session_state["editando_cot_id"] = None
                    st.success(f"ELIMINADAS: {', '.join(ids_a_borrar)}.")
                    st.rerun()

            id_editar = st.session_state.get("editando_cot_id")
            if id_editar and id_editar in df_cot["id"].tolist():
                cot_ed = df_cot[df_cot["id"] == id_editar].iloc[0]
                st.info(f"✏️ **EDITANDO COTIZACIÓN:** `{id_editar}` — {_texto_seguro(cot_ed['cliente'])}")

                lista_resp_ed = df_resp["responsable"].tolist() if not df_resp.empty else ["ENEKO"]
                resp_act_ed = _texto_seguro(cot_ed["responsable"], lista_resp_ed[0])
                if resp_act_ed not in lista_resp_ed:
                    lista_resp_ed.insert(0, resp_act_ed)

                lista_com_ed = df_com["comercial"].tolist() if not df_com.empty else ["ENEKO"]
                com_act_ed = _texto_seguro(cot_ed["comercial"], lista_com_ed[0]).upper()
                if com_act_ed == "VASILY":
                    com_act_ed = "VASYL"
                if com_act_ed not in lista_com_ed:
                    lista_com_ed.insert(0, com_act_ed)

                centro_act_ed = normalizar_centro(_texto_seguro(cot_ed["centro"], "0329 DERIO"))
                mes_act_ed = _texto_seguro(cot_ed["mes"], mes_desde_fecha(_texto_seguro(cot_ed["fecha"]))).upper()
                if mes_act_ed not in MESES_VALIDOS:
                    mes_act_ed = MESES_VALIDOS[0]

                with st.form(f"form_editar_cot_{id_editar}"):
                    e_r1, e_r2, e_r3, e_r4, e_r5 = st.columns(5)
                    ed_cliente = e_r1.text_input("CLIENTE", value=_texto_seguro(cot_ed["cliente"])).upper().strip()
                    ed_comercial = e_r2.selectbox("COMERCIAL", lista_com_ed, index=lista_com_ed.index(com_act_ed))
                    ed_responsable = e_r3.selectbox("RESPONSABLE", lista_resp_ed, index=lista_resp_ed.index(resp_act_ed))
                    ed_centro = e_r4.selectbox("CENTRO", CENTROS_VALIDOS, index=CENTROS_VALIDOS.index(centro_act_ed))
                    pri_opts = ["Alta", "Baja"]
                    pri_act = _texto_seguro(cot_ed["prioridad"], "Alta")
                    ed_prioridad = e_r5.selectbox("PRIORIDAD", pri_opts, index=pri_opts.index(pri_act) if pri_act in pri_opts else 0)

                    e_c1, e_c2, e_c3, e_c4, e_c5 = st.columns(5)
                    ed_fecha = e_c1.text_input("FECHA (DD/MM/YYYY)", value=_texto_seguro(cot_ed["fecha"]))
                    ed_mes = e_c2.selectbox("MES", MESES_VALIDOS, index=MESES_VALIDOS.index(mes_act_ed))
                    tipo_opts = ["EXPORT", "IMPORT"]
                    tipo_act = "IMPORT" if "IMPORT" in _texto_seguro(cot_ed["tipo_envio"], "EXPORT").upper() else "EXPORT"
                    ed_tipo = e_c3.selectbox("TIPO DE ENVÍO", tipo_opts, index=tipo_opts.index(tipo_act))
                    ed_pais = e_c4.text_input("PAÍS", value=_texto_seguro(cot_ed["pais"])).upper().strip()
                    ed_contacto = e_c5.text_input("CONTACTO", value=_texto_seguro(cot_ed["contacto"])).upper().strip()

                    _ed_c_act = _texto_seguro(cot_ed["courier"]).upper().strip()
                    _ed_s_act = _texto_seguro(cot_ed["servicio"]).upper().strip()
                    _ed_m_def = _inferir_mercancia(_texto_seguro(cot_ed["tipo_envio"]), _ed_s_act, _ed_c_act, _texto_seguro(cot_ed["es_especial"]))
                    _ed_m_opts = list(CATALOGO_MERCANCIA.keys()) + ["OTRO / MANUAL"]
                    em1, em2, em3 = st.columns(3)
                    ed_merc = em1.selectbox(
                        "TIPO DE MERCANCÍA",
                        _ed_m_opts,
                        index=_ed_m_opts.index(_ed_m_def) if _ed_m_def in _ed_m_opts else 0,
                        key=f"ed_merc_{id_editar}",
                    )
                    if ed_merc in CATALOGO_MERCANCIA:
                        _ed_c_opts = list(CATALOGO_MERCANCIA[ed_merc].keys())
                        if _ed_c_act and _ed_c_act not in _ed_c_opts:
                            _ed_c_opts.append(_ed_c_act)
                        _ed_c_opts.append("OTRO / MANUAL")
                        _idx_ec = _ed_c_opts.index(_ed_c_act) if _ed_c_act in _ed_c_opts else 0
                        _ed_c_sel = em2.selectbox("COURIER", _ed_c_opts, index=_idx_ec, key=f"ed_c_sel_{id_editar}")
                        ed_courier = (
                            em2.text_input("ESCRIBIR COURIER", value=_ed_c_act, key=f"ed_c_txt_{id_editar}").upper().strip()
                            if _ed_c_sel == "OTRO / MANUAL"
                            else _ed_c_sel
                        )
                        _ed_s_opts = list(CATALOGO_MERCANCIA[ed_merc].get(_ed_c_sel, ["ESTÁNDAR"]))
                        if _ed_s_act and _ed_s_act not in _ed_s_opts:
                            _ed_s_opts.append(_ed_s_act)
                        _ed_s_opts.append("OTRO / MANUAL")
                        _idx_es = _ed_s_opts.index(_ed_s_act) if _ed_s_act in _ed_s_opts else 0
                        _ed_s_sel = em3.selectbox("SERVICIO", _ed_s_opts, index=_idx_es, key=f"ed_s_sel_{id_editar}")
                        ed_servicio = (
                            em3.text_input("ESCRIBIR SERVICIO", value=_ed_s_act, key=f"ed_s_txt_{id_editar}").upper().strip()
                            if _ed_s_sel == "OTRO / MANUAL"
                            else _ed_s_sel
                        )
                    else:
                        ed_courier = em2.text_input("COURIER", value=_ed_c_act, key=f"ed_c_lib_{id_editar}").upper().strip()
                        ed_servicio = em3.text_input("SERVICIO", value=_ed_s_act, key=f"ed_s_lib_{id_editar}").upper().strip()

                    e_d1, e_d2, e_d3 = st.columns(3)
                    ed_peso = e_d1.text_input("PESO", value=_texto_seguro(cot_ed["peso"])).upper().strip()
                    _prev_actual_txt = _texto_seguro(cot_ed["prevision_envio"]).strip()
                    _rango_prev_ed = e_d2.date_input(
                        "PREVISIÓN ENVÍO (RANGO)",
                        value=(),
                        format="DD/MM/YYYY",
                        key=f"ed_prev_rango_{id_editar}",
                    )
                    _rango_prev_ed_str = _formatear_rango_prevision(_rango_prev_ed)
                    ed_prevision = (_rango_prev_ed_str or _prev_actual_txt).strip()
                    if _prev_actual_txt and not _rango_prev_ed_str:
                        e_d2.caption(f"Actual: {_prev_actual_txt}")
                    est_ed_opts = ["En Curso", "Enviada", "Aceptada", "Perdida"]
                    est_ed_act = _texto_seguro(cot_ed["estado"], "En Curso")
                    ed_estado = e_d3.selectbox("ESTADO", est_ed_opts, index=est_ed_opts.index(est_ed_act) if est_ed_act in est_ed_opts else 0)

                    e_m1, e_m2, e_m3, e_m4 = st.columns(4)
                    ed_coste = e_m1.number_input("COSTE (€)", min_value=-100000.0, max_value=1000000.0, step=1.0, value=a_float_seguro(cot_ed["coste"], 0.0))
                    ed_coste_total = e_m2.number_input("COSTE TOTAL (€)", min_value=-100000.0, max_value=1000000.0, step=1.0, value=a_float_seguro(cot_ed["coste_total"], 0.0))
                    ed_precio = e_m3.number_input("PRECIO (€)", min_value=-100000.0, max_value=1000000.0, step=1.0, value=a_float_seguro(cot_ed["precio"], 0.0))
                    ed_precio_total = e_m4.number_input("PRECIO TOTAL (€)", min_value=-100000.0, max_value=1000000.0, step=1.0, value=a_float_seguro(cot_ed["precio_total"], 0.0))

                    e_n1, e_n2, e_n3 = st.columns(3)
                    ed_margen = e_n1.number_input("MARGEN", min_value=-100000.0, max_value=1000000.0, step=0.5, value=a_float_seguro(cot_ed["margen"], 0.0))
                    ed_margen_total = e_n2.number_input("MARGEN TOTAL", min_value=-100000.0, max_value=1000000.0, step=0.5, value=a_float_seguro(cot_ed["margen_total"], 0.0))
                    esp_opts = ["AUTO (DETECTAR)", "SÍ", "NO"]
                    esp_act = _texto_seguro(cot_ed["es_especial"], "AUTO (DETECTAR)")
                    ed_especial = e_n3.selectbox("COTIZACIÓN ESPECIAL", esp_opts, index=esp_opts.index(esp_act) if esp_act in esp_opts else 0)

                    ed_envios = st.text_area("DETALLES DEL ENVÍO", value=_texto_seguro(cot_ed["envios"]))
                    ed_comentarios = st.text_area("COMENTARIOS", value=_texto_seguro(cot_ed["comentarios"]))
                    ed_notas = st.text_area("NOTAS GENERALES", value=_texto_seguro(cot_ed["notas_generales"]))

                    b_save_ed, b_cancel_ed = st.columns(2)
                    guardar_ed = b_save_ed.form_submit_button("💾 GUARDAR CAMBIOS DE COTIZACIÓN")
                    cancelar_ed = b_cancel_ed.form_submit_button("✖ CERRAR EDICIÓN")

                    if cancelar_ed:
                        st.session_state["editando_cot_id"] = None
                        st.rerun()

                    if guardar_ed:
                        if not ed_cliente:
                            st.error("EL NOMBRE DEL CLIENTE NO PUEDE ESTAR VACÍO.")
                        else:
                            ahora_ed = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            esp_final_ed = (
                                detectar_especial_texto(
                                    f"{ed_envios} {ed_comentarios} {ed_notas}",
                                    pais=ed_pais,
                                    servicio=ed_servicio,
                                    tipo_envio=ed_tipo,
                                )
                                if ed_especial == "AUTO (DETECTAR)"
                                else ed_especial
                            )
                            fila_r_ed = df_resp[df_resp["responsable"] == ed_responsable]
                            email_resp_ed = fila_r_ed.iloc[0]["email_responsable"] if not fila_r_ed.empty else _texto_seguro(cot_ed["email_responsable"])

                            imp_ref_ed = float(ed_precio_total) if ed_precio_total > 0 else (float(ed_precio) if ed_precio > 0 else None)
                            mrg_ref_ed = float(ed_margen_total) if ed_margen_total != 0 else float(ed_margen)

                            conn_ed = get_conn()
                            conn_ed.execute(
                                """
                                UPDATE cotizaciones
                                SET cliente = ?, comercial = ?, responsable = ?, email_responsable = ?,
                                    centro = ?, prioridad = ?, fecha = ?, mes = ?, tipo_envio = ?,
                                    pais = ?, contacto = ?, peso = ?, courier = ?, servicio = ?,
                                    prevision_envio = ?, estado = ?,
                                    coste = ?, coste_total = ?, precio = ?, precio_total = ?,
                                    margen = ?, margen_total = ?, importe_ofertado = ?, margen_pct = ?,
                                    es_especial = ?, envios = ?, comentarios = ?, notas_generales = ?,
                                    ultima_actualizacion = ?
                                WHERE id = ?
                                """,
                                (
                                    ed_cliente, ed_comercial, ed_responsable, email_resp_ed,
                                    ed_centro, ed_prioridad, ed_fecha.strip(), ed_mes, ed_tipo,
                                    ed_pais, ed_contacto, ed_peso, ed_courier, ed_servicio,
                                    ed_prevision, ed_estado,
                                    float(ed_coste), float(ed_coste_total), float(ed_precio), float(ed_precio_total),
                                    float(ed_margen), float(ed_margen_total), imp_ref_ed, mrg_ref_ed,
                                    esp_final_ed, ed_envios.upper().strip(), ed_comentarios.upper().strip(), ed_notas.upper().strip(),
                                    ahora_ed, id_editar,
                                ),
                            )
                            conn_ed.commit()
                            conn_ed.close()

                            registrar_historial(
                                id_editar,
                                ed_responsable,
                                "Edición cotización",
                                ed_estado,
                                f"PRECIO TOTAL: {ed_precio_total:.2f}€ | MARGEN TOTAL: {ed_margen_total:.2f}% | ESPECIAL: {esp_final_ed}",
                            )
                            st.session_state["editando_cot_id"] = None
                            st.success(f"COTIZACIÓN {id_editar} ACTUALIZADA.")
                            st.rerun()
            st.divider()
            st.markdown("### REGISTRAR ACCIÓN (LLAMADA O CORREO) Y ESTADO")
            cot_act = df_cot[df_cot["id"] == id_sel].iloc[0]

            mostrar_aviso_precios_cliente(df_cot, cot_act["cliente"])

            with st.form("form_seguimiento"):
                lista_resp = df_resp["responsable"].tolist() if not df_resp.empty else ["ENEKO"]
                idx_r = lista_resp.index(cot_act["responsable"]) if cot_act["responsable"] in lista_resp else 0

                s1, s2, s3 = st.columns(3)
                quien_actua = s1.selectbox("RESPONSABLE QUE REGISTRA LA ACCIÓN", lista_resp, index=idx_r)
                canal_act = s2.selectbox("CANAL DE CONTACTO", ["Llamada telefónica", "Correo enviado"])
                resultado_act = s3.selectbox(
                    "RESULTADO DEL ENVÍO",
                    ["Pendiente / Sigue adelante", "Sí, envío aceptado", "No, envío rechazado / perdido"],
                )

                e1, e2, e3 = st.columns(3)
                estados_lista = ["En Curso", "Enviada", "Aceptada", "Perdida"]
                idx_e = estados_lista.index(cot_act["estado"]) if cot_act["estado"] in estados_lista else 0
                nuevo_estado = e1.selectbox("ESTADO FINAL", estados_lista, index=idx_e)

                motivos_lista = [
                    "", "PRECIO CARO", "COMPETENCIA MEJOR PRECIO", "TIEMPO DE TRÁNSITO / PLAZO",
                    "CANCELADO POR CLIENTE", "SIN RESPUESTA", "OTRO",
                ]
                motivo_cierre = e2.selectbox("MOTIVO DE RECHAZO (SI ES PERDIDA)", motivos_lista)
                if motivo_cierre in ("PRECIO CARO", "COMPETENCIA MEJOR PRECIO"):
                    _n_prev_cli = int((df_cot["cliente"] == cot_act["cliente"]).sum())
                    if _n_prev_cli > 1:
                        st.caption(
                            f"🔗 Sinergia: **{cot_act['cliente']}** tiene **{_n_prev_cli}** cotizaciones registradas; "
                            "conviene contrastar precios y condiciones previas antes de cerrar como perdida."
                        )
                precio_comp = e3.text_input("PRECIO COMPETENCIA / ALTERNATIVA (€)", value=str(cot_act["precio_competencia"] or "")).upper()

                detalle_act = st.text_area("DETALLE DE LA LLAMADA O CORREO (OBLIGATORIO)")

                if st.form_submit_button("GUARDAR SEGUIMIENTO"):
                    if nuevo_estado == "Perdida" and not motivo_cierre:
                        st.error("SI MARCAS LA COTIZACIÓN COMO PERDIDA, DEBES ELEGIR UN MOTIVO DE RECHAZO.")
                    elif not detalle_act.strip():
                        st.error("DEBES ANOTAR QUÉ SE HABLÓ O QUÉ CORREO SE ENVIÓ.")
                    else:
                        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        conn = get_conn()
                        conn.execute(
                            """
                            UPDATE cotizaciones
                            SET estado = ?, motivo_cierre = ?, precio_competencia = ?,
                                ultima_actualizacion = ?, alerta_24h_enviada = 0
                            WHERE id = ?
                            """,
                            (nuevo_estado, motivo_cierre, precio_comp.strip(), ahora, id_sel),
                        )
                        conn.commit()
                        conn.close()

                        registrar_historial(
                            id_sel,
                            quien_actua,
                            canal_act,
                            resultado_act,
                            f"{detalle_act.upper().strip()} | MOTIVO: {motivo_cierre or '-'} | COMP: {precio_comp.strip() or '-'}",
                        )
                        st.success("SEGUIMIENTO GUARDADO.")
                        st.rerun()

            st.markdown("### HISTORIAL DE SEGUIMIENTO")
            conn = get_conn()
            df_hist = pd.read_sql_query(
                "SELECT fecha_hora, usuario, canal_accion, resultado_envio, detalle FROM seguimiento WHERE id_cotizacion = ? ORDER BY id_log DESC",
                conn,
                params=(id_sel,),
            )
            conn.close()
            st.dataframe(df_hist, use_container_width=True, hide_index=True)

    elif menu == "📊 PANEL Y RECHAZOS":
        st.subheader("PANEL DE RESULTADOS, SINERGIAS Y MOTIVOS DE RECHAZO")
        df_cot = cargar_cotizaciones_df()

        if df_cot.empty:
            st.info("SIN DATOS.")
        else:
            df_p = df_cot.copy()
            for col_txt in [
                "cliente", "comercial", "responsable", "centro", "mes",
                "tipo_envio", "pais", "servicio", "courier", "es_especial",
                "estado", "motivo_cierre", "precio_competencia",
            ]:
                if col_txt not in df_p.columns:
                    df_p[col_txt] = ""
                df_p[col_txt] = df_p[col_txt].fillna("").astype(str).str.strip()
                if col_txt in ("cliente", "comercial", "responsable", "mes", "tipo_envio", "pais", "servicio", "courier", "es_especial", "motivo_cierre"):
                    df_p[col_txt] = df_p[col_txt].str.upper()
                    if col_txt == "comercial":
                        df_p.loc[df_p[col_txt] == "VASILY", col_txt] = "VASYL"

            for col_num in ["precio_total", "coste_total", "margen_total"]:
                if col_num not in df_p.columns:
                    df_p[col_num] = 0.0
                df_p[col_num] = pd.to_numeric(df_p[col_num], errors="coerce").fillna(0.0)

            total = len(df_p)
            aceptadas = int((df_p["estado"] == "Aceptada").sum())
            perdidas = int((df_p["estado"] == "Perdida").sum())
            especiales = int((df_p["es_especial"].isin(["SÍ", "SI"])).sum())
            cerradas = aceptadas + perdidas
            tasa_exito = (aceptadas / cerradas * 100.0) if cerradas > 0 else 0.0

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("TOTAL COTIZACIONES", total)
            k2.metric("ACEPTADAS", aceptadas)
            k3.metric("PERDIDAS", perdidas)
            k4.metric("ESPECIALES", especiales)
            k5.metric("ÉXITO EN CIERRES", f"{tasa_exito:.1f} %".replace(".", ","))

            st.divider()
            st.markdown("### 🔗 SINERGIA 1: CLIENTES RECURRENTES Y CRUCES DE EQUIPO")
            st.caption("Identifica clientes con varias cotizaciones y cruces de comerciales o responsables para unificar criterios, tarifas y seguimiento.")

            grp_cli = (
                df_p[df_p["cliente"] != ""]
                .groupby("cliente", as_index=False)
                .agg(
                    cotizaciones=("id", "count"),
                    aceptadas=("estado", lambda s: int((s == "Aceptada").sum())),
                    perdidas=("estado", lambda s: int((s == "Perdida").sum())),
                    en_curso_enviadas=("estado", lambda s: int(s.isin(["En Curso", "Enviada"]).sum())),
                    especiales=("es_especial", lambda s: int(s.isin(["SÍ", "SI"]).sum())),
                    importe_total_eur=("precio_total", "sum"),
                    comerciales=("comercial", lambda s: ", ".join(sorted({x for x in s if x}))),
                    num_comerciales=("comercial", lambda s: len({x for x in s if x})),
                    responsables=("responsable", lambda s: ", ".join(sorted({x for x in s if x}))),
                    num_responsables=("responsable", lambda s: len({x for x in s if x})),
                )
            )
            grp_cli["cruce_equipo"] = grp_cli.apply(
                lambda r: "SÍ (REVISAR SINERGIA)" if (r["num_comerciales"] > 1 or r["num_responsables"] > 1) else "NO",
                axis=1,
            )
            grp_cli = grp_cli.sort_values(by=["cotizaciones", "aceptadas"], ascending=[False, False])

            sc1, sc2 = st.columns([1.4, 1.0])
            with sc1:
                st.markdown("#### TOP CLIENTES POR VOLUMEN DE COTIZACIONES")
                top_cli_chart = grp_cli.head(15).set_index("cliente")[["aceptadas", "perdidas", "en_curso_enviadas"]]
                if not top_cli_chart.empty:
                    st.bar_chart(top_cli_chart)
                else:
                    st.info("Sin clientes suficientes para graficar.")

            with sc2:
                st.markdown("#### CRUCES DE COMERCIALES / RESPONSABLES")
                cruces_df = grp_cli[grp_cli["cruce_equipo"].str.startswith("SÍ")]
                st.metric("CLIENTES CON CRUCE DE EQUIPO", len(cruces_df))
                if not cruces_df.empty:
                    st.dataframe(
                        cruces_df[["cliente", "cotizaciones", "aceptadas", "perdidas", "comerciales", "responsables"]],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("No hay clientes compartidos entre varios comerciales o responsables.")

            st.markdown("#### TABLA DE SINERGIAS POR CLIENTE (≥ 2 COTIZACIONES)")
            multi_cli = grp_cli[grp_cli["cotizaciones"] >= 2]
            if not multi_cli.empty:
                st.dataframe(
                    multi_cli[[
                        "cliente", "cotizaciones", "aceptadas", "perdidas",
                        "en_curso_enviadas", "especiales", "importe_total_eur",
                        "cruce_equipo", "comerciales", "responsables",
                    ]],
                    use_container_width=True,
                    hide_index=True,
                )
                cli_insp = st.selectbox(
                    "INSPECCIONAR HISTORIAL DE UN CLIENTE RECURRENTE",
                    ["-- SELECCIONAR --"] + multi_cli["cliente"].tolist(),
                    key="sinergia_sel_cliente",
                )
                if cli_insp != "-- SELECCIONAR --":
                    det_cli = df_p[df_p["cliente"] == cli_insp][
                        [c for c in [
                            "id", "fecha", "mes", "centro", "comercial", "responsable",
                            "tipo_envio", "pais", "servicio", "courier", "peso",
                            "es_especial", "estado", "precio_total", "margen_total",
                            "precio_competencia", "motivo_cierre",
                        ] if c in df_p.columns]
                    ]
                    st.dataframe(det_cli, use_container_width=True, hide_index=True)
            else:
                st.info("Aún no hay clientes con 2 o más cotizaciones registradas.")

            st.divider()
            st.markdown("### 👥 SINERGIA 2: RENDIMIENTO POR COMERCIAL Y RESPONSABLE")
            sr1, sr2 = st.columns(2)

            with sr1:
                st.markdown("#### COTIZACIONES POR COMERCIAL")
                piv_com = pd.crosstab(df_p["comercial"].replace("", "SIN COMERCIAL"), df_p["estado"])
                if not piv_com.empty:
                    st.bar_chart(piv_com)
                res_com = (
                    df_p.groupby(df_p["comercial"].replace("", "SIN COMERCIAL"), as_index=False)
                    .agg(
                        total=("id", "count"),
                        aceptadas=("estado", lambda s: int((s == "Aceptada").sum())),
                        perdidas=("estado", lambda s: int((s == "Perdida").sum())),
                        importe_eur=("precio_total", "sum"),
                    )
                    .sort_values(by="total", ascending=False)
                )
                st.dataframe(res_com, use_container_width=True, hide_index=True)

            with sr2:
                st.markdown("#### COTIZACIONES POR RESPONSABLE")
                piv_resp = pd.crosstab(df_p["responsable"].replace("", "SIN RESPONSABLE"), df_p["estado"])
                if not piv_resp.empty:
                    st.bar_chart(piv_resp)
                res_resp = (
                    df_p.groupby(df_p["responsable"].replace("", "SIN RESPONSABLE"), as_index=False)
                    .agg(
                        total=("id", "count"),
                        aceptadas=("estado", lambda s: int((s == "Aceptada").sum())),
                        perdidas=("estado", lambda s: int((s == "Perdida").sum())),
                        importe_eur=("precio_total", "sum"),
                    )
                    .sort_values(by="total", ascending=False)
                )
                st.dataframe(res_resp, use_container_width=True, hide_index=True)

            st.divider()
            st.markdown("### 🌍 SINERGIA 3: RUTAS, SERVICIOS, COURIERS Y COTIZACIONES ESPECIALES")
            st1, st2 = st.columns(2)

            with st1:
                st.markdown("#### TIPO DE ENVÍO (EXPORT / IMPORT) Y ESPECIALES")
                piv_tipo = pd.crosstab(df_p["tipo_envio"].replace("", "SIN TIPO"), df_p["estado"])
                if not piv_tipo.empty:
                    st.bar_chart(piv_tipo)

                piv_esp = pd.crosstab(df_p["es_especial"].replace("", "NO"), df_p["estado"])
                if not piv_esp.empty:
                    st.markdown("#### ESPECIALES (SÍ / NO) POR ESTADO")
                    st.bar_chart(piv_esp)

            with st2:
                st.markdown("#### TOP PAÍSES / DESTINOS")
                paises_no_vacios = df_p[df_p["pais"] != ""]
                if not paises_no_vacios.empty:
                    top_pais = pd.crosstab(paises_no_vacios["pais"], paises_no_vacios["estado"])
                    top_pais["_tot"] = top_pais.sum(axis=1)
                    top_pais = top_pais.sort_values(by="_tot", ascending=False).head(12).drop(columns=["_tot"])
                    st.bar_chart(top_pais)
                else:
                    st.info("No hay países informados todavía.")

                st.markdown("#### TOP SERVICIOS Y COURIERS")
                serv_no_vacios = df_p[df_p["servicio"] != ""]
                if not serv_no_vacios.empty:
                    st.dataframe(
                        serv_no_vacios.groupby(["servicio", "courier"], as_index=False)
                        .agg(
                            cotizaciones=("id", "count"),
                            aceptadas=("estado", lambda s: int((s == "Aceptada").sum())),
                            perdidas=("estado", lambda s: int((s == "Perdida").sum())),
                        )
                        .sort_values(by="cotizaciones", ascending=False)
                        .head(12),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("No hay servicios informados todavía.")

            st.divider()
            st.markdown("### 📈 SINERGIA 4: EVOLUCIÓN MENSUAL Y MOTIVOS DE RECHAZO")
            sm1, sm2 = st.columns(2)

            with sm1:
                st.markdown("#### EVOLUCIÓN POR MES")
                mes_ord = [m for m in MESES_VALIDOS if m in set(df_p["mes"])]
                otros_mes = sorted([m for m in set(df_p["mes"]) if m and m not in MESES_VALIDOS])
                orden_mes_final = mes_ord + otros_mes
                if orden_mes_final:
                    piv_mes = pd.crosstab(df_p["mes"], df_p["estado"]).reindex(orden_mes_final).dropna(how="all")
                    if not piv_mes.empty:
                        st.bar_chart(piv_mes)
                    else:
                        st.info("Sin datos mensuales para graficar.")
                else:
                    st.info("No hay meses registrados.")

            with sm2:
                st.markdown("#### MOTIVOS DE RECHAZO (COTIZACIONES PERDIDAS)")
                df_perd = df_p[df_p["estado"] == "Perdida"]
                motivos_validos = df_perd[df_perd["motivo_cierre"] != ""]["motivo_cierre"]
                if not motivos_validos.empty:
                    st.bar_chart(motivos_validos.value_counts())
                else:
                    st.info("Aún no hay motivos de rechazo rellenados en las cotizaciones perdidas.")

            st.divider()
            st.markdown("### 🎯 SINERGIA 5: ACCIONES INMEDIATAS (REVISIÓN DE PRECIOS Y DATOS PENDIENTES)")
            perd_sin_motivo = int((df_perd["motivo_cierre"] == "").sum()) if not df_perd.empty else 0
            perd_sin_comp = int((df_perd["precio_competencia"] == "").sum()) if not df_perd.empty else 0

            a1, a2 = st.columns(2)
            a1.warning(f"PERDIDAS SIN MOTIVO DE RECHAZO: **{perd_sin_motivo}**")
            a2.warning(f"PERDIDAS SIN PRECIO COMPETENCIA: **{perd_sin_comp}**")

            st.markdown("#### COTIZACIONES PERDIDAS PARA REVISIÓN DE PRECIOS")
            cols_perd = [
                c for c in [
                    "id", "centro", "fecha", "cliente", "comercial", "responsable",
                    "tipo_envio", "pais", "servicio", "es_especial",
                    "precio_total", "precio_competencia", "motivo_cierre",
                ] if c in df_perd.columns
            ]
            st.dataframe(df_perd[cols_perd], use_container_width=True, hide_index=True)

            st.divider()
            st.markdown("### 💰 SINERGIA 6: IMPORTE OFERTADO VS. MARGEN POR SERVICIO Y PAÍS")
            df_p["_tipo_merc_inf"] = df_p.apply(
                lambda r: _inferir_mercancia(r.get("tipo_envio", ""), r.get("servicio", ""), r.get("courier", ""), r.get("es_especial", "")),
                axis=1,
            )
            _m_col1, _m_col2 = st.columns(2)
            with _m_col1:
                st.markdown("#### POR TIPO DE MERCANCÍA")
                res_merc_imp = (
                    df_p.groupby("_tipo_merc_inf", as_index=False)
                    .agg(
                        cotizaciones=("id", "count"),
                        importe_total_eur=("precio_total", "sum"),
                        importe_aceptado_eur=("precio_total", lambda s: float(s[df_p.loc[s.index, "estado"] == "Aceptada"].sum())),
                        margen_medio=("margen_total", "mean"),
                    )
                    .sort_values(by="importe_total_eur", ascending=False)
                )
                res_merc_imp["margen_medio"] = res_merc_imp["margen_medio"].round(2)
                st.dataframe(res_merc_imp, use_container_width=True, hide_index=True)

            with _m_col2:
                st.markdown("#### TOP PAÍSES POR IMPORTE OFERTADO")
                df_pais_ok = df_p[df_p["pais"] != ""]
                if not df_pais_ok.empty:
                    res_pais_imp = (
                        df_pais_ok.groupby("pais", as_index=False)
                        .agg(
                            cotizaciones=("id", "count"),
                            importe_total_eur=("precio_total", "sum"),
                            importe_aceptado_eur=("precio_total", lambda s: float(s[df_pais_ok.loc[s.index, "estado"] == "Aceptada"].sum())),
                            margen_medio=("margen_total", "mean"),
                        )
                        .sort_values(by="importe_total_eur", ascending=False)
                        .head(10)
                    )
                    res_pais_imp["margen_medio"] = res_pais_imp["margen_medio"].round(2)
                    st.dataframe(res_pais_imp, use_container_width=True, hide_index=True)
                else:
                    st.info("Sin países informados todavía.")

            csv_panel = df_p.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "📥 EXPORTAR DATOS DEL PANEL A CSV",
                data=csv_panel,
                file_name=f"panel_sinergias_cotizaciones_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                key="btn_export_panel_csv",
            )
    elif menu == "📈 DASHBOARD TIEMPO REAL":
        st.subheader("DASHBOARD EN TIEMPO REAL — COTIZACIONES Y METAS 2026")
        st.caption("Actualización automática en vivo desde la base de datos SQLite al registrar, editar o cerrar cotizaciones.")

        df_cot_live = cargar_cotizaciones_df()

        if df_cot_live.empty:
            st.info("NO HAY COTIZACIONES REGISTRADAS EN TIEMPO REAL.")
        else:
            df_d = df_cot_live.copy()

            # Normalizar columnas de texto
            for c_txt in ["cliente", "comercial", "responsable", "centro", "mes", "fecha", "tipo_envio", "pais", "servicio", "courier", "es_especial", "estado", "motivo_cierre", "envios", "comentarios"]:
                if c_txt not in df_d.columns:
                    df_d[c_txt] = ""
                df_d[c_txt] = df_d[c_txt].fillna("").astype(str).str.strip()
                if c_txt in ("cliente", "comercial", "responsable", "mes", "tipo_envio", "pais", "servicio", "courier", "es_especial", "motivo_cierre", "envios", "comentarios"):
                    df_d[c_txt] = df_d[c_txt].str.upper()

            # Derivar mes si viene vacío
            mask_sin_mes = df_d["mes"] == ""
            if mask_sin_mes.any():
                df_d.loc[mask_sin_mes, "mes"] = df_d.loc[mask_sin_mes, "fecha"].apply(mes_desde_fecha)

            # Calcular importe efectivo en EUR (prioriza precio_total > 0, luego precio > 0, luego importe_ofertado)
            def _importe_fila(row):
                pt = a_float_seguro(row.get("precio_total"), 0.0)
                if pt > 0:
                    return pt
                pr = a_float_seguro(row.get("precio"), 0.0)
                if pr > 0:
                    return pr
                imp = a_float_seguro(row.get("importe_ofertado"), 0.0)
                return imp if imp > 0 else 0.0

            df_d["importe_eur"] = df_d.apply(_importe_fila, axis=1)
            df_d["margen_num"] = df_d["margen_total"].apply(lambda x: a_float_seguro(x, 0.0)) if "margen_total" in df_d.columns else 0.0

            # Clasificación en Especiales, Grupaje y No Especiales
            def _segmento_fila(row):
                txt_comb = f"{row.get('servicio', '')} {row.get('tipo_envio', '')} {row.get('courier', '')} {row.get('envios', '')} {row.get('comentarios', '')}"
                if "GRUPAJE" in txt_comb:
                    return "GRUPAJE"
                if row.get("es_especial", "") in ("SÍ", "SI"):
                    return "ESPECIALES"
                return "NO ESPECIALES"

            df_d["segmento"] = df_d.apply(_segmento_fila, axis=1)

            # Filtros rápidos en tiempo real
            df1, df2, df3, df4 = st.columns(4)
            mes_filtro_opts = ["TODOS LOS MESES"] + [m for m in MESES_VALIDOS if m in set(df_d["mes"])] + sorted([m for m in set(df_d["mes"]) if m and m not in MESES_VALIDOS])
            sel_mes_d = df1.selectbox("MES (TIEMPO REAL)", mes_filtro_opts, key="dash_live_mes")
            sel_seg_d = df2.selectbox("SEGMENTO", ["TODOS", "ESPECIALES", "NO ESPECIALES", "GRUPAJE"], key="dash_live_seg")
            sel_com_d = df3.selectbox("COMERCIAL", ["TODOS"] + sorted([x for x in df_d["comercial"].unique() if x]), key="dash_live_com")
            _todos_resp = set(x for x in df_d["responsable"].unique() if x)
            for _fn_name, _col_name in [
                ("cargar_responsables_df", "responsable"),
                ("cargar_comerciales_df", "comercial"),
                ("cargar_direccion_df", "persona"),
            ]:
                if _fn_name in globals():
                    try:
                        _df_tmp = globals()[_fn_name]()
                        if _df_tmp is not None and not _df_tmp.empty and _col_name in _df_tmp.columns:
                            for _v in _df_tmp[_col_name].dropna().astype(str):
                                _vv = _v.strip().upper()
                                if _vv == "VASILY":
                                    _vv = "VASYL"
                                if _vv:
                                    _todos_resp.add(_vv)
                    except Exception:
                        pass
            for _extra_p in ["VASYL", "BEGOÑA", "FRANCINE", "IMANOL", "JULEN", "OLGA", "MARIA", "NAIARA LLAMAS", "NAIARA ZARATE", "ENEKO", "ELENA", "EMILIO", "IBON", "SILVIA FERNANDEZ", "BEATRIZ"]:
                _todos_resp.add(_extra_p)
            sel_resp_d = df4.selectbox("RESPONSABLE", ["TODOS"] + sorted(_todos_resp), key="dash_live_resp")

            df_f = df_d.copy()
            if sel_mes_d != "TODOS LOS MESES":
                df_f = df_f[df_f["mes"] == sel_mes_d]
            if sel_seg_d != "TODOS":
                df_f = df_f[df_f["segmento"] == sel_seg_d]
            if sel_com_d != "TODOS":
                df_f = df_f[df_f["comercial"] == sel_com_d]
            if sel_resp_d != "TODOS":
                df_f = df_f[df_f["responsable"] == sel_resp_d]

            # KPIs principales en tiempo real
            n_tot = len(df_f)
            imp_tot = float(df_f["importe_eur"].sum())
            df_acep = df_f[df_f["estado"] == "Aceptada"]
            n_acep = len(df_acep)
            imp_acep = float(df_acep["importe_eur"].sum())
            df_pend = df_f[df_f["estado"].isin(["En Curso", "Enviada"])]
            n_pend = len(df_pend)
            imp_pend = float(df_pend["importe_eur"].sum())

            ratio_num_pct = (n_acep / n_tot * 100.0) if n_tot > 0 else 0.0
            ratio_imp_pct = (imp_acep / imp_tot * 100.0) if imp_tot > 0 else 0.0

            k_a, k_b, k_c, k_d, k_e, k_f = st.columns(6)
            k_a.metric("Nº TOTAL", n_tot)
            k_b.metric("IMPORTE TOTAL", f"{imp_tot:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
            k_c.metric("Nº ACEPTADOS", n_acep)
            k_d.metric("IMPORTE ACEPTADOS", f"{imp_acep:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
            k_e.metric("RATIO ACEPTADOS Nº", f"{ratio_num_pct:.1f} %".replace(".", ","))
            k_f.metric("RATIO ACEPTADOS €", f"{ratio_imp_pct:.1f} %".replace(".", ","))

            st.caption(f"Pendientes activos en vista: **{n_pend}** cotizaciones por un importe de **{imp_pend:,.2f} €**".replace(",", "X").replace(".", ",").replace("X", "."))

            st.divider()
            st.markdown("### 📦 INDICADORES EN VIVO POR SEGMENTO (ESPECIALES / NO ESPECIALES / GRUPAJE)")

            seg_rows = []
            metas_seg = {
                "ESPECIALES": {"meta_imp": 700000.0, "meta_num": 356, "meta_acep_imp": 217000.0, "meta_r_num": 50.0, "meta_r_imp": 31.0},
                "NO ESPECIALES": {"meta_imp": 400000.0, "meta_num": 206, "meta_acep_imp": 280000.0, "meta_r_num": 80.0, "meta_r_imp": 70.0},
                "GRUPAJE": {"meta_imp": 98000.0, "meta_num": 204, "meta_acep_imp": 30380.0, "meta_r_num": 40.0, "meta_r_imp": 31.0},
            }

            for seg_name in ["ESPECIALES", "NO ESPECIALES", "GRUPAJE"]:
                sub_s = df_f[df_f["segmento"] == seg_name]
                sub_a = sub_s[sub_s["estado"] == "Aceptada"]
                sub_p = sub_s[sub_s["estado"].isin(["En Curso", "Enviada"])]

                c_tot = len(sub_s)
                i_tot = float(sub_s["importe_eur"].sum())
                c_ace = len(sub_a)
                i_ace = float(sub_a["importe_eur"].sum())
                c_pen = len(sub_p)
                i_pen = float(sub_p["importe_eur"].sum())
                r_num = (c_ace / c_tot * 100.0) if c_tot > 0 else 0.0
                r_imp = (i_ace / i_tot * 100.0) if i_tot > 0 else 0.0
                m_cfg = metas_seg[seg_name]

                seg_rows.append({
                    "SEGMENTO": seg_name,
                    "Nº TOTAL": c_tot,
                    "META Nº": m_cfg["meta_num"],
                    "IMPORTE TOTAL (€)": round(i_tot, 2),
                    "META IMPORTE (€)": m_cfg["meta_imp"],
                    "Nº ACEPTADOS": c_ace,
                    "IMPORTE ACEPTADOS (€)": round(i_ace, 2),
                    "META ACEPT. (€)": m_cfg["meta_acep_imp"],
                    "RATIO Nº (%)": round(r_num, 1),
                    "META RATIO Nº (%)": m_cfg["meta_r_num"],
                    "RATIO € (%)": round(r_imp, 1),
                    "META RATIO € (%)": m_cfg["meta_r_imp"],
                    "Nº PENDIENTES": c_pen,
                    "PENDIENTES (€)": round(i_pen, 2),
                })

            df_seg_res = pd.DataFrame(seg_rows)
            st.dataframe(df_seg_res, use_container_width=True, hide_index=True)

            g_s1, g_s2 = st.columns(2)
            with g_s1:
                st.markdown("#### IMPORTE TOTAL VS. ACEPTADO POR SEGMENTO (€)")
                st.bar_chart(df_seg_res.set_index("SEGMENTO")[["IMPORTE TOTAL (€)", "IMPORTE ACEPTADOS (€)"]])
            with g_s2:
                st.markdown("#### Nº TOTAL VS. ACEPTADOS POR SEGMENTO")
                st.bar_chart(df_seg_res.set_index("SEGMENTO")[["Nº TOTAL", "Nº ACEPTADOS"]])

            st.divider()
            st.markdown("### 📅 EVOLUCIÓN MENSUAL EN TIEMPO REAL (ENERO – DICIEMBRE)")

            meses_presentes = [m for m in MESES_VALIDOS if m in set(df_d["mes"])] + sorted([m for m in set(df_d["mes"]) if m and m not in MESES_VALIDOS])
            if meses_presentes:
                mensual_rows = []
                for m_nom in meses_presentes:
                    sub_m = df_d[df_d["mes"] == m_nom]
                    if sel_seg_d != "TODOS":
                        sub_m = sub_m[sub_m["segmento"] == sel_seg_d]
                    if sel_com_d != "TODOS":
                        sub_m = sub_m[sub_m["comercial"] == sel_com_d]
                    if sel_resp_d != "TODOS":
                        sub_m = sub_m[sub_m["responsable"] == sel_resp_d]

                    m_ace = sub_m[sub_m["estado"] == "Aceptada"]
                    m_pen = sub_m[sub_m["estado"].isin(["En Curso", "Enviada"])]
                    m_tot_n = len(sub_m)
                    m_ace_n = len(m_ace)
                    m_tot_i = float(sub_m["importe_eur"].sum())
                    m_ace_i = float(m_ace["importe_eur"].sum())
                    m_pen_n = len(m_pen)
                    m_pen_i = float(m_pen["importe_eur"].sum())

                    mensual_rows.append({
                        "MES": m_nom,
                        "Nº TOTAL": m_tot_n,
                        "Nº ACEPTADOS": m_ace_n,
                        "Nº PENDIENTES": m_pen_n,
                        "RATIO Nº (%)": round((m_ace_n / m_tot_n * 100.0) if m_tot_n > 0 else 0.0, 1),
                        "IMPORTE TOTAL (€)": round(m_tot_i, 2),
                        "IMPORTE ACEPTADOS (€)": round(m_ace_i, 2),
                        "PENDIENTES (€)": round(m_pen_i, 2),
                        "RATIO € (%)": round((m_ace_i / m_tot_i * 100.0) if m_tot_i > 0 else 0.0, 1),
                    })

                df_mensual = pd.DataFrame(mensual_rows)
                gm1, gm2 = st.columns(2)
                with gm1:
                    st.markdown("#### EVOLUCIÓN MENSUAL DE IMPORTES (€)")
                    st.bar_chart(df_mensual.set_index("MES")[["IMPORTE TOTAL (€)", "IMPORTE ACEPTADOS (€)", "PENDIENTES (€)"]])
                with gm2:
                    st.markdown("#### EVOLUCIÓN MENSUAL DE Nº COTIZACIONES")
                    st.bar_chart(df_mensual.set_index("MES")[["Nº TOTAL", "Nº ACEPTADOS", "Nº PENDIENTES"]])

                st.dataframe(df_mensual, use_container_width=True, hide_index=True)
            else:
                st.info("No hay meses registrados para mostrar la evolución mensual.")

            st.divider()
            st.markdown("### 🎯 CUMPLIMIENTO FRENTE A METAS DEL DASHBOARD 2026")
            meta_res_num = 50.0
            meta_res_imp = 31.0

            c_m1, c_m2 = st.columns(2)
            diff_num = ratio_num_pct - meta_res_num
            diff_imp = ratio_imp_pct - meta_res_imp
            c_m1.metric(
                "RATIO COTIZACIONES EN NÚMERO VS. META (50,0 %)",
                f"{ratio_num_pct:.1f} %".replace(".", ","),
                f"{diff_num:+.1f} pp".replace(".", ","),
            )
            c_m2.metric(
                "RATIO COTIZACIONES EN IMPORTE VS. META (31,0 %)",
                f"{ratio_imp_pct:.1f} %".replace(".", ","),
                f"{diff_imp:+.1f} pp".replace(".", ","),
            )

            st.markdown("#### COTIZACIONES PENDIENTES EN TIEMPO REAL")
            if not df_pend.empty:
                cols_pend_live = [
                    c for c in [
                        "id", "fecha", "mes", "centro", "cliente", "comercial", "responsable",
                        "segmento", "tipo_envio", "pais", "servicio", "estado", "importe_eur",
                    ] if c in df_pend.columns
                ]
                st.dataframe(df_pend[cols_pend_live], use_container_width=True, hide_index=True)
            else:
                st.success("No hay cotizaciones pendientes con el filtro actual.")

    elif menu == "👥 CARTERA Y CORREOS":
        st.subheader("COMERCIALES, RESPONSABLES, DIRECCIÓN Y CARTERA")
        df_com = cargar_comerciales_df()
        df_resp = cargar_responsables_df()
        df_dir = cargar_direccion_df()
        df_cli = cargar_clientes_df()

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### COMERCIALES Y CORREOS")
            st.dataframe(df_com, use_container_width=True, hide_index=True)
            with st.form("form_com"):
                c_nom = st.text_input("NOMBRE COMERCIAL").upper().strip()
                c_mail = st.text_input("CORREO ELECTRÓNICO COMERCIAL").strip()
                if st.form_submit_button("GUARDAR COMERCIAL"):
                    if c_nom and c_mail:
                        conn = get_conn()
                        conn.execute(
                            """
                            INSERT INTO comerciales (comercial, email_comercial)
                            VALUES (?, ?)
                            ON CONFLICT(comercial) DO UPDATE SET email_comercial = excluded.email_comercial
                            """,
                            (c_nom, c_mail),
                        )
                        conn.commit()
                        conn.close()
                        st.success("COMERCIAL ACTUALIZADO.")
                        st.rerun()

        with col2:
            st.markdown("#### RESPONSABLES DE COTIZACIÓN Y CORREOS")
            st.dataframe(df_resp, use_container_width=True, hide_index=True)
            with st.form("form_resp"):
                r_nom = st.text_input("NOMBRE RESPONSABLE").upper().strip()
                r_mail = st.text_input("CORREO ELECTRÓNICO RESPONSABLE").strip()
                if st.form_submit_button("GUARDAR RESPONSABLE"):
                    if r_nom and r_mail:
                        conn = get_conn()
                        conn.execute(
                            """
                            INSERT INTO responsables (responsable, email_responsable)
                            VALUES (?, ?)
                            ON CONFLICT(responsable) DO UPDATE SET email_responsable = excluded.email_responsable
                            """,
                            (r_nom, r_mail),
                        )
                        conn.commit()
                        conn.close()
                        st.success("RESPONSABLE ACTUALIZADO.")
                        st.rerun()

        st.divider()
        st.markdown("#### DIRECCIÓN")
        st.dataframe(df_dir, use_container_width=True, hide_index=True)

        _renderizar_bloque_smtp_y_alertas(df_com, df_resp, df_dir, df_cli)

        st.divider()
        st.markdown("#### CARTERA DE CLIENTES (ASIGNACIÓN DE COMERCIAL POR CLIENTE)")
        st.dataframe(df_cli[["id_cliente", "cliente", "comercial", "email_comercial"]], use_container_width=True, hide_index=True)

        with st.form("form_asignar_cliente"):
            a1, a2 = st.columns(2)
            cli_opts = df_cli["cliente"].tolist() if not df_cli.empty else []
            cli_a_editar = a1.selectbox("SELECCIONAR CLIENTE", cli_opts) if cli_opts else a1.text_input("CLIENTE").upper()
            com_opts_disp = df_com["comercial"].tolist() if not df_com.empty else ["ENEKO"]
            com_nuevo = a2.selectbox("ASIGNAR COMERCIAL", com_opts_disp)
            if st.form_submit_button("GUARDAR ASIGNACIÓN DE COMERCIAL"):
                if cli_a_editar:
                    conn = get_conn()
                    conn.execute(
                        """
                        INSERT INTO clientes (cliente, contacto_habitual, comercial)
                        VALUES (?, '', ?)
                        ON CONFLICT(cliente) DO UPDATE SET comercial = excluded.comercial
                        """,
                        (str(cli_a_editar).upper().strip(), com_nuevo),
                    )
                    conn.commit()
                    conn.close()
                    st.success(f"CLIENTE {cli_a_editar} ASIGNADO A {com_nuevo}.")
                    st.rerun()

except Exception as exc:
    st.error(f"Error en la interfaz: {type(exc).__name__}: {exc}")
    st.exception(exc)
