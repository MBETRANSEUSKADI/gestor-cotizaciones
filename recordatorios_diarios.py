from datetime import datetime, date, timedelta
import re
import sqlite3
from pathlib import Path
import streamlit as st

try:
    from database import get_conn, init_db
except Exception:
    DB_PATH = Path("C:/gestor_cotizaciones/cotizaciones.db")
    if not DB_PATH.exists():
        DB_PATH = Path("cotizaciones.db")

    def get_conn():
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db():
        pass

try:
    from alertas_correo import enviar_email_smtp
except Exception:
    def enviar_email_smtp(destinatarios, asunto, cuerpo):
        return False, "Módulo alertas_correo no disponible en este entorno."

URL_WEB_POR_DEFECTO = "http://localhost:8501"


def asegurar_tabla_alertas_diarias(conn=None):
    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS log_alertas_11_12 (
            id_alerta INTEGER PRIMARY KEY AUTOINCREMENT,
            id_cotizacion TEXT NOT NULL,
            fecha_envio_alerta TEXT NOT NULL,
            responsable TEXT,
            email_responsable TEXT,
            estado_cotizacion TEXT,
            enviado_ok INTEGER DEFAULT 0,
            detalle_envio TEXT,
            creado_en TEXT NOT NULL,
            UNIQUE(id_cotizacion, fecha_envio_alerta)
        )
        """
    )
    if own_conn:
        conn.commit()
        conn.close()


def _parsear_fecha_cotizacion(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    txt = str(val).strip()
    if not txt:
        return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(txt[:10], fmt).date()
        except ValueError:
            continue

    m = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", txt)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    m_iso = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", txt)
    if m_iso:
        try:
            return date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
        except ValueError:
            pass

    return None


def _resolver_email_responsable(conn, responsable_nombre, email_actual=""):
    em = str(email_actual or "").strip()
    if "@" in em:
        return em
    resp_up = str(responsable_nombre or "").strip().upper()
    if not resp_up:
        return ""
    try:
        row = conn.execute(
            "SELECT email_responsable FROM responsables WHERE UPPER(TRIM(responsable)) = ?",
            (resp_up,),
        ).fetchone()
        if row and row["email_responsable"] and "@" in str(row["email_responsable"]):
            return str(row["email_responsable"]).strip()
    except Exception:
        pass
    try:
        row_c = conn.execute(
            "SELECT email_comercial FROM comerciales WHERE UPPER(TRIM(comercial)) = ?",
            (resp_up,),
        ).fetchone()
        if row_c and row_c["email_comercial"] and "@" in str(row_c["email_comercial"]):
            return str(row_c["email_comercial"]).strip()
    except Exception:
        pass
    return ""


def _obtener_url_web():
    try:
        qp = st.query_params
        for k in ("web_url", "url", "app_url"):
            v = str(qp.get(k, "") or "").strip()
            if v.startswith("http://") or v.startswith("https://"):
                return v
    except Exception:
        pass
    return URL_WEB_POR_DEFECTO


def es_elegible_alerta_11_12(fecha_alta_raw, estado_raw, ahora_dt=None, forzar_ventana=False):
    ahora = ahora_dt or datetime.now()
    estado_norm = str(estado_raw or "").strip().lower()

    if estado_norm != "en curso":
        return False, f"Estado '{estado_raw or 'Sin estado'}' distinto de 'En curso'."

    if not forzar_ventana:
        inicio_ventana = ahora.replace(hour=11, minute=0, second=0, microsecond=0)
        fin_ventana = ahora.replace(hour=12, minute=0, second=0, microsecond=0)
        if not (inicio_ventana <= ahora < fin_ventana):
            return False, f"Fuera de franja 11:00-12:00 (hora actual: {ahora.strftime('%H:%M')})."

    fecha_alta = _parsear_fecha_cotizacion(fecha_alta_raw)
    if fecha_alta is None:
        return False, "Fecha de cotización no válida."

    primer_dia_alerta = fecha_alta + timedelta(days=1)
    if ahora.date() < primer_dia_alerta:
        return False, f"Aún no ha llegado el día siguiente ({primer_dia_alerta.strftime('%d/%m/%Y')})."

    return True, "Elegible para alerta diaria (11:00-12:00)."


def procesar_alertas_responsables_11_12(ahora_dt=None, forzar_ventana=False, url_web=None):
    ahora = ahora_dt or datetime.now()
    hoy_str = ahora.strftime("%Y-%m-%d")
    enlace = (url_web or _obtener_url_web()).strip() or URL_WEB_POR_DEFECTO

    conn = get_conn()
    asegurar_tabla_alertas_diarias(conn)
    conn.commit()

    candidatas = 0
    enviadas = 0
    omitidas = 0
    errores = []
    detalles = []

    try:
        rows = conn.execute("SELECT * FROM cotizaciones").fetchall()
    except Exception as exc:
        conn.close()
        return {"candidatas": 0, "enviadas": 0, "omitidas": 0, "errores": [f"Error leyendo cotizaciones: {exc}"], "detalles": []}

    for r in rows:
        keys = r.keys()
        cot_id = str(r["id"] if "id" in keys else "").strip()
        estado_val = str(r["estado"] if "estado" in keys else "").strip()
        fecha_val = r["fecha"] if "fecha" in keys else (r["ultima_actualizacion"] if "ultima_actualizacion" in keys else None)
        if not _parsear_fecha_cotizacion(fecha_val) and "ultima_actualizacion" in keys:
            fecha_val = r["ultima_actualizacion"]

        responsable_val = str(r["responsable"] if "responsable" in keys else "").strip()
        email_col = str(r["email_responsable"] if "email_responsable" in keys else "").strip()
        cliente_val = str(r["cliente"] if "cliente" in keys else "").strip()
        comercial_val = str(r["comercial"] if "comercial" in keys else "").strip()

        elegible, motivo = es_elegible_alerta_11_12(fecha_val, estado_val, ahora_dt=ahora, forzar_ventana=forzar_ventana)
        if not elegible:
            omitidas += 1
            continue

        candidatas += 1

        ya_enviada = conn.execute(
            "SELECT id_alerta FROM log_alertas_11_12 WHERE id_cotizacion = ? AND fecha_envio_alerta = ? AND enviado_ok = 1",
            (cot_id, hoy_str),
        ).fetchone()
        if ya_enviada:
            omitidas += 1
            detalles.append(f"{cot_id}: ya notificada hoy ({hoy_str}) a {responsable_val}.")
            continue

        correo_dest = _resolver_email_responsable(conn, responsable_val, email_col)
        if not correo_dest:
            msg_err = f"{cot_id} ({cliente_val}): responsable '{responsable_val or 'SIN ASIGNAR'}' sin correo electrónico configurado."
            errores.append(msg_err)
            conn.execute(
                """
                INSERT INTO log_alertas_11_12
                    (id_cotizacion, fecha_envio_alerta, responsable, email_responsable, estado_cotizacion, enviado_ok, detalle_envio, creado_en)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(id_cotizacion, fecha_envio_alerta) DO UPDATE SET
                    responsable=excluded.responsable,
                    email_responsable=excluded.email_responsable,
                    estado_cotizacion=excluded.estado_cotizacion,
                    enviado_ok=0,
                    detalle_envio=excluded.detalle_envio,
                    creado_en=excluded.creado_en
                """,
                (cot_id, hoy_str, responsable_val, "", estado_val, msg_err, ahora.strftime("%Y-%m-%d %H:%M:%S")),
            )
            continue

        asunto = f"[RECORDATORIO SEGUIMIENTO 11:00-12:00] Cotización {cot_id} — {cliente_val} (En curso)"
        cuerpo = (
            f"Hola {responsable_val or 'Responsable'},\n\n"
            f"Tienes pendiente indicar una acción de seguimiento para la siguiente cotización que continúa En curso:\n\n"
            f"• ID Cotización: {cot_id}\n"
            f"• Cliente: {cliente_val}\n"
            f"• Comercial: {comercial_val or '-'}\n"
            f"• Estado actual: {estado_val}\n\n"
            f"Accede a la web para registrar tu acción de seguimiento y actualizar el estado:\n"
            f"{enlace}\n\n"
            f"Este recordatorio se enviará cada día entre las 11:00 y las 12:00 hasta que la cotización pase a un estado final distinto de En curso.\n\n"
            f"TRANSEUSKADI GROUP"
        )

        ok_mail, info_mail = enviar_email_smtp([correo_dest], asunto, cuerpo)
        if ok_mail:
            enviadas += 1
            detalles.append(f"{cot_id}: alerta enviada a {correo_dest} ({responsable_val}).")
            conn.execute(
                """
                INSERT INTO log_alertas_11_12
                    (id_cotizacion, fecha_envio_alerta, responsable, email_responsable, estado_cotizacion, enviado_ok, detalle_envio, creado_en)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(id_cotizacion, fecha_envio_alerta) DO UPDATE SET
                    responsable=excluded.responsable,
                    email_responsable=excluded.email_responsable,
                    estado_cotizacion=excluded.estado_cotizacion,
                    enviado_ok=1,
                    detalle_envio=excluded.detalle_envio,
                    creado_en=excluded.creado_en
                """,
                (cot_id, hoy_str, responsable_val, correo_dest, estado_val, f"Enviado OK: {info_mail}", ahora.strftime("%Y-%m-%d %H:%M:%S")),
            )
        else:
            err_txt = f"{cot_id} -> {correo_dest}: {info_mail}"
            errores.append(err_txt)
            conn.execute(
                """
                INSERT INTO log_alertas_11_12
                    (id_cotizacion, fecha_envio_alerta, responsable, email_responsable, estado_cotizacion, enviado_ok, detalle_envio, creado_en)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(id_cotizacion, fecha_envio_alerta) DO UPDATE SET
                    responsable=excluded.responsable,
                    email_responsable=excluded.email_responsable,
                    estado_cotizacion=excluded.estado_cotizacion,
                    enviado_ok=0,
                    detalle_envio=excluded.detalle_envio,
                    creado_en=excluded.creado_en
                """,
                (cot_id, hoy_str, responsable_val, correo_dest, estado_val, err_txt, ahora.strftime("%Y-%m-%d %H:%M:%S")),
            )

    conn.commit()
    conn.close()
    return {
        "candidatas": candidatas,
        "enviadas": enviadas,
        "omitidas": omitidas,
        "errores": errores,
        "detalles": detalles,
    }


def ejecutar_chequeo_automatico_11_12_en_app():
    ahora = datetime.now()
    if not (11 <= ahora.hour < 12):
        return None
    marca_key = f"_alerta_11_12_chequeada_{ahora.strftime('%Y-%m-%d')}"
    if st.session_state.get(marca_key):
        return None
    st.session_state[marca_key] = True
    return procesar_alertas_responsables_11_12(ahora_dt=ahora, forzar_ventana=False)


if __name__ == "__main__":
    res = procesar_alertas_responsables_11_12(forzar_ventana=False)
    print("Resultado alertas 11:00-12:00:", res)