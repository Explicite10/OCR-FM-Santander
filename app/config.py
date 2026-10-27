from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración vía variables de entorno o archivo .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- VLM ---
    # "ollama" usa la API nativa de Ollama; "openai" cualquier servidor compatible (vLLM, LM Studio...).
    vlm_backend: Literal["ollama", "openai"] = "ollama"
    vlm_base_url: str = "http://localhost:11434"
    vlm_model: str = "qwen3-vl:8b-instruct"
    vlm_api_key: str = "EMPTY"
    vlm_timeout_s: float = 180.0
    vlm_max_side: int = 1600  # lado mayor (px) de la imagen que se manda al VLM
    vlm_max_retries: int = 2
    vlm_num_ctx: int = 8192
    vlm_think: bool | None = None  # False apaga el "razonamiento" en modelos que lo traen (Qwen3.5)
    vlm_enabled: bool = True
    # Sin anclas (tarjeta inclinada, chica o muy tenue): el VLM ubica la tarjeta y se repite el OCR ahí.
    vlm_localizador: bool = True
    vlm_locate_max_side: int = 1000

    # --- OCR ---
    ocr_det_model: str = "PP-OCRv5_mobile_det"
    ocr_rec_model: str = "PP-OCRv6_medium_rec"
    ocr_enabled: bool = True

    # --- Documento ---
    render_dpi: int = 250
    max_pages: int = 6  # páginas que se renderizan (la tarjeta suele venir en las primeras)
    max_paginas_documento: int = 30  # un PDF con más páginas se rechaza (código 224)
    max_upload_mb: int = 25
    solo_pdf: bool = True

    # --- Decisiones ---
    rechazar_no_fm: bool = True  # sin tarjeta INM reconocible → estado "rechazado" (código 220)
    # Plan de atención: "anio" (año de vigencia >= año actual, como pide el plan) o "fecha" (vencimiento >= hoy)
    regla_vigencia: Literal["anio", "fecha"] = "anio"
    # Si el modelo de visión falla al leer el anverso: 502 (igual que DocumentAI) en vez de responder sólo con OCR
    error_vlm_502: bool = True
    max_concurrent_jobs: int = 2

    # --- API ---
    api_key: str | None = None
    enable_docs: bool = True
    database_url: str | None = None
    guardar_resultados: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
