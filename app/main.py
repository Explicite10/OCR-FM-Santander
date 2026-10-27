import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, Security, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import pipeline, plan
from .config import get_settings
from .db import Database, Extraccion
from .documents import PDF_MAGIC
from .ocr import engine
from .respuesta import ESTADOS, MENSAJES, con_plan, construir, http_status, sobre
from .schemas import ExtraccionDetalle, ExtraccionResumen, ListaExtracciones, Revision
from .vlm import VlmClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fm-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.vlm = VlmClient(s) if s.vlm_enabled else None
    app.state.sem = asyncio.Semaphore(s.max_concurrent_jobs)
    app.state.db = None
    if s.database_url:
        app.state.db = Database(s.database_url)
        await app.state.db.init()
        log.info("Base de datos lista")
    if s.ocr_enabled:
        log.info("Cargando PaddleOCR...")
        await asyncio.to_thread(engine.warmup)
    if app.state.vlm and not await app.state.vlm.health():
        log.warning("El VLM %s no responde en %s", s.vlm_model, s.vlm_base_url)
    yield
    if app.state.vlm:
        await app.state.vlm.aclose()
    if app.state.db:
        await app.state.db.close()


_s = get_settings()
app = FastAPI(
    title="Forma Migratoria OCR API",
    version="0.1.0",
    description="Extracción estructurada de la tarjeta de residente del INM (Residente Temporal / Permanente).",
    lifespan=lifespan,
    docs_url="/docs" if _s.enable_docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _s.enable_docs else None,
)

_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)


def _error_doc(*codigos: int) -> dict:
    return {c: {"description": ESTADOS[c], "content": {"application/json": {"example": sobre(c)}}} for c in codigos}


def check_api_key(x_api_key: str | None = Security(_api_key)) -> None:
    expected = get_settings().api_key
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail=MENSAJES[401])


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    mensaje = exc.detail if isinstance(exc.detail, str) and exc.detail not in ("Not Found", "Method Not Allowed") else None
    return JSONResponse(sobre(exc.status_code, mensaje), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    errores = [f"{'.'.join(str(x) for x in e.get('loc', []) if x != 'body')}: {e.get('msg')}" for e in exc.errors()]
    return JSONResponse(sobre(422, f"{MENSAJES[422]} {'; '.join(errores)}"), status_code=422)


@app.exception_handler(Exception)
async def _internal_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Error no controlado")
    return JSONResponse(sobre(500), status_code=500)


@app.get("/health")
async def health():
    s = get_settings()
    vlm_ok = await app.state.vlm.health() if app.state.vlm else None
    return {"status": "ok" if vlm_ok is not False else "degradado", "vlm": vlm_ok,
            "modelo_vlm": s.vlm_model, "backend_vlm": s.vlm_backend, "base_de_datos": app.state.db is not None}


_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"II*\x00", b"MM\x00*", b"BM")


def _tipo(data: bytes) -> str | None:
    if PDF_MAGIC in data[:1024]:
        return "pdf"
    if data.startswith(_IMAGE_MAGIC) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return "imagen"
    return None


async def _read(f: UploadFile) -> bytes | JSONResponse:
    s = get_settings()
    limit = s.max_upload_mb * 1024 * 1024
    data = await f.read(limit + 1)
    if len(data) > limit:
        return JSONResponse(sobre(413, f"{f.filename}: excede {s.max_upload_mb} MB"), status_code=413)
    if not data:
        return JSONResponse(sobre(222, f"{f.filename}: el archivo llegó vacío"))
    tipo = _tipo(data)
    dice_pdf = (f.content_type == "application/pdf") or (f.filename or "").lower().endswith(".pdf")
    if dice_pdf and tipo != "pdf":
        return JSONResponse(sobre(222, f"{f.filename}: dice ser PDF pero su contenido es otra cosa"))
    if tipo is None or (s.solo_pdf and tipo != "pdf"):
        permitidos = "PDF" if s.solo_pdf else "PDF, JPEG, PNG, TIFF o WEBP"
        return JSONResponse(sobre(400, f"{f.filename}: tipo no soportado; se acepta {permitidos}"), status_code=400)
    return data


_D_NOMBRE = ("Nombre completo capturado en la solicitud, en cualquier orden. "
             "Alternativa: apellido_paterno, apellido_materno y nombres.")
_D_CURP = "CURP capturada en la solicitud (si existe)."
_D_FECHA = "Fecha de nacimiento capturada: AAAA-MM-DD (también acepta DD/MM/AAAA)."
_D_NAC = "Nacionalidad capturada: gentilicio (Colombiana), país (Colombia) o código ISO (COL)."
_DOC = {200: {"description": "Desenlace en `codigo`: 200, 210-212 (procesado) o 220-224 (no se extrajo)"},
        **_error_doc(400, 401, 413, 422, 500, 502)}


async def _atender(file: UploadFile, solicitud: plan.Solicitud) -> JSONResponse:
    data = await _read(file)
    if isinstance(data, JSONResponse):
        return data
    async with app.state.sem:
        result = await pipeline.process([data], app.state.vlm, file.filename)
    log.info("archivo procesado estado=%s tiempo_ms=%s revisar=%s", result.estado,
             result.meta.tiempo_total_ms if result.meta else None, result.campos_a_revisar)
    if app.state.db is not None and get_settings().guardar_resultados:
        try:
            result.id = await app.state.db.save(result.model_dump(mode="json"))
        except Exception:  # noqa: BLE001
            log.exception("No se pudo guardar el resultado")
            result.advertencias.append("No se pudo guardar el resultado en la base de datos")
    body = con_plan(construir(result), solicitud)
    log.info("codigo=%s cumple_plan=%s", body["codigo"], body.get("validacion_plan", {}).get("cumple"))
    return JSONResponse(body, status_code=http_status(body["codigo"]))


def _solicitud(nombre, apellido_paterno, apellido_materno, nombres, curp, fecha_nacimiento, nacionalidad) -> plan.Solicitud:
    return plan.Solicitud(nombre=nombre, apellido_paterno=apellido_paterno, apellido_materno=apellido_materno,
                          nombres=nombres, curp=curp, fecha_nacimiento=fecha_nacimiento, nacionalidad=nacionalidad)


@app.post("/forma-migratoria", dependencies=[Depends(check_api_key)], response_class=JSONResponse,
          summary="Extrae los datos de una tarjeta de residente del INM y valida contra la solicitud",
          responses=_DOC)
async def forma_migratoria(file: UploadFile = File(..., description="PDF con la tarjeta (anverso y reverso)"),
                           nombre: str | None = Form(None, description=_D_NOMBRE),
                           apellido_paterno: str | None = Form(None), apellido_materno: str | None = Form(None),
                           nombres: str | None = Form(None), curp: str | None = Form(None, description=_D_CURP),
                           fecha_nacimiento: str | None = Form(None, description=_D_FECHA),
                           nacionalidad: str | None = Form(None, description=_D_NAC)) -> JSONResponse:
    return await _atender(file, _solicitud(nombre, apellido_paterno, apellido_materno, nombres, curp,
                                           fecha_nacimiento, nacionalidad))


@app.post("/extract", dependencies=[Depends(check_api_key)], response_class=JSONResponse,
          summary="Pruebas: mismo resultado que /forma-migratoria", responses=_DOC)
async def extract(file: UploadFile = File(...), nombre: str | None = Form(None),
                  apellido_paterno: str | None = Form(None), apellido_materno: str | None = Form(None),
                  nombres: str | None = Form(None), curp: str | None = Form(None),
                  fecha_nacimiento: str | None = Form(None), nacionalidad: str | None = Form(None)) -> JSONResponse:
    return await _atender(file, _solicitud(nombre, apellido_paterno, apellido_materno, nombres, curp,
                                           fecha_nacimiento, nacionalidad))


def _db() -> Database:
    if app.state.db is None:
        raise HTTPException(status_code=503, detail="Base de datos no configurada (DATABASE_URL)")
    return app.state.db


def _resumen(r: Extraccion) -> ExtraccionResumen:
    return ExtraccionResumen(id=r.id, creado=r.creado, archivo=r.archivo, estado=r.estado, curp=r.curp, nue=r.nue,
                             nombre_completo=r.nombre_completo, campos_a_revisar=r.campos_a_revisar or [],
                             tiempo_ms=r.tiempo_ms)


@app.get("/v1/forma-migratoria/extracciones", response_model=ListaExtracciones, dependencies=[Depends(check_api_key)])
async def listar(estado: str | None = Query(None), curp: str | None = None, q: str | None = Query(None),
                 limite: int = Query(50, ge=1, le=500), desde: int = Query(0, ge=0)) -> ListaExtracciones:
    total, rows = await _db().list(estado, curp, q, limite, desde)
    return ListaExtracciones(total=total, elementos=[_resumen(r) for r in rows])


@app.get("/v1/forma-migratoria/extracciones/{id_}", response_model=ExtraccionDetalle, dependencies=[Depends(check_api_key)])
async def detalle(id_: str) -> ExtraccionDetalle:
    r = await _db().get(id_)
    if r is None:
        raise HTTPException(status_code=404, detail="No existe")
    return ExtraccionDetalle(**_resumen(r).model_dump(), resultado=r.resultado, datos_corregidos=r.datos_corregidos,
                             revisado_por=r.revisado_por, revisado_en=r.revisado_en)


@app.put("/v1/forma-migratoria/extracciones/{id_}/revision", response_model=ExtraccionDetalle,
         dependencies=[Depends(check_api_key)])
async def revisar(id_: str, revision: Revision = Body(...)) -> ExtraccionDetalle:
    r = await _db().review(id_, revision.datos, revision.revisado_por)
    if r is None:
        raise HTTPException(status_code=404, detail="No existe")
    return await detalle(id_)
