import re
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

from database import get_conn, registrar_historial


def _normalizar_destinatarios(destinatario):
    if isinstance(destinatario, (list, tuple, set)):
        items = [str(d).strip().strip("[]'\"") for d in destinatario if str(d).strip()]
    elif isinstance(destinatario, str):
        limpio = destinatario.strip()
        if limpio.startswith("[") and limpio.endswith("]"):
            limpio = limpio[1:-1]
        items = [d.strip().strip("'\"") for d in limpio.split(",") if d.strip()]
    else:
        items = []
    return [d for d in items if "@" in d]


def _extraer_ddmmaaaa(fecha_str=None):
    txt = str(fecha_str or "").strip()
    m_dmy = re.search(r"\b(\d{2})[/-](\d{2})[/-](\d{4})\b", txt)
    if m_dmy:
        return f"{m_dmy.group(1)}{m_dmy.group(2)}{m_dmy.group(3)}"
    m_ymd = re.search(r"\b(\d{4})[/-](\d{2})[/-](\d{2})\b", txt)
    if m_ymd:
        return f"{m_ymd.group(3)}{m_ymd.group(2)}{m_ymd.group(1)}"
    return datetime.now().strftime("%d%m%Y")


def generar_id_cotizacion_correlativo(fecha_str=None):
    """Genera un ID con formato DDMMYYYY-XXX (numeración correlativa por fecha)."""
    prefijo = f"{_extraer_ddmmaaaa(fecha_str)}-"
    conn = get_conn()
    filas = conn.execute(
        "SELECT id FROM cotizaciones WHERE UPPER(TRIM(CAST(id AS TEXT))) LIKE ?",
        (f"{prefijo}%",),
    ).fetchall()
    conn.close()

    max_corr = 0
    for f in filas:
        val_id = str(f["id"] or "").strip().upper()
        if val_id.startswith(prefijo):
            sufijo = val_id[len(prefijo):]
            m_num = re.match(r"^(\d+)", sufijo)
            if m_num:
                num = int(m_num.group(1))
                if num > max_corr:
                    max_corr = num

    return f"{prefijo}{max_corr + 1:03d}"


def obtener_config_smtp():
    conn = get_conn()
    row = conn.execute("SELECT * FROM config_smtp WHERE id = 1").fetchone()
    conn.close()
    if not row:
        return {
            "smtp_host": "",
            "smtp_port": 465,
            "smtp_user": "",
            "smtp_password": "",
            "use_tls": 0,
        }
    return dict(row)


def guardar_config_smtp(smtp_host, smtp_port, smtp_user, smtp_password, use_tls=0):
    conn = get_conn()
    conn.execute("""
        UPDATE config_smtp
        SET smtp_host = ?,
            smtp_port = ?,
            smtp_user = ?,
            smtp_password = ?,
            use_tls = ?
        WHERE id = 1
    """, (
        (smtp_host or "").strip(),
        int(smtp_port or 465),
        (smtp_user or "").strip(),
        (smtp_password or "").strip(),
        1 if use_tls else 0,
    ))
    conn.commit()
    conn.close()


def enviar_correo(destinatario, asunto, cuerpo):
    cfg = obtener_config_smtp()
    host = (cfg.get("smtp_host") or "").strip()
    port = int(cfg.get("smtp_port") or 465)
    user = (cfg.get("smtp_user") or "").strip()
    password = (cfg.get("smtp_password") or "").strip()
    use_tls = bool(cfg.get("use_tls", 0))

    if not host or not user or not password:
        return False, "Falta configurar el servidor SMTP, el usuario o la contraseña en config_smtp."

    destinos = _normalizar_destinatarios(destinatario)
    if not destinos:
        return False, f"Destinatario no válido: '{destinatario}'."

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = ", ".join(destinos)
    msg["Subject"] = asunto
    msg.set_content(cuerpo)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20) as server:
                server.ehlo()
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                if use_tls:
                    server.starttls()
                    server.ehlo()
                server.login(user, password)
                server.send_message(msg)
        return True, f"Correo enviado correctamente a {', '.join(destinos)}."
    except smtplib.SMTPAuthenticationError as exc:
        code = getattr(exc, "smtp_code", "")
        err_bytes = getattr(exc, "smtp_error", b"")
        err_txt = err_bytes.decode("utf-8", errors="replace") if isinstance(err_bytes, bytes) else str(err_bytes)
        return False, f"Error de autenticación SMTP ({code}): {err_txt or exc}"
    except Exception as exc:
        return False, f"Error SMTP al enviar a {', '.join(destinos)}: {type(exc).__name__}: {exc}"


def enviar_email_smtp(destinatario, asunto, cuerpo):
    return enviar_correo(destinatario, asunto, cuerpo)


def obtener_email_comercial(nombre_comercial):
    if not nombre_comercial:
        return ""
    conn = get_conn()
    row = conn.execute(
        "SELECT email_comercial FROM comerciales WHERE UPPER(TRIM(comercial)) = UPPER(TRIM(?))",
        (nombre_comercial,),
    ).fetchone()
    conn.close()
    return (row["email_comercial"] or "").strip() if row else ""


def obtener_email_responsable(nombre_responsable):
    if not nombre_responsable:
        return ""
    conn = get_conn()
    row = conn.execute(
        "SELECT email_responsable FROM responsables WHERE UPPER(TRIM(responsable)) = UPPER(TRIM(?))",
        (nombre_responsable,),
    ).fetchone()
    conn.close()
    return (row["email_responsable"] or "").strip() if row else ""


def _formatear_numero(val, default="0,00"):
    if val is None or str(val).strip() == "":
        return default
    s = str(val).replace("€", "").replace("%", "").strip().replace(",", ".")
    try:
        n = float(s)
        return f"{n:.2f}".replace(".", ",")
    except ValueError:
        return str(val).strip()


def notificar_nueva_cotizacion(
    id_cotizacion,
    arg2=None,
    arg3=None,
    arg4=None,
    arg5=None,
    arg6=None,
    arg7=None,
    *args,
    **kwargs,
):
    id_limpio = str(id_cotizacion or "").strip().upper()

    conn = get_conn()
    cot = conn.execute(
        "SELECT * FROM cotizaciones WHERE UPPER(TRIM(CAST(id AS TEXT))) = ?",
        (id_limpio,),
    ).fetchone()
    conn.close()

    cot_dict = dict(cot) if cot else {}

    # Si el ID no sigue ya el formato DDMMYYYY-XXX, se sugiere/compone uno con fecha + correlativo
    if re.match(r"^\d{8}-\d{3,}$", id_limpio):
        id_mostrar = id_limpio
    else:
        fecha_ref = cot_dict.get("fecha") or cot_dict.get("ultima_actualizacion")
        id_mostrar = generar_id_cotizacion_correlativo(fecha_ref)

    extras = [
        str(x).strip()
        for x in (arg2, arg3, arg4, arg5, arg6, arg7) + args
        if x is not None and str(x).strip() != ""
    ]

    estados_conocidos = {
        "EN CURSO", "PENDIENTE", "ABIERTA", "GANADA", "PERDIDA",
        "CERRADA", "RECHAZADA", "APROBADA", "ACEPTADA", "ENVIADA",
    }

    def _es_numero(val):
        s = str(val or "").replace("€", "").replace("%", "").strip().replace(",", ".")
        try:
            float(s)
            return True
        except ValueError:
            return False

    nom_cliente = (cot_dict.get("cliente") or "").strip()
    if not nom_cliente:
        nom_cliente = next(
            (x for x in extras if not _es_numero(x) and x.upper() not in estados_conocidos),
            "SIN CLIENTE",
        )

    nom_comercial = (cot_dict.get("comercial") or "").strip() or "SIN ASIGNAR"

    if cot_dict.get("precio_total") is not None and str(cot_dict.get("precio_total")).strip() != "":
        imp_str = _formatear_numero(cot_dict.get("precio_total"))
    elif cot_dict.get("importe_ofertado") is not None and str(cot_dict.get("importe_ofertado")).strip() != "":
        imp_str = _formatear_numero(cot_dict.get("importe_ofertado"))
    else:
        num_extra = next((x for x in extras if _es_numero(x)), "0")
        imp_str = _formatear_numero(num_extra)

    nom_responsable = (cot_dict.get("responsable") or "").strip()
    if not nom_responsable or _es_numero(nom_responsable):
        nom_responsable = next(
            (
                x for x in extras
                if not _es_numero(x)
                and x.upper() not in estados_conocidos
                and x.upper() != nom_cliente.upper()
                and x.upper() != nom_comercial.upper()
            ),
            "-",
        )

    estado_bd = (cot_dict.get("estado") or "").strip()
    if estado_bd and estado_bd.upper() not in {"SI", "NO", "TRUE", "FALSE", "0", "1"}:
        estado_actual = estado_bd
    else:
        estado_actual = next(
            (x for x in extras if x.upper() in estados_conocidos),
            estado_bd or "-",
        )

    margen_raw = (
        cot_dict.get("margen")
        if cot_dict.get("margen") is not None
        else cot_dict.get("margen_envio")
    )
    margen_total_raw = (
        cot_dict.get("margen_total")
        if cot_dict.get("margen_total") is not None
        else None
    )
    margen_str = _formatear_numero(margen_raw) if margen_raw is not None and str(margen_raw).strip() != "" else "-"
    margen_total_str = (
        _formatear_numero(margen_total_raw)
        if margen_total_raw is not None and str(margen_total_raw).strip() != ""
        else "-"
    )

    detalles = (
        cot_dict.get("detalles_envio")
        or cot_dict.get("detalles")
        or cot_dict.get("envios")
        or ""
    )
    if not detalles and extras:
        detalles = " | ".join(extras)

    email_comercial = obtener_email_comercial(nom_comercial)

    if not email_comercial:
        msg = f"Sin correo configurado para el comercial '{nom_comercial}'."
        registrar_historial(id_limpio or id_mostrar, "SISTEMA", "AVISO COMERCIAL", "PENDIENTE_EMAIL", msg)
        return False, msg

    asunto = f"Nueva cotización (>300 €) - {id_mostrar} - {nom_cliente}"
    cuerpo = (
        f"Hola {nom_comercial},\n\n"
        f"Se ha registrado una nueva cotización en el gestor:\n"
        f"- ID Cotización: {id_mostrar}\n"
        f"- Cliente: {nom_cliente}\n"
        f"- Centro: {cot_dict.get('centro') or '-'}\n"
        f"- Tipo / País: {cot_dict.get('tipo_envio') or '-'} / {cot_dict.get('pais') or '-'}\n"
        f"- Courier / Servicio: {cot_dict.get('courier') or '-'} / {cot_dict.get('servicio') or '-'}\n"
        f"- Importe ofertado / Total: {imp_str} €\n"
        f"- Margen: {margen_str} %\n"
        f"- Margen total: {margen_total_str} %\n"
        f"- Responsable: {nom_responsable}\n"
        f"- Estado actual: {estado_actual}\n"
    )
    if detalles:
        cuerpo += f"- Detalles / Envíos: {detalles}\n"
    cuerpo += "\nUn saludo."

    ok, info = enviar_correo(email_comercial, asunto, cuerpo)
    registrar_historial(
        id_limpio or id_mostrar,
        "SISTEMA",
        "AVISO COMERCIAL",
        "ENVIADO" if ok else "ERROR",
        f"{email_comercial}: {info}",
    )
    return ok, info


def revisar_alertas_24h(horas=24):
    conn = get_conn()
    filas = conn.execute("""
        SELECT *
        FROM cotizaciones
        WHERE UPPER(TRIM(estado)) NOT IN ('GANADA', 'PERDIDA', 'CERRADA', 'RECHAZADA')
          AND COALESCE(alerta_24h_enviada, 0) = 0
    """).fetchall()
    conn.close()

    ahora = datetime.now()
    limite = ahora - timedelta(hours=horas)
    enviados = 0
    errores = []

    for cot in filas:
        ref_str = (cot["ultima_actualizacion"] or "").strip()
        fecha_ref = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y"):
            try:
                fecha_ref = datetime.strptime(ref_str, fmt)
                break
            except ValueError:
                continue

        if not fecha_ref or fecha_ref > limite:
            continue

        responsable = cot["responsable"] or ""
        email_resp = (cot["email_responsable"] or "").strip() or obtener_email_responsable(responsable)

        if not email_resp:
            err_msg = f"{cot['id']}: sin correo de responsable ({responsable})."
            errores.append(err_msg)
            registrar_historial(cot["id"], "SISTEMA", "ALERTA 24H", "ERROR", err_msg)
            continue

        importe = cot["precio_total"] if cot["precio_total"] is not None else cot["importe_ofertado"]
        asunto = f"ALERTA 24H - Cotización pendiente {cot['id']} ({cot['cliente']})"
        cuerpo = (
            f"Hola {responsable},\n\n"
            f"La siguiente cotización lleva más de {horas} horas sin cerrarse ni actualizarse:\n"
            f"- ID Cotización: {cot['id']}\n"
            f"- Cliente: {cot['cliente']}\n"
            f"- Centro: {cot['centro'] or '-'}\n"
            f"- Comercial: {cot['comercial']}\n"
            f"- Importe: {importe if importe is not None else 0} €\n"
            f"- Estado actual: {cot['estado']}\n"
            f"- Última actualización: {cot['ultima_actualizacion']}\n\n"
            f"Por favor, revisa y actualiza su estado o motivo de cierre en el gestor."
        )

        ok, info = enviar_correo(email_resp, asunto, cuerpo)
        if ok:
            conn_upd = get_conn()
            conn_upd.execute(
                "UPDATE cotizaciones SET alerta_24h_enviada = 1 WHERE id = ?",
                (cot["id"],),
            )
            conn_upd.commit()
            conn_upd.close()
            enviados += 1
            registrar_historial(cot["id"], "SISTEMA", "ALERTA 24H", "ENVIADO", f"{email_resp}: {info}")
        else:
            err_msg = f"{cot['id']}: {info}"
            errores.append(err_msg)
            registrar_historial(cot["id"], "SISTEMA", "ALERTA 24H", "ERROR", err_msg)

    return enviados, errores


def revisar_y_enviar_alertas_24h(horas=24):
    return revisar_alertas_24h(horas=horas)


if __name__ == "__main__":
    cfg = obtener_config_smtp()
    print("Configuración SMTP actual:", {
        "smtp_host": cfg.get("smtp_host"),
        "smtp_port": cfg.get("smtp_port"),
        "smtp_user": cfg.get("smtp_user"),
        "use_tls": cfg.get("use_tls"),
        "password_configurada": bool(cfg.get("smtp_password")),
    })