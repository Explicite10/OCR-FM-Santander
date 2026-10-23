"""Modelos de la respuesta JSON de la API (formato interno)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Confianza = Literal["alta", "media", "baja"]
Resultado = Literal["ok", "falla", "no_aplica"]


class Nombre(BaseModel):
    apellidos: str | None = None
    nombres: str | None = None
    nombre_completo: str | None = Field(None, description="Tal como está impreso (apellidos primero)")


class DatosFM(BaseModel):
    tipo_documento: str | None = Field(None, description="RESIDENTE TEMPORAL | RESIDENTE PERMANENTE | INMIGRADO | ...")
    nue: str | None = Field(None, description="Número Único de Extranjero (13 dígitos)")
    nombre: Nombre = Field(default_factory=Nombre)
    nacionalidad: str | None = Field(None, description="Gentilicio impreso (ESPAÑOLA, BRASILEÑA...)")
    pais: str | None = Field(None, description="Código ISO alfa-3 impreso (ESP, BRA...)")
    sexo: str | None = Field(None, description="H | M | X")
    fecha_nacimiento: str | None = Field(None, description="AAAA-MM-DD")
    curp: str | None = None
    permiso_para_trabajar: bool | None = None
    fecha_expedicion: str | None = None
    fecha_vencimiento: str | None = Field(None, description="Vacío en Residente Permanente")
    vigente: bool | None = None
    # Reverso
    numero_documento: str | None = Field(None, description="Número de la tarjeta (MRZ / 'No.' del reverso)")
    numero_segob_inm: str | None = None
    impreso_en: str | None = None
    condicion_estancia: str | None = None
    mrz: list[str] = Field(default_factory=list)
    mrz_nacionalidad: str | None = None


class Validacion(BaseModel):
    regla: str
    resultado: Resultado
    detalle: str | None = None


class Meta(BaseModel):
    tiempo_total_ms: int
    tiempos_ms: dict[str, int] = Field(default_factory=dict)
    modelo_vlm: str | None = None
    paginas: int = 0
    rotado: bool = False
    pagina_anverso: int | None = None
    pagina_reverso: int | None = None
    recorte_anverso: str | None = None
    recorte_reverso: str | None = None
    mrz_fuente: str | None = None
    senales_fm: list[str] = Field(default_factory=list, description="Indicios de tarjeta INM (OCR)")
    otros_documentos: list[str] = Field(default_factory=list, description="Otros documentos vistos en el PDF")
    caracteres_leidos: int = 0
    categoria: Literal["forma_migratoria", "otro", "hoja_en_blanco"] | None = None
    documento_detectado: str | None = None


class ResultadoFM(BaseModel):
    id: str | None = None
    archivo: str | None = None
    estado: Literal["ok", "revisar", "error", "rechazado"]
    datos: DatosFM = Field(default_factory=DatosFM)
    confianza: dict[str, Confianza] = Field(default_factory=dict)
    campos_a_revisar: list[str] = Field(default_factory=list)
    validaciones: list[Validacion] = Field(default_factory=list)
    advertencias: list[str] = Field(default_factory=list)
    error: str | None = None
    error_codigo: int | None = None
    meta: Meta | None = None
    recortes: dict[str, str] | None = Field(None, description="PNG en base64 (sólo si se pide)")


class ExtraccionResumen(BaseModel):
    id: str
    creado: datetime
    archivo: str | None = None
    estado: str
    curp: str | None = None
    nue: str | None = None
    nombre_completo: str | None = None
    campos_a_revisar: list[str] = Field(default_factory=list)
    tiempo_ms: int | None = None


class ListaExtracciones(BaseModel):
    total: int
    elementos: list[ExtraccionResumen]


class ExtraccionDetalle(ExtraccionResumen):
    resultado: dict[str, Any]
    datos_corregidos: dict[str, Any] | None = None
    revisado_por: str | None = None
    revisado_en: datetime | None = None


class Revision(BaseModel):
    datos: dict[str, Any]
    revisado_por: str | None = None
