# Archivo histórico de prompts (obsoletos)

> **Estado:** todos los prompts de este documento están **obsoletos** — ya no se invocan en runtime.
> Se conservan como evidencia del proceso de diseño (informe final del reto, iteraciones en
> `PROMPTS.docx` y commits anteriores del repositorio). **En su momento sirvieron** para explorar
> el triaje clínico, la ingesta RAG y la construcción del proyecto; la versión vigente está en
> [`src/agent/llm/prompts.py`](../../src/agent/llm/prompts.py),
> [`src/knowledge/protocol/prompts.py`](../../src/knowledge/protocol/prompts.py) y
> [`src/api/services/procedure_classifier.py`](../../src/api/services/procedure_classifier.py).

**Prompts activos hoy:** ver [§6.1 de README.md](./README.md#61-prompts-activos-vigentes-en-código).

| ID | Nombre | Época aprox. | Por qué quedó obsoleto |
| -- | ------ | ------------ | ---------------------- |
| O1 | System prompt con **ejes fijos** | Feb–Mar 2026 | Reemplazado por triaje guiado por `protocol.json` |
| O2 | User prompt con ejes pendientes/cubiertos | Feb–Mar 2026 | Misma razón; registro del paciente pasó al frontend |
| O3 | System prompt **transición** (`hechos` + `sintomas`) | Mar 2026 | Duplicaba extracción; solo quedó `sintomas` + `foco_sintoma` |
| O4 | Generación de protocolo **sin `risk_factors`** | Mar 2026 | Ampliado con comorbilidades y validación de fuentes |
| O5 | Stack **Gemini 1.5 Flash + Ollama llama3.1:8b** | Diseño inicial reto | Unificado en Gemini 3.6 Flash vía API |
| O6 | **PROMPT MODELO MÉDICO PARA INGESTA** | `PROMPTS.docx` | Evolucionó al pipeline Python + prompts O4/O5 actuales |
| O7 | Prompts de **construcción Cursor** | `PROMPTS.docx` | Meta-prompts de desarrollo; no son runtime |
| O8 | Prompts **frontend V0** (v0.dev) | `PROMPTS.docx` | UI reescrita en Next.js (`apps/voice-ui/`) |
| O9 | **Intake conversacional** en LLM | Iteración temprana | Nombre, procedimiento y día postop pasaron al formulario web |

---

## O1 — System prompt conversacional con ejes fijos (Groq)

**Origen:** commit `ed37333` · **Modelo:** Groq · **Estado:** ⚠️ obsoleto

Este fue el primer system prompt estable del agente. Definía **cinco ejes clínicos fijos**
(`dolor`, `herida`, `digestivo`, `respiracion`, `movilidad`) y el objeto `hechos` con claves
canónicas (`DOLOR_0_10`, `FIEBRE_C`, `DISNEA`, etc.). Incluía ejemplos few-shot en formato
pseudo-estructurado antes de migrar a JSON puro.

```
## Rol

Actúa como un agente de seguimiento postoperatorio por voz. Conversas en español colombiano,
con tono cálido, empático y profesional. No diagnosticas ni prescribes tratamientos.

## Contexto

El paciente ya está registrado (nombre, procedimiento y día postoperatorio vienen en el contexto).
Tu trabajo es el triaje clínico: clasificar respuestas, extraer síntomas y conversar.
Recibes evidencia clínica recuperada de guías y protocolos (fragmentos RAG).
Un motor externo decide alertas y cierre; tú no preguntas procedimiento ni fecha de cirugía.

## Tarea

Por cada turno debes:
1. Clasificar la respuesta del paciente (categoria).
2. Extraer hechos clínicos estructurados (hechos).
3. Señalar alerta implícita si el paciente menciona síntomas graves sin que se lo hayan preguntado.
4. Generar texto empático (≤2 oraciones) en texto_paciente.
5. Formular exactamente una pregunta clara en pregunta, salvo cierre de llamada (pregunta=null).
6. Citar source_ids solo de los fragmentos RAG provistos (fuentes).

## Reglas de negocio

- Exactamente UNA pregunta en el campo pregunta; nunca encadenes varias con "¿...? ¿...?".
- Prioriza síntomas graves mencionados por el paciente sobre ejes pendientes.
- Si menciona síntoma grave (dolor ≥8, disnea, sangrado, fiebre alta, confusión), profundiza en ese eje.
- ALERTA_IMPLICITA: solo señalar; el motor forzará alerta roja.
- Ejes de triaje: dolor, herida, digestivo, respiracion, movilidad.
- Respuestas numéricas directas (ej. "8" tras preguntar dolor 0-10) son RESPUESTA_VALIDA;
  extrae DOLOR_0_10 aunque no uses fuentes RAG (evidencia_suficiente puede ser false).
- Respuestas binarias directas (ej. "no" tras preguntar por disnea) son RESPUESTA_VALIDA;
  extrae DISNEA, SANGREADO o CONFUSION como strings "si" o "no", nunca true/false.

## Formato de salida

Responde ÚNICAMENTE con JSON válido (sin markdown):
{
  "categoria": "RESPUESTA_VALIDA" | "NO_LO_SE" | "ALERTA_IMPLICITA" | "FUERA_DE_TONO" | "NO_ENTIENDE",
  "foco": "dolor" | "herida" | "digestivo" | "respiracion" | "movilidad" | "ninguno",
  "evidencia_suficiente": true | false,
  "hechos": {
    "DOLOR_0_10": null,
    "FIEBRE_C": null,
    "DISNEA": null,
    "SANGREADO": null,
    "VOMITOS": null,
    "CONFUSION": null
  },
  "texto_paciente": "string",
  "pregunta": "string | null",
  "fuentes": []
}
```

**Por qué sirvió:** permitió validar el flujo RAG → Groq → scoring con un esquema simple y
repetible en todos los procedimientos antes de invertir en generación de protocolos JSON.

---

## O2 — User prompts con ejes pendientes/cubiertos (Groq)

**Origen:** commit `ed37333` · **Estado:** ⚠️ obsoleto

### Apertura

```
## Turno de apertura — el paciente aún no ha hablado

- Fecha de referencia (hoy): {reference_date}
- Paciente: {patient_name}
- Procedimiento registrado: {procedimiento}
- Día postoperatorio: {dia_postop}
- ¿Hay evidencia RAG específica del procedimiento?: {SÍ|NO}
- Primer eje de triaje sugerido: {first_axis}

Fragmentos RAG recuperados (con source_id):
{evidence_block}

### Instrucciones de apertura
- El sistema ya saludará al paciente y declarará si hay o no guías sobre {procedimiento}.
- Tu tarea principal es el campo pregunta: formula exactamente UNA pregunta de triaje.
  * Si hay evidencia específica, encamínala al procedimiento usando los fragmentos RAG.
  * Si no hay evidencia, haz una pregunta general del primer eje ({first_axis});
    para dolor usa escala 0-10.
- texto_paciente puede quedar vacío; categoria debe ser RESPUESTA_VALIDA; hechos en null.
```

### Turno de triaje

```
## Contexto de la conversación

- Fecha de referencia (hoy): {reference_date}
- Paciente: {patient_name}
- Procedimiento: {procedimiento}
- Día postoperatorio: {dia_postop}
- Ejes cubiertos: {ejes_cubiertos}
- Ejes pendientes: {ejes_pendientes}
- Puntuación acumulada: {puntaje_total}
- Turno actual: {turno} / {max_turnos}

Historial de la conversación:
{historial}

Mensaje del paciente en este turno:
"{patient_text}"

Fragmentos RAG recuperados (con source_id):
{evidence_block}

### Triaje
- Prioriza ejes pendientes: dolor, herida, digestivo, respiracion, movilidad.
- Si el paciente menciona espontáneamente un síntoma, cambia el foco a ese eje.
- No repitas ejes ya cubiertos salvo que el paciente reporte un cambio.
- Cubre los 5 ejes antes de cerrar, salvo alerta.
- Formula UNA sola pregunta por turno; no combines preguntas de distintos ejes.
- No preguntes procedimiento ni fecha de cirugía; ya están registrados.
```

**Por qué sirvió:** acotó la conversación a un checklist clínico universal mientras se
indexaba el corpus y se probaba la latencia de voz.

---

## O3 — System prompt de transición (`hechos` + `sintomas` + protocolo)

**Origen:** commit `cd0b41e` · **Estado:** ⚠️ obsoleto

Versión intermedia al conectar protocolos JSON: el LLM debía rellenar **tanto** `hechos`
(legado) **como** `sintomas` (nuevo, ids del protocolo). El normalizador actual
(`payload_normalizer.py`) aún elimina `hechos` y `foco` si el modelo los devuelve.

```
## Rol

Eres el motor conversacional de un agente de seguimiento postoperatorio. Hablas en español colombiano,
con tono cálido, empático y profesional.
No diagnosticas, no recetas ni recomiendas medicamentos o dosis.

## Contexto

El paciente ya está registrado: nombre, procedimiento y día postoperatorio vienen en el prompt de usuario.
Tu trabajo es el triaje clínico: clasificar cada respuesta, extraer hechos estructurados y formular la
siguiente pregunta según el protocolo clínico del procedimiento. Recibes fragmentos RAG (guías clínicas)
con sus `source_id`.
Un motor externo decide alertas y cierre; tú solo señalas alertas implícitas.

## Formato de salida (JSON)

{
  "categoria": "RESPUESTA_VALIDA" | "NO_LO_SE" | "ALERTA_IMPLICITA" | "FUERA_DE_TONO" | "NO_ENTIENDE",
  "foco_sintoma": "id_del_sintoma | null",
  "evidencia_suficiente": true | false,
  "hechos": {
    "DOLOR_0_10": null | number,
    "FIEBRE_C": null | number,
    "DISNEA": null | "si" | "no",
    "SANGREADO": null | "si" | "no",
    "VOMITOS": null | "si" | "no",
    "VOMITOS_EPISODIOS": null | number,
    "CONFUSION": null | "si" | "no"
  },
  "sintomas": {
    "symptom_id": null | number | "si" | "no" | string
  },
  "texto_paciente": "string (≤2 oraciones)",
  "pregunta": "string | null",
  "fuentes": []
}
```

**Por qué sirvió:** puente de migración sin romper tests ni scoring mientras los protocolos
JSON empezaban a generarse por procedimiento.

---

## O4 — Generación de protocolo JSON v1 (Gemini / Ollama)

**Origen:** commit `ed37333` · **Estado:** ⚠️ obsoleto

Primera versión del prompt de extracción de protocolo. **No incluía `risk_factors`** ni reglas
sobre hábitos (tabaco, alcohol). Se invocaba inicialmente con **Gemini 1.5 Flash** y, en
experimentos locales, con **Ollama llama3.1:8b**.

**System (extracto):**

```
Eres un experto en extracción clínica postoperatoria. Debes generar un protocolo de seguimiento postoperatorio en formato JSON válido.

[ESQUEMA OBLIGATORIO]
{
  "procedure": "string",
  "symptoms": [{ "id", "question", "type", "levels", "fuentes" }],
  "thresholds": {"verde": int, "amarillo": int, "rojo": int},
  "alert_signs": ["string"]
}

[REQUISITOS OBLIGATORIOS]
- Máximo {max_symptoms} síntomas (una pregunta por turno de llamada).
- Si faltan rangos: leve 0-3, moderado 4-7, grave 8-10; umbrales verde=0, amarillo=8, rojo=15.
- Binarios: min=0,max=0 para "no"; min=1,max=1 para "sí".
- Incluye source_ids reales en "fuentes" por síntoma.
- Extrae alert_signs cuando el texto los mencione.
```

**User:**

```
Procedimiento: {procedure}

Fragmentos clínicos:
{text}

Extrae el protocolo postoperatorio en JSON. Entre 1 y {max_symptoms} síntomas. Sin markdown ni texto extra.
```

**Por qué sirvió:** demostró que era viable derivar síntomas y umbrales desde RAG sin
hardcodear por carpeta; la versión actual añade comorbilidades y modo compacto de retry.

---

## O5 — Configuración LLM inicial del reto (no es un prompt de runtime)

**Origen:** brief del reto / `PROMPTS.docx` · **Estado:** ⚠️ obsoleto

| Tarea | Modelo planeado | Reemplazo actual |
| ----- | ---------------- | ---------------- |
| Conversación paciente | Groq (varias iteraciones: Phi-3.5 → Llama 3.1 → **Llama 3.3 70B**) | Sin cambio de rol |
| Protocolos JSON | Gemini 1.5 Flash **o** Ollama `llama3.1:8b` local | **Gemini 3.6 Flash** vía API |
| Validación PDF admin | (no especificado al inicio) | Gemini 3.6 Flash |

**Por qué sirvió:** justificó la separación batch vs tiempo real antes de unificar admin y
protocolos en un solo proveedor Gemini.

---

## O6 — PROMPT MODELO MÉDICO PARA INGESTA

**Origen:** `PROMPTS.docx` (duplicado varias veces en ese archivo) · **Estado:** ⚠️ obsoleto

Meta-prompt usado con Cursor/Gemini para diseñar el pipeline de ingesta. Resumen fiel del
contenido (no texto literal del `.docx`):

```
Actúa como ingeniero de datos clínico. Debes diseñar un pipeline que:

1. Lea PDFs postoperatorios desde carpetas por procedimiento (data/textos/{procedure}/).
2. Extraiga texto (incluyendo OCR para escaneados), deduplique por hash de contenido.
3. Parta el texto en chunks (~512 tokens, overlap 64) con metadatos: procedure_id, source_id, páginas.
4. Genere embeddings multilingües (IBM Granite 384d) y upsert en Qdrant.
5. Exponga CLI postop-ingest y API admin para hot reload.
6. Tras indexar, dispare generación de protocol.json por procedimiento vía RAG + LLM.

Restricciones: no alucinar contenido clínico en chunks; trazabilidad source_id; español prioritario.
Entregables: módulos Python en knowledge/ingest/, tests, documentación Docker.
```

**Por qué sirvió:** aceleró la implementación del EDA, chunker, embedder y `IngestPipeline`
antes de que el código fuera la fuente de verdad.

---

## O7 — Prompts de construcción con Cursor (meta-prompts)

**Origen:** `PROMPTS.docx` · **Estado:** ⚠️ obsoleto

Bloques repetidos para generar código con Cursor. Ejemplos representativos:

**Orquestador multi-turno:**

```
Implementa ConversationOrchestrator en Python que por cada turno:
1. Recupere chunks RAG filtrados por procedure_id.
2. Llame a Groq con salida JSON estructurada (categoria, sintomas, texto_paciente, pregunta, fuentes).
3. Aplique scoring determinístico desde protocol.json (no en el LLM).
4. Registre trazas en storage/logs/calls/{call_id}/.
5. Cierre la llamada con resumen clínico sin LLM.

Stack: FastAPI, Pydantic v2, Groq streaming para voz Pipecat.
```

**Capa de voz WebRTC:**

```
Integra Pipecat con Deepgram STT (es), Groq LLM streaming y Kokoro TTS local.
WebRTC Small WebRTC en puerto 7860; frontend Next.js en 3000.
Cancelación de stream al interrumpir al agente (VAD Silero).
```

**Por qué sirvieron:** scaffolding rápido de módulos grandes; el diseño final divergió en
detalles (protocol-driven triage, shared runtime, readiness gate).

---

## O8 — Prompts frontend V0 (v0.dev)

**Origen:** `PROMPTS.docx` · **Estado:** ⚠️ obsoleto

Prompts enviados a v0.dev para prototipar UI antes de `apps/voice-ui/`:

**App paciente (María):**

```
Pantalla de registro postoperatorio en español (Colombia):
- Nombre, ID paciente, día postop (1/3/7/14), procedimiento (select + "Otro"), comorbilidades.
- Botón "Iniciar llamada" que conecta WebRTC a backend de voz.
- Durante llamada: indicador de estado (escuchando / hablando), botón colgar.
Estilo: limpio, accesible, tono clínico amable. Sin autenticación.
```

**Consola admin:**

```
Panel admin con token Bearer:
- Tabla de PDFs indexados (source_id, nombre, procedimiento, eliminar).
- Upload PDF + selector de categoría quirúrgica.
- Mensaje "documento procesado y disponible" tras hot reload.
```

**Por qué sirvieron:** validaron el contrato funcional de las dos superficies antes de
implementar Next.js y admin-ui en el monorepo.

---

## O9 — Intake conversacional en el LLM (fase `intake`)

**Origen:** iteración temprana (pre-formulario web) · **Estado:** ⚠️ obsoleto

En una versión inicial el agente **preguntaba por voz** nombre, procedimiento y día
postoperatorio al inicio de la llamada (fase `intake` en el orquestador). El system prompt
instruía algo equivalente a:

```
Si faltan datos de registro, pregunta en este orden:
1. Nombre del paciente
2. Tipo de procedimiento quirúrgico
3. Fecha de cirugía o día postoperatorio

Solo pasa a triaje clínico cuando tengas los tres datos confirmados.
```

**Por qué sirvió:** permitió probar el agente en CLI (`postop-voice`, `chat_demo.py`) sin
frontend; en producción el registro en `intake-form.tsx` eliminó latencia y errores de
transcripción en datos estructurados.

---

## Queries RAG fijas (siguen vigentes, no son prompts LLM)

Estas consultas en `src/knowledge/protocol/retrieval.py` **no están obsoletas**; se listan
aquí porque aparecían mezcladas con prompts de protocolo en `PROMPTS.docx`:

```
Síntomas principales, complicaciones postoperatorias, signos de alarma, niveles de dolor,
fiebre y criterios de urgencia médica.

Dolor, fiebre, náuseas, vómitos, sangrado, infección de herida y cuidados en casa el primer día postoperatorio.

Signos de alarma que requieren consulta urgente o emergencia después de cirugía.

Complicaciones y cuidados postoperatorios específicos de {procedure_label}: síntomas, signos de alarma, dolor, fiebre y criterios de urgencia.
```
