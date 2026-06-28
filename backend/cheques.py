"""
backend/cheques.py — Generación del PDF de cheques (pagarés) listos para imprimir.

A partir de la hoja `Resumen_Músicos` de un Excel ya editado por el usuario, lee la
columna `Total Truncado` (importe definitivo de cada músico) y genera un PDF con un
cheque por bloque, calibrado para imprimirse SOBRE el papel preimpreso de pagarés de
Caixa Popular.

La hoja física mide 20 × 30,4 cm con 4 cheques (76 mm de alto cada uno). Todas las
posiciones de calibración están centralizadas en las constantes de abajo (en mm,
medidas desde la esquina superior izquierda de cada cheque). Para afinar el encaje:
imprime la "página de calibración" sobre un cheque en blanco, mide el desfase y ajusta
`OFFSET_X` / `OFFSET_Y` (corrección global) o la posición de cada campo.
"""

import unicodedata
from datetime import date, datetime
from io import BytesIO

import pandas as pd
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


class ChequeError(Exception):
    """Error de negocio al preparar los cheques (mensaje apto para el usuario)."""


# ======================================================================
# CALIBRACIÓN — todo en milímetros
# ======================================================================
PAGE_W = 200.0        # ancho de la hoja
PAGE_H = 304.0        # alto de la hoja
CHEQUE_H = 76.0       # alto de cada cheque (304 / 4)
N_PER_PAGE = 4        # cheques por hoja

# Corrección global aplicada a TODOS los campos (ajústala tras la prueba de
# calibración si todo el texto sale desplazado en la misma dirección).
# Signo (coherente con la X/Y por campo): X+ = derecha, Y+ = abajo.
DEFAULT_OFFSET_X = 0.0
DEFAULT_OFFSET_Y = 0.0

# Deriva acumulativa por cheque dentro de una misma hoja (mm). El cheque de la
# posición i se desplaza i·deriva, para compensar que el papel se va corriendo
# poco a poco hacia abajo/lado al avanzar por la hoja. X+ = derecha, Y+ = abajo.
DEFAULT_DRIFT_X = 0.0
DEFAULT_DRIFT_Y = 0.0

# Posición (x, y) de cada campo, medida desde la esquina superior IZQUIERDA del
# cheque. y crece hacia ABAJO. Tamaño de fuente en puntos.
DEFAULT_FIELDS = {
    "eur":      {"x": 122.0, "y": 21.5, "size": 12},   # # importe #   (junto a "EUR.")
    "portador": {"x": 24.0,  "y": 30.5, "size": 11},   # "Al Portador" (línea "A")
    "euros":    {"x": 30.0,  "y": 37.0, "size": 11},   # importe en letra (línea "Euros")
    # La línea de emisión ya trae "de ... de" impreso: día, mes y año van en
    # tres huecos separados, cada uno con su propia posición.
    "data_dia": {"x": 102.0, "y": 46.0, "size": 10},   # día (en letra)
    "data_mes": {"x": 130.0, "y": 46.0, "size": 10},   # mes (en letra)
    "data_any": {"x": 160.0, "y": 46.0, "size": 10},   # año (en número)
    # Nombre del músico en el DORSO (copia autocopiable). Se imprime a doble cara.
    "dorso_nombre": {"x": 60.0, "y": 38.0, "size": 12},
}

# Campos que van en la cara delantera (cheque) y en la trasera (dorso).
FRONT_KEYS = ["eur", "portador", "euros", "data_dia", "data_mes", "data_any"]
BACK_KEYS = ["dorso_nombre"]

# Etiquetas legibles de cada campo (para el panel de calibración del frontend).
FIELD_LABELS = {
    "eur": "Importe (EUR)",
    "portador": "Al Portador",
    "euros": "Importe en letra",
    "data_dia": "Fecha · Día",
    "data_mes": "Fecha · Mes",
    "data_any": "Fecha · Año",
    "dorso_nombre": "Dorso · Nombre del músico",
}

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def get_default_calibration() -> dict:
    """Calibración por defecto (la que el frontend muestra al abrir el panel)."""
    return {
        "offset_x": DEFAULT_OFFSET_X,
        "offset_y": DEFAULT_OFFSET_Y,
        "drift_x": DEFAULT_DRIFT_X,
        "drift_y": DEFAULT_DRIFT_Y,
        "fields": {k: dict(v) for k, v in DEFAULT_FIELDS.items()},
        "labels": dict(FIELD_LABELS),
    }


def _resolve_calibration(calibration: dict | None):
    """Mezcla la calibración recibida con los valores por defecto.

    Devuelve (offset_x, offset_y, drift_x, drift_y, fields) ya completos.
    """
    cal = calibration or {}

    def _f(value, fallback):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(fallback)

    ox = _f(cal.get("offset_x"), DEFAULT_OFFSET_X)
    oy = _f(cal.get("offset_y"), DEFAULT_OFFSET_Y)
    dx = _f(cal.get("drift_x"), DEFAULT_DRIFT_X)
    dy = _f(cal.get("drift_y"), DEFAULT_DRIFT_Y)
    cfields = cal.get("fields") or {}
    fields = {}
    for key, base in DEFAULT_FIELDS.items():
        cf = cfields.get(key) or {}
        fields[key] = {
            "x": _f(cf.get("x"), base["x"]),
            "y": _f(cf.get("y"), base["y"]),
            "size": _f(cf.get("size"), base["size"]),
        }
    return ox, oy, dx, dy, fields


# ======================================================================
# NÚMERO → LETRA (valencià)
# ======================================================================
_UNITATS = [
    "zero", "u", "dos", "tres", "quatre", "cinc", "sis", "set", "huit", "nou",
    "deu", "onze", "dotze", "tretze", "catorze", "quinze", "setze",
    "dèsset", "díhuit", "dènou",
]
_DESENES = {
    2: "vint", 3: "trenta", 4: "quaranta", 5: "cinquanta",
    6: "seixanta", 7: "setanta", 8: "huitanta", 9: "noranta",
}
_CENTENES = {
    1: "cent", 2: "dos-cents", 3: "tres-cents", 4: "quatre-cents", 5: "cinc-cents",
    6: "sis-cents", 7: "set-cents", 8: "huit-cents", 9: "nou-cents",
}


def _u(n: int, noun: bool) -> str:
    """Unidad 0-9. El 1 es 'un' delante de sustantivo masculino, 'u' aislado."""
    if n == 1:
        return "un" if noun else "u"
    return _UNITATS[n]


def _two(n: int, noun: bool) -> str:
    """0-99."""
    if n < 20:
        return _u(n, noun) if n in (0, 1) else _UNITATS[n]
    d, u = divmod(n, 10)
    if u == 0:
        return _DESENES[d]
    if d == 2:
        return "vint-i-" + _u(u, noun)
    return _DESENES[d] + "-" + _u(u, noun)


def _three(n: int, noun: bool) -> str:
    """0-999."""
    if n < 100:
        return _two(n, noun)
    c, r = divmod(n, 100)
    if c == 1:
        return "cent" if r == 0 else "cent " + _two(r, noun)
    base = _CENTENES[c]
    return base if r == 0 else base + " " + _two(r, noun)


def numero_a_lletres(n: int, noun: bool = True) -> str:
    """Convierte un entero (0–999.999) a su cardinal en valencià.

    `noun=True` usa las formas delante de sustantivo masculino (euros): 'un',
    'vint-i-un'… Para fechas (día) usar `noun=False` ('u', 'vint-i-u').
    """
    n = int(n)
    if n < 0:
        raise ChequeError("No se puede escribir en letra un importe negativo.")
    if n == 0:
        return "zero"
    if n < 1000:
        return _three(n, noun)
    th, r = divmod(n, 1000)
    head = "mil" if th == 1 else _three(th, True) + " mil"
    return head if r == 0 else head + " " + _three(r, noun)


# ======================================================================
# FECHA → texto (valencià)
# ======================================================================
_MESOS = [
    "", "gener", "febrer", "març", "abril", "maig", "juny",
    "juliol", "agost", "setembre", "octubre", "novembre", "desembre",
]


def fecha_a_texto(d: date) -> str:
    """'22-06-2026' → 'Vint-i-dos de juny de 2026' (texto completo, para el listado)."""
    dia = numero_a_lletres(d.day, noun=False)
    mes = _MESOS[d.month]
    conn = "d'" if mes[0] in "aeiou" else "de "
    texto = f"{dia} {conn}{mes} de {d.year}"
    return texto[0].upper() + texto[1:]


def fecha_partes(d: date) -> dict:
    """Parte la fecha en día (letra), mes (letra) y año (número).

    El cheque ya trae los "de" impresos, así que cada parte va en su propio hueco.
    """
    dia = numero_a_lletres(d.day, noun=False)
    return {
        "dia": dia[0].upper() + dia[1:],
        "mes": _MESOS[d.month],
        "any": str(d.year),
    }


def _parse_fecha(value) -> date:
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ChequeError(f"Fecha de emisión no válida: '{value}'. Usa el formato AAAA-MM-DD.")


# ======================================================================
# LECTURA DEL EXCEL
# ======================================================================
def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def _find_sheet(xl: pd.ExcelFile) -> str:
    for name in xl.sheet_names:
        n = _norm(name)
        if "resumen" in n and ("music" in n or "músic" in n or "musi" in n):
            return name
    raise ChequeError(
        "No encuentro la hoja 'Resumen_Músicos' en el Excel. "
        f"Hojas presentes: {', '.join(xl.sheet_names)}."
    )


def _find_col(cols, *needles):
    norm = {c: _norm(c) for c in cols}
    for c, n in norm.items():
        if any(needle in n for needle in needles):
            return c
    return None


def read_cheque_amounts(file_bytes: bytes):
    """Lee (nombre, importe entero, importe en letra) de cada músico con importe > 0.

    Devuelve (items, info) donde info detalla qué hoja/columnas se usaron y avisos.
    """
    try:
        xl = pd.ExcelFile(BytesIO(file_bytes))
    except Exception as e:
        raise ChequeError(f"No se pudo abrir el Excel: {e}")

    sheet = _find_sheet(xl)
    df = xl.parse(sheet)

    name_col = _find_col(df.columns, "musico", "nombre", "nom")
    if name_col is None:
        raise ChequeError(
            f"No encuentro la columna del nombre del músico en la hoja '{sheet}'."
        )

    warnings = []
    amount_col = _find_col(df.columns, "truncad")
    if amount_col is None:
        amount_col = _find_col(df.columns, "importe_final", "importe final")
        if amount_col is None:
            raise ChequeError(
                f"No encuentro la columna 'Total Truncado' (ni 'Importe_Final') en '{sheet}'."
            )
        warnings.append(
            f"No había columna 'Total Truncado'; se usó '{amount_col}' como importe."
        )

    items = []
    for _, row in df.iterrows():
        nombre = row[name_col]
        if pd.isna(nombre) or not str(nombre).strip():
            continue
        raw = row[amount_col]
        if pd.isna(raw):
            continue
        try:
            importe = int(float(raw))   # trunca a euros enteros
        except (TypeError, ValueError):
            continue
        if importe <= 0:
            continue
        items.append({
            "nombre": str(nombre).strip(),
            "importe": importe,
            "letras": numero_a_lletres(importe, noun=True),
        })

    if not items:
        raise ChequeError(
            f"No hay ningún músico con importe > 0 en la columna '{amount_col}'."
        )

    info = {"sheet": sheet, "name_col": name_col, "amount_col": amount_col, "warnings": warnings}
    return items, info


def get_sample_items():
    """Músicos de muestra para probar la calibración sin necesidad de un Excel real.

    Incluye un nombre largo y un importe grande a propósito, para comprobar el encaje.
    """
    raw = [
        ("Joan Pasqual Server", 223),
        ("Maria Llopis Gil", 93),
        ("Vicent Bernabéu Ferrandis", 1234),
        ("Anna Mompó Esteve", 50),
    ]
    return [
        {"nombre": n, "importe": i, "letras": numero_a_lletres(i, noun=True)}
        for n, i in raw
    ]


# ======================================================================
# NÚMERO DE SERIE (correlativo)
# ======================================================================
def _serie_to_int(serie):
    if serie is None:
        return None
    digits = "".join(ch for ch in str(serie) if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def _serie_format(n: int) -> str:
    """1125268 → '1.125.268'."""
    s = str(n)
    parts = []
    while len(s) > 3:
        parts.insert(0, s[-3:])
        s = s[:-3]
    parts.insert(0, s)
    return ".".join(parts)


# ======================================================================
# GENERACIÓN DEL PDF
# ======================================================================
def _draw_field(c, key, text, cheque_index, ox, oy, dx, dy, fields, bold=False):
    """Escribe `text` en el campo `key` del cheque `cheque_index` (0 = arriba).

    Convención de signos: X+ = derecha, Y+ = abajo (tanto offset como deriva).
    La deriva se acumula con la posición del cheque (cheque_index).
    """
    f = fields[key]
    x = (f["x"] + ox + cheque_index * dx) * mm
    # reportlab mide y desde abajo: posición del campo (desde arriba) → restar.
    top_of_cheque = PAGE_H - cheque_index * CHEQUE_H
    y = (top_of_cheque - f["y"] - oy - cheque_index * dy) * mm
    c.setFont(FONT_BOLD if bold else FONT, f["size"])
    c.drawString(x, y, text)


def generate_cheques_pdf(items, fecha_emision, serie_inicial=None, calibration=None,
                         incluir_dorso=False) -> bytes:
    """Genera el PDF con todos los cheques (4 por página) + listado de control.

    Si `incluir_dorso=True`, tras cada hoja de cheques se añade una página con el
    nombre de cada músico, para imprimir a doble cara (voltear por el lado largo) y
    que el nombre quede en la copia autocopiable del dorso.
    """
    if not items:
        raise ChequeError("No hay cheques que generar.")

    fecha = _parse_fecha(fecha_emision)
    fecha_txt = fecha_a_texto(fecha)
    partes = fecha_partes(fecha)
    serie_n = _serie_to_int(serie_inicial)
    ox, oy, dx, dy, fields = _resolve_calibration(calibration)

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(PAGE_W * mm, PAGE_H * mm))

    listado = []
    pages = [items[i:i + N_PER_PAGE] for i in range(0, len(items), N_PER_PAGE)]
    for p, page_items in enumerate(pages):
        # --- Cara delantera: los cheques ---
        for slot, item in enumerate(page_items):
            _draw_field(c, "eur", f"# {item['importe']} #", slot, ox, oy, dx, dy, fields, bold=True)
            _draw_field(c, "portador", "Al Portador", slot, ox, oy, dx, dy, fields)
            euros_txt = item["letras"][0].upper() + item["letras"][1:]
            _draw_field(c, "euros", euros_txt, slot, ox, oy, dx, dy, fields)
            _draw_field(c, "data_dia", partes["dia"], slot, ox, oy, dx, dy, fields)
            _draw_field(c, "data_mes", partes["mes"], slot, ox, oy, dx, dy, fields)
            _draw_field(c, "data_any", partes["any"], slot, ox, oy, dx, dy, fields)

            idx = p * N_PER_PAGE + slot
            serie_txt = _serie_format(serie_n + idx) if serie_n is not None else ""
            listado.append((serie_txt, item["nombre"], item["importe"]))
        c.showPage()

        # --- Cara trasera: el nombre del músico (dorso autocopiable) ---
        if incluir_dorso:
            for slot, item in enumerate(page_items):
                _draw_field(c, "dorso_nombre", item["nombre"], slot, ox, oy, dx, dy, fields)
            c.showPage()

    _draw_listado(c, listado, fecha_txt)
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def _draw_listado(c, listado, fecha_txt):
    """Página final de control: serie → músico → importe."""
    left = 18 * mm
    y = (PAGE_H - 20) * mm
    c.setFont(FONT_BOLD, 14)
    c.drawString(left, y, "Listado de control de cheques")
    y -= 8 * mm
    c.setFont(FONT, 9)
    c.drawString(left, y, f"Fecha de emisión: {fecha_txt}   ·   Total cheques: {len(listado)}")
    y -= 10 * mm

    c.setFont(FONT_BOLD, 9)
    c.drawString(left, y, "Sèrie")
    c.drawString(left + 38 * mm, y, "Músico")
    c.drawString(left + 130 * mm, y, "Importe (€)")
    y -= 2 * mm
    c.line(left, y, (PAGE_W - 18) * mm, y)
    y -= 6 * mm

    total = 0
    c.setFont(FONT, 9)
    for serie_txt, nombre, importe in listado:
        if y < 20 * mm:
            c.showPage()
            y = (PAGE_H - 20) * mm
            c.setFont(FONT, 9)
        c.drawString(left, y, serie_txt or "—")
        c.drawString(left + 38 * mm, y, nombre[:55])
        c.drawRightString((PAGE_W - 20) * mm, y, str(importe))
        total += importe
        y -= 5.5 * mm

    y -= 2 * mm
    c.line(left, y, (PAGE_W - 18) * mm, y)
    y -= 6 * mm
    c.setFont(FONT_BOLD, 9)
    c.drawString(left + 38 * mm, y, "TOTAL")
    c.drawRightString((PAGE_W - 20) * mm, y, str(total))


def generate_calibration_pdf(calibration=None, incluir_dorso=False) -> bytes:
    """Página de prueba: marca los límites de cada cheque y la posición de cada campo.

    Imprímela sobre un cheque en blanco para ver el encaje y ajustar los valores.
    Si `incluir_dorso=True`, añade una cara trasera de prueba con el nombre.
    """
    ox, oy, dx, dy, fields = _resolve_calibration(calibration)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(PAGE_W * mm, PAGE_H * mm))

    ejemplos = {
        "eur": "# 223 #",
        "portador": "Al Portador",
        "euros": "Dos-cents vint-i-tres",
        "data_dia": "Vint-i-dos",
        "data_mes": "juny",
        "data_any": "2026",
        "dorso_nombre": "Joan Pasqual Server",
    }

    def _draw_face(keys, titulo):
        for i in range(N_PER_PAGE):
            top = PAGE_H - i * CHEQUE_H
            # Marco del cheque
            c.setLineWidth(0.3)
            c.setDash(2, 2)
            c.rect(0, (top - CHEQUE_H) * mm, PAGE_W * mm, CHEQUE_H * mm)
            c.setDash()

            # Reglas en cm (borde superior e izquierdo del cheque)
            c.setFont(FONT, 5)
            for cm in range(0, int(PAGE_W // 10) + 1):
                x = cm * 10 * mm
                c.line(x, top * mm, x, (top - 3) * mm)
                c.drawString(x + 0.5 * mm, (top - 2.5) * mm, str(cm))
            for cm in range(0, int(CHEQUE_H // 10) + 1):
                y = (top - cm * 10) * mm
                c.line(0, y, 3 * mm, y)
                c.drawString(0.5 * mm, (top - cm * 10 - 2) * mm, str(cm))

            if titulo:
                c.setFont(FONT, 6)
                c.drawString(PAGE_W * mm - 50 * mm, (top - 3) * mm, titulo)

            # Posición real de cada campo: cruz + etiqueta + texto de ejemplo
            for key in keys:
                f = fields[key]
                x = (f["x"] + ox + i * dx) * mm
                y = (top - f["y"] - oy - i * dy) * mm
                c.setLineWidth(0.4)
                c.line(x - 2 * mm, y, x + 2 * mm, y)
                c.line(x, y - 2 * mm, x, y + 2 * mm)
                c.setFont(FONT, f["size"])
                c.drawString(x, y, ejemplos[key])
                c.setFont(FONT, 4)
                c.drawString(x, y + 2.5 * mm, f"[{key}  x={f['x']} y={f['y']}]")

    _draw_face(FRONT_KEYS, "")
    c.showPage()

    if incluir_dorso:
        _draw_face(BACK_KEYS, "DORSO (cara trasera)")
        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer.getvalue()
