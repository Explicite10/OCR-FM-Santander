# Evaluación inicial (lote Santander de formas migratorias, 22-oct-2026)

## El lote

- 420 PDFs (`OneDrive_2_22-10-2026.zip`), todos escaneados (1 con capa de texto), 1-2 páginas en el 93 %
  (hasta 48 en un caso), carta/A4, fotocopias en blanco y negro con sello "cotejado contra original".
- La "forma migratoria" es la **tarjeta de residente del INM**: Residente Temporal (144 por texto OCR) o
  Residente Permanente (215), más 5 modelos antiguos "Inmigrado" (FM2). Anverso y reverso suelen venir en
  la misma página; en ~13 PDFs la tarjeta está girada 90°.
- Casi todos traen además otros documentos: pasaporte en 290 (MRZ TD3 legible), INE en 17, licencias,
  acreditaciones diplomáticas de la SRE, y hasta una solicitud de tarjeta de crédito.
- Nacionalidades más frecuentes (MRZ): COL 47, ESP 35, VEN 33, ARG 31, BRA 24, FRA 20, CUB 19, KOR 18, CHL 14, PER 12.

**Barrido con PaddleOCR sin giros ni VLM** (`~/fm/res/` en el servidor): la MRZ `I<MEX` aparece legible en
**370 docs (88 %)** y en **350 (83 %) cuadran los 4 dígitos verificadores** directamente del OCR. De los 50
sin MRZ, 7 traen señales de tarjeta INM (giradas o FM2 antigua) y 43 no muestran tarjeta en el OCR
(tarjeta de lado, sólo INE, sólo pasaporte...).

Hallazgos que cambiaron el diseño:
- El INM escribe la **fecha de expedición** en la posición que ICAO reserva al vencimiento (línea 2, pos. 9-15);
  en Residente Permanente va vacía. El vencimiento sólo está impreso en el anverso.
- El renglón 3 (nombres) de la MRZ no tiene dígito verificador y el OCR lo lee con espacios: se compara por
  prefijo/palabras contra el anverso, donde los apellidos van en MAYÚSCULAS y los nombres en Title case.
- Una INE sola se parece a la tarjeta (MRZ TD1 `IDMEX`, misma línea 2): se descarta por nacionalidad MEX.
- El dígito compuesto suele quedar tapado por el sello: si número y fechas cuadran, sólo se avisa (211).

## Opciones evaluadas (todas open source, GPU de 8 GB)

| Opción | Veredicto |
|---|---|
| **PaddleOCR (PP-OCRv5 det + v6 rec) + MRZ con dígitos verificadores** | Base del sistema: 83 % de las MRZ íntegras sin VLM, en CPU. Es lo que da la precisión "casi 100 %" en los campos con verificador. |
| **Qwen3-VL 8B instruct (Ollama)** para el anverso y rescate de MRZ | Elegido. Lee la tarjeta incluso a página completa y girada (~8 s/página); con recorte baja a ~5 s y deja de partir nombres. Mismo modelo que INE y pasaporte: un solo Ollama para los tres servicios. |
| Qwen3-VL 4B instruct | Probado (ver abajo): 13 % más rápido, lee peor los nombres. Descartado. |
| **PaddleOCR-VL-1.6 (0.9B, Apache 2.0)**, líder de OmniDocBench | Probado (ver abajo). La imagen oficial `sm120` no funciona en la RTX 5060 Ti (20 min sin terminar un recorte); vía llama.cpp (GGUF oficial) corre en ~1 s por recorte, pero **colapsa la franja MRZ** (sólo 4 de 60 reversos con MRZ íntegra, contra ~50 del PaddleOCR clásico), alucina texto en tibetano/chino y lee peor la CURP. Es un modelo de parseo de documentos largos, no de tarjetas con zonas de ancho fijo. Descartado. |
| Qwen3.5 9B | En pasaportes empató en calidad pero 35 % más lento y hay que apagar el "razonamiento". No aporta aquí. |
| GLM-OCR 0.9B | Rápido y chico pero mucho menos preciso en campos impresos y CURP (medido en pasaportes). Descartado. |
| PaddleOCR-VL / dots.ocr / MinerU | Pensados para documentos largos (layout, tablas); para una tarjeta con 12 campos no superan a un VLM con esquema JSON + validaciones. No se probaron. |
| Fine-tuning (LayoutLM / Donut / Qwen-VL LoRA) con los 420 docs | No hace falta: los campos críticos ya vienen respaldados por dígitos verificadores (MRZ, CURP) y el VLM genérico lee bien lo demás. Sólo tendría sentido con miles de ejemplos etiquetados y un formato que cambie poco. |
| Embeddings / RAG | No aplican a la extracción: no hay texto libre que buscar. La clasificación de documentos se resuelve con palabras clave y las MRZ. |
| Servicios de pago (Azure Document Intelligence, Google Document AI, Textract) | No se consideran: los datos no pueden salir del servidor y el objetivo es open source. |

## Lote completo, versión 1 (PaddleOCR + Qwen3-VL 8B) — 420 docs

| | |
|---|---|
| ok / revisar / rechazado / error | **351 (83.6 %)** / 35 (8.3 %) / 33 (7.9 %) / 1 (PDF de 48 páginas) |
| Sobre los 386 PDFs que sí traen tarjeta | **351 ok = 90.9 %** |
| Código 200 (todo cuadra) / 210 / 211 | 279 (66 %) / 42 (10 %) / 65 (16 %) |
| MRZ íntegra (todos los dígitos verificadores) | 364 (86.7 %) · 370 leídas por OCR, 17 rescatadas por el VLM |
| Recorte por ancla (anverso / reverso) | 385 / 382 · página completa 33 / 36 (casi todos los rechazados) |
| Confianza alta (de 386): número doc. / nacimiento / sexo / tipo / nombre / CURP / NUE | 384 / 384 / 383 / 383 / 375 / 370 / 311 |
| Tiempo (3 en paralelo, OCR en CPU, GPU 8 GB compartida) | mediana 24 s/doc (OCR 12.7 s, VLM anverso 5.9 s) |

Los 33 rechazos son correctos: 17 PDFs con sólo INE, 13 con sólo pasaporte, 2 acreditaciones SRE, 1 solicitud
bancaria. Las tarjetas giradas 90° (13) se resolvieron con los giros del OCR.

Qué causaba los 210/211 y se corrige en la v2:
- 45 `curp_vs_nombre`: el VLM pierde el primer apellido al separar apellidos/nombres → ahora manda el texto
  impreso (apellidos en MAYÚSCULAS, nombres en Title case); y faltaba la regla de palabras altisonantes del
  RENAPO (p. ej. CASAS GARCIA Andrés → CXGA, no CAGA).
- 10 `nombre_vs_mrz`: la MRZ del INM trunca cada palabra (JIMENEZ → JIMEN) u omite el segundo apellido →
  comparación palabra por palabra con prefijos.
- 27 `fecha_nacimiento_consistente`: en parte la MRZ "reparada" con el dígito verificador hacia una fecha que ni
  el anverso ni la CURP respaldan → ganan las dos fuentes que coinciden.
- 101 permanentes con vencimiento en `media`: la tarjeta imprime la etiqueta sin valor → `alta` cuando el tipo es
  Residente Permanente. 48 permanentes sin fecha de expedición: correcto, esa tarjeta no la imprime.
- `expedicion_antes_de_vencimiento`: un vencimiento igual o anterior a la expedición (respaldada por la MRZ) es
  lectura errónea del anverso → confianza baja en ese campo, no discrepancia del documento.

## Lote completo, versión 2 (mismo modelo, con los ajustes anteriores) — 420 docs

| | v1 | v2 |
|---|---|---|
| ok / revisar | 351 / 35 | **359 / 27** (93 % de los 386 con tarjeta) |
| Código 200 (todo cuadra) | 279 (66 %) | **310 (74 %)** |
| Código 210 (discrepancia real) | 42 (10 %) | **16 (3.8 %)** |
| Código 211 (avisos: la MRZ mandó sobre el anverso, compuesto tapado, iniciales de CURP...) | 65 | 60 |
| `curp_vs_nombre` / `nombre_vs_mrz` que fallan | 45 / 10 | 5 / 2 |
| Confianza alta: número doc. / nacimiento / sexo / nombre / CURP / vencimiento | 384 / 384 / 383 / 375 / 370 / 278 | 384 / 384 / 383 / **383** / 370 / **300** |

Lo que queda en 210 (16 docs) es sobre todo: CURP con 16-17 caracteres que ni el VLM ni el OCR completan (7),
fecha de nacimiento donde el anverso y la CURP contradicen a la MRZ (4) y 3 MRZ con número o fecha ilegibles.
Los 27 `revisar` son CURP ilegible (16), NUE que VLM y OCR leen con un dígito distinto (9, la NUE no trae
verificador) y 2 nombres que no cuadran con la MRZ. Son justo los candidatos a revisión humana.

**Siguientes pasos sugeridos**
1. Verdad de terreno: `python -m scripts.evaluar plantilla --resultados lote/resultados/resultados.csv --n 50`,
   corregir a mano y `comparar`, para confirmar que `alta` ≈ 100 % (como se hizo en INE).
2. Segunda lectura del VLM sobre recortes ampliados de la CURP y la NUE cuando VLM y OCR difieren (bajaría los
   16 + 9 `revisar`).
3. Velocidad: el OCR en CPU (12.9 s) es el cuello de botella con 3 en paralelo; PaddleOCR en GPU o 200 dpi.

## Qwen3-VL 8B vs 4B (mismos 40 docs, mismo pipeline v1)

| Modelo | ok / revisar / rechazado | MRZ íntegra | Conf. alta: nombres · CURP · NUE · nacionalidad | s/doc (mediana) |
|---|---|---|---|---|
| **qwen3-vl:8b-instruct** | **36 / 2 / 2** | 36 | 37 · 37 · 31 · 36 | 18.1 |
| qwen3-vl:4b-instruct | 35 / 3 / 2 | 36 | 35 · 37 · 34 · 35 | 15.7 |

Idénticos 24 de 40; el 4B cambia sobre todo apellidos/nombres (8) y SEGOB-INM (10). Es 13 % más rápido pero lee
peor los nombres. Como el 8B ya está cargado para INE y pasaporte, no hay ahorro real en usar el 4B: se queda el 8B.

## PaddleOCR-VL-1.6 (líder de OmniDocBench) sobre los mismos recortes

Cómo se corrió en el servidor (RTX 5060 Ti, Blackwell):
- Imagen oficial `paddleocr-vl:latest-nvidia-gpu-sm120`: carga el modelo en 3.5 min y después se queda 20 minutos
  en el primer recorte con la GPU al 0 % (los kernels no corren en sm120): inviable.
- GGUF oficial (`PaddlePaddle/PaddleOCR-VL-1.6-GGUF`) con `ghcr.io/ggml-org/llama.cpp:server-cuda`: carga en
  segundos, 2 GB de VRAM, ~1 s por recorte. Es la forma de usarlo si alguna vez hiciera falta.

| Prueba | PaddleOCR-VL-1.6 (llama.cpp) | Lo actual |
|---|---|---|
| MRZ íntegra en 60 reversos (pide "transcribe line by line") | **4** (colapsa `<<<<<` y pierde el largo de 30) | PaddleOCR clásico: ~50 directo del OCR; con el rescate del VLM 364/386 en el lote |
| Número + fecha de nacimiento válidos (60) | 35 | ~55 |
| CURP del anverso | mete espacios, confunde L con "I." y pierde un carácter de la fecha | Qwen3-VL: correcta y validada con dígito verificador |
| Pipeline completo (layout + VLM) | 3.4-12.7 s por recorte, bloques con texto en tibetano/chino alucinado | — |

Conclusión: PaddleOCR-VL es excelente para páginas de documento (texto corrido, tablas), pero para una tarjeta
con una zona de ancho fijo y códigos con verificador pierde contra PaddleOCR clásico + Qwen3-VL. No cambia nada
en los tres proyectos.
