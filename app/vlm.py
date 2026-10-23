"""Cliente del modelo de visión (VLM) con salida JSON estructurada + prompts de la tarjeta INM.

Backends con la misma interfaz:
* ollama: API nativa (/api/chat).
* openai: API compatible con OpenAI (/v1/chat/completions) — vLLM, LM Studio, etc.
"""

import asyncio
import base64
import json
import logging
import time
from typing import Any

import cv2
import httpx
import numpy as np

from .config import Settings, get_settings
from .documents import encode_png

log = logging.getLogger(__name__)


class VlmError(RuntimeError):
    pass


FRONT_FIELDS = ["tipo_documento", "nue", "nombre_completo", "apellidos", "nombres", "nacionalidad", "pais",
                "sexo", "fecha_nacimiento", "curp", "permiso_para_trabajar", "fecha_expedicion",
                "fecha_vencimiento", "folio", "campos_ilegibles"]
FRONT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tipo_documento": {"type": "string"},
        "nue": {"type": "string"},
        "nombre_completo": {"type": "string"},
        "apellidos": {"type": "string"},
        "nombres": {"type": "string"},
        "nacionalidad": {"type": "string"},
        "pais": {"type": "string"},
        "sexo": {"type": "string"},
        "fecha_nacimiento": {"type": "string"},
        "curp": {"type": "string"},
        "permiso_para_trabajar": {"type": "boolean"},
        "fecha_expedicion": {"type": "string"},
        "fecha_vencimiento": {"type": "string"},
        "folio": {"type": "string"},
        "campos_ilegibles": {"type": "array", "items": {"type": "string"}},
    },
    "required": FRONT_FIELDS,
}

FRONT_PROMPT = """Eres un sistema de captura de datos. La imagen es el ANVERSO de una tarjeta de residente del Instituto Nacional de Migración (INM, México), fotocopiada en blanco y negro; puede tener sellos ("COTEJADO CONTRA ORIGINAL"), firmas o manchas encima. Los modelos antiguos dicen "INMIGRADO", "INMIGRANTE" o "NO INMIGRANTE" (FM2 / FM3).

Transcribe EXACTAMENTE lo impreso en cada campo, carácter por carácter:
- tipo_documento: el título de la tarjeta tal cual: "RESIDENTE TEMPORAL", "RESIDENTE PERMANENTE", "INMIGRADO", "INMIGRANTE", "NO INMIGRANTE"...
- nue: los 13 dígitos junto a "NUE" (Número Único de Extranjero). En tarjetas antiguas no existe: "".
- nombre_completo: el renglón bajo "Nombre / Name" tal cual está impreso, respetando mayúsculas y minúsculas (los apellidos van en MAYÚSCULAS y los nombres con inicial mayúscula, p. ej. "PEREZ LOPEZ Ana Maria"). En tarjetas antiguas ("NOMBRE Y APELLIDOS") copia los renglones en orden separados por espacio.
- apellidos: sólo los apellidos, en MAYÚSCULAS. nombres: sólo los nombres de pila, en MAYÚSCULAS.
- nacionalidad: el gentilicio impreso (ESPAÑOLA, BRASILEÑA, CHINA...). pais: el código de 3 letras junto a "País / Country" (ESP, BRA, CHN...); si no hay, "".
- sexo: lo impreso junto a "Sexo / Sex" (Hombre, Mujer, Masculino, Femenino, M, F).
- fecha_nacimiento, fecha_expedicion, fecha_vencimiento: DD/MM/AAAA. Si la tarjeta no imprime vencimiento (Residente Permanente), "".
- curp: los 18 caracteres junto a "CURP". Distingue con cuidado 0/O, 1/I, 5/S, 8/B, 2/Z: las posiciones 5-10 son dígitos de la fecha de nacimiento, la 11 es H o M y las posiciones 12-13 suelen ser "NE".
- permiso_para_trabajar: true sólo si la tarjeta dice "PERMISO PARA TRABAJAR".
- folio: en tarjetas antiguas el número junto a "FOLIO"; si no hay, "".

Reglas:
- NO inventes ni completes datos. Si un carácter o campo no se lee con certeza, deja "" y agrega el nombre del campo a campos_ilegibles.
- Ignora sellos, firmas, anotaciones a mano y textos que no sean de la tarjeta.
- Conserva Ñ y acentos tal como aparecen en nombres."""

BACK_FIELDS = ["numero_segob_inm", "impreso_en", "numero_documento", "condicion_estancia",
               "mrz_linea1", "mrz_linea2", "mrz_linea3"]
BACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in BACK_FIELDS},
    "required": BACK_FIELDS,
}

BACK_PROMPT = """La imagen es el REVERSO de una tarjeta de residente del Instituto Nacional de Migración (México), fotocopiada en blanco y negro, posiblemente con sellos encima.
Transcribe EXACTAMENTE:
- numero_segob_inm: el texto "SEGOB-INM-" seguido de dígitos, arriba a la izquierda.
- impreso_en: lo que sigue a "Impreso en:" (oficina y fecha), tal cual.
- numero_documento: los dígitos junto a "No." (a la derecha de los códigos 2D).
- condicion_estancia: el texto de observaciones o condición de estancia si lo hay; si no, "".
- mrz_linea1, mrz_linea2, mrz_linea3: los 3 renglones de texto tipo máquina (MRZ) de 30 caracteres cada uno, abajo; el primero empieza con "I<MEX". Carácter por carácter, incluyendo cada símbolo "<", sin espacios. Si un carácter no se distingue escribe tu mejor lectura; no omitas caracteres."""

MRZ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"mrz_linea1": {"type": "string"}, "mrz_linea2": {"type": "string"}, "mrz_linea3": {"type": "string"}},
    "required": ["mrz_linea1", "mrz_linea2", "mrz_linea3"],
}
MRZ_PROMPT = """La imagen muestra la franja MRZ (3 renglones de 30 caracteres tipo máquina, el primero empieza con "I<MEX") del reverso de una tarjeta de residente del INM (México), fotocopiada.
Transcribe los 3 renglones EXACTAMENTE, carácter por carácter, incluyendo cada símbolo "<", sin espacios. No omitas caracteres."""

LOCATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tarjetas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lado": {"type": "string", "enum": ["anverso", "reverso", "desconocido"]},
                    "bbox_2d": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
                    "rotacion": {"type": "integer", "enum": [0, 90, 180, 270]},
                },
                "required": ["lado", "bbox_2d", "rotacion"],
            },
        },
    },
    "required": ["tarjetas"],
}

LOCATE_PROMPT = """La imagen es una página escaneada de {w}x{h} píxeles. Puede contener una tarjeta de residente del Instituto Nacional de Migración (México): el ANVERSO (foto, encabezado "INSTITUTO NACIONAL DE MIGRACIÓN", título "RESIDENTE TEMPORAL" o "RESIDENTE PERMANENTE", NUE, Nombre, CURP) y/o el REVERSO ("SEGOB-INM-", dos códigos 2D cuadrados y una franja de 3 renglones tipo máquina con "<<<" abajo), a veces las dos caras en la misma página, giradas, inclinadas o pequeñas. La página puede traer además pasaportes, licencias o credenciales INE: NO los incluyas.

Devuelve en "tarjetas" cada cara de la tarjeta del INM que veas:
- bbox_2d: [x1, y1, x2, y2] en píxeles de esta imagen, el rectángulo completo de la tarjeta (ligeramente holgado).
- lado: "anverso", "reverso" o "desconocido".
- rotacion: grados en sentido horario (0, 90, 180 o 270) que hay que girar el recorte para que el texto quede derecho.
Si no hay ninguna tarjeta del INM, devuelve una lista vacía."""


class VlmClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        self._client = httpx.AsyncClient(timeout=self.s.vlm_timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def locate(self, img: np.ndarray) -> tuple[list[dict], float]:
        h, w = img.shape[:2]
        scale = min(1.0, self.s.vlm_locate_max_side / max(h, w))
        small = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else img
        sh, sw = small.shape[:2]
        data, secs = await self.extract(small, LOCATE_PROMPT.format(w=sw, h=sh), LOCATE_SCHEMA, max_side=None)
        cards = []
        for c in data.get("tarjetas") or []:
            try:
                x1, y1, x2, y2 = (float(v) for v in c["bbox_2d"])
            except (KeyError, TypeError, ValueError):
                continue
            if x2 <= x1 or y2 <= y1:
                continue
            cards.append({
                "lado": c.get("lado") if c.get("lado") in ("anverso", "reverso") else "desconocido",
                "bbox_2d": [int(x1 / scale), int(y1 / scale), int(x2 / scale), int(y2 / scale)],
                "rotacion": c.get("rotacion") if c.get("rotacion") in (0, 90, 180, 270) else 0,
            })
        return cards, secs

    async def extract(self, img: np.ndarray, prompt: str, schema: dict[str, Any],
                      max_side: int | None = -1) -> tuple[dict, float]:
        if img is None or img.size == 0:
            raise VlmError("Imagen vacía")
        if max_side == -1:
            max_side = self.s.vlm_max_side
        b64 = base64.b64encode(encode_png(img, max_side)).decode()
        last: Exception | None = None
        for attempt in range(self.s.vlm_max_retries + 1):
            t0 = time.perf_counter()
            try:
                if self.s.vlm_backend == "ollama":
                    text = await self._ollama(b64, prompt, schema)
                else:
                    text = await self._openai(b64, prompt, schema)
                return _parse_json(text), time.perf_counter() - t0
            except (httpx.HTTPError, ValueError, KeyError) as e:
                last = e
                log.warning("VLM intento %d falló: %s", attempt + 1, e)
                await asyncio.sleep(1.5 * (attempt + 1))
        raise VlmError(f"El VLM no respondió correctamente: {last}")

    async def _ollama(self, b64: str, prompt: str, schema: dict) -> str:
        payload = {
            "model": self.s.vlm_model,
            "stream": False,
            "format": schema,
            "keep_alive": "30m",
            "options": {"temperature": 0, "seed": 0, "num_ctx": self.s.vlm_num_ctx, "num_predict": 800},
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        }
        if self.s.vlm_think is not None:
            payload["think"] = self.s.vlm_think
        r = await self._client.post(f"{self.s.vlm_base_url.rstrip('/')}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"]

    async def _openai(self, b64: str, prompt: str, schema: dict) -> str:
        payload = {
            "model": self.s.vlm_model,
            "temperature": 0,
            "seed": 0,
            "max_tokens": 800,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "fm", "schema": schema, "strict": True}},
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
        }
        base = self.s.vlm_base_url.rstrip("/")
        url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
        r = await self._client.post(url, json=payload,
                                    headers={"Authorization": f"Bearer {self.s.vlm_api_key}"})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    async def health(self) -> bool:
        base = self.s.vlm_base_url.rstrip("/")
        try:
            if self.s.vlm_backend == "ollama":
                r = await self._client.get(f"{base}/api/tags", timeout=5)
                names = {m["name"] for m in r.json().get("models", [])}
                return self.s.vlm_model in names
            r = await self._client.get(f"{base if base.endswith('/v1') else base + '/v1'}/models", timeout=5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"Respuesta sin JSON: {text[:200]}")
    return json.loads(text[start:end + 1])
