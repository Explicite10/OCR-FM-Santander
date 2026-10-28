# Prompt para implementar el cliente de la API OCR de formas migratorias INM (Open Source)

Copia todo el bloque en un asistente de IA y cambia el lenguaje y framework en la primera línea.

```text
Actúa como desarrollador senior. Implementa en [LENGUAJE / FRAMEWORK] un cliente para la API
"OCR de Formas Migratorias INM (Open Source)" siguiendo EXACTAMENTE este contrato. Entrega: módulo
cliente, modelos tipados de la respuesta, manejo de errores y reintentos, y un ejemplo de uso.

== QUÉ HACE LA API ==
Recibe un expediente escaneado en PDF y devuelve en JSON los datos de la tarjeta de residente del
INM (México): RESIDENTE TEMPORAL, RESIDENTE PERMANENTE o INMIGRADO (formato antiguo). Ignora
cualquier otro documento del archivo (pasaporte, INE, etc.) y lo reporta en clasificacion.
Todo corre en el servidor de la empresa (PaddleOCR + Qwen3-VL), sin servicios externos.

== PETICIÓN ==
POST http://172.10.30.17:18475/forma-migratoria
Header obligatorio: X-API-Key: <clave>   (leerla de una variable de entorno OCR_INM_API_KEY;
                                           nunca escribirla en el código)
Body: multipart/form-data con UN archivo PDF en el campo "file" (content-type application/pdf).
Campos de texto OPCIONALES en el mismo formulario (datos capturados en la solicitud), para que la
API responda las validaciones del plan de atención:
  nombre (completo, cualquier orden)  -- o bien: apellido_paterno, apellido_materno, nombres
  curp (18 chars, solo si existe) · fecha_nacimiento (AAAA-MM-DD o DD/MM/AAAA)
  nacionalidad (gentilicio "Colombiana", país "Colombia" o ISO "COL")
Solo PDF (imagen u otro formato responde 400). Tamaño máximo 25 MB (413). Máximo 30 páginas (224);
la tarjeta debe estar en las primeras 6. Frente y reverso en el mismo archivo.
Timeout del cliente: 120 s. La API tarda 15-25 s por expediente y procesa 2 a la vez; las demás
esperan turno. En cargas masivas, enviar como máximo 2 peticiones en paralelo.
GET /health (sin API key) devuelve {"status":"ok"|"degradado", "vlm": bool, ...} para monitoreo.

== RESPUESTA: SIEMPRE ESTE SOBRE JSON ==
{
  "codigo": int,          // decide con ESTE campo, no con el estado HTTP
  "estado": str,          // nombre fijo del código
  "mensaje": str,         // texto para humanos
  "id": str,              // solo si el servidor guarda historial (opcional)
  "datos": {...},         // solo códigos 200, 210, 211, 212
  "mrz": {...},           // solo 200-212
  "validacion": {"ok": bool, "completo": bool, "coincidencias": [str],
                 "discrepancias": [str], "sin_verificar": [str]},   // solo 200-212
  "avisos": [str],        // solo 200-212
  "clasificacion": {"categoria": "forma_migratoria"|"otro"|"hoja_en_blanco",
                    "confianza": null, "caracteres_leidos": int, "senales": [str],
                    "otros_documentos": [str], "motivo": str, "documento_detectado": str},
  "confianza": {"<campo>": "alta"|"media"|"baja"},   // solo 200-212
  "meta": {"tiempo_total_ms": int, "tiempos_ms": {...}, "paginas": int,
           "paginas_forma_migratoria": [int], "paginas_ignoradas": [int], "motor": "paddleocr+vlm",
           "version_modelo": str, "pagina_anverso": int, "pagina_reverso": int,
           "recorte_anverso": str, "recorte_reverso": str, "mrz_fuente": "texto"|"entidad"},
  "validacion_plan": {    // códigos 200-221: plan de atención, sección Forma Migratoria
    "cumple": bool,       // true solo si las 8 validaciones pasan
    "mensaje": str,       // "Documento válido: ..." o "Revisar documento y motivo de rechazo"
    "motivos_rechazo": [str],
    "regla_vigencia": "anio"|"fecha",
    "validaciones": [{"id": str, "pregunta": str, "resultado": "SI"|"NO"|"NO_APLICA"|"NO_VERIFICADO",
                      "ok": bool, "detalle": str}]   // 8 elementos, en este orden:
      // hoja_en_blanco (pasa con NO), imagen_ilegible (pasa con NO), es_forma_migratoria,
      // vigente, nombre_coincide, curp_coincide (NO_APLICA no bloquea),
      // fecha_nacimiento_coincide, nacionalidad_coincide
  }
}
REGLA: si un dato no se pudo leer, la LLAVE NO APARECE (no viene null). Todos los campos de
"datos", "mrz", "confianza", "clasificacion" y "meta" deben modelarse como OPCIONALES.

== CAMPOS DE "datos" ==
tipo_documento (str: "RESIDENTE TEMPORAL" | "RESIDENTE PERMANENTE" | "INMIGRADO")
nue (str, 13 dígitos) · apellidos (str) · nombres (str) · nombre_completo (str)
nacionalidad (str, gentilicio: "COLOMBIANA"; en tarjetas antiguas puede ser código "HTI")
pais (str, ISO alfa-3: "COL") · sexo (str: "H" = hombre, "M" = mujer)
fecha_nacimiento (str "AAAA-MM-DD") · curp (str, 18 chars)
permiso_para_trabajar (bool: true o false)
fecha_expedicion ("AAAA-MM-DD") · fecha_vencimiento ("AAAA-MM-DD"; NO existe en permanentes)
vigente (bool) · numero_documento (str) · numero_segob_inm (str)
impreso_en (str: oficina y fecha, "OR CIUDAD DE MEXICO, 15/01/2025") · pais_emisor (str, siempre "MEX")

== CAMPOS DE "mrz" ==
lineas ([str] x3), tipo_documento, pais_emisor, numero_documento, fecha_nacimiento,
sexo ("M" | "F" -- convención internacional, distinta de datos.sexo),
fecha_expedicion, sin_fecha_expedicion (bool), nacionalidad, apellidos, nombres,
digitos_control {numero_documento: bool, fecha_nacimiento: bool,
                 fecha_expedicion: bool|null, compuesto: bool},
integra (bool), origen ("texto"|"entidad").
Si no se pudo leer la MRZ el bloque es solo {"error": str, "texto_crudo": str (opcional)}.

== CÓDIGOS Y ACCIÓN ==
Viajan con HTTP 200 (la petición fue válida):
 200 PROCESADO                    -> ACEPTAR: usar datos directo.
 211 PROCESADO_CON_AVISOS         -> ACEPTAR_CON_REVISION: mostrar "avisos".
 212 PROCESADO_INCOMPLETO         -> ACEPTAR_CON_REVISION: mostrar validacion.sin_verificar.
 210 PROCESADO_CON_DISCREPANCIAS  -> REVISION_OBLIGATORIA: mostrar validacion.discrepancias;
                                     no usar los datos sin revisión humana.
 220 NO_ES_FORMA_MIGRATORIA       -> DOCUMENTO_INCORRECTO (sin datos).
 221 HOJA_EN_BLANCO               -> DOCUMENTO_INCORRECTO (reescanear).
 222 ARCHIVO_CORRUPTO             -> ARCHIVO_INVALIDO.
 223 PDF_PROTEGIDO                -> ARCHIVO_INVALIDO (quitar contraseña).
 224 LIMITE_PAGINAS               -> ARCHIVO_INVALIDO (más de 30 páginas: enviar solo la tarjeta).
Viajan con su mismo estado HTTP:
 400 ARCHIVO_NO_SOPORTADO, 413 ARCHIVO_DEMASIADO_GRANDE, 422 PETICION_INVALIDA -> ARCHIVO_INVALIDO
 401 NO_AUTORIZADO, 404 NO_ENCONTRADO, 405 METODO_NO_PERMITIDO               -> ERROR_CONFIGURACION
 500 ERROR_INTERNO, 502 ERROR_MODELO_VISION, 503 SERVICIO_NO_DISPONIBLE       -> REINTENTAR
Cualquier código desconocido -> tratar como REINTENTAR y registrarlo.

== REINTENTOS ==
Reintentar SOLO 500, 502, 503, errores de conexión y timeouts: máximo 3 intentos con espera
de 2 s, 4 s y 8 s. Nunca reintentar 4xx ni 210-224.

== DECISIÓN CON EL PLAN DE ATENCIÓN ==
Si existe "validacion_plan": cumple=true -> APROBADO; cumple=false -> REVISAR y mostrar
"motivos_rechazo". Si no existe (errores técnicos), decidir con la tabla de códigos de arriba.
"codigo" habla de la calidad de la extracción; "validacion_plan.cumple" de si el documento
coincide con la solicitud y está vigente. Son independientes.

== REQUISITOS DE IMPLEMENTACIÓN ==
1. Función principal: extraer(archivo_pdf, solicitud opcional) -> resultado tipado con: codigo,
   estado, mensaje, accion (enum de las acciones de arriba), cumple_plan, motivos_rechazo,
   datos (opcional), avisos, discrepancias, sin_verificar y el JSON crudo completo.
2. Leer SIEMPRE el JSON aunque el HTTP sea 4xx/5xx (también trae el sobre).
3. Si la respuesta no es JSON (caída del servidor, proxy), devolver accion=REINTENTAR.
4. No registrar en logs nombres, CURP, NUE ni el contenido de "datos" (datos personales).
5. API key, URL y timeout configurables por variables de entorno.
6. Incluir pruebas unitarias con respuestas simuladas para 200, 210, 211, 220, 401 y 502,
   y para validacion_plan con cumple=true y cumple=false.

== EJEMPLO DE RESPUESTA 200 (datos ficticios, extracto) ==
{"codigo":200,"estado":"PROCESADO","mensaje":"El documento se procesó y todas las comprobaciones cuadraron.",
 "datos":{"tipo_documento":"RESIDENTE TEMPORAL","nue":"0000001234567","apellidos":"PEREZ GOMEZ",
  "nombres":"MARIA FERNANDA","nombre_completo":"PEREZ GOMEZ MARIA FERNANDA","nacionalidad":"COLOMBIANA",
  "pais":"COL","sexo":"M","fecha_nacimiento":"1990-06-09","curp":"PEGF900609MNERMR07",
  "permiso_para_trabajar":true,"fecha_expedicion":"2025-01-13","fecha_vencimiento":"2027-01-12",
  "vigente":true,"numero_documento":"12345678","numero_segob_inm":"SEGOB-INM-00123456",
  "impreso_en":"OR CIUDAD DE MEXICO, 15/01/2025","pais_emisor":"MEX"},
 "validacion":{"ok":true,"completo":true,"coincidencias":["MRZ (dígitos de control)"],
  "discrepancias":[],"sin_verificar":[]},
 "avisos":[],"clasificacion":{"categoria":"forma_migratoria","confianza":null,"caracteres_leidos":812}}
```
