# Cómo comparar OCR-INM-OpenSource contra OCR-INM-DocumentAI y hacer que mejore

Las dos APIs responden el mismo JSON, así que se pueden medir con la misma vara. El método tiene tres niveles;
el primero no necesita a nadie etiquetando y ya encuentra la mayoría de los problemas.

## Nivel 1: acuerdo entre las dos APIs con la MRZ de árbitro (automático)

```bash
API_A_URL=http://localhost:18475 API_A_KEY=... API_B_URL=http://localhost:18476 API_B_KEY=... \
python -m scripts.comparar_apis lote/pdfs --salida lote/comparacion --concurrencia 2
```

- Corre las dos APIs sobre la misma carpeta (reanudable: guarda cada JSON) y produce `comparacion.md` (sin
  datos personales) y `comparacion.csv` (con los valores; se queda en el servidor).
- Por campo cuenta: igual, sólo A, sólo B, difieren. Cuando difieren, decide quién tiene razón con un
  **árbitro objetivo**: la MRZ cuando su dígito de control cuadra (número de documento, fecha de nacimiento,
  sexo, fecha de expedición, nacionalidad, apellidos/nombres) y el dígito verificador de la CURP.
- Lo que no tiene árbitro (NUE, SEGOB-INM, lugar de impresión, vencimiento) queda en la lista de "archivos con
  diferencias" para el nivel 2.

Qué mirar primero en `comparacion.md`:

1. **"sólo B"** alto en un campo = OpenSource no lo está extrayendo (así apareció `impreso_en`: el VLM sólo
   leía el reverso cuando la MRZ no cuadraba; ahora también sale del OCR).
2. **"B acierta"** alto = OpenSource lee mal (así aparecieron los nombres: el VLM cambia letras en nombres poco
   comunes; ahora la MRZ íntegra corrige ortografía y separación apellidos/nombres).
3. **Códigos**: muchos 210/212 en una API y 200 en la otra sobre los mismos PDFs señalan validaciones
   demasiado estrictas o datos que faltan, no necesariamente lecturas peores.

## Nivel 2: verdad humana sobre una muestra (30-50 documentos)

`scripts/evaluar.py plantilla` genera un CSV con lo que leyó el sistema; una persona corrige sólo lo que está mal
(abrirlo en Excel, marcar `verificado=si`). Luego `scripts/evaluar.py comparar` da la exactitud por campo y, lo
más útil, **la exactitud según la confianza que asignó la API**: `alta` debe andar en 100 %; si no, hay que
endurecer la regla que la otorga. Conviene elegir la muestra entre los archivos que el nivel 1 marcó con
diferencias: ahí está la información.

DocumentAI ya tiene su medición humana (`resultados/endpoint_vs_humano.json`: 30 documentos, 97.1 % por campo).
Con la misma muestra etiquetada se obtiene el número equivalente para OpenSource y la comparación queda cerrada.

## Nivel 3: el ciclo de mejora

1. Correr el nivel 1 con la versión actual (es la línea base: `lote/comparacion`).
2. Tomar el campo con más "sólo B" o "B acierta", abrir 3-5 de esos PDFs, entender la causa (recorte, OCR, VLM,
   fusión) y corregirla con una prueba unitaria con datos ficticios.
3. Volver a correr sólo OpenSource a otra carpeta (`--salida lote/comparacion_v2`; DocumentAI no cambia, se
   copian sus JSON) y comparar las dos corridas de OpenSource entre sí con `scripts/comparar_lotes.py`
   para confirmar que mejoró ese campo **sin empeorar los demás**.
4. Repetir. Cuando el nivel 1 ya no acusa diferencias sistemáticas, pasar al nivel 2 para el número final.

Reglas que han funcionado:

- **La MRZ con dígitos verificadores manda** sobre cualquier lectura visual (números, fechas, sexo,
  nacionalidad, ortografía de nombres). Sólo el vencimiento, el NUE, el SEGOB-INM y el lugar no están en la MRZ.
- **Dos fuentes independientes** (OCR y VLM) para cada campo; si coinciden, confianza alta; si no, baja y aviso.
- **Nunca inventar**: si un campo no se lee, no aparece. Un `212` honesto vale más que un `200` con un dato falso.
- **Datos ficticios en las pruebas**: los PDFs y los CSV con valores se quedan en el servidor.

## Resultado de la primera corrida (100 documentos, 27-oct-2026)

| Campo | igual | sólo OpenSource | sólo DocumentAI | difieren | árbitro: OpenSource | DocumentAI |
|---|---:|---:|---:|---:|---:|---:|
| curp | 73 | 4 | 0 | 15 | 15 | 0 |
| nombres | 84 | 4 | 0 | 6 | 5 | 5 |
| apellidos | 89 | 2 | 0 | 3 | 2 | 3 |
| fecha_expedicion | 79 | 4 | 8 | 0 | 1 | 0 |
| impreso_en | 15 | 5 | 59 | 4 | - | - |
| sexo | 88 | 4 | 0 | 2 | DocumentAI entrega "X" o vacío en hombres | |

Tiempos: OpenSource mediana 14.6 s (p90 40 s); DocumentAI 9.2 s (p90 12 s).

Mejoras aplicadas a partir de esto: `impreso_en` y `fecha_expedicion` también desde el OCR, nombres corregidos con
la MRZ íntegra (ortografía y orden apellidos/nombres), NUE con patrón `000000` + 7 dígitos.
