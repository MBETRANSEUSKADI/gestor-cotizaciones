import sqlite3
from datetime import datetime

DB_PATH = "cotizaciones.db"

CENTROS_VALIDOS = [
    "0329 DERIO",
    "2775 GETXO",
    "3401 VITORIA",
    "0343 ABADIÑO",
    "0220 ZARAUTZ",
    "0274 EIBAR",
    "0309 OÑATI",
]

MESES_VALIDOS = [
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]

COMERCIALES_INICIALES = [
    ("VASYL", "mbe329comercial@mbe.es"),
    ("BEGOÑA", "comercial220@mbe.es"),
    ("FRANCINE", "mbe3401comercial@mbe.es"),
    ("IMANOL", "imartin@mbe.es"),
]

RESPONSABLES_INICIALES = [
    ("JULEN", "mbe329@mbe.es"),
    ("OLGA", "mbe343@mbe.es"),
    ("MARIA", "mbe3401@mbe.es"),
    ("NAIARA LLAMAS", "mbe274@mbe.es"),
    ("NAIARA ZARATE", "mbe220@mbe.es"),
    ("ENEKO", "mbe2775@mbe.es"),
    ("ELENA", "operaciones220@mbe.es"),
]

DIRECCION_INICIAL = [
    ("EMILIO", "eastier@mbe.es"),
]

CARTERA_ENEKO = [
    "AUXILIAR LAMINADORA ALAVESA, S.A. (AULASA - GRUPO ROCES)",
    "BASALAN CLUPAK, S.L.U. (MONTAJES Y MECANIZACIONES BASALAN)",
    "BODEGAS ITSASMENDI S.L.",
    "COMECARAN, S.A.",
    "CONSEJO REGULADOR DE LA D.O. BIZKAIKO TXAKOLINA",
    "CONSILIUM SPAIN S.L.",
    "CONSORCIO ESS BILBAO",
    "CUNOVA SERVICE SPAIN, S.A.U.",
    "DICOINSA S.L.",
    "DINAKSA PESAJE S.L.",
    "FIDIA IBERICA, S.A",
    "FORBRASS S.A.",
    "GESLARFIN, S.L.",
    "GORORDO SEA SAFETY S.L.",
    "HIERROS Y CARBONES, S.A.",
    "HYDROGEN ONSITE, S.L.",
    "IGN RECUPERACIONES SL (INVERSIONES GRANADA NORTE)",
    "INDUSTRIAS DOY MANUEL MORATE, S.L.",
    "IRASTELAY, S.L. (SCORP CENTRO DE NEGOCIOS)",
    "JMS TERMOFIG, S.L.",
    "KOOPERA SERVICIOS AMBIENTALES S. COOP",
    "LANTEK HIDRAULICA, S.L.",
    "LARRENO S.L.",
    "MESIMA BILBAO S.A.",
    "NUA BIOLOGICAL INNOVATIONS, S.L.",
    "NUEVA INCAL, S.A.",
    "OKENDO TXAKOLINA, S.L.",
    "QUANDT DECOR S.L.",
    "RECYMET SYSTEMS, S.L.",
    "REYMA, MATERIALES REFRACTARIOS, S.A.",
    "RODABIL, S.A.",
    "SUMINISTROS Y CALIBRACION INDUSTRIAL, S.L.",
    "UKAI, S.A.",
    "AZAROS 21, S.A.",
    "BATZ ZAMUDIO, S.COOP.",
    "AR SHELVING, S.A.",
    "MAXAMCORP INTERNATIONAL, S.L.U.",
    "SILICONAS SILAM, S.A.",
    "INSTITUT MARQUÈS OBSTETRICIA I GINECOLOGIA, S.L.",
    "DATIK INFORMACIÓN INTELIGENTE, S.L.",
    "ARSONDATA METERING (IOT WATER ANALYTICS)",
    "REFRACTORY SOLUTIONS INSERTEC SLU",
    "INDUSTRIAL FURNACES INSERTEC S.L.U.",
]


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS comerciales (
            comercial TEXT PRIMARY KEY,
            email_comercial TEXT NOT NULL DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS responsables (
            responsable TEXT PRIMARY KEY,
            email_responsable TEXT NOT NULL DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS direccion (
            persona TEXT PRIMARY KEY,
            email_persona TEXT NOT NULL DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS config_smtp (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            smtp_host TEXT NOT NULL DEFAULT '',
            smtp_port INTEGER NOT NULL DEFAULT 587,
            smtp_user TEXT NOT NULL DEFAULT '',
            smtp_password TEXT NOT NULL DEFAULT '',
            use_tls INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id_cliente INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT UNIQUE NOT NULL,
            contacto_habitual TEXT DEFAULT '',
            comercial TEXT NOT NULL DEFAULT 'SIN ASIGNAR'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cotizaciones (
            id TEXT PRIMARY KEY,
            prioridad TEXT NOT NULL,
            fecha TEXT NOT NULL,
            mes TEXT DEFAULT '',
            centro TEXT DEFAULT '0329 DERIO',
            id_cliente INTEGER,
            cliente TEXT NOT NULL,
            contacto TEXT DEFAULT '',
            comercial TEXT NOT NULL,
            responsable TEXT NOT NULL,
            email_responsable TEXT DEFAULT '',
            prevision_envio TEXT DEFAULT '',
            estado TEXT NOT NULL,
            motivo_cierre TEXT DEFAULT '',
            precio_competencia TEXT DEFAULT '',
            importe_ofertado REAL,
            margen_pct REAL,
            peso TEXT DEFAULT '',
            courier TEXT DEFAULT '',
            tipo_envio TEXT DEFAULT 'EXPORT',
            pais TEXT DEFAULT '',
            servicio TEXT DEFAULT '',
            coste REAL,
            coste_total REAL,
            precio REAL,
            precio_total REAL,
            margen REAL,
            margen_total REAL,
            es_especial TEXT DEFAULT 'NO',
            comentarios TEXT DEFAULT '',
            notas_generales TEXT DEFAULT '',
            origen TEXT NOT NULL,
            envios TEXT DEFAULT '',
            ultima_actualizacion TEXT NOT NULL,
            alerta_24h_enviada INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS seguimiento (
            id_log INTEGER PRIMARY KEY AUTOINCREMENT,
            id_cotizacion TEXT NOT NULL,
            fecha_hora TEXT NOT NULL,
            usuario TEXT NOT NULL,
            canal_accion TEXT NOT NULL,
            resultado_envio TEXT NOT NULL,
            detalle TEXT NOT NULL,
            FOREIGN KEY (id_cotizacion) REFERENCES cotizaciones (id)
        )
    """)

    cols_existentes = {r["name"] for r in cur.execute("PRAGMA table_info(cotizaciones)").fetchall()}
    nuevas_cols = {
        "mes": "TEXT DEFAULT ''",
        "centro": "TEXT DEFAULT '0329 DERIO'",
        "peso": "TEXT DEFAULT ''",
        "courier": "TEXT DEFAULT ''",
        "tipo_envio": "TEXT DEFAULT 'EXPORT'",
        "pais": "TEXT DEFAULT ''",
        "servicio": "TEXT DEFAULT ''",
        "coste": "REAL",
        "coste_total": "REAL",
        "precio": "REAL",
        "precio_total": "REAL",
        "margen": "REAL",
        "margen_total": "REAL",
        "alerta_24h_enviada": "INTEGER NOT NULL DEFAULT 0",
    }
    for col_name, col_def in nuevas_cols.items():
        if col_name not in cols_existentes:
            cur.execute(f"ALTER TABLE cotizaciones ADD COLUMN {col_name} {col_def}")

    cur.execute("DELETE FROM comerciales WHERE comercial = 'VASILY'")
    cur.execute("UPDATE clientes SET comercial = 'VASYL' WHERE comercial = 'VASILY'")
    cur.execute("UPDATE cotizaciones SET comercial = 'VASYL' WHERE comercial = 'VASILY'")

    for nombre, correo in COMERCIALES_INICIALES:
        cur.execute("""
            INSERT INTO comerciales (comercial, email_comercial)
            VALUES (?, ?)
            ON CONFLICT(comercial) DO UPDATE SET email_comercial = excluded.email_comercial
        """, (nombre.upper().strip(), correo.strip()))

    for nombre, correo in RESPONSABLES_INICIALES:
        cur.execute("""
            INSERT INTO responsables (responsable, email_responsable)
            VALUES (?, ?)
            ON CONFLICT(responsable) DO UPDATE SET email_responsable = excluded.email_responsable
        """, (nombre.upper().strip(), correo.strip()))

    for nombre, correo in DIRECCION_INICIAL:
        cur.execute("""
            INSERT INTO direccion (persona, email_persona)
            VALUES (?, ?)
            ON CONFLICT(persona) DO UPDATE SET email_persona = excluded.email_persona
        """, (nombre.upper().strip(), correo.strip()))

    cur.execute("""
        INSERT OR IGNORE INTO config_smtp (id, smtp_host, smtp_port, smtp_user, smtp_password, use_tls)
        VALUES (1, '', 587, '', '', 1)
    """)

    for emp in CARTERA_ENEKO:
        cur.execute("""
            INSERT OR IGNORE INTO clientes (cliente, contacto_habitual, comercial)
            VALUES (?, '', 'ENEKO')
        """, (emp.upper().strip(),))

    conn.commit()
    conn.close()


def registrar_historial(id_cotizacion, usuario, canal_accion, resultado_envio, detalle):
    conn = get_conn()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        INSERT INTO seguimiento (id_cotizacion, fecha_hora, usuario, canal_accion, resultado_envio, detalle)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (id_cotizacion, ahora, usuario.upper().strip(), canal_accion, resultado_envio, detalle))
    conn.execute("""
        UPDATE cotizaciones SET ultima_actualizacion = ? WHERE id = ?
    """, (ahora, id_cotizacion))
    conn.commit()
    conn.close()