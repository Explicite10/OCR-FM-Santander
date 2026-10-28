# -*- coding: utf-8 -*-
"""Genera la documentacion PDF de integracion de la API OCR de formas migratorias INM (Open Source).

    python docs/generar_documentacion.py . docs/Documentacion_API_OCR_INM_OpenSource.pdf
"""
import json
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

PROYECTO = Path(sys.argv[1])
SALIDA = Path(sys.argv[2])
EJ = json.loads((PROYECTO / "docs" / "ejemplos_respuesta.json").read_text(encoding="utf-8"))
PROMPT = (PROYECTO / "docs" / "PROMPT_IA.md").read_text(encoding="utf-8").split("```text", 1)[1].rsplit("```", 1)[0].strip("\n")

URL = "http://172.10.30.17:18475"
W, Hh = letter
AZUL = colors.HexColor("#1F3A5F")
AZUL2 = colors.HexColor("#2F5D8C")
CLARO = colors.HexColor("#E8EEF6")
GRIS = colors.HexColor("#5F6368")
LINEA = colors.HexColor("#D0D7E2")
CODIGO_BG = colors.HexColor("#F4F6F9")
VERDE = colors.HexColor("#2E7D32")
AMBAR = colors.HexColor("#B26A00")
ROJO = colors.HexColor("#B3261E")

ss = getSampleStyleSheet()
S = {
    "h1": ParagraphStyle("h1", keepWithNext=1, fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=AZUL, spaceBefore=4, spaceAfter=10),
    "h2": ParagraphStyle("h2", keepWithNext=1, fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=AZUL2, spaceBefore=12, spaceAfter=6),
    "h3": ParagraphStyle("h3", keepWithNext=1, fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=colors.black, spaceBefore=8, spaceAfter=4),
    "p": ParagraphStyle("p", fontName="Helvetica", fontSize=9.6, leading=14, spaceAfter=6),
    "li": ParagraphStyle("li", fontName="Helvetica", fontSize=9.6, leading=14, leftIndent=14, bulletIndent=4, spaceAfter=3),
    "cel": ParagraphStyle("cel", fontName="Helvetica", fontSize=8.4, leading=11),
    "celb": ParagraphStyle("celb", fontName="Helvetica-Bold", fontSize=8.4, leading=11),
    "celw": ParagraphStyle("celw", fontName="Helvetica-Bold", fontSize=8.4, leading=11, textColor=colors.white),
    "celm": ParagraphStyle("celm", fontName="Courier", fontSize=8, leading=11),
    "code": ParagraphStyle("code", fontName="Courier", fontSize=7.7, leading=10.2),
    "nota": ParagraphStyle("nota", fontName="Helvetica", fontSize=9, leading=13),
    "toc0": ParagraphStyle("toc0", fontName="Helvetica-Bold", fontSize=10.2, leading=15, leftIndent=0),
    "toc1": ParagraphStyle("toc1", fontName="Helvetica", fontSize=9.0, leading=12.5, leftIndent=16, textColor=GRIS),
}


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(t, st="p"):
    return Paragraph(t, S[st])


def H1(t):
    p = Paragraph(t, S["h1"]); p._toc = (0, t); return p


def H2(t):
    p = Paragraph(t, S["h2"]); p._toc = (1, t); return p


def H3(t):
    return Paragraph(t, S["h3"])


def LI(items, st="li"):
    return [Paragraph(t, S[st], bulletText="•") for t in items]


def m(t):
    """texto monoespaciado en linea"""
    return f'<font name="Courier" size="8.6">{esc(t)}</font>'


def _envolver(linea, ancho=104):
    """Parte lineas largas en el ultimo espacio, con sangria de continuacion."""
    if len(linea) <= ancho:
        return [linea]
    sangria = " " * (len(linea) - len(linea.lstrip()) + 4)
    out, resto = [], linea
    while len(resto) > ancho:
        corte = resto.rfind(" ", 0, ancho)
        if corte <= len(sangria):
            corte = ancho
        out.append(resto[:corte])
        resto = sangria + resto[corte:].lstrip()
    out.append(resto)
    return out


def code(texto, titulo=None, lineas_por_bloque=14):
    lineas = [x for l in texto.rstrip("\n").split("\n") for x in _envolver(l)]
    filas = []
    if titulo:
        filas.append([Paragraph(titulo, S["celw"])])
    for i in range(0, len(lineas), lineas_por_bloque):
        filas.append([Preformatted("\n".join(lineas[i:i + lineas_por_bloque]), S["code"])])
    t = Table(filas, colWidths=[17.2 * cm])
    est = [("BACKGROUND", (0, 0), (-1, -1), CODIGO_BG), ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]
    if titulo:
        est += [("BACKGROUND", (0, 0), (-1, 0), AZUL2), ("TOPPADDING", (0, 0), (-1, 0), 4), ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ("NOSPLIT", (0, 0), (0, 1))]  # el titulo nunca queda solo al final de una pagina
    est += [("TOPPADDING", (0, 1 if titulo else 0), (-1, 1 if titulo else 0), 6),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 6)]
    t.setStyle(TableStyle(est))
    return [t, Spacer(1, 8)]


def tabla(encabezado, filas, anchos, mono_cols=(), zebra=True):
    data = [[Paragraph(h, S["celw"]) for h in encabezado]]
    for f in filas:
        data.append([Paragraph(str(c), S["celm"] if i in mono_cols else S["cel"]) for i, c in enumerate(f)])
    t = Table(data, colWidths=[a * cm for a in anchos], repeatRows=1)
    est = [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
           ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINEA), ("BOX", (0, 0), (-1, -1), 0.5, LINEA),
           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
           ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]
    if zebra:
        for i in range(2, len(data), 2):
            est.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F7F9FC")))
    t.setStyle(TableStyle(est))
    return [t, Spacer(1, 8)]


def caja(texto, color=AZUL2, fondo=CLARO, titulo=None):
    contenido = (f"<b>{titulo}</b><br/>" if titulo else "") + texto
    t = Table([[Paragraph(contenido, S["nota"])]], colWidths=[17.2 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fondo), ("LINEBEFORE", (0, 0), (0, -1), 3, color),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return [t, Spacer(1, 8)]


def js(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ documento

class Doc(BaseDocTemplate):
    def __init__(self, fn, **kw):
        super().__init__(fn, **kw)
        marco = Frame(2.1 * cm, 2.0 * cm, W - 4.2 * cm, Hh - 4.1 * cm, id="n")
        self.addPageTemplates([PageTemplate("portada", [Frame(0, 0, W, Hh, id="p")], onPage=portada),
                               PageTemplate("normal", [marco], onPage=pagina)])

    def afterFlowable(self, f):
        if hasattr(f, "_toc"):
            nivel, texto = f._toc
            clave = f"s{id(f)}"
            self.canv.bookmarkPage(clave)
            self.canv.addOutlineEntry(texto, clave, level=nivel, closed=nivel > 0)
            self.notify("TOCEntry", (nivel, texto, self.page, clave))


def portada(c, d):
    c.saveState()
    c.setFillColor(AZUL); c.rect(0, Hh - 9.5 * cm, W, 9.5 * cm, stroke=0, fill=1)
    c.setFillColor(AZUL2); c.rect(0, Hh - 9.8 * cm, W, 0.3 * cm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 11); c.drawString(2.4 * cm, Hh - 3.0 * cm, "GUÍA DE INTEGRACIÓN PARA DESARROLLADORES")
    c.setFont("Helvetica-Bold", 28); c.drawString(2.4 * cm, Hh - 4.6 * cm, "API OCR de Formas")
    c.drawString(2.4 * cm, Hh - 5.8 * cm, "Migratorias INM")
    c.setFont("Helvetica", 12.5)
    c.drawString(2.4 * cm, Hh - 7.2 * cm, "Extracción de datos de la tarjeta de residente del INM con PaddleOCR y")
    c.drawString(2.4 * cm, Hh - 7.8 * cm, "Qwen3-VL (open source, 100 % local) y validación MRZ y CURP")
    c.setFillColor(colors.black)
    y = Hh - 12 * cm
    filas = [("Endpoint principal", f"POST {URL}/forma-migratoria"), ("Autenticación", "Header X-API-Key"),
             ("Formato de respuesta", "JSON (sobre homologado «API Santander IA»)"),
             ("Versión de la API", "0.2.0"), ("Versión del documento", "1.0 · 28 de octubre de 2026"),
             ("Elaborado por", "Alexis Eduardo Juárez Jaimes")]
    for k, v in filas:
        c.setFont("Helvetica-Bold", 10); c.setFillColor(GRIS); c.drawString(2.4 * cm, y, k.upper())
        c.setFont("Helvetica", 11.5); c.setFillColor(colors.black); c.drawString(7.4 * cm, y, v)
        c.setStrokeColor(LINEA); c.line(2.4 * cm, y - 0.35 * cm, W - 2.4 * cm, y - 0.35 * cm)
        y -= 1.05 * cm
    c.setFont("Helvetica", 8.5); c.setFillColor(GRIS)
    c.drawString(2.4 * cm, 2.0 * cm, "Uso interno. Contiene la especificación técnica del servicio; no contiene datos de clientes.")
    c.restoreState()


def pagina(c, d):
    c.saveState()
    c.setStrokeColor(LINEA); c.line(2.1 * cm, Hh - 1.45 * cm, W - 2.1 * cm, Hh - 1.45 * cm)
    c.setFont("Helvetica", 7.8); c.setFillColor(GRIS)
    c.drawString(2.1 * cm, Hh - 1.25 * cm, "API OCR de Formas Migratorias INM (Open Source) · Guía de integración")
    c.drawRightString(W - 2.1 * cm, Hh - 1.25 * cm, "v1.0 · 28/10/2026")
    c.drawString(2.1 * cm, 1.2 * cm, "Uso interno")
    c.drawRightString(W - 2.1 * cm, 1.2 * cm, f"Página {d.page}")
    c.restoreState()


st = []
st += [NextPageTemplate("normal"), PageBreak()]

# ------------------------------------------------------------------ indice
st.append(Paragraph("Contenido", S["h1"]))
toc = TableOfContents()
toc.levelStyles = [S["toc0"], S["toc1"]]
toc.dotsMinLevel = 0
toc.tableStyle = TableStyle([("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)])
st += [toc, PageBreak()]

# ------------------------------------------------------------------ 1
st.append(H1("1. Qué hace esta API"))
st.append(P("La API recibe un expediente escaneado en PDF y devuelve en JSON los datos de la <b>tarjeta de residente del "
            "Instituto Nacional de Migración (INM)</b>: temporal, permanente o el formato antiguo «Inmigrado», junto con la "
            "zona MRZ del reverso, las comprobaciones cruzadas entre todas las fuentes y las validaciones del plan de atención. "
            "Si el expediente trae otros documentos (pasaporte, credencial INE, licencia...) se detectan y se reportan, pero no "
            "se extraen. Todo el procesamiento es <b>open source y corre en el servidor de la empresa</b>: PaddleOCR para el texto "
            "y el modelo de visión Qwen3-VL 8B para leer la tarjeta. Ningún documento sale de la red interna."))
st.append(H2("1.1 Cómo funciona por dentro"))
st += tabla(["Paso", "Qué ocurre"], [
    ("1. Recepción", "Valida la API key, que el archivo sea PDF, su tamaño (25 MB) y páginas (30), y que se pueda abrir."),
    ("2. Render y OCR", "Convierte hasta 6 páginas a imagen (250 dpi) y PaddleOCR lee todo el texto. Con ese texto ubica el "
                        "anverso (título «RESIDENTE TEMPORAL / PERMANENTE» o encabezado del INM) y el reverso (la MRZ I&lt;MEX), "
                        "probando la página girada 90°, 180° y 270° si hace falta."),
    ("3. Filtro", "Descarta hojas en blanco (221). Una credencial INE sola (MRZ IDMEX) o un expediente sin ninguna señal de "
                  "tarjeta INM responde 220. Pasaportes, INE y licencias en el mismo PDF se reportan en clasificacion."),
    ("4. Recortes", "Recorta y endereza cada cara. Si el OCR no encontró las anclas (tarjeta inclinada, chica o muy tenue), el "
                    "modelo de visión localiza la tarjeta y se repite el OCR sobre ese recorte."),
    ("5. Lectura de la tarjeta", "Qwen3-VL lee el anverso y devuelve un JSON con esquema fijo. Lee también el reverso cuando la "
                                 "MRZ no cuadra o falta el folio SEGOB-INM."),
    ("6. MRZ del reverso", "Lee las 3 líneas de la MRZ con el OCR y verifica sus dígitos de control (número, fecha de "
                           "nacimiento, fecha de expedición y compuesto). Si no cuadran, también la pide al modelo de visión."),
    ("7. Fusión y validación", "Cruza cada dato entre sus fuentes (modelo de visión, OCR, MRZ y CURP), corrige confusiones "
                               "típicas (O/0, I/1), corrige la ortografía y el orden de apellidos y nombres con la MRZ, toma el "
                               "lugar y la fecha de expedición del reverso y asigna una confianza por campo."),
    ("8. Plan de atención", "Si se envían los datos capturados en la solicitud, responde las 8 validaciones del plan de atención "
                            "(sección Forma Migratoria) con SÍ/NO y los motivos de rechazo."),
    ("9. Respuesta", "Entrega el JSON con un código que indica la calidad de la extracción. Si el servidor tiene base de datos, "
                     "guarda el resultado (nunca la imagen) y devuelve su id."),
], [3.4, 13.8])
st.append(H2("1.2 Fuentes que se cruzan para cada dato"))
st.append(P("La precisión viene de que casi todo dato tiene al menos dos fuentes independientes o un dígito verificador:"))
st += tabla(["Dato", "Fuentes"], [
    ("Número de documento (tarjeta)", "MRZ (dígito verificador) vs «No.» del reverso"),
    ("Fecha de nacimiento", "MRZ (dígito verificador), anverso, CURP"),
    ("Fecha de expedición", "MRZ (dígito verificador; el INM la pone en la posición ICAO del vencimiento), anverso y "
                            "«Expedido en» del reverso en tarjetas antiguas"),
    ("Fecha de vencimiento", "Anverso (solo impresa; no existe en Residente Permanente)"),
    ("Sexo", "Anverso, MRZ (M/F) y CURP (H/M)"),
    ("Apellidos y nombres", "Modelo de visión, OCR del renglón «Nombre / Name» (apellidos en mayúsculas), línea 3 de la MRZ e "
                            "iniciales de la CURP"),
    ("CURP (entidad NE)", "Estructura, dígito verificador, fecha y sexo de la MRZ; se repara con la MRZ si un dígito se leyó mal"),
    ("Nacionalidad / país", "Gentilicio impreso y código de 3 letras vs nacionalidad de la MRZ"),
    ("NUE, SEGOB-INM, lugar de impresión, permiso", "Modelo de visión vs OCR"),
], [5.0, 12.2])
st.append(H2("1.3 Documentos soportados"))
st += LI(["<b>Tarjeta de Residente Temporal</b> (con o sin permiso para trabajar).",
          "<b>Tarjeta de Residente Permanente</b> (no tiene fecha de vencimiento).",
          "<b>Tarjeta «Inmigrado»</b> de formato antiguo (residencia definitiva).",
          "Fotocopias en blanco y negro, con sellos de cotejo, tarjetas giradas o chicas en la hoja, y expedientes con "
          "pasaporte, INE u otros documentos en el mismo PDF.",
          "<b>No soportados:</b> FMM, formas FM2/FM3 en libreta, pasaportes, credencial INE sola y cualquier otro documento: "
          "devuelven el código <b>220</b>."])
st += caja("La tarjeta debe venir con <b>anverso y reverso en el mismo PDF</b> y dentro de las <b>primeras 6 páginas</b>. El "
           "reverso contiene la MRZ, que es la base de la validación: sin reverso los datos se entregan, pero con menos "
           "comprobaciones (códigos 211 o 212).", titulo="Importante")

# ------------------------------------------------------------------ 2
st.append(H1("2. Inicio rápido"))
st += LI(["Solicita la <b>API key</b> al responsable del servicio. Guárdala en una variable de entorno o gestor de "
          "secretos, nunca en el código.",
          f"Envía el PDF por <b>POST multipart/form-data</b> en el campo {m('file')} a {m('/forma-migratoria')} "
          f"con el header {m('X-API-Key')}.",
          "Para validar contra la solicitud, agrega en el mismo formulario nombre, curp, fecha_nacimiento y "
          "nacionalidad capturados (sección 4.1).",
          f"Lee {m('validacion_plan.cumple')} para saber si el documento pasa el plan de atención, y {m('codigo')} "
          "para la calidad de la extracción (secciones 5.6 y 6)."])
st += code(f'''curl -X POST "{URL}/forma-migratoria" \\
  -H "X-API-Key: $OCR_INM_API_KEY" \\
  -F "file=@expediente.pdf;type=application/pdf" \\
  -F "nombre=Maria Fernanda Perez Gomez" \\
  -F "curp=PEGF900609MNERMR07" \\
  -F "fecha_nacimiento=1990-06-09" \\
  -F "nacionalidad=Colombiana"''', "Ejemplo (curl)")

# ------------------------------------------------------------------ 3
st.append(H1("3. Conexión"))
st += tabla(["Concepto", "Valor"], [
    ("URL base", m(URL)),
    ("Red", "Red interna de la empresa (servidor srviatwo). El servicio no está expuesto a internet."),
    ("Protocolo", "HTTP (sin TLS). Ver sección 10, Seguridad."),
    ("Autenticación", f"Header {m('X-API-Key')} con la clave del servicio. Sin ella se responde 401."),
    ("Formato de respuesta", "JSON UTF-8, siempre con el mismo sobre (sección 5), igual que la API de Document AI."),
    ("Documentación interactiva", f"Swagger en {m(URL + '/docs')} (categorías Forma migratoria, Pruebas, Historial y Sistema) "
                                  f"y especificación OpenAPI en {m(URL + '/openapi.json')}"),
], [4.2, 13])
st.append(H2("3.1 Endpoints"))
st += tabla(["Método", "Ruta", "Auth", "Uso"], [
    ("POST", m("/forma-migratoria"), "Sí", "<b>Endpoint principal.</b> Usar este en todas las integraciones."),
    ("POST", m("/extract"), "Sí", "Alias para pruebas. Responde exactamente igual que /forma-migratoria."),
    ("GET", m("/v1/forma-migratoria/extracciones"), "Sí", "Historial de resultados guardados, con filtros. Requiere base de "
                                                          "datos (hoy no está habilitada en el servidor: responde 503)."),
    ("GET", m("/v1/forma-migratoria/extracciones/{id}"), "Sí", "Resultado completo guardado de una extracción."),
    ("PUT", m("/v1/forma-migratoria/extracciones/{id}/revision"), "Sí", "Guarda la corrección hecha por una persona."),
    ("GET", m("/health"), "No", "Estado del servicio, del modelo de visión y de la base de datos, para monitoreo."),
], [1.4, 6.4, 1.1, 8.3])
st.append(H2("3.2 Límites y tiempos"))
st += tabla(["Concepto", "Valor", "Qué pasa si se excede"], [
    ("Tamaño máximo", "25 MB por archivo", "Código 413"),
    ("Tipos aceptados", "Solo PDF (se verifica el contenido, no la extensión)", "Código 400"),
    ("Archivos por petición", "1", "Solo se procesa el campo file"),
    ("Páginas", "Hasta 30; se analizan las primeras 6 (la tarjeta suele venir al principio)", "Código 224"),
    ("Tiempo de respuesta", "15 a 25 segundos por expediente (en lote con 2 en paralelo: mediana 20 s, p90 47 s)", "-"),
    ("Peticiones simultáneas", "2 se procesan a la vez (una GPU de 8 GB compartida)", "Las demás esperan su turno (ver 7.3)"),
    ("Timeout recomendado en el cliente", "120 segundos", "-"),
], [4.4, 7.0, 5.8])

# ------------------------------------------------------------------ 4
st.append(H1("4. Petición"))
st += tabla(["Elemento", "Valor"], [
    ("Método y ruta", m("POST /forma-migratoria")),
    ("Content-Type", m("multipart/form-data")),
    ("Header obligatorio", m("X-API-Key: <tu clave>")),
    ("Campo del archivo", f"{m('file')} (obligatorio). Si falta o tiene otro nombre: código 422."),
    ("Tipo del archivo", f"PDF. Indicar {m('application/pdf')} en la parte del archivo. La API revisa el contenido real: un "
                         "archivo que dice ser PDF y no lo es responde 222; una imagen responde 400."),
], [4.0, 13.2])
st.append(H2("4.1 Datos de la solicitud (opcionales)"))
st.append(P("Campos de texto en el mismo formulario. Con ellos la API responde las validaciones de coincidencia del "
            "plan de atención. Sin ellos la extracción funciona igual, pero esas validaciones quedan como "
            "NO_VERIFICADO y el plan no se cumple."))
st += tabla(["Campo", "Formato", "Uso"], [
    ("nombre", "Texto", "Nombre completo capturado, en cualquier orden (nombres y apellidos)."),
    ("apellido_paterno, apellido_materno, nombres", "Texto", "Alternativa a nombre, si la solicitud los captura por separado."),
    ("curp", "18 caracteres", "Solo si la solicitud tiene CURP. Si no se envía, la validación queda NO_APLICA y no bloquea."),
    ("fecha_nacimiento", "AAAA-MM-DD", "También acepta DD/MM/AAAA."),
    ("nacionalidad", "Texto", "Gentilicio (Colombiana), país (Colombia) o código ISO de 2 o 3 letras (CO, COL)."),
], [5.2, 2.6, 9.4], mono_cols=(0,))
st.append(H2("4.2 Ejemplos por lenguaje"))
st += code(f'''import os
import requests

URL = "{URL}/forma-migratoria"
API_KEY = os.environ["OCR_INM_API_KEY"]

def extraer_forma_migratoria(ruta_pdf: str, solicitud: dict | None = None) -> dict:
    with open(ruta_pdf, "rb") as f:
        resp = requests.post(
            URL,
            headers={{"X-API-Key": API_KEY}},
            files={{"file": (os.path.basename(ruta_pdf), f, "application/pdf")}},
            data=solicitud or {{}},   # nombre, curp, fecha_nacimiento, nacionalidad
            timeout=120,
        )
    return resp.json()          # siempre trae codigo, estado y mensaje

r = extraer_forma_migratoria("expediente.pdf", {{
    "nombre": "Maria Fernanda Perez Gomez", "curp": "PEGF900609MNERMR07",
    "fecha_nacimiento": "1990-06-09", "nacionalidad": "Colombiana",
}})
plan = r.get("validacion_plan")
if plan:
    print("Cumple el plan:", plan["cumple"], "-", plan["mensaje"])
    for motivo in plan["motivos_rechazo"]:
        print("  -", motivo)
if r["codigo"] in (200, 210, 211, 212):
    print(r["datos"].get("nombre_completo"))   # usar .get(): las llaves pueden faltar''',
                "Python (requests)")
st += code(f'''import {{ readFile }} from "node:fs/promises";

const URL = "{URL}/forma-migratoria";

export async function extraerFormaMigratoria(rutaPdf, solicitud = {{}}) {{
  const buffer = await readFile(rutaPdf);
  const form = new FormData();
  form.append("file", new Blob([buffer], {{ type: "application/pdf" }}), "expediente.pdf");
  // solicitud: {{ nombre, curp, fecha_nacimiento, nacionalidad }} (opcionales)
  for (const [k, v] of Object.entries(solicitud)) if (v) form.append(k, v);

  const resp = await fetch(URL, {{
    method: "POST",
    headers: {{ "X-API-Key": process.env.OCR_INM_API_KEY }},
    body: form,
    signal: AbortSignal.timeout(120_000),
  }});
  return await resp.json();   // {{ codigo, estado, mensaje, datos?, validacion_plan?, ... }}
}}''', "JavaScript / Node.js 18+ (fetch nativo)")
st += code(f'''using System.Net.Http.Headers;
using System.Text.Json;

var http = new HttpClient {{ Timeout = TimeSpan.FromSeconds(120) }};
http.DefaultRequestHeaders.Add("X-API-Key", Environment.GetEnvironmentVariable("OCR_INM_API_KEY"));

using var form = new MultipartFormDataContent();
var archivo = new ByteArrayContent(await File.ReadAllBytesAsync("expediente.pdf"));
archivo.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
form.Add(archivo, "file", "expediente.pdf");
form.Add(new StringContent("Maria Fernanda Perez Gomez"), "nombre");   // datos de la solicitud (opcionales)
form.Add(new StringContent("1990-06-09"), "fecha_nacimiento");
form.Add(new StringContent("Colombiana"), "nacionalidad");

var resp = await http.PostAsync("{URL}/forma-migratoria", form);
using var json = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
int codigo = json.RootElement.GetProperty("codigo").GetInt32();
if (json.RootElement.TryGetProperty("validacion_plan", out var plan))
    Console.WriteLine($"Cumple: {{plan.GetProperty("cumple").GetBoolean()}}");
if (codigo is 200 or 210 or 211 or 212)
{{
    var datos = json.RootElement.GetProperty("datos");
    if (datos.TryGetProperty("curp", out var curp)) Console.WriteLine(curp.GetString());
}}''', "C# (.NET 6+)")
st += code(f'''<?php
$ch = curl_init("{URL}/forma-migratoria");
curl_setopt_array($ch, [
    CURLOPT_POST           => true,
    CURLOPT_HTTPHEADER     => ["X-API-Key: " . getenv("OCR_INM_API_KEY")],
    CURLOPT_POSTFIELDS     => [
        "file"             => new CURLFile("expediente.pdf", "application/pdf", "expediente.pdf"),
        "nombre"           => "Maria Fernanda Perez Gomez",   // datos de la solicitud (opcionales)
        "fecha_nacimiento" => "1990-06-09",
        "nacionalidad"     => "Colombiana",
    ],
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT        => 120,
]);
$body = json_decode(curl_exec($ch), true);
curl_close($ch);

$cumple = $body["validacion_plan"]["cumple"] ?? false;
if (in_array($body["codigo"], [200, 210, 211, 212])) {{
    $curp = $body["datos"]["curp"] ?? null;   // la llave puede no venir
}}''', "PHP (cURL)")

# ------------------------------------------------------------------ 5
st.append(H1("5. Estructura de la respuesta"))
st.append(P("Todas las respuestas, exitosas o de error, comparten el mismo sobre (formato homologado «API Santander IA», el "
            "mismo que la API de formas migratorias con Document AI y las APIs de INE y pasaporte). Los bloques de datos solo "
            "aparecen cuando aplican. <b>Regla general: si un dato no se pudo leer, la llave no aparece</b> (no viene con "
            f"{m('null')} ni vacía). Accede a los campos de forma segura."))
st += code('''{
  "codigo": 200,                 // número: qué pasó (sección 6). Úsalo para decidir.
  "estado": "PROCESADO",         // texto fijo equivalente al código
  "mensaje": "...",              // texto para mostrar a una persona; puede cambiar
  "id": "4f1c...",               // id del resultado guardado        (solo si hay base de datos)
  "datos": { ... },              // datos de la tarjeta              (solo códigos 200-212)
  "mrz": { ... },                // lectura y validación de la MRZ    (solo códigos 200-212)
  "validacion": { ... },         // comprobaciones cruzadas           (solo códigos 200-212)
  "avisos": [ ... ],             // puntos a revisar por una persona  (solo códigos 200-212)
  "clasificacion": { ... },      // qué documento se detectó          (códigos 200-221)
  "confianza": { ... },          // nivel de confianza por campo      (solo códigos 200-212)
  "meta": { ... },               // tiempos, páginas, motor           (códigos 200-221)
  "validacion_plan": { ... }     // las 8 validaciones del plan       (códigos 200-221)
}''', "Sobre de la respuesta")
st.append(H2("5.1 Bloque datos"))
st += tabla(["Campo", "Tipo", "Ejemplo", "Descripción"], [
    ("tipo_documento", "texto", "RESIDENTE TEMPORAL", "RESIDENTE TEMPORAL · RESIDENTE PERMANENTE · INMIGRADO"),
    ("nue", "texto", "0000001234567", "Número Único de Extranjero (13 dígitos)."),
    ("apellidos", "texto", "PEREZ GOMEZ", "En mayúsculas. Ortografía y separación verificadas con la MRZ."),
    ("nombres", "texto", "MARIA FERNANDA", "En mayúsculas."),
    ("nombre_completo", "texto", "PEREZ GOMEZ MARIA FERNANDA", "Apellidos seguidos de nombres."),
    ("nacionalidad", "texto", "COLOMBIANA", "Gentilicio impreso. En tarjetas antiguas puede venir como código (HTI)."),
    ("pais", "texto", "COL", "Código ISO de 3 letras del país de nacionalidad."),
    ("sexo", "texto", "M", "<b>H = hombre, M = mujer</b> (convención mexicana)."),
    ("fecha_nacimiento", "fecha", "1990-06-09", "Formato AAAA-MM-DD."),
    ("curp", "texto", "PEGF900609MNERMR07", "18 caracteres, con dígito verificador. Puede faltar en tarjetas antiguas."),
    ("permiso_para_trabajar", "booleano", "true", "true si la tarjeta trae la leyenda «PERMISO PARA TRABAJAR»; false si no."),
    ("fecha_expedicion", "fecha", "2025-01-13", "AAAA-MM-DD. En tarjetas antiguas se toma de «Expedido en» del reverso."),
    ("fecha_vencimiento", "fecha", "2027-01-12", "AAAA-MM-DD. <b>No aparece</b> en permanente ni inmigrado."),
    ("vigente", "booleano", "true", "Con la regla del plan (año de vencimiento ≥ año actual). Permanente e inmigrado: true."),
    ("numero_documento", "texto", "12345678", "Número de la tarjeta («No.» del reverso), respaldado por la MRZ."),
    ("numero_segob_inm", "texto", "SEGOB-INM-00123456", "Folio impreso en el reverso. No existe en tarjetas antiguas."),
    ("impreso_en", "texto", "OR CIUDAD DE MEXICO, 15/01/2025", "Oficina y fecha de «Impreso en» / «Expedido en», tal como están impresas."),
    ("condicion_estancia", "texto", "-", "Solo si el reverso la imprime (tarjetas antiguas)."),
    ("pais_emisor", "texto", "MEX", "Siempre MEX."),
], [4.0, 1.6, 4.4, 7.2], mono_cols=(0, 2))
st.append(H2("5.2 Bloque mrz"))
st.append(P("La MRZ son las tres líneas de 30 caracteres al pie del reverso (formato ICAO TD1). Sus números y fechas traen "
            "dígitos de control, por eso es la fuente más confiable. Cuando no se pudo leer, el bloque solo trae "
            f"{m('error')} (y a veces {m('texto_crudo')})."))
st += tabla(["Campo", "Tipo", "Descripción"], [
    ("lineas", "lista", "Las 3 líneas tal como se leyeron."),
    ("tipo_documento / pais_emisor", "texto", "«I&lt;» / MEX."),
    ("numero_documento", "texto", "Número de la tarjeta según la MRZ."),
    ("fecha_nacimiento", "fecha", "AAAA-MM-DD."),
    ("sexo", "texto", "<b>M o F</b> (convención internacional de la MRZ; en datos se convierte a H/M)."),
    ("fecha_expedicion", "fecha", "AAAA-MM-DD. En la tarjeta INM esta posición de la MRZ es la fecha de expedición."),
    ("sin_fecha_expedicion", "booleano", "true cuando la MRZ no trae fecha (frecuente en permanentes antiguas)."),
    ("nacionalidad", "texto", "Código ISO de 3 letras."),
    ("apellidos / nombres", "texto", "Según la MRZ. Pueden venir recortados: la línea mide 30 caracteres."),
    ("digitos_control", "objeto", "numero_documento, fecha_nacimiento, fecha_expedicion (null si no hay fecha) y compuesto: "
                                  "true si el dígito cuadra."),
    ("integra", "booleano", "true si todos los dígitos de control cuadran."),
    ("origen", "texto", "texto (leída del OCR) o entidad (leída por el modelo de visión)."),
    ("error", "texto", "Solo cuando no se localizó o no se pudo leer la MRZ."),
], [4.6, 1.7, 10.9], mono_cols=(0,))
st.append(H2("5.3 Bloque validacion"))
st += tabla(["Campo", "Tipo", "Descripción"], [
    ("ok", "booleano", "true si no hay discrepancias."),
    ("completo", "booleano", "true si se pudieron correr todas las comprobaciones."),
    ("coincidencias", "lista de texto", "Comprobaciones que cuadraron."),
    ("discrepancias", "lista de texto", "Datos que se contradicen. <b>Si no está vacía, el código es 210.</b>"),
    ("sin_verificar", "lista de texto", "Comprobaciones que no se pudieron hacer (dato faltante, sin MRZ...)."),
], [3.4, 2.6, 11.2], mono_cols=(0,))
st.append(P("Comprobaciones que realiza la API: dígitos de control de la MRZ · número de documento (reverso vs MRZ) · "
            "fecha de nacimiento (anverso, MRZ y CURP) · fecha de expedición (anverso vs MRZ) · sexo (anverso, MRZ y CURP) · "
            "apellidos y nombres (MRZ) · país vs nacionalidad (MRZ) · estructura y dígito verificador de la CURP · CURP vs "
            "fecha de nacimiento, sexo y nombre (iniciales) · CURP con entidad NE (nacido en el extranjero) · fecha de "
            "expedición anterior al vencimiento."))
st.append(H2("5.4 avisos, clasificacion, confianza y meta"))
st += tabla(["Bloque", "Contenido"], [
    ("avisos", "Lista de textos con puntos que conviene revisar a mano, aunque no sean contradicciones: un dato del anverso "
               "se leyó distinto y se entregó el de la MRZ, un campo con confianza baja, la fecha de expedición se tomó del "
               "reverso... <b>Si no está vacía, el código es 211.</b>"),
    ("clasificacion", "categoria: forma_migratoria · otro · hoja_en_blanco. caracteres_leidos: cantidad de texto detectado. "
                      "senales: indicios de tarjeta INM que encontró el OCR. otros_documentos: otros documentos vistos en el "
                      "PDF (pasaporte, ine...). motivo y documento_detectado: solo en 220/221. confianza: siempre null."),
    ("confianza", "Nivel por campo (tipo_documento, nue, nombre, fecha_nacimiento, sexo, curp, pais, nacionalidad, fechas, "
                  "numero_documento, numero_segob_inm): <b>alta</b> = dos fuentes independientes coinciden o lo respalda un "
                  "dígito verificador · <b>media</b> = una sola fuente con estructura válida · <b>baja</b> = desacuerdo o "
                  "ilegible. Úsalo para resaltar campos en pantallas de revisión."),
    ("meta", "tiempo_total_ms, tiempos_ms por etapa, paginas, paginas_forma_migratoria, paginas_ignoradas, motor "
             "(paddleocr+vlm), version_modelo, pagina_anverso / pagina_reverso, recorte_anverso / recorte_reverso (ancla, "
             "localizador o pagina_completa) y mrz_fuente. Informativo; no tomar decisiones con él."),
], [3.0, 14.2], mono_cols=(0,))
st.append(H2("5.5 Historial y revisión humana"))
st.append(P("Cuando el servidor tiene base de datos (variable DATABASE_URL), cada resultado se guarda (solo el JSON, nunca "
            "la imagen) y la respuesta trae su id. Con GET /v1/forma-migratoria/extracciones se listan los resultados y con "
            "PUT .../{id}/revision se guarda la corrección hecha por una persona. Hoy esa base de datos no está habilitada en "
            "el servidor: estas rutas responden 503 y la respuesta no trae id."))

st.append(H2("5.6 Bloque validacion_plan (plan de atención)"))
st.append(P("Responde las 8 validaciones del <b>Plan de atención - Validación documental</b>, sección Forma "
            "Migratoria, en el mismo orden y con la misma forma que la API de Document AI. Es independiente de "
            "<b>codigo</b>: codigo describe la calidad de la extracción y validacion_plan dice si el documento cumple el plan."))
st += tabla(["Campo", "Tipo", "Descripción"], [
    ("cumple", "booleano", "true solo si las 8 validaciones pasan al 100 %."),
    ("mensaje", "texto", "«Documento válido: cumple con todas las validaciones.» o «Revisar documento y motivo de rechazo»."),
    ("motivos_rechazo", "lista de texto", "Una línea por cada validación que no pasó, con su explicación."),
    ("regla_vigencia", "texto", "Regla usada para la vigencia: anio (plan de atención) o fecha."),
    ("validaciones", "lista", "Las 8 validaciones: id, pregunta, resultado, ok y detalle."),
], [3.6, 2.6, 11.0], mono_cols=(0,))
st += tabla(["#", "id", "Pregunta del plan", "Pasa cuando", "Regla"], [
    ("1", "hoja_en_blanco", "¿Es una hoja en blanco?", "NO", "Se leyó texto en el documento."),
    ("2", "imagen_ilegible", "¿La imagen es ilegible?", "NO", "SÍ si no hay texto, si faltan 2 o más datos esenciales "
                                                            "(nombre, fecha de nacimiento, número, NUE) o si falta uno y la MRZ tampoco se lee."),
    ("3", "es_forma_migratoria", "¿Es una FM?", "SI", "Tarjeta de residente del INM: temporal, permanente o inmigrado."),
    ("4", "vigente", "¿Está vigente?", "SI", "Año de vigencia igual o mayor al año actual. Permanente e inmigrado no vencen: SÍ."),
    ("5", "nombre_coincide", "¿El nombre coincide?", "SI", "Mismas palabras sin importar orden, acentos ni mayúsculas."),
    ("6", "curp_coincide", "¿La CURP coincide?", "SI o NO_APLICA", "Igual a la capturada. Se toleran hasta 2 caracteres que el OCR confunde "
                                                                 "(O/0, I/1, S/5, B/8...) si la CURP capturada cuadra con la fecha y el sexo verificados. "
                                                                 "Sin CURP en solicitud o tarjeta: NO_APLICA."),
    ("7", "fecha_nacimiento_coincide", "¿La fecha de nacimiento coincide?", "SI", "Misma fecha (la de la tarjeta está verificada por la MRZ)."),
    ("8", "nacionalidad_coincide", "¿La nacionalidad coincide?", "SI", "Mismo país: acepta gentilicio, nombre del país o código ISO."),
], [0.6, 4.6, 3.4, 2.0, 6.6], mono_cols=(1,))
st += tabla(["resultado", "Significado", "¿Bloquea?"], [
    ("SI / NO", "Respuesta a la pregunta del plan.", "Según la columna «Pasa cuando»"),
    ("NO_APLICA", "La comprobación no corresponde (CURP sin dato).", "No"),
    ("NO_VERIFICADO", "Faltan datos para responder: no se envió el dato de la solicitud, no se leyó en la tarjeta "
                      "o el documento no es una FM.", "Sí"),
], [3.2, 10.0, 4.0], mono_cols=(0,))
st += caja("La regla de vigencia del plan compara solo el año. Si se prefiere comparar la fecha exacta de vencimiento "
           "contra hoy, el responsable del servicio la cambia con REGLA_VIGENCIA=fecha. datos.vigente usa siempre la "
           "misma regla que el plan.", titulo="Vigencia")

# ------------------------------------------------------------------ 6
st.append(H1("6. Códigos de respuesta"))
st += caja(f"Los códigos <b>200 a 224 viajan con HTTP 200</b>, porque la petición fue correcta aunque el documento no "
           f"sirva. Decide siempre con el campo {m('codigo')} del JSON, no con el estado HTTP. Los errores 4xx y 5xx "
           f"sí viajan con su mismo estado HTTP. Los códigos son los mismos que en la API de Document AI.",
           color=AMBAR, fondo=colors.HexColor("#FFF6E5"), titulo="Regla de oro")
st.append(H2("6.1 Documento procesado (trae datos)"))
st += tabla(["Código", "estado", "Significado", "Qué hacer"], [
    ("200", "PROCESADO", "Todo cuadró: anverso, reverso, MRZ y CURP coinciden.", "<font color='#2E7D32'><b>Usar los datos directo.</b></font>"),
    ("211", "PROCESADO_CON_AVISOS", "Sin contradicciones, pero hay algo para revisar (ver avisos): un dato del anverso se "
                                    "leyó distinto y se entregó el de la MRZ, un campo con confianza baja...", "Usar los datos; revisión rápida de avisos."),
    ("212", "PROCESADO_INCOMPLETO", "Sin contradicciones ni avisos, pero alguna comprobación no se pudo hacer (ver "
                                    "sin_verificar). Poco frecuente: casi siempre viene acompañado de un aviso (211).",
     "Usar los datos; revisar los campos de sin_verificar."),
    ("210", "PROCESADO_CON_DISCREPANCIAS", "Hay datos que se contradicen (ver discrepancias). Al menos un dato puede estar mal.",
     "<font color='#B3261E'><b>No usar sin revisión humana</b></font> de los campos indicados."),
], [1.4, 5.2, 6.0, 4.6], mono_cols=(0, 1))
st.append(H2("6.2 Documento evaluado pero no extraído (sin datos)"))
st += tabla(["Código", "estado", "Significado", "Qué hacer"], [
    ("220", "NO_ES_FORMA_MIGRATORIA", "El archivo no trae tarjeta de residente del INM (pasaporte, INE, otro).", "Pedir el documento correcto."),
    ("221", "HOJA_EN_BLANCO", "No se leyó texto (menos de 10 letras o dígitos).", "Reescanear con mejor calidad."),
    ("222", "ARCHIVO_CORRUPTO", "El archivo llegó vacío, está dañado o no es el PDF que dice ser.", "Reenviar un archivo válido."),
    ("223", "PDF_PROTEGIDO", "El PDF tiene contraseña.", "Quitar la contraseña y reenviar."),
    ("224", "LIMITE_PAGINAS", "Más de 30 páginas.", "Enviar solo las páginas de la tarjeta."),
], [1.4, 5.2, 6.0, 4.6], mono_cols=(0, 1))
st.append(H2("6.3 Errores (sin datos, con su estado HTTP)"))
st += tabla(["Código / HTTP", "estado", "Causa", "Qué hacer", "¿Reintentar?"], [
    ("400", "ARCHIVO_NO_SOPORTADO", "El archivo no es PDF.", "Enviar un PDF con su tipo correcto.", "No"),
    ("401", "NO_AUTORIZADO", "Falta el header X-API-Key o la clave es incorrecta.", "Revisar configuración.", "No"),
    ("404", "NO_ENCONTRADO", "Ruta inexistente o id de extracción que no existe.", "Revisar la URL.", "No"),
    ("405", "METODO_NO_PERMITIDO", "Método HTTP incorrecto (p. ej. GET a /forma-migratoria).", "Usar POST.", "No"),
    ("413", "ARCHIVO_DEMASIADO_GRANDE", "Archivo mayor a 25 MB.", "Comprimir o enviar solo las páginas de la tarjeta.", "No"),
    ("422", "PETICION_INVALIDA", "Falta el campo file o el multipart está mal formado. El mensaje dice qué falló.", "Corregir la petición.", "No"),
    ("500", "ERROR_INTERNO", "Error no controlado de la API.", "Reportar con hora y archivo.", "Una vez"),
    ("502", "ERROR_MODELO_VISION", "El modelo de visión no respondió al leer la tarjeta (GPU ocupada o reiniciándose).", "Esperar y reintentar.", "Sí, con espera"),
    ("503", "SERVICIO_NO_DISPONIBLE", "Base de datos no configurada (solo rutas de historial).", "Avisar al responsable.", "Sí, con espera"),
], [1.6, 4.6, 4.4, 4.2, 2.4], mono_cols=(0, 1))
st += caja("Si el servidor está caído o no hay red, no llegará ningún JSON: el cliente verá un error de conexión o de "
           "timeout. Trátalo como un 502 (reintentar con espera).", titulo="Sin respuesta")

# ------------------------------------------------------------------ 7
st.append(H1("7. Integración recomendada"))
st.append(H2("7.1 Cómo decidir"))
st.append(P("Si integras el plan de atención, decide primero con <b>validacion_plan.cumple</b>: true significa que el "
            "documento pasó las 8 validaciones; false, que hay que revisar el documento con los motivos de rechazo. "
            "Usa <b>codigo</b> para los errores técnicos y para saber qué tan confiable es la extracción."))
st += code('''def decidir_plan(body: dict) -> str:
    plan = body.get("validacion_plan")
    if plan is None:                       # error técnico: no se evaluó el documento
        return decidir(body)
    if plan["cumple"]:
        return "APROBADO"
    return "REVISAR"                       # mostrar plan["motivos_rechazo"]''', "Decisión con el plan de atención (Python)")
st += code('''def decidir(body: dict) -> str:
    c = body["codigo"]
    if c == 200:
        return "ACEPTAR"                    # datos listos
    if c in (211, 212):
        return "ACEPTAR_CON_REVISION"       # revisar body["avisos"] / body["validacion"]["sin_verificar"]
    if c == 210:
        return "REVISION_OBLIGATORIA"       # revisar body["validacion"]["discrepancias"]
    if c in (220, 221):
        return "DOCUMENTO_INCORRECTO"       # pedir otro documento o reescaneo
    if c in (222, 223, 224, 400, 413, 422):
        return "ARCHIVO_INVALIDO"           # corregir el archivo o la petición; no reintentar igual
    if c == 401:
        return "ERROR_CONFIGURACION"        # API key
    return "REINTENTAR"                     # 500, 502, 503 o cualquier código desconocido''', "Lógica de decisión (Python)")
st.append(H2("7.2 Reintentos"))
st += LI(["<b>Reintentar solo 500, 502, 503 y errores de conexión o timeout</b>, con espera creciente: 2 s, 4 s y 8 s "
          "(máximo 3 intentos).",
          "<b>No reintentar</b> 4xx ni los códigos 210 a 224: el resultado no cambiará enviando el mismo archivo.",
          "El modelo de visión corre con semilla fija, así que el mismo archivo da el mismo resultado: un reintento de 211 "
          "o 212 no lo mejora."])
st += code('''import time, requests

def extraer_con_reintentos(ruta, intentos=3):
    for i in range(intentos):
        try:
            body = extraer_forma_migratoria(ruta)       # función de la sección 4.2
            if body["codigo"] not in (500, 502, 503):
                return body
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(2 ** (i + 1))                       # 2 s, 4 s, 8 s
    raise RuntimeError("OCR INM no disponible después de varios intentos")''', "Reintentos con espera (Python)")
st.append(H2("7.3 Concurrencia"))
st.append(P("La API procesa <b>2 expedientes a la vez</b> y el modelo de visión atiende una petición a la vez en la GPU "
            "(8 GB, compartida con las APIs de INE y pasaporte). Si llegan más, esperan su turno sin error. Medido en lote "
            "con 2 en paralelo sobre 420 expedientes: mediana 20 s por expediente, p90 47 s."))
st += tabla(["Peticiones enviadas a la vez", "Tiempo aproximado de la última respuesta"], [
    ("1 a 2", "15 a 25 segundos"), ("3 a 4", "35 a 50 segundos"), ("5 a 6", "55 a 75 segundos")], [7.0, 10.2])
st += LI(["<b>Recomendado:</b> en cargas masivas, que el cliente envíe como máximo 2 en paralelo; enviar más no acelera, solo hace esperar.",
          "Mantén el timeout de 120 segundos: cubre la espera de turno en cargas normales.",
          "El límite protege la GPU compartida y lo ajusta el responsable del servicio (MAX_CONCURRENT_JOBS)."])
st.append(H2("7.4 Buenas prácticas"))
st += LI(["Guarda el JSON completo junto al expediente: permite auditar qué devolvió la API y por qué.",
          f"Muestra en pantallas de revisión los textos de {m('discrepancias')}, {m('avisos')} y {m('sin_verificar')}, "
          f"y resalta los campos con confianza {m('media')} o {m('baja')}.",
          "Trata cualquier código desconocido como error y regístralo: permite agregar códigos nuevos sin romper la integración.",
          "No registres en logs el contenido de datos (nombres, CURP, NUE): son datos personales.",
          "No hay costo por documento (todo es open source y local); el límite es la capacidad de la GPU."])

# ------------------------------------------------------------------ 8
st.append(H1("8. Ejemplos de respuesta"))
st.append(P("Ejemplos generados por el código real de la API (docs/generar_ejemplos.py) con <b>datos ficticios</b>."))
st.append(H2("8.1 Código 200: procesado"))
st += code(js(EJ["200"]), "200 PROCESADO (respuesta completa)")


def parcial(c):
    b = EJ[c]
    return {k: b[k] for k in ("codigo", "estado", "mensaje")} | {"datos": "{ ... igual que en 200 ... }",
                                                                "validacion": b["validacion"], "avisos": b["avisos"]}


st.append(H2("8.2 Código 210: con discrepancias"))
st.append(P("La CURP impresa indica otro año de nacimiento que la MRZ y el anverso. Un dato está mal: requiere revisión."))
st += code(js(parcial("210")), "210 PROCESADO_CON_DISCREPANCIAS (extracto)")
st.append(H2("8.3 Código 211: con avisos"))
st.append(P("El número del reverso se leyó distinto, pero la MRZ lo respalda con su dígito de control: se entrega el de la MRZ."))
st += code(js(parcial("211")), "211 PROCESADO_CON_AVISOS (extracto)")
st.append(H2("8.4 Tarjeta permanente antigua: 211"))
st.append(P("Permanente antigua sin CURP legible y sin fecha en la MRZ: la comprobación de la CURP queda en sin_verificar, la "
            "fecha de expedición se toma de «Expedido en» del reverso y ambos puntos se reportan en avisos. No hay "
            "fecha_vencimiento."))
bp = EJ["permanente"]
st += code(js({k: bp[k] for k in ("codigo", "estado", "mensaje", "datos", "validacion", "avisos")}), "211 permanente antigua (extracto)")
st.append(H2("8.5 Código 220 y 221: sin datos"))
st += code(js(EJ["220"]), "220 NO_ES_FORMA_MIGRATORIA")
b221 = EJ["221"]
st += code(js({k: b221[k] for k in ("codigo", "estado", "mensaje", "clasificacion")} |
              {"validacion_plan": {k: b221["validacion_plan"][k] for k in ("cumple", "mensaje", "motivos_rechazo")}}),
           "221 HOJA_EN_BLANCO (extracto)")
st.append(H2("8.6 validacion_plan: cumple"))
st += code(js(EJ["200"]["validacion_plan"]), "validacion_plan con la solicitud correcta")
st.append(H2("8.7 validacion_plan: no cumple"))
st.append(P("Solicitud con nombre incompleto, otra fecha de nacimiento y otra nacionalidad."))
st += code(js({k: EJ["plan_rechazo"][k] for k in ("cumple", "mensaje", "motivos_rechazo")}),
           "validacion_plan con datos que no coinciden (extracto)")
st.append(P("Sin datos de la solicitud, las validaciones de coincidencia quedan NO_VERIFICADO:"))
st += code(js({k: EJ["plan_sin_solicitud"][k] for k in ("cumple", "mensaje", "motivos_rechazo")}),
           "validacion_plan sin datos de la solicitud (extracto)")
st.append(H2("8.8 Errores"))
st += code("\n\n".join(f"// HTTP {c if int(c) >= 300 else 200}\n" + json.dumps(EJ[c], ensure_ascii=False)
                       for c in ("401", "400", "413", "422", "222", "223", "224", "500", "502")), "Errores (una línea por código)")

# ------------------------------------------------------------------ 9
st.append(H1("9. Health check"))
st.append(P(f"{m('GET /health')} no requiere API key. Úsalo para monitoreo o para verificar la conexión antes de integrar."))
st += code(f'''curl {URL}/health

{{"status": "ok", "vlm": true, "modelo_vlm": "qwen3-vl:8b-instruct", "backend_vlm": "ollama", "base_de_datos": false}}''',
           "Petición y respuesta")
st.append(P("status es «degradado» cuando el modelo de visión no responde. La prueba completa es enviar un documento conocido."))

# ------------------------------------------------------------------ 10
st.append(H1("10. Seguridad"))
st += LI(["<b>API key:</b> trátala como contraseña. Guárdala en variables de entorno o un gestor de secretos; no la "
          "subas a repositorios ni la compartas por correo o chat. Si se filtra, el responsable del servicio la "
          "cambia y la anterior deja de funcionar al instante.",
          "<b>Red:</b> el servicio usa HTTP sin cifrado y está pensado para la red interna. No lo expongas a internet; "
          "si se necesita desde fuera, debe ir detrás de un proxy con HTTPS.",
          "<b>Datos personales:</b> todo se procesa en el servidor de la empresa, sin servicios externos. La API no guarda "
          "los archivos; si se habilita el historial, guarda solo el JSON del resultado. Los logs solo registran código, "
          "estado y tiempos.",
          "<b>Logs:</b> no registres datos de clientes en logs de aplicaciones cliente."])

# ------------------------------------------------------------------ 11
st.append(H1("11. Precisión y limitaciones"))
st.append(P("Medido el 27 de octubre de 2026 sobre los primeros <b>50 expedientes</b> del lote de Santander (420 PDFs). Cada "
            "campo se capturó de la imagen con una lectura independiente de los dos pipelines (verificada con los dígitos de "
            "control de la MRZ y de la CURP) y se calificó con las mismas reglas para esta API y para la de Document AI "
            "(scripts/medir_json_vs_humano.py). De los 50, 3 son credenciales INE sin tarjeta INM; los 47 restantes se "
            "evaluaron en 14 campos."))
st += tabla(["Indicador", "Resultado", "Base"], [
    ("Precisión por campo (14 campos)", "<b>98.9 %</b>", "657 campos, 7 errores"),
    ("Expedientes con los 14 campos correctos", "<b>85.1 %</b>", "40 de 47"),
    ("Documentos que no son FM rechazados correctamente (220)", "3 de 3", "credenciales INE"),
    ("Antes de las mejoras del 27 de octubre", "92.8 % · 12.8 %", "misma muestra y mismas reglas"),
], [7.6, 3.2, 6.4])
st += tabla(["Campo", "Exactitud", "Errores encontrados"], [
    ("tipo_documento, nue, curp, numero_documento, nacionalidad, pais, fecha_nacimiento, sexo, fecha_expedicion, "
     "fecha_vencimiento, permiso_para_trabajar", "100 %", "Ninguno en 47"),
    ("apellidos", "97.9 %", "1: la MRZ se leyó con una letra cambiada y el OCR del anverso no la desempató."),
    ("nombres", "95.7 %", "2: nombre recortado por la MRZ sin otra fuente que lo complete; una letra confundida (I/L)."),
    ("impreso_en (lugar)", "91.5 %", "4: el modelo de visión no leyó el reverso y el OCR no encontró la línea."),
], [7.2, 2.0, 8.0], mono_cols=(0,))
st.append(H2("11.1 Comparación con la API de Document AI"))
st += tabla(["Indicador", "Open Source (esta API)", "Document AI"], [
    ("Precisión por campo (47 tarjetas, 14 campos)", "<b>98.9 %</b>", "<b>98.0 %</b>"),
    ("Expedientes con los 14 campos correctos", "85.1 %", "85.1 %"),
    ("Antes de las mejoras", "92.8 %", "94.1 %"),
    ("Código 200 en la muestra", "36 de 47", "17 de 47"),
    ("Tiempo por expediente", "15 a 25 s", "8 a 10 s"),
    ("Costo por documento", "Ninguno (local)", "Aprox. 0.03 USD por página"),
    ("Dónde se procesa", "Servidor de la empresa", "Google Cloud, región Estados Unidos"),
], [7.2, 5.0, 5.0])
st += caja("Las dos APIs responden el mismo sobre y los mismos códigos, así que un cliente puede apuntar a cualquiera de las "
           "dos sin cambios. Esta API entrega 200 con más frecuencia porque cruza más fuentes por campo (modelo de visión, "
           "OCR, MRZ y CURP); Document AI es más rápida.", color=VERDE, fondo=colors.HexColor("#EAF4EA"),
           titulo="Lo que esto significa para la integración")
st.append(H2("11.2 Limitaciones"))
st += LI(["<b>Muestra:</b> 47 tarjetas dan intervalos amplios: cada error vale unos 2 puntos en su campo y 0.15 en el global.",
          "<b>Lugar de impresión:</b> es el campo más débil; depende de que el reverso se lea completo.",
          "<b>Nombres largos:</b> la MRZ recorta a 30 caracteres; si el anverso está borroso, la última palabra puede quedar incompleta.",
          "Escaneos muy borrosos, sellos sobre la MRZ y tarjetas giradas bajan la precisión; la API lo refleja con 210 o 211 y "
          "confianza media o baja.",
          "La tarjeta debe estar en las primeras 6 páginas del PDF.",
          "Procesa 2 expedientes a la vez; los demás esperan turno (sección 7.3)."])

# ------------------------------------------------------------------ 12
st.append(H1("12. Preguntas frecuentes"))
faqs = [
    ("Recibo HTTP 200 pero no hay datos.", f"Revisa {m('codigo')}: probablemente es 220, 221, 222, 223 o 224. Esos códigos viajan con HTTP 200."),
    ("¿Por qué falta una llave en datos?", "Porque ese dato no se pudo leer o no existe en la tarjeta (p. ej. fecha_vencimiento en permanentes). Usa acceso seguro (.get, ??, TryGetProperty)."),
    ("¿Por qué datos.sexo dice M y mrz.sexo dice F?", "Son convenciones distintas: en datos M = mujer (H/M); en la MRZ F = female (M/F). Es la misma persona."),
    ("¿Puedo mandar una imagen JPG o PNG?", "No en el servidor de Santander (SOLO_PDF=true): responde 400. Conviértela a PDF antes de enviarla."),
    ("¿Puedo mandar anverso y reverso en archivos separados?", "No. La API recibe un PDF por petición; une ambas caras en un solo PDF. Sin reverso no hay MRZ."),
    ("El expediente trae pasaporte y tarjeta INM.", "No pasa nada: la API ubica la tarjeta y reporta el pasaporte en clasificacion.otros_documentos. La tarjeta debe estar en las primeras 6 páginas."),
    ("Me responde 401.", "Falta el header X-API-Key, tiene otro nombre o la clave es incorrecta. Las mayúsculas del nombre del header no importan; el valor sí."),
    ("Me responde 422.", "El archivo no viaja en el campo file o la petición no es multipart/form-data. El mensaje indica qué faltó."),
    ("¿Cuál uso, /forma-migratoria o /extract?", "/forma-migratoria. /extract es un alias para pruebas."),
    ("No envío datos de la solicitud y cumple sale false.", "Es lo esperado: sin esos datos no se pueden responder las validaciones de coincidencia (NO_VERIFICADO). La extracción en datos sigue siendo válida."),
    ("¿codigo 200 significa que cumple el plan?", "No necesariamente. codigo habla de la extracción; validacion_plan.cumple dice si coincide con la solicitud y está vigente."),
    ("¿En qué se diferencia de la API de Document AI?", "Mismo contrato y mismos códigos. Esta API corre local, sin costo por documento, tarda más (15-25 s) y solo acepta PDF; datos.permiso_para_trabajar viene true o false (en Document AI solo aparece cuando es true)."),
    ("¿Cuánto cuesta cada documento?", "Nada: todo el procesamiento es open source y corre en el servidor de la empresa."),
]
for q, a in faqs:
    st.append(KeepTogether([P(f"<b>{q}</b>", "p"), P(a, "nota"), Spacer(1, 4)]))

# ------------------------------------------------------------------ 13
st.append(H1("13. Prompt para implementar con IA"))
st.append(P("Copia este prompt en un asistente de IA (Claude, ChatGPT, Copilot...) e indica el lenguaje o framework. "
            "Contiene el contrato completo para generar un cliente correcto. También está en el archivo "
            f"{m('docs/PROMPT_IA.md')} del proyecto, más fácil de copiar."))
st += code(PROMPT, "Prompt")

# ------------------------------------------------------------------ 14
st.append(KeepTogether([H1("14. Glosario")] + tabla(["Término", "Significado"], [
    ("INM", "Instituto Nacional de Migración (México), emisor de la tarjeta de residente."),
    ("Forma migratoria", "En esta API, la tarjeta de residente del INM (temporal, permanente o inmigrado)."),
    ("MRZ", "Zona de lectura mecánica: las 3 líneas con caracteres «&lt;» al pie del reverso. Formato ICAO TD1."),
    ("Dígito de control", "Número calculado a partir de un dato de la MRZ o de la CURP que permite detectar errores de lectura."),
    ("NUE", "Número Único de Extranjero (13 dígitos)."),
    ("CURP", "Clave Única de Registro de Población (18 caracteres). NE en las posiciones 12-13 = nacido en el extranjero."),
    ("Anverso / reverso", "Frente y vuelta de la tarjeta."),
    ("PaddleOCR", "Motor OCR open source que lee el texto de la página y ubica anverso y reverso."),
    ("Qwen3-VL", "Modelo de visión y lenguaje open source (8 B parámetros) que lee la tarjeta y devuelve un JSON."),
    ("Plan de atención", "«Plan de atención - Validación documental» de Santander: las 8 preguntas SÍ/NO de la sección Forma Migratoria."),
], [3.6, 13.6])))

doc = Doc(str(SALIDA), pagesize=letter, title="API OCR de Formas Migratorias INM (Open Source) - Guía de integración",
          author="Alexis Eduardo Juárez Jaimes", subject="Documentación para desarrolladores", leftMargin=2.1 * cm,
          rightMargin=2.1 * cm, topMargin=2.0 * cm, bottomMargin=2.0 * cm)
doc.multiBuild(st)
print("ok", SALIDA)
