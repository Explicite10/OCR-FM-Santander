# Forma Migratoria OCR API

API en FastAPI que extrae los datos de la **tarjeta de residente del Instituto Nacional de Migración**
(Residente Temporal / Residente Permanente; también los modelos antiguos "Inmigrado" FM2) a partir de PDFs
escaneados (fotocopias en blanco y negro con sellos "cotejado contra original", a menudo junto con el pasaporte,
una INE o una licencia en el mismo PDF) y devuelve un JSON con **confianza por campo** y **validaciones**.

Todo corre local y open source: **PaddleOCR** + **Qwen3-VL 8B** (Ollama). Es la misma arquitectura que
`OCR-INE-Santander` y `passport-ocr-api`, cambiando el ancla: aquí manda la **MRZ TD1 `I<MEX`** del reverso
(ICAO 9303, con dígitos verificadores) y el título "RESIDENTE TEMPORAL / PERMANENTE" del anverso.

## Cómo funciona

```
PDF ─► páginas (250 dpi, hasta 6)
    ─► PaddleOCR por página ─► ubica el reverso (MRZ I<MEX) y el anverso (título / encabezado INM)
                             └─ si no hay anclas, prueba la página girada 90°/180°/270°; después el VLM ubica la tarjeta
    ─► recortes ─► Qwen3-VL lee el anverso (JSON con esquema fijo)
                └► reverso: MRZ por OCR con dígitos verificadores; si no cuadra, el VLM (y una 2ª pasada sobre la franja)
    ─► fusión + validaciones ─► JSON
```

**Fuentes que se cruzan**

| Dato | Fuentes |
|---|---|
| Número de documento (tarjeta) | MRZ (dígito verificador) vs "No." del reverso |
| Fecha de nacimiento | MRZ (dígito verificador) vs anverso vs CURP |
| Fecha de expedición | MRZ (dígito verificador; **el INM la pone en la posición ICAO del vencimiento**) vs anverso |
| Fecha de vencimiento | anverso (sólo impresa; vacía en Residente Permanente) |
| Sexo | anverso vs MRZ (M/F) vs CURP (H/M) |
| Apellidos / nombres | anverso (apellidos en MAYÚSCULAS, nombres en Title case) vs renglón 3 de la MRZ vs iniciales de la CURP |
| CURP (entidad "NE") | estructura + dígito verificador + fecha y sexo de la MRZ; se repara con la MRZ si un dígito se leyó mal |
| Nacionalidad / país | gentilicio impreso y código de 3 letras vs nacionalidad de la MRZ |
| NUE, tipo, permiso para trabajar, SEGOB-INM, impreso en | VLM vs OCR |

**Confianza**: `alta` = dos fuentes coinciden o lo respalda un dígito verificador · `media` = una fuente con
estructura válida · `baja` = desacuerdo o ilegible. `estado = "revisar"` si un campo crítico queda en `baja`
o si el número / fecha de nacimiento de la MRZ no cuadran con su dígito verificador.

Los otros documentos del PDF (pasaporte, INE, licencia, acreditación SRE) se detectan y se reportan en
`clasificacion.otros_documentos`, pero no se extraen. Una INE sola (MRZ `IDMEX`, nacionalidad MEX) no se
confunde con la tarjeta: responde 220 `NO_ES_FORMA_MIGRATORIA`.

## Uso

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # VLM_BASE_URL=http://localhost:11434 con Ollama local; define API_KEY
.venv/bin/uvicorn app.main:app --port 8000
curl -X POST localhost:8000/forma-migratoria -H "X-API-Key: <API_KEY>" -F "file=@tarjeta.pdf;type=application/pdf"
```

**Lote** (reanudable):

```bash
python -m scripts.procesar_lote lote/pdfs --salida lote/resultados --concurrencia 3 --recortes
python -m scripts.procesar_lote --salida lote/resultados --solo-resumen
```

Genera `json/*.json` y `resultados.csv` (datos personales; no sacar del servidor), `diagnostico.csv` y
`resumen.md` (sin datos personales), y con `--recortes` los PNG del anverso/reverso localizados.

**Pruebas**: `python -m pytest -q`

## Servidor (Docker)

```bash
cp .env.example .env
# Compartir el Ollama de ine-ocr (misma GPU de 8 GB; ya viene así en .env.example):
docker compose up -d --build
# Lote de pruebas (la carpeta lote/ debe ser escribible por uid 1000: chmod -R 777 lote):
docker compose run --rm lote lote/pdfs --salida lote/resultados --concurrencia 3 --recortes
```

API en `http://SERVIDOR:18475`.

**API key**: con `API_KEY` definida en `.env` (así está en el servidor, igual que INE y pasaporte, cada uno con su
propia key), `POST /forma-migratoria` y el historial exigen el header `X-API-Key`; sin él o con otro valor responde
`401 NO_AUTORIZADO`. `/health` no la pide. En `/docs`, el botón **Authorize** la captura una vez para todas las
llamadas. Para cambiarla: editar `API_KEY` en `.env` y `docker compose up -d api`.

Historial opcional (`DATABASE_URL`): `GET /v1/forma-migratoria/extracciones`, `.../{id}`, `PUT .../{id}/revision`.

## Respuesta de `POST /forma-migratoria`

Mismo sobre que las APIs de INE y pasaporte: `codigo` / `estado` / `mensaje` + `datos`, `mrz`, `validacion`,
`avisos`, `clasificacion`, `confianza`, `meta`.

| `codigo` | `estado` |
|---:|---|
| 200 | `PROCESADO` (todo cuadró) |
| 210 | `PROCESADO_CON_DISCREPANCIAS` (ver `validacion.discrepancias`) |
| 211 | `PROCESADO_CON_AVISOS` (ver `avisos`) |
| 212 | `PROCESADO_INCOMPLETO` (ver `validacion.sin_verificar`) |
| 220 | `NO_ES_FORMA_MIGRATORIA` · 221 `HOJA_EN_BLANCO` · 222 `ARCHIVO_CORRUPTO` · 223 `PDF_PROTEGIDO` · 224 `LIMITE_PAGINAS` |
| 400 / 401 / 413 / 422 / 500 | archivo no soportado / sin API key / muy grande / petición inválida / error |

```json
{
  "codigo": 200, "estado": "PROCESADO", "mensaje": "...",
  "datos": {
    "tipo_documento": "RESIDENTE TEMPORAL", "nue": "0000001234567",
    "apellidos": "PEREZ LOPEZ", "nombres": "ANA MARIA", "nombre_completo": "PEREZ LOPEZ Ana Maria",
    "nacionalidad": "ESPAÑOLA", "pais": "ESP", "sexo": "M", "fecha_nacimiento": "1990-03-15",
    "curp": "PELA900315MNERPN00", "permiso_para_trabajar": true,
    "fecha_expedicion": "2025-01-10", "fecha_vencimiento": "2027-01-09", "vigente": true,
    "numero_documento": "12345678", "numero_segob_inm": "SEGOB-INM-00123456",
    "impreso_en": "OR CIUDAD DE MEXICO, 05/01/2025", "pais_emisor": "MEX"
  },
  "mrz": {"lineas": ["I<MEX12345678<8<<<<<<<<<<<<<<<", "9003152F2501109ESP<<<<<<<<<<<6", "PEREZ<LOPEZ<<ANA<MARIA<<<<<<<<"],
          "numero_documento": "12345678", "fecha_nacimiento": "1990-03-15", "sexo": "M", "fecha_expedicion": "2025-01-10",
          "nacionalidad": "ESP", "apellidos": "PEREZ LOPEZ", "nombres": "ANA MARIA",
          "digitos_control": {"numero_documento": true, "fecha_nacimiento": true, "fecha_expedicion": true, "compuesto": true},
          "integra": true, "origen": "texto"},
  "validacion": {"ok": true, "completo": true, "coincidencias": ["MRZ (dígitos de control)", "apellidos y nombres (MRZ)", "..."],
                 "discrepancias": [], "sin_verificar": []},
  "avisos": [],
  "clasificacion": {"categoria": "forma_migratoria", "confianza": null, "senales": ["RESIDENTE TEMPORAL", "mrz_td1", "..."],
                    "otros_documentos": ["pasaporte (ESP)"]},
  "confianza": {"nombre": "alta", "curp": "alta", "numero_documento": "alta"},
  "meta": {"tiempo_total_ms": 9800, "tiempos_ms": {"ocr_y_recorte": 3900, "vlm_anverso": 4700}, "mrz_fuente": "ocr"}
}
```

Resultados sobre el lote de pruebas y las opciones evaluadas: [docs/EVALUACION.md](docs/EVALUACION.md).

## Privacidad

Las tarjetas son datos personales. Todo se procesa localmente; los logs sólo registran estado y tiempos.
`lote/`, `samples/`, `resultados/` y `*.pdf` están en `.gitignore`.
