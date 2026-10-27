"""Orquestación: archivo -> páginas -> OCR + recortes -> VLM -> MRZ -> fusión -> JSON."""

import asyncio
import base64
import logging
import re
import time

import cv2
import numpy as np

from . import front_ocr, gate, mrz_td1
from . import validators as v
from .config import get_settings
from .documents import DocumentError, encode_png, load_pages
from .layout import Box, CardBox, Layout, Side, analyze, analyze_boxes
from .merge import CRITICAL_FIELDS, Merger, needs_review
from .ocr import engine
from .schemas import Meta, ResultadoFM
from .vlm import BACK_PROMPT, BACK_SCHEMA, FRONT_PROMPT, FRONT_SCHEMA, MRZ_PROMPT, MRZ_SCHEMA, VlmClient, VlmError

log = logging.getLogger(__name__)

MIN_CARACTERES_OCR = 10


def _ms(t: float) -> int:
    return int(t * 1000)


def _meta(s, times: dict[str, int], t_start: float, layout: Layout, mrz_source: str | None,
          vlm: VlmClient | None, senales: list[str], caracteres: int = 0, categoria: str | None = None,
          documento: str | None = None) -> Meta:
    return Meta(
        caracteres_leidos=caracteres,
        categoria=categoria,
        documento_detectado=documento,
        tiempo_total_ms=_ms(time.perf_counter() - t_start),
        tiempos_ms=times,
        modelo_vlm=s.vlm_model if vlm is not None and s.vlm_enabled else None,
        paginas=layout.pages,
        rotado=layout.rotated,
        pagina_anverso=layout.front.page + 1 if layout.front else None,
        pagina_reverso=layout.back.page + 1 if layout.back else None,
        recorte_anverso=layout.front.method if layout.front else None,
        recorte_reverso=layout.back.method if layout.back else None,
        mrz_fuente=mrz_source,
        senales_fm=senales,
        otros_documentos=layout.otros_documentos,
    )


def _mrz_strip(side: Side) -> np.ndarray | None:
    """Recorte ampliado de la franja MRZ (último tercio del reverso) para una 2ª lectura del VLM."""
    img = side.image
    h, w = img.shape[:2]
    if h < 40 or w < 80:
        return None
    strip = img[int(h * 0.55):, :]
    sh, sw = strip.shape[:2]
    if sw < 1400:
        scale = 1400 / sw
        strip = cv2.resize(strip, (int(sw * scale), int(sh * scale)), interpolation=cv2.INTER_CUBIC)
    return strip


async def process(files: list[bytes], vlm: VlmClient | None, filename: str | None = None,
                  include_crops: bool = False) -> ResultadoFM:
    s = get_settings()
    t_start = time.perf_counter()
    times: dict[str, int] = {}

    # 1. Páginas
    t = time.perf_counter()
    try:
        pages: list[np.ndarray] = []
        for data in files:
            pages += await asyncio.to_thread(load_pages, data, s.render_dpi, s.max_pages, s.max_paginas_documento)
    except DocumentError as e:
        return ResultadoFM(archivo=filename, estado="error", error=str(e), error_codigo=e.codigo,
                           meta=Meta(tiempo_total_ms=_ms(time.perf_counter() - t_start)))
    times["render"] = _ms(time.perf_counter() - t)

    # 2. OCR + localización
    t = time.perf_counter()
    ocr_read = engine.read if s.ocr_enabled else (lambda img: [])
    layout: Layout = await asyncio.to_thread(analyze, pages, ocr_read)
    times["ocr_y_recorte"] = _ms(time.perf_counter() - t)
    vlm_on = vlm is not None and s.vlm_enabled

    def gate_eval() -> gate.Veredicto:
        return gate.evaluate(layout.page_lines,
                             layout.front is not None and layout.front.method == "ancla",
                             layout.back is not None and layout.back.method == "ancla")

    veredicto = gate_eval()
    texto = sum(len(re.sub(r"[^A-Z0-9]", "", l.text.upper())) for lines in layout.page_lines for l in lines)
    if s.rechazar_no_fm and s.ocr_enabled and texto < MIN_CARACTERES_OCR:
        motivo = "El documento está en blanco o no tiene texto legible"
        return ResultadoFM(archivo=filename, estado="rechazado", error=motivo, advertencias=list(layout.warnings),
                           meta=_meta(s, times, t_start, layout, None, vlm, veredicto.senales, texto, "hoja_en_blanco"))
    if s.rechazar_no_fm and s.ocr_enabled and not vlm_on and not veredicto.es_fm:
        return ResultadoFM(archivo=filename, estado="rechazado", error=veredicto.motivo, advertencias=list(layout.warnings),
                           meta=_meta(s, times, t_start, layout, None, vlm, veredicto.senales, texto, "otro",
                                      ", ".join(layout.otros_documentos) or None))

    # 2b. Sin anclas: el VLM ubica la tarjeta y se repite el OCR en los recortes
    if vlm_on and s.vlm_localizador and s.ocr_enabled and not layout.anchored:
        t = time.perf_counter()
        try:
            cards: list[CardBox] = []
            for i, page in enumerate(layout.page_images):
                found, _ = await vlm.locate(page)
                cards += [CardBox(i, Box(*c["bbox_2d"]), c["lado"], c["rotacion"]) for c in found]
                if any(c.lado == "anverso" for c in cards) and any(c.lado == "reverso" for c in cards):
                    break
            if cards:
                layout = await asyncio.to_thread(analyze_boxes, layout, cards, ocr_read)
                veredicto = gate_eval()
            else:
                layout.warnings.append("El localizador no vio ninguna tarjeta del INM en la página")
        except VlmError as e:
            log.error("Localizador falló: %s", e)
            layout.warnings.append("El localizador de tarjetas falló; se analizó la página completa")
        times["localizacion_vlm"] = _ms(time.perf_counter() - t)
    warnings = list(layout.warnings)

    ocr_front = front_ocr.extract(layout.front.lines if layout.front and layout.front.method == "ancla" else [])
    ocr_back = front_ocr.extract(layout.back.lines if layout.back and layout.back.method == "ancla" else [])
    if not ocr_back.numero_segob_inm:
        # El "SEGOB-INM-" se imprime arriba del reverso y a veces queda fuera del recorte: se busca en toda la página
        pagina = layout.back.page if layout.back else None
        if pagina is not None and pagina < len(layout.page_lines):
            ocr_back.numero_segob_inm = front_ocr.extract(layout.page_lines[pagina]).numero_segob_inm
    ocr_mrz = mrz_td1.parse(layout.back.mrz_lines) if layout.back and layout.back.mrz_lines else None

    # 3. VLM: anverso siempre; reverso si la MRZ del OCR no cuadra al 100 % o falta el SEGOB-INM
    vlm_front: dict | None = None
    vlm_back: dict | None = None
    vlm_mrz: mrz_td1.MrzResult | None = None
    mrz_integra = bool(ocr_mrz and ocr_mrz.valido and not ocr_mrz.corregido and len(ocr_mrz.lineas) == 3)
    need_back = not mrz_integra or not ocr_back.numero_segob_inm
    if vlm_on:
        jobs = {}
        if layout.front is not None:
            jobs["vlm_anverso"] = vlm.extract(layout.front.image, FRONT_PROMPT, FRONT_SCHEMA)
        if need_back and layout.back is not None:
            jobs["vlm_reverso"] = vlm.extract(layout.back.image, BACK_PROMPT, BACK_SCHEMA)
        results = await asyncio.gather(*jobs.values(), return_exceptions=True)
        for name, res in zip(jobs, results):
            if isinstance(res, Exception):
                log.error("%s falló: %s", name, res)
                if name == "vlm_anverso" and s.error_vlm_502:
                    # Igual que la API de DocumentAI cuando falla el motor: 502, sin datos a medias
                    return ResultadoFM(archivo=filename, estado="error", error=str(res), error_codigo=502,
                                       advertencias=warnings,
                                       meta=_meta(s, times, t_start, layout, None, vlm, veredicto.senales, texto))
                warnings.append(f"El modelo de visión falló en {name.split('_')[1]}; se usó sólo OCR")
                continue
            data, secs = res
            times[name] = _ms(secs)
            if name == "vlm_anverso":
                vlm_front = data
            else:
                vlm_back = data
                vlm_mrz = mrz_td1.parse([data.get("mrz_linea1", ""), data.get("mrz_linea2", ""), data.get("mrz_linea3", "")])
        # 3b. Si ni OCR ni VLM dan una MRZ íntegra, segunda pasada sobre la franja ampliada
        best_so_far = mrz_td1.best(ocr_mrz, vlm_mrz)
        if layout.back is not None and layout.back.method == "ancla" and not (best_so_far and best_so_far.valido):
            strip = _mrz_strip(layout.back)
            if strip is not None:
                try:
                    data, secs = await vlm.extract(strip, MRZ_PROMPT, MRZ_SCHEMA, max_side=1800)
                    times["vlm_mrz"] = _ms(secs)
                    vlm_mrz = mrz_td1.best(vlm_mrz, mrz_td1.parse([data.get("mrz_linea1", ""), data.get("mrz_linea2", ""),
                                                                   data.get("mrz_linea3", "")]))
                except VlmError as e:
                    log.warning("2ª lectura de MRZ falló: %s", e)
    else:
        warnings.append("VLM deshabilitado: resultados sólo con OCR")

    chosen = mrz_td1.best(ocr_mrz, vlm_mrz)
    if chosen is not None and chosen.nacionalidad == "MEX":
        warnings.append("La MRZ leída tiene nacionalidad MEX: es una credencial INE, no una tarjeta de residente")
        chosen = ocr_mrz = vlm_mrz = None
    mrz_source = None
    if chosen is not None:
        mrz_source = "ocr" if chosen is ocr_mrz else "vlm"
        other = vlm_mrz if chosen is ocr_mrz else ocr_mrz
        if other is not None and other.valido and chosen.valido and other.numero_documento != chosen.numero_documento:
            warnings.append("OCR y VLM leyeron MRZ válidas pero distintas")

    # 4. Fusión y validación
    merger = Merger(vlm_front, vlm_back, ocr_front, ocr_back, chosen)
    datos = merger.run()
    warnings += merger.warnings
    review = needs_review(merger.conf)
    critical_bad = [f for f in review if f in CRITICAL_FIELDS]
    # La MRZ "cuenta" si número y fecha de nacimiento cuadran con su dígito verificador; el compuesto
    # (un solo dígito, a menudo tapado por el sello) sólo baja a aviso.
    mrz_core = bool(chosen) and all(any(c.nombre == n and c.valido for c in chosen.checks)
                                    for n in ("mrz_numero", "mrz_fecha_nacimiento"))
    estado = "revisar" if critical_bad or not mrz_core else "ok"
    if vlm_front is None and vlm_on:
        estado = "revisar"

    meta = _meta(s, times, t_start, layout, mrz_source, vlm, veredicto.senales, texto, "forma_migratoria")

    # 5. Verificación final: el VLM leyó y aun así no hay DATOS de una tarjeta INM
    mrz_real = chosen is not None and chosen.numero_documento is not None and chosen.n_validos > 0
    datos_fm = (mrz_real or (datos.nue and v.NUE_RE.match(datos.nue)) or
                (datos.tipo_documento and veredicto.es_fm) or (v.curp_valid(datos.curp) and datos.curp[11:13] == "NE"))
    if s.rechazar_no_fm and vlm_front is not None and not datos_fm:
        motivo = ("No se reconoció una tarjeta de residente del INM: sin MRZ válida, sin NUE y sin título de la tarjeta"
                  + (f" (otros documentos: {', '.join(layout.otros_documentos)})" if layout.otros_documentos else ""))
        meta.categoria = "otro"
        meta.documento_detectado = ", ".join(layout.otros_documentos) or None
        return ResultadoFM(archivo=filename, estado="rechazado", error=motivo, advertencias=warnings, meta=meta)

    result = ResultadoFM(archivo=filename, estado=estado, datos=datos, confianza=merger.conf, campos_a_revisar=review,
                         validaciones=merger.checks, advertencias=warnings, meta=meta)
    if include_crops:
        result.recortes = {
            name: base64.b64encode(encode_png(side.image, 1400)).decode()
            for name, side in (("anverso", layout.front), ("reverso", layout.back)) if side is not None
        }
    return result
